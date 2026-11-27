"""'As received': every document of a case in ONE email (real pre-alerts carry all their attachments). Made-up files."""
from pathlib import Path

from nexus_agent.local_sender import build_message


def test_one_email_carries_every_attachment(tmp_path: Path):
    a, b = tmp_path / "MAWB.pdf", tmp_path / "INVOICE.pdf"
    a.write_bytes(b"%PDF-1.4 a"); b.write_bytes(b"%PDF-1.4 b")
    msg = build_message([a, b], "to@example.com", "DXB-004 | x | AS RECEIVED (MASTER+INVOICE)", "DXB-004", org_line="Org:LAE")
    names = [p.get_filename() for p in msg.iter_attachments()]
    assert names == ["MAWB.pdf", "INVOICE.pdf"]
    body = msg.get_body(("plain",)).get_content()
    assert body.startswith("Org:LAE") and "MAWB.pdf, INVOICE.pdf" in body


def test_single_file_still_works(tmp_path: Path):
    a = tmp_path / "x.pdf"; a.write_bytes(b"%PDF")
    assert [p.get_filename() for p in build_message(a, "t@e.com", "s", "r").iter_attachments()] == ["x.pdf"]
