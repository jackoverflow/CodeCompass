"""Database engine, session factory and declarative base.

Everything is driven by ``DATABASE_URL`` so the same code runs unchanged in the
dev container, in CI and in production. The engine is created once at import
time and shared process-wide; sessions are short-lived and per request.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@db:5432/architecture_mapper",
)

# Deterministic constraint names keep Alembic autogenerate diffs stable and make
# production errors ("violates constraint ...") readable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # discard connections killed by a DB restart/pooler
    pool_size=5,
    max_overflow=10,
    pool_recycle=1800,  # recycle before idle-connection timeouts bite
    pool_timeout=30,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,  # keep ORM objects usable after commit (response serialization)
)


class Base(DeclarativeBase):
    """Declarative base shared by every model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: exactly one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
