"""Report for ONE day's run: what was observed, which bugs the run found, and which earlier raised bugs did not show this time.
Built from the day's validate / data CSVs in runs/_reports and from the bug history, so earlier days never leak in."""
from __future__ import annotations

import csv
import json
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


def _compare(reports: Path, day: str) -> dict:
    """Today's cases against each case's last earlier day (standing rule); never stops the report."""
    try:
        from . import daycompare
        return daycompare.compare(reports, day)
    except Exception as exc:
        return {"day": day, "cases": [], "first_runs": [], "error": f"{type(exc).__name__}: {exc}"}


def _patterns(store: Store, reports: Path):
    """Bug patterns learned from the sheet statuses (cache written by `./nx patterns`) or, without the cache, from the local decisions."""
    from . import bugprob
    f = reports.parent.parent / "state" / "bug_patterns.json"
    try:
        if f.exists():
            return bugprob.Patterns(json.loads(f.read_text(encoding="utf-8"))["records"])
    except Exception:
        pass
    return bugprob.Patterns(bugprob.history_from_store(store))


def _std(P, doc: str, x: dict) -> dict:
    """class (MATCH / MISSING / MISMATCH ...) and, for the ones to review, the likelihood of a real bug with its basis."""
    from . import stdcompare as SC
    cls = SC.classify(x)
    out = {"class": cls, "prob": None, "basis": ""}
    if cls in SC.REVIEWABLE and x.get("result") in ("FAIL", "REVIEW"):
        p, basis = P.estimate(doc, x.get("field", ""), SC.nature(cls))
        out.update(prob=p, basis=basis)
    return out


