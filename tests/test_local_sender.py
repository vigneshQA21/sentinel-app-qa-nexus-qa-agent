import base64
import io
import email
from email.policy import default

from pypdf import PdfReader
from reportlab.pdfgen import canvas

from nexus_agent.config import Config
from nexus_agent.local_sender import LocalSender
from nexus_agent.pdf_split import classify_page, detect_parts, find_hawbs
from nexus_agent.store import Store


TAG = "QA agent trigger / Don't delete / Regression testing"


def make_pdf(pages: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for t in pages:
        c.drawString(72, 750, t)
        c.showPage()
    c.save()
    return buf.getvalue()


class FakeSvc:
    def __init__(self):
        self.sent = []

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):
        self.sent.append(body["raw"])
        return self

    def modify(self, **kw):
        return self

    def execute(self):
        return {"id": f"msg{len(self.sent)}"}


class FakeFwd:
    def __init__(self):
        self.svc = FakeSvc()

    def _label_id(self):
        return "L1"


def setup(tmp_path):
    cfg = Config(root=tmp_path, config_dir=Config().root / "config")
    cfg.settings["local_docs"].update(archive_after_send=True, skip_already_sent=True)   # legacy behaviour under test
    kb = tmp_path / "knowledge_base"
    (kb / "consolidated").mkdir(parents=True)
    pdf = make_pdf(["MASTER AIR WAYBILL 176-12345675", "continuation page",
                    "HAWB No: UNF1001", "COMMERCIAL INVOICE", "PACKING LIST"])
    (kb / "consolidated" / "scan_001.pdf").write_bytes(pdf)
    store = Store(tmp_path / "state" / "agent.db")
    fwd = FakeFwd()
    return cfg, LocalSender(cfg, store, fwd), fwd, kb


def test_classify_and_group():
    kw = Config().settings["pdf_split"]["keywords"]
    assert classify_page("HAWB No: EVLHR035404", kw) == "HBL"
    assert classify_page("C A R G O M A N I F E S T", kw) == "MANIFEST"
    assert classify_page("nothing here", kw) is None
    parts = detect_parts(["Master Air Waybill", "x", "HAWB No: A1234", "COMMERCIAL INVOICE"], kw)
    assert [(p.label, p.pages) for p in parts] == [("MBL", [0, 1]), ("HBL", [2]), ("INVOICE", [3])]


def test_awb_form_order_and_hawb_label_variants(tmp_path):
    cfg = Config()
    kw = cfg.settings["pdf_split"]["keywords"]
    form = "Shipper's Name and Address Consignee's Name"
    assert [p.label for p in detect_parts([form, form], kw)] == ["MBL", "HBL"]
    # real case FJ-0002136: master form mentioning "cargo manifest", manifest, house form quoting MAWB#
    real = [form + " Cargo Manifest", "AIR CARGO MANIFEST MAWB", form + " MAWB# 176-2756 3922"]
    assert [p.label for p in detect_parts(real, kw)] == ["MBL", "MANIFEST", "HBL"]
    assert [p.label for p in detect_parts([form + " HAWB No: SAL1234"], kw)] == ["HBL"]
    texts = ["HAWB： TESTHAWB0003MAWB： 160-15585765", "HAWB : 142-65780659", "HAWB No: EVLHR035404",
             "HAWB NO AIR CARGO MANIFEST", "HAWB SLAC"]
    assert find_hawbs(texts, detect_parts(texts, kw), cfg) == ["TESTHAWB0003", "142-65780659", "EVLHR035404"]


def decode(raw):
    return email.message_from_bytes(base64.urlsafe_b64decode(raw), policy=default)


def test_screening_reports_contents_without_touching_file(tmp_path):
    cfg, sender, fwd, kb = setup(tmp_path)
    pdf = kb / "consolidated" / "scan_001.pdf"
    before = pdf.read_bytes()
    sc = sender.screen(pdf)
    assert sc.ref == "UNF1001" and sc.ok and sc.pages == 5
    assert sc.types == {"MBL", "HBL", "INVOICE", "PACKING"}
    assert sender.send_all(dry_run=True) and fwd.svc.sent == [] and pdf.read_bytes() == before


