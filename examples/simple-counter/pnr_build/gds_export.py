# KLayout GDS export script
import pya

layout = pya.Layout()
opts = pya.LoadLayoutOptions()
opts.lefdef_config.read_lef_with_def = True
opts.lefdef_config.lef_files = [
    '/mnt/h/openforge/share/pdk/sky130/lef/sky130hd.tlef',
    '/mnt/h/openforge/share/pdk/sky130/lef/sky130_fd_sc_hd_merged.lef',
]

try:
    layout.read('/mnt/h/openforge/examples/simple-counter/pnr_build/counter_routed.def', opts)
    layout.write('/mnt/h/openforge/examples/simple-counter/pnr_build/counter.gds')
    import os
    size = os.path.getsize('/mnt/h/openforge/examples/simple-counter/pnr_build/counter.gds')
    print(f'GDS_EXPORTED: /mnt/h/openforge/examples/simple-counter/pnr_build/counter.gds ({size} bytes)')
except Exception as e:
    print(f'GDS_EXPORT_ERROR: {e}')
