"""One Nexus login, several organisations: the session's ID token says which organisation it is on; a run signs in with its tenant's
Org Code when the session is missing, expired or on another organisation, and never reads data from another organisation.
Offline: a fake page and fake tokens (no Nexus, no real credentials)."""
import base64
import json

import pytest

from nexus_agent.config import Config
from nexus_agent.nexus import session as S


def jwt(org: str) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"custom:organization_code": org, "exp": 9999999999}).encode()).decode().rstrip("=")
    return f"h.{body}.sig"


class FakeCtx:
    def __init__(self, org=""):
        self.org, self.cleared = org, 0

    def cookies(self):
        return [{"name": S.ID_TOKEN_COOKIE, "value": jwt(self.org)}] if self.org else []

    def clear_cookies(self):
        self.cleared += 1
        self.org = ""


class FakePage:
    """Signed in when the context holds a token; the login form signs in to the organisation typed into #orgId."""
    def __init__(self, ctx, base, login_org_override=None, login_ok=True):
        self.ctx, self.url, self.filled, self.override, self.login_ok = ctx, base + "/sentinel-nexus/email", {}, login_org_override, login_ok

    def goto(self, url, **k):
        self.url = url

    def fill(self, sel, value):
        self.filled[sel] = value

    def click(self, sel):
        if self.login_ok:
            self.ctx.org = self.override or self.filled.get("#orgId", "")
            self.url = self.url.replace("/auth/logIn", "/sentinel-nexus/email")

    def locator(self, sel):
        page = self

        class L:
            first = None
            def wait_for(self, state="visible", timeout=None):
                if not page.ctx.org or "/auth/logIn" in page.url:
                    raise S.PWTimeout("not signed in")
        loc = L(); loc.first = loc
        return loc


def make(monkeypatch, org_in_session="", user="qa", pwd="secret", tenant_org="DXB", mock=False, **page_kw):
    cfg = Config(profile=None if mock else "uat")
    cfg.settings["nexus"] = {**cfg.settings["nexus"], "organisation_code": tenant_org}
    monkeypatch.setenv("NEXUS_USER", user) if user else monkeypatch.delenv("NEXUS_USER", raising=False)
    monkeypatch.setenv("NEXUS_PASSWORD", pwd) if pwd else monkeypatch.delenv("NEXUS_PASSWORD", raising=False)
    s = S.NexusSession(cfg)
    s.context = FakeCtx(org_in_session)
    s.page = FakePage(s.context, cfg.base_url, **page_kw)
    s.saved = 0
    s.save = lambda: setattr(s, "saved", s.saved + 1)
    return s


def test_org_is_read_from_the_id_token_only():
    assert S.org_from_cookies([{"name": S.ID_TOKEN_COOKIE, "value": jwt("UNI")}]) == "UNI"
    assert S.org_from_cookies([{"name": S.ID_TOKEN_COOKIE, "value": "not-a-jwt"}]) == ""
    assert S.org_from_cookies([]) == ""


def test_right_organisation_needs_no_login(monkeypatch):
    s = make(monkeypatch, org_in_session="DXB")
    s.ensure_logged_in()
    assert s.saved == 0 and s.page.filled == {} and s.context.cleared == 0


def test_another_organisation_signs_in_again_with_the_tenants_org_code(monkeypatch):
    s = make(monkeypatch, org_in_session="UNI")
    s.ensure_logged_in()
    assert s.context.cleared == 1                                            # the other organisation's tokens are dropped first
    assert s.page.filled == {"#orgId": "DXB", "#username": "qa", "#password": "secret"}
    assert s.active_org() == "DXB" and s.saved == 1


def test_expired_session_signs_in_with_the_org_code(monkeypatch):
    s = make(monkeypatch, org_in_session="")
    s.ensure_logged_in()
    assert s.page.filled["#orgId"] == "DXB" and s.saved == 1


def test_wrong_organisation_without_credentials_stops_the_run(monkeypatch):
    s = make(monkeypatch, org_in_session="UNI", user="", pwd="")
    with pytest.raises(S.WrongOrganisation, match="organisation 'UNI'.*tenant 'india' \\(organisation 'DXB'\\)"):
        s.ensure_logged_in()


def test_a_login_that_lands_on_another_organisation_is_never_kept(monkeypatch):
    s = make(monkeypatch, org_in_session="", login_org_override="JPN")
    with pytest.raises(S.WrongOrganisation):
        s.ensure_logged_in()
    assert s.saved == 0


def test_failed_sign_in_says_so_without_any_password(monkeypatch):
    s = make(monkeypatch, org_in_session="", login_ok=False, pwd="secret")
    with pytest.raises(S.SessionExpired, match="signing in to Nexus failed") as e:
        s.ensure_logged_in()
    assert "secret" not in str(e.value)


def test_mock_profile_has_no_org_check(monkeypatch):
    s = make(monkeypatch, org_in_session="", mock=True)
    assert s.expected_org == ""


def test_banner_names_the_organisation():
    assert "org=UNI" in Config(profile="uat").banner()
