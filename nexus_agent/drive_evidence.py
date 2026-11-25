"""Puts a day's test evidence into Google Drive, in one folder with a fixed layout:

    <evidence root>/Regression testing/Nexus Automated Test Evidence/<yyyy-mm-dd>/
        01 Test runs/<CASE> - <IPA>/   screenshots of every check (+ 'cleanup' for delete evidence)
        02 Bugs/                       evidence of the bugs logged that day (bugs.log_confirmed uploads here)
        03 Report/                     Automated test report <date>.pdf (the report as a self-contained PDF)

Nothing is overwritten or deleted: a screenshot goes up under '<HHMMSS>_<name>' (its time on disk) and a file that is already there is skipped;
only the report PDF is replaced in place, because it grows during the day."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from . import bugs as B
from .config import Config

log = logging.getLogger(__name__)
ROOT = ["Regression testing", "Nexus Automated Test Evidence"]
RUNS, BUGS, REPORT = "01 Test runs", "02 Bugs", "03 Report"


def _link(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


def _state(cfg: Config) -> Path:
    return cfg.state_dir / "drive_evidence.json"


def day_url(cfg: Config, date: str) -> str:
    try:
        return json.loads(_state(cfg).read_text()).get(date, "")
    except Exception:
        return ""


def _upload_version(drive, path: Path, folder: str, name: str) -> tuple[str, bool]:
    """Uploads `path` as `name`; returns (link, uploaded) - uploaded False when a file of that name was already there."""
    q = "name = '{}' and '{}' in parents and trashed = false".format(name.replace("\\", "\\\\").replace("'", "\\'"), folder)
    found = drive.files().list(q=q, fields="files(id)", pageSize=1, supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get("files", [])
    if found:
        return f"https://drive.google.com/file/d/{found[0]['id']}/view", False
    return B.drive_upload(drive, path, folder, name)[1], True


def report_pdf(cfg: Config, date: str) -> Path | None:
    """The day's HTML report rendered to a self-contained PDF (the HTML itself refers to screenshots by relative path)."""
    html = cfg.runs_dir / "_reports" / f"runreport_{date.replace('-', '')}.html"
    if not html.exists():
        return None
    from playwright.sync_api import sync_playwright
    out = cfg.runs_dir / "_reports" / f"Automated test report {date}.pdf"
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1300, "height": 900})
        pg.goto(html.resolve().as_uri())
        pg.wait_for_timeout(1500)
        pg.emulate_media(media="screen")
        pg.pdf(path=str(out), width="1300px", print_background=True, margin={"top": "10px", "bottom": "10px", "left": "10px", "right": "10px"})
        b.close()
    return out


