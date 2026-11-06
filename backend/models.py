"""SQLAlchemy ORM models for CodeCompass.

Design notes:
* UUID primary keys are generated client-side, so IDs exist before the INSERT
  and are safe to expose in URLs.
* Foreign keys use ``ondelete="CASCADE"`` at the database level; the ORM
  relationships mirror that with ``passive_deletes=True`` so PostgreSQL, not
  Python, performs the cascade.
* Every foreign key is indexed explicitly: PostgreSQL does not index FKs
  automatically, and cascade deletes/lookups scan without it.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Severity(str, enum.Enum):
    """Ordered debt severity; stored as VARCHAR + CHECK, not a native PG enum."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TimestampMixin:
    """Server-side timestamps so the database clock is the single source of truth."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    repository_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    dependencies: Mapped[list["CodeDependency"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    debt_items: Mapped[list["TechnicalDebtItem"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (Index("ix_projects_name", "name"),)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Project id={self.id} name={self.name!r}>"


class CodeDependency(Base, TimestampMixin):
    """A directed edge in the project's file dependency graph."""

    __tablename__ = "code_dependencies"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_file: Mapped[str] = mapped_column(String(1024), nullable=False)
    target_file: Mapped[str] = mapped_column(String(1024), nullable=False)
    dependency_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="import",
        server_default="import",
    )

    project: Mapped[Project] = relationship(back_populates="dependencies")

    __table_args__ = (
        # One edge per (project, source, target): makes re-scanning idempotent.
        UniqueConstraint(
            "project_id",
            "source_file",
            "target_file",
            name="uq_code_dependencies_project_id_source_file_target_file",
        ),
        Index("ix_code_dependencies_project_id", "project_id"),
        Index("ix_code_dependencies_target_file", "target_file"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CodeDependency {self.source_file} -> {self.target_file}>"


class TechnicalDebtItem(Base, TimestampMixin):
    """A single piece of debt discovered in a project's codebase."""

    __tablename__ = "technical_debt_items"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[Severity] = mapped_column(
        Enum(
            Severity,
            name="debt_severity",
            native_enum=False,
            length=20,
            create_constraint=True,
            validate_strings=True,
            # Persist enum *values* ("high"), not member names ("HIGH"), so the
            # CHECK constraint, server_default and API payloads all agree.
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=Severity.MEDIUM,
        server_default=Severity.MEDIUM.value,
    )
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="code_smell",
        server_default="code_smell",
    )
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proposed_fix: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship(back_populates="debt_items")

    __table_args__ = (
        # Serves the hot query: "debt for this project, worst first".
        Index(
            "ix_technical_debt_items_project_id_severity",
            "project_id",
            "severity",
        ),
        Index("ix_technical_debt_items_severity", "severity"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<TechnicalDebtItem id={self.id} severity={self.severity}>"
