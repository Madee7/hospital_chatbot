"""
Database configuration for FastAPI application using SQLAlchemy 2.0.

This module provides database connection setup, session management,
and base configuration for ORM models.
"""

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Session,
    sessionmaker,
)

from app.core.config import DATABASE_URL


engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True,
    echo=False,
)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    future=True,
)


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy ORM models.
    """
    pass


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI database dependency.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    """
    Create database tables.

    Development use only.
    Production should use Alembic migrations.
    """
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
