"""Report for ONE day's run: what was observed, which bugs the run found, and which earlier raised bugs did not show this time.
Built from the day's validate / data CSVs in runs/_reports and from the bug history, so earlier days never leak in."""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .store import Store

DATA_FILES = {"Master": "master_data", "House": "house_data", "Manifest": "manifest_data", "Invoice": "invoice_data",
              "Packing List": "packing_data", "Debit Note": "debitnote_data", "Shipper Document": "shipperdoc_data"}


def _rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _stamp(path: Path) -> str:
    return path.stem.split("_", 1)[1] if "_" in path.stem else path.stem        # "<yyyymmdd>_<hhmmss>"


def _sheet_row(note: str) -> str:
    m = re.search(r"!A(\d+):|row (\d+)", note or "")
    return (m.group(1) or m.group(2)) if m else ""


def sheet_retested(cfg, rows: list[str]) -> dict[str, bool]:
    """Read-only look at the bug sheet: row -> True when it already has a Re-test status or a Fixed status (so it is not reported again).
    Returns {} when the sheet cannot be read; the report then lists every passed bug and says so."""
    if not rows:
        return {}
    try:
        from . import bugs as B
        st = B.sheet_state(cfg)
        header = st["header"]
        i_status, i_retest = header.index("Status"), header.index("Re-test status")
        svc = B.sheets_service(cfg)
        sid, tab = cfg.settings["bugsheet"]["spreadsheet_id"], st["tab_name"]
        got = svc.spreadsheets().values().batchGet(spreadsheetId=sid, ranges=[f"'{tab}'!A{r}:P{r}" for r in rows]).execute()
        out = {}
        for r, vr in zip(rows, got.get("valueRanges", [])):
            v = (vr.get("values") or [[]])[0]
            cell = lambda i: (v[i] if i < len(v) else "").strip()
            out[r] = bool(cell(i_retest)) or "fixed" in cell(i_status).lower()
        return out
    except Exception:
        return {}


def dev_completed_to_retest(cfg) -> list[dict] | None:
    """Read-only: sheet rows whose Status is "Development Completed" and whose Re-test status is blank. Those are always re-tested.
    None when the sheet cannot be read."""
    try:
        from . import bugs as B
        st = B.sheet_state(cfg)
        svc = B.sheets_service(cfg)
        got = svc.spreadsheets().values().get(spreadsheetId=cfg.settings["bugsheet"]["spreadsheet_id"],
                                              range=f"'{st['tab_name']}'!A1:P1000").execute().get("values", [])
        ix = {n.strip(): i for i, n in enumerate(got[0])}
        cell = lambda r, n: (r[ix[n]] if ix[n] < len(r) else "").strip()
        return [{"row": str(n), "job": cell(r, "Job Number"), "file": cell(r, "File Name").split("\n")[0]}
                for n, r in enumerate(got, 1) if n > 1 and cell(r, "Status") == "Development Completed" and not cell(r, "Re-test status")]
    except Exception:
        return None