def test_consolidated_sent_unsplit_as_one_email_then_archived(tmp_path):
    cfg, sender, fwd, kb = setup(tmp_path)
    original = (kb / "consolidated" / "scan_001.pdf").read_bytes()
    done = sender.send_all()
    assert len(done) == 1 and len(fwd.svc.sent) == 1
    m = decode(fwd.svc.sent[0])
    assert m["Subject"] == TAG + " | Pre-Alert UNF1001 | CONSOLIDATED (MASTER+HOUSE+INVOICE+PACKING LIST)" and m["To"] == "prealert.nexus@unifo.in"
    atts = list(m.iter_attachments())
    assert len(atts) == 1 and atts[0].get_filename() == "scan_001.pdf"
    assert atts[0].get_payload(decode=True) == original          # byte-for-byte, not split
    assert (kb / "sent" / "UNF1001" / "scan_001.pdf").exists()
    assert not (kb / "consolidated" / "scan_001.pdf").exists()
    assert sender.send_all() == []
    (kb / "consolidated" / "scan_001.pdf").write_bytes(original)  # dropped again: still not resent
    assert sender.send_all() == [] and len(fwd.svc.sent) == 1


def test_failed_screening_blocks_send_unless_forced(tmp_path):
    cfg, sender, fwd, kb = setup(tmp_path)
    (kb / "consolidated" / "scan_001.pdf").write_bytes(make_pdf(["COMMERCIAL INVOICE only"]))
    sc = sender.screen(kb / "consolidated" / "scan_001.pdf")
    assert not sc.ok and set(sc.missing) == {"MBL", "HBL"}
    assert sender.send_all() == [] and fwd.svc.sent == []
    assert len(sender.send_all(force=True)) == 1 and len(fwd.svc.sent) == 1


def test_individual_files_one_email_each(tmp_path):
    cfg, sender, fwd, kb = setup(tmp_path)
    (kb / "consolidated" / "scan_001.pdf").unlink()
    ind = kb / "individual" / "UNF3003"
    ind.mkdir(parents=True)
    (ind / "UNF3003_INVOICE.pdf").write_bytes(make_pdf(["x"]))
    (ind / "UNF3003_HBL.pdf").write_bytes(make_pdf(["y"]))
    assert len(sender.send_all()) == 2
    assert {decode(r)["Subject"] for r in fwd.svc.sent} == {
        TAG + " | Pre-Alert UNF3003 | INDIVIDUAL | INVOICE", TAG + " | Pre-Alert UNF3003 | INDIVIDUAL | HOUSE"}
    assert not ind.exists()


def test_individual_type_from_filename_then_pdf_text(tmp_path):
    cfg, sender, fwd, kb = setup(tmp_path)
    d = kb / "individual" / "UNF4004"
    d.mkdir(parents=True)
    (d / "UNF4004_Master.pdf").write_bytes(make_pdf(["whatever"]))
    (d / "random_name.pdf").write_bytes(make_pdf(["HAWB No: UNF4004"]))
    (d / "mystery.pdf").write_bytes(make_pdf(["nothing recognisable"]))
    subjects = {it.path.name: it.subject for it in sender.pending() if it.ref == "UNF4004"}
    assert subjects["UNF4004_Master.pdf"].endswith("| INDIVIDUAL | MASTER")
    assert subjects["random_name.pdf"].endswith("| INDIVIDUAL | HOUSE")
    assert subjects["mystery.pdf"].endswith("| INDIVIDUAL | DOCUMENT")


def test_real_world_type_rules_and_priority_header(tmp_path):
    kw = Config().settings["pdf_split"]["keywords"]
    assert classify_page("MAWB NO: PCS HAWB SLAC HOUSE AIRWAYBILL LIST NOTE", kw) == "MANIFEST"   # not HOUSE
    assert classify_page("Packing details Crate No Package Dimension ... PACKING LIST ... INVOICE NO 1", kw) == "PACKING"
    assert classify_page("COMMERCIAL INVOICE Page 1 of 1", kw) == "INVOICE"
    assert classify_page("Terms of sales: This invoice is issued in accordance", kw) == "INVOICE"
    assert classify_page("DELIVERY NOTE 009041", kw) == "DELIVERY"
    from nexus_agent.local_sender import build_message
    f = tmp_path / "a.pdf"
    f.write_bytes(make_pdf(["x"]))
    m = build_message(f, "x@y.z", "s", "R", "high")
    assert m["X-Priority"] == "1 (Highest)" and m["Importance"] == "High"
    assert build_message(f, "x@y.z", "s", "R")["Importance"] is None


def test_reuse_mode_keeps_files_and_sends_again(tmp_path):
    cfg, sender, fwd, kb = setup(tmp_path)
    sender.ld.update(archive_after_send=False, skip_already_sent=False)     # the project default
    pdf = kb / "consolidated" / "scan_001.pdf"
    assert len(sender.send_all()) == 1 and pdf.exists() and not (kb / "sent").exists()
    assert len(sender.send_all()) == 1 and len(fwd.svc.sent) == 2             # same document, sent again
