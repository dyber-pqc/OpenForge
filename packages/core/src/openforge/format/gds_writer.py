"""Real GDSII binary writer - produces files compatible with Magic, KLayout, Cadence Virtuoso.

GDSII (Graphic Database System II) is the de-facto interchange format for IC layout.
This module produces fully spec-compliant binary GDSII Stream Format files that can
be opened in any modern EDA tool: KLayout, Magic, Cadence Virtuoso, Mentor Calibre,
Synopsys IC Compiler, etc.

Format reference
================

A GDSII file is a sequence of records.  Each record begins with a 4-byte header:

    +--------+--------+--------+--------+
    |    length (u16)|  rtype |  dtype |
    +--------+--------+--------+--------+

`length` is the total number of bytes in the record (header + data) as a big-endian
unsigned 16-bit integer.  `rtype` (record type) and `dtype` (data type) are each one
unsigned byte.  The header is followed by `length - 4` bytes of payload encoded
according to `dtype`.

Coordinates are stored as 4-byte big-endian signed integers in **database units**
(typically nanometres for modern PDKs).  The UNITS record at the start of the file
defines the conversion from database units to user units (typically microns) and
from database units to metres.

Record hierarchy:

    HEADER
    BGNLIB
      LIBNAME
      UNITS
      [BGNSTR
        STRNAME
        [BOUNDARY|PATH|TEXT|SREF|AREF ...]
        ENDSTR]*
    ENDLIB

This module implements all the records needed to produce a complete library
containing polygons, paths, text labels, and cell references / arrays.

Example
=======

    >>> from pathlib import Path
    >>> lib = GdsLibrary(name="MYLIB")
    >>> cell = GdsStructure(name="TOP")
    >>> cell.boundaries.append(
    ...     GdsBoundary(layer=66, datatype=20,
    ...                 points=[(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    ... )
    >>> lib.structures.append(cell)
    >>> write_gds(lib, Path("out.gds"))
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

if TYPE_CHECKING:
    from collections.abc import Iterable

# ============================================================================
# RECORD TYPES (from the GDSII Stream Format specification)
# ============================================================================

HEADER = 0x00
BGNLIB = 0x01
LIBNAME = 0x02
UNITS = 0x03
ENDLIB = 0x04
BGNSTR = 0x05
STRNAME = 0x06
ENDSTR = 0x07
BOUNDARY = 0x08
PATH = 0x09
SREF = 0x0A
AREF = 0x0B
TEXT = 0x0C
LAYER = 0x0D
DATATYPE = 0x0E
WIDTH = 0x0F
XY = 0x10
ENDEL = 0x11
SNAME = 0x12
COLROW = 0x13
TEXTNODE = 0x14
NODE = 0x15
TEXTTYPE = 0x16
PRESENTATION = 0x17
STRING = 0x19
STRANS = 0x1A
MAG = 0x1B
ANGLE = 0x1C
REFLIBS = 0x1F
FONTS = 0x20
PATHTYPE = 0x21
GENERATIONS = 0x22
ATTRTABLE = 0x23
ELFLAGS = 0x26
NODETYPE = 0x2A
PROPATTR = 0x2B
PROPVALUE = 0x2C
BOX = 0x2D
BOXTYPE = 0x2E
PLEX = 0x2F

# ============================================================================
# DATA TYPES
# ============================================================================

NO_DATA = 0x00
BIT_ARRAY = 0x01
TWO_BYTE_INT = 0x02
FOUR_BYTE_INT = 0x03
FOUR_BYTE_REAL = 0x04
EIGHT_BYTE_REAL = 0x05
ASCII_STRING = 0x06


# ============================================================================
# SKY130 PDK LAYER MAP (commonly needed by the desktop transistor editor)
# ============================================================================
#
# These are the canonical SKY130 GDS (layer, datatype) numbers as published
# in the SkyWater Open Source PDK.  Used by callers that want a quick mapping
# from a friendly layer name to the right GDS pair without having to load the
# full PDK technology file.

SKY130_LAYERS: dict[str, tuple[int, int]] = {
    "nwell": (64, 20),
    "pwell": (64, 44),
    "dnwell": (64, 18),
    "diff": (65, 20),
    "ndiff": (65, 20),
    "pdiff": (65, 20),
    "tap": (65, 44),
    "psdm": (94, 20),
    "nsdm": (93, 44),
    "poly": (66, 20),
    "polysilicon": (66, 20),
    "licon": (66, 44),
    "li1": (67, 20),
    "mcon": (67, 44),
    "met1": (68, 20),
    "metal1": (68, 20),
    "via1": (68, 44),
    "via": (68, 44),
    "met2": (69, 20),
    "metal2": (69, 20),
    "via2": (69, 44),
    "met3": (70, 20),
    "metal3": (70, 20),
    "via3": (70, 44),
    "met4": (71, 20),
    "metal4": (71, 20),
    "via4": (71, 44),
    "met5": (72, 20),
    "metal5": (72, 20),
    "pad": (76, 20),
    "text": (83, 44),
    "boundary": (235, 4),
    "prboundary": (235, 4),
    "contact": (66, 44),
}


def sky130_layer(name: str, default: tuple[int, int] = (1, 0)) -> tuple[int, int]:
    """Look up a SKY130 (layer, datatype) pair by friendly name.

    Unknown names fall back to the supplied default rather than raising,
    so generic editors can map their layers without crashing on custom names.
    """
    return SKY130_LAYERS.get(name.lower(), default)


# ============================================================================
# DATA MODEL
# ============================================================================


@dataclass
class GdsBoundary:
    """A polygon (filled region) on a (layer, datatype)."""

    layer: int
    datatype: int
    points: list[tuple[int, int]]  # in database units (typically nm)


@dataclass
class GdsPath:
    """A wire / path on a (layer, datatype)."""

    layer: int
    datatype: int
    width: int  # in database units
    pathtype: int = 0  # 0=square ends, 1=round, 2=square+half-width extension
    points: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class GdsText:
    """A text label."""

    layer: int
    texttype: int
    string: str
    x: int
    y: int
    height: int = 1000  # in db units (used to compute MAG relative to nominal 1um)
    rotation: float = 0.0
    mag: float = 1.0


@dataclass
class GdsSref:
    """An instance reference (SREF) to another structure."""

    sname: str
    x: int
    y: int
    rotation: float = 0.0
    mag: float = 1.0
    reflect: bool = False


@dataclass
class GdsAref:
    """An array reference (AREF) - regular grid of cell instances."""

    sname: str
    x: int  # origin x in db units
    y: int  # origin y in db units
    cols: int
    rows: int
    col_spacing: int
    row_spacing: int
    rotation: float = 0.0
    mag: float = 1.0
    reflect: bool = False


@dataclass
class GdsBox:
    """A BOX element (rectangular box stored as 5-vertex closed polygon)."""

    layer: int
    boxtype: int
    points: list[tuple[int, int]]


@dataclass
class GdsStructure:
    """A cell / structure containing geometry and instances."""

    name: str
    boundaries: list[GdsBoundary] = field(default_factory=list)
    paths: list[GdsPath] = field(default_factory=list)
    texts: list[GdsText] = field(default_factory=list)
    srefs: list[GdsSref] = field(default_factory=list)
    arefs: list[GdsAref] = field(default_factory=list)
    boxes: list[GdsBox] = field(default_factory=list)

    def add_rectangle(
        self,
        layer: int,
        datatype: int,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
    ) -> GdsBoundary:
        """Convenience: add an axis-aligned rectangle as a boundary."""
        b = GdsBoundary(
            layer=layer,
            datatype=datatype,
            points=[(x1, y1), (x2, y1), (x2, y2), (x1, y2)],
        )
        self.boundaries.append(b)
        return b


@dataclass
class GdsLibrary:
    """A complete GDSII library file."""

    name: str = "LIB"
    version: int = 600  # GDSII version 6
    user_units: float = 1e-6  # 1 micron
    db_units: float = 1e-9  # 1 nanometre
    structures: list[GdsStructure] = field(default_factory=list)


# ============================================================================
# LOW-LEVEL BINARY ENCODERS
# ============================================================================


def _write_record(
    f: BinaryIO,
    record_type: int,
    data_type: int,
    data: bytes = b"",
) -> None:
    """Write a single GDSII record header followed by its payload.

    The total record length (header + payload) must fit in a u16.  GDSII does
    have a long-record extension but in practice nothing uses it; we raise
    instead so callers see the violation immediately.
    """
    length = len(data) + 4
    if length > 0xFFFF:
        raise ValueError(f"GDS record too long: {length} bytes (record type 0x{record_type:02X})")
    if length % 2 != 0:
        raise ValueError(f"GDS records must have even length, got {length} bytes")
    f.write(struct.pack(">HBB", length, record_type, data_type))
    if data:
        f.write(data)


def _pack_string(s: str) -> bytes:
    """Encode an ASCII string padded to even length with NUL bytes."""
    b = s.encode("ascii", errors="replace")
    if len(b) % 2 != 0:
        b += b"\x00"
    return b


def _pack_int16(values: Iterable[int]) -> bytes:
    """Pack a sequence of 16-bit signed big-endian integers."""
    vals = list(values)
    return struct.pack(f">{len(vals)}h", *vals)


def _pack_int32(values: Iterable[int]) -> bytes:
    """Pack a sequence of 32-bit signed big-endian integers."""
    vals = list(values)
    return struct.pack(f">{len(vals)}i", *vals)


def _pack_real8(value: float) -> bytes:
    """Encode a Python float as a GDSII 8-byte real (excess-64 hex float).

    GDSII uses an unusual floating point format inherited from IBM mainframes:
    1 sign bit, 7-bit excess-64 hex exponent, 56-bit fraction with the radix
    point at the *left* of the fraction.  The value represented is

        (-1)^sign * fraction * 16^(exponent - 64)

    where ``fraction`` is treated as a 56-bit unsigned integer divided by 2^56.
    """
    if value == 0.0:
        return b"\x00" * 8

    sign_bit = 0
    if value < 0:
        sign_bit = 1
        value = -value

    # Find hex exponent so that 1/16 <= mantissa < 1
    exponent = int(math.floor(math.log(value) / math.log(16))) + 1
    mantissa_f = value / (16.0**exponent)

    # Normalise mantissa into [1/16, 1)
    while mantissa_f >= 1.0:
        mantissa_f /= 16.0
        exponent += 1
    while mantissa_f < 1.0 / 16.0 and mantissa_f > 0:
        mantissa_f *= 16.0
        exponent -= 1

    biased_exp = exponent + 64
    if biased_exp < 0 or biased_exp > 127:
        raise ValueError(f"GDS real out of range: {value}")

    mantissa_int = int(mantissa_f * (1 << 56))
    if mantissa_int >= (1 << 56):
        mantissa_int = (1 << 56) - 1

    first_byte = (sign_bit << 7) | biased_exp
    out = bytearray(8)
    out[0] = first_byte
    for i in range(7):
        out[1 + i] = (mantissa_int >> ((6 - i) * 8)) & 0xFF
    return bytes(out)


def _pack_xy(points: Iterable[tuple[int, int]]) -> bytes:
    """Pack a list of (x, y) coordinate pairs as a flat int32 array."""
    flat: list[int] = []
    for x, y in points:
        flat.append(int(x))
        flat.append(int(y))
    return _pack_int32(flat)


def _now_timestamp() -> list[int]:
    """Return a 12-element [last-mod, last-access] timestamp pair."""
    now = datetime.now()
    pair = [now.year, now.month, now.day, now.hour, now.minute, now.second]
    return pair + pair


# ============================================================================
# HIGH-LEVEL WRITER
# ============================================================================


def write_gds(library: GdsLibrary, output_path: Path | str) -> Path:
    """Write a complete GDSII binary file.

    Args:
        library: The :class:`GdsLibrary` to serialise.
        output_path: Filesystem path for the output ``.gds`` file.  Parent
            directories are created if they do not exist.

    Returns:
        The fully-resolved :class:`Path` of the written file.

    Raises:
        ValueError: If the library contains data that cannot be encoded
            (record too long, real value out of range, etc.).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if library.db_units <= 0 or library.user_units <= 0:
        raise ValueError("GDS library units must be positive")

    with open(output_path, "wb") as f:
        # ----- HEADER -----
        _write_record(f, HEADER, TWO_BYTE_INT, _pack_int16([library.version]))

        # ----- BGNLIB (mod + access timestamps) -----
        _write_record(f, BGNLIB, TWO_BYTE_INT, _pack_int16(_now_timestamp()))

        # ----- LIBNAME -----
        _write_record(f, LIBNAME, ASCII_STRING, _pack_string(library.name))

        # ----- UNITS -----
        # First real:  user units expressed in db units (e.g. 1e-3 = 1 nm per um)
        # Second real: db unit size in metres
        units_payload = _pack_real8(library.db_units / library.user_units) + _pack_real8(
            library.db_units
        )
        _write_record(f, UNITS, EIGHT_BYTE_REAL, units_payload)

        # ----- Structures -----
        for struct_obj in library.structures:
            _write_structure(f, struct_obj)

        # ----- ENDLIB -----
        _write_record(f, ENDLIB, NO_DATA)

    return output_path