def build(store: Store, reports: Path, date: str, retested: dict[str, bool] | None = None) -> dict:
    day = date.replace("-", "")
    validates = sorted(reports.glob(f"validate_{day}_*.csv"), key=_stamp)
    current: dict[str, dict] = {}                         # latest check per case where the pre-alert exists in Nexus
    for f in validates:
        for r in _rows(f):
            if r.get("nexus_status") == "CREATED_IN_NEXUS":
                current[r["case_id"]] = r
    sent: dict[str, int] = defaultdict(int)
    for f in sorted(reports.glob(f"suite_{day}_*.csv"), key=_stamp):
        for r in _rows(f):
            if r.get("status") == "SENT":
                sent[r["case_id"]] += 1
    ipas = {r["ipa"]: cid for cid, r in current.items()}

    data: dict[str, list[dict]] = defaultdict(list)        # data rows of today's current pre-alerts, per document
    for doc, prefix in DATA_FILES.items():
        for f in sorted(reports.glob(f"{prefix}_{day}_*.csv"), key=_stamp):
            for r in _rows(f):
                if r["ipa"] in ipas:
                    data[doc].append(r)
    latest_data: dict[tuple, dict] = {}                    # newest check of a field per pre-alert
    for doc, rows in data.items():
        for r in rows:
            latest_data[(doc, r["ipa"], r["field"])] = r

    cases = []
    for cid, r in sorted(current.items()):
        parts = [p.strip() for p in (r.get("details") or "").split(" | ")]
        causes = [p[len("PROBABLE ROOT CAUSE:"):].strip() for p in parts if p.startswith("PROBABLE ROOT CAUSE:")]
        mapping = [p for p in parts if re.match(r"^[A-Z ]+: (PASS|FAIL|REVIEW)", p)]
        seen = next((p for p in parts if p.startswith("IPA/")), "")
        others = next((p for p in parts if p.startswith("also in Others")), "")
        counts = {}
        for (doc, ipa, _f), x in latest_data.items():
            if ipa == r["ipa"]:
                c = counts.setdefault(doc, defaultdict(int))
                c[x["result"]] += 1
        findings = [{"document": doc, "field": x.get("field", ""), "doc": x.get("expected_from_document", ""), "nexus": x.get("shown_in_nexus", ""),
                     "result": x["result"], "note": x.get("note", ""), "source": x.get("source", "")}
                    for (doc, ipa, _f), x in latest_data.items() if ipa == r["ipa"] and x["result"] in ("FAIL", "REVIEW", "KNOWN", "NOT_VERIFIABLE")]
        cases.append({"case_id": cid, "ipa": r["ipa"], "verdict": r["verdict"], "after": r.get("appeared_after_s", ""), "mapping": mapping,
                      "causes": causes, "seen": seen, "others": others, "counts": counts, "findings": findings})

    # today's occurrences of bugs (from the bug history), joined with the bug table
    bugs = {b["fingerprint"]: b for st in ("PENDING", "APPROVED", "LOGGED", "NOT_A_BUG") for b in store.bugs_by_status(st)}
    hist = store.history_rows()
    first_day = {}
    for h in hist:
        first_day.setdefault(h["fingerprint"], h["seen_at"][:10])
    today: dict[str, dict] = {}
    for h in hist:
        if h["seen_at"][:10] != date or h["ipa"] not in ipas:
            continue
        cur = [m.split(":")[0] for c in cases if c["ipa"] == h["ipa"] for m in c["mapping"] if not re.match(r"^[A-Z ]+: PASS", m)]
        if h["document"] == "Mapping":                      # only what the LATEST check of this pre-alert still shows (Nexus may still have been linking)
            if h["field"] not in cur:
                continue
        elif h["document"] in DATA_FILES and latest_data.get((h["document"], h["ipa"], h["field"]), {}).get("result", "") == "PASS":
            continue
        b = bugs.get(h["fingerprint"], {})
        today[h["fingerprint"]] = {"case_id": h["case_id"], "document": h["document"], "field": h["field"], "ipa": h["ipa"],
                                   "status": b.get("status", "?"), "row": _sheet_row(b.get("note", "")),
                                   "first": first_day[h["fingerprint"]]}
    new = [x for x in today.values() if x["status"] in ("PENDING", "?")]
    still = [x for x in today.values() if x["status"] in ("LOGGED", "APPROVED")]
    accepted = [x for x in today.values() if x["status"] == "NOT_A_BUG"]

    # previously raised (logged) bugs that did not show in this run
    passed, not_tested, already = [], [], 0
    for fp, b in bugs.items():
        if b["status"] != "LOGGED" or fp in today:
            continue
        cid, doc = b["case_id"], b["document"]
        item = {"case_id": cid, "document": doc, "field": b["field"], "row": _sheet_row(b.get("note", ""))}
        if cid not in current:
            not_tested.append({**item, "why": "sent, not validated" if cid in sent else "not run today"})
        elif doc == "Mapping" or any(k[0] == doc and ipas.get(k[1]) == cid for k in latest_data):
            if retested and retested.get(item["row"]):          # already re-tested / Fixed in the sheet: nothing new to say
                already += 1
                continue
            passed.append({**item, "ipa": current[cid]["ipa"]})
        else:
            not_tested.append({**item, "why": f"{doc} data was not checked today"})
    return {"date": date, "cases": cases, "sent": dict(sent), "new": new, "still": still, "accepted": accepted,
            "passed": sorted(passed, key=lambda x: x["row"] or "0"), "not_tested": not_tested, "already": already,
            "sheet_read": retested is not None and bool(retested)}


def _line(x: dict) -> str:
    return f"{x['case_id']} · {x['document']} · {x['field']} ({x['ipa']})" if "ipa" in x else f"{x['case_id']} · {x['document']} · {x['field']}"


