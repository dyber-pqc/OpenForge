"""KLayout GDSII viewer and DRC engine."""

from __future__ import annotations

import re
from os import PathLike
from typing import Mapping, Sequence

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult


class KLayoutEngine(ToolEngine):
    """Wraps KLayout for DRC, layout viewing, and image export.

    Typical workflow::

        engine = KLayoutEngine()
        result = engine.run_drc("design.gds", "rules.drc")
    """

    BINARY = "klayout"
    DOCKER_IMAGE = "klayout/klayout:latest"

    def __init__(
        self,
        *,
        backend: ExecutionBackend = ExecutionBackend.NATIVE,
        binary_override: str | None = None,
    ) -> None:
        super().__init__(
            backend=backend,
            binary_override=binary_override,
        )

    # ------------------------------------------------------------------
    # ToolEngine interface
    # ------------------------------------------------------------------

    def check_installed(self) -> bool:
        if self.backend == ExecutionBackend.DOCKER:
            return self.run(["-v"]).ok
        return self._which() is not None

    def version(self) -> str:
        result = self.run(["-v"])
        text = result.stdout + result.stderr
        # "KLayout 0.28.15 ..."
        if m := re.search(r"KLayout\s+([\d.]+)", text, re.IGNORECASE):
            return m.group(1)
        # Sometimes version is just a number
        if m := re.search(r"(\d+\.\d+[\d.]*)", text):
            return m.group(1)
        return "unknown"

    # ------------------------------------------------------------------
    # High-level operations
    # ------------------------------------------------------------------

    def run_drc(
        self,
        gds_file: str | PathLike[str],
        drc_script: str | PathLike[str],
        *,
        extra_args: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run a DRC rule deck on a GDSII layout in batch mode.

        Parameters
        ----------
        gds_file:
            Input GDSII layout file.
        drc_script:
            DRC rule script (Ruby or Python).
        extra_args:
            Arbitrary extra flags.
        """
        args: list[str] = [
            "-b",
            "-r", str(drc_script),
            "-rd", f"input={gds_file}",
        ]
        args.extend(extra_args)

        return self.run(args, cwd=cwd, env=env, timeout=timeout)

    def view(
        self,
        gds_file: str | PathLike[str],
        *,
        layer_props: str | PathLike[str] | None = None,
        extra_args: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Open a GDSII file in the KLayout GUI viewer.

        Parameters
        ----------
        gds_file:
            GDSII layout file to view.
        layer_props:
            Optional layer properties (``.lyp``) file.
        extra_args:
            Arbitrary extra flags.

        Note
        ----
        This launches a GUI application and typically does not return
        until the user closes the window.
        """
        args: list[str] = [str(gds_file)]

        if layer_props:
            args.extend(["-ly", str(layer_props)])

        args.extend(extra_args)

        return self.run(args, cwd=cwd, env=env, timeout=timeout)

    def export_image(
        self,
        gds_file: str | PathLike[str],
        output_png: str | PathLike[str],
        *,
        layer_props: str | PathLike[str] | None = None,
        width: int = 1024,
        height: int = 1024,
        extra_args: Sequence[str] = (),
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Export a GDSII layout to a PNG image in batch mode.

        Parameters
        ----------
        gds_file:
            Input GDSII layout file.
        output_png:
            Output PNG image path.
        layer_props:
            Optional layer properties (``.lyp``) file.
        width:
            Image width in pixels.
        height:
            Image height in pixels.
        extra_args:
            Arbitrary extra flags.
        """
        # Build a minimal Ruby export script using KLayout runtime variables
        export_script_lines = [
            "ly = RBA::Layout.new",
            "ly.read($input)",
            "lv = RBA::LayoutView.new",
            "lv.show_layout(ly, false)",
        ]
        if layer_props:
            export_script_lines.append("lv.load_layer_props($lyp)")
        export_script_lines.append(
            "lv.save_image($output, $width.to_i, $height.to_i)"
        )
        export_ruby = "; ".join(export_script_lines)

        args: list[str] = [
            "-b",
            "-rd", f"input={gds_file}",
            "-rd", f"output={output_png}",
            "-rd", f"width={width}",
            "-rd", f"height={height}",
        ]
        if layer_props:
            args.extend(["-rd", f"lyp={layer_props}"])

        args.extend(["-r", export_ruby])
        args.extend(extra_args)

        return self.run(args, cwd=cwd, env=env, timeout=timeout)