def _write_structure(f: BinaryIO, structure: GdsStructure) -> None:
    """Serialise a single :class:`GdsStructure` to ``f``."""
    _write_record(f, BGNSTR, TWO_BYTE_INT, _pack_int16(_now_timestamp()))
    _write_record(f, STRNAME, ASCII_STRING, _pack_string(structure.name))

    for boundary in structure.boundaries:
        _write_boundary(f, boundary)
    for path in structure.paths:
        _write_path(f, path)
    for box in structure.boxes:
        _write_box(f, box)
    for text in structure.texts:
        _write_text(f, text)
    for sref in structure.srefs:
        _write_sref(f, sref)
    for aref in structure.arefs:
        _write_aref(f, aref)

    _write_record(f, ENDSTR, NO_DATA)


def _write_boundary(f: BinaryIO, b: GdsBoundary) -> None:
    """Serialise a BOUNDARY (polygon) element."""
    if len(b.points) < 3:
        return  # need at least 3 distinct vertices

    _write_record(f, BOUNDARY, NO_DATA)
    _write_record(f, LAYER, TWO_BYTE_INT, _pack_int16([b.layer]))
    _write_record(f, DATATYPE, TWO_BYTE_INT, _pack_int16([b.datatype]))

    # GDSII boundaries must be explicitly closed.
    points = [(int(x), int(y)) for x, y in b.points]
    if points[0] != points[-1]:
        points.append(points[0])

    _write_record(f, XY, FOUR_BYTE_INT, _pack_xy(points))
    _write_record(f, ENDEL, NO_DATA)


