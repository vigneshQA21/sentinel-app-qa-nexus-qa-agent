"""A tiny stand-in for the Nexus web UI, used to test the agent end to end.

Run:  python mock_nexus/app.py      (http://127.0.0.1:5055, user demo / demo)

Seeded shipments:
  UNF1001  all good, but shipper country is ' in ' -> agent autofixes to IN  -> PASS
  UNF1002  invoice left 'Unclassified'                                         -> CLASSIFICATION_FAIL
  UNF1003  mock TMS XML drops part of the consignee name                       -> XML_MISMATCH
  UNF1005  shipper city empty; fixed by corrections/UNF1005.yaml if present     -> PASS / NEEDS_REVIEW
"""
from __future__ import annotations

import copy
import os
import time
from functools import wraps
from xml.sax.saxutils import escape

from flask import Flask, redirect, render_template_string, request, session, url_for

APPROVAL_DELAY = float(os.getenv("MOCK_APPROVAL_DELAY", "2"))

DOCS_OK = [("MAWB_17612345675.pdf", "MAWB"), ("HAWB.pdf", "HAWB"),
           ("Invoice_8812.pdf", "Commercial Invoice"), ("PackingList.pdf", "Packing List")]

BASE = dict(mawb="176-12345675", shipper_name="Acme Textiles Pvt Ltd", shipper_address1="12 Mill Road",
            shipper_city="Tiruppur", shipper_country="IN", consignee_name="Nordic Retail AB",
            pieces="12", gross_weight="245.50", origin="MAA", destination="ARN", etd="15-Oct-2026")

SEED = {
    "UNF1001": dict(docs=DOCS_OK, data={**BASE, "hawb": "UNF1001", "shipper_country": " in "}),
    "UNF1002": dict(docs=[DOCS_OK[0], DOCS_OK[1], ("Invoice_8813.pdf", "Unclassified"), DOCS_OK[3]],
                    data={**BASE, "hawb": "UNF1002"}),
    "UNF1003": dict(docs=DOCS_OK, data={**BASE, "hawb": "UNF1003", "consignee_name": "Nordic Retail AB Stockholm"},
                    xml_bug=True),
    "UNF1005": dict(docs=DOCS_OK, data={**BASE, "hawb": "UNF1005", "shipper_city": ""}),
}
# Shipments with document sections (Master / House), as the real pre-alert page shows them.
MAP_OK = {"Master": [("Master_AWB.pdf", "Master AWB"), ("Manifest.pdf", "Manifest")],
          "House": [("House_AWB.pdf", "House AWB"), ("Invoice.pdf", "Commercial Invoice"), ("PackingList.pdf", "Packing List")]}
MAP_BAD = {"Master": [("Master_AWB.pdf", "Master AWB"), ("Manifest.pdf", "Manifest"), ("Invoice.pdf", "Commercial Invoice")],
           "House": [("House_AWB.pdf", "House AWB")]}                       # invoice under Master, no packing list
SEED["UNF2001"] = dict(docs=[d for v in MAP_OK.values() for d in v], mapping=MAP_OK, data={**BASE, "hawb": "UNF2001"})
SEED["UNF2002"] = dict(docs=[d for v in MAP_BAD.values() for d in v], mapping=MAP_BAD, data={**BASE, "hawb": "UNF2002"})
FIELDS = ["mawb", "hawb", "shipper_name", "shipper_address1", "shipper_city", "shipper_country",
          "consignee_name", "pieces", "gross_weight", "origin", "destination", "etd"]

app = Flask(__name__)
app.secret_key = "mock-nexus"
DB: dict = {}


def reset():
    DB.clear()
    for ref, s in copy.deepcopy(SEED).items():
        DB[ref] = {**s, "pushed_at": None, "toast": ""}


reset()


def login_required(fn):
    @wraps(fn)
    def inner(*a, **kw):
        if not session.get("user"):
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return inner


def tms_status(s):
    if not s["pushed_at"]:
        return "Not pushed"
    return "Approved" if time.time() - s["pushed_at"] >= APPROVAL_DELAY else "Pending Approval"


def tms_xml(s):
    d = dict(s["data"])
    if s.get("xml_bug"):
        d["consignee_name"] = d["consignee_name"][:16]          # simulated mapping bug
    day, mon, yr = d["etd"].split("-")
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    etd_iso = f"{yr}-{months.index(mon) + 1:02d}-{int(day):02d}"
    e = {k: escape(str(v)) for k, v in d.items()}
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<TMSShipment>
  <Header><MasterBill>{e['mawb']}</MasterBill><HouseBill>{e['hawb']}</HouseBill></Header>
  <Shipper><Name>{e['shipper_name']}</Name><Address1>{e['shipper_address1']}</Address1><City>{e['shipper_city']}</City><Country>{e['shipper_country']}</Country></Shipper>
  <Consignee><Name>{e['consignee_name']}</Name></Consignee>
  <Cargo><Pieces>{e['pieces']}</Pieces><GrossWeight unit="KG">{e['gross_weight']}</GrossWeight></Cargo>
  <Route><Origin>{e['origin']}</Origin><Destination>{e['destination']}</Destination><ETD>{etd_iso}</ETD></Route>
