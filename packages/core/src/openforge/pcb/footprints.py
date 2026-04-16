"""Built-in PCB footprint library with real datasheet dimensions."""

from __future__ import annotations

from openforge.pcb.model import PcbFootprint, PcbPad


def _smd_pad(name: str, x: float, y: float, sx: float, sy: float, shape: str = "rect") -> PcbPad:
    return PcbPad(
        name=name,
        x_mm=x,
        y_mm=y,
        shape=shape,  # type: ignore[arg-type]
        size_x_mm=sx,
        size_y_mm=sy,
        drill_mm=0.0,
        layers=["F.Cu", "F.Mask", "F.Paste"],
    )


def _tht_pad(
    name: str, x: float, y: float, pad: float, drill: float, shape: str = "round"
) -> PcbPad:
    return PcbPad(
        name=name,
        x_mm=x,
        y_mm=y,
        shape=shape,  # type: ignore[arg-type]
        size_x_mm=pad,
        size_y_mm=pad,
        drill_mm=drill,
        layers=["F.Cu", "B.Cu", "F.Mask", "B.Mask"],
    )


def _chip_2pad(name: str, lib_w: float, pad_w: float, pad_h: float, desc: str) -> PcbFootprint:
    dx = lib_w / 2
    return PcbFootprint(
        name=name,
        library="openforge_smd",
        ref="R?",
        value="",
        pads=[
            _smd_pad("1", -dx, 0.0, pad_w, pad_h),
            _smd_pad("2", dx, 0.0, pad_w, pad_h),
        ],
        courtyard=[
            (-dx - pad_w / 2 - 0.25, -pad_h / 2 - 0.25),
            (dx + pad_w / 2 + 0.25, -pad_h / 2 - 0.25),
            (dx + pad_w / 2 + 0.25, pad_h / 2 + 0.25),
            (-dx - pad_w / 2 - 0.25, pad_h / 2 + 0.25),
            (-dx - pad_w / 2 - 0.25, -pad_h / 2 - 0.25),
        ],
        description=desc,
    )


def _soic_pads(n: int, pitch: float, span: float, pad_w: float, pad_h: float) -> list[PcbPad]:
    pads: list[PcbPad] = []
    per_side = n // 2
    y0 = -(per_side - 1) * pitch / 2
    x = span / 2
    for i in range(per_side):
        pads.append(_smd_pad(str(i + 1), -x, y0 + i * pitch, pad_w, pad_h))
    for i in range(per_side):
        pads.append(_smd_pad(str(n - i), x, y0 + i * pitch, pad_w, pad_h))
    return pads


def _soic(
    name: str,
    n: int,
    pitch: float,
    span: float,
    pad_w: float,
    pad_h: float,
    body_w: float,
    body_l: float,
    desc: str,
) -> PcbFootprint:
    cx = span / 2 + pad_w / 2 + 0.25
    cy = body_l / 2 + 0.25
    return PcbFootprint(
        name=name,
        library="openforge_smd",
        ref="U?",
        pads=_soic_pads(n, pitch, span, pad_w, pad_h),
        courtyard=[(-cx, -cy), (cx, -cy), (cx, cy), (-cx, cy), (-cx, -cy)],
        silkscreen=[
            (-body_w / 2, -body_l / 2, body_w / 2, -body_l / 2),
            (body_w / 2, -body_l / 2, body_w / 2, body_l / 2),
            (body_w / 2, body_l / 2, -body_w / 2, body_l / 2),
            (-body_w / 2, body_l / 2, -body_w / 2, -body_l / 2),
        ],
        description=desc,
    )


def _qfp_pads(n: int, pitch: float, span: float, pad_w: float, pad_h: float) -> list[PcbPad]:
    pads: list[PcbPad] = []
    per_side = n // 4
    start = -(per_side - 1) * pitch / 2
    # left side: pads 1..per_side (vertical pads)
    for i in range(per_side):
        pads.append(_smd_pad(str(i + 1), -span / 2, start + i * pitch, pad_h, pad_w))
    # bottom side
    for i in range(per_side):
        pads.append(_smd_pad(str(per_side + i + 1), start + i * pitch, span / 2, pad_w, pad_h))
    # right side (reverse y)
    for i in range(per_side):
        pads.append(
            _smd_pad(str(2 * per_side + i + 1), span / 2, -(start + i * pitch), pad_h, pad_w)
        )
    # top side (reverse x)
    for i in range(per_side):
        pads.append(
            _smd_pad(str(3 * per_side + i + 1), -(start + i * pitch), -span / 2, pad_w, pad_h)
        )
    return pads


