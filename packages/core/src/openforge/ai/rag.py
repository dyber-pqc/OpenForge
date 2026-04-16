"""Simple RAG index backed by Ollama embeddings.

The index walks a project tree, embeds text chunks using a local Ollama
model (``nomic-embed-text`` by default), and supports cosine-similarity
top-k search. Designed to be small, dependency-free and persistable to a
local JSON cache so re-opening a project does not re-embed everything.

Handles the common degraded case gracefully: if Ollama is unavailable,
:meth:`embed_text` returns an empty vector and :meth:`search` falls back
to naive substring matching so the AI assistant still functions.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from openforge.ai.ollama_client import OllamaClient

if TYPE_CHECKING:
    from collections.abc import Iterable

DEFAULT_GLOBS = ["**/*.v", "**/*.sv", "**/*.svh", "**/*.vh", "**/*.sdc", "**/*.yaml", "**/*.yml", "**/*.md"]
DEFAULT_EMBED_MODEL = "nomic-embed-text"
CHUNK_MAX_CHARS = 1800


class RagDoc(BaseModel):
    """A single indexed chunk."""

    path: str
    content: str
    embedding: list[float] = Field(default_factory=list)
    kind: str = "text"
    metadata: dict = Field(default_factory=dict)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _chunk(text: str, size: int = CHUNK_MAX_CHARS) -> list[str]:
    if len(text) <= size:
        return [text]
    out: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        nl = text.rfind("\n", start + size // 2, end)
        if nl > start:
            end = nl
        out.append(text[start:end])
        start = end
    return out


def _kind_for(path: Path) -> str:
    s = path.suffix.lower()
    if s in (".v", ".sv", ".vh", ".svh"):
        return "rtl"
    if s in (".vhd", ".vhdl"):
        return "vhdl"
    if s == ".sdc":
        return "sdc"
    if s in (".yaml", ".yml"):
        return "config"
    if s == ".md":
        return "doc"
    return "text"


class RagIndex:
    """Local, file-backed RAG store."""

    def __init__(
        self,
        project_root: str | Path,
        cache_dir: str | Path | None = None,
        client: OllamaClient | None = None,
        embed_model: str = DEFAULT_EMBED_MODEL,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.cache_dir = Path(cache_dir) if cache_dir else self.project_root / ".openforge" / "rag"
        self.client = client or OllamaClient()
        self.embed_model = embed_model
        self.docs: list[RagDoc] = []
        self._hashes: dict[str, str] = {}

    # -- embeddings ------------------------------------------------------

    def embed_text(self, text: str) -> list[float]:
        try:
            return self.client.embed(self.embed_model, text)
        except Exception:
            return []

    # -- indexing --------------------------------------------------------

    def index_project(self, globs: Iterable[str] | None = None) -> int:
        globs = list(globs) if globs else DEFAULT_GLOBS
        count = 0
        seen: set[str] = set()
        new_docs: list[RagDoc] = []
        for pattern in globs:
            for p in self.project_root.glob(pattern):
                if not p.is_file():
                    continue
                rel = str(p.relative_to(self.project_root))
                if rel in seen:
                    continue
                seen.add(rel)
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                digest = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()
                self._hashes[rel] = digest
                for i, chunk in enumerate(_chunk(text)):
                    emb = self.embed_text(chunk)
                    new_docs.append(
                        RagDoc(
                            path=rel,
                            content=chunk,
                            embedding=emb,
                            kind=_kind_for(p),
                            metadata={"chunk": i, "sha1": digest},
                        )
                    )
                    count += 1
        self.docs = new_docs
        return count

    def incremental_update(self, changed_files: Iterable[str | Path]) -> int:
        updated = 0
        changed_rel: set[str] = set()
        for f in changed_files:
            p = Path(f)
            if not p.is_absolute():
                p = self.project_root / p
            try:
                rel = str(p.relative_to(self.project_root))
            except ValueError:
                continue
            changed_rel.add(rel)
        if not changed_rel:
            return 0
        # drop old chunks for changed files
        self.docs = [d for d in self.docs if d.path not in changed_rel]
        for rel in changed_rel:
            p = self.project_root / rel
            if not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            digest = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()
            self._hashes[rel] = digest
            for i, chunk in enumerate(_chunk(text)):
                emb = self.embed_text(chunk)
                self.docs.append(
                    RagDoc(
                        path=rel,
                        content=chunk,
                        embedding=emb,
                        kind=_kind_for(p),
                        metadata={"chunk": i, "sha1": digest},
                    )
                )
                updated += 1
        return updated

    # -- search ----------------------------------------------------------

    def search(self, query: str, top_k: int = 5) -> list[RagDoc]:
        if not self.docs:
            return []
        q_emb = self.embed_text(query)
        if q_emb:
            scored = [(_cosine(q_emb, d.embedding), d) for d in self.docs if d.embedding]
            scored.sort(key=lambda x: x[0], reverse=True)
            return [d for s, d in scored[:top_k] if s > 0]
        # fallback: naive substring match
        q_lower = query.lower()
        ranked = sorted(
            self.docs,
            key=lambda d: d.content.lower().count(q_lower),
            reverse=True,
        )
        return [d for d in ranked[:top_k] if q_lower in d.content.lower()]

    # -- persistence -----------------------------------------------------

    def _cache_file(self) -> Path:
        return self.cache_dir / "index.json"

    def save_index(self) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        f = self._cache_file()
        payload = {
            "embed_model": self.embed_model,
            "hashes": self._hashes,
            "docs": [d.model_dump() for d in self.docs],
        }
        f.write_text(json.dumps(payload), encoding="utf-8")
        return f

    def load_index(self) -> bool:
        f = self._cache_file()
        if not f.exists():
            return False
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return False
        self._hashes = dict(payload.get("hashes", {}))
        self.docs = [RagDoc(**d) for d in payload.get("docs", [])]
        return True


__all__ = ["RagDoc", "RagIndex", "DEFAULT_EMBED_MODEL"]
