"""Durable final-status outbox. Contains search metadata, never credentials."""

import json
import os
from pathlib import Path


def state_path():
    directory = Path(os.environ.get("GMAPSCRAP_STATE_DIR", Path.home() / "Library/Application Support/GmapScrap"))
    return directory / "pending-search.json"


def pending_search():
    path = state_path()
    if not path.exists():
        return None
    return json.loads(path.read_text())


def remember_search(run):
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def forget_search():
    state_path().unlink(missing_ok=True)
