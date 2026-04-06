"""Abstract base class for EDA tool engines and shared data types."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from os import PathLike
from pathlib import Path
from typing import Mapping, Sequence


class ExecutionBackend(StrEnum):
    """How the tool binary is invoked."""

    NATIVE = "native"
    DOCKER = "docker"


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Outcome of a single tool invocation."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    command: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the process exited with code 0."""
        return self.returncode == 0


class ToolEngine(ABC):
    """Base class every EDA tool wrapper must implement.

    Subclasses set :pyattr:`BINARY` / :pyattr:`DOCKER_IMAGE` and provide
    high-level operations such as *compile*, *synthesize*, *lint*, etc.
    """

    #: Name of the CLI binary (e.g. ``"verilator"``, ``"yosys"``).
    BINARY: str = ""
    #: Default Docker image used when *backend* is ``DOCKER``.
    DOCKER_IMAGE: str = ""

    def __init__(
        self,
        *,
        backend: ExecutionBackend = ExecutionBackend.NATIVE,
        binary_override: str | None = None,
        docker_image_override: str | None = None,
    ) -> None:
        self.backend = backend
        self.binary = binary_override or self.BINARY
        self.docker_image = docker_image_override or self.DOCKER_IMAGE

    # ------------------------------------------------------------------
    # Required interface
    # ------------------------------------------------------------------

    @abstractmethod
    def check_installed(self) -> bool:
        """Return *True* when the tool is available on the current system."""
        ...

    @abstractmethod
    def version(self) -> str:
        """Return the tool's version string."""
        ...

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------

    async def run_async(
        self,
        args: Sequence[str],
        *,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Execute the tool asynchronously and return a :class:`ToolResult`."""
        cmd = self._build_command(args, cwd=cwd)
        work_dir = str(cwd) if cwd else None
        start = time.monotonic()

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir if self.backend == ExecutionBackend.NATIVE else None,
            env=dict(env) if env else None,
        )
        try:
            raw_out, raw_err = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult(
                returncode=-1,
                stderr=f"Process timed out after {timeout}s",
                duration=time.monotonic() - start,
                command=cmd,
            )

        return ToolResult(
            returncode=proc.returncode or 0,
            stdout=raw_out.decode(errors="replace"),
            stderr=raw_err.decode(errors="replace"),
            duration=time.monotonic() - start,
            command=cmd,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_command(
        self,
        args: Sequence[str],
        *,
        cwd: str | PathLike[str] | None = None,
    ) -> list[str]:
        """Construct the full argv, wrapping in ``docker run`` when needed."""
        if self.backend == ExecutionBackend.DOCKER:
            docker_cmd: list[str] = ["docker", "run", "--rm"]
            if cwd:
                vol = str(Path(cwd).resolve())
                # Convert Windows backslashes to forward slashes for Docker
                vol = vol.replace("\\", "/")
                docker_cmd += ["-v", f"{vol}:/work", "-w", "/work"]
            docker_cmd.append(self.docker_image)
            docker_cmd.append(self.binary)
            docker_cmd.extend(args)
            return docker_cmd

        return [self.binary, *args]

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Execute the tool synchronously and return a :class:`ToolResult`.

        On Windows with MSYS/Git Bash, sets MSYS_NO_PATHCONV=1 to
        prevent path mangling when using Docker.
        """
        cmd = self._build_command(args, cwd=cwd)
        work_dir = str(cwd) if cwd else None
        start = time.monotonic()

        # Merge environment: inherit OS env + user overrides + MSYS fix
        import os
        run_env = dict(os.environ)
        if env:
            run_env.update(env)
        if self.backend == ExecutionBackend.DOCKER:
            run_env["MSYS_NO_PATHCONV"] = "1"

        try:
            proc = subprocess.run(
                cmd,
                cwd=work_dir if self.backend == ExecutionBackend.NATIVE else None,
                env=run_env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return ToolResult(
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration=time.monotonic() - start,
                command=cmd,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                returncode=-1,
                stderr=f"Process timed out after {timeout}s",
                duration=time.monotonic() - start,
                command=cmd,
            )
        except FileNotFoundError:
            return ToolResult(
                returncode=-1,
                stderr=f"Tool binary not found: {cmd[0]}",
                duration=time.monotonic() - start,
                command=cmd,
            )

    def _which(self) -> str | None:
        """Locate the binary on ``$PATH``, or *None*."""
        return shutil.which(self.binary)
