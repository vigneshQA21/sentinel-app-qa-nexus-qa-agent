"""A sample file labelled with one document type whose printed title is another type is flagged (no real documents)."""
from nexus_agent import label_check as L


def test_debit_note_label_on_an_invoice_is_flagged():
    assert L.check_file("03 DEBIT NOTE - DN FCA.pdf", "INVOICE Reference #: 123 BILL to: X") == "labelled DEBIT NOTE but the document's title says INVOICE"


def test_matching_or_unknown_labels_pass():
    assert L.check_file("02 DEBIT NOTE - X.pdf", "DEBIT NOTE SGH1 ... INVOICE DATE 04-Nov") == ""      # the real title is there
    assert L.check_file("01 MASTER - X.pdf", "INVOICE") == ""                                        # labels without a rule
    assert L.check_file("04 INVOICE - X.pdf", "no title words") == ""
