"""Field-level precision on top of the word-presence check (standard for every tenant, 26 Nov 2026).

Word presence ("every word of the Nexus value is somewhere on the bill") hides real bugs:
  * a field is compared with ITS OWN box on the bill, not with the whole page: Place of Delivery NAGOYA is not confirmed by
    NAGOYA printed under Port of Discharge; an empty box with a Nexus value is reported;
  * a party is the SAME party, not a party whose words are inside another one: "CONTEC CO.,LTD." is not "TAIWAN CONTEC CO.,LTD",
    "EVEX GLOBAL FREIGHT LIMITED" is not "GLOBAL FREIGHT SOLUTION LTD." (legal words and a branch suffix are ignored);
  * Shipper and Consignee mapped to the same Party ID while the bill prints two different parties.
Rows are only made stricter: a PASS can become FAIL / REVIEW with the reason; nothing becomes PASS here."""
from __future__ import annotations

import re

from . import docextract

LEGAL = {"CO", "COMPANY", "LTD", "LIMITED", "INC", "CORP", "CORPORATION", "LLC", "GMBH", "SA", "LTDA", "PVT", "PRIVATE", "KK",
         "PLC", "THE", "AND", "OY", "AB", "BV", "NV", "AG", "SRL", "SPA", "PTE", "PTY"}

# Nexus label (lower case) -> must be inside the box read for it (BOX fields: ports, places, vessel, voyage, bill / booking no.)
BOX_LABELS = re.compile(r"^(vessel( name)?|voyage( no\.?| number)?|port of loading|port of discharge|place of receipt|place of delivery|"
                        r"final destination|bill no\.?|booking( no\.?)?)$")


def _toks(s: str) -> set[str]:
    return {t for t in re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper()).split() if t}


def party_core(name: str) -> set[str]:
    """Distinctive words of a party name: no legal words, no branch suffix ('LOGISTEED Express, Ltd. - TYO' -> {LOGISTEED, EXPRESS})."""
    name = re.sub(r"\s+-\s+[A-Z]{2,4}\s*$", "", (name or "").strip(), flags=re.I)
    return {t for t in _toks(name) if t not in LEGAL and len(t) > 1}


NOISE = {"WAYBILL", "SHIPPER", "CONSIGNEE", "EXPORTER", "IMPORTER", "NOTIFY", "PARTY", "NAME", "ADDRESS", "COMPLETE", "AND", "OF", "SEA",
         "BILL", "LADING", "NON", "NEGOTIABLE"}


def same_party(nexus: str, document: str) -> bool:
    """The bill names the same party: its name at the START of the box (heading words skipped) has the same distinctive words.
    A box read as one line ('VAARNII OY Sorvaajankatu 15 00880 HELSINKI') is cut after the name; words before the name that are not
    headings count ('TAIWAN CONTEC CO.,LTD' is not 'CONTEC CO.,LTD.')."""
    a = party_core(nexus)
    if not a:
        return False
    words = re.sub(r"[^A-Za-z0-9 ]", " ", (document or "").splitlines()[0] if (document or "").strip() else "").upper().split()
    while words and words[0] in NOISE:
        words = words[1:]
    for k in range(1, min(len(words), 14) + 1):
        core = {t for t in words[:k] if t not in LEGAL and len(t) > 1}
        if core == a:
            return True
        if not core <= a:
            return False                                                   # the bill's name already has a word Nexus does not
    return False


def _set(r: dict, result: str, note: str, doc: str | None = None) -> None:
    r["result"] = result
    r["note"] = f"{note} | {r.get('note', '')}".strip(" |")
    if doc is not None:
        r["expected_from_document"] = doc
    r["strict"] = True


def box_fields(rows: list[dict], src: dict) -> None:
    """A PASS by word presence must also be inside the field's own box. Text bills only: OCR text of a scanned bill is not precise
    enough to say what a box prints (it stays REVIEW-by-eye there)."""
    if src.get("scanned"):
        return
    for r in rows:
        label = (r.get("label") or "").strip().lower()
        nexus = (r.get("shown_in_nexus") or "").strip()
        if r.get("result") != "PASS" or not nexus or not BOX_LABELS.match(label):
            continue
        dv, how = docextract.extract_from_source(src, r.get("label", ""), nexus)
        if not how.startswith(("by position", "after the label")):
            continue                                                       # no box located: word presence stays the evidence
        if dv.startswith(docextract.NO_VALUE):
            if "is blank" in dv or "blank" in how:
                _set(r, "REVIEW", f"the bill's own box for this field is blank, but Nexus shows '{nexus}' (filled from another field?)", dv)
            continue
        if not _toks(nexus) - _toks(dv):
            continue
        _set(r, "FAIL", f"not what the bill prints in this field's box ('{dv}'): the words are elsewhere on the bill", dv)


