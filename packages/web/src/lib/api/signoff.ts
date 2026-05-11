/**
 * Sign-off API client + shared types for DRC, LVS and xRC reports.
 *
 * Mirrors the FastAPI route in
 * ``packages/api/src/openforge_api/routes/signoff.py``.
 */

const API_BASE = '/api';

// --- DRC --------------------------------------------------------------------

export interface DrcRuleCount {
	rule: string;
	count: number;
}

export type DrcSeverity = 'green' | 'yellow' | 'red';

export interface DrcReport {
	project_id: string;
	rule_deck: string;
	rules_loaded: number;
	total_violations: number;
	top_rules: DrcRuleCount[];
	severity: DrcSeverity;
}

// --- LVS --------------------------------------------------------------------

export interface LvsSideCounts {
	devices: number;
	nets: number;
}

export type LvsVerdict = 'MATCH' | 'MISMATCH' | 'UNKNOWN';

export interface LvsReport {
	project_id: string;
	verdict: LvsVerdict;
	layout: LvsSideCounts;
	schematic: LvsSideCounts;
	physical_only_filtered: number;
	mismatched_devices: string[];
	mismatched_nets: string[];
}

// --- xRC --------------------------------------------------------------------

export interface XrcCornerC {
	min: number;
	typ: number;
	max: number;
}

export interface XrcWorstNet {
	name: string;
	r: number;
	c: number;
}

export interface XrcReport {
	project_id: string;
	total_wirelength_um: number;
	total_r_ohm: number;
	total_c_ff: XrcCornerC;
	worst_net: XrcWorstNet;
	coupling_pairs: number;
	spef_files: Record<string, string>;
}

// --- Helpers ---------------------------------------------------------------

/** Map a raw violation count to the DRC severity bucket. */
export function severityFor(violations: number): DrcSeverity {
	if (violations > 1000) return 'red';
	if (violations > 100) return 'yellow';
	return 'green';
}

/** Tailwind text color class for a severity. */
export function severityClass(sev: DrcSeverity): string {
	switch (sev) {
		case 'red':
			return 'text-red-400';
		case 'yellow':
			return 'text-yellow-300';
		default:
			return 'text-emerald-400';
	}
}

/** Tailwind background class for a severity badge. */
export function severityBg(sev: DrcSeverity): string {
	switch (sev) {
		case 'red':
			return 'bg-red-500/15 border-red-400/40';
		case 'yellow':
			return 'bg-yellow-500/10 border-yellow-300/40';
		default:
			return 'bg-emerald-500/10 border-emerald-400/40';
	}
}

/** Format a fF value as a human-readable capacitance string. */
export function formatCap(ff: number): string {
	if (ff >= 1e6) return `${(ff / 1e6).toFixed(2)} nF`;
	if (ff >= 1e3) return `${(ff / 1e3).toFixed(2)} pF`;
	return `${ff.toFixed(2)} fF`;
}

/** Format a resistance value (Ω → kΩ / MΩ). */
export function formatRes(ohm: number): string {
	if (ohm >= 1e6) return `${(ohm / 1e6).toFixed(2)} MΩ`;
	if (ohm >= 1e3) return `${(ohm / 1e3).toFixed(2)} kΩ`;
	return `${ohm.toFixed(2)} Ω`;
}

/** Format a wirelength value in µm/mm. */
export function formatLength(um: number): string {
	if (um >= 1e6) return `${(um / 1e6).toFixed(3)} m`;
	if (um >= 1e3) return `${(um / 1e3).toFixed(2)} mm`;
	return `${um.toFixed(2)} µm`;
}

// --- Mock fallbacks (PicoRV32 sky130 numbers) ------------------------------

export const MOCK_DRC: DrcReport = {
	project_id: 'mock-picorv32',
	rule_deck: 'sky130_subset.drc (DRX)',
	rules_loaded: 8,
	total_violations: 721_702,
	top_rules: [
		{ rule: 'met1.density', count: 612_400 },
		{ rule: 'li1.spacing', count: 81_200 },
		{ rule: 'met1.spacing', count: 16_840 },
		{ rule: 'via.enclosure', count: 6_220 },
		{ rule: 'poly.width', count: 2_910 },
		{ rule: 'diff.spacing', count: 1_240 },
		{ rule: 'nwell.overlap', count: 612 },
		{ rule: 'tap.distance', count: 280 }
	],
	severity: 'red'
};

export const MOCK_LVS: LvsReport = {
	project_id: 'mock-picorv32',
	verdict: 'MATCH',
	layout: { devices: 7971, nets: 8191 },
	schematic: { devices: 7971, nets: 8191 },
	physical_only_filtered: 12,
	mismatched_devices: [],
	mismatched_nets: []
};

export const MOCK_XRC: XrcReport = {
	project_id: 'mock-picorv32',
	total_wirelength_um: 1_887_929.9,
	total_r_ohm: 1_676_813.7,
	total_c_ff: {
		min: 13_045_746.7,
		typ: 14_495_274.1,
		max: 15_944_801.5
	},
	worst_net: { name: '_00006_[1]', r: 40_205.2, c: 379_988.0 },
	coupling_pairs: 299_267,
	spef_files: {
		min: 'build/xrc/picorv32.min.spef',
		typ: 'build/xrc/picorv32.typ.spef',
		max: 'build/xrc/picorv32.max.spef'
	}
};

// --- Fetchers --------------------------------------------------------------

async function fetchOrNull<T>(path: string): Promise<T | null> {
	try {
		const res = await fetch(`${API_BASE}${path}`);
		if (!res.ok) return null;
		return (await res.json()) as T;
	} catch {
		return null;
	}
}

export const fetchDrc = (projectId: string) =>
	fetchOrNull<DrcReport>(`/signoff/${projectId}/drc`);

export const fetchLvs = (projectId: string) =>
	fetchOrNull<LvsReport>(`/signoff/${projectId}/lvs`);

export const fetchXrc = (projectId: string) =>
	fetchOrNull<XrcReport>(`/signoff/${projectId}/xrc`);
