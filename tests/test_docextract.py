"""'Document says' is never blank: the field's value is read from the document by label or by form, else the matching line, else
'no value found in the document'."""
from nexus_agent import docextract as X

BL = """SEA WAYBILL
B/L No.: PASU6472330910
OCEAN VESSEL / VOYAGE
WES SINA 487E
PORT OF LOADING: SHANGHAI, CHINA
PORT OF DISCHARGE: KOBE, JAPAN
PLACE AND DATE OF ISSUE
SHANGHAI 04 NOV 2026
CSLU5176844 40HQ 12 PKGS 4,550.000 KGS 58.000 CBM
FREIGHT COLLECT
TERMS: FOB SHANGHAI
"""


def test_labelled_values_are_extracted():
    assert X.extract("Port Of Loading", "", BL)[0] == "SHANGHAI, CHINA"
    assert X.extract("Port Of Discharge", "", BL)[0] == "KOBE, JAPAN"
    assert X.extract("Place", "", BL)[0] == "SHANGHAI 04 NOV 2026"            # heading alone on its line: the next line
    assert X.extract("Bill No.", "", BL)[0] == "PASU6472330910"


def test_values_recognised_by_their_form():
    assert X.extract("Container Type", "", BL)[0] == "40HQ"
    assert X.extract("Gross Weight Value", "4550", BL)[0] == "4,550.000 KGS"
    assert X.extract("Volume Of Goods Value", "", BL)[0] == "58.000 CBM"
    assert X.extract("No Of Pieces Value", "", BL)[0] == "12 PKGS"
    assert X.extract("Freight Payment", "", BL)[0] == "FREIGHT COLLECT"
    assert X.extract("Incoterm", "", BL)[0] == "FOB"


def test_matching_line_then_no_value():
    v, how = X.extract("Carrier Name", "COSCO SHIPPING LINES", "ISSUED BY COSCO SHIPPING LINES CO LTD\nPAGE 1")
    assert "COSCO SHIPPING LINES" in v and how
    assert X.extract("Consignee Address", "TOKYO JAPAN", "nothing related here") == (X.NO_VALUE, "")


def test_fill_blanks_never_leaves_document_says_empty():
    rows = X.fill_blanks([{"expected_from_document": ""}, {"expected_from_document": "  "}, {"expected_from_document": "X"}])
    assert [r["expected_from_document"] for r in rows] == [X.NO_VALUE, X.NO_VALUE, "X"]
