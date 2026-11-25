"""Saved-session handling for Nexus: reuse cookies/local storage, re-login only on expiry."""
from __future__ import annotations

import logging

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

from ..config import Config

log = logging.getLogger(__name__)


class SessionExpired(RuntimeError):
    """Session is gone and no credentials are configured for a headless re-login."""


class WrongOrganisation(SessionExpired):
    """The session belongs to another organisation (tenant) than this run's: nothing may be read or compared with it."""


ID_TOKEN_COOKIE = "unifo-id-token"
ORG_CLAIM = "custom:organization_code"


def org_from_cookies(cookies: list[dict]) -> str:
    """The organisation code inside the session's ID token (a JWT cookie), '' when there is none. Only that claim is read; no token is logged."""
    import base64
    import json
    tok = next((c.get("value", "") for c in cookies if c.get("name") == ID_TOKEN_COOKIE), "")
    parts = tok.split(".")
    if len(parts) != 3:
        return ""
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (ValueError, TypeError):
        return ""
    return str(claims.get(ORG_CLAIM, "") or "")


class NexusSession:
    def __init__(self, cfg: Config, headless: bool = True):
        self.cfg = cfg
        self.headless = headless
        self.sel = cfg.selectors["login"]
        self.state_file = cfg.path(cfg.settings["nexus"]["session_file"])
        self._pw = self.browser = self.context = None
        self.page: Page | None = None

    # --- lifecycle --------------------------------------------------------
    def __enter__(self) -> "NexusSession":
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=self.headless)
        kwargs = {"accept_downloads": True, "viewport": {"width": 1800, "height": 1000}}   # wide enough to draw the whole Shipment Details table
        if self.state_file.exists():
            kwargs["storage_state"] = str(self.state_file)
            log.info("Reusing saved Nexus session %s", self.state_file)
        self.context = self.browser.new_context(**kwargs)
        self.context.set_default_timeout(self.cfg.settings["nexus"].get("navigation_timeout_ms", 30000))
        try:
            self.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=self.cfg.base_url)
        except Exception:  # not supported in every browser / origin
            pass
        self.page = self.context.new_page()
        return self

    def __exit__(self, *exc) -> None:
        for obj in (self.context, self.browser):
            try:
                obj and obj.close()
            except Exception:
                pass
        if self._pw:
            self._pw.stop()

    # --- session ----------------------------------------------------------
    def save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.context.storage_state(path=str(self.state_file))
        try:
            self.state_file.chmod(0o600)
        except OSError:
            pass

    def is_logged_in(self) -> bool:
        login_path = self.cfg.settings["nexus"]["login_path"]
        if login_path and login_path in self.page.url:
            return False
        try:
            self.page.locator(self.sel["logged_in_marker"]).first.wait_for(state="visible", timeout=5000)
            return True
        except PWTimeout:
            return False

    # --- organisation (tenant) -------------------------------------------
    @property
    def expected_org(self) -> str:
        """This tenant's organisation code; only where the login form has an Org Code field (the real Nexus, not the mock)."""
        if not self.sel.get("org_code"):
            return ""
        return str(self.cfg.settings["nexus"].get("organisation_code") or "")

    def active_org(self) -> str:
        """The organisation code the browser session is signed in to (from the ID token cookie)."""
        try:
            return org_from_cookies(self.context.cookies())
        except Exception:
            return ""

    def assert_org(self) -> None:
        """Stops the run when the session is on another organisation than this tenant's. No expected code configured = no check (old behaviour)."""
        want, have = self.expected_org, self.active_org()
        if want and have.upper() != want.upper():
            raise WrongOrganisation(f"the Nexus session is on organisation '{have or '(unknown)'}', but this run is for tenant "
                                    f"'{self.cfg.tenant}' (organisation '{want}'): nothing was read or compared")

    def ensure_logged_in(self) -> None:
        """Health check before every shipment. Signs in again (with the tenant's organisation code) when the session is missing, expired
        or on another organisation, if credentials exist; then checks the organisation of the session."""
        home = self.cfg.base_url + self.cfg.settings["nexus"]["home_path"]
        if not self.page.url.startswith(self.cfg.base_url):
            self.page.goto(home)
        ok = self.is_logged_in()
        if not ok:
            self.page.goto(home)
            ok = self.is_logged_in()
        want = self.expected_org
        if ok and (not want or self.active_org().upper() == want.upper()):
            return
        user, pwd = self.cfg.nexus_user, self.cfg.nexus_password
        if not (user and pwd):
            if ok:                                   # signed in, but to the wrong organisation, and no way to switch: stop
                self.assert_org()
            raise SessionExpired("Nexus session expired and NEXUS_USER/NEXUS_PASSWORD are not set. "
                                 f"Run `./nx{'' if self.cfg.tenant == 'india' else ' --tenant ' + self.cfg.tenant} login` to log in again.")
        log.info("Signing in to Nexus%s (session %s)", f" for organisation {want}" if want else "",
                 "on another organisation" if ok else "missing or expired")
        self.context.clear_cookies()                 # never mix two organisations' tokens in one context
        self.page.goto(self.cfg.base_url + self.cfg.settings["nexus"]["login_path"])
        if want and self.sel.get("org_code"):
            self.page.fill(self.sel["org_code"], want)
        self.page.fill(self.sel["username"], user)
        self.page.fill(self.sel["password"], pwd)
        self.page.click(self.sel["submit"])
        try:
            self.page.locator(self.sel["logged_in_marker"]).first.wait_for(state="visible", timeout=60000)
        except PWTimeout:
            raise SessionExpired("signing in to Nexus failed (check NEXUS_USER / NEXUS_PASSWORD and the organisation code): nothing was run")
        self.assert_org()                            # signed in: it must be this tenant's organisation before the session is kept
        self.save()

    def interactive_login(self, wait_seconds: int = 300) -> None:
        """Opens Nexus in a visible browser; a person types their own credentials (OTP/SSO ok).
        No password is read from or stored by the agent; only the resulting session is saved."""
        self.page.goto(self.cfg.base_url + self.cfg.settings["nexus"]["home_path"])
        if self.expected_org and self.sel.get("org_code"):
            try:                                     # pre-fill this tenant's organisation code on the login form
                self.page.locator(self.sel["org_code"]).first.fill(self.expected_org, timeout=10000)
            except Exception:
                pass
        print("\nA browser window has opened. Log in to Nexus there with your own credentials"
              + (f" (organisation {self.expected_org})." if self.expected_org else "."))
        import sys
        if sys.stdin.isatty():
            print("When you can see the pre-alert list, come back here and press Enter.")
            input()
            self.save()
        else:   # no keyboard attached (e.g. started by an agent): save while the window is open, finish when it is closed
            print(f"When you can see the pre-alert list, CLOSE the browser window (waiting up to {wait_seconds}s).")
            self._save_until_closed(wait_seconds)
        print(f"Session saved to {self.state_file} (contains login cookies: keep it private).")
        if self.expected_org:
            try:
                import json
                have = org_from_cookies(json.loads(self.state_file.read_text()).get("cookies", []))
            except Exception:
                have = ""
            if have.upper() != self.expected_org.upper():
                print(f"WARNING: this session is on organisation '{have or '(unknown)'}', not '{self.expected_org}' (tenant {self.cfg.tenant}): "
                      f"runs will refuse it. Log in again with Org Code {self.expected_org}.")
            else:
                print(f"Organisation checked: {have} (tenant {self.cfg.tenant}).")

    def _save_until_closed(self, wait_seconds: int) -> None:
        saved = False
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(max(1, wait_seconds // 2)):
            try:
                if self.page.is_closed():
                    break
                self.context.storage_state(path=str(self.state_file))
                saved = True
                self.page.wait_for_timeout(2000)
            except Exception:       # window closed while saving: keep the last good copy
                break
        if not saved:
            raise SessionExpired("the browser was closed before any session could be saved; run login again")
        try:
            self.state_file.chmod(0o600)
        except OSError:
            pass
