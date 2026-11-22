"""Minimal async SQLite setup; tables created on startup for the classroom MVP."""

from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from .models import Base


def sqlite_engine(path: Path) -> AsyncEngine:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.resolve()}")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def sessions(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Small additive migration for existing student databases.
        # create_all() does not update previously created tables.
        columns = (await conn.execute(text("PRAGMA table_info(articles)"))).all()
        if "content" not in {column[1] for column in columns}:
            await conn.execute(text("ALTER TABLE articles ADD COLUMN content TEXT"))
        user_columns = (await conn.execute(text("PRAGMA table_info(users)"))).all()
        if "add_synonyms" not in {column[1] for column in user_columns}:
            await conn.execute(text("ALTER TABLE users ADD COLUMN add_synonyms BOOLEAN NOT NULL DEFAULT 0"))
