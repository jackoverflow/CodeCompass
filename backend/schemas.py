"""Pydantic v2 request/response schemas for the public API.

Schemas are the API contract: they validate and normalize input before it ever
reaches the ORM, and they keep database columns out of the wire format.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from .models import Severity


class ProjectBase(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=255,
        examples=["codecompass-api"],
        description="Human readable project name.",
    )
    repository_url: HttpUrl = Field(
        max_length=2048,
        examples=["https://github.com/acme/codecompass"],
        description="Clone URL of the repository to analyse.",
    )

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_name(cls, value: object) -> object:
        """Trim surrounding whitespace and reject whitespace-only names."""
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                raise ValueError("name must not be blank")
            return cleaned
        return value


class ProjectCreate(ProjectBase):
    description: str | None = Field(
        default=None,
        max_length=2000,
        examples=["Maps architecture drift and technical debt."],
    )


class ProjectRead(ProjectBase):
    """Serialized project returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class ScanRequest(BaseModel):
    """Body of ``POST /projects/{project_id}/scan``."""

    directory_path: str = Field(
        min_length=1,
        max_length=4096,
        examples=["/workspaces/my-service"],
        description="Absolute path of a local directory to analyse.",
    )

    @field_validator("directory_path", mode="before")
    @classmethod
    def _normalize_path(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                raise ValueError("directory_path must not be blank")
            return cleaned
        return value


class ScanSummary(BaseModel):
    """Counts produced by a scan."""

    files_scanned: int = Field(ge=0, examples=[42])
    dependencies_found: int = Field(ge=0, examples=[137])
    debt_items_found: int = Field(ge=0, examples=[2])


class DependencyRead(BaseModel):
    """One edge of the import graph."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_file: str
    target_file: str
    dependency_type: str


class DebtItemRead(BaseModel):
    """One technical debt finding."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None = None
    severity: Severity
    category: str
    file_path: str | None = None
    line_number: int | None = None
    proposed_fix: str | None = None


class ProjectDetail(ProjectRead):
    """Project plus everything the dashboard needs to render a scan."""

    dependencies: list[DependencyRead] = Field(default_factory=list)
    debt_items: list[DebtItemRead] = Field(default_factory=list)