def _write_path(f: BinaryIO, p: GdsPath) -> None:
    """Serialise a PATH element."""
    if len(p.points) < 2:
        return

    _write_record(f, PATH, NO_DATA)
    _write_record(f, LAYER, TWO_BYTE_INT, _pack_int16([p.layer]))
    _write_record(f, DATATYPE, TWO_BYTE_INT, _pack_int16([p.datatype]))
    _write_record(f, PATHTYPE, TWO_BYTE_INT, _pack_int16([p.pathtype]))
    _write_record(f, WIDTH, FOUR_BYTE_INT, _pack_int32([int(p.width)]))
    _write_record(f, XY, FOUR_BYTE_INT, _pack_xy(p.points))
    _write_record(f, ENDEL, NO_DATA)


def _write_box(f: BinaryIO, b: GdsBox) -> None:
    """Serialise a BOX element."""
    if len(b.points) != 5:
        return
    _write_record(f, BOX, NO_DATA)
    _write_record(f, LAYER, TWO_BYTE_INT, _pack_int16([b.layer]))
    _write_record(f, BOXTYPE, TWO_BYTE_INT, _pack_int16([b.boxtype]))
    _write_record(f, XY, FOUR_BYTE_INT, _pack_xy(b.points))
    _write_record(f, ENDEL, NO_DATA)