def build(store: Store, reports: Path, date: str, retested: dict[str, bool] | None = None) -> dict:
    P = _patterns(store, reports)
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

    # consolidation of the day: every run session of today (send, mapping check, data checks) in time order, and every attempt per case
    def _t(f: Path) -> str:
        st = _stamp(f).split("_")[-1]
        return f"{st[0:2]}:{st[2:4]}:{st[4:6]}"
    runs: list[dict] = []
    attempts: dict[str, list[dict]] = defaultdict(list)
    for f in sorted(reports.glob(f"suite_{day}_*.csv"), key=_stamp):
        rows = [r for r in _rows(f) if r.get("status") not in ("DRY_RUN",)]
        if rows:
            runs.append({"time": _t(f), "kind": "Send", "stamp": _stamp(f),
                         "summary": ", ".join(f"{r['case_id']} {r.get('status', '')}" for r in rows if r.get("status"))[:300]})
            for r in rows:
                sent_at = (r.get("sent_at") or "")[11:19] or _t(f)
                attempts[r["case_id"]].append({"time": sent_at, "what": "email " + (r.get("status") or "").lower(), "ipa": "", "result": r.get("status", "")})
    for f in validates:
        rows = _rows(f)
        runs.append({"time": _t(f), "kind": "Mapping check", "stamp": _stamp(f),
                     "summary": ", ".join(f"{r['case_id']} {r.get('verdict', '')}" for r in rows)[:300]})
        for r in rows:
            attempts[r["case_id"]].append({"time": _t(f), "what": "mapping check", "ipa": r.get("ipa", ""), "result": r.get("verdict", ""),
                                           "status": r.get("nexus_status", "")})
    for doc, prefix in DATA_FILES.items():
        for f in sorted(reports.glob(f"{prefix}_{day}_*.csv"), key=_stamp):
            rows = _rows(f)
            by: dict[str, dict] = defaultdict(lambda: defaultdict(int))
            ipa_of: dict[str, str] = {}
            for r in rows:
                if r.get("result") in ("PASS", "FAIL", "REVIEW", "KNOWN"):
                    by[r["case_id"]][r["result"]] += 1
                    ipa_of[r["case_id"]] = r.get("ipa", "")
                elif r.get("result") == "ERROR":
                    by[r["case_id"]]["ERROR"] += 1
            if by:
                runs.append({"time": _t(f), "kind": f"{doc} data check", "stamp": _stamp(f), "summary": ", ".join(
                    f"{c} " + "/".join(f"{k} {v}" for k, v in sorted(cnt.items())) for c, cnt in by.items())[:300]})
                for c, cnt in by.items():
                    attempts[c].append({"time": _t(f), "what": f"{doc} data", "ipa": ipa_of.get(c, ""),
                                        "result": "ERROR" if cnt.get("ERROR") and len(cnt) == 1 else "FAIL" if cnt.get("FAIL") else "REVIEW" if cnt.get("REVIEW") else "PASS",
                                        "counts": dict(cnt)})
    runs.sort(key=lambda x: x["stamp"])

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
                     "result": x["result"], "note": x.get("note", ""), "source": x.get("source", ""), **_std(P, doc, x)}
                    for (doc, ipa, _f), x in latest_data.items() if ipa == r["ipa"] and x["result"] in ("FAIL", "REVIEW", "KNOWN", "NOT_VERIFIABLE")]
        rows_by_doc: dict[str, list[dict]] = defaultdict(list)
        for (doc, ipa, _f), x in latest_data.items():
            if ipa == r["ipa"]:
                rows_by_doc[doc].append({"field": x.get("field", ""), "doc": x.get("expected_from_document", ""), "nexus": x.get("shown_in_nexus", ""),
                                         "result": x.get("result", ""), "note": x.get("note", ""), "source": x.get("source", ""), **_std(P, doc, x)})
        cases.append({"case_id": cid, "ipa": r["ipa"], "verdict": r["verdict"], "after": r.get("appeared_after_s", ""), "mapping": mapping,
                      "causes": causes, "seen": seen, "others": others, "counts": counts, "findings": findings,
                      "rows": dict(rows_by_doc), "attempts": attempts.get(cid, [])})

    cmp_ = _compare(reports, day)
    from . import stdcompare as SC
    regressed = {(c["case_id"], ch["document"], ch["field"]) for c in cmp_.get("cases", []) for ch in c["changes"] if ch["kind"] == "REGRESSED"}
    for c in cases:
        tri = {SC.PASS_B: 0, SC.INFO_B: 0, SC.KNOWN_B: 0, SC.FAIL_B: [], SC.DISCUSS_B: []}
        for doc, rows in c["rows"].items():
            for x in rows:
                b = SC.triage(x["class"], (c["case_id"], doc, x["field"]) in regressed)
                if b in (SC.FAIL_B, SC.DISCUSS_B):
                    tri[b].append({"document": doc, **{k: x[k] for k in ("field", "doc", "nexus", "class", "note", "prob")}})
                else:
                    tri[b] += 1
        c["triage"] = tri

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
    return {"date": date, "cases": cases, "runs": runs, "attempts": dict(attempts), "sent": dict(sent), "new": new, "still": still, "accepted": accepted,
            "passed": sorted(passed, key=lambda x: x["row"] or "0"), "not_tested": not_tested, "already": already,
            "sheet_read": retested is not None and bool(retested), "compare": cmp_}


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
    out += ["", "DATA VALIDATION RESULT  (Nexus field -> document; nothing below is a bug until you confirm it)"]
    for c in d["cases"]:
        t = c.get("triage")
        if not t or not (t["PASS"] or t["FAIL"] or t["DISCUSSION NEEDED"]):
            continue
        out.append(f"  {c['case_id']}  {c['ipa']}:  PASS {t['PASS']}   FAIL {len(t['FAIL'])}   DISCUSSION NEEDED {len(t['DISCUSSION NEEDED'])}"
                   f"   (info {t['INFO']}, known {t['KNOWN']})")
        for title, key, why in (("FAIL - it matched in an earlier run and does not now", "FAIL", ""),
                                ("DISCUSSION NEEDED - mismatches and doubts", "DISCUSSION NEEDED", "")):
            if t[key]:
                out.append(f"      {title}")
                for x in t[key]:
                    out.append(f"        [{x['class']}] {x['document']} · {x['field']}: document says '{(x['doc'] or '-')[:60]}' | Nexus shows '{(x['nexus'] or '-')[:60]}'")
    out += ["", f"BUGS FOUND IN THIS RUN ({len(d['new'])} new, waiting for your decision)"]
    out += [f"  - {_line(x)}" + (f"  [also seen on {x['first']}]" if x["first"] != d["date"] else "") for x in d["new"]] or ["  none"]
    out += ["", f"RAISED BUGS STILL THERE ({len(d['still'])})"]
    out += [f"  - {_line(x)}  [bug sheet row {x['row']}]" if x["row"] else f"  - {_line(x)}  [{x['status'].lower()}]" for x in d["still"]] or ["  none"]
    if d.get("compare") and (d["compare"]["cases"] or d["compare"]["first_runs"]):
        from . import daycompare
        out += ["", "COMPARED WITH THE PREVIOUS RUN OF EACH CASE (fields reported by the checks: new / regressed / still there / no longer reported)"]
        out += ["  " + ln for ln in daycompare.render(d["compare"])]
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


