"""Opens Nexus with the saved session and prints LOGGED IN or SESSION EXPIRED."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexus_agent.config import Config  # noqa: E402
from nexus_agent.nexus.session import NexusSession  # noqa: E402

cfg = Config(profile="uat")
with NexusSession(cfg, headless=True) as s:
    s.page.goto(cfg.base_url + cfg.settings["nexus"]["home_path"])
    ok = s.is_logged_in()
print("LOGGED IN" if ok else "SESSION EXPIRED - run: python -m nexus_agent login")
sys.exit(0 if ok else 1)
