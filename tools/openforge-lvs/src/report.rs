//! LVS report types and rendering.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NetMismatch {
    pub layout_net: Option<String>,
    pub schem_net: Option<String>,
    pub note: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceMismatch {
    pub layout_device: Option<String>,
    pub schem_device: Option<String>,
    pub note: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LvsReport {
    pub matched: bool,
    pub top: String,
    pub net_count_layout: usize,
    pub net_count_schem: usize,
    pub device_count_layout: usize,
    pub device_count_schem: usize,
    pub mismatched_nets: Vec<NetMismatch>,
    pub mismatched_devices: Vec<DeviceMismatch>,
    pub matched_pairs: Vec<(String, String)>,
    pub reason: Option<String>,
    /// Number of physical-only cells (tap, decap, fill, antenna diode)
    /// dropped from the layout DEF before LVS comparison. Always 0 for
    /// SPICE-only paths and for LVS runs with the filter disabled.
    #[serde(default)]
    pub filtered_physical_cells: usize,
    /// Human-readable summary of which physical-only macros were filtered.
    #[serde(default)]
    pub filtered_physical_summary: String,
}

impl LvsReport {
    pub fn render_human(&self) -> String {
        let mut s = String::new();
        s.push_str(&format!(
            "LVS RESULT: {}\n",
            if self.matched { "MATCH" } else { "MISMATCH" }
        ));
        s.push_str(&format!(
            "  Schematic: {} devices, {} nets\n",
            self.device_count_schem, self.net_count_schem
        ));
        s.push_str(&format!(
            "  Layout:    {} devices, {} nets\n",
            self.device_count_layout, self.net_count_layout
        ));
        if self.filtered_physical_cells > 0 {
            s.push_str(&format!("  {}\n", self.filtered_physical_summary));
        }
        if self.matched {
            s.push_str(&format!(
                "  Matched:   {} device pairs\n",
                self.matched_pairs.len()
            ));
        } else if let Some(r) = &self.reason {
            s.push('\n');
            s.push_str(r);
            s.push('\n');
        }
        s
    }
}