def report(d: dict) -> str:
    out = [f"RUN REPORT {d['date']}  (today's run only)", ""]
    out.append("OBSERVATIONS")
    if not d["cases"]:
        out.append("  No pre-alert from today's run was found in Nexus yet.")
    for c in d["cases"]:
        out.append(f"  {c['case_id']}  {c['verdict']}  {c['ipa']}" + (f"  (appeared after {c['after']} s)" if c["after"] else ""))
        bad = [p for p in c["mapping"] if not re.match(r"^[A-Z ]+: PASS", p)]
        out.append("      Mapping: " + ("all documents placed correctly" if not bad else "; ".join(bad)))
        if c["seen"]:
            out.append("      Nexus holds: " + c["seen"].replace(c["ipa"] + " seen -> ", ""))
        if c["others"]:
            out.append("      " + c["others"])
        for cause in c["causes"]:
            out.append("      Root cause: " + cause)
        if c["counts"]:
            data = [f"{doc} " + ", ".join(f"{k} {v}" for k, v in sorted(cnt.items()) if k in ("PASS", "FAIL", "REVIEW", "KNOWN"))
                    for doc, cnt in c["counts"].items() if any(k in ("PASS", "FAIL", "REVIEW", "KNOWN") for k in cnt)]
            out.append("      Data: " + "; ".join(data))
    missing = [cid for cid in d["sent"] if cid not in {c["case_id"] for c in d["cases"]}]
    for cid in missing:
        out.append(f"  {cid}  sent today ({d['sent'][cid]} email(s)) but not validated in Nexus yet")
    out += ["", f"BUGS FOUND IN THIS RUN ({len(d['new'])} new, waiting for your decision)"]
    out += [f"  - {_line(x)}" + (f"  [also seen on {x['first']}]" if x["first"] != d["date"] else "") for x in d["new"]] or ["  none"]
    out += ["", f"RAISED BUGS STILL THERE ({len(d['still'])})"]
    out += [f"  - {_line(x)}  [bug sheet row {x['row']}]" if x["row"] else f"  - {_line(x)}  [{x['status'].lower()}]" for x in d["still"]] or ["  none"]
    out += ["", f"PREVIOUSLY RAISED BUGS THAT PASSED IN THIS RUN, NOT RE-TESTED YET ({len(d['passed'])})"]
    out += [f"  - {_line(x)}  [bug sheet row {x['row']}]  not seen in {x['ipa']}" for x in d["passed"]] or ["  none"]
    if d["already"]:
        out.append(f"  ({d['already']} more passed but already have a re-test / Fixed status in the sheet, so they are not listed)")
    if d["not_tested"]:
        out += ["", f"RAISED BUGS NOT RE-TESTED TODAY ({len(d['not_tested'])})"]
        out += [f"  - {_line(x)}  [bug sheet row {x['row']}]  {x['why']}" if x["row"] else f"  - {_line(x)}  {x['why']}" for x in d["not_tested"]]
    if d.get("to_retest") is not None:
        out += ["", f"DEVELOPMENT COMPLETED, RE-TEST BLANK: TO RE-TEST NOW ({len(d['to_retest'])})"]
        out += [f"  - row {x['row']} · {x['job']} · {x['file']}" for x in d["to_retest"]] or ["  none"]
    if d["accepted"]:
        out += ["", f"ACCEPTED, NOT A BUG ({len(d['accepted'])} seen, no action)"]
    return "\n".join(out)


def write(reports: Path, store: Store, date: str | None = None, cfg=None) -> tuple[str, Path]:
    date = date or datetime.now().strftime("%Y-%m-%d")
    d = build(store, reports, date)
    if cfg is not None and d["passed"]:                      # drop the ones the sheet already shows as re-tested / Fixed
        retested = sheet_retested(cfg, [x["row"] for x in d["passed"] if x["row"]])
        d = build(store, reports, date, retested)
        if not retested:
            d["note"] = "bug sheet could not be read: every passed bug is listed, including ones already re-tested"
    d["to_retest"] = dev_completed_to_retest(cfg) if cfg is not None else None
    text = report(d)
    if d.get("note"):
        text += "\n\n(" + d["note"] + ")"
    path = reports / f"runreport_{date.replace('-', '')}_{datetime.now():%H%M%S}.md"
    path.write_text("```\n" + text + "\n```\n", encoding="utf-8")
    return text, path