def _compare_html(d: dict, esc) -> str:
    cmp_ = d.get("compare") or {}
    if not cmp_.get("cases"):
        return ""
    from . import daycompare as DC
    rows, det = [], []
    for c in cmp_["cases"]:
        n = c["counts"]
        warn = " ⚠" if c["not_comparable"] else ""
        rows.append(f'<tr><td>{esc(c["case_id"])}</td><td>{esc(DC._pretty(c["prev_day"]))}</td><td>{esc(c["prev_ipa"])} → {esc(c["ipa"])}</td>'
                    f'<td>{esc(c["mapping_before"] or "-")} → {esc(c["mapping_now"] or "-")}</td><td>{n.get("NEW", 0)}</td><td>{n.get("REGRESSED", 0)}</td>'
                    f'<td>{n.get("STILL", 0)}</td><td>{n.get("FIXED", 0)}</td><td>{warn}</td></tr>')
        ch = [x for x in c["changes"] if x["kind"] in ("REGRESSED", "NEW", "FIXED")][:12]
        if ch:
            body = "".join(f'<tr><td>{x["kind"]}</td><td>{esc(x["document"])}</td><td>{esc(x["field"])}</td><td>{esc(x["before"])} → {esc(x["after"])}</td>'
                           f'<td>{esc(x["nexus_now"][:80])}</td></tr>' for x in ch)
            det.append(f"<details><summary><b>{esc(c['case_id'])}</b>: what changed since {esc(DC._pretty(c['prev_day']))}</summary>"
                       f"<table class='small'><tr><th>Change</th><th>Document</th><th>Field</th><th>Result</th><th>Nexus now</th></tr>{body}</table></details>")
    note = ("<p class='sub'>⚠ Sea findings before 13-Nov came from the old checker (party blocks named by order, no document values): not strictly comparable. "
            "Each case is compared with its last earlier day that has data.</p>")
    return ("<section><h2>Compared with the previous run of each case</h2><table><tr><th>Case</th><th>Previous run</th><th>Pre-alert</th><th>Mapping</th>"
            "<th>New</th><th>Regressed</th><th>Still there</th><th>No longer reported</th><th></th></tr>" + "".join(rows) + "</table>" + note + "".join(det) + "</section>")


