from datetime import date

from nexus_agent.devlog import append_log


def test_notes_go_under_the_days_heading_and_old_entries_stay(tmp_path):
    f = tmp_path / "docs" / "PROGRESS_LOG.md"
    f.parent.mkdir()
    f.write_text("# Progress log (day by day)\n\n## 2026-10-15\n\n- first day\n\n## 2026-10-16\n\n- second day\n", encoding="utf-8")
    assert append_log(f, "added   a check", date(2026, 10, 16)) == "## 2026-10-16"
    append_log(f, "and another", date(2026, 10, 16))
    append_log(f, "late note for day one", date(2026, 10, 15))
    text = f.read_text(encoding="utf-8")
    assert text.index("- first day") < text.index("- late note for day one") < text.index("## 2026-10-16")
    assert text.index("- second day") < text.index("- added a check") < text.index("- and another")     # extra spaces tidied, order kept


def test_a_new_day_gets_a_new_heading_and_a_missing_file_is_created(tmp_path):
    f = tmp_path / "PROGRESS_LOG.md"
    append_log(f, "hello", date(2026, 10, 25))
    append_log(f, "second", date(2026, 10, 25))
    append_log(f, "next day", date(2026, 10, 26))
    assert f.read_text(encoding="utf-8").split("\n") == ["# Progress log (day by day)", "", "## 2026-10-25", "", "- hello", "- second", "", "## 2026-10-26", "", "- next day", ""]


def test_a_heading_with_a_title_after_the_date_is_the_same_day(tmp_path):
    f = tmp_path / "PROGRESS_LOG.md"
    f.write_text("# Progress log (day by day)\n\n## 2026-10-24  (day 5: Google)\n\n- one\n\n## 2026-10-25\n\n- next\n", encoding="utf-8")
    append_log(f, "two", date(2026, 10, 24))
    text = f.read_text(encoding="utf-8")
    assert text.count("## 2026-10-24") == 1 and text.index("- one") < text.index("- two") < text.index("## 2026-10-25")
