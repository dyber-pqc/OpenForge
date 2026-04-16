"""Parametric footprint generators for OpenForge PCB.

Each function returns a :class:`PcbFootprint` with manufacturing-grade pad
sizes, courtyards and silkscreen. Numbers come from IPC-7351B "Least/
Nominal" land patterns where applicable.
"""
from __future__ import annotations

from openforge.pcb.model import PcbFootprint, PcbPad

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _smd_pad(name: str, x: float, y: float, sx: float, sy: float,
             shape: str = "rect") -> PcbPad:
    return PcbPad(
        name=name, x_mm=x, y_mm=y, shape=shape,  # type: ignore[arg-type]
        size_x_mm=sx, size_y_mm=sy, drill_mm=0.0,
        layers=["F.Cu", "F.Mask", "F.Paste"],
    )


def _tht_pad(name: str, x: float, y: float, pad: float, drill: float,
             shape: str = "round") -> PcbPad:
    return PcbPad(
        name=name, x_mm=x, y_mm=y, shape=shape,  # type: ignore[arg-type]
        size_x_mm=pad, size_y_mm=pad, drill_mm=drill,
        layers=["F.Cu", "B.Cu", "F.Mask", "B.Mask"],
    )


def _rect_courtyard(w: float, h: float,
                    margin: float = 0.25) -> list[tuple[float, float]]:
    hw = w / 2 + margin
    hh = h / 2 + margin
    return [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh), (-hw, -hh)]


def _rect_silk(w: float, h: float) -> list[tuple[float, float, float, float]]:
    hw = w / 2
    hh = h / 2
    return [
        (-hw, -hh, hw, -hh),
        (hw, -hh, hw, hh),
        (hw, hh, -hw, hh),
        (-hw, hh, -hw, -hh),
    ]


# ---------------------------------------------------------------------------
# pin headers / sockets
# ---------------------------------------------------------------------------


def pin_header(rows: int, cols: int,
               pitch_mm: float = 2.54) -> PcbFootprint:
    """Through-hole pin header (rows x cols), round pads, square pad on pin 1."""
    pads: list[PcbPad] = []
    pad_dia = max(1.7, pitch_mm * 0.66)
    drill = max(0.9, pitch_mm * 0.35)
    x0 = -(cols - 1) * pitch_mm / 2
    y0 = -(rows - 1) * pitch_mm / 2
    n = 1
    for c in range(cols):
        for r in range(rows):
            shape = "rect" if n == 1 else "round"
            pads.append(_tht_pad(str(n),
                                 x0 + c * pitch_mm,
                                 y0 + r * pitch_mm,
                                 pad_dia, drill, shape))
            n += 1
    body_w = cols * pitch_mm
    body_h = rows * pitch_mm
    return PcbFootprint(
        name=f"PinHeader_{rows}x{cols:02d}_P{pitch_mm:.2f}mm",
        library="openforge_connectors", ref="J?",
        pads=pads,
        courtyard=_rect_courtyard(body_w + 0.8, body_h + 0.8),
        silkscreen=_rect_silk(body_w, body_h),
        description=f"{rows}x{cols} header, {pitch_mm}mm pitch",
    )


def terminal_block(pins: int, pitch_mm: float = 5.08) -> PcbFootprint:
    """Phoenix-style screw terminal block."""
    pads = []
    pad_dia = 2.4
    drill = 1.3
    x0 = -(pins - 1) * pitch_mm / 2
    for i in range(pins):
        shape = "rect" if i == 0 else "round"
        pads.append(_tht_pad(str(i + 1), x0 + i * pitch_mm, 0.0,
                             pad_dia, drill, shape))
    body_w = pins * pitch_mm
    body_h = pitch_mm * 1.6
    return PcbFootprint(
        name=f"TerminalBlock_{pins}P_P{pitch_mm:.2f}mm",
        library="openforge_connectors", ref="J?",
        pads=pads,
        courtyard=_rect_courtyard(body_w + 0.5, body_h + 0.5),
        silkscreen=_rect_silk(body_w, body_h),
        description=f"{pins}-way screw terminal, {pitch_mm}mm pitch",
    )


# ---------------------------------------------------------------------------
# basic pads
# ---------------------------------------------------------------------------


def custom_pad(width_mm: float, height_mm: float,
               shape: str = "rect") -> PcbFootprint:
    pad = _smd_pad("1", 0.0, 0.0, width_mm, height_mm, shape)
    return PcbFootprint(
        name=f"Pad_{width_mm:.2f}x{height_mm:.2f}mm",
        library="openforge_pads", ref="TP?",
        pads=[pad],
        courtyard=_rect_courtyard(width_mm, height_mm, 0.1),
        description=f"Custom {shape} pad {width_mm}x{height_mm}mm",
    )


