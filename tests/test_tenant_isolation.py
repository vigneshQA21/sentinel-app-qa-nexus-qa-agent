"""Stage 2: tenant layout. India keeps today's config/, state/, runs/; any other tenant has config/<tenant>/ and must keep its own
database, runs and session. Offline: temporary folders only, no Nexus, Gmail or real database."""
import shutil
from pathlib import Path

import pytest
import yaml

from nexus_agent.__main__ import main
from nexus_agent.bugs import fingerprint
from nexus_agent.config import ROOT, Config, ConfigError, available_tenants
from nexus_agent.store import Store


def _tenant(root: Path, name: str, **paths):
    d = root / "config" / name
    d.mkdir(parents=True)
    for f in (ROOT / "config").glob("*.yaml"):
        shutil.copy2(f, d / f.name)
    s = yaml.safe_load((d / "settings.yaml").read_text())
    s["tenant"] = paths.pop("tenant", name)
    s["paths"].update(state_dir=paths.get("state", f"state/{name}"), runs_dir=paths.get("runs", f"runs/{name}"),
                      corrections_dir=f"corrections/{name}")
    s["nexus"]["session_file"] = paths.get("session", f"state/{name}/nexus_session.json")
    (d / "settings.yaml").write_text(yaml.safe_dump(s))
    return d


@pytest.fixture
def root(tmp_path):
    shutil.copytree(ROOT / "config", tmp_path / "config")        # India: today's layout
    _tenant(tmp_path, "dubai")
    _tenant(tmp_path, "japan")
    return tmp_path


def test_india_is_todays_layout_with_or_without_the_flag(root):
    for t in (None, "india", "INDIA"):
        cfg = Config(root=root, profile="uat", tenant=t)
        assert (cfg.config_dir, cfg.state_dir, cfg.runs_dir) == (root / "config", root / "state", root / "runs")
        assert cfg.tenant == "india" and cfg.problems() == []


def test_each_tenant_loads_only_its_own_folders(root):
    seen = set()
    for t in ("india", "dubai", "japan"):
        cfg = Config(root=root, profile="uat", tenant=t)
        assert cfg.problems() == [] and cfg.tenant == t
        key = (cfg.config_dir, cfg.state_dir, cfg.runs_dir, cfg.path(cfg.settings["nexus"]["session_file"]))
        assert not seen & set(key), f"{t} shares a folder with another tenant"
        seen |= set(key)
    d = Config(root=root, tenant="dubai")
    assert d.state_dir == root / "state" / "dubai" and d.runs_dir == root / "runs" / "dubai"


def test_unknown_tenant_names_the_known_ones(root):
    with pytest.raises(ConfigError, match="Known tenants: india, dubai, japan"):
        Config(root=root, tenant="korea")
    assert available_tenants(root) == ["india", "dubai", "japan"]


def test_tenant_and_config_together_are_refused(root):
    with pytest.raises(ConfigError, match="either --tenant or --config"):
        Config(root / "config", root=root, tenant="dubai")


def test_a_copied_config_that_names_another_tenant_is_refused(root):
    _tenant(root, "oman", tenant="dubai", state="state/oman", runs="runs/oman", session="state/oman/s.json")
    found = Config(root=root, tenant="oman").problems()
    assert any("says tenant 'dubai', but tenant 'oman' was asked for" in p for p in found)


def test_a_tenant_that_would_share_indias_state_runs_or_session_is_refused(root):
    _tenant(root, "qatar", state="state", runs="runs", session="state/nexus_session.json")
    found = " ".join(Config(root=root, tenant="qatar").problems())
    for key in ("paths.state_dir", "paths.runs_dir", "nexus.session_file"):
        assert key in found


def test_the_same_finding_in_two_tenants_stays_in_two_databases(root):
    fp = fingerprint("REG-001", "Master", "Status", "CW Sync Pending", "Shipper Mapping Pending")
    stores = {t: Store(Config(root=root, tenant=t).state_dir / "agent.db") for t in ("india", "dubai")}
    assert stores["india"].bug_add_pending(fp, "REG-001", "Master", "Status", "{}")
    assert stores["dubai"].bug_get(fp) is None                           # Dubai's history does not see India's finding
    assert stores["dubai"].bug_add_pending(fp, "REG-001", "Master", "Status", "{}")   # the same case id and finding are new in Dubai
    assert (root / "state" / "agent.db").exists() and (root / "state" / "dubai" / "agent.db").exists()


def test_banner_names_the_tenant_folders(root):
    b = Config(root=root, profile="uat", tenant="japan").banner()
    assert "tenant=japan" in b and str(root / "state" / "japan" / "agent.db") in b and str(root / "runs" / "japan") in b


def test_cli_unknown_tenant_stops_before_running(capsys):
    assert main(["--tenant", "no-such-tenant", "cases"]) == 2
    assert "Nothing was run." in capsys.readouterr().err


def test_cli_india_flag_is_the_same_as_no_flag(capsys):
    assert main(["--tenant", "india", "cases"]) == 0
    with_flag = capsys.readouterr()
    assert main(["cases"]) == 0
    without = capsys.readouterr()
    assert with_flag.out == without.out and "tenant=india" in with_flag.err
