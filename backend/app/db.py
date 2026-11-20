"""Database engine/session management (SQLAlchemy 2, sync sessions; PostgreSQL in Compose, SQLite in dev/tests)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.is_sqlite = url.startswith("sqlite")
        kwargs: dict = {"future": True, "pool_pre_ping": True}
        if self.is_sqlite:
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        self.engine: Engine = create_engine(url, **kwargs)
        if self.is_sqlite:
            event.listen(self.engine, "connect", _sqlite_pragmas)
        self._factory = sessionmaker(self.engine, expire_on_commit=False, class_=Session)

    def create_all(self) -> None:
        from app.models import Base

        Base.metadata.create_all(self.engine)

    def drop_all(self) -> None:
        from app.models import Base

        Base.metadata.drop_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self._factory()
        try:
            yield s
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def new_session(self) -> Session:
        return self._factory()


def _sqlite_pragmas(dbapi_conn, _record) -> None:  # noqa: ANN001 - DBAPI connection
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


_override: Database | None = None


@lru_cache
def _default_db() -> Database:
    from app.config import get_settings

    settings = get_settings()
    if settings.database_url.startswith("sqlite:///"):
        from pathlib import Path

        Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return Database(settings.database_url)


def get_db() -> Database:
    return _override or _default_db()


def set_db(db: Database | None) -> None:
    """Swap the process database (tests, CLI tools)."""
    global _override
    _override = db
