"""Several Houses in one pre-alert: the checker validates the House of the sample (by bill), never simply the first row, and reports
every other House (empty bill / not in the sample) as a separate finding. Offline, no real data."""
from nexus_agent import house_pick as H

EXTRA = {"Record Type": "House", "Bill No.": "Enter No", "Shipper": "", "Consignee": "", "Page Nos.": "1", "Status": "Job Creation Pending"}
REAL = {"Record Type": "House", "Bill No.": "ABCDHKG/NGO26003", "Shipper": "SHIPPER CO", "Consignee": "CONSIGNEE CO", "Page Nos.": "1"}
MASTER = {"Record Type": "Master", "Bill No.": "MBL0000001"}


def test_the_house_printed_on_the_sample_is_chosen_even_when_it_is_not_first():
    rec, extras = H.choose([MASTER, EXTRA, REAL], "House", printed_text="HOUSE BILL ABCD-HKG/NGO-26003 SHIPPER CO")
    assert rec is REAL and extras == [EXTRA]


def test_expected_bill_wins_and_other_sample_houses_are_not_extra():
    other = {**REAL, "Bill No.": "HB0000002"}
    rec, extras = H.choose([EXTRA, other, REAL], "House", expected=["ABCDHKG/NGO26003", "HB0000002"])
    assert rec in (other, REAL) and extras == [EXTRA]                    # both are Houses of the sample: neither is an extra


def test_house_not_in_the_sample_is_extra_when_the_sample_is_known():
    stranger = {**REAL, "Bill No.": "ZZZ9999999"}
    rec, extras = H.choose([REAL, stranger], "House", expected=["ABCDHKG/NGO26003"])
    assert rec is REAL and extras == [stranger]


def test_without_sample_information_an_empty_house_is_still_extra():
    rec, extras = H.choose([EXTRA, REAL], "House")
    assert rec is REAL and extras == [EXTRA]


def test_viewer_parent_follows_the_chosen_bill():
    opts = ["Master (MBL0000001)", "House 1", "House (ABCDHKG/NGO26003)"]
    assert H.parent_for(opts, "House", REAL) == "House (ABCDHKG/NGO26003)"
    assert H.parent_for(opts, "Master", MASTER) == "Master (MBL0000001)"


def test_extra_house_is_reported_as_a_fail_row_with_what_nexus_shows():
    [r] = H.extra_rows([EXTRA], "House", ["ABCDHKG/NGO26003"])
    assert r["result"] == "FAIL" and "(empty)" in r["shown_in_nexus"] and "Job Creation Pending" in r["shown_in_nexus"]
    assert "ABCDHKG/NGO26003" in r["expected_from_document"]
