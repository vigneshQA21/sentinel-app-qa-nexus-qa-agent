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

    if args.cmd == "validate-master":
        from . import master_check as MC
        from . import testsuite as T
        wanted = {c.upper() for c in args.cases}
        chosen = [c for c in T.read_cases(cfg) if c.id in wanted]
        results = MC.run_master_check(cfg, chosen, headless=args.headless, wait_seconds=args.wait)
        print(MC.format_report(results))
        print(f"\nReport: {MC.write_report(cfg, results)}")
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
        for r in rows:
            print(f"{r['case_id']:8} {r['verdict']:6} {r['nexus_status']:17} {r['ref']} {r.get('ipa', '')}")
            for part in r["details"].split(" | "):
                print(f"           {part}")
        print(f"\nReport: {V.write_report(cfg, rows)}")
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
        if args.validate and not args.dry_run:
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
                        mrows.append(mres)
                        print(MC.format_report([mres]), flush=True)

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
