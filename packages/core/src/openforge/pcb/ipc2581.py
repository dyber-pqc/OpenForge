"""IPC-2581 Rev B exporter for OpenForge PCB boards.

IPC-2581 is the open data-exchange standard for PCB design handoff.
A single XML file contains the full board description: stackup, layers,
features (pads, lines, polygons), component placements, nets, BOM, and
DRC rules. Fab houses like JLCPCB, PCBWay, and Sierra Circuits accept
IPC-2581 directly.

This exporter produces a minimal but schema-valid Rev B document.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree as ET

if TYPE_CHECKING:  # pragma: no cover
    from openforge.pcb.model import PcbBoard


IPC_NAMESPACE = "http://webstds.ipc.org/2581"
IPC_SCHEMA = "http://webstds.ipc.org/2581 http://webstds.ipc.org/2581/IPC-2581B.xsd"


class Ipc2581Exporter:
    """IPC-2581 Rev B XML exporter.

    Ships the full board (layers, features, components, nets, BOM,
    DRC rules) in a single self-contained XML file that IPC-2581-
    compliant fab and assembly houses can parse directly.
    """

    def __init__(self, board: PcbBoard) -> None:
        self.board = board
        self._uid_counter = 0

    # ------------------------------------------------------------------
    def _generate_uuid(self) -> str:
        self._uid_counter += 1
        return f"UID{self._uid_counter:05d}"

    def _format_real(self, value: float, decimals: int = 4) -> str:
        if value is None:
            return "0"
        return f"{float(value):.{decimals}f}"

    # ------------------------------------------------------------------
    def export(self, output_path: Path, revision: str = "B") -> Path:
        """Generate an IPC-2581 Rev B XML file and write it to disk.

        Returns the written path.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        root = ET.Element(
            "IPC-2581",
            {
                "xmlns": IPC_NAMESPACE,
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "xsi:schemaLocation": IPC_SCHEMA,
                "revision": revision,
            },
        )

        self._build_content(root)
        self._build_logical_header(root)
        self._build_history_record(root)
        self._build_bom_header(root)
        self._build_bom(root)
        self._build_ecad(root)

        # Pretty format
        try:
            ET.indent(root, space="  ")
        except AttributeError:  # pragma: no cover (py<3.9)
            pass
        xml_bytes = ET.tostring(
            root, encoding="utf-8", xml_declaration=True, short_empty_elements=False
        )
        output_path.write_bytes(xml_bytes)
        return output_path

    # ------------------------------------------------------------------
    # Top-level sections
    # ------------------------------------------------------------------
    def _build_content(self, parent: ET.Element) -> None:
        content = ET.SubElement(
            parent,
            "Content",
            {
                "roleRef": "Owner",
                "stepRef": self.board.name or "board_1",
            },
        )
        ET.SubElement(
            content,
            "FunctionMode",
            {"mode": "DESIGN"},
        )
        ET.SubElement(
            content,
            "StepRef",
            {"name": self.board.name or "board_1"},
        )
        # Layer reference list (copper + mask + silk)
        stackup = getattr(self.board, "stackup", None)
        if stackup is not None:
            for layer in getattr(stackup, "layers", []):
                ET.SubElement(
                    content,
                    "LayerRef",
                    {"name": getattr(layer, "name", "layer")},
                )
        ET.SubElement(
            content,
            "BomRef",
            {"name": f"{self.board.name or 'board_1'}_bom"},
        )

    def _build_logical_header(self, parent: ET.Element) -> None:
        lh = ET.SubElement(parent, "LogicalHeader")
        owner = ET.SubElement(
            lh,
            "Owner",
            {"name": "OpenForge"},
        )
        ET.SubElement(
            owner,
            "Person",
            {"name": "OpenForge User", "enterpriseRef": "OpenForge"},
        )
        ET.SubElement(
            lh,
            "Title",
            {"name": self.board.name or "board"},
        )
        ET.SubElement(
            lh,
            "Source",
            {"name": "OpenForge EDA"},
        )
        ET.SubElement(
            lh,
            "Generator",
            {"name": "openforge.pcb.ipc2581"},
        )
        ET.SubElement(
            lh,
            "GeneratorVersion",
            {"version": "1.0.0"},
        )
        ET.SubElement(
            lh,
            "Date",
            {"dateTime": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")},
        )

    def _build_history_record(self, parent: ET.Element) -> None:
        hist = ET.SubElement(
            parent,
            "HistoryRecord",
            {
                "number": "1",
                "origination": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "software": "OpenForge EDA",
                "lastChange": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        ET.SubElement(
            hist,
            "FileRevision",
            {
                "fileRevisionId": self._generate_uuid(),
                "comment": "Initial export",
                "label": "Rev 1",
            },
        )

    def _build_bom_header(self, parent: ET.Element) -> None:
        bh = ET.SubElement(
            parent,
            "BomHeader",
            {
                "assembly": self.board.name or "board_1",
                "revision": "1",
                "affectedItem": self.board.name or "board_1",
            },
        )
        ET.SubElement(
            bh,
            "Title",
            {"name": f"{self.board.name or 'board'} BOM"},
        )
        ET.SubElement(
            bh,
            "Source",
            {"name": "OpenForge"},
        )

    def _build_bom(self, parent: ET.Element) -> None:
        bom = ET.SubElement(
            parent,
            "Bom",
            {"name": f"{self.board.name or 'board_1'}_bom"},
        )
        # Group footprints by (value, footprint name) for BOM lines
        groups: dict[tuple[str, str], list[str]] = {}
        for fp in getattr(self.board, "footprints", []):
            key = (fp.value or fp.ref, fp.name)
            groups.setdefault(key, []).append(fp.ref)

        for idx, ((value, fpname), refs) in enumerate(groups.items(), start=1):
            item = ET.SubElement(
                bom,
                "BomItem",
                {
                    "OEMDesignNumberRef": f"BOM{idx:04d}",
                    "quantity": str(len(refs)),
                    "pinCount": "0",
                    "category": "ELECTRICAL",
                },
            )
            ET.SubElement(
                item,
                "RefDes",
                {"name": ",".join(refs), "populate": "true"},
            )
            char = ET.SubElement(item, "Characteristics", {"category": "ELECTRICAL"})
            ET.SubElement(
                char,
                "Textual",
                {
                    "definitionSource": "VALUE",
                    "textualCharacteristicName": "Value",
                    "textualCharacteristicValue": value or "",
                },
            )
            ET.SubElement(
                char,
                "Textual",
                {
                    "definitionSource": "FOOTPRINT",
                    "textualCharacteristicName": "Footprint",
                    "textualCharacteristicValue": fpname or "",
                },
            )

    def _build_ecad(self, parent: ET.Element) -> None:
        ecad = ET.SubElement(
            parent,
            "Ecad",
            {"name": f"{self.board.name or 'board'}_ecad"},
        )
        self._build_cad_header(ecad)
        self._build_cad_data(ecad)

    def _build_cad_header(self, parent: ET.Element) -> None:
        ch = ET.SubElement(parent, "CadHeader", {"units": "MILLIMETER"})
        spec = ET.SubElement(ch, "Spec", {"name": "OpenForgeDefaultSpec"})
        gen = ET.SubElement(spec, "General", {"type": "ELECTRICAL"})
        # DRC rules
        drc_rules = getattr(self.board, "drc_rules", {}) or {}
        min_track = float(drc_rules.get("min_track_width_mm", 0.15))
        min_clear = float(drc_rules.get("min_clearance_mm", 0.15))
        ET.SubElement(
            gen,
            "Property",
            {
                "name": "minimum_line_width",
                "value": self._format_real(min_track),
                "units": "MILLIMETER",
            },
        )
        ET.SubElement(
            gen,
            "Property",
            {
                "name": "minimum_clearance",
                "value": self._format_real(min_clear),
                "units": "MILLIMETER",
            },
        )

    def _build_cad_data(self, parent: ET.Element) -> None:
        cd = ET.SubElement(parent, "CadData")
        self._build_layers(cd)
        self._build_stackup(cd)
        self._build_step(cd)

    def _build_layers(self, parent: ET.Element) -> None:
        stackup = getattr(self.board, "stackup", None)
        if stackup is None:
            return
        cu_index = 0
        for layer in getattr(stackup, "layers", []):
            lname = getattr(layer, "name", "layer")
            lkind = getattr(layer, "kind", "signal")
            if lkind in ("signal", "plane"):
                cu_index += 1
                layer_func = "CONDUCTOR" if lkind == "signal" else "PLANE"
                side = (
                    "TOP" if cu_index == 1 else ("BOTTOM" if lname.startswith("B.") else "INTERNAL")
                )
            elif lkind == "dielectric":
                layer_func = "DIELCORE"
                side = "INTERNAL"
            elif lkind == "mask":
                layer_func = "SOLDERMASK"
                side = "TOP" if lname.startswith("F.") else "BOTTOM"
            elif lkind == "silk":
                layer_func = "SILKSCREEN"
                side = "TOP" if lname.startswith("F.") else "BOTTOM"
            elif lkind == "paste":
                layer_func = "SOLDERPASTE"
                side = "TOP" if lname.startswith("F.") else "BOTTOM"
            else:
                layer_func = "DOCUMENT"
                side = "INTERNAL"
            ET.SubElement(
                parent,
                "Layer",
                {
                    "name": lname,
                    "layerFunction": layer_func,
                    "side": side,
                    "polarity": "POSITIVE",
                },
            )

    def _build_stackup(self, parent: ET.Element) -> None:
        stackup = getattr(self.board, "stackup", None)
        if stackup is None:
            return
        sg = ET.SubElement(
            parent,
            "Stackup",
            {
                "name": "main_stackup",
                "overallThickness": self._format_real(
                    sum(
                        float(getattr(l, "thickness_mm", 0.0))
                        for l in getattr(stackup, "layers", [])
                    )
                ),
                "whereMeasured": "METAL",
                "stackupStatus": "PROPOSED",
            },
        )
        sg_group = ET.SubElement(sg, "StackupGroup", {"name": "main"})
        for idx, layer in enumerate(getattr(stackup, "layers", []), start=1):
            ET.SubElement(
                sg_group,
                "StackupLayer",
                {
                    "layerOfGroupRef": getattr(layer, "name", f"L{idx}"),
                    "thickness": self._format_real(getattr(layer, "thickness_mm", 0.0)),
                    "tolPlus": "0.05",
                    "tolMinus": "0.05",
                    "sequence": str(idx),
                },
            )

    def _build_step(self, parent: ET.Element) -> None:
        step = ET.SubElement(
            parent,
            "Step",
            {"name": self.board.name or "board_1"},
        )
        # Datum
        ET.SubElement(step, "Datum", {"x": "0", "y": "0"})
        bx0, by0, bx1, by1 = self.board.bounding_box()
        da = ET.SubElement(step, "DesignArea")
        ET.SubElement(
            da,
            "Point",
            {"x": self._format_real(bx0), "y": self._format_real(by0)},
        )
        ET.SubElement(
            da,
            "Point",
            {"x": self._format_real(bx1), "y": self._format_real(by1)},
        )

        # Profile (board outline)
        profile = ET.SubElement(step, "Profile")
        poly = ET.SubElement(profile, "Polygon")
        outline = self.board.outline or [
            (bx0, by0),
            (bx1, by0),
            (bx1, by1),
            (bx0, by1),
        ]
        if outline:
            first = outline[0]
            ET.SubElement(
                poly,
                "PolyBegin",
                {
                    "x": self._format_real(first[0]),
                    "y": self._format_real(first[1]),
                },
            )
            for x, y in outline[1:]:
                ET.SubElement(
                    poly,
                    "PolyStepSegment",
                    {"x": self._format_real(x), "y": self._format_real(y)},
                )
            ET.SubElement(
                poly,
                "PolyStepSegment",
                {
                    "x": self._format_real(first[0]),
                    "y": self._format_real(first[1]),
                },
            )

        # BomRef
        ET.SubElement(
            step,
            "BomRef",
            {"name": f"{self.board.name or 'board_1'}_bom"},
        )

        # Components
        self._build_components(step)
        # Nets
        self._build_nets(step)
        # Layer features
        self._build_layer_features(step)

    def _build_components(self, parent: ET.Element) -> None:
        for fp in getattr(self.board, "footprints", []):
            layer_name = "F.Cu" if getattr(fp, "layer", "top") == "top" else "B.Cu"
            comp = ET.SubElement(
                parent,
                "Component",
                {
                    "refDes": fp.ref,
                    "packageRef": fp.name,
                    "part": fp.value or fp.name,
                    "layerRef": layer_name,
                    "mountType": "SMT",
                },
            )
            ET.SubElement(
                comp,
                "NonstandardAttribute",
                {"name": "value", "value": fp.value or "", "type": "STRING"},
            )
            ET.SubElement(
                comp,
                "Xform",
                {
                    "rotation": self._format_real(fp.rotation_deg, 2),
                    "mirror": "false",
                },
            )
            ET.SubElement(
                comp,
                "Location",
                {
                    "x": self._format_real(fp.x_mm),
                    "y": self._format_real(fp.y_mm),
                },
            )

    def _build_nets(self, parent: ET.Element) -> None:
        for nid, name in getattr(self.board, "nets", {}).items():
            if not name:
                continue
            ET.SubElement(
                parent,
                "LogicalNet",
                {
                    "name": name,
                    "net": str(nid),
                },
            )

    def _build_layer_features(self, parent: ET.Element) -> None:
        # Group features by layer
        by_layer: dict[str, dict[str, list[Any]]] = {}

        def _bucket(layer_name: str) -> dict[str, list[Any]]:
            return by_layer.setdefault(
                layer_name, {"tracks": [], "vias": [], "pads": [], "zones": []}
            )

        for t in getattr(self.board, "tracks", []):
            _bucket(t.layer)["tracks"].append(t)
        for v in getattr(self.board, "vias", []):
            _bucket(v.layer_from)["vias"].append(v)
            if v.layer_to != v.layer_from:
                _bucket(v.layer_to)["vias"].append(v)
        for z in getattr(self.board, "zones", []):
            _bucket(z.layer)["zones"].append(z)
        for fp in getattr(self.board, "footprints", []):
            for pad in fp.pads:
                for lname in pad.layers:
                    _bucket(lname)["pads"].append((fp, pad))

        for layer_name, feats in by_layer.items():
            lf = ET.SubElement(
                parent,
                "LayerFeature",
                {"layerRef": layer_name},
            )
            fset = ET.SubElement(
                lf,
                "Set",
                {"geometryUsage": "ELECTRICAL"},
            )

            # Tracks -> Line features
            for t in feats["tracks"]:
                feat = ET.SubElement(
                    fset,
                    "Features",
                    {"id": self._generate_uuid()},
                )
                line = ET.SubElement(
                    feat,
                    "Line",
                    {
                        "startX": self._format_real(t.x1_mm),
                        "startY": self._format_real(t.y1_mm),
                        "endX": self._format_real(t.x2_mm),
                        "endY": self._format_real(t.y2_mm),
                    },
                )
                ET.SubElement(
                    line,
                    "LineDescRef",
                    {"id": f"LD_{self._format_real(t.width_mm)}"},
                )

            # Vias -> Pad (round)
            for v in feats["vias"]:
                feat = ET.SubElement(
                    fset,
                    "Features",
                    {"id": self._generate_uuid()},
                )
                ET.SubElement(
                    feat,
                    "Pad",
                    {
                        "x": self._format_real(v.x_mm),
                        "y": self._format_real(v.y_mm),
                    },
                )
                ET.SubElement(
                    feat,
                    "Circle",
                    {"diameter": self._format_real(v.diameter_mm)},
                )

            # Component pads -> Pad features
            for fp, pad in feats["pads"]:
                wx, wy = fp.pad_world_xy(pad)
                feat = ET.SubElement(
                    fset,
                    "Features",
                    {"id": self._generate_uuid()},
                )
                ET.SubElement(
                    feat,
                    "Pad",
                    {
                        "x": self._format_real(wx),
                        "y": self._format_real(wy),
                    },
                )
                if pad.shape == "round" or pad.drill_mm > 0:
                    ET.SubElement(
                        feat,
                        "Circle",
                        {"diameter": self._format_real(min(pad.size_x_mm, pad.size_y_mm))},
                    )
                else:
                    ET.SubElement(
                        feat,
                        "RectCenter",
                        {
                            "width": self._format_real(pad.size_x_mm),
                            "height": self._format_real(pad.size_y_mm),
                        },
                    )

            # Zones -> Polygons
            for z in feats["zones"]:
                if not z.polygon:
                    continue
                feat = ET.SubElement(
                    fset,
                    "Features",
                    {"id": self._generate_uuid()},
                )
                poly = ET.SubElement(feat, "Surface", {"polarity": "POSITIVE"})
                pg = ET.SubElement(poly, "Polygon")
                first = z.polygon[0]
                ET.SubElement(
                    pg,
                    "PolyBegin",
                    {
                        "x": self._format_real(first[0]),
                        "y": self._format_real(first[1]),
                    },
                )
                for x, y in z.polygon[1:]:
                    ET.SubElement(
                        pg,
                        "PolyStepSegment",
                        {
                            "x": self._format_real(x),
                            "y": self._format_real(y),
                        },
                    )
                ET.SubElement(
                    pg,
                    "PolyStepSegment",
                    {
                        "x": self._format_real(first[0]),
                        "y": self._format_real(first[1]),
                    },
                )


__all__ = ["Ipc2581Exporter"]
