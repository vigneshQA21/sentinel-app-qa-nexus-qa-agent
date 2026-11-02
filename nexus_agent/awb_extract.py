"""Reads the Master Air Waybill from the source PDF by position. This is the SOURCE OF TRUTH the Nexus data is
checked against: whatever the document says is what Nexus must show. Anything that cannot be read is returned as
None (and reported as NOT_VERIFIABLE, never as a pass)."""
from __future__ import annotations

import re
from pathlib import Path

import pdfplumber

FLIGHT = re.compile(r"\b([A-Z0-9]{2}\d{2,4})/(\d{1,2})\b")


def _left(words, text_start: str, after: float = -1.0, x_max: float = 70):
    cands = [w for w in words if w["x0"] < x_max and w["text"].replace("\u2019", "'").startswith(text_start) and w["top"] > after]
    return min(cands, key=lambda w: w["top"]) if cands else None


def _lines(page, x0, top, x1, bottom) -> list[str]:
    if bottom <= top:
        return []
    txt = page.within_bbox((x0, max(top, 0), x1, min(bottom, page.height))).extract_text() or ""      # strict: only text fully inside
    return [ln.strip() for ln in txt.splitlines() if ln.strip()]


def _gutter(words, top: float, bottom: float, width: float) -> float | None:
    """x where the party column ends: the widest empty vertical strip (>= 10 pt) between the left text and the right-hand text
    (Air Waybill title, 'Copies 1, 2 and 3 ...', conditions) inside the shipper / consignee area, or None when there is none."""
    iv = sorted((w["x0"], w["x1"]) for w in words if top < w["top"] < bottom)
    cover: list[list[float]] = []
    for x0, x1 in iv:
        if cover and x0 <= cover[-1][1] + 0.5:
            cover[-1][1] = max(cover[-1][1], x1)
        else:
            cover.append([x0, x1])
    gaps = [(b[0] - a[1], a[1]) for a, b in zip(cover, cover[1:]) if 0.3 * width <= a[1] <= 0.75 * width and b[0] - a[1] >= 10]
    return max(gaps)[1] + 3 if gaps else None


def _nature_column(words, rest: str):
    """Nature-and-quantity text read from its own column: from the first word of the goods description (right of the rate / charge
    columns) down to the volume line, ignoring words that sit left of that column. Returns (text, volume) or None."""
    first = rest.split()[0] if rest.split() else ""
    starts = [w for w in words if w["text"] == first] if first else []
    if not starts:
        return None
    st = min(starts, key=lambda w: w["top"])
    stop = min([w["top"] for w in words if w["text"].startswith("Prepaid") and w["top"] > st["top"]] or [1e9])
    col = [w for w in words if w["x0"] >= st["x0"] - 2 and st["top"] - 1 <= w["top"] < stop - 1]
    rows: list[list[dict]] = []
    for w in sorted(col, key=lambda w: (round(w["top"]), w["x0"])):
        if rows and abs(rows[-1][0]["top"] - w["top"]) < 2.5:
            rows[-1].append(w)
        else:
            rows.append([w])
    out, vol = [], None
    for r in rows:
        ln = " ".join(w["text"] for w in sorted(r, key=lambda w: w["x0"]))
        out.append(ln)
        v = re.search(r"\bVOL\s*([\d.,]+)\s*([A-Z0-9]+)", ln)
        if v:
            vol = (v.group(1), v.group(2))
            break
    return (" ".join(out), vol) if out else None


def _generic_fill(out: dict, text: str) -> None:
    """Fills the fields that are still empty from the page text, for short forwarder forms like 'Check B/L 16015776084 CHJE262335 ...'.
    The party blocks are the whole page, so a name or address passes when it is anywhere on that page."""
    flat = " ".join(text.split())
    out["generic"] = True

    def put(key, value):
        if value not in (None, "") and not out.get(key):
            out[key] = value

    m = re.search(r"B/L\s*[:#]?\s*(\d{3})[-\s]?(\d{8})\b", flat, re.I) or re.search(r"\b(\d{3})-(\d{8})\b", flat)
    if m:
        put("awb_number", f"{m.group(1)}-{m.group(2)}")
        h = re.search(re.escape(m.group(1)) + r"-?" + re.escape(m.group(2)) + r"\s+([A-Z]{3,5}\d{5,8})\b", flat)
        put("house_number", h.group(1) if h else None)
    r = re.search(r"\b([A-Z]{3})\s+([A-Z0-9]{2})\s+([A-Z]{3})\s+([A-Z0-9]{2})\b", flat)
    if r and not out.get("seg_to"):
        out["seg_to"], out["seg_carrier"] = [r.group(1), r.group(3)], [r.group(2), r.group(4)]
    c = re.search(r"\b[A-Z]{3}\s+(PP|CC)\s+(?:PP|CC)\b", flat)
    put("charges_code", c.group(1) if c else None)
    d = re.search(r"([A-Z][A-Za-z .,/-]{3,60}?)\s+FREIGHT\s+(?:PREPAID|COLLECT)", flat)
    put("departure_airport", d.group(1).strip() if d else None)
    f = None
    for ln in text.splitlines():                      # one line: "BOMBAY, INDIA CX035 2026-08-22 NIL"
        f = re.match(r"\s*([A-Z][A-Za-z .,/-]{3,60}?)\s+([A-Z0-9]{2}\d{2,4})\s+(\d{4})-(\d{2})-(\d{2})", ln)
        if f:
            break
    if f:
        put("destination_airport", f.group(1).strip())
        if not out.get("flights"):
            out["flights"] = [(f.group(2), int(f.group(5)))]
        put("executed_on", f"{f.group(3)}-{f.group(4)}-{f.group(5)}")
    pcs = re.search(r"TOTAL\s*(\d+)\s*PALLET|\((\d+)\)\s*(?:PLT|PKG|CTN|PALLET)", flat, re.I)
    put("pieces", (pcs.group(1) or pcs.group(2)) if pcs else None)
    v = re.search(r"VOL(?:UME)?\s*[:.]?\s*([\d.,]+)\s*(M3|CBM)", flat, re.I)
    if v and not out.get("volume"):
        out["volume"] = (v.group(1), v.group(2).upper())
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not out.get("shipper_lines"):
        out["shipper_lines"] = lines
    if not out.get("consignee_lines"):
        out["consignee_lines"] = lines
    tail = []
    seen_flight = False
    for ln in lines:                                  # goods description = whatever follows the flight line
        if seen_flight:
            tail.append(ln)
        elif re.search(r"\b[A-Z0-9]{2}\d{2,4}\s+\d{4}-\d{2}-\d{2}\b", ln):
            seen_flight = True
    put("nature", " ".join(tail) if tail else None)


