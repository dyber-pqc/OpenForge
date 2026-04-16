"""Waveform data model and VCD/FST parsers.

Production-grade VCD parser with support for $scope, $upscope, $var,
$enddefinitions, $dumpvars, $dumpall, $dumpon, $dumpoff, $dumpoff,
bit/bus/real/integer values including x/z.

FST parsing attempts pylibfst; otherwise falls back to invoking the
``fst2vcd`` helper that ships with GTKWave.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import os


class SignalKind(StrEnum):
    WIRE = "wire"
    REG = "reg"
    INTEGER = "integer"
    REAL = "real"
    EVENT = "event"
    PARAMETER = "parameter"
    BUS = "bus"
    ENUM = "enum"


_VCD_KIND_MAP = {
    "wire": SignalKind.WIRE,
    "reg": SignalKind.REG,
    "integer": SignalKind.INTEGER,
    "real": SignalKind.REAL,
    "realtime": SignalKind.REAL,
    "event": SignalKind.EVENT,
    "parameter": SignalKind.PARAMETER,
    "tri": SignalKind.WIRE,
    "wand": SignalKind.WIRE,
    "wor": SignalKind.WIRE,
    "supply0": SignalKind.WIRE,
    "supply1": SignalKind.WIRE,
    "logic": SignalKind.WIRE,
    "bit": SignalKind.WIRE,
}


class WaveSignal(BaseModel):
    name: str
    full_path: str
    kind: SignalKind
    width: int = 1
    msb: int = 0
    lsb: int = 0
    parent_scope: str = ""
    vcd_id: str = ""  # identifier code from VCD


class WaveTransition(BaseModel):
    time: int
    value: int | str


class WaveScope(BaseModel):
    name: str
    kind: str = "module"
    children: list[WaveScope] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)


WaveScope.model_rebuild()


_TIMESCALE_UNITS = {
    "s": 1_000_000_000_000,
    "ms": 1_000_000_000,
    "us": 1_000_000,
    "ns": 1_000,
    "ps": 1,
    "fs": 0,  # sub-ps gets clamped
}


def _parse_timescale(ts: str) -> int:
    """Return integer ps per tick."""
    m = re.match(r"\s*(\d+)\s*([a-zA-Z]+)\s*", ts)
    if not m:
        return 1000  # default 1ns
    n = int(m.group(1))
    unit = m.group(2).lower()
    scale = _TIMESCALE_UNITS.get(unit, 1000)
    return max(1, n * scale)


def _parse_bin_value(v: str) -> int | str:
    """Parse a VCD bit/vector value. Returns int when fully 0/1, else the
    string (for x/z/mixed)."""
    v = v.strip()
    if not v:
        return 0
    if v[0] in "bB":
        v = v[1:]
    if all(c in "01" for c in v):
        try:
            return int(v, 2) if v else 0
        except ValueError:
            return v
    return v  # keep X/Z/H/L/U/W/- as-is


class Waveform(BaseModel):
    timescale_ps: int = 1000
    end_time: int = 0
    scopes: list[WaveScope] = Field(default_factory=list)
    signals: dict[str, WaveSignal] = Field(default_factory=dict)
    data: dict[str, list[WaveTransition]] = Field(default_factory=dict)

    # ───────── Parsers ─────────
    @classmethod
    def parse_vcd(cls, path: str | os.PathLike) -> Waveform:
        p = Path(path)
        text = p.read_text(errors="replace")
        return cls._parse_vcd_text(text)

    @classmethod
    def _parse_vcd_text(cls, text: str) -> Waveform:
        wf = cls()
        # id → canonical full_path key
        id_to_key: dict[str, list[str]] = {}
        id_width: dict[str, int] = {}
        scope_stack: list[WaveScope] = []
        root_scopes: list[WaveScope] = []

        tokens = text.split()
        i = 0
        n = len(tokens)

        def read_until(end_tok: str) -> list[str]:
            nonlocal i
            out: list[str] = []
            while i < n and tokens[i] != end_tok:
                out.append(tokens[i])
                i += 1
            if i < n:
                i += 1  # consume end
            return out

        in_defs = True
        cur_time = 0
        while i < n:
            tok = tokens[i]
            i += 1
            if in_defs:
                if tok == "$timescale":
                    body = read_until("$end")
                    wf.timescale_ps = _parse_timescale(" ".join(body))
                elif tok == "$scope":
                    body = read_until("$end")
                    kind = body[0] if body else "module"
                    name = body[1] if len(body) > 1 else "top"
                    scope = WaveScope(name=name, kind=kind)
                    if scope_stack:
                        scope_stack[-1].children.append(scope)
                    else:
                        root_scopes.append(scope)
                    scope_stack.append(scope)
                elif tok == "$upscope":
                    read_until("$end")
                    if scope_stack:
                        scope_stack.pop()
                elif tok == "$var":
                    body = read_until("$end")
                    # $var <kind> <width> <id> <name> [<[range]>]
                    if len(body) < 4:
                        continue
                    kind_str = body[0].lower()
                    try:
                        width = int(body[1])
                    except ValueError:
                        width = 1
                    vid = body[2]
                    name = body[3]
                    range_str = " ".join(body[4:]) if len(body) > 4 else ""
                    msb = width - 1
                    lsb = 0
                    m = re.match(r"\[(\-?\d+)(?::(\-?\d+))?\]", range_str)
                    if m:
                        msb = int(m.group(1))
                        lsb = int(m.group(2)) if m.group(2) is not None else msb
                    scope_path = ".".join(s.name for s in scope_stack)
                    full_path = f"{scope_path}.{name}" if scope_path else name
                    kind = _VCD_KIND_MAP.get(kind_str, SignalKind.WIRE)
                    if width > 1 and kind in (SignalKind.WIRE, SignalKind.REG):
                        # Keep original kind, width marks bus-ness
                        pass
                    sig = WaveSignal(
                        name=name,
                        full_path=full_path,
                        kind=kind,
                        width=width,
                        msb=msb,
                        lsb=lsb,
                        parent_scope=scope_path,
                        vcd_id=vid,
                    )
                    wf.signals[full_path] = sig
                    wf.data.setdefault(full_path, [])
                    if scope_stack:
                        scope_stack[-1].signals.append(full_path)
                    id_to_key.setdefault(vid, []).append(full_path)
                    id_width[vid] = width
                elif tok == "$enddefinitions":
                    read_until("$end")
                    in_defs = False
                    wf.scopes = root_scopes
                elif tok.startswith("$"):
                    # ignore comment/version/date
                    if not tok.endswith("$end"):
                        read_until("$end")
                continue

            # simulation section
            if tok.startswith("#"):
                try:
                    cur_time = int(tok[1:])
                except ValueError:
                    continue
                if cur_time > wf.end_time:
                    wf.end_time = cur_time
            elif tok in ("$dumpvars", "$dumpall", "$dumpon", "$dumpoff", "$end"):
                continue
            elif tok[0] in "01xXzZhHlLuUwW-":
                # scalar: value + id (no space)
                val_ch = tok[0]
                vid = tok[1:]
                if not vid:
                    continue
                if val_ch in "01":
                    val: int | str = int(val_ch)
                else:
                    val = val_ch.lower()
                for key in id_to_key.get(vid, ()):
                    wf.data[key].append(WaveTransition(time=cur_time, value=val))
            elif tok[0] in "bB":
                # vector: b<bits> then space then id
                bits = tok[1:]
                if i >= n:
                    break
                vid = tokens[i]
                i += 1
                val = _parse_bin_value("b" + bits)
                for key in id_to_key.get(vid, ()):
                    wf.data[key].append(WaveTransition(time=cur_time, value=val))
            elif tok[0] in "rR":
                # real: r<value> then id
                try:
                    val = tok[1:]
                except Exception:
                    val = "0"
                if i >= n:
                    break
                vid = tokens[i]
                i += 1
                for key in id_to_key.get(vid, ()):
                    wf.data[key].append(WaveTransition(time=cur_time, value=val))
            else:
                # unknown, skip
                continue

        if not wf.scopes:
            wf.scopes = root_scopes
        return wf

    @classmethod
    def parse_fst(cls, path: str | os.PathLike) -> Waveform:
        p = Path(path)
        # Try pylibfst first
        try:
            import pylibfst  # type: ignore

            return cls._parse_fst_pylibfst(p, pylibfst)
        except Exception:
            pass
        # Fallback: fst2vcd
        fst2vcd = shutil.which("fst2vcd")
        if not fst2vcd:
            raise RuntimeError(
                "FST support requires pylibfst or fst2vcd in PATH"
            )
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.vcd"
            subprocess.run(
                [fst2vcd, str(p), "-o", str(out)],
                check=True,
                capture_output=True,
            )
            return cls.parse_vcd(out)

    @classmethod
    def _parse_fst_pylibfst(cls, path: Path, lib) -> Waveform:
        # Best-effort generic shim; pylibfst API varies.
        # If this fails, caller will fall back to fst2vcd.
        raise NotImplementedError("pylibfst direct parse not wired")

    # ───────── Queries ─────────
    def signal_at_time(self, name: str, time: int) -> int | str:
        trs = self.data.get(name)
        if not trs:
            return "x"
        # Binary search for the last transition <= time
        lo, hi = 0, len(trs) - 1
        result: int | str = trs[0].value
        while lo <= hi:
            mid = (lo + hi) // 2
            if trs[mid].time <= time:
                result = trs[mid].value
                lo = mid + 1
            else:
                hi = mid - 1
        return result

    def search(self, name_pattern: str) -> list[str]:
        pat = name_pattern.lower()
        try:
            rx = re.compile(pat)
        except re.error:
            rx = None
        out: list[str] = []
        for key in self.signals:
            kl = key.lower()
            if rx and rx.search(kl) or pat in kl:
                out.append(key)
        return out