def _qfp(
    name: str, n: int, pitch: float, span: float, pad_w: float, pad_h: float, body: float, desc: str
) -> PcbFootprint:
    cx = span / 2 + pad_h / 2 + 0.25
    return PcbFootprint(
        name=name,
        library="openforge_smd",
        ref="U?",
        pads=_qfp_pads(n, pitch, span, pad_w, pad_h),
        courtyard=[(-cx, -cx), (cx, -cx), (cx, cx), (-cx, cx), (-cx, -cx)],
        silkscreen=[
            (-body / 2, -body / 2, body / 2, -body / 2),
            (body / 2, -body / 2, body / 2, body / 2),
            (body / 2, body / 2, -body / 2, body / 2),
            (-body / 2, body / 2, -body / 2, -body / 2),
        ],
        description=desc,
    )


def _bga(name: str, grid: int, pitch: float, pad_d: float, body: float, desc: str) -> PcbFootprint:
    pads: list[PcbPad] = []
    start = -(grid - 1) * pitch / 2
    idx = 1
    for row in range(grid):
        for col in range(grid):
            pads.append(
                PcbPad(
                    name=str(idx),
                    x_mm=start + col * pitch,
                    y_mm=start + row * pitch,
                    shape="round",
                    size_x_mm=pad_d,
                    size_y_mm=pad_d,
                    drill_mm=0.0,
                    layers=["F.Cu", "F.Mask"],
                )
            )
            idx += 1
    c = body / 2 + 0.25
    return PcbFootprint(
        name=name,
        library="openforge_bga",
        ref="U?",
        pads=pads,
        courtyard=[(-c, -c), (c, -c), (c, c), (-c, c), (-c, -c)],
        description=desc,
    )


def _header(name: str, rows: int, cols: int, pitch: float = 2.54) -> PcbFootprint:
    pads: list[PcbPad] = []
    idx = 1
    x0 = -(cols - 1) * pitch / 2
    y0 = -(rows - 1) * pitch / 2
    for c in range(cols):
        for r in range(rows):
            # pin 1 is rect for orientation
            shape = "rect" if idx == 1 else "round"
            pads.append(
                PcbPad(
                    name=str(idx),
                    x_mm=x0 + c * pitch,
                    y_mm=y0 + r * pitch,
                    shape=shape,  # type: ignore[arg-type]
                    size_x_mm=1.7,
                    size_y_mm=1.7,
                    drill_mm=1.0,
                    layers=["F.Cu", "B.Cu", "F.Mask", "B.Mask"],
                )
            )
            idx += 1
    w = cols * pitch
    h = rows * pitch
    return PcbFootprint(
        name=name,
        library="openforge_conn",
        ref="J?",
        pads=pads,
        courtyard=[
            (-w / 2 - 0.25, -h / 2 - 0.25),
            (w / 2 + 0.25, -h / 2 - 0.25),
            (w / 2 + 0.25, h / 2 + 0.25),
            (-w / 2 - 0.25, h / 2 + 0.25),
            (-w / 2 - 0.25, -h / 2 - 0.25),
        ],
        description=f"{rows}x{cols} pin header {pitch}mm",
    )


