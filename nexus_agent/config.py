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


class ConfigError(ValueError):
    """The configuration is incomplete: the run stops before touching Nexus, Gmail or the database."""


# Keys every command relies on (settings.yaml). A missing one used to fail mid-run with a KeyError.
REQUIRED_SETTINGS = {"nexus": ["base_url", "home_path", "session_file"], "paths": ["state_dir", "runs_dir", "corrections_dir"]}
# Selector keys UatPages reads when the real-Nexus profile is loaded (selectors.uat.yaml).
REQUIRED_UAT_SELECTORS = ["loading", "row_marker", "subject_cell", "view_documents", "viewer_url_part", "parent_search",
                          "header_buttons_ignore", "left_headings"]


DEFAULT_TENANT = "india"          # India keeps today's config/, state/ and runs/ folders (approved 25 Nov 2026)


def available_tenants(root: str | Path | None = None) -> list[str]:
    """India plus every config/<name>/ that holds a settings.yaml."""
    base = Path(root or ROOT) / "config"
    return [DEFAULT_TENANT] + sorted(p.name for p in base.iterdir() if p.is_dir() and (p / "settings.yaml").exists()) if base.is_dir() else [DEFAULT_TENANT]


def tenant_config_dir(tenant: str | None, root: str | Path | None = None) -> Path:
    """config/ for India (or no tenant), config/<tenant>/ for any other tenant. An unknown tenant stops with the list of known ones."""
    base = Path(root or ROOT) / "config"
    name = (tenant or DEFAULT_TENANT).strip().lower()
    if name == DEFAULT_TENANT:
        return base
    if not (base / name / "settings.yaml").exists():
        raise ConfigError(f"no configuration for tenant '{name}': expected {base / name / 'settings.yaml'}. "
                          f"Known tenants: {', '.join(available_tenants(root))}")
    return base / name


class Config:
    def __init__(self, config_dir: str | Path | None = None, root: str | Path | None = None,
                 profile: str | None = None, tenant: str | None = None):
        self.root = Path(root) if root else ROOT
        if tenant and config_dir:
            raise ConfigError("give either --tenant or --config, not both")
        self.expected_tenant = (tenant or "").strip().lower() or None
        cdir = Path(config_dir) if config_dir else (tenant_config_dir(tenant, self.root) if tenant else
                                                     Path(os.getenv("NEXUS_AGENT_CONFIG") or self.root / "config"))
        self.config_dir = cdir
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

    # ---- start-up check ------------------------------------------------
    @property
    def tenant(self) -> str:
        """The tenant this configuration belongs to (settings `tenant:`); the original config is India's."""
        return str(self.settings.get("tenant") or "india")

    def problems(self) -> list[str]:
        """What is missing or unusable in this configuration (empty = fine). Reads only; changes nothing."""
        out = []
        for section, keys in REQUIRED_SETTINGS.items():
            block = self.settings.get(section)
            if not isinstance(block, dict):
                out.append(f"settings.yaml: section '{section}' is missing")
                continue
            for k in keys:
                v = block.get(k)
                if k == "home_path" and v == "":
                    continue
                if not isinstance(v, str) or not v.strip():
                    out.append(f"settings.yaml: '{section}.{k}' is missing or empty")
        url = (self.settings.get("nexus") or {}).get("base_url") or ""
        if isinstance(url, str) and url and not url.startswith(("http://", "https://")):
            out.append(f"settings.yaml: 'nexus.base_url' must start with http:// or https:// (got '{url}')")
        out += self._isolation_problems()
        if self.profile == "uat":
            uat = self.selectors.get("uat")
            if not isinstance(uat, dict):
                out.append(f"selectors.uat.yaml: section 'uat' is missing (profile 'uat' in {self.config_dir})")
            else:
                out += [f"selectors.uat.yaml: 'uat.{k}' is missing" for k in REQUIRED_UAT_SELECTORS if k not in uat]
        return out

    def _isolation_problems(self) -> list[str]:
        """A tenant other than India must name itself and keep its own database, runs and session, so no history, baseline,
        bug fingerprint or login is ever shared with another tenant. India's original config is not affected."""
        out = []
        if self.expected_tenant and self.expected_tenant != self.tenant:
            out.append(f"settings.yaml in {self.config_dir} says tenant '{self.tenant}', but tenant '{self.expected_tenant}' was asked for")
        if self.tenant == DEFAULT_TENANT:
            return out
        paths, nexus = self.settings.get("paths") or {}, self.settings.get("nexus") or {}
        if not str(nexus.get("organisation_code") or "").strip():
            out.append(f"settings.yaml: 'nexus.organisation_code' is missing: tenant '{self.tenant}' needs its own Org Code "
                       f"(the same Nexus login serves every tenant; the organisation tells them apart)")
        for label, value in (("paths.state_dir", paths.get("state_dir")), ("paths.runs_dir", paths.get("runs_dir")),
                             ("nexus.session_file", nexus.get("session_file"))):
            if isinstance(value, str) and value.strip() and self.tenant not in Path(value).parts:
                out.append(f"settings.yaml: '{label}' ({value}) must be inside a '{self.tenant}' folder, "
                           f"e.g. state/{self.tenant}/ or runs/{self.tenant}/, so tenant '{self.tenant}' shares nothing with another tenant")
        return out

    def unset(self, value) -> bool:
        """A setting that still says TO-BE-PROVIDED (or is empty): the action that needs it must not run."""
        return not str(value or "").strip() or "TO-BE-PROVIDED" in str(value)

    def validate(self) -> None:
        """Raises ConfigError listing every problem at once, so a wrong or partial config stops before the run starts."""
        found = self.problems()
        if found:
            raise ConfigError(f"configuration in {self.config_dir} is not usable:\n  - " + "\n  - ".join(found))

    def banner(self) -> str:
        """One line naming what this run will use. No credentials: the session file is named, never read."""
        org = str((self.settings.get("nexus") or {}).get("organisation_code") or "-")
        return (f"[nexus-agent] tenant={self.tenant} org={org} profile={self.profile or 'mock'} nexus={self.base_url} "
                f"config={self.config_dir} db={self.state_dir / 'agent.db'} runs={self.runs_dir}")
