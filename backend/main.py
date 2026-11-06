"""FastAPI entry point for the Living Architecture & Technical Debt Mapper backend."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from .database import engine, get_db
from .models import Project
from .scanner import scan_directory
from .schemas import (
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
    ScanRequest,
    ScanSummary,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Release pooled connections on shutdown instead of leaking them."""
    yield
    engine.dispose()


app = FastAPI(
    title="Living Architecture & Technical Debt Mapper API",
    version="0.1.0",
    lifespan=lifespan,
)

# The Next.js dev server runs on :3000; allow it during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Liveness check: the API is up and can reach PostgreSQL."""
    database = "ok"
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        database = f"unavailable: {exc.__class__.__name__}"

    return {"status": "ok", "database": database}


@app.post(
    "/projects/",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    tags=["projects"],
    summary="Register a project for analysis",
    responses={409: {"description": "Project conflicts with an existing record"}},
)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
) -> Project:
    """Persist a new project and return it with server-generated fields."""
    project = Project(
        name=payload.name,
        repository_url=str(payload.repository_url),
        description=payload.description,
    )
    db.add(project)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project could not be created due to a conflicting record.",
        ) from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable, please retry.",
        ) from None

    # Load server defaults (created_at/updated_at) into the instance.
    db.refresh(project)
    return project


@app.get(
    "/projects/{project_id}",
    response_model=ProjectDetail,
    tags=["projects"],
    summary="Fetch a project with its dependency graph and debt items",
    responses={404: {"description": "Project not found"}},
)
def get_project(
    project_id: UUID,
    db: Session = Depends(get_db),
) -> Project:
    """Return one project plus its scan results.

    ``selectinload`` issues one extra query per collection instead of a row
    multiplication join, so a project with thousands of edges stays two queries.
    """
    statement = (
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.dependencies),
            selectinload(Project.debt_items),
        )
    )
    project = db.scalars(statement).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    return project


def _resolve_scan_directory(raw_path: str) -> Path:
    """Validate the requested scan root and return its canonical path.

    ``resolve(strict=True)`` collapses ``..``/symlinks before any check, so the
    containment test below cannot be bypassed with a crafted path.
    """
    try:
        resolved = Path(raw_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"directory_path does not exist: {raw_path}",
        ) from None

    if not resolved.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"directory_path is not a directory: {raw_path}",
        )

    # Optional defence in depth: set SCAN_ROOT to confine scans to a workspace.
    allowed_root = os.getenv("SCAN_ROOT")
    if allowed_root:
        try:
            boundary = Path(allowed_root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SCAN_ROOT is misconfigured.",
            ) from None
        if not resolved.is_relative_to(boundary):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="directory_path is outside the permitted scan root.",
            )

    return resolved


@app.post(
    "/projects/{project_id}/scan",
    response_model=ScanSummary,
    status_code=status.HTTP_200_OK,
    tags=["projects"],
    summary="Statically analyse a local directory for a project",
    responses={
        400: {"description": "directory_path is missing or not a directory"},
        403: {"description": "directory_path is outside SCAN_ROOT"},
        404: {"description": "Project not found"},
        422: {"description": "Scan aborted (too many files)"},
    },
)
def scan_project(
    project_id: UUID,
    payload: ScanRequest,
    db: Session = Depends(get_db),
) -> ScanSummary:
    """Scan a local directory and persist its dependency graph and debt items."""
    if db.get(Project, project_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    directory = _resolve_scan_directory(payload.directory_path)

    try:
        result = scan_directory(project_id, str(directory), db)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable, please retry.",
        ) from None

    return ScanSummary(
        files_scanned=result.files_scanned,
        dependencies_found=result.dependencies_found,
        debt_items_found=result.debt_items_found,
    )
