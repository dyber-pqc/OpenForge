"""DAG-based run engine for OpenForge flows.

Executes a :class:`RunGraph` of :class:`RunStage` objects in topological order
with bounded parallelism, captures per-stage logs to disk, detects a simple
input-hash cache hit, and supports cancel / rerun-from.

The engine is deliberately self-contained: stages are subprocess commands
(lists of strings) plus metadata. Higher-level factories live in
``openforge.runner.stages``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .artifacts import ArtifactKind, ArtifactRegistry, detect_kind


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


class RunArtifact(BaseModel):
    """An output file produced by a stage."""

    model_config = ConfigDict(extra="allow")

    name: str
    path: str
    kind: ArtifactKind = ArtifactKind.OTHER
    size_bytes: int = 0
    created_at: str = Field(default_factory=_utcnow)


class RunStage(BaseModel):
    """A single node in a run graph.

    ``command`` is a list of strings passed directly to ``subprocess.Popen``.
    ``cwd`` is the working directory. ``produces`` is a list of glob patterns
    (relative to ``cwd``) that will be scanned for artifacts on success.
    """

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    id: str
    name: str
    tool: str
    command: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    produces: list[str] = Field(default_factory=list)
    cacheable: bool = True

    # runtime state
    status: RunStatus = RunStatus.PENDING
    started_at: str | None = None
    finished_at: str | None = None
    log_path: str | None = None
    artifacts: list[RunArtifact] = Field(default_factory=list)
    exit_code: int | None = None
    cache_hit: bool = False


class RunGraph:
    """A DAG of :class:`RunStage` objects."""

    def __init__(self) -> None:
        self._stages: dict[str, RunStage] = {}

    def add_stage(self, stage: RunStage) -> RunStage:
        if stage.id in self._stages:
            raise ValueError(f"stage id already present: {stage.id}")
        self._stages[stage.id] = stage
        return stage

    def get(self, stage_id: str) -> RunStage:
        return self._stages[stage_id]

    def stages(self) -> list[RunStage]:
        return list(self._stages.values())

    def topological_order(self) -> list[RunStage]:
        """Return stages in a valid topological order (Kahn's algorithm)."""
        indeg: dict[str, int] = {sid: 0 for sid in self._stages}
        for s in self._stages.values():
            for dep in s.depends_on:
                if dep not in self._stages:
                    raise ValueError(f"stage '{s.id}' depends on unknown '{dep}'")
                indeg[s.id] += 1
        ready = [sid for sid, d in indeg.items() if d == 0]
        order: list[RunStage] = []
        while ready:
            sid = ready.pop(0)
            order.append(self._stages[sid])
            for other in self._stages.values():
                if sid in other.depends_on:
                    indeg[other.id] -= 1
                    if indeg[other.id] == 0:
                        ready.append(other.id)
        if len(order) != len(self._stages):
            raise ValueError("cycle detected in run graph")
        return order

    def can_run(self, stage_id: str) -> bool:
        """True if all deps of ``stage_id`` are in SUCCESS/SKIPPED."""
        s = self._stages[stage_id]
        return all(
            self._stages[d].status in (RunStatus.SUCCESS, RunStatus.SKIPPED)
            for d in s.depends_on
        )


class _RunState:
    """In-memory record of a submitted run."""

    def __init__(self, run_id: str, graph: RunGraph, run_dir: Path) -> None:
        self.run_id = run_id
        self.graph = graph
        self.run_dir = run_dir
        self.started_at = _utcnow()
        self.finished_at: str | None = None
        self.cancelled = threading.Event()
        self.futures: dict[str, Future[Any]] = {}
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.lock = threading.Lock()


CallbackStage = Callable[[str, RunStage], None]
CallbackLog = Callable[[str, RunStage, str], None]


class RunEngine:
    """Execute :class:`RunGraph` instances with bounded parallelism."""

    def __init__(self, workspace_dir: str | Path, max_parallel: int = 4) -> None:
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.max_parallel = max_parallel
        self._executor = ThreadPoolExecutor(max_workers=max_parallel)
        self._runs: dict[str, _RunState] = {}
        self._runs_lock = threading.Lock()
        self.artifacts = ArtifactRegistry()

        self.on_stage_start: CallbackStage | None = None
        self.on_stage_progress: CallbackStage | None = None
        self.on_stage_finish: CallbackStage | None = None
        self.on_log_line: CallbackLog | None = None

    # ----- public API -------------------------------------------------------

    def submit(self, graph: RunGraph) -> str:
        """Start executing ``graph``. Returns a run_id. Non-blocking."""
        graph.topological_order()  # validate / raise on cycle
        run_id = uuid.uuid4().hex[:12]
        run_dir = self.workspace_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        state = _RunState(run_id, graph, run_dir)
        with self._runs_lock:
            self._runs[run_id] = state
        # dispatch in a background thread so submit() doesn't block
        threading.Thread(
            target=self._drive, args=(state,), name=f"run-{run_id}", daemon=True
        ).start()
        return run_id

    def cancel(self, run_id: str) -> None:
        state = self._runs.get(run_id)
        if not state:
            return
        state.cancelled.set()
        with state.lock:
            for proc in list(state.processes.values()):
                with contextlib.suppress(Exception):
                    proc.terminate()
        for s in state.graph.stages():
            if s.status in (RunStatus.PENDING, RunStatus.RUNNING):
                s.status = RunStatus.CANCELLED

    def status(self, run_id: str) -> dict[str, Any]:
        state = self._runs.get(run_id)
        if not state:
            return {"run_id": run_id, "found": False}
        stages = [s.model_dump(mode="json") for s in state.graph.stages()]
        return {
            "run_id": run_id,
            "found": True,
            "started_at": state.started_at,
            "finished_at": state.finished_at,
            "cancelled": state.cancelled.is_set(),
            "stages": stages,
        }

    def wait(self, run_id: str, timeout: float | None = None) -> dict[str, Any]:
        """Block until all stages of ``run_id`` reach a terminal state."""
        deadline = None if timeout is None else time.monotonic() + timeout
        state = self._runs.get(run_id)
        if not state:
            return self.status(run_id)
        while True:
            terminal = {
                RunStatus.SUCCESS,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
                RunStatus.SKIPPED,
            }
            if all(s.status in terminal for s in state.graph.stages()):
                return self.status(run_id)
            if deadline is not None and time.monotonic() > deadline:
                return self.status(run_id)
            time.sleep(0.02)

    def rerun_from(self, run_id: str, stage_id: str) -> str:
        """Re-run ``stage_id`` and all its downstream dependents.

        Returns the id of the new run. The new run reuses the same graph
        object; upstream stages keep their SUCCESS state and their outputs
        are still visible via the artifact registry.
        """
        state = self._runs.get(run_id)
        if not state:
            raise KeyError(f"unknown run: {run_id}")
        if stage_id not in {s.id for s in state.graph.stages()}:
            raise KeyError(f"unknown stage: {stage_id}")

        # Build downstream closure
        downstream: set[str] = {stage_id}
        changed = True
        while changed:
            changed = False
            for s in state.graph.stages():
                if s.id in downstream:
                    continue
                if any(d in downstream for d in s.depends_on):
                    downstream.add(s.id)
                    changed = True
        # Reset them
        for s in state.graph.stages():
            if s.id in downstream:
                s.status = RunStatus.PENDING
                s.started_at = None
                s.finished_at = None
                s.exit_code = None
                s.cache_hit = False
                s.artifacts = []
        return self.submit(state.graph)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ----- v2: checkpoint / resume / diff-rerun ----------------------------

    def checkpoint(self, run_id: str) -> Path:
        """Serialize run state to ``workspace/runs/{run_id}/checkpoint.json``."""
        state = self._runs.get(run_id)
        if state is None:
            raise KeyError(f"unknown run: {run_id}")
        data = {
            "run_id": state.run_id,
            "started_at": state.started_at,
            "finished_at": state.finished_at,
            "cancelled": state.cancelled.is_set(),
            "stages": [s.model_dump(mode="json") for s in state.graph.stages()],
        }
        path = state.run_dir / "checkpoint.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def resume(self, run_id: str) -> str:
        """Reload checkpoint and continue from the first incomplete stage.

        Returns the *new* run_id for the re-submission. Any stages that were
        not SUCCESS or SKIPPED are reset to PENDING.
        """
        run_dir = self.workspace_dir / "runs" / run_id
        cp_file = run_dir / "checkpoint.json"
        if not cp_file.exists():
            raise FileNotFoundError(f"no checkpoint for run {run_id}")
        data = json.loads(cp_file.read_text(encoding="utf-8"))

        graph = RunGraph()
        for sd in data.get("stages", []):
            stage = RunStage.model_validate(sd)
            if stage.status not in (RunStatus.SUCCESS, RunStatus.SKIPPED):
                stage.status = RunStatus.PENDING
                stage.started_at = None
                stage.finished_at = None
                stage.exit_code = None
                stage.cache_hit = False
                stage.artifacts = []
            graph.add_stage(stage)
        return self.submit(graph)

    def diff_rerun(self, run_id: str, new_graph: RunGraph) -> str:
        """Re-execute only stages whose input hash changed vs the prior run.

        Stages whose ``(tool, command, env, deps)`` signature is identical
        to the same id in the previous run are marked as SUCCESS and keep
        their artifacts. All others are reset to PENDING and scheduled.
        """
        old = self._runs.get(run_id)
        if old is None:
            raise KeyError(f"unknown run: {run_id}")

        def sig(s: RunStage) -> str:
            h = hashlib.sha256()
            h.update(s.tool.encode())
            h.update(b"\x00")
            h.update(json.dumps(s.command, sort_keys=True).encode())
            h.update(b"\x00")
            h.update(json.dumps(s.env, sort_keys=True).encode())
            h.update(b"\x00")
            h.update(json.dumps(sorted(s.depends_on)).encode())
            return h.hexdigest()

        old_by_id = {s.id: s for s in old.graph.stages()}
        for s in new_graph.stages():
            prev = old_by_id.get(s.id)
            if prev is not None and sig(prev) == sig(s) and prev.status == RunStatus.SUCCESS:
                s.status = RunStatus.SUCCESS
                s.started_at = prev.started_at
                s.finished_at = prev.finished_at
                s.exit_code = prev.exit_code
                s.cache_hit = True
                s.artifacts = list(prev.artifacts)
            else:
                s.status = RunStatus.PENDING
        return self.submit(new_graph)

    # ----- v2: distributed workers -----------------------------------------

    def register_worker(self, worker_url: str) -> None:
        """Register a remote worker URL for distributed dispatch."""
        pool = self._ensure_pool()
        from .dispatch import WorkerNode  # local import to avoid cycles

        url = worker_url.rstrip("/")
        if not any(w.url == url for w in pool.workers):
            pool.workers.append(
                WorkerNode(url=url, name=url, capabilities=[], status="unknown", current_load=0)
            )

    def unregister_worker(self, worker_url: str) -> None:
        pool = self._ensure_pool()
        url = worker_url.rstrip("/")
        pool.workers = [w for w in pool.workers if w.url != url]

    def _ensure_pool(self):  # type: ignore[no-untyped-def]
        if not hasattr(self, "_worker_pool") or self._worker_pool is None:
            from .dispatch import WorkerPool

            self._worker_pool = WorkerPool(workers=[])
        return self._worker_pool

    def dispatch_stage(self, stage: RunStage, worker_url: str) -> dict[str, Any]:
        """POST the stage spec to a worker and poll until complete."""
        from .dispatch import WorkerNode
        from .dispatch import dispatch as _dispatch

        node = WorkerNode(
            url=worker_url.rstrip("/"),
            name=worker_url,
            capabilities=[],
            status="unknown",
            current_load=0,
        )
        return _dispatch(stage, node)

    def local_or_remote(self, stage: RunStage) -> str:
        """Decide whether to execute ``stage`` locally or on a remote worker.

        Returns either the string ``"local"`` or a worker URL. Uses the stage
        ``cost_hint`` (extra field, default 0) and current worker load.
        """
        pool = self._ensure_pool() if hasattr(self, "_worker_pool") else None
        cost = 0
        try:
            cost = int(getattr(stage, "cost_hint", 0) or 0)
        except Exception:
            cost = 0
        if not pool or not pool.workers:
            return "local"
        if cost < 5:
            return "local"
        worker = pool.best_for(stage)
        if worker is None:
            return "local"
        return worker.url

    # ----- execution core ---------------------------------------------------

    def _drive(self, state: _RunState) -> None:
        """Main scheduling loop - runs in its own thread."""
        graph = state.graph
        try:
            order = graph.topological_order()
        except Exception:
            state.finished_at = _utcnow()
            return

        pending = [s for s in order if s.status == RunStatus.PENDING]
        running: dict[str, Future[Any]] = {}

        while pending or running:
            if state.cancelled.is_set():
                break
            # launch newly-ready stages up to max_parallel
            progressed = False
            for s in list(pending):
                if len(running) >= self.max_parallel:
                    break
                if not graph.can_run(s.id):
                    # skip if any dep failed/cancelled
                    if any(
                        graph.get(d).status
                        in (RunStatus.FAILED, RunStatus.CANCELLED)
                        for d in s.depends_on
                    ):
                        s.status = RunStatus.SKIPPED
                        pending.remove(s)
                        progressed = True
                        if self.on_stage_finish:
                            self.on_stage_finish(state.run_id, s)
                    continue
                pending.remove(s)
                fut = self._executor.submit(self._run_stage, state, s)
                running[s.id] = fut
                progressed = True

            # harvest completed
            done_ids: list[str] = []
            for sid, fut in running.items():
                if fut.done():
                    done_ids.append(sid)
            for sid in done_ids:
                running.pop(sid, None)
                progressed = True

            if not progressed:
                time.sleep(0.01)

        state.finished_at = _utcnow()

    def _run_stage(self, state: _RunState, stage: RunStage) -> None:
        """Execute a single stage. Runs inside the thread pool."""
        stage_dir = state.run_dir / stage.id
        stage_dir.mkdir(parents=True, exist_ok=True)
        log_path = stage_dir / "stage.log"
        stage.log_path = str(log_path)

        # Cache check
        cache_key = self._cache_key(state, stage)
        cache_file = stage_dir / "cache.json"
        if stage.cacheable and self._cache_hit(state, stage, cache_key):
            stage.status = RunStatus.SUCCESS
            stage.cache_hit = True
            stage.started_at = _utcnow()
            stage.finished_at = stage.started_at
            stage.exit_code = 0
            log_path.write_text("[cache hit]\n", encoding="utf-8")
            self._collect_artifacts(state, stage)
            if self.on_stage_finish:
                self.on_stage_finish(state.run_id, stage)
            return

        stage.status = RunStatus.RUNNING
        stage.started_at = _utcnow()
        if self.on_stage_start:
            self.on_stage_start(state.run_id, stage)

        if not stage.command:
            # nothing to run - treat as success
            stage.status = RunStatus.SUCCESS
            stage.exit_code = 0
            stage.finished_at = _utcnow()
            log_path.write_text("[no-op stage]\n", encoding="utf-8")
            self._collect_artifacts(state, stage)
            self._cache_write(cache_file, cache_key)
            if self.on_stage_finish:
                self.on_stage_finish(state.run_id, stage)
            return

        try:
            cwd = Path(stage.cwd) if stage.cwd else stage_dir
            cwd.mkdir(parents=True, exist_ok=True)
            with log_path.open("wb") as logf:
                proc = subprocess.Popen(
                    stage.command,
                    cwd=str(cwd),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env={**dict(__import__("os").environ), **stage.env},
                )
                with state.lock:
                    state.processes[stage.id] = proc
                assert proc.stdout is not None
                for line in proc.stdout:
                    logf.write(line)
                    logf.flush()
                    if self.on_log_line:
                        with contextlib.suppress(Exception):
                            self.on_log_line(
                                state.run_id, stage, line.decode("utf-8", "replace")
                            )
                    if self.on_stage_progress:
                        with contextlib.suppress(Exception):
                            self.on_stage_progress(state.run_id, stage)
                rc = proc.wait()
                with state.lock:
                    state.processes.pop(stage.id, None)
            stage.exit_code = rc
            if state.cancelled.is_set():
                stage.status = RunStatus.CANCELLED
            elif rc == 0:
                stage.status = RunStatus.SUCCESS
                self._collect_artifacts(state, stage)
                self._cache_write(cache_file, cache_key)
            else:
                stage.status = RunStatus.FAILED
        except Exception as e:  # noqa: BLE001
            stage.status = RunStatus.FAILED
            stage.exit_code = -1
            with log_path.open("ab") as logf:
                logf.write(f"\n[engine error] {e}\n".encode())
        finally:
            stage.finished_at = _utcnow()
            if self.on_stage_finish:
                with contextlib.suppress(Exception):
                    self.on_stage_finish(state.run_id, stage)

    # ----- artifacts & cache -----------------------------------------------

    def _collect_artifacts(self, state: _RunState, stage: RunStage) -> None:
        stage_dir = state.run_dir / stage.id
        search_root = Path(stage.cwd) if stage.cwd else stage_dir
        collected: list[RunArtifact] = []
        patterns = stage.produces or ["*"]
        seen: set[str] = set()
        for pat in patterns:
            for p in search_root.glob(pat):
                if not p.is_file():
                    continue
                key = str(p.resolve())
                if key in seen:
                    continue
                seen.add(key)
                art = RunArtifact(
                    name=p.name,
                    path=str(p),
                    kind=detect_kind(p),
                    size_bytes=p.stat().st_size,
                )
                collected.append(art)
                self.artifacts.register(state.run_id, stage.id, art)
        stage.artifacts = collected

    def _cache_key(self, state: _RunState, stage: RunStage) -> str:
        h = hashlib.sha256()
        h.update(stage.tool.encode())
        h.update(b"\x00")
        h.update(json.dumps(stage.command, sort_keys=True).encode())
        h.update(b"\x00")
        h.update(json.dumps(stage.env, sort_keys=True).encode())
        h.update(b"\x00")
        # include upstream artifact paths + sizes
        for dep in stage.depends_on:
            dep_stage = state.graph.get(dep)
            for a in dep_stage.artifacts:
                h.update(a.path.encode())
                h.update(str(a.size_bytes).encode())
        return h.hexdigest()

    def _cache_hit(self, state: _RunState, stage: RunStage, key: str) -> bool:
        cache_file = state.run_dir / stage.id / "cache.json"
        if not cache_file.exists():
            return False
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            return False
        return data.get("key") == key

    def _cache_write(self, cache_file: Path, key: str) -> None:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps({"key": key, "at": _utcnow()}), encoding="utf-8"
            )
        except Exception:
            pass


__all__ = [
    "RunEngine",
    "RunGraph",
    "RunStage",
    "RunStatus",
    "RunArtifact",
]