def edge_pad(width_mm: float, height_mm: float,
             side: str = "bottom") -> PcbFootprint:
    """Board-edge pad (battery contact, card-edge connector finger)."""
    y = height_mm / 2 if side == "bottom" else -height_mm / 2
    pad = _smd_pad("1", 0.0, y, width_mm, height_mm, "rect")
    return PcbFootprint(
        name=f"EdgePad_{width_mm:.1f}x{height_mm:.1f}mm_{side}",
        library="openforge_pads", ref="EP?",
        pads=[pad],
        courtyard=_rect_courtyard(width_mm, height_mm * 2),
        description=f"Edge pad {side}",
    )


def test_point(diameter_mm: float = 1.0) -> PcbFootprint:
    d = max(1.0, diameter_mm)
    pad = _smd_pad("1", 0.0, 0.0, d, d, "round")
    return PcbFootprint(
        name=f"TestPoint_D{d:.1f}mm",
        library="openforge_tp", ref="TP?",
        pads=[pad],
        courtyard=_rect_courtyard(d + 0.5, d + 0.5),
        description="Test point",
    )


def fiducial_mark(diameter_mm: float = 1.0) -> PcbFootprint:
    d = diameter_mm
    mask = d * 2
    pad = PcbPad(
        name="1", x_mm=0.0, y_mm=0.0, shape="round",
        size_x_mm=d, size_y_mm=d, drill_mm=0.0,
        layers=["F.Cu", "F.Mask"],
    )
    # Mask clearance pad (represented as second mask-only pad)
    return PcbFootprint(
        name=f"Fiducial_D{d:.1f}mm",
        library="openforge_fid", ref="FID?",
        pads=[pad],
        courtyard=_rect_courtyard(mask + 0.4, mask + 0.4),
        description="Fiducial mark",
    )


def mounting_hole(drill_mm: float, pad_diameter_mm: float = 0.0,
                  plated: bool = False) -> PcbFootprint:
    pad_d = pad_diameter_mm if pad_diameter_mm > 0 else drill_mm + 1.0
    if plated:
        pad = _tht_pad("1", 0.0, 0.0, pad_d, drill_mm, "round")
    else:
        pad = PcbPad(
            name="", x_mm=0.0, y_mm=0.0, shape="round",
            size_x_mm=pad_d, size_y_mm=pad_d, drill_mm=drill_mm,
            layers=["Edge.Cuts"],
        )
    return PcbFootprint(
        name=f"MountingHole_{drill_mm:.1f}mm"
             + ("_Pad" if plated else "_NPTH"),
        library="openforge_mech", ref="H?",
        pads=[pad],
        courtyard=_rect_courtyard(pad_d + 0.5, pad_d + 0.5),
        description=f"Mounting hole drill={drill_mm}mm "
                    f"{'plated' if plated else 'NPTH'}",
    )


def castellated_edge(pin_count: int,
                     pitch_mm: float = 2.54) -> PcbFootprint:
    """Castellated half-holes (ESP-01 / module style)."""
    pads: list[PcbPad] = []
    pad_w = pitch_mm * 0.6
    pad_h = pitch_mm * 1.2
    x0 = -(pin_count - 1) * pitch_mm / 2
    for i in range(pin_count):
        pads.append(_smd_pad(str(i + 1), x0 + i * pitch_mm, 0.0,
                             pad_w, pad_h))
    body_w = pin_count * pitch_mm
    return PcbFootprint(
        name=f"Castellated_{pin_count}P_P{pitch_mm:.2f}mm",
        library="openforge_modules", ref="J?",
        pads=pads,
        courtyard=_rect_courtyard(body_w + 0.4, pad_h + 0.4),
        silkscreen=_rect_silk(body_w, pad_h),
        description=f"{pin_count}-pin castellated edge",
    )


# ---------------------------------------------------------------------------
# ICs
# ---------------------------------------------------------------------------


