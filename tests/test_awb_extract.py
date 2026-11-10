

def test_awb_layouts_that_were_not_verifiable(tmp_path):
    """REG-005: AWB number split in two, flights without the airline prefix, routing line with the carrier NAME, volume as CBM.
    REG-006: routing line with the flight and date, 'PP PP' charge line, month glued to the flight date."""
    from pathlib import Path
    from nexus_agent import awb_extract as A
    r5 = A.extract_master(Path("samples/REG-005/FJ-0000883 - Consolidated - Sh.pdf"), 0)
    assert r5["awb_number"] == "057-05262084" and r5["origin_code"] == "TLV" and r5["seg_to"] == ["CDG", "BLR"]
    assert r5["flights"] == [("963", 28), ("194", 29)] and r5["charges_code"] == "PP" and r5["volume"] == (".1284", "CBM")
    h5 = A.extract_master(Path("samples/REG-005/FJ-0000883 - Consolidated - Sh.pdf"), 2)
    assert h5["house_number"] == "SNY06007868" and h5["charges_code"] == "CC"
    m6 = A.extract_master(Path("samples/REG-006/FJ-0000518 - MA-1.pdf"), 0)
    assert m6["origin_code"] == "PVG" and m6["seg_to"] == ["HKG", "MAA"] and m6["flights"] == [("CX051", 20), ("CX2047", 20)] and m6["charges_code"] == "PP"
    h6 = A.extract_master(Path("samples/REG-006/FJ-0000518 - HA-4.pdf"), 0)
    assert h6["seg_to"] == ["MAA"] and h6["charges_code"] == "CC"