def _write_text(f: BinaryIO, t: GdsText) -> None:
    """Serialise a TEXT element."""
    _write_record(f, TEXT, NO_DATA)
    _write_record(f, LAYER, TWO_BYTE_INT, _pack_int16([t.layer]))
    _write_record(f, TEXTTYPE, TWO_BYTE_INT, _pack_int16([t.texttype]))
    # PRESENTATION: bit array describing font, justification.  Default 0.
    _write_record(f, PRESENTATION, BIT_ARRAY, b"\x00\x00")

    if t.rotation != 0 or t.mag != 1.0:
        _write_record(f, STRANS, BIT_ARRAY, b"\x00\x00")
        if t.mag != 1.0:
            _write_record(f, MAG, EIGHT_BYTE_REAL, _pack_real8(t.mag))
        if t.rotation != 0:
            _write_record(f, ANGLE, EIGHT_BYTE_REAL, _pack_real8(t.rotation))

    _write_record(f, XY, FOUR_BYTE_INT, _pack_xy([(t.x, t.y)]))
    _write_record(f, STRING, ASCII_STRING, _pack_string(t.string))
    _write_record(f, ENDEL, NO_DATA)


def _write_sref(f: BinaryIO, s: GdsSref) -> None:
    """Serialise a structure reference (SREF) instance."""
    _write_record(f, SREF, NO_DATA)
    _write_record(f, SNAME, ASCII_STRING, _pack_string(s.sname))

    if s.rotation != 0 or s.mag != 1.0 or s.reflect:
        flags = 0x8000 if s.reflect else 0x0000
        _write_record(f, STRANS, BIT_ARRAY, struct.pack(">H", flags))
        if s.mag != 1.0:
            _write_record(f, MAG, EIGHT_BYTE_REAL, _pack_real8(s.mag))
        if s.rotation != 0:
            _write_record(f, ANGLE, EIGHT_BYTE_REAL, _pack_real8(s.rotation))

    _write_record(f, XY, FOUR_BYTE_INT, _pack_xy([(s.x, s.y)]))
    _write_record(f, ENDEL, NO_DATA)


