"""Live status page for a run: everything the run prints or logs is also shown in a browser page that refreshes by itself.

`install()` is called once at the start of the long commands (suite, validate*). It
  - tees stdout/stderr and the logging output into runs/_live/live.log,
  - rebuilds runs/_live/index.html after every line (a table of the cases and their state, the checks as they finish, the log),
  - opens the page in the browser once per run.
Nothing here changes what the run does; if anything fails the run carries on without the page."""
from __future__ import annotations

import atexit
import html
import logging
import os
import re
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

CASE = re.compile(r"\b(REG-\d{3})\b")
FINAL = re.compile(r"^(REG-\d{3})\s+(SENT|PASS|FAIL|ERROR|SKIPPED|DRY_RUN|NOT_RECEIVED|REVIEW)\b\s*(.*)$")
CHECK = re.compile(r"^\s+([A-Z][A-Z /_]+?):\s+(PASS|FAIL|REVIEW|INFO|NOT_VERIFIABLE)\b(.*)$")
WAIT = re.compile(r"(REG-\d{3}): waiting (\d+)s for Nexus")
SENT = re.compile(r"Sent '(REG-\d{3}) \|")
NEXT_WAIT = re.compile(r"waiting (\d+)s before (?:the next email|case (REG-\d{3}))")
COLOUR = {"PASS": "#15803d", "FAIL": "#b91c1c", "ERROR": "#b91c1c", "NOT_RECEIVED": "#b91c1c", "REVIEW": "#b45309",
          "SENT": "#1d4ed8", "SKIPPED": "#6b7280", "DRY_RUN": "#6b7280", "INFO": "#6b7280", "NOT_VERIFIABLE": "#6b7280"}


