import { describe, expect, it } from 'vitest';
import {
	severityFor,
	severityClass,
	severityBg,
	formatCap,
	formatRes,
	formatLength,
	MOCK_DRC,
	MOCK_LVS,
	MOCK_XRC
} from './signoff';

describe('DRC tab data', () => {
	it('classifies severity by violation count', () => {
		expect(severityFor(0)).toBe('green');
		expect(severityFor(50)).toBe('green');
		expect(severityFor(101)).toBe('yellow');
		expect(severityFor(1001)).toBe('red');
	});

	it('mock DRC matches the PicoRV32 sky130 sign-off report', () => {
		expect(MOCK_DRC.total_violations).toBe(721_702);
		expect(MOCK_DRC.severity).toBe('red');
		expect(MOCK_DRC.top_rules.length).toBeGreaterThan(0);
		expect(MOCK_DRC.top_rules.length).toBeLessThanOrEqual(10);
		// Top rules sorted descending
		for (let i = 1; i < MOCK_DRC.top_rules.length; i++) {
			expect(MOCK_DRC.top_rules[i - 1].count).toBeGreaterThanOrEqual(
				MOCK_DRC.top_rules[i].count
			);
		}
	});

	it('severity classes return Tailwind tokens', () => {
		expect(severityClass('red')).toContain('red');
		expect(severityClass('yellow')).toContain('yellow');
		expect(severityClass('green')).toContain('emerald');
		expect(severityBg('red')).toContain('red');
	});
});

describe('LVS tab data', () => {
	it('mock LVS reports MATCH on PicoRV32 with balanced device/net counts', () => {
		expect(MOCK_LVS.verdict).toBe('MATCH');
		expect(MOCK_LVS.layout.devices).toBe(7971);
		expect(MOCK_LVS.schematic.devices).toBe(7971);
		expect(MOCK_LVS.layout.nets).toBe(MOCK_LVS.schematic.nets);
		expect(MOCK_LVS.mismatched_devices).toHaveLength(0);
		expect(MOCK_LVS.mismatched_nets).toHaveLength(0);
		expect(MOCK_LVS.physical_only_filtered).toBeGreaterThanOrEqual(0);
	});
});

describe('xRC tab data', () => {
	it('mock xRC matches the PicoRV32 sky130 corner sweep', () => {
		// 14.5 nF typ
		expect(MOCK_XRC.total_c_ff.typ).toBeCloseTo(14_495_274.1, 0);
		// min < typ < max (10% derate)
		expect(MOCK_XRC.total_c_ff.min).toBeLessThan(MOCK_XRC.total_c_ff.typ);
		expect(MOCK_XRC.total_c_ff.typ).toBeLessThan(MOCK_XRC.total_c_ff.max);
		expect(MOCK_XRC.coupling_pairs).toBe(299_267);
		expect(Object.keys(MOCK_XRC.spef_files)).toEqual(
			expect.arrayContaining(['min', 'typ', 'max'])
		);
	});

	it('formats capacitance/resistance/length with engineering units', () => {
		expect(formatCap(14_495_274.1)).toMatch(/nF$/);
		expect(formatCap(500)).toMatch(/fF$/);
		expect(formatRes(1_676_813.7)).toMatch(/MΩ$/);
		expect(formatRes(120)).toMatch(/Ω$/);
		expect(formatLength(1_887_929.9)).toMatch(/mm$/);
		expect(formatLength(50)).toMatch(/µm$/);
	});
});