FOOTPRINTS: dict[str, PcbFootprint] = {
    # Resistors (IPC-7351 nominal)
    "R_0402": _chip_2pad("R_0402", 0.90, 0.55, 0.60, "Resistor 0402 (1005 metric)"),
    "R_0603": _chip_2pad("R_0603", 1.55, 0.80, 0.95, "Resistor 0603 (1608 metric)"),
    "R_0805": _chip_2pad("R_0805", 1.95, 1.00, 1.30, "Resistor 0805 (2012 metric)"),
    "R_1206": _chip_2pad("R_1206", 3.10, 1.15, 1.80, "Resistor 1206 (3216 metric)"),
    "R_2010": _chip_2pad("R_2010", 4.80, 1.40, 2.70, "Resistor 2010 (5025 metric)"),
    "R_2512": _chip_2pad("R_2512", 5.80, 1.50, 3.40, "Resistor 2512 (6332 metric)"),
    # Capacitors
    "C_0402": _chip_2pad("C_0402", 0.90, 0.55, 0.60, "Capacitor 0402"),
    "C_0603": _chip_2pad("C_0603", 1.55, 0.80, 0.95, "Capacitor 0603"),
    "C_0805": _chip_2pad("C_0805", 1.95, 1.00, 1.30, "Capacitor 0805"),
    "C_1206": _chip_2pad("C_1206", 3.10, 1.15, 1.80, "Capacitor 1206"),
    "C_1210": _chip_2pad("C_1210", 3.10, 1.15, 2.70, "Capacitor 1210"),
    # SOIC (1.27mm pitch)
    "SOIC-8": _soic("SOIC-8", 8, 1.27, 5.20, 1.55, 0.60, 3.90, 4.90, "SOIC-8 150mil"),
    "SOIC-14": _soic("SOIC-14", 14, 1.27, 5.20, 1.55, 0.60, 3.90, 8.65, "SOIC-14 150mil"),
    "SOIC-16": _soic("SOIC-16", 16, 1.27, 5.20, 1.55, 0.60, 3.90, 9.90, "SOIC-16 150mil"),
    # TSSOP (0.65mm pitch)
    "TSSOP-8": _soic("TSSOP-8", 8, 0.65, 5.20, 1.50, 0.45, 3.00, 3.00, "TSSOP-8"),
    "TSSOP-14": _soic("TSSOP-14", 14, 0.65, 5.20, 1.50, 0.45, 4.40, 5.00, "TSSOP-14"),
    "TSSOP-20": _soic("TSSOP-20", 20, 0.65, 5.20, 1.50, 0.45, 4.40, 6.50, "TSSOP-20"),
    # QFN (no-lead, treat as flat SOIC-style; using _qfp is fine)
    "QFN-16": _qfp("QFN-16", 16, 0.65, 2.90, 0.80, 0.35, 3.00, "QFN-16 3x3 0.5mm"),
    "QFN-32": _qfp("QFN-32", 32, 0.50, 4.90, 0.80, 0.30, 5.00, "QFN-32 5x5 0.5mm"),
    "QFN-48": _qfp("QFN-48", 48, 0.50, 6.90, 0.80, 0.30, 7.00, "QFN-48 7x7 0.5mm"),
    "QFN-64": _qfp("QFN-64", 64, 0.50, 8.90, 0.80, 0.30, 9.00, "QFN-64 9x9 0.5mm"),
    # LQFP
    "LQFP-32": _qfp("LQFP-32", 32, 0.80, 8.40, 1.50, 0.50, 7.00, "LQFP-32 7x7 0.8mm"),
    "LQFP-48": _qfp("LQFP-48", 48, 0.50, 8.40, 1.50, 0.30, 7.00, "LQFP-48 7x7 0.5mm"),
    "LQFP-64": _qfp("LQFP-64", 64, 0.50, 11.40, 1.50, 0.30, 10.00, "LQFP-64 10x10 0.5mm"),
    "LQFP-100": _qfp("LQFP-100", 100, 0.50, 15.40, 1.50, 0.30, 14.00, "LQFP-100 14x14 0.5mm"),
    # BGA
    "BGA-256": _bga("BGA-256", 16, 1.00, 0.45, 17.0, "BGA-256 1.0mm pitch 16x16"),
    "BGA-484": _bga("BGA-484", 22, 1.00, 0.45, 23.0, "BGA-484 1.0mm pitch 22x22"),
    # USB
    "USB-C_Recep": PcbFootprint(
        name="USB-C_Recep",
        library="openforge_conn",
        ref="J?",
        pads=[_smd_pad(str(i + 1), -3.25 + i * 0.5, -3.0, 0.30, 1.20) for i in range(12)]
        + [
            _tht_pad("S1", -4.32, 0.0, 1.8, 1.0, "oval"),
            _tht_pad("S2", 4.32, 0.0, 1.8, 1.0, "oval"),
        ],
        description="USB Type-C Receptacle SMT",
    ),
    "USB_Micro-B": PcbFootprint(
        name="USB_Micro-B",
        library="openforge_conn",
        ref="J?",
        pads=[_smd_pad(str(i + 1), -1.3 + i * 0.65, -2.25, 0.40, 1.35) for i in range(5)]
        + [
            _tht_pad("S1", -3.50, 0.0, 1.8, 1.0),
            _tht_pad("S2", 3.50, 0.0, 1.8, 1.0),
        ],
        description="USB Micro-B Receptacle",
    ),
    "SMA_Edge": PcbFootprint(
        name="SMA_Edge",
        library="openforge_rf",
        ref="J?",
        pads=[
            _smd_pad("1", 0.0, 0.0, 1.6, 2.0),
            _smd_pad("2", -3.05, 0.0, 1.4, 2.0),
            _smd_pad("3", 3.05, 0.0, 1.4, 2.0),
        ],
        description="SMA edge-launch connector",
    ),
    "SMA_Vertical": PcbFootprint(
        name="SMA_Vertical",
        library="openforge_rf",
        ref="J?",
        pads=[
            _tht_pad("1", 0.0, 0.0, 1.6, 1.2),
            _tht_pad("2", -3.05, 3.05, 1.6, 1.6),
            _tht_pad("3", 3.05, 3.05, 1.6, 1.6),
            _tht_pad("4", -3.05, -3.05, 1.6, 1.6),
            _tht_pad("5", 3.05, -3.05, 1.6, 1.6),
        ],
        description="SMA vertical PCB connector",
    ),
    # Pin headers 2.54mm
    "PinHeader_1x4": _header("PinHeader_1x4", 1, 4),
    "PinHeader_1x6": _header("PinHeader_1x6", 1, 6),
    "PinHeader_1x8": _header("PinHeader_1x8", 1, 8),
    "PinHeader_2x5": _header("PinHeader_2x5", 2, 5),
    "PinHeader_2x10": _header("PinHeader_2x10", 2, 10),
}


def get_footprint(name: str) -> PcbFootprint:
    fp = FOOTPRINTS.get(name)
    if fp is None:
        raise KeyError(f"Footprint {name!r} not found")
    return fp.model_copy(deep=True)


def list_footprints() -> list[str]:
    return sorted(FOOTPRINTS.keys())
