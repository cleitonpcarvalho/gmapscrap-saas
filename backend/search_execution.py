"""Serialize desktop status and ingestion, including across PostgreSQL workers.

The advisory transaction uses a separate connection: existing lead helpers commit
their own sessions, which would otherwise release a row lock before ingestion ends.
"""

from contextlib import contextmanager
from threading import RLock

from fastapi import Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth import get_current_username
from backend.database import get_db
from backend.models import SearchRun

TERMINAL_SEARCH_STATES = {"completed", "failed", "stopped"}
_locks = [RLock() for _ in range(128)]


@contextmanager
def desktop_execution_lock(db, run_id):
    with _locks[run_id % len(_locks)]:
        if db.get_bind().dialect.name == "postgresql":
            with db.get_bind().connect() as connection, connection.begin():
                connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 0x474D000000000000 + run_id})
                yield
        else:
            yield


def locked_desktop_run(run_id: int, db: Session = Depends(get_db), username=Depends(get_current_username)):
    with desktop_execution_lock(db, run_id):
        run = db.get(SearchRun, run_id, populate_existing=True)
        if run is None:
            raise HTTPException(404, "Busca não encontrada")
        yield run