def qfn_parametric(pins: int, pitch_mm: float,
                   body_mm: float,
                   pad_length_mm: float) -> PcbFootprint:
    """Parametric QFN package. Pin 1 is bottom-left, CCW numbering."""
    assert pins % 4 == 0, "QFN pin count must be multiple of 4"
    per_side = pins // 4
    pads: list[PcbPad] = []
    pad_w = pad_length_mm
    pad_h = pitch_mm * 0.6
    # Half body + half pad center offset
    edge = body_mm / 2 - pad_w / 2 + 0.1
    start = -(per_side - 1) * pitch_mm / 2
    n = 1
    # Left side (vertical pads, sx=pad_w horizontal, sy=pad_h vertical)
    for i in range(per_side):
        pads.append(_smd_pad(str(n), -edge, start + i * pitch_mm,
                             pad_w, pad_h))
        n += 1
    # Bottom: pads horizontal
    for i in range(per_side):
        pads.append(_smd_pad(str(n), start + i * pitch_mm, edge,
                             pad_h, pad_w))
        n += 1
    # Right
    for i in range(per_side):
        pads.append(_smd_pad(str(n), edge,
                             start + (per_side - 1 - i) * pitch_mm,
                             pad_w, pad_h))
        n += 1
    # Top
    for i in range(per_side):
        pads.append(_smd_pad(str(n),
                             start + (per_side - 1 - i) * pitch_mm, -edge,
                             pad_h, pad_w))
        n += 1
    # Exposed thermal pad (center)
    tp_size = body_mm - 2 * pad_length_mm - 0.4
    if tp_size > 0.5:
        pads.append(PcbPad(
            name=str(pins + 1), x_mm=0.0, y_mm=0.0, shape="rect",
            size_x_mm=tp_size, size_y_mm=tp_size, drill_mm=0.0,
            layers=["F.Cu", "F.Mask", "F.Paste"],
        ))
    cy = body_mm + pad_length_mm + 0.5
    return PcbFootprint(
        name=f"QFN-{pins}_{body_mm:.1f}x{body_mm:.1f}mm_P{pitch_mm:.2f}mm",
        library="openforge_ic", ref="U?",
        pads=pads,
        courtyard=_rect_courtyard(cy, cy),
        silkscreen=_rect_silk(body_mm, body_mm),
        description=f"QFN{pins} {body_mm}mm, pitch {pitch_mm}mm",
    )


def bga_parametric(rows: int, cols: int, pitch_mm: float,
                   ball_dia_mm: float) -> PcbFootprint:
    """BGA with row letter / col number naming (A1, A2, ... etc)."""
    pads: list[PcbPad] = []
    x0 = -(cols - 1) * pitch_mm / 2
    y0 = -(rows - 1) * pitch_mm / 2
    pad_dia = ball_dia_mm * 0.8  # SMD pad, solder-mask defined ~ 80% of ball
    letters = "ABCDEFGHJKLMNPRTUVWY"  # IPC skipping I, O, Q, S, X, Z
    for r in range(rows):
        for c in range(cols):
            name = f"{letters[r % len(letters)]}{c + 1}"
            pads.append(PcbPad(
                name=name,
                x_mm=x0 + c * pitch_mm,
                y_mm=y0 + r * pitch_mm,
                shape="round",
                size_x_mm=pad_dia, size_y_mm=pad_dia, drill_mm=0.0,
                layers=["F.Cu", "F.Mask", "F.Paste"],
            ))
    body_w = cols * pitch_mm + pad_dia
    body_h = rows * pitch_mm + pad_dia
    return PcbFootprint(
        name=f"BGA-{rows * cols}_{rows}x{cols}_P{pitch_mm:.2f}mm",
        library="openforge_ic", ref="U?",
        pads=pads,
        courtyard=_rect_courtyard(body_w + 0.4, body_h + 0.4),
        silkscreen=_rect_silk(body_w, body_h),
        description=f"BGA {rows}x{cols}, pitch {pitch_mm}mm",
    )


def sot23_parametric(pins: int = 3) -> PcbFootprint:
    """SOT-23 / SOT-23-5 / SOT-23-6 family, IPC-7351B nominal."""
    assert pins in (3, 5, 6), "sot23_parametric supports 3/5/6 pin variants"
    pitch = 0.95
    span = 2.8
    pad_w = 1.0
    pad_h = 0.6
    pads: list[PcbPad] = []
    if pins == 3:
        pads.append(_smd_pad("1", -span / 2, -pitch, pad_w, pad_h))
        pads.append(_smd_pad("2", -span / 2, pitch, pad_w, pad_h))
        pads.append(_smd_pad("3", span / 2, 0.0, pad_w, pad_h))
    else:
        pins // 2 + pins % 2
        # 5 pin: 3 on left, 2 on right ; 6 pin: 3/3
        left = 3 if pins == 5 else 3
        right = pins - left
        start = -(left - 1) * pitch / 2
        for i in range(left):
            pads.append(_smd_pad(str(i + 1), -span / 2, start + i * pitch,
                                 pad_w, pad_h))
        start = -(right - 1) * pitch / 2
        for i in range(right):
            pads.append(_smd_pad(str(pins - i), span / 2, start + i * pitch,
                                 pad_w, pad_h))
    return PcbFootprint(
        name=f"SOT-23-{pins}",
        library="openforge_ic", ref="U?",
        pads=pads,
        courtyard=_rect_courtyard(span + pad_w + 0.4,
                                  (max(left, right, 3) - 1) * pitch
                                  + pad_h + 0.4
                                  if pins > 3 else pitch * 2 + pad_h + 0.4),
        silkscreen=_rect_silk(1.6, 2.9),
        description=f"SOT-23-{pins}",
    )
