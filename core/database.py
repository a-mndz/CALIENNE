"""
Database configuration using SQLAlchemy (async) and asyncpg.
Provides async engine, sessionmaker, Base declarative class, and dependency injection helper.
"""

from pathlib import Path
from typing import Any, AsyncGenerator

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.config import get_settings

settings = get_settings()

# HIGH-016 audit fix: database SSL is now configurable via ``DATABASE_SSL``
# environment variable.  Default ``False`` keeps local development friction
# free; production deployments must set this to ``True`` so the underlying
# asyncpg driver negotiates an encrypted channel.
def get_engine_kwargs(db_url: str) -> dict:
    kwargs = {"echo": False}
    if db_url.startswith("postgresql"):
        connect_args: dict[str, Any] = {"ssl": settings.DATABASE_SSL}
        if getattr(settings, "DATABASE_STATEMENT_CACHE_SIZE", None) is not None:
            connect_args["statement_cache_size"] = settings.DATABASE_STATEMENT_CACHE_SIZE
        kwargs.update({
            "pool_size": getattr(settings, "DATABASE_POOL_SIZE", 20),
            "max_overflow": getattr(settings, "DATABASE_MAX_OVERFLOW", 10),
            "pool_timeout": getattr(settings, "DATABASE_POOL_TIMEOUT", 30),
            "pool_pre_ping": True,
            "pool_recycle": 3600,
            "connect_args": connect_args,
        })
    return kwargs

engine = create_async_engine(
    settings.DATABASE_URL,
    **get_engine_kwargs(settings.DATABASE_URL),
)


async def verify_schema_current() -> None:
    """Fail startup when database revision is not at Alembic head."""
    root = Path(__file__).resolve().parent.parent
    alembic_config = Config(str(root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(root / "migrations"))
    expected_heads = set(ScriptDirectory.from_config(alembic_config).get_heads())
    async with engine.connect() as connection:
        current_heads = await connection.run_sync(
            lambda sync_connection: set(
                MigrationContext.configure(sync_connection).get_current_heads()
            )
        )
    if current_heads != expected_heads:
        raise RuntimeError(
            "Database schema is not current: "
            f"found {sorted(current_heads) or ['unversioned']}, "
            f"expected {sorted(expected_heads)}. Run 'alembic upgrade head'."
        )

async_session_maker = async_sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)

# Modern Declarative Base class (SQLAlchemy 2.0 style)
class Base(DeclarativeBase):
    pass

# FastAPI Dependency for obtaining an async session per request
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an asynchronous database session.
    The session is automatically closed when the request block finishes.
    Safely rolls back on BaseException (including asyncio.CancelledError).
    """
    session = async_session_maker()
    try:
        yield session
    except BaseException:
        try:
            await session.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            await session.close()
        except Exception:
            pass
