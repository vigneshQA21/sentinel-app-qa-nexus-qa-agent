"""CLI:
  python -m nexus_agent login                 # log in once, save the Nexus session
  python -m nexus_agent run                   # Gmail -> Nexus -> checks -> push -> XML reconcile
  python -m nexus_agent run --dry-run         # read and check only: no forward, edit or push
  python -m nexus_agent run --no-gmail --refs UNF1001 UNF1002   # (re)process given references
  python -m nexus_agent forward               # only forward new Gmail pre-alerts
  python -m nexus_agent validate --cases REG-001   # check the mapping in the Nexus UI (saved session)
  python -m nexus_agent send-local [--dry-run] # screen + email knowledge_base/consolidated PDFs as-is (and individual/ files)
"""
from __future__ import annotations

# Always run with the project's own Python (.venv), whichever terminal this is started from.
import os
import sys
from pathlib import Path

_venv_python = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python"
if (_venv_python.exists() and not os.environ.get("NEXUS_NO_REEXEC")
        and Path(sys.prefix).resolve() != (_venv_python.parent.parent).resolve()):
    os.environ["NEXUS_NO_REEXEC"] = "1"
    os.execv(str(_venv_python), [str(_venv_python), "-m", "nexus_agent", *sys.argv[1:]])


import argparse
import logging
import sys

from .config import Config


def _note_bugs(cfg, mapping_rows=None, groups=None) -> None:
    """Saves FAIL / REVIEW findings as bug CANDIDATES (never adds anything to the bug sheet) and prints a one-line hint.
    groups = [(title, results)] with title Master | House | Manifest | Invoice | Packing List."""
    from . import bugs as B
    from . import testsuite as T
    from .store import Store
    try:
        cases = {c.id: c for c in T.read_cases(cfg)}
        cands = B.candidates_from_mapping(mapping_rows or [], cases, cfg)
        for title, results in groups or []:
            cands += B.candidates_from_results(results, title, cases, cfg)
        store = Store(cfg.state_dir / "agent.db")
        new, known = B.record(cfg, store, cands)
        line = B.summary_line(store, new, known)
        if line:
            print(line)
    except Exception as exc:                       # never let bug bookkeeping break a validation run
        print(f"(bug candidates could not be saved: {type(exc).__name__}: {exc})")


