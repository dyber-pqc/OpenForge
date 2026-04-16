"""Bus / protocol decoders for waveform analysis.

Each decoder consumes a sequence of ``WaveTransition`` objects (and in the
case of multi-signal protocols, a dict of signals) and emits a list of
``(start_time, end_time, label)`` packets.

Built-in radix decoders: hex, dec, oct, bin, ascii, enum, fixed, float.
Built-in protocol decoders: i2c, spi, uart, axi-lite.
"""

from __future__ import annotations

import re
import struct
from typing import Any, Callable

from pydantic import BaseModel, Field

from openforge.format.waveform import WaveSignal, WaveTransition


class DecodeRule(BaseModel):
    name: str
    signal_pattern: str
    kind: str  # hex/dec/oct/bin/ascii/enum/fixed/float/i2c/spi/uart/axi
    params: dict[str, Any] = Field(default_factory=dict)


Packet = tuple[int, int, str]


def _coerce_int(v: int | str) -> int | None:
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v, 2)
        except ValueError:
            return None
    return None


def _format_radix(v: int | str, width: int, radix: str) -> str:
    iv = _coerce_int(v)
    if iv is None:
        return str(v).upper()
    if radix == "hex":
        digits = max(1, (width + 3) // 4)
        return f"{iv:0{digits}X}h"
    if radix == "dec":
        return str(iv)
    if radix == "oct":
        digits = max(1, (width + 2) // 3)
        return f"{iv:0{digits}o}o"
    if radix == "bin":
        return f"{iv:0{max(1,width)}b}b"
    if radix == "ascii":
        try:
            return "".join(
                chr((iv >> (8 * i)) & 0xFF) or "."
                for i in range(max(1, width // 8) - 1, -1, -1)
            )
        except Exception:
            return f"{iv:X}"
    return str(iv)


def _format_fixed(v: int | str, width: int, q_int: int, q_frac: int, signed: bool) -> str:
    iv = _coerce_int(v)
    if iv is None:
        return str(v)
    if signed and iv & (1 << (width - 1)):
        iv -= 1 << width
    return f"{iv / (1 << q_frac):.{min(6, q_frac)}f}"


def _format_float(v: int | str, width: int) -> str:
    iv = _coerce_int(v)
    if iv is None:
        return str(v)
    try:
        if width <= 32:
            b = struct.pack(">I", iv & 0xFFFFFFFF)
            return f"{struct.unpack('>f', b)[0]:g}"
        b = struct.pack(">Q", iv & 0xFFFFFFFFFFFFFFFF)
        return f"{struct.unpack('>d', b)[0]:g}"
    except Exception:
        return str(iv)


class BusDecoder:
    def __init__(self, rules: list[DecodeRule] | None = None) -> None:
        self.rules: list[DecodeRule] = rules or []

    # ──────────── entry point ────────────
    def decode(
        self,
        signal: WaveSignal,
        transitions: list[WaveTransition],
    ) -> list[Packet]:
        rule = self._match_rule(signal)
        if rule is None:
            return self._decode_radix(signal, transitions, "hex")
        k = rule.kind
        if k in ("hex", "dec", "oct", "bin", "ascii"):
            return self._decode_radix(signal, transitions, k)
        if k == "enum":
            return self._decode_enum(signal, transitions, rule.params)
        if k == "fixed":
            return self._decode_fixed(signal, transitions, rule.params)
        if k == "float":
            return self._decode_float(signal, transitions)
        # Protocols are typically multi-signal and handled via their own
        # explicit entry points; decoding a single line here is best effort.
        if k == "uart":
            return self.decode_uart(transitions, rule.params.get("baud", 115200), rule.params.get("clk_hz", 50_000_000))
        return self._decode_radix(signal, transitions, "hex")

    def _match_rule(self, signal: WaveSignal) -> DecodeRule | None:
        for r in self.rules:
            try:
                if re.search(r.signal_pattern, signal.full_path):
                    return r
            except re.error:
                if r.signal_pattern in signal.full_path:
                    return r
        return None

    # ──────────── radix decoders ────────────
    def _decode_radix(
        self,
        signal: WaveSignal,
        trs: list[WaveTransition],
        radix: str,
    ) -> list[Packet]:
        out: list[Packet] = []
        for idx, t in enumerate(trs):
            end = trs[idx + 1].time if idx + 1 < len(trs) else t.time
            out.append((t.time, end, _format_radix(t.value, signal.width, radix)))
        return out

    def _decode_enum(
        self,
        signal: WaveSignal,
        trs: list[WaveTransition],
        params: dict,
    ) -> list[Packet]:
        mapping: dict[int, str] = {int(k): str(v) for k, v in params.get("map", {}).items()}
        out: list[Packet] = []
        for idx, t in enumerate(trs):
            end = trs[idx + 1].time if idx + 1 < len(trs) else t.time
            iv = _coerce_int(t.value)
            label = mapping.get(iv, f"?{iv}") if iv is not None else str(t.value)
            out.append((t.time, end, label))
        return out

    def _decode_fixed(
        self,
        signal: WaveSignal,
        trs: list[WaveTransition],
        params: dict,
    ) -> list[Packet]:
        q_int = int(params.get("q_int", signal.width // 2))
        q_frac = int(params.get("q_frac", signal.width - q_int))
        signed = bool(params.get("signed", True))
        out: list[Packet] = []
        for idx, t in enumerate(trs):
            end = trs[idx + 1].time if idx + 1 < len(trs) else t.time
            out.append(
                (
                    t.time,
                    end,
                    _format_fixed(t.value, signal.width, q_int, q_frac, signed),
                )
            )
        return out

    def _decode_float(
        self,
        signal: WaveSignal,
        trs: list[WaveTransition],
    ) -> list[Packet]:
        out: list[Packet] = []
        for idx, t in enumerate(trs):
            end = trs[idx + 1].time if idx + 1 < len(trs) else t.time
            out.append((t.time, end, _format_float(t.value, signal.width)))
        return out

    # ──────────── protocol decoders ────────────
    def decode_i2c(
        self,
        sda: list[WaveTransition],
        scl: list[WaveTransition],
    ) -> list[Packet]:
        """Decode an I2C transaction given SDA and SCL transition streams."""
        events = self._merge_two(sda, scl)  # list of (time, sda, scl)
        out: list[Packet] = []
        in_frame = False
        bits: list[int] = []
        start_t = 0
        byte_start = 0
        phase = "idle"  # idle / addr / data / ack
        prev_sda = 1
        prev_scl = 1
        addr_byte: int | None = None
        for t, s, c in events:
            # START: SDA falls while SCL high
            if prev_scl == 1 and c == 1 and prev_sda == 1 and s == 0:
                out.append((t, t, "START"))
                in_frame = True
                bits = []
                phase = "addr"
                start_t = t
                byte_start = t
            # STOP: SDA rises while SCL high
            elif prev_scl == 1 and c == 1 and prev_sda == 0 and s == 1 and in_frame:
                out.append((t, t, "STOP"))
                in_frame = False
                phase = "idle"
            # Sample on rising SCL
            elif prev_scl == 0 and c == 1 and in_frame:
                bits.append(s & 1)
                if phase in ("addr", "data") and len(bits) == 8:
                    val = 0
                    for b in bits:
                        val = (val << 1) | b
                    if phase == "addr":
                        rw = "R" if (val & 1) else "W"
                        out.append((byte_start, t, f"ADDR {val >> 1:02X} {rw}"))
                        addr_byte = val
                    else:
                        out.append((byte_start, t, f"DATA {val:02X}"))
                    bits = []
                    phase = "ack"
                elif phase == "ack" and len(bits) == 1:
                    out.append((byte_start, t, "ACK" if bits[0] == 0 else "NACK"))
                    bits = []
                    phase = "data"
                    byte_start = t
                elif len(bits) == 1 and phase in ("addr", "data"):
                    byte_start = t
            prev_sda = s
            prev_scl = c
        return out

    def decode_spi(
        self,
        mosi: list[WaveTransition],
        miso: list[WaveTransition],
        sclk: list[WaveTransition],
        cs: list[WaveTransition],
        cpol: int = 0,
        cpha: int = 0,
        bits_per_word: int = 8,
    ) -> list[Packet]:
        out: list[Packet] = []
        events = self._merge_many({"mosi": mosi, "miso": miso, "sclk": sclk, "cs": cs})
        cur = {"mosi": 0, "miso": 0, "sclk": cpol, "cs": 1}
        prev_sclk = cpol
        prev_cs = 1
        word_mosi = 0
        word_miso = 0
        count = 0
        frame_start = 0
        active_edge = 1 if cpha == 0 else 0  # sample edge (simplified)
        # cpol=0 cpha=0: sample on rising edge
        sample_rising = (cpol == 0 and cpha == 0) or (cpol == 1 and cpha == 1)
        for t, name, val in events:
            cur[name] = val if isinstance(val, int) else 0
            if name == "cs":
                if prev_cs == 1 and cur["cs"] == 0:
                    frame_start = t
                    word_mosi = word_miso = 0
                    count = 0
                elif prev_cs == 0 and cur["cs"] == 1:
                    if count:
                        out.append(
                            (
                                frame_start,
                                t,
                                f"SPI {word_mosi:0{(count + 3)//4}X}/{word_miso:0{(count + 3)//4}X}",
                            )
                        )
                    count = 0
                prev_cs = cur["cs"]
            elif name == "sclk" and cur["cs"] == 0:
                rising = prev_sclk == 0 and cur["sclk"] == 1
                falling = prev_sclk == 1 and cur["sclk"] == 0
                if (sample_rising and rising) or ((not sample_rising) and falling):
                    word_mosi = (word_mosi << 1) | (cur["mosi"] & 1)
                    word_miso = (word_miso << 1) | (cur["miso"] & 1)
                    count += 1
                    if count == bits_per_word:
                        out.append(
                            (
                                frame_start,
                                t,
                                f"SPI {word_mosi:0{(bits_per_word + 3)//4}X}/{word_miso:0{(bits_per_word + 3)//4}X}",
                            )
                        )
                        word_mosi = word_miso = 0
                        count = 0
                        frame_start = t
                prev_sclk = cur["sclk"]
        return out

    def decode_uart(
        self,
        line: list[WaveTransition],
        baud: int = 115200,
        clk_hz: int = 50_000_000,
    ) -> list[Packet]:
        """8N1 UART decode. Time units are VCD ticks; caller supplies
        the bit period via baud+clk mapping (we assume 1 tick == 1ns)."""
        if not line:
            return []
        bit_period_ns = max(1, 1_000_000_000 // max(1, baud))
        # Assume 1 tick == 1ns here; caller can re-scale.
        out: list[Packet] = []
        # Walk looking for falling edges = start bit
        i = 0
        while i < len(line):
            t = line[i]
            val = _coerce_int(t.value) or 0
            if val == 0:
                # sample 8 data bits at centre of each bit period
                start_t = t.time
                byte = 0
                for bit in range(8):
                    sample_t = start_t + (bit + 1) * bit_period_ns + bit_period_ns // 2
                    # find state at sample_t
                    v = 0
                    for tr in line:
                        if tr.time <= sample_t:
                            cv = _coerce_int(tr.value)
                            if cv is not None:
                                v = cv & 1
                        else:
                            break
                    byte |= (v & 1) << bit
                end_t = start_t + 10 * bit_period_ns
                ch = chr(byte) if 32 <= byte < 127 else "."
                out.append((start_t, end_t, f"UART {byte:02X} '{ch}'"))
                # advance past this frame
                while i < len(line) and line[i].time < end_t:
                    i += 1
                continue
            i += 1
        return out

    def decode_axi_lite(
        self,
        channels: dict[str, list[WaveTransition]],
    ) -> list[Packet]:
        """Group AW/W/B handshakes into transactions.

        ``channels`` must include keys: awvalid, awready, awaddr, wvalid,
        wready, wdata, bvalid, bready."""
        req = ("awvalid", "awready", "awaddr", "wvalid", "wready", "wdata", "bvalid", "bready")
        for r in req:
            channels.setdefault(r, [])
        events = self._merge_many(channels)
        state = {k: 0 for k in req}
        out: list[Packet] = []
        aw_t: int | None = None
        w_t: int | None = None
        aw_addr = 0
        w_data = 0
        for t, name, val in events:
            iv = _coerce_int(val)
            if iv is not None:
                state[name] = iv
            if state["awvalid"] and state["awready"] and aw_t is None:
                aw_t = t
                aw_addr = state["awaddr"]
            if state["wvalid"] and state["wready"] and w_t is None:
                w_t = t
                w_data = state["wdata"]
            if state["bvalid"] and state["bready"] and aw_t is not None:
                out.append(
                    (
                        aw_t,
                        t,
                        f"AXI WR @{aw_addr:08X}={w_data:08X}",
                    )
                )
                aw_t = w_t = None
        return out

    # ──────────── helpers ────────────
    @staticmethod
    def _merge_two(
        a: list[WaveTransition], b: list[WaveTransition]
    ) -> list[tuple[int, int, int]]:
        """Merge two 1-bit streams into (time, a_val, b_val) triples."""
        events: list[tuple[int, int, int]] = []
        ai = bi = 0
        av = bv = 0
        times = sorted({*(t.time for t in a), *(t.time for t in b)})
        for tt in times:
            while ai < len(a) and a[ai].time <= tt:
                cv = _coerce_int(a[ai].value)
                if cv is not None:
                    av = cv & 1
                ai += 1
            while bi < len(b) and b[bi].time <= tt:
                cv = _coerce_int(b[bi].value)
                if cv is not None:
                    bv = cv & 1
                bi += 1
            events.append((tt, av, bv))
        return events

    @staticmethod
    def _merge_many(
        streams: dict[str, list[WaveTransition]],
    ) -> list[tuple[int, str, int | str]]:
        """Return interleaved (time, name, value) tuples sorted by time."""
        merged: list[tuple[int, str, int | str]] = []
        for name, trs in streams.items():
            for t in trs:
                merged.append((t.time, name, t.value))
        merged.sort(key=lambda x: x[0])
        return merged
