"""Daily update for Zoho: builds it from today's progress log and the bugs logged today, shows it, and posts it only after a yes.
Cliq gets a short message (incoming webhook), the Sprints task gets a fuller comment (OAuth API). Secrets come from the environment only."""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

from .store import Store

CLIQ_BULLETS, CLIQ_WIDTH, SPRINTS_WIDTH = 6, 140, 300


def _trim(text: str, n: int) -> str:
    """One line: the first sentence if it fits, else cut at n."""
    text = " ".join(text.split())
    first = re.match(r".{20,}?[.;:] ", text)
    if first and len(first.group(0)) <= n:
        return first.group(0).rstrip(" ;:")
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def log_bullets(log_path: Path, day: str) -> list[str]:
    """The bullets under today's '## yyyy-mm-dd' heading of the progress log (empty if there is none)."""
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8").split("\n")
    start = next((i for i, ln in enumerate(lines) if ln == f"## {day}" or ln.startswith(f"## {day} ")), None)
    if start is None:
        return []
    out: list[str] = []
    for ln in lines[start + 1:]:
        if ln.startswith("## "):
            break
        if ln.startswith("- "):
            out.append(ln[2:].strip())
        elif ln.startswith("  ") and out and ln.strip():       # a wrapped continuation of the previous bullet
            out[-1] += " " + ln.strip()
    return out


def bugs_logged(store: Store, day: str) -> list[dict]:
    """Bugs written to the bug sheet today: sheet row, Nexus job and the first words of the description."""
    out = []
    for b in store.bugs_by_status("LOGGED"):
        if not (b.get("decided_at") or "").startswith(day):
            continue
        try:
            d = json.loads(b.get("data") or "{}")
        except ValueError:
            d = {}
        m = re.search(r"!A(\d+):", b.get("note") or "")
        out.append({"row": m.group(1) if m else "", "ipa": d.get("ipa", ""), "text": d.get("description") or f"{b['document']} · {b['field']}"})
    return out


def build_update(cfg, store: Store, day: str | None = None) -> dict:
    day = day or date.today().isoformat()
    return {"day": day, "done": log_bullets(cfg.path("docs/PROGRESS_LOG.md"), day), "bugs": bugs_logged(store, day),
            "pending": len(store.bugs_by_status("PENDING"))}


def render_cliq(u: dict) -> str:
    lines = [f"*Regression update, {u['day']}*"]
    lines += [f"• {_trim(x, CLIQ_WIDTH)}" for x in u["done"][:CLIQ_BULLETS]]
    if len(u["done"]) > CLIQ_BULLETS:
        lines.append(f"• …and {len(u['done']) - CLIQ_BULLETS} more (see the task)")
    if u["bugs"]:
        lines.append(f"Bugs logged today ({len(u['bugs'])}):")
        lines += [f"  – row {b['row'] or '?'}, {b['ipa'] or 'no job'}: {_trim(b['text'], CLIQ_WIDTH)}" for b in u["bugs"]]
    if u["pending"]:
        lines.append(f"{u['pending']} findings still waiting for a decision.")
    return "\n".join(lines)


def render_sprints(u: dict) -> str:
    lines = [f"Update, {u['day']}", "", "Done:"]
    lines += [f"- {_trim(x, SPRINTS_WIDTH)}" for x in u["done"]] or ["- (no entry in the progress log today)"]
    if u["bugs"]:
        lines += ["", f"Bugs logged in the UAT sheet today ({len(u['bugs'])}):"]
        lines += [f"- row {b['row'] or '?'}, {b['ipa'] or 'no job'}: {_trim(b['text'], SPRINTS_WIDTH)}" for b in u["bugs"]]
    lines += ["", f"Pending: {u['pending']} findings waiting for a decision."]
    return "\n".join(lines)


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def _post(url: str, data: bytes, headers: dict) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:                    # noqa: S310 (https URLs from our own settings)
        body = r.read().decode("utf-8", "replace")
    try:
        return json.loads(body) if body else {}
    except ValueError:
        return {"raw": body[:200]}


def missing(env: dict, keys: list[str]) -> list[str]:
    return [k for k in keys if not env.get(k)]


CLIQ_KEYS = ["ZOHO_CLIQ_WEBHOOK_URL"]
CLIQ_CHAT_KEYS = ["ZOHO_CLIQ_CHAT_ID", "ZOHO_ACCOUNTS_URL", "ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN"]
SPRINTS_KEYS = ["ZOHO_ACCOUNTS_URL", "ZOHO_SPRINTS_API", "ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN",
                "ZOHO_SPRINTS_TEAM_ID", "ZOHO_SPRINTS_PROJECT_ID", "ZOHO_SPRINTS_MODULE_ID", "ZOHO_SPRINTS_ITEM_ID"]


_CACHE = Path(__file__).resolve().parent.parent / "state" / "zoho_token.json"


