import asyncio

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.database import get_db
from app.main import app
from app import models  # noqa: F401 - register models with metadata


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = testing_session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def api_client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    class InProcessApiClient:
        def request(self, method, path, **kwargs):
            async def send():
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    return await client.request(method, path, **kwargs)

            return asyncio.run(send())

        def get(self, path, **kwargs):
            return self.request("GET", path, **kwargs)

        def post(self, path, **kwargs):
            return self.request("POST", path, **kwargs)

        def put(self, path, **kwargs):
            return self.request("PUT", path, **kwargs)

        def delete(self, path, **kwargs):
            return self.request("DELETE", path, **kwargs)

        def close(self):
            pass

    client = InProcessApiClient()
    yield client
    client.close()
    app.dependency_overrides.clear()
