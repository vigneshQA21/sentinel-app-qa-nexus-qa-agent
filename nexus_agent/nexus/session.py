"""Saved-session handling for Nexus: reuse cookies/local storage, re-login only on expiry."""
from __future__ import annotations

import logging

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

from ..config import Config

log = logging.getLogger(__name__)


class SessionExpired(RuntimeError):
    """Session is gone and no credentials are configured for a headless re-login."""


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

    def ensure_logged_in(self) -> None:
        """Health check before every shipment. Re-logs in headless when credentials exist."""
        home = self.cfg.base_url + self.cfg.settings["nexus"]["home_path"]
        if not self.page.url.startswith(self.cfg.base_url):
            self.page.goto(home)
        if self.is_logged_in():
            return
        self.page.goto(home)
        if self.is_logged_in():
            return
        user, pwd = self.cfg.nexus_user, self.cfg.nexus_password
        if not (user and pwd):
            raise SessionExpired("Nexus session expired and NEXUS_USER/NEXUS_PASSWORD are not set. "
                                 "Run `./nx login` to log in again.")
        log.info("Session expired, logging in as %s", user)
        self.page.goto(self.cfg.base_url + self.cfg.settings["nexus"]["login_path"])
        self.page.fill(self.sel["username"], user)
        self.page.fill(self.sel["password"], pwd)
        self.page.click(self.sel["submit"])
        self.page.locator(self.sel["logged_in_marker"]).first.wait_for(state="visible")
        self.save()

    def interactive_login(self, wait_seconds: int = 300) -> None:
        """Opens Nexus in a visible browser; a person types their own credentials (OTP/SSO ok).
        No password is read from or stored by the agent; only the resulting session is saved."""
        self.page.goto(self.cfg.base_url + self.cfg.settings["nexus"]["home_path"])
        print("\nA browser window has opened. Log in to Nexus there with your own credentials.")
        import sys
        if sys.stdin.isatty():
            print("When you can see the pre-alert list, come back here and press Enter.")
            input()
            self.save()
        else:   # no keyboard attached (e.g. started by an agent): save while the window is open, finish when it is closed
            print(f"When you can see the pre-alert list, CLOSE the browser window (waiting up to {wait_seconds}s).")
            self._save_until_closed(wait_seconds)
        print(f"Session saved to {self.state_file} (contains login cookies: keep it private).")

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