def _party_name_on_bill(src: dict, nexus_name: str) -> str:
    """The bill's party name line for this Nexus name: an equal party first, else the closest name line ('' when none)."""
    cells = docextract._layout_cells(src) if src.get("pdf") and not src.get("scanned") else []
    want = party_core(nexus_name)
    if not want:
        return ""
    if any(same_party(nexus_name, c) for c in cells):
        return next(c for c in cells if same_party(nexus_name, c))
    best = [(len(want & party_core(c)) / len(want), -len(c), c) for c in cells if party_core(c) and len(c) <= 80]
    best = [b for b in best if b[0] >= 0.5]
    return max(best)[2] if best else ""


def party_names(rows: list[dict], src: dict, boxes: dict) -> None:
    """Shipper / Consignee name: the same party as the bill's box (when the box is known) or as a name line of the bill."""
    for r in rows:
        sec, label = (r.get("section") or ""), (r.get("label") or "")
        nexus = (r.get("shown_in_nexus") or "").strip()
        is_party = (sec in ("Shipper", "Consignee") and label == "Name") or (sec == "Shipment Details" and label in ("Shipper", "Consignee"))
        if not is_party or r.get("result") not in ("PASS", "REVIEW") or not nexus or re.match(r"^\W*SAME\s+AS\b", nexus, re.I):
            continue
        key = (sec if sec in ("Shipper", "Consignee") else label).lower()
        if key in boxes:                                                   # the party's own box, read by position
            first = (boxes[key][0] or "").strip().splitlines()[0] if (boxes[key][0] or "").strip() else ""
            bill = first or boxes[key][0]
        else:
            bill = _party_name_on_bill(src, nexus)
        if not bill:
            continue
        if same_party(nexus, bill):
            continue
        extra_doc = party_core(bill) - party_core(nexus)
        extra_nx = party_core(nexus) - party_core(bill)
        why = []
        if extra_nx:
            why.append(f"Nexus has {', '.join(sorted(extra_nx))} that the bill's name does not")
        if extra_doc:
            why.append(f"the bill's name has {', '.join(sorted(extra_doc))} that Nexus does not")
        _set(r, "FAIL", f"a different party: the bill prints '{bill}' ({'; '.join(why)})", bill)


def _distinct_parties(src: dict, boxes: dict, nexus_name: str) -> list[str]:
    """The different party names the bill prints that hold the Nexus name's words (TAIWAN CONTEC CO.,LTD and CONTEC CO.,LTD = two)."""
    if boxes.get("shipper") and boxes.get("consignee"):
        names = [(boxes[k][0] or "").strip().splitlines()[0] for k in ("shipper", "consignee") if (boxes[k][0] or "").strip()]
        by_core: dict[frozenset, str] = {}
        for n in names:
            if party_core(n):
                by_core.setdefault(frozenset(party_core(n)), n)              # ACME CO LTD = ACME CO., LTD.
        return list(by_core.values())
    want = party_core(nexus_name)
    cells = docextract._layout_cells(src) if src.get("pdf") and not src.get("scanned") else []
    seen: dict[frozenset, str] = {}
    for c in cells:
        core = party_core(c)
        if want and want <= core and len(c) <= 80 and re.search(r"\b(CO|LTD|LIMITED|INC|CORP|LLC|GMBH|LTDA|KK|OY)\b", c.upper()):
            seen.setdefault(frozenset(core), c)
    return list(seen.values())


def same_party_id(rows: list[dict], src: dict | None = None, boxes: dict | None = None) -> list[dict]:
    """Shipper and Consignee with the same Party ID while the bill prints two different parties: one FAIL row."""
    pid = {sec: (r.get("shown_in_nexus") or "").strip() for r in rows for sec in ("Shipper", "Consignee")
           if r.get("section") == sec and r.get("label") == "Party ID"}
    s, c = pid.get("Shipper", ""), pid.get("Consignee", "")
    if not s or s != c or re.fullmatch(r"(?i)select( option)?", s):
        return []
    nexus_name = next(((r.get("shown_in_nexus") or "") for r in rows if r.get("section") == "Shipper" and r.get("label") == "Name"), "")
    parties = _distinct_parties(src or {}, boxes or {}, nexus_name)
    if len(parties) == 1:
        return []                                                         # the bill really prints the same party twice
    printed = " / ".join(f"'{x}'" for x in parties) if parties else "see the bill's Shipper and Consignee boxes"
    return [{"section": "Parties", "label": "Shipper / Consignee Party ID", "field": "Parties · Shipper / Consignee Party ID",
             "expected_from_document": f"two different parties: {printed}",
             "shown_in_nexus": f"Shipper ID {s} = Consignee ID {c}", "result": "FAIL", "strict": True,
             "note": "Shipper and Consignee are mapped to the same Party ID: one of them is matched to the other's party"}]


def tighten(rows: list[dict], src: dict, boxes: dict | None = None) -> list[dict]:
    box_fields(rows, src)
    party_names(rows, src, boxes or {})
    return rows + same_party_id(rows, src, boxes or {})
