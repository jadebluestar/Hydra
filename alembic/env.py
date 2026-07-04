"""
Alembic async migration environment.

This file is executed by every alembic CLI command. It:
  1. Loads the database URL from application settings (not from alembic.ini)
  2. Imports all models so their tables appear in Base.metadata
  3. Configures online (real DB connection) and offline (SQL script) modes

Adding a new model:
  After creating a model in models/, add its import to the "Model imports"
  section below. Without the import, Alembic cannot see the table and will
  generate "drop table" migrations to remove it.

Running migrations:
  # Apply all pending migrations
  alembic upgrade head

  # Roll back the most recent migration
  alembic downgrade -1

  # Generate a migration from model changes
  alembic revision --autogenerate -m "add users table"

  # Preview SQL without touching the database
  alembic upgrade head --sql
"""

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Safety net: ensure the project root is in sys.path even if alembic.ini's
# prepend_sys_path didn't work (e.g., when running from a different cwd).
_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.config import get_settings  # noqa: E402
from database.base import Base  # noqa: E402

# ── Model imports ──────────────────────────────────────────────────────────────
# Every SQLAlchemy model that defines a __tablename__ MUST be imported here.
# Alembic uses Base.metadata to detect schema changes during autogenerate.
# Without these imports the tables are invisible to autogenerate and it will
# generate DROP TABLE statements to remove them.
import models  # noqa: F401 — registers all models with Base.metadata
# ──────────────────────────────────────────────────────────────────────────────

alembic_config = context.config

# Override the placeholder sqlalchemy.url from alembic.ini with the real URL
# from application settings. This ensures migrations always target the same
# database as the running application.
settings = get_settings()
alembic_config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Offline mode: generate SQL DDL without connecting to the database.

    Useful for:
    - Reviewing the exact SQL before applying it
    - Deploying to a database you can't access from your local machine
    - Regulatory requirements where all schema changes need SQL sign-off

    Invoked with: alembic upgrade head --sql
    """
    url = alembic_config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_server_default=True,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """
    Synchronous migration runner invoked via run_sync() inside the async context.

    Alembic's migration API is synchronous. run_sync() bridges the async
    connection from asyncpg into a sync-compatible wrapper that Alembic can use.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_server_default=True,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations online."""
    connectable = async_engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section, {}),
        prefix="sqlalchemy.",
        # NullPool: no connection pooling for one-off migration runs.
        # Connection pooling is designed for long-running servers that reuse
        # connections. A migration tool runs once and exits — pooling adds
        # overhead and can cause "connection not returned to pool" issues.
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
