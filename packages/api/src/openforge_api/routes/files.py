"""File management routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Body, HTTPException, Query, status

from openforge_api.models.schemas import (
    FileContent,
    FileCreateRequest,
    FileNode,
    FileSearchResult,
)

if TYPE_CHECKING:
    from uuid import UUID

router = APIRouter()


# ---------------------------------------------------------------------------
# In-memory store (placeholder -- will be backed by filesystem/git)
# ---------------------------------------------------------------------------

_project_files: dict[UUID, dict[str, str]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_project(project_id: UUID) -> dict[str, str]:
    """Return the file store for a project, or raise 404."""
    files = _project_files.get(project_id)
    if files is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return files


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/{project_id}/tree", response_model=FileNode)
async def get_file_tree(project_id: UUID) -> FileNode:
    """Get the file tree structure for a project."""
    files = _ensure_project(project_id)

    # Build a flat-to-tree structure
    # TODO: Replace with real filesystem walk
    root = FileNode(name="/", path="/", is_dir=True)
    for path, content in sorted(files.items()):
        parts = path.strip("/").split("/")
        current = root
        for i, part in enumerate(parts):
            partial = "/" + "/".join(parts[: i + 1])
            is_last = i == len(parts) - 1
            existing = next((c for c in current.children if c.name == part), None)
            if existing is None:
                node = FileNode(
                    name=part,
                    path=partial,
                    is_dir=not is_last,
                    size=len(content.encode()) if is_last else 0,
                )
                current.children.append(node)
                current = node
            else:
                current = existing

    return root


@router.get("/{project_id}/content", response_model=FileContent)
async def read_file(
    project_id: UUID,
    path: str = Query(..., description="Relative file path within the project"),
) -> FileContent:
    """Read the content of a file in a project."""
    files = _ensure_project(project_id)
    content = files.get(path)
    if content is None:
        raise HTTPException(status_code=404, detail="File not found")

    # Detect language from extension
    ext = path.rsplit(".", 1)[-1] if "." in path else ""
    lang_map = {
        "v": "verilog",
        "sv": "systemverilog",
        "vhd": "vhdl",
        "vhdl": "vhdl",
        "py": "python",
        "rs": "rust",
        "json": "json",
        "yaml": "yaml",
        "yml": "yaml",
        "toml": "toml",
        "tcl": "tcl",
        "sdc": "tcl",
        "lib": "liberty",
    }

    return FileContent(
        path=path,
        content=content,
        language=lang_map.get(ext, ""),
    )


@router.put(
    "/{project_id}/content",
    response_model=FileContent,
    status_code=status.HTTP_200_OK,
)
async def write_file(
    project_id: UUID,
    body: FileContent = Body(...),
) -> FileContent:
    """Write content to a file in a project (creates or overwrites)."""
    files = _ensure_project(project_id)
    # TODO: Write to actual filesystem and track in git
    files[body.path] = body.content
    return body


@router.post(
    "/{project_id}/create",
    response_model=FileNode,
    status_code=status.HTTP_201_CREATED,
)
async def create_file(
    project_id: UUID,
    body: FileCreateRequest = Body(...),
) -> FileNode:
    """Create a new file or directory in a project."""
    files = _ensure_project(project_id)

    if body.path in files and not body.is_dir:
        raise HTTPException(status_code=409, detail="File already exists")

    if not body.is_dir:
        files[body.path] = body.content

    # TODO: Create on actual filesystem
    return FileNode(
        name=body.path.rsplit("/", 1)[-1],
        path=body.path,
        is_dir=body.is_dir,
        size=len(body.content.encode()) if not body.is_dir else 0,
    )


@router.delete("/{project_id}/file", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    project_id: UUID,
    path: str = Query(..., description="Relative file path to delete"),
) -> None:
    """Delete a file from a project."""
    files = _ensure_project(project_id)
    if path not in files:
        raise HTTPException(status_code=404, detail="File not found")
    # TODO: Delete from actual filesystem
    del files[path]


@router.get("/{project_id}/search", response_model=list[FileSearchResult])
async def search_files(
    project_id: UUID,
    q: str = Query(..., min_length=1, description="Search query (substring match)"),
    glob: str = Query("*", description="File glob pattern filter"),
    limit: int = Query(100, ge=1, le=1000),
) -> list[FileSearchResult]:
    """Search file contents within a project (grep-like)."""
    files = _ensure_project(project_id)
    results: list[FileSearchResult] = []

    for path, content in files.items():
        # Simple glob matching -- TODO: use fnmatch for real glob
        if glob != "*" and not path.endswith(glob.lstrip("*")):
            continue

        for line_number, line in enumerate(content.splitlines(), start=1):
            if q in line:
                results.append(
                    FileSearchResult(path=path, line_number=line_number, line=line)
                )
                if len(results) >= limit:
                    return results

    return results
