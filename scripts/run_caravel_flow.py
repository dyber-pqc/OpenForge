"""Driver script to run the Caravel user_proj_example full RTL-to-GDS flow.

Bridges the legacy openforge.yaml schema (top_module / rtl_sources at root)
to the FullFlowRunner via FullFlowConfig.from_openforge_config so the
floorplan / placement / routing yaml overrides are honoured.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from openforge.config.loader import load_config
from openforge.flow.full_flow import FullFlowConfig, FullFlowRunner


def main(project_dir: str) -> int:
    pdir = Path(project_dir).resolve()
    cfg = load_config(search_dir=pdir)
    extra = cfg.model_extra or {}

    top = extra.get("top_module") or cfg.project.top_module
    rtl_globs = extra.get("rtl_sources") or cfg.design.sources or []
    constraints = extra.get("constraint_files") or cfg.design.constraints or []
    pdk_block = extra.get("pdk") or {}
    pdk_name = (
        pdk_block.get("name")
        if isinstance(pdk_block, dict)
        else None
    ) or cfg.project.target_pdk or "sky130A"
    std_cell = (
        pdk_block.get("std_cell_lib") if isinstance(pdk_block, dict) else None
    ) or "sky130_fd_sc_hd"

    rtl_files: list[str] = []
    for pat in rtl_globs:
        # Allow plain paths and globs.
        p = pdir / pat
        if p.exists():
            rtl_files.append(str(p))
            continue
        rtl_files.extend(str(x) for x in pdir.glob(pat))
    if not rtl_files:
        print("[driver] ERROR: no rtl files found", flush=True)
        return 2

    sdc_file = None
    for c in constraints:
        cp = pdir / c
        if cp.exists() and cp.suffix == ".sdc":
            # Pass relative path so OpenROAD (running under WSL) can resolve it
            # via ``../../<rel>`` from the per-stage build dir.
            sdc_file = c
            break
    if sdc_file is None:
        print("[driver] ERROR: no .sdc constraint", flush=True)
        return 2

    target_freq = 100.0
    meta = extra.get("metadata") or {}
    if isinstance(meta, dict) and meta.get("target_freq_mhz"):
        target_freq = float(meta["target_freq_mhz"])

    full_cfg = FullFlowConfig.from_openforge_config(
        cfg,
        top_module=top,
        rtl_files=rtl_files,
        sdc_file=sdc_file,
        pdk=pdk_name,
        std_cell_lib=std_cell,
        target_freq_mhz=target_freq,
        output_dir="build",
    )

    print("[driver] top:", top, flush=True)
    print("[driver] rtl:", rtl_files, flush=True)
    print("[driver] sdc:", sdc_file, flush=True)
    print("[driver] pdk:", pdk_name, flush=True)
    print(
        "[driver] floorplan_util:",
        full_cfg.floorplan_utilization,
        "die:",
        full_cfg.floorplan_die_area,
        "droute_iter:",
        full_cfg.routing_droute_end_iter,
        flush=True,
    )

    runner = FullFlowRunner(full_cfg, work_dir=pdir)
    t0 = time.time()

    def _on_stage(stage: str, status: str) -> None:
        elapsed = time.time() - t0
        print(f"[stage] +{elapsed:7.1f}s  {stage:12s} -> {status}", flush=True)

    result = runner.run(progress_callback=_on_stage)
    print(
        f"\n[driver] overall={result.overall_status} runtime={result.total_runtime_s:.1f}s",
        flush=True,
    )
    if result.gds_path:
        print(f"[driver] gds={result.gds_path}", flush=True)
    for s in result.stages:
        if s.errors:
            msg = f"[driver] {s.stage} errors: {s.errors[:3]}"
            try:
                print(msg, flush=True)
            except UnicodeEncodeError:
                print(msg.encode("ascii", "replace").decode("ascii"), flush=True)
    return 0 if result.overall_status == "success" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
