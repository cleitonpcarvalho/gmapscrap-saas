import sys
from pathlib import Path
import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


@pytest.fixture(autouse=True)
def isolated_desktop_state(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAPSCRAP_STATE_DIR", str(tmp_path / "desktop-state"))