def upload_day(cfg: Config, date: str | None = None, dry_run: bool = False, out=print) -> str:
    date = date or datetime.now().strftime("%Y-%m-%d")
    if cfg.unset(cfg.settings["bugsheet"].get("evidence_folder_id")):
        out(f"no Drive evidence folder for tenant '{cfg.tenant}' (bugsheet.evidence_folder_id): nothing uploaded")
        return ""
    day_dir = cfg.runs_dir / date
    from . import runreport as RR
    from .store import Store
    ipas = {c["case_id"]: c["ipa"] for c in RR.build(Store(cfg.state_dir / "agent.db"), cfg.runs_dir / "_reports", date)["cases"]}
    plan: list[tuple[str, Path, str]] = []          # (sub-folder path under the case folder, file, drive name)
    for case_dir in sorted(p for p in day_dir.iterdir() if p.is_dir() and not p.name.startswith("_")) if day_dir.is_dir() else []:
        label = f"{case_dir.name} - {ipas[case_dir.name].replace('/', '-')}" if case_dir.name in ipas else case_dir.name
        for f in sorted(case_dir.glob("*.png")):
            plan.append((label, f, f"{datetime.fromtimestamp(f.stat().st_mtime):%H%M%S}_{f.name}"))
        for f in sorted((case_dir / "cleanup").glob("*.png")):
            plan.append((f"{label}/cleanup", f, f.name))
    out(f"{date}: {len(plan)} screenshot(s) in {len({p[0].split('/')[0] for p in plan})} case folder(s) to upload" + (" (dry run, nothing uploaded)" if dry_run else ""))
    if dry_run:
        return ""
    drive = B.drive_service(cfg)
    day = B.ensure_folder_path(drive, cfg.settings["bugsheet"]["evidence_folder_id"], ROOT + [date])
    runs = B.ensure_folder_path(drive, day, [RUNS])
    B.ensure_folder_path(drive, day, [BUGS])
    rep = B.ensure_folder_path(drive, day, [REPORT])
    folders: dict[str, str] = {}
    up = skip = 0
    for sub, f, name in plan:
        if sub not in folders:
            folders[sub] = B.ensure_folder_path(drive, runs, sub.split("/"))
        _link_, done = _upload_version(drive, f, folders[sub], name)
        up += done
        skip += not done
    out(f"screenshots: {up} uploaded, {skip} already there")
    pdf = report_pdf(cfg, date)
    if pdf:
        from googleapiclient.http import MediaFileUpload
        found = drive.files().list(q=f"name = '{pdf.name}' and '{rep}' in parents and trashed = false", fields="files(id)", pageSize=1,
                                   supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get("files", [])
        if found:
            drive.files().update(fileId=found[0]["id"], media_body=MediaFileUpload(str(pdf)), supportsAllDrives=True).execute()
        else:
            drive.files().create(body={"name": pdf.name, "parents": [rep]}, media_body=MediaFileUpload(str(pdf)), fields="id", supportsAllDrives=True).execute()
        out(f"report: {pdf.name} {'updated' if found else 'uploaded'} in '{REPORT}'")
    else:
        out("report: no HTML report for this day yet (run ./nx runreport first)")
    url = _link(day)
    try:
        data = json.loads(_state(cfg).read_text())
    except Exception:
        data = {}
    data[date] = url
    _state(cfg).write_text(json.dumps(data, indent=1))
    out(f"Drive folder of {date}: {url}")
    return url


# --- automatic, never-stopping upload ---------------------------------------------------------------
AUTO_CMDS = {"suite", "validate", "validate-master", "validate-house", "validate-docs", "validate-mhfields", "validate-directbl",
             "validate-drafts", "runreport", "delete", "preflight", "run", "forward", "send-local"}


def days_to_upload(cfg: Config, today: str | None = None) -> list[str]:
    """Today, plus every earlier day that has screenshots and no recorded Drive folder (catch-up), plus the last 2 days again (files added after
    their last upload). Uploading is idempotent: files already in Drive are skipped."""
    today = today or datetime.now().strftime("%Y-%m-%d")
    try:
        done = json.loads(_state(cfg).read_text())
    except Exception:
        done = {}
    days = sorted(p.name for p in cfg.runs_dir.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name) and any(p.rglob("*.png")))
    recent = days[-3:]
    return sorted({d for d in days if d not in done} | set(recent) | {today}, reverse=True)


def auto_upload(cfg: Config, out=print, attempts: int = 4) -> int:
    """Uploads every day from days_to_upload. A failure (network, Drive quota, expired token) is retried with a growing pause and logged; it NEVER
    raises and never changes the exit code of a run. Returns the number of days that failed."""
    import fcntl
    import time
    lock = open(cfg.state_dir / "drive_upload.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        out("Drive upload: another upload is already running")
        return 0
    failed = 0
    for day in days_to_upload(cfg):
        for n in range(1, attempts + 1):
            try:
                upload_day(cfg, day, out=out)
                break
            except Exception as exc:
                out(f"Drive upload {day}: attempt {n}/{attempts} failed ({type(exc).__name__}: {str(exc).splitlines()[0][:120] if str(exc) else ''})")
                if n == attempts:
                    failed += 1
                else:
                    time.sleep(30 * n)
    return failed


def start_background(cfg: Config) -> None:
    """Fire and forget: a detached process runs the upload after the command that produced the evidence; the command never waits for it."""
    import subprocess
    import sys
    log = cfg.runs_dir / "_logs" / "drive_upload.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(log, "a") as fh:
            fh.write(f"\n--- {datetime.now():%Y-%m-%d %H:%M:%S} auto upload started ---\n")
            subprocess.Popen([sys.executable, "-m", "nexus_agent", "upload-evidence", "--auto"], stdout=fh, stderr=fh, stdin=subprocess.DEVNULL,
                             cwd=str(cfg.root) if hasattr(cfg, "root") else None, start_new_session=True)
    except Exception:
        pass