def extract_master(pdf_path: Path, page_index: int = 0) -> dict:
    """Master AWB fields of one page. Keys: awb_number, origin_code, shipper_lines, consignee_lines,
    departure_airport, destination_airport, seg_to (list), seg_carrier (list), currency, charges_code, flights
    [(number, day)], pieces, gross_weight, gross_unit, chargeable_weight, nature, volume, executed_on."""
    out: dict = {k: None for k in ("awb_number", "origin_code", "shipper_lines", "consignee_lines", "departure_airport",
                                    "destination_airport", "seg_to", "seg_carrier", "currency", "charges_code",
                                    "flights", "pieces", "gross_weight", "gross_unit", "chargeable_weight", "nature",
                                    "volume", "executed_on", "text", "reference", "incoterm", "house_number", "generic", "ocr")}
    with pdfplumber.open(str(pdf_path)) as pdf:
        pg = pdf.pages[page_index]
        words = pg.extract_words()
        text = pg.extract_text() or ""
        if len(text.strip()) < 25:                                  # a scan: read it with OCR, and treat it like a free-form page
            from . import ocr as _ocr
            text = _ocr.page_text(Path(pdf_path).read_bytes(), page_index)
            out["text"], out["ocr"] = text, True
            m = re.search(r"\b(\d{3})[- ]?(\d{8})\b", text)
            out["awb_number"] = f"{m.group(1)}-{m.group(2)}" if m else None
            m = re.search(r"\bHAWB\s*(?:No\.?)?\s*[:.]?\s*([A-Z]{2,5}\d{4,9})\b", text, re.I)
            out["house_number"] = m.group(1) if m else None
            _generic_fill(out, text)
            return out
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
        x1 = issued["x0"] - 2 if issued else None
        if x1 is None and ship and agent:                         # no 'Issued' anchor (e.g. lower-case 'issued by'): find the gap between the columns
            x1 = _gutter(words, ship["top"], agent["top"], W)
        x1 = x1 or W * 0.55

        if ship and cons:
            out["shipper_lines"] = _lines(pg, 0, ship["bottom"] - 0.5, x1, cons["top"] - 1)
        if cons and agent:
            out["consignee_lines"] = _lines(pg, 0, cons["bottom"] - 0.5, x1, agent["top"] - 1)
        if dep and to_hdr:
            ln = _lines(pg, 0, dep["bottom"] + 2, x1, to_hdr["top"] - 1)
            out["departure_airport"] = ln[0] if ln else None
        if to_hdr and dest:
            for ln in _lines(pg, 0, to_hdr["bottom"] + 2, W, dest["top"] - 1):
                m = re.match(r"^((?:[A-Z]{3}\s+[A-Z0-9]{2}\s+)+)([A-Z]{3})\s*(PP|CC|PC|CP|NC|NP|PX|XX)", ln)
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
        for ln in lines:                                           # "NICE C00401666 TERMS: EXW": reference number + incoterm
            m = re.search(r"\s([A-Z0-9][A-Z0-9/-]{4,})\s+TERMS:\s*([A-Z]{3})\b", ln)
            if m:
                out["reference"], out["incoterm"] = m.group(1), m.group(2)
                break
        for k, ln in enumerate(lines):
            m = re.match(r"^\s*(\d+)\s+([\d.,]+)\s?([KL])\b\s+[A-Z]?\s*([\d.,]+)\s*(.*)$", ln)
            if m:
                out["pieces"], out["gross_weight"], out["gross_unit"], out["chargeable_weight"] = \
                    m.group(1), m.group(2), m.group(3), m.group(4)
                # drop the rate / charge columns ("2.75 165.00" or "As Agreed") that sit before the goods description
                rest = re.sub(r"^(?:As Agreed|[\d.,]+)(?:\s+(?:As Agreed|[\d.,]+)){0,2}\s*", "", m.group(5)).strip()
                nature = [rest]
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
                col = _nature_column(words, rest)
                if col:                                              # text of OTHER columns can sit on the same lines (bank / credit text): read only this column
                    out["nature"] = col[0]
                    out["volume"] = col[1] or out["volume"]
                break
        m = re.search(r"\b(\d{1,2}-[A-Za-z]{3}-\d{2,4})\b", text[text.find("Currency Conversion"):] if "Currency Conversion" in text else "")
        out["executed_on"] = m.group(1) if m else None
        if ship is None or cons is None:                  # not the IATA layout (e.g. a short forwarder form): read what can be read from the text
            _generic_fill(out, text)
    return out