# --------------------------------------------------------------------------------------------------------------------------------------
# HTML version: opens in the browser after every run
COLOUR = {"PASS": "#15803d", "FAIL": "#b91c1c", "ERROR": "#b91c1c", "REVIEW": "#b45309", "KNOWN": "#6b7280", "INFO": "#6b7280",
          "NOT_VERIFIABLE": "#6b7280"}


def _chip(text: str, result: str) -> str:
    import html
    c = COLOUR.get(result, "#6b7280")
    return f'<span class="chip" style="border-color:{c};color:{c}">{html.escape(text)}</span>'


def _traces(runs_dir: Path, date: str, cid: str, ipa: str) -> dict:
    """The newest trace folder of this pre-alert, and the newest one that holds the mapping screenshots (viewer parents)."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ipa).strip("-")
    dirs = sorted((runs_dir / date / cid).glob(f"trace_*_{slug}"), key=lambda p: p.name)
    mapping = next((d for d in reversed(dirs) if any(d.glob("*_parent_House.png"))), None)
    return {"latest": dirs[-1] if dirs else None, "mapping": mapping}


def html_report(d: dict, reports: Path) -> str:
    import html
    import os
    esc = html.escape
    runs_dir = reports.parent
    rel = lambda p: esc(os.path.relpath(p, reports).replace(os.sep, "/"))
    out = []
    summary = ""
    details = ""
    for c in d["cases"]:
        tr = _traces(runs_dir, d["date"], c["case_id"], c["ipa"])
        mapping = " ".join(_chip(m.split(" (")[0], m.split(": ")[1].split(" ")[0]) for m in c["mapping"])
        data = " ".join(_chip(f"{doc} " + " ".join(f"{k} {v}" for k, v in sorted(cnt.items()) if k in ("PASS", "FAIL", "REVIEW")),
                              "FAIL" if cnt.get("FAIL") else "REVIEW" if cnt.get("REVIEW") else "PASS") for doc, cnt in c["counts"].items()
                        if any(k in ("PASS", "FAIL", "REVIEW") for k in cnt))
        link = f'<a href="{rel(tr["latest"] / "index.html")}">trace</a>' if tr["latest"] else ""
        summary += (f'<tr><td><a href="#{c["case_id"]}"><b>{c["case_id"]}</b></a></td><td>{_chip(c["verdict"], c["verdict"])}</td><td>{esc(c["ipa"])}</td>'
                    f'<td>{esc(str(c["after"]))} s</td><td>{mapping}</td><td>{data or "not checked"}</td><td>{link}</td></tr>')
        bad = [m for m in c["mapping"] if not re.match(r"^[A-Z ]+: PASS", m)]
        sec = [f'<h2 id="{c["case_id"]}">{c["case_id"]} · {esc(c["ipa"])} · {_chip(c["verdict"], c["verdict"])}</h2>']
        sec.append("<p><b>Mapping:</b> " + ("all documents placed correctly" if not bad else esc("; ".join(bad))) + "</p>")
        if c["seen"]:
            sec.append("<p><b>Nexus holds:</b> " + esc(c["seen"].replace(c["ipa"] + " seen -> ", "")) + "</p>")
        if c["others"]:
            sec.append("<p>" + esc(c["others"]) + "</p>")
        for cause in c["causes"]:
            sec.append(f'<p class="cause"><b>Probable root cause:</b> {esc(cause)}</p>')
        if c["findings"]:
            rows = "".join(f'<tr><td>{esc(f["document"])}</td><td>{esc(f["field"])}</td><td>{esc(f["doc"])}</td><td>{esc(f["nexus"])}</td>'
                           f'<td>{_chip(f["result"], f["result"])}</td><td>{esc(f["note"])}</td></tr>' for f in sorted(
                               c["findings"], key=lambda f: ({"FAIL": 0, "REVIEW": 1}.get(f["result"], 2), f["document"], f["field"])))
            sec.append("<h3>Data findings (fields that did not match)</h3><table><tr><th>Document</th><th>Field</th><th>Document says</th>"
                       f"<th>Nexus shows</th><th>Result</th><th>Note</th></tr>{rows}</table>")
        shots = []
        if tr["mapping"]:
            for pat, cap in (("*_prealert_expanded.png", "Pre-Alerts page, row expanded"), ("*_unresolved_row.png", "Unresolved Documents"),
                             ("*_parent_Master.png", "Viewer: Master"), ("*_parent_House.png", "Viewer: House"),
                             ("*_parent_Manifest.png", "Viewer: Manifest"), ("*_others_tab.png", "Others tab")):
                f = next(iter(sorted(tr["mapping"].glob(pat))), None)
                if f:
                    shots.append(f'<figure><a href="{rel(f)}"><img src="{rel(f)}" loading="lazy"></a><figcaption>{cap}</figcaption></figure>')
        if shots:
            sec.append("<h3>Screenshots (click to enlarge)</h3><div class='shots'>" + "".join(shots) + "</div>")
        details += "<section>" + "".join(sec) + "</section>"
    for cid in [x for x in d["sent"] if x not in {c["case_id"] for c in d["cases"]}]:
        summary += f'<tr><td><b>{cid}</b></td><td colspan="6">sent today ({d["sent"][cid]} email(s)) but not validated in Nexus yet</td></tr>'

    def bugs(title: str, items: list[dict], extra=lambda x: "") -> str:
        li = "".join(f"<li>{esc(_line(x))} {extra(x)}</li>" for x in items) or "<li>none</li>"
        return f"<section><h2>{esc(title)} ({len(items)})</h2><ul>{li}</ul></section>"
    row = lambda x: f'<span class="sub">[bug sheet row {x["row"]}]</span>' if x.get("row") else ""
    tail = bugs("Bugs found in this run, waiting for your decision", d["new"],
                lambda x: f'<span class="sub">[also seen on {x["first"]}]</span>' if x["first"] != d["date"] else "")
    tail += bugs("Raised bugs still there", d["still"], row)
    tail += bugs("Previously raised bugs that passed in this run, not re-tested yet", d["passed"],
                 lambda x: f'<span class="sub">[bug sheet row {x["row"]}] not seen in {esc(x["ipa"])}</span>')
    tail += bugs("Raised bugs not re-tested today", d["not_tested"], lambda x: f'<span class="sub">{esc(x["why"])}</span>')
    if d.get("to_retest") is not None:
        tail += ("<section><h2>Development Completed, re-test blank: to re-test now (" + str(len(d["to_retest"])) + ")</h2><ul>"
                 + "".join(f"<li>row {esc(x['row'])} · {esc(x['job'])} · {esc(x['file'])}</li>" for x in d["to_retest"]) + "</ul></section>")
    tail += f'<p class="sub">Accepted as not a bug: {len(d["accepted"])} seen, no action.</p>'
    return ('<!doctype html><meta charset=utf-8><title>Run report ' + esc(d["date"]) + '</title><style>body{font:15px system-ui;margin:24px;'
            'background:#f5f6f8;color:#1c2330}h1{font-size:22px}h2{font-size:17px;margin:0 0 8px}h3{font-size:14px;margin:14px 0 6px}'
            'section{background:#fff;border:1px solid #d9dde3;border-radius:8px;padding:12px 16px;margin:0 0 16px}table{border-collapse:collapse;'
            'width:100%;background:#fff}td,th{border:1px solid #d9dde3;padding:6px 9px;text-align:left;vertical-align:top;font-size:13px}th{background:#eef0f3}'
            '.chip{display:inline-block;border:1px solid;border-radius:10px;padding:1px 8px;margin:2px 4px 2px 0;font-size:12px;white-space:nowrap}'
            '.cause{background:#fff7ed;border-left:3px solid #c2410c;padding:6px 10px}.sub{color:#6b7280;font-size:12px}'
            '.shots{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px}figure{margin:0}img{width:100%;border:1px solid #d9dde3}'
            'figcaption{font-size:12px;color:#6b7280}</style>'
            f'<h1>Run report {esc(d["date"])}</h1><p class="sub">Generated {datetime.now():%H:%M:%S}. Today\'s run only. Nothing here was added to the bug sheet.</p>'
            '<section><h2>All cases executed today</h2><table><tr><th>Case</th><th>Verdict</th><th>Pre-alert</th><th>Appeared after</th><th>Mapping</th>'
            f'<th>Data checks</th><th>Trace</th></tr>{summary}</table></section>' + details + tail)


def write_html(cfg, store: Store, date: str | None = None, with_sheet: bool = True) -> Path:
    """Builds today's report as HTML (runs/_reports/runreport_<date>.html, overwritten as the day goes on)."""
    date = date or datetime.now().strftime("%Y-%m-%d")
    reports = cfg.runs_dir / "_reports"
    d = build(store, reports, date)
    d["to_retest"] = dev_completed_to_retest(cfg) if with_sheet else None
    path = reports / f"runreport_{date.replace('-', '')}.html"
    path.write_text(html_report(d, reports), encoding="utf-8")
    return path