def _write_aref(f: BinaryIO, a: GdsAref) -> None:
    """Serialise an array reference (AREF) instance."""
    _write_record(f, AREF, NO_DATA)
    _write_record(f, SNAME, ASCII_STRING, _pack_string(a.sname))

    if a.rotation != 0 or a.mag != 1.0 or a.reflect:
        flags = 0x8000 if a.reflect else 0x0000
        _write_record(f, STRANS, BIT_ARRAY, struct.pack(">H", flags))
        if a.mag != 1.0:
            _write_record(f, MAG, EIGHT_BYTE_REAL, _pack_real8(a.mag))
        if a.rotation != 0:
            _write_record(f, ANGLE, EIGHT_BYTE_REAL, _pack_real8(a.rotation))

    _write_record(f, COLROW, TWO_BYTE_INT, _pack_int16([a.cols, a.rows]))

    # AREF requires three XY points: origin, the endpoint of the column vector
    # (totalling cols * col_spacing along it) and endpoint of the row vector.
    xy = [
        (a.x, a.y),
        (a.x + a.cols * a.col_spacing, a.y),
        (a.x, a.y + a.rows * a.row_spacing),
    ]
    _write_record(f, XY, FOUR_BYTE_INT, _pack_xy(xy))
    _write_record(f, ENDEL, NO_DATA)


