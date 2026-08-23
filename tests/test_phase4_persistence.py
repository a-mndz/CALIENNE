from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.models import CheckpointRecord
from orchestrator.checkpoints import CheckpointManager

pytestmark = pytest.mark.integration


def _docker_available() -> bool:
    try:
        import docker
        from testcontainers.postgres import PostgresContainer  # noqa: F401

        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_real_database_checkpoint_latest_and_owner_delete(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'checkpoints.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: CheckpointRecord.__table__.create(sync_connection)
            )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        manager = CheckpointManager("database", db_session_factory=factory)

        alice_old = await manager.save_checkpoint(
            request_id="shared",
            user_email="alice@example.com",
            session_id="alice-session",
            stage="first",
            agent_outputs={},
            partial_results={},
        )
        await manager.save_checkpoint(
            request_id="shared",
            user_email="alice@example.com",
            session_id="alice-session",
            stage="latest",
            agent_outputs={},
            partial_results={},
        )
        bob_id = await manager.save_checkpoint(
            request_id="shared",
            user_email="bob@example.com",
            session_id="bob-session",
            stage="bob",
            agent_outputs={},
            partial_results={},
        )

        latest = await manager.get_latest_checkpoint("shared", "alice@example.com")
        assert latest is not None and latest.stage == "latest"
        assert await manager.delete_checkpoints("shared", "alice@example.com") == 2
        assert await manager.restore_checkpoint(alice_old, "alice@example.com") is None
        assert await manager.restore_checkpoint(bob_id, "bob@example.com") is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_database_checkpoint_rejects_expired_read(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'expired.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: CheckpointRecord.__table__.create(sync_connection)
            )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        manager = CheckpointManager("database", db_session_factory=factory)
        checkpoint_id = await manager.save_checkpoint(
            request_id="expired",
            user_email="alice@example.com",
            session_id=None,
            stage="old",
            agent_outputs={},
            partial_results={},
        )
        async with factory() as session:
            record = (
                await session.execute(
                    select(CheckpointRecord).where(
                        CheckpointRecord.checkpoint_id == checkpoint_id
                    )
                )
            ).scalar_one()
            record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()

        assert await manager.restore_checkpoint(checkpoint_id, "alice@example.com") is None
        assert await manager.get_latest_checkpoint("expired", "alice@example.com") is None
    finally:
        await engine.dispose()


@pytest.mark.slow
@pytest.mark.skipif(not _docker_available(), reason="Docker/testcontainers unavailable")
def test_alembic_postgres_upgrade_and_downgrade() -> None:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as postgres:
        database_url = postgres.get_connection_url().replace(
            "postgresql+psycopg2", "postgresql+asyncpg"
        )
        env = {
            **os.environ,
            "DATABASE_URL": database_url,
            "CALIENNE_JWT_SECRET_KEY": "test-only-do-not-use-in-production-32chars-min",
        }
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
            env=env,
        )
        subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "base"],
            check=True,
            env=env,
        )
