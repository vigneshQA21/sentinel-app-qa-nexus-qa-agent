from nexus_agent.live import Live


def test_live_page_tracks_case_state_and_checks(tmp_path):
    lv = Live(tmp_path, "suite REG-007")
    lv.feed("Sent 'REG-007 | QA agent trigger | Pre-Alert X | INDIVIDUAL | MASTER' to prealert.nexus@unifo.in (message id 1)")
    lv.feed("REG-007: waiting 89s for Nexus to process the email before checking")
    assert lv.cases["REG-007"]["state"] == "waiting for Nexus"
    lv.feed("REG-007  FAIL   CREATED_IN_NEXUS  ORAE26040499 IPA/1/2026-27")
    lv.feed("           MASTER: PASS (in Master)")
    lv.feed("           INVOICE: FAIL (not found in Nexus)")
    c = lv.cases["REG-007"]
    assert c["state"] == "FAIL" and [x[:2] for x in c["checks"]] == [("MASTER", "PASS"), ("INVOICE", "FAIL")]
    page = (tmp_path / "index.html").read_text()
    assert "REG-007" in page and 'http-equiv="refresh"' in page and "INVOICE FAIL" in page
    lv.finish()
    assert 'http-equiv="refresh"' not in (tmp_path / "index.html").read_text()


def test_html_run_report_lists_cases_findings_and_bug_sections(tmp_path):
    from nexus_agent.runreport import html_report
    reports = tmp_path / "_reports"; reports.mkdir()
    d = {"date": "2026-11-02", "sent": {"REG-009": 1}, "new": [], "still": [], "passed": [], "not_tested": [], "accepted": [], "to_retest": [],
         "cases": [{"case_id": "REG-002", "ipa": "IPA/2359/2026-27", "verdict": "PASS", "after": 184, "mapping": ["MASTER: PASS (in Master)", "PO: REVIEW (x)"],
                    "causes": ["a cause"], "seen": "IPA/2359/2026-27 seen -> Master (1): MAWBx1", "others": "", "counts": {"Master": {"PASS": 3, "FAIL": 1}},
                    "findings": [{"document": "Master", "field": "Date", "doc": "10 Aug", "nexus": "HK1, 10 Aug", "result": "FAIL", "note": "n", "source": "s"}]}]}
    page = html_report(d, reports)
    assert "REG-002" in page and "HK1, 10 Aug" in page and "a cause" in page and "REG-009" in page and "Data findings" in page