# ============================================================================
# CONVENIENCE FACTORIES / VERIFICATION HELPERS
# ============================================================================


def create_test_library() -> GdsLibrary:
    """Create a tiny library with one cell containing a polygon, path, and text.

    Used by smoke tests to confirm the writer produces well-formed binary output.
    """
    lib = GdsLibrary(name="TESTLIB")
    cell = GdsStructure(name="TESTCELL")

    # 1 um square on poly (sky130 layer 66/20)
    cell.boundaries.append(
        GdsBoundary(
            layer=66,
            datatype=20,
            points=[(0, 0), (1000, 0), (1000, 1000), (0, 1000)],
        )
    )

    # 200 nm wide met1 wire across the cell
    cell.paths.append(
        GdsPath(
            layer=68,
            datatype=20,
            width=200,
            points=[(0, 500), (2000, 500)],
        )
    )

    # A label
    cell.texts.append(
        GdsText(
            layer=68,
            texttype=5,
            string="VDD",
            x=100,
            y=900,
            height=200,
        )
    )

    lib.structures.append(cell)
    return lib


def verify_gds_header(path: Path | str) -> bool:
    """Quickly verify that ``path`` starts with a valid GDSII HEADER record.

    Returns True iff the first record is a 6-byte HEADER (length=6, type=0,
    dtype=2 - two-byte int).  Useful as a smoke check after writing.
    """
    path = Path(path)
    with open(path, "rb") as f:
        header = f.read(4)
    if len(header) != 4:
        return False
    length = struct.unpack(">H", header[:2])[0]
    rtype = header[2]
    dtype = header[3]
    return length == 6 and rtype == HEADER and dtype == TWO_BYTE_INT


def library_from_rectangles(
    name: str,
    cell_name: str,
    rects: Iterable[tuple[int, int, int, int, int, int]],
) -> GdsLibrary:
    """Build a single-cell library from an iterable of rectangle tuples.

    Each rectangle is ``(layer, datatype, x1, y1, x2, y2)`` in db units.
    """
    lib = GdsLibrary(name=name)
    cell = GdsStructure(name=cell_name)
    for layer, datatype, x1, y1, x2, y2 in rects:
        cell.add_rectangle(layer, datatype, x1, y1, x2, y2)
    lib.structures.append(cell)
    return lib


__all__ = [
    # Records / data types (re-exported for advanced users)
    "HEADER",
    "BGNLIB",
    "LIBNAME",
    "UNITS",
    "ENDLIB",
    "BGNSTR",
    "STRNAME",
    "ENDSTR",
    "BOUNDARY",
    "PATH",
    "SREF",
    "AREF",
    "TEXT",
    "LAYER",
    "DATATYPE",
    "WIDTH",
    "XY",
    "ENDEL",
    "SNAME",
    "COLROW",
    "TEXTTYPE",
    "PRESENTATION",
    "STRING",
    "STRANS",
    "MAG",
    "ANGLE",
    "PATHTYPE",
    "NO_DATA",
    "BIT_ARRAY",
    "TWO_BYTE_INT",
    "FOUR_BYTE_INT",
    "FOUR_BYTE_REAL",
    "EIGHT_BYTE_REAL",
    "ASCII_STRING",
    # SKY130 helpers
    "SKY130_LAYERS",
    "sky130_layer",
    # Data model
    "GdsBoundary",
    "GdsPath",
    "GdsText",
    "GdsSref",
    "GdsAref",
    "GdsBox",
    "GdsStructure",
    "GdsLibrary",
    # API
    "write_gds",
    "create_test_library",
    "verify_gds_header",
    "library_from_rectangles",
]