def _baseline(cfg, results=None, title="", mapping_rows=None) -> None:
    """Marks findings that are already logged (or accepted as not a bug) as KNOWN so only NEW differences fail the case."""
    from . import baseline as BL
    from .store import Store
    try:
        store = Store(cfg.state_dir / "agent.db")
        n, fixed = BL.apply_checks(store, results, title) if results is not None else (0, [])
        if mapping_rows:
            n += BL.apply_mapping(store, mapping_rows)
        if n:
            print(f"(baseline) {n} known issue(s) in {title or 'mapping'} shown as KNOWN: logged or accepted earlier, they do not fail the case")
        for f in fixed:
            print(f"(baseline) {f}")
    except Exception as exc:
        print(f"(baseline could not be applied: {type(exc).__name__}: {exc})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nexus_agent")
    ap.add_argument("--config", help="config directory (default: ./config)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--profile", help="selector profile: uat (default, the real Nexus) or mock")
    sub = ap.add_subparsers(dest="cmd", required=True)

    lg = sub.add_parser("login", help="log in to Nexus in a browser window and save the session")
    lg.add_argument("--wait", type=int, default=300)

    rn = sub.add_parser("run", help="process pre-alerts end to end")
    rn.add_argument("--refs", nargs="*", help="HAWB/MAWB references to process")
    rn.add_argument("--no-gmail", action="store_true", help="skip Gmail forwarding")
    rn.add_argument("--dry-run", action="store_true")
    rn.add_argument("--headed", action="store_true", help="show the browser")

    fw = sub.add_parser("forward", help="only forward new Gmail pre-alerts")
    fw.add_argument("--dry-run", action="store_true")

    sl = sub.add_parser("send-local", help="screen and email knowledge_base documents to the Nexus mailbox")
    sl.add_argument("--dry-run", action="store_true")
    sl.add_argument("--refs", nargs="*", help="only these references")
    sl.add_argument("--force", action="store_true", help="resend even if already sent / send despite a failed screening")

    va = sub.add_parser("validate", help="check in the Nexus UI that a sent test case was classified and mapped correctly")
    va.add_argument("--cases", nargs="+", default=["REG-001"], help="test case ids (default: REG-001)")
    va.add_argument("--ref", help="HAWB/FJ to look for (default: the reference of the last email sent for the case)")
    va.add_argument("--wait", type=int, help="seconds to wait for the pre-alert to appear (default timing.prealert_wait_seconds)")
    va.add_argument("--headless", action="store_true", help="hide the browser (default: the browser window is shown)")
    va.add_argument("--headed", action="store_true", help=argparse.SUPPRESS)      # kept for old commands: headed is the default

    vm = sub.add_parser("validate-master", help="compare the Master data Nexus extracted with what the source PDF says")
    vm.add_argument("--cases", nargs="+", default=["REG-001"], help="test case ids (default: REG-001)")
    vm.add_argument("--wait", type=int, help="seconds to wait for the pre-alert (default: buffer + polling from the send time)")
    vm.add_argument("--headless", action="store_true", help="hide the browser (default: shown)")

    vh = sub.add_parser("validate-house", help="compare the House data Nexus extracted with what the source PDF says")
    vh.add_argument("--cases", nargs="+", default=["REG-001"], help="test case ids (default: REG-001)")
    vh.add_argument("--wait", type=int, help="seconds to wait for the pre-alert (default: buffer + polling from the send time)")
    vh.add_argument("--headless", action="store_true", help="hide the browser (default: shown)")

    vd = sub.add_parser("validate-docs", help="compare the Manifest, Invoice and Packing List data Nexus extracted with the documents")
    vd.add_argument("--cases", nargs="+", default=["REG-001"], help="test case ids (default: REG-001)")
    vd.add_argument("--only", nargs="+", choices=["manifest", "invoice", "packing"], help="check only these documents")
    vd.add_argument("--wait", type=int, help="seconds to wait for the pre-alert (default: buffer + polling from the send time)")
    vd.add_argument("--headless", action="store_true", help="hide the browser (default: shown)")

    sub.add_parser("history", help="internal bug history: bugs found, how often each repeats, status")
    cd = sub.add_parser("casedoc", help="write every validation of the given cases into the test-case workbook (new tab, backup first)")
    cd.add_argument("--cases", nargs="+", default=["REG-001", "REG-002"])
    lg2 = sub.add_parser("log", help="add a note to today's entry in docs/PROGRESS_LOG.md")
    lg2.add_argument("text", nargs="+", help="what changed / what was decided")

    bg = sub.add_parser("bugs", help="review the bug candidates found by the checks; nothing is logged without your y")
    bg.add_argument("--list", action="store_true", help="only list them (also what happens when there is no keyboard)")
    bg.add_argument("--check-sheet", action="store_true", help="connect to the bug sheet READ-ONLY: find the tab, read the header, map the columns (writes nothing)")

    cs = sub.add_parser("cases", help="list the in-scope test cases and whether their samples are available")

    ig = sub.add_parser("ingest", help="file downloads from samples/_inbox/ under their test case")

    su = sub.add_parser("suite", help="stage, screen and send the sample documents of the test cases")
    su.add_argument("--cases", nargs="*", help="test case ids, e.g. REG-001 REG-006 (default: all in scope)")
    su.add_argument("--dry-run", action="store_true")
    su.add_argument("--force", action="store_true", help="send even if screening fails")
    su.add_argument("--validate", action="store_true",
                    help="after each case is sent, wait a buffer, poll until Nexus shows the pre-alert and validate its mapping (headed browser)")
    su.add_argument("--interval", type=int, help="seconds to wait between cases (default: testsuite.case_interval_seconds; 0 = none)")
    su.add_argument("--resend", action="store_true", help="send again even if the file was sent before")

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    import os
    profile = args.profile or (None if os.getenv("NEXUS_MOCK") else "uat")
    cfg = Config(args.config, profile=None if profile == "mock" else profile)

    if args.cmd == "login":
        from .nexus.session import NexusSession
        with NexusSession(cfg, headless=False) as s:
            s.interactive_login(args.wait)
        return 0

    if args.cmd == "forward":
        from .gmail_forwarder import GmailForwarder
        from .store import Store
        fwd = GmailForwarder(cfg, Store(cfg.state_dir / "agent.db")).forward_new(args.dry_run)
        print(f"{len(fwd)} pre-alert(s) {'would be ' if args.dry_run else ''}forwarded")
        return 0

    if args.cmd == "history":
        from . import history as H
        from .store import Store
        print(H.report(Store(cfg.state_dir / "agent.db")))
        return 0

    if args.cmd == "casedoc":
        from . import casedoc as CD
        path, backup, n = CD.write(cfg, [c.upper() for c in args.cases])
        print(f"{n} validations written to the tab '{CD.TAB}' in {path}\nBackup of the workbook before the change: {backup}")
        return 0

    if args.cmd == "log":
        from .devlog import append_log
        print(f"added under {append_log(cfg.path('docs/PROGRESS_LOG.md'), ' '.join(args.text))} in docs/PROGRESS_LOG.md")
        return 0

    if args.cmd == "bugs":
        from . import bugs as B
        from .store import Store
        if args.check_sheet:
            try:
                state = B.check_sheet(cfg)
            except Exception as exc:
                print(f"Could not read the bug sheet: {type(exc).__name__}: {str(exc).splitlines()[0][:300]}")
                print("Check: Google Sheets API enabled, scope .../auth/spreadsheets added, and your Google account can edit the sheet.")
                return 2
            print(f"Connected (read-only) to: {state['spreadsheet_title']}  ·  tab: {state['tab_name']}")
            print("Header row and how each column will be filled:")
            for h, field in state["mapping"]:
                print(f"   {h or '(blank)':32} -> {field or '(left empty: not recognised)'}")
            try:
                tail = B.read_sheet_tail(cfg)
                print(f"\nThe sheet has {tail['data_rows']} bug rows (header in row {tail['header_row']}, last used row {tail['last_row']}).")
                print("Last rows, to copy the way bugs are recorded:")
                for rn, r in tail["tail"]:
                    print(f"  row {rn}:")
                    for h, v in zip(state["header"], list(r) + [""] * len(state["header"])):
                        if str(v).strip():
                            print(f"      {h or '(blank)':26}: {' '.join(str(v).split())[:150]}")
            except Exception as exc:
                print(f"(could not read the last rows: {type(exc).__name__})")
            try:
                cur = cfg.settings["bugsheet"].get("evidence_folder_id")
                if cur:
                    meta = B.drive_service(cfg).files().get(fileId=cur, fields="name,mimeType,capabilities(canAddChildren)", supportsAllDrives=True).execute()
                    ok = meta.get("capabilities", {}).get("canAddChildren")
                    print(f"\nEvidence folder set in settings: '{meta.get('name')}'  ->  " + ("you can add files to it" if ok else "NO permission to add files to it"))
                folders = B.discover_evidence_folder(cfg)
                if folders:
                    print("\nDrive folder(s) holding the evidence already linked in the sheet:")
                    for pid, name, n in folders:
                        print(f"   {name or '(name hidden)'}   id: {pid}   ({n} of the recent files){'   <- the one set in settings' if pid == cur else ''}")
                    if not cur:
                        print("   evidence_folder_id is not set yet: tell the agent which folder to use (it is never guessed).")
                else:
                    print("\n(no evidence folder found from the existing chips)")
            except Exception as exc:
                print(f"\n(Drive folder not checked: {type(exc).__name__}: {str(exc).splitlines()[0][:160]})")
            print("\nNothing was written to the sheet. Bugs are added only when you answer y in  ./nx bugs.")
            return 0
        store = Store(cfg.state_dir / "agent.db")
        st = {k: len(store.bugs_by_status(k)) for k in ("PENDING", "APPROVED", "LOGGED", "NOT_A_BUG")}
        print("Bug candidates: " + ", ".join(f"{k.lower().replace('_', ' ')} {v}" for k, v in st.items()))
        if args.list or not sys.stdin.isatty():
            import json
            for n, rec in enumerate(store.bugs_by_status("PENDING"), 1):
                c = json.loads(rec["data"])
                print(f"\n{n}. [{c['result']}] {c['case_id']} · {c['document']} · {c['field']}\n   " + B.two_lines(c).replace("\n", "\n   "))
            if st["PENDING"]:
                print("\nTo decide on them (y / n / skip) run  ./nx bugs  in a terminal. Nothing has been added to the bug sheet.")
            return 0
        print(f"Where a confirmed bug goes: {'the Google sheet' if B.effective_backend(cfg) == 'sheets' else 'a paste file (run ./nx bugs --check-sheet to connect the sheet)'}")
        B.review(cfg, store)
        return 0

    if args.cmd == "validate-docs":
        from . import docs_check as DC
        from . import master_check as MC
        from . import testsuite as T
        wanted = {c.upper() for c in args.cases}
        chosen = [c for c in T.read_cases(cfg) if c.id in wanted]
        kinds = tuple(k.upper() for k in args.only) if args.only else None
        shown_kinds = kinds or ("MANIFEST", "INVOICE", "PACKING", "DEBITNOTE", "SHIPPERDOC")
        results = DC.run_docs_check(cfg, chosen, headless=args.headless, wait_seconds=args.wait, kinds=kinds)
        from . import bugs as _B
        for k in shown_kinds:
            _baseline(cfg, [r for r in results if r["kind"] == k], _B.DOC_TITLES[k])
        for r in results:
            print(MC.format_report([r], DC.TITLES[r["kind"]]))
        for k in shown_kinds:
            part = [r for r in results if r["kind"] == k]
            if part:
                print(f"\n{DC.TITLES[k].title()} report: {MC.write_report(cfg, part, k.lower() + '_data')}")
        from . import bugs as B
        _note_bugs(cfg, groups=[(B.DOC_TITLES[k], [r for r in results if r["kind"] == k]) for k in shown_kinds])
        return 0 if all(r["verdict"] == "PASS" for r in results) else 2

    if args.cmd == "validate-house":
        from . import house_check as HC
        from . import master_check as MC
        from . import testsuite as T
        wanted = {c.upper() for c in args.cases}
        chosen = [c for c in T.read_cases(cfg) if c.id in wanted]
        results = HC.run_house_check(cfg, chosen, headless=args.headless, wait_seconds=args.wait)
        _baseline(cfg, results, "House")
        print(MC.format_report(results, "HOUSE DATA"))
        print(f"\nReport: {MC.write_report(cfg, results, 'house_data')}")
        _note_bugs(cfg, groups=[("House", results)])
        return 0 if all(r["verdict"] == "PASS" for r in results) else 2

    if args.cmd == "validate-master":
        from . import master_check as MC
        from . import testsuite as T
        wanted = {c.upper() for c in args.cases}
        chosen = [c for c in T.read_cases(cfg) if c.id in wanted]
        results = MC.run_master_check(cfg, chosen, headless=args.headless, wait_seconds=args.wait)
        _baseline(cfg, results, "Master")
        print(MC.format_report(results))
        print(f"\nReport: {MC.write_report(cfg, results)}")
        _note_bugs(cfg, groups=[("Master", results)])
        return 0 if all(r["verdict"] == "PASS" for r in results) else 2

    if args.cmd == "validate":
        from . import testsuite as T
        from . import validate as V
        wanted = {c.upper() for c in args.cases}
        chosen = [c for c in T.read_cases(cfg) if c.id in wanted]
        missing = wanted - {c.id for c in chosen}
        if missing:
            print(f"unknown or out-of-scope case(s): {', '.join(sorted(missing))}")
            return 2
        rows = V.run_validate(cfg, chosen, headless=args.headless and not args.headed, ref=args.ref, wait_seconds=args.wait)
        _baseline(cfg, mapping_rows=rows)
        for r in rows:
            print(f"{r['case_id']:8} {r['verdict']:6} {r['nexus_status']:17} {r['ref']} {r.get('ipa', '')}")
            for part in r["details"].split(" | "):
                print(f"           {part}")
        print(f"\nReport: {V.write_report(cfg, rows)}")
        _note_bugs(cfg, mapping_rows=rows)
        return 0 if all(r["verdict"] == "PASS" for r in rows) else 2

    if args.cmd in ("cases", "ingest", "suite"):
        from . import testsuite as T
        cases = T.read_cases(cfg)
        if args.cmd == "cases":
            for c in cases:
                n = len(T.sample_files(cfg, c))
                print(f"{c.id:8} {c.mode:12} {c.sample_ref or '-':12} samples: {n or 'none':<5} {c.docs[:70]}")
            return 0
        if args.cmd == "ingest":
            filed, unmatched = T.ingest(cfg, cases)
            for cid, names in filed.items():
                print(f"{cid}: {', '.join(names)}")
            for n in unmatched:
                print(f"UNMATCHED (name has no case id or FJ of an in-scope case): {n}")
            print(f"{sum(map(len, filed.values()))} file(s) filed, {len(unmatched)} unmatched")
            return 0
        from .local_sender import LocalSender
        from .store import Store
        wanted = {c.upper() for c in args.cases} if args.cases else None
        chosen = [c for c in cases if not wanted or c.id in wanted]
        store = Store(cfg.state_dir / "agent.db")
        sender = LocalSender(cfg, store)
        interval = cfg.settings["testsuite"].get("case_interval_seconds", 0) if args.interval is None else args.interval
        vrows: list[dict] = []
        mrows: list[dict] = []
        hrows: list[dict] = []
        drows: list[dict] = []
        if args.validate and not args.dry_run:
            from . import docs_check as DC
            from . import house_check as HC
            from . import master_check as MC
            from . import validate as V
            from .nexus.pages import NexusPages
            from .nexus.session import NexusSession, SessionExpired
            from .nexus.uat import UatPages
            if args.interval is None:
                interval = 0                  # the validation wait replaces the fixed gap between cases
            with NexusSession(cfg, headless=False) as sess:
                try:
                    sess.ensure_logged_in()   # fail BEFORE sending anything
                except SessionExpired as exc:
                    print(f"Nothing was sent. {exc}")
                    return 2
                ui = UatPages(sess.page, cfg) if "uat" in cfg.selectors else NexusPages(sess.page, cfg)

                def after(case, case_rows):
                    if not any(r["status"] == "SENT" for r in case_rows):
                        return
                    if case.mode == "individual":
                        vrows.append({"case_id": case.id, "ref": "", "ipa": "", "nexus_status": "", "verdict": "SKIPPED",
                                      "appeared_after_s": "", "details": "UI validation of individual cases is not built yet", "evidence": ""})
                        return
                    print(f"\n{case.id}: sent, now validating in Nexus ...", flush=True)
                    try:
                        vrows.append(V.validate_case(cfg, ui, store, case))
                        _baseline(cfg, mapping_rows=[vrows[-1]])
                    except Exception as exc:
                        vrows.append({"case_id": case.id, "ref": "", "ipa": "", "nexus_status": "ERROR", "verdict": "ERROR",
                                      "appeared_after_s": "", "details": f"{type(exc).__name__}: {exc}"[:300], "evidence": ""})
                    r = vrows[-1]
                    print(f"{case.id}: {r['verdict']} {r['nexus_status']} {r['ipa']} (seen {r['appeared_after_s']}s after sending)", flush=True)
                    if r["nexus_status"] == "CREATED_IN_NEXUS":      # the pre-alert exists: now the Master data against the document
                        print(f"{case.id}: checking the Master data against the document ...", flush=True)
                        try:
                            mres = MC._check_one(cfg, ui, store, case, 60)
                        except Exception as exc:
                            mres = {"case_id": case.id, "ipa": "", "source": "", "verdict": "ERROR", "rows": [],
                                    "message": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"}
                        _baseline(cfg, [mres], "Master")
                        mrows.append(mres)
                        print(MC.format_report([mres]), flush=True)
                        print(f"{case.id}: checking the House data against the document ...", flush=True)
                        try:
                            hres = HC.check_house_one(cfg, ui, store, case, 60)
                        except Exception as exc:
                            hres = {"case_id": case.id, "ipa": "", "source": "", "verdict": "ERROR", "rows": [],
                                    "message": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"}
                        _baseline(cfg, [hres], "House")
                        hrows.append(hres)
                        print(MC.format_report([hres], "HOUSE DATA"), flush=True)
                        print(f"{case.id}: checking the Manifest, Invoice and Packing List data against the documents ...", flush=True)
                        try:
                            dres = DC.check_docs_one(cfg, ui, store, case, 60, DC.kinds_for(cfg, case))
                        except Exception as exc:
                            dres = [{"case_id": case.id, "kind": k, "ipa": "", "source": "", "verdict": "ERROR", "rows": [],
                                     "message": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"} for k in ("MANIFEST", "INVOICE", "PACKING")]
                        from . import bugs as _B
                        for k in {r["kind"] for r in dres}:
                            _baseline(cfg, [r for r in dres if r["kind"] == k], _B.DOC_TITLES[k])
                        drows.extend(dres)
                        for r in dres:
                            print(MC.format_report([r], DC.TITLES[r["kind"]]), flush=True)

                rows = T.run_suite(cfg, sender, chosen, args.dry_run, args.force, args.resend,
                                   interval_seconds=interval, after_case=after)
        else:
            rows = T.run_suite(cfg, sender, chosen, args.dry_run, args.force, args.resend, interval_seconds=interval)
        for r in rows:
            print(f"{r['case_id']:8} {r['status']:17} {r['subject'] or r['warnings']}")
        print(f"\nReport: {T.write_report(cfg, rows)}")
        if vrows:
            print("\nUI VALIDATION")
            for r in vrows:
                print(f"{r['case_id']:8} {r['verdict']:8} {r['nexus_status']:17} {r['ipa']}")
                for part in r["details"].split(" | "):
                    print(f"           {part}")
            print(f"Validation report: {V.write_report(cfg, vrows)}")
        if mrows:
            print(f"Master data report: {MC.write_report(cfg, mrows)}")
        if hrows:
            print(f"House data report: {MC.write_report(cfg, hrows, 'house_data')}")
        if vrows or mrows or hrows or drows:
            from . import bugs as B
            _note_bugs(cfg, mapping_rows=vrows, groups=[("Master", mrows), ("House", hrows)]
                       + [(B.DOC_TITLES[k], [r for r in drows if r["kind"] == k]) for k in ("MANIFEST", "INVOICE", "PACKING", "DEBITNOTE", "SHIPPERDOC")])
        for k in ("MANIFEST", "INVOICE", "PACKING", "DEBITNOTE", "SHIPPERDOC"):
            part = [r for r in drows if r["kind"] == k]
            if part:
                print(f"{DC.TITLES[k].title()} report: {MC.write_report(cfg, part, k.lower() + '_data')}")
        return 0

    if args.cmd == "send-local":
        from .local_sender import LocalSender
        from .store import Store
        done = LocalSender(cfg, Store(cfg.state_dir / "agent.db")).send_all(
            args.dry_run, args.refs, args.force)
        for pa in done:
            print(f"  {'WOULD SEND' if args.dry_run else 'SENT'}: {pa.subject}")
        print(f"{len(done)} email(s) {'would be ' if args.dry_run else ''}sent")
        return 0

    from .agent import Agent
    from .models import Status
    results, report = Agent(cfg, dry_run=args.dry_run, headless=not args.headed).run(
        refs=args.refs, use_gmail=not args.no_gmail)
    for r in results:
        print(f"{r.ref:<16} {r.status.value:<20} {'; '.join(r.messages)}")
    print(f"\nReport: {report / 'summary.html'}")
    ok = {Status.PASS, Status.DRY_RUN_OK, Status.APPROVAL_PENDING, Status.NOT_RECEIVED}
    return 0 if all(r.status in ok for r in results) else 2


if __name__ == "__main__":
    sys.exit(main())