def _triage_html(d: dict, esc) -> str:
    parts = []
    for c in d["cases"]:
        t = c.get("triage")
        if not t or not (t["PASS"] or t["FAIL"] or t["DISCUSSION NEEDED"]):
            continue
        def tbl(key):
            body = "".join(f'<tr><td>{esc(x["class"])}</td><td>{esc(x["document"])}</td><td>{esc(x["field"])}</td><td>{esc(x["doc"][:80] or "-")}</td>'
                           f'<td>{esc(x["nexus"][:80] or "-")}</td></tr>' for x in t[key])
            return (f"<table class='small'><tr><th>Class</th><th>Document</th><th>Field</th><th>Document says</th><th>Nexus shows</th></tr>{body}</table>"
                    if t[key] else "<p class='sub'>none</p>")
        parts.append(f"<h3>{esc(c['case_id'])} · {esc(c['ipa'])}: PASS {t['PASS']} · FAIL {len(t['FAIL'])} · DISCUSSION NEEDED {len(t['DISCUSSION NEEDED'])}</h3>"
                     f"<p><b>FAIL</b> (matched in an earlier run, not now)</p>{tbl('FAIL')}<p><b>DISCUSSION NEEDED</b> (mismatches and doubts)</p>{tbl('DISCUSSION NEEDED')}")
    return ("<section><h2>Data validation result</h2><p class='sub'>Nexus field → document. A FAIL or a discussion item becomes a bug only after you confirm it.</p>"
            + "".join(parts) + "</section>") if parts else ""


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
            def _lk(f):
                return f'<td title="{esc(f.get("basis", ""))}">{round(f["prob"] * 100)}%</td>' if f.get("prob") is not None else "<td></td>"
            rows = "".join(f'<tr><td>{esc(f["document"])}</td><td>{esc(f["field"])}</td><td>{esc(f.get("class", ""))}</td>{_lk(f)}<td>{esc(f["doc"])}</td><td>{esc(f["nexus"])}</td>'
                           f'<td>{_chip(f["result"], f["result"])}</td><td>{esc(f["note"])}</td></tr>' for f in sorted(
                               c["findings"], key=lambda f: (-(f.get("prob") if f.get("prob") is not None else -1), {"FAIL": 0, "REVIEW": 1}.get(f["result"], 2), f["document"], f["field"])))
            sec.append("<h3>Data findings: what the document prints against the Nexus shipment data (most likely bugs first)</h3>"
                       "<p class='sub'>MISSING = the document prints it, Nexus is empty · MISMATCH = both have a value, they differ · NOT IN DOCUMENT = Nexus holds a value the document does not print. "
                       "Likelihood = share of earlier findings of the same kind that were real bugs in the bug sheet (hover for the basis); it only orders the list, it is not a verdict.</p>"
                       "<table><tr><th>Document</th><th>Field</th><th>Class</th><th>Bug likelihood</th><th>Document says</th>"
                       f"<th>Nexus shows</th><th>Result</th><th>Note</th></tr>{rows}</table>")
        if c.get("attempts"):
            att = "".join(f'<tr><td>{esc(a["time"])}</td><td>{esc(a["what"])}</td><td>{esc(a.get("ipa", ""))}</td>'
                          f'<td>{_chip(a["result"], a["result"])}</td></tr>' for a in c["attempts"])
            sec.append(f"<h3>All attempts today</h3><table class='small'><tr><th>Time (sent / check finished)</th><th>Step</th><th>Pre-alert</th><th>Result</th></tr>{att}</table>")
        for doc, rws in sorted((c.get("rows") or {}).items()):
            order = {"FAIL": 0, "REVIEW": 1, "KNOWN": 2, "NOT_VERIFIABLE": 3, "INFO": 4, "PASS": 5}
            cnt = defaultdict(int)
            for x in rws:
                cnt[x["result"]] += 1
            body = "".join(f'<tr><td>{esc(x["field"])}</td><td>{esc(x.get("class", ""))}</td><td>{esc(x["doc"])}</td><td>{esc(x["nexus"])}</td><td>{_chip(x["result"], x["result"])}</td>'
                           f'<td>{esc(x["note"])}</td></tr>' for x in sorted(rws, key=lambda x: (order.get(x["result"], 9), x["field"])))
            head = ", ".join(f"{k} {v}" for k, v in sorted(cnt.items(), key=lambda kv: order.get(kv[0], 9)))
            src = esc(rws[0].get("source", "")) if rws else ""
            sec.append(f"<details><summary><b>{esc(doc)}</b>: every field checked ({len(rws)}) · {esc(head)}</summary><p class='sub'>Source: {src}</p>"
                       f"<table class='small'><tr><th>Field</th><th>Class</th><th>Document says</th><th>Nexus shows</th><th>Result</th><th>Note</th></tr>{body}</table></details>")
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
    # consolidation of the day: tiles + the timeline of every run session of the day
    cases = d["cases"]
    passed = sum(1 for c in cases if c["verdict"] == "PASS")
    failed = sum(1 for c in cases if c["verdict"] != "PASS")
    unvalidated = [x for x in d["sent"] if x not in {c["case_id"] for c in cases}]
    tiles = "".join(f'<div class="tile"><b>{v}</b><span>{esc(k)}</span></div>' for k, v in (
        ("cases validated", len(cases)), ("mapping PASS", passed), ("mapping not PASS", failed), ("sent, not validated", len(unvalidated)),
        ("run sessions today", len(d.get("runs", []))), ("new bug candidates", len(d["new"])), ("raised bugs still there", len(d["still"]))))
    timeline = "".join(f'<tr><td>{esc(r["time"])}</td><td>{esc(r["kind"])}</td><td>{esc(r["summary"])}</td></tr>' for r in d.get("runs", []))
    timeline = (f'<section><h2>Runs today ({len(d.get("runs", []))}): everything done on {esc(d["date"])}, oldest first</h2>'
                f'<details><summary>show the timeline</summary><table class="small"><tr><th>Time (finished)</th><th>Run</th><th>Cases and results</th></tr>{timeline}</table></details></section>'
                if timeline else "")
    logo = ""
    try:
        logo = (Path(__file__).resolve().parent.parent / "assets" / "nexus_logo.svg").read_text(encoding="utf-8").replace('style="width: 100%; height: 100%;"', 'style="width:100%;height:100%"')
    except OSError:
        logo = ""
    return ('<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Automated test report ' + esc(d["date"]) + '</title><style>'
            ':root{--bg:#f5f6f8;--card:#fff;--line:#d9dde3;--ink:#1c2330;--mute:#6b7280;--head:#0f172a}'
            '@media (prefers-color-scheme:dark){:root{--bg:#0f1420;--card:#171d2b;--line:#2a3345;--ink:#e6e9ef;--mute:#9aa4b5;--head:#0b0f19}}'
            'body{font:15px system-ui,sans-serif;margin:0;background:var(--bg);color:var(--ink)}main{max-width:1280px;margin:0 auto;padding:0 20px 40px}'
            'header{background:var(--head);color:#fff;padding:18px 24px;display:flex;align-items:center;gap:16px}'
            'header .logo{width:44px;height:44px;flex:none}header h1{margin:0;font-size:24px}header p{margin:2px 0 0;color:#aab4c6;font-size:13px}'
            'h2{font-size:17px;margin:0 0 8px}h3{font-size:14px;margin:14px 0 6px}'
            'section{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:0 0 16px}'
            'table{border-collapse:collapse;width:100%;background:var(--card)}td,th{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top;font-size:13px}'
            'th{background:rgba(127,140,160,.14)}table.small td,table.small th{font-size:12px;padding:4px 7px}'
            '.chip{display:inline-block;border:1px solid;border-radius:10px;padding:1px 8px;margin:2px 4px 2px 0;font-size:12px;white-space:nowrap}'
            '.cause{background:rgba(194,65,12,.12);border-left:3px solid #c2410c;padding:6px 10px}.sub{color:var(--mute);font-size:12px}'
            '.tiles{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 16px;min-width:130px}'
            '.tile b{display:block;font-size:24px}.tile span{color:var(--mute);font-size:12px}details{margin:8px 0}summary{cursor:pointer}'
            '.shots{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px}figure{margin:0}img{width:100%;border:1px solid var(--line)}'
            'figcaption{font-size:12px;color:var(--mute)}a{color:#2563eb}</style>'
            f'<header><div class="logo">{logo}</div><div><h1>Automated test report</h1>'
            f'<p>Nexus Pre-Alert regression · {esc(d["date"])} · consolidated: every run of the day · generated {datetime.now():%H:%M:%S}</p></div></header><main>'
            f'<div class="tiles">{tiles}</div>' + timeline +
            '<section><h2>Cases, latest result of the day</h2><table><tr><th>Case</th><th>Verdict</th><th>Pre-alert</th><th>Appeared after</th><th>Mapping</th>'
            f'<th>Data checks</th><th>Trace</th></tr>{summary}</table></section>' + _triage_html(d, esc) + _compare_html(d, esc) + details + tail +
            '<p class="sub">Nothing in this report was added to the bug sheet; that needs your confirmation for each bug.</p></main>')


def write_html(cfg, store: Store, date: str | None = None, with_sheet: bool = True) -> Path:
    """Builds today's report as HTML (runs/_reports/runreport_<date>.html, overwritten as the day goes on)."""
    date = date or datetime.now().strftime("%Y-%m-%d")
    reports = cfg.runs_dir / "_reports"
    d = build(store, reports, date)
    d["to_retest"] = dev_completed_to_retest(cfg) if with_sheet else None
    path = reports / f"runreport_{date.replace('-', '')}.html"
    path.write_text(html_report(d, reports), encoding="utf-8")
    return path
