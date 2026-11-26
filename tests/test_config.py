"""Stage 1: start-up config check and banner. Offline only: no Nexus, Gmail or database is touched."""
import shutil
from pathlib import Path

import pytest
import yaml

from nexus_agent.__main__ import main
from nexus_agent.config import Config, ConfigError, ROOT


def _copy_config(tmp_path: Path, edit=None, uat_edit=None) -> Path:
    d = tmp_path / "config"
    shutil.copytree(ROOT / "config", d)
    if edit:
        s = yaml.safe_load((d / "settings.yaml").read_text())
        edit(s)
        (d / "settings.yaml").write_text(yaml.safe_dump(s))
    if uat_edit:
        u = yaml.safe_load((d / "selectors.uat.yaml").read_text())
        uat_edit(u)
        (d / "selectors.uat.yaml").write_text(yaml.safe_dump(u))
    return d


def test_the_real_india_config_is_valid_for_both_profiles():
    for profile in ("uat", None):
        cfg = Config(profile=profile)
        assert cfg.problems() == []
        cfg.validate()                                     # does not raise
    assert Config().tenant == "india"                       # the original config is India's, with or without a 'tenant:' key


def test_missing_key_is_named(tmp_path):
    d = _copy_config(tmp_path, edit=lambda s: s["nexus"].pop("session_file"))
    cfg = Config(d, profile="uat")
    assert cfg.problems() == ["settings.yaml: 'nexus.session_file' is missing or empty"]
    with pytest.raises(ConfigError, match="nexus.session_file"):
        cfg.validate()


def test_every_problem_is_listed_at_once(tmp_path):
    def edit(s):
        s["nexus"]["base_url"] = "uat.example"
        s.pop("paths")
    d = _copy_config(tmp_path, edit=edit, uat_edit=lambda u: u["uat"].pop("row_marker"))
    found = Config(d, profile="uat").problems()
    assert any("must start with http" in p for p in found)
    assert any("section 'paths' is missing" in p for p in found)
    assert any("uat.row_marker" in p for p in found)


def test_mock_profile_does_not_need_the_uat_selectors(tmp_path):
    d = _copy_config(tmp_path, uat_edit=lambda u: u.pop("uat"))
    assert Config(d, profile=None).problems() == []
    assert any("section 'uat' is missing" in p for p in Config(d, profile="uat").problems())


def test_banner_names_tenant_url_db_and_runs_but_no_credentials(tmp_path):
    d = _copy_config(tmp_path, edit=lambda s: s.update(tenant="dubai"))
    b = Config(d, profile="uat").banner()
    assert "tenant=dubai" in b and "nexus=https://" in b and "agent.db" in b and "runs=" in b
    assert "password" not in b.lower() and "token" not in b.lower()


def test_cli_stops_before_running_when_the_config_is_broken(tmp_path, capsys):
    d = _copy_config(tmp_path, edit=lambda s: s["paths"].pop("state_dir"))
    assert main(["--config", str(d), "cases"]) == 2
    err = capsys.readouterr().err
    assert "Nothing was run." in err and "paths.state_dir" in err
