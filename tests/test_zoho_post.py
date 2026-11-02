import json
from pathlib import Path

from nexus_agent import zoho_post as Z

LOG = "# Log\n\n## 2026-11-02\n\n- Built the Sea set.\n- Logged row 252\n  wrapped line.\n\n## 2026-11-01\n\n- old\n"


class FakeStore:
    def __init__(self, bugs=(), pending=0):
        self.bugs, self.pending, self.posted = list(bugs), pending, []

    def bugs_by_status(self, status):
        return self.bugs if status == "LOGGED" else [{}] * self.pending

    def posts_for(self, day, target):
        return [p[2] for p in self.posted if p[0] == day and p[1] == target]

    def post_add(self, day, target, digest):
        self.posted.append((day, target, "2026-11-02T18:00:00"))


class Cfg:
    def __init__(self, tmp):
        self.tmp = tmp

    def path(self, p):
        return self.tmp / p


def _cfg(tmp_path):
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs/PROGRESS_LOG.md").write_text(LOG, encoding="utf-8")
    return Cfg(tmp_path)


BUG = {"decided_at": "2026-11-02T17:00:00", "note": "'UAT'!A252:P252", "document": "d", "field": "f",
       "data": json.dumps({"ipa": "IPA/2391/2026-27", "description": "Approving the Master locks the House."})}
ENV = {k: "x" for k in Z.CLIQ_KEYS + Z.SPRINTS_KEYS}


def test_update_uses_only_today_and_joins_wrapped_lines(tmp_path):
    u = Z.build_update(_cfg(tmp_path), FakeStore([BUG], 3), "2026-11-02")
    assert u["done"] == ["Built the Sea set.", "Logged row 252 wrapped line."]
    assert u["bugs"][0]["row"] == "252" and u["pending"] == 3
    assert "old" not in Z.render_sprints(u) and "row 252, IPA/2391/2026-27" in Z.render_cliq(u)


def test_no_answer_posts_nothing(tmp_path):
    calls = []
    rc = Z.run(_cfg(tmp_path), FakeStore(), "2026-11-02", ask=lambda _q: "n", out=lambda *_: None, env=ENV, post=lambda *a: calls.append(a) or {})
    assert rc == 0 and calls == []


def test_dry_run_posts_nothing(tmp_path):
    calls = []
    Z.run(_cfg(tmp_path), FakeStore(), "2026-11-02", dry_run=True, ask=lambda _q: "y", out=lambda *_: None, env=ENV, post=lambda *a: calls.append(a) or {})
    assert calls == []


def test_yes_posts_both_and_records_and_asks_again_on_repeat(tmp_path):
    calls, store, answers = [], FakeStore(), iter(["y", "n", "n"])
    post = lambda url, data, headers: calls.append(url) or {"access_token": "t"}
    Z.run(_cfg(tmp_path), store, "2026-11-02", ask=lambda _q: next(answers), out=lambda *_: None, env=ENV, post=post)
    assert len(store.posted) == 2 and any("/notes/?action=addnotes" in u for u in calls)
    n = len(calls)
    answers = iter(["y", "n", "n"])
    Z.run(_cfg(tmp_path), store, "2026-11-02", ask=lambda _q: next(answers), out=lambda *_: None, env=ENV, post=post)
    assert len(calls) == n                                              # asked "post again?", said n


def test_missing_settings_are_named_not_sent(tmp_path):
    msgs, calls = [], []
    rc = Z.run(_cfg(tmp_path), FakeStore(), "2026-11-02", ask=lambda _q: "c", out=msgs.append, env={}, post=lambda *a: calls.append(a) or {})
    assert rc == 2 and calls == [] and any("ZOHO_CLIQ_WEBHOOK_URL" in m for m in msgs)


def test_cliq_group_chat_uses_oauth_and_chat_endpoint():
    calls = []
    env = {"ZOHO_CLIQ_CHAT_ID": "CT_1", "ZOHO_ACCOUNTS_URL": "https://a", "ZOHO_CLIENT_ID": "i", "ZOHO_CLIENT_SECRET": "s", "ZOHO_REFRESH_TOKEN": "r"}
    assert Z.cliq_keys(env) == Z.CLIQ_CHAT_KEYS and Z.missing(env, Z.cliq_keys(env)) == []
    Z.post_cliq("hi", env, lambda url, data, h: calls.append((url, h)) or {"access_token": "t"})
    assert calls[1][0].endswith("/chats/CT_1/message") and calls[1][1]["Authorization"] == "Zoho-oauthtoken t"
