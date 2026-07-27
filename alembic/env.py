"""
Alembic migration environment.

Uses the same DATABASE_URL and SQLAlchemy Base/models as the app,
so `alembic revision --autogenerate` compares real models to the live DB.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# App imports: settings + metadata that registers every ORM table.
from app.core.config import DATABASE_URL
from app.db.database import Base
import app.models  # noqa: F401  — register models on Base.metadata

config = context.config

# Prefer the app's DATABASE_URL (.env / environment) over the placeholder
# in alembic.ini so local and server always use the right database.
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL scripts without connecting to the database."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
