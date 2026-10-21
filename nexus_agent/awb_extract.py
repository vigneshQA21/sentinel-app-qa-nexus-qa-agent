"""Reads the Master Air Waybill from the source PDF by position. This is the SOURCE OF TRUTH the Nexus data is
checked against: whatever the document says is what Nexus must show. Anything that cannot be read is returned as
None (and reported as NOT_VERIFIABLE, never as a pass)."""
from __future__ import annotations

import re
from pathlib import Path

import pdfplumber

FLIGHT = re.compile(r"\b([A-Z0-9]{2}\d{2,4})/(\d{1,2})\b")


def _left(words, text_start: str, after: float = -1.0, x_max: float = 70):
    cands = [w for w in words if w["x0"] < x_max and w["text"].startswith(text_start) and w["top"] > after]
    return min(cands, key=lambda w: w["top"]) if cands else None


def _lines(page, x0, top, x1, bottom) -> list[str]:
    if bottom <= top:
        return []
    txt = page.within_bbox((x0, max(top, 0), x1, min(bottom, page.height))).extract_text() or ""      # strict: only text fully inside
    return [ln.strip() for ln in txt.splitlines() if ln.strip()]


def extract_master(pdf_path: Path, page_index: int = 0) -> dict:
    """Master AWB fields of one page. Keys: awb_number, origin_code, shipper_lines, consignee_lines,
    departure_airport, destination_airport, seg_to (list), seg_carrier (list), currency, charges_code, flights
    [(number, day)], pieces, gross_weight, gross_unit, chargeable_weight, nature, volume, executed_on."""
    out: dict = {k: None for k in ("awb_number", "origin_code", "shipper_lines", "consignee_lines", "departure_airport",
                                    "destination_airport", "seg_to", "seg_carrier", "currency", "charges_code",
                                    "flights", "pieces", "gross_weight", "gross_unit", "chargeable_weight", "nature",
                                    "volume", "executed_on", "text")}
    with pdfplumber.open(str(pdf_path)) as pdf:
        pg = pdf.pages[page_index]
        words = pg.extract_words()
        text = pg.extract_text() or ""
        out["text"] = text
        W = pg.width

        m = re.search(r"\b(\d{3}-\d{8})\b", text)
        out["awb_number"] = m.group(1) if m else None
        m = re.search(r"\b\d{3}([A-Z]{3})\s?\d{8}\b", text)
        out["origin_code"] = m.group(1) if m else None

        ship = _left(words, "Shipper's")
        cons = _left(words, "Consignee's")
        agent = _left(words, "Issuing")
        dep = _left(words, "Airport", after=agent["top"] if agent else -1)
        to_hdr = _left(words, "To", after=dep["top"] if dep else -1)
        dest = _left(words, "Airport", after=to_hdr["top"] if to_hdr else -1)
        hand = _left(words, "Handling", after=dest["top"] if dest else -1)
        issued = next((w for w in words if w["text"] == "Issued" and ship and ship["top"] <= w["top"] <= (cons["top"] if cons else 1e9)), None)
        x1 = issued["x0"] - 2 if issued else W * 0.55

        if ship and cons:
            out["shipper_lines"] = _lines(pg, 0, ship["bottom"] + 2, x1, cons["top"] - 1)
        if cons and agent:
            out["consignee_lines"] = _lines(pg, 0, cons["bottom"] + 2, x1, agent["top"] - 1)
        if dep and to_hdr:
            ln = _lines(pg, 0, dep["bottom"] + 2, x1, to_hdr["top"] - 1)
            out["departure_airport"] = ln[0] if ln else None
        if to_hdr and dest:
            for ln in _lines(pg, 0, to_hdr["bottom"] + 2, W, dest["top"] - 1):
                m = re.match(r"^((?:[A-Z]{3}\s+[A-Z0-9]{2}\s+)+)([A-Z]{3})\s+(PP|CC|PC|CP|NC|NP|PX|XX)", ln)
                if m:
                    pairs = re.findall(r"([A-Z]{3})\s+([A-Z0-9]{2})", m.group(1))
                    out["seg_to"] = [p[0] for p in pairs]
                    out["seg_carrier"] = [p[1] for p in pairs]
                    out["currency"], out["charges_code"] = m.group(2), m.group(3)
                    break
        if dest and hand:
            ln = _lines(pg, 0, dest["bottom"] + 2, x1, hand["top"] - 1)
            if ln:
                first = ln[0]
                cut = FLIGHT.search(first)
                out["destination_airport"] = (first[:cut.start()] if cut else first).strip()
                out["flights"] = [(a, int(b)) for a, b in FLIGHT.findall(first)]

        lines = text.splitlines()
        for k, ln in enumerate(lines):
            m = re.match(r"^\s*(\d+)\s+([\d.,]+)\s?([KL])\b\s+[A-Z]?\s*([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s*(.*)$", ln)
            if m:
                out["pieces"], out["gross_weight"], out["gross_unit"], out["chargeable_weight"] = \
                    m.group(1), m.group(2), m.group(3), m.group(4)
                nature = [m.group(7).strip()]
                for nxt in lines[k + 1:k + 8]:
                    if re.match(r"^\d+\s+[\d.]+\s+[\d.]+$", nxt.strip()) or re.search(
                            r"Prepaid|Weight Charge|Valuation|Currency Conversion|Executed|Signature|Other Charges", nxt):
                        break
                    nature.append(nxt.strip())
                    v = re.search(r"\bVOL\s*([\d.,]+)\s*([A-Z0-9]+)", nxt)
                    if v:
                        out["volume"] = (v.group(1), v.group(2))
                        break                                    # the goods description ends with the volume line
                out["nature"] = " ".join(x for x in nature if x)
                break
        m = re.search(r"\b(\d{1,2}-[A-Za-z]{3}-\d{2,4})\b", text[text.find("Currency Conversion"):] if "Currency Conversion" in text else "")
        out["executed_on"] = m.group(1) if m else None
    return out
