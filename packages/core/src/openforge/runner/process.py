"""Process runner with live output streaming for EDA tool execution."""

from __future__ import annotations

import asyncio
import subprocess
import time
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Final outcome of a streamed process execution."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    command: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the process exited with code 0."""
        return self.returncode == 0


class ProcessRunner:
    """Wraps subprocess execution with live output streaming.

    Designed for use by :class:`SimulationRunner` to stream compilation
    and simulation output to the console panel in real-time.
    """

    @staticmethod
    def run_with_output(
        cmd: Sequence[str],
        *,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        callback: Callable[[str], None] | None = None,
    ) -> ProcessResult:
        """Execute a command synchronously, calling *callback* for each output line.

        Parameters
        ----------
        cmd:
            Command and arguments to execute.
        cwd:
            Working directory for the subprocess.
        env:
            Environment variables for the subprocess.
        timeout:
            Maximum wall-clock seconds before the process is killed.
        callback:
            Called with each line of combined stdout/stderr as it arrives.
            If *None*, output is silently collected.
        """
        work_dir = str(cwd) if cwd else None
        start = time.monotonic()
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        try:
            proc = subprocess.Popen(
                list(cmd),
                cwd=work_dir,
                env=dict(env) if env else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            msg = f"Command not found: {cmd[0]}"
            if callback:
                callback(msg)
            return ProcessResult(
                returncode=-1,
                stderr=msg,
                duration=time.monotonic() - start,
                command=list(cmd),
            )

        import selectors

        sel = selectors.DefaultSelector()
        if proc.stdout:
            sel.register(proc.stdout, selectors.EVENT_READ)
        if proc.stderr:
            sel.register(proc.stderr, selectors.EVENT_READ)

        try:
            while sel.get_map():
                # Respect timeout
                elapsed = time.monotonic() - start
                if timeout is not None and elapsed >= timeout:
                    proc.kill()
                    proc.wait()
                    msg = f"Process timed out after {timeout}s"
                    if callback:
                        callback(msg)
                    return ProcessResult(
                        returncode=-1,
                        stdout="".join(stdout_lines),
                        stderr="".join(stderr_lines) + f"\n{msg}",
                        duration=time.monotonic() - start,
                        command=list(cmd),
                    )

                remaining = (timeout - elapsed) if timeout else None
                events = sel.select(timeout=min(remaining, 0.1) if remaining else 0.1)

                for key, _ in events:
                    line = key.fileobj.readline()  # type: ignore[union-attr]
                    if not line:
                        sel.unregister(key.fileobj)
                        continue

                    if key.fileobj is proc.stdout:
                        stdout_lines.append(line)
                    else:
                        stderr_lines.append(line)

                    if callback:
                        callback(line.rstrip("\n"))

                # Check if process has ended and no more data
                if proc.poll() is not None and not events:
                    # Drain remaining
                    if proc.stdout:
                        for line in proc.stdout:
                            stdout_lines.append(line)
                            if callback:
                                callback(line.rstrip("\n"))
                    if proc.stderr:
                        for line in proc.stderr:
                            stderr_lines.append(line)
                            if callback:
                                callback(line.rstrip("\n"))
                    break
        finally:
            sel.close()

        proc.wait()

        return ProcessResult(
            returncode=proc.returncode or 0,
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
            duration=time.monotonic() - start,
            command=list(cmd),
        )

    @staticmethod
    async def run_async_with_output(
        cmd: Sequence[str],
        *,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> AsyncGenerator[str, None]:
        """Execute a command asynchronously, yielding output lines as they arrive.

        Parameters
        ----------
        cmd:
            Command and arguments to execute.
        cwd:
            Working directory for the subprocess.
        env:
            Environment variables for the subprocess.
        timeout:
            Maximum wall-clock seconds before the process is killed.

        Yields
        ------
        str
            Each line of combined stdout/stderr output (newline stripped).
        """
        work_dir = str(cwd) if cwd else None
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=work_dir,
                env=dict(env) if env else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            yield f"[ERROR] Command not found: {cmd[0]}"
            return

        async def _read_stream(
            stream: asyncio.StreamReader | None,
        ) -> AsyncGenerator[str, None]:
            if stream is None:
                return
            while True:
                line_bytes = await stream.readline()
                if not line_bytes:
                    break
                yield line_bytes.decode(errors="replace").rstrip("\n")

        # Merge stdout and stderr into a single async stream
        async def _merged() -> AsyncGenerator[str, None]:
            tasks: dict[str, asyncio.Task[bytes | None]] = {}
            stdout_done = False
            stderr_done = False

            while not (stdout_done and stderr_done):
                # Check timeout
                if timeout is not None and (time.monotonic() - start) >= timeout:
                    proc.kill()
                    await proc.wait()
                    yield f"[ERROR] Process timed out after {timeout}s"
                    return

                if not stdout_done and proc.stdout and "stdout" not in tasks:
                    tasks["stdout"] = asyncio.create_task(proc.stdout.readline())
                if not stderr_done and proc.stderr and "stderr" not in tasks:
                    tasks["stderr"] = asyncio.create_task(proc.stderr.readline())

                if not tasks:
                    break

                done, _ = await asyncio.wait(
                    tasks.values(),
                    timeout=0.1,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in done:
                    line_bytes = task.result()
                    # Determine which stream
                    for name, t in list(tasks.items()):
                        if t is task:
                            del tasks[name]
                            if not line_bytes:
                                if name == "stdout":
                                    stdout_done = True
                                else:
                                    stderr_done = True
                            else:
                                yield line_bytes.decode(errors="replace").rstrip("\n")
                            break

        async for line in _merged():
            yield line

        await proc.wait()
