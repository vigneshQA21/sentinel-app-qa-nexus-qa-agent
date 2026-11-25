"""select_parent waits for the header to show the chosen parent and never reads a half-switched viewer."""
import pytest
from nexus_agent.nexus.uat import UatPages


class _Page:
    def __init__(self): self.waits = 0
    def wait_for_timeout(self, ms): self.waits += 1
    def get_by_text(self, name, exact=True):
        class L:
            last = type("C", (), {"click": staticmethod(lambda timeout=0: None)})()
        return L()


def _ui(shown_seq):
    ui = UatPages.__new__(UatPages)
    ui.page = _Page()
    seq = iter(shown_seq)
    last = {"v": ""}
    def shown():
        try: last["v"] = next(seq)
        except StopIteration: pass
        return last["v"]
    ui._open_dropdown = lambda: None
    ui._parent_shown = shown
    return ui


def test_waits_until_header_shows_the_parent():
    ui = _ui(["Master (1)", "Master (1)", "Air Manifest"])
    ui.select_parent("Air Manifest")                       # header lags two polls, then switches: no error


def test_raises_instead_of_reading_a_stale_parent():
    ui = _ui(["Master (1)"])
    with pytest.raises(RuntimeError, match="could not switch the viewer"):
        ui.select_parent("Air Manifest", attempts=2, settle_s=1.0)