</TMSShipment>"""


LAYOUT = """<!doctype html><html><head><meta charset="utf-8"><title>Nexus (mock)</title>
<style>body{font-family:sans-serif;margin:20px}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 8px}
input[disabled]{background:#f3f3f3;color:#000}#toast{color:green}</style></head><body>
{% if session.user %}<div>Nexus · <span id="user-menu">{{ session.user }}</span> · <a href="/logout">logout</a></div><hr>{% endif %}
{{ body|safe }}</body></html>"""


def page(body_tpl, **ctx):
    return render_template_string(LAYOUT, body=render_template_string(body_tpl, **ctx))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == "demo" and request.form.get("password") == "demo":
            session["user"] = "demo"
            return redirect(url_for("prealerts"))
    return page("""<h3>Nexus login</h3><form method="post">
      <input id="username" name="username" placeholder="user"> <input id="password" name="password" type="password">
      <button id="login-btn" type="submit">Login</button></form>""")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@app.route("/prealerts")
@login_required
def prealerts():
    q = request.args.get("q", "").strip().upper()
    rows = [(r, s) for r, s in DB.items() if not q or q in r]
    return page("""<h3>Pre-alerts</h3><form><input id="search" name="q" value="{{q}}">
      <button id="search-btn">Search</button></form>
      <table id="prealerts"><thead><tr><th>HAWB</th><th>MAWB</th><th>TMS</th><th></th></tr></thead><tbody>
      {% for r, s in rows %}<tr><td>{{r}}</td><td>{{s.data.mawb}}</td><td>{{status(s)}}</td>
      <td><a class="open-link" href="/shipment/{{r}}">Open</a></td></tr>{% endfor %}</tbody></table>""",
                q=q, rows=rows, status=tms_status)


@app.route("/shipment/<ref>")
@login_required
def shipment(ref):
    s = DB[ref]
    toast, s["toast"] = s["toast"], ""
    st = tms_status(s)
    return page("""<h3>Pre-alert {{ref}}</h3><div id="toast">{{toast}}</div>
      {% if s.mapping %}{% for sec, docs in s.mapping.items() %}<div data-section="{{sec}}"><h4>{{sec}}</h4>
      <table><tbody>{% for n, t in docs %}<tr class="doc-row"><td class="doc-name">{{n}}</td><td class="doc-type">{{t}}</td></tr>{% endfor %}</tbody></table></div>
      {% endfor %}{% endif %}
      <h4>Documents</h4><table id="documents"><tbody>
      {% for n, t in s.docs %}<tr><td class="doc-name">{{n}}</td><td class="doc-type">{{t}}</td></tr>{% endfor %}
      </tbody></table>
      <h4>Shipper data</h4><form id="shipper-form" method="post" action="/shipment/{{ref}}/shipper">
      {% for f in fields %}<div><label>{{f}}</label> <input id="f-{{f}}" name="{{f}}" value="{{s.data[f]}}" disabled></div>{% endfor %}
      <button type="button" id="edit-shipper" onclick="document.querySelectorAll('#shipper-form input').forEach(i=>i.disabled=false)">Edit</button>
      <button id="save-shipper" type="submit">Save</button></form>
      <h4>TMS</h4><div>Status: <span id="tms-status">{{st}}</span></div>
      <form method="post" action="/shipment/{{ref}}/push"><button id="push-tms" {% if s.pushed_at %}disabled{% endif %}>Push XML to TMS</button></form>
      {% if st == 'Approved' %}<button id="view-xml" onclick="document.getElementById('xml-content').style.display='block'">View XML</button>
      <pre id="xml-content" style="display:none">{{xml}}</pre>{% endif %}""",
                ref=ref, s=s, fields=FIELDS, toast=toast, st=st, xml=tms_xml(s) if st == "Approved" else "")


@app.route("/shipment/<ref>/shipper", methods=["POST"])
@login_required
def save_shipper(ref):
    for f in FIELDS:
        if f in request.form:
            DB[ref]["data"][f] = request.form[f]
    DB[ref]["toast"] = "Saved"
    return redirect(url_for("shipment", ref=ref))


@app.route("/shipment/<ref>/push", methods=["POST"])
@login_required
def push(ref):
    DB[ref]["pushed_at"] = DB[ref]["pushed_at"] or time.time()
    return redirect(url_for("shipment", ref=ref))


@app.route("/_reset", methods=["POST"])
def _reset():
    reset()
    return "ok"


if __name__ == "__main__":
    app.run(port=int(os.getenv("MOCK_PORT", "5055")))