def _access_token(env, post) -> str:
    """Zoho limits how many access tokens one refresh token may request, so a real run reuses the last one while it is valid."""
    use_cache = post is _post
    if use_cache:
        try:
            c = json.loads(_CACHE.read_text())
            if c.get("refresh") == _digest(env["ZOHO_REFRESH_TOKEN"]) and c.get("until", 0) > datetime.now().timestamp() + 120:
                return c["token"]
        except (OSError, ValueError):
            pass
    token = _new_access_token(env, post)
    if use_cache:
        try:
            _CACHE.parent.mkdir(exist_ok=True)
            _CACHE.write_text(json.dumps({"token": token, "refresh": _digest(env["ZOHO_REFRESH_TOKEN"]), "until": datetime.now().timestamp() + 3300}))
            _CACHE.chmod(0o600)
        except OSError:
            pass
    return token


def _new_access_token(env, post) -> str:
    tok = post(env["ZOHO_ACCOUNTS_URL"].rstrip("/") + "/oauth/v2/token", urllib.parse.urlencode({
        "grant_type": "refresh_token", "client_id": env["ZOHO_CLIENT_ID"], "client_secret": env["ZOHO_CLIENT_SECRET"],
        "refresh_token": env["ZOHO_REFRESH_TOKEN"]}).encode(), {"Content-Type": "application/x-www-form-urlencoded"})
    if not tok.get("access_token"):
        raise RuntimeError(f"Zoho gave no access token ({tok.get('error', 'unknown error')})")
    return tok["access_token"]


def cliq_keys(env) -> list[str]:
    """A webhook URL alone is enough; a group chat (no webhook) needs the chat id and the OAuth client."""
    return CLIQ_KEYS if env.get("ZOHO_CLIQ_WEBHOOK_URL") or not env.get("ZOHO_CLIQ_CHAT_ID") else CLIQ_CHAT_KEYS


def post_cliq(text: str, env=os.environ, post=_post) -> str:
    if env.get("ZOHO_CLIQ_WEBHOOK_URL"):
        post(env["ZOHO_CLIQ_WEBHOOK_URL"], json.dumps({"text": text}).encode(), {"Content-Type": "application/json"})
        return "posted to Cliq (webhook)"
    token = _access_token(env, post)                       # needs the scope ZohoCliq.Webhooks.CREATE on the refresh token
    post(f"{env.get('ZOHO_CLIQ_API', 'https://cliq.zoho.in/api/v2').rstrip('/')}/chats/{env['ZOHO_CLIQ_CHAT_ID']}/message",
         json.dumps({"text": text}).encode(), {"Authorization": f"Zoho-oauthtoken {token}", "Content-Type": "application/json"})
    return "posted to the Cliq chat"


def post_sprints(text: str, env=os.environ, post=_post) -> str:
    token = _access_token(env, post)
    url = (f"{env['ZOHO_SPRINTS_API'].rstrip('/')}/team/{env['ZOHO_SPRINTS_TEAM_ID']}/projects/{env['ZOHO_SPRINTS_PROJECT_ID']}"
           f"/modules/{env['ZOHO_SPRINTS_MODULE_ID']}/entity/{env['ZOHO_SPRINTS_ITEM_ID']}/notes/?action=addnotes")
    post(url, urllib.parse.urlencode({"name": text}).encode(),
         {"Authorization": f"Zoho-oauthtoken {token}", "Content-Type": "application/x-www-form-urlencoded"})
    return "comment added to the Sprints task"


def run(cfg, store: Store, day: str | None = None, dry_run: bool = False, ask=input, out=print, env=os.environ, post=_post,
        text_file: str | None = None) -> int:
    u = build_update(cfg, store, day)
    cliq, sprints = render_cliq(u), render_sprints(u)
    if text_file:                                  # a hand-edited update replaces the automatic draft for both targets
        cliq = sprints = Path(text_file).read_text(encoding="utf-8").strip()
        u = {**u, "done": u["done"] or [cliq]}
    out("----- Cliq message -----\n" + cliq + "\n\n----- Sprints comment -----\n" + sprints + "\n")
    if not u["done"] and not u["bugs"]:
        out("Nothing recorded for this day yet (no progress-log entry, no bugs logged): nothing to post.")
        return 1
    if dry_run:
        out("Dry run: nothing was posted.")
        return 0
    targets = {"cliq": (cliq, cliq_keys(env), post_cliq), "sprints": (sprints, SPRINTS_KEYS, post_sprints)}
    answer = (ask("Post to both (y), Cliq only (c), Sprints only (s), or cancel (n)? ") or "n").strip().lower()
    chosen = {"y": ["cliq", "sprints"], "c": ["cliq"], "s": ["sprints"]}.get(answer)
    if not chosen:
        out("Nothing was posted.")
        return 0
    rc = 0
    for name in chosen:
        text, keys, fn = targets[name]
        if gap := missing(env, keys):
            out(f"{name}: not set up, add to .env: {', '.join(gap)}")
            rc = 2
            continue
        before = store.posts_for(u["day"], name)
        if before and (ask(f"{name}: already posted today at {before[-1][11:16]}. Post again? (y/n) ").strip().lower() != "y"):
            out(f"{name}: skipped")
            continue
        try:
            out(f"{name}: {fn(text, env, post)}")
            store.post_add(u["day"], name, _digest(text))
        except Exception as exc:                                         # the update is never lost: it is printed above
            out(f"{name}: FAILED ({type(exc).__name__}: {str(exc).splitlines()[0][:160] if str(exc) else ''})")
            rc = 2
    return rc
