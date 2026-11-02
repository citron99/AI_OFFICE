from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.base import Base
from app.db.session import create_engine, create_session_factory
from app.db.tables.process_runtime import ProcessRuntimeRecord
from app.main import create_app


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    test_engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    # TZ 7.1: a fresh tenant now starts at A1 recommendation, not A2 draft.
    # The synthetic pilot tenant has been promoted to A2 through the same
    # OWNER runtime endpoint a real operator would use, so tests that need
    # a draft may proceed keep working without weakening the default.
    async with create_session_factory(test_engine)() as session:
        session.add(
            ProcessRuntimeRecord(
                company_id="comp_demo",
                process_id="office_review",
                autonomy_level="a2_draft",
                updated_by="usr_demo_owner",
            )
        )
        await session.commit()
    yield test_engine
    await test_engine.dispose()


@pytest_asyncio.fixture
async def client(engine: AsyncEngine, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        app_env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        llm_provider="mock",
        embedding_provider="mock",
        auto_create_schema=False,
        upload_dir=tmp_path / "uploads",
        max_upload_bytes=1024,
    )
    app = create_app(
        settings=settings,
        engine=engine,
        session_factory=create_session_factory(engine),
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
            yield api_client
