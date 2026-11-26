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


# --- small boxes read by position on a laid-out page (fake page: words with coordinates, no real document) ---
from nexus_agent import docvalue as V


class FakePage:
    width = 600.0

    def __init__(self, rows):
        """rows: [(top, [(x0, text), ...]), ...]; each word is 6 pt per character wide."""
        self.words = [{"text": t, "x0": x, "x1": x + 6 * len(t), "top": top, "bottom": top + 9} for top, ws in rows for x, t in ws]

    def extract_words(self, **k):
        return [dict(w) for w in self.words]


def words(x, text):
    out = []
    for t in text.split():
        out.append((x, t)); x += 6 * len(t) + 4
    return out


TITLE_CASE = FakePage([
    (100, words(40, "Vessel") + words(200, "Port of loading") + words(360, "Port of discharge")),
    (112, words(40, "OOCL PORTUGAL 007E") + words(200, "HAMBURG") + words(360, "NAGOYA")),
    (124, words(40, "Pick-up inland") + words(200, "Port of transshipment") + words(360, "Place of delivery")),
    (136, words(200, "BUSAN")),
    (148, words(40, "Marks and nos.") + words(200, "Number and kind of packages; description of goods")),
    (300, words(40, "subject to the Port of Discharge or Place of Delivery named in the contract")),
])


def test_title_case_headings_that_fill_their_cell_are_read_by_position():
    assert V.small_box_on_page(TITLE_CASE, "port of loading") == "HAMBURG"
    assert V.small_box_on_page(TITLE_CASE, "port of discharge") == "NAGOYA"
    assert V.small_box_on_page(TITLE_CASE, "vessel") == "OOCL PORTUGAL 007E"


def test_an_empty_box_is_reported_blank_never_the_neighbouring_value():
    assert V.small_box_on_page(TITLE_CASE, "place of delivery") == V.BLANK     # BUSAN belongs to Port of transshipment


def test_vessel_box_with_voyage_is_split():
    assert X.split_voyage("OOCL PORTUGAL 007E") == ("OOCL PORTUGAL", "007E")
    assert X.split_voyage("ONE RELIABILITY") == ("ONE RELIABILITY", "")


def test_heading_inside_a_sentence_of_terms_is_ignored():
    terms = FakePage([(300, words(40, "subject to the Port of Discharge or Place of Delivery named in the contract"))])
    assert V.small_box_on_page(terms, "place of delivery") == ""


def test_banner_across_the_box_edge_is_not_the_box_value():
    page = FakePage([
        (100, words(40, "Port of Loading") + words(200, "Place of Delivery. Applicable only when used as Multimodal B/L")),
        (112, words(40, "Santos, SP, Brazil")),
        (124, words(150, "PARTICULARS FURNISHED BY SHIPPER")),
    ])
    assert V.small_box_on_page(page, "port of loading") == "Santos, SP, Brazil"
    assert V.small_box_on_page(page, "place of delivery") == V.BLANK


def test_value_cell_on_a_form_without_printed_labels():
    cells = ["HKX2618575", "HKNGO26126471", "YM INCEPTION / 250N", "HONG KONG", "NAGOYA", "16-OCT-2026"]
    assert X.matching_cell(cells, "YM INCEPTION") == "YM INCEPTION / 250N"
    assert X.matching_cell(cells, "HKNGO26126471") == "HKNGO26126471"
    assert X.matching_cell(cells, "BUSAN") == ""


def test_an_address_over_several_lines_is_read_as_one_block():
    text = "Notify\nLOGISTEED EXPRESS, LTD.\n26F OFFICE X TRITON SQUARE,\n1-8-10, HARUMI, CHUO-KU,\n104-6026, TOKYO, JAPAN\nFAX: 03"
    v = X.matching_line(text, "26F OFFICE X TRITON SQUARE ,1-8-10 , HARUMI , CHUO-KU , 104-6026 , TOKYO")
    assert v.startswith("26F OFFICE X TRITON SQUARE") and "TOKYO" in v and "Notify" not in v


def test_party_address_is_read_under_the_name_on_a_form_without_labels():
    lines = ["   GLOBAL FREIGHT SOLUTION LTD.", "   ROOM 6, 9/F, CAMERON CENTRE,", "   TSUEN WAN, HONG KONG", "", "",
             "   LOGISTEED EXPRESS, LTD.", "   HARUMI TRITON SQUARE,", "", "   OFFICE TOWER X 26TH FLOOR,   other column text", "", "",
             "   SAME AS CONSIGNEE"]
    assert X.party_block(lines, "LOGISTEED Express, Ltd. - TYO") == ("LOGISTEED EXPRESS, LTD.", "HARUMI TRITON SQUARE, OFFICE TOWER X 26TH FLOOR,")
    assert X.party_block(lines, "GLOBAL FREIGHT SOLUTION LTD.")[1] == "ROOM 6, 9/F, CAMERON CENTRE, TSUEN WAN, HONG KONG"
    assert X.party_block(lines, "UNKNOWN PARTY CO") == ("", "")


def test_labelled_values_must_have_the_fields_shape():
    text = "Shipper Country of Origin Bill/Lading Number\nVAARNII OY WBL0000000730\nSEAL. NO.:\nOOLJYY0948"
    assert X.extract("Bill No.", "", text)[0] == "WBL0000000730"                  # not the shipper name on the same line
    assert X.extract("Seal No", "", text)[0] == "OOLJYY0948"                      # not 'NO.:'


def test_placeholders_and_shared_boxes():
    assert X.PLACEHOLDER.match("Enter No") and X.PLACEHOLDER.match("Select option") and not X.PLACEHOLDER.match("NAGOYA")
    assert X._narrow("vessel name", "OOCL PORTUGAL / 007E", "cell")[0] == "OOCL PORTUGAL"
    assert X._narrow("voyage number", "OOCL PORTUGAL / 007E", "cell")[0] == "007E"
    assert X._narrow("place", "19-08-2026", "label")[0].startswith(X.NO_VALUE)
    assert X._narrow("place", "HELSINKI, 2026-08-19", "label")[0] == "HELSINKI, 2026-08-19"