class Live:
    def __init__(self, folder: Path, title: str):
        self.dir = folder
        self.title = title
        self.started = datetime.now()
        self.lines: list[str] = []
        self.cases: dict[str, dict] = {}
        self.current: str | None = None
        self.done = False
        self.lock = threading.Lock()
        folder.mkdir(parents=True, exist_ok=True)
        self.log = open(folder / "live.log", "a", encoding="utf-8")
        self.log.write(f"\n===== {title} · started {self.started:%Y-%m-%d %H:%M:%S} =====\n")

    # --- reading the lines -------------------------------------------------------------------
    def _case(self, cid: str) -> dict:
        return self.cases.setdefault(cid, {"state": "queued", "detail": "", "sent": 0, "checks": []})

    def feed(self, line: str) -> None:
        line = line.rstrip("\n")
        if not line.strip():
            return
        with self.lock:
            stamp = f"{datetime.now():%H:%M:%S}"
            self.lines.append(f"{stamp}  {line}")
            self.lines = self.lines[-500:]
            try:
                self.log.write(f"{stamp}  {line}\n")
                self.log.flush()
            except Exception:
                pass
            self._parse(line)
            self._render()

    def _parse(self, line: str) -> None:
        was = self.current
        self._parse_line(line)
        if was and self.current and was != self.current and self.cases.get(was, {}).get("state") in ("waiting for Nexus", "validating", "sending"):
            self.cases[was]["state"] = "sent"                       # the run moved on (individual cases are validated separately)
            self.cases[was]["detail"] = "sent; the check follows in the final summary or with ./nx validate"

    def _parse_line(self, line: str) -> None:
        if m := SENT.search(line):
            c = self._case(m.group(1)); c["sent"] += 1; c["state"] = "sending"; c["detail"] = f"{c['sent']} email(s) sent"
            self.current = m.group(1)
        elif m := WAIT.search(line):
            c = self._case(m.group(1)); c["state"] = "waiting for Nexus"; c["detail"] = f"{m.group(2)} s left before the first look"
            self.current = m.group(1)
        elif "validating in Nexus" in line and (m := CASE.search(line)):
            c = self._case(m.group(1)); c["state"] = "validating"; c["detail"] = "reading the Nexus pre-alert"
            self.current = m.group(1)
        elif m := FINAL.match(line):
            c = self._case(m.group(1)); c["state"] = m.group(2); c["detail"] = m.group(3).strip()[:160]
            c["checks"] = []                                  # a new verdict block starts: the checks that follow belong to it
            self.current = m.group(1)
        elif (m := CHECK.match(line)) and self.current:
            self._case(self.current)["checks"].append((m.group(1).strip(), m.group(2), m.group(3).strip()[:140]))
        elif m := CASE.search(line):
            if "waiting" in line and "before case" in line:
                self._case(m.group(1))

    # --- the page ----------------------------------------------------------------------------
    def _render(self) -> None:
        try:
            esc = html.escape
            rows = ""
            for cid, c in self.cases.items():
                col = COLOUR.get(c["state"], "#1d4ed8")
                checks = " ".join(
                    f'<span class="chip" style="border-color:{COLOUR.get(v, "#6b7280")};color:{COLOUR.get(v, "#6b7280")}">{esc(n)} {esc(v)}</span>'
                    for n, v, _d in c["checks"])
                rows += (f'<tr><td><b>{cid}</b></td><td style="color:{col};font-weight:600">{esc(c["state"])}</td>'
                         f'<td>{esc(c["detail"])}</td><td>{checks}</td></tr>')
            last = self.lines[-1] if self.lines else ""
            log = "\n".join(esc(x) for x in reversed(self.lines[-120:]))
            state = "FINISHED" if self.done else "RUNNING"
            refresh = "" if self.done else '<meta http-equiv="refresh" content="3">'
            page = (f'<!doctype html><meta charset=utf-8>{refresh}<title>Live run · {esc(self.title)}</title>'
                    "<style>body{font:15px system-ui;margin:24px;background:#f5f6f8;color:#1c2330}h1{font-size:20px;margin:0 0 4px}"
                    ".s{color:#6b7280;margin:0 0 16px}table{border-collapse:collapse;width:100%;background:#fff}"
                    "td,th{border:1px solid #d9dde3;padding:8px 10px;text-align:left;vertical-align:top}th{background:#eef0f3}"
                    ".chip{display:inline-block;border:1px solid;border-radius:10px;padding:1px 8px;margin:2px 4px 2px 0;font-size:12px}"
                    "pre{background:#0f172a;color:#e2e8f0;padding:12px;border-radius:8px;max-height:420px;overflow:auto;font-size:12px}"
                    ".now{background:#fff;border:1px solid #d9dde3;border-radius:8px;padding:10px 14px;margin:0 0 16px}</style>"
                    f'<h1>{esc(self.title)} · {state}</h1><p class="s">Started {self.started:%H:%M:%S}, updated {datetime.now():%H:%M:%S}. '
                    "This page refreshes by itself every 3 seconds while the run is going.</p>"
                    f'<div class="now"><b>Now:</b> {esc(last)}</div>'
                    "<table><tr><th>Case</th><th>State</th><th>Detail</th><th>Checks</th></tr>" + rows + "</table>"
                    f"<h3>Log (newest first)</h3><pre>{log}</pre>")
            (self.dir / "index.html").write_text(page, encoding="utf-8")
        except Exception:
            pass

    def finish(self) -> None:
        self.done = True
        with self.lock:
            self.lines.append(f"{datetime.now():%H:%M:%S}  --- run finished ---")
            self._render()
            try:
                self.log.write("===== finished =====\n"); self.log.close()
            except Exception:
                pass


class _Tee:
    def __init__(self, real, live: Live):
        self.real, self.live, self.buf = real, live, ""

    def write(self, s):
        n = self.real.write(s)
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.live.feed(line)
        return n

    def flush(self):
        self.real.flush()

    def __getattr__(self, name):
        return getattr(self.real, name)


class _Handler(logging.Handler):
    def __init__(self, live: Live):
        super().__init__(logging.INFO)
        self.live = live

    def emit(self, record):
        try:
            if record.name.startswith("nexus_agent"):
                self.live.feed(f"{record.levelname} {record.name.split('.')[-1]}: {record.getMessage()}")
        except Exception:
            pass


def install(runs_dir: Path, title: str, open_browser: bool = True) -> Live | None:
    """Start the live page for this process. Returns None (and the run carries on) if it cannot be set up."""
    try:
        live = Live(Path(runs_dir) / "_live", title)
        sys.stdout = _Tee(sys.stdout, live)
        logging.getLogger().addHandler(_Handler(live))
        atexit.register(live.finish)
        live.feed(f"live page: {live.dir / 'index.html'}")
        if open_browser and not os.getenv("NEXUS_LIVE_NO_OPEN"):
            webbrowser.open((live.dir / "index.html").resolve().as_uri())
        return live
    except Exception:
        return None
