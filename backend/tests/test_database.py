import asyncio

import pytest
from sqlalchemy import text

from app import database


def test_database_dependency_closes_session_after_request(monkeypatch):
    class FakeSession:
        closed = False

        def close(self):
            self.closed = True

    session = FakeSession()
    monkeypatch.setattr(database, "SessionLocal", lambda: session)

    async def consume_dependency():
        dependency = database.get_db()
        yielded = await dependency.__anext__()
        assert yielded is session
        await dependency.aclose()

    asyncio.run(consume_dependency())

    assert session.closed is True


def test_sqlite_connections_enforce_foreign_keys():
    if database.engine.dialect.name != "sqlite":
        pytest.skip("SQLite-specific connection setting")

    with database.engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
