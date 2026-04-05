"""Project CRUD routes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    """Request body for creating a project."""

    name: str = Field(..., min_length=1, max_length=128, examples=["my-crypto-core"])
    description: str = Field("", max_length=1024)
    template: str = Field("empty", examples=["crypto-accelerator", "simple-counter", "empty"])


class ProjectSummary(BaseModel):
    """Abbreviated project info for list views."""

    id: UUID
    name: str
    created_at: datetime


class ProjectDetail(BaseModel):
    """Full project representation."""

    id: UUID
    name: str
    description: str
    template: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# In-memory store (placeholder)
# ---------------------------------------------------------------------------

_projects: dict[UUID, ProjectDetail] = {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[ProjectSummary])
async def list_projects() -> list[ProjectSummary]:
    """List all projects."""
    # TODO: Replace with database query via openforge-core
    return [
        ProjectSummary(id=p.id, name=p.name, created_at=p.created_at)
        for p in _projects.values()
    ]


@router.post("/", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate) -> ProjectDetail:
    """Create a new project."""
    now = datetime.utcnow()
    project = ProjectDetail(
        id=uuid4(),
        name=body.name,
        description=body.description,
        template=body.template,
        created_at=now,
        updated_at=now,
    )
    # TODO: Persist to database and scaffold project files on disk
    _projects[project.id] = project
    return project


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: UUID) -> ProjectDetail:
    """Get a project by ID."""
    project = _projects.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: UUID) -> None:
    """Delete a project."""
    if project_id not in _projects:
        raise HTTPException(status_code=404, detail="Project not found")
    # TODO: Clean up project files on disk
    del _projects[project_id]
