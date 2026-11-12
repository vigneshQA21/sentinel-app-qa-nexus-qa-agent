from pathlib import Path

from nexus_agent import phases as PH


def _files(*names):
    return [Path(f"FJ-1 - {n}.pdf") for n in names]


def test_phase_manifest_is_only_the_manifest():
    got = PH.plan(_files("Master", "Manifest", "House", "Invoice"), "FJ-1", "manifest")
    assert [f.name for f in got] == ["FJ-1 - Manifest.pdf"]


def test_phase_house_master_sends_all_houses_first_then_master():
    got = PH.plan(_files("Master", "Manifest", "House 2", "House 1", "Invoice"), "FJ-1", "house-master")
    assert [f.name for f in got] == ["FJ-1 - House 1.pdf", "FJ-1 - House 2.pdf", "FJ-1 - Master.pdf"]


def test_phase_master_house_then_the_rest_in_regression_order():
    got = PH.plan(_files("Packing List", "Invoice", "House", "Manifest", "Master", "Certificate of Origin"), "FJ-1", "master-house")
    assert [PH._kind(f, "FJ-1") for f in got] == ["Master", "House", "Manifest", "Invoice", "Packing List", "Certificate of Origin"]


def test_sample_without_the_document_is_skipped():
    assert PH.plan(_files("Master", "House"), "FJ-1", "manifest") == []
