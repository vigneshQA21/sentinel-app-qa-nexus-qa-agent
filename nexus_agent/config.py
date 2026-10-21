"""Loads YAML config + environment overrides."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

try:  # optional .env support
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Config:
    def __init__(self, config_dir: str | Path | None = None, root: str | Path | None = None,
                 profile: str | None = None):
        self.root = Path(root) if root else ROOT
        cdir = Path(config_dir or os.getenv("NEXUS_AGENT_CONFIG") or self.root / "config")
        self.settings = _load(cdir / "settings.yaml")
        self.selectors = _load(cdir / "selectors.yaml")
        self.profile = profile
        if profile and (cdir / f"selectors.{profile}.yaml").exists():      # e.g. selectors.uat.yaml for the real Nexus
            self.selectors = _deep_merge(self.selectors, _load(cdir / f"selectors.{profile}.yaml"))
        self.rules = _load(cdir / "rules.yaml")
        self.xml_mapping = _load(cdir / "xml_mapping.yaml")

        nexus = self.settings.setdefault("nexus", {})
        if os.getenv("NEXUS_MOCK"):  # run against the bundled mock Nexus
            nexus.update(base_url="http://127.0.0.1:5055", home_path="/prealerts", login_path="/login")
        if os.getenv("NEXUS_BASE_URL"):
            nexus["base_url"] = os.environ["NEXUS_BASE_URL"]

    # ---- convenience -------------------------------------------------
    def path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else self.root / p

    @property
    def state_dir(self) -> Path:
        return self.path(self.settings["paths"]["state_dir"])

    @property
    def runs_dir(self) -> Path:
        return self.path(self.settings["paths"]["runs_dir"])

    @property
    def corrections_dir(self) -> Path:
        return self.path(self.settings["paths"]["corrections_dir"])

    @property
    def base_url(self) -> str:
        return self.settings["nexus"]["base_url"].rstrip("/")

    @property
    def nexus_user(self) -> str | None:
        return os.getenv("NEXUS_USER")

    @property
    def nexus_password(self) -> str | None:
        return os.getenv("NEXUS_PASSWORD")

    def timing(self, key: str) -> float:
        return float(self.settings["timing"][key])
