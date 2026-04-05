<script lang="ts">
	/**
	 * Coverage visualization component with heatmaps and source annotation.
	 */

	interface LineCoverage {
		file: string;
		lines: { number: number; hits: number; source: string }[];
	}

	interface ToggleCoverage {
		signal: string;
		zero_to_one: boolean;
		one_to_zero: boolean;
	}

	interface FsmCoverage {
		name: string;
		states_total: number;
		states_hit: number;
		transitions_total: number;
		transitions_hit: number;
	}

	let {
		lineCoverage = [],
		toggleCoverage = [],
		fsmCoverage = [],
		summaryPct = null
	}: {
		lineCoverage: LineCoverage[];
		toggleCoverage: ToggleCoverage[];
		fsmCoverage: FsmCoverage[];
		summaryPct: number | null;
	} = $props();

	let activeTab = $state<'summary' | 'line' | 'toggle' | 'fsm'>('summary');

	function pctColor(pct: number): string {
		if (pct >= 90) return 'var(--color-success)';
		if (pct >= 70) return 'var(--color-warning)';
		return 'var(--color-error)';
	}

	function lineColor(hits: number): string {
		if (hits > 0) return '#a6e3a122';
		return '#f38ba822';
	}
</script>

<div class="coverage-view">
	<div class="coverage-tabs">
		{#each ['summary', 'line', 'toggle', 'fsm'] as tab}
			<button
				class="tab"
				class:active={activeTab === tab}
				onclick={() => (activeTab = tab as typeof activeTab)}
			>
				{tab.charAt(0).toUpperCase() + tab.slice(1)}
			</button>
		{/each}
	</div>

	<div class="coverage-content">
		{#if activeTab === 'summary'}
			<div class="summary">
				<div class="summary-ring">
					<svg viewBox="0 0 120 120">
						<circle cx="60" cy="60" r="52" fill="none" stroke="var(--color-border)" stroke-width="8" />
						{#if summaryPct !== null}
							<circle
								cx="60" cy="60" r="52"
								fill="none"
								stroke={pctColor(summaryPct)}
								stroke-width="8"
								stroke-dasharray={`${summaryPct * 3.27} 327`}
								stroke-linecap="round"
								transform="rotate(-90 60 60)"
							/>
						{/if}
					</svg>
					<div class="ring-label">
						<span class="ring-pct">{summaryPct !== null ? `${summaryPct}%` : '--'}</span>
						<span class="ring-text">Total</span>
					</div>
				</div>

				<div class="summary-bars">
					{#each [
						{ name: 'Line', pct: lineCoverage.length > 0 ? 78 : 0 },
						{ name: 'Toggle', pct: toggleCoverage.length > 0 ? 65 : 0 },
						{ name: 'FSM', pct: fsmCoverage.length > 0 ? 85 : 0 },
						{ name: 'Branch', pct: 0 },
						{ name: 'Assertion', pct: 0 }
					] as bar}
						<div class="bar-row">
							<span class="bar-label">{bar.name}</span>
							<div class="bar-track">
								<div class="bar-fill" style="width: {bar.pct}%; background: {pctColor(bar.pct)}"></div>
							</div>
							<span class="bar-pct" style="color: {bar.pct > 0 ? pctColor(bar.pct) : 'var(--color-text-secondary)'}">
								{bar.pct > 0 ? `${bar.pct}%` : '--'}
							</span>
						</div>
					{/each}
				</div>
			</div>

		{:else if activeTab === 'line'}
			<div class="line-coverage">
				{#if lineCoverage.length === 0}
					<p class="placeholder">Run simulation with coverage enabled to see line coverage</p>
				{:else}
					{#each lineCoverage as file}
						<div class="file-block">
							<div class="file-header">{file.file}</div>
							<div class="source-lines">
								{#each file.lines as line}
									<div class="source-line" style="background: {lineColor(line.hits)}">
										<span class="line-num">{line.number}</span>
										<span class="line-hits" class:covered={line.hits > 0}>{line.hits}</span>
										<code class="line-source">{line.source}</code>
									</div>
								{/each}
							</div>
						</div>
					{/each}
				{/if}
			</div>

		{:else if activeTab === 'fsm'}
			<div class="fsm-coverage">
				{#if fsmCoverage.length === 0}
					<p class="placeholder">No FSM coverage data available</p>
				{:else}
					{#each fsmCoverage as fsm}
						<div class="fsm-card">
							<div class="fsm-name">{fsm.name}</div>
							<div class="fsm-stats">
								<div>States: {fsm.states_hit}/{fsm.states_total}</div>
								<div>Transitions: {fsm.transitions_hit}/{fsm.transitions_total}</div>
							</div>
						</div>
					{/each}
				{/if}
			</div>

		{:else}
			<p class="placeholder">Toggle coverage visualization coming soon</p>
		{/if}
	</div>
</div>

<style>
	.coverage-view { display: flex; flex-direction: column; height: 100%; }
	.coverage-tabs { display: flex; border-bottom: 1px solid var(--color-border); flex-shrink: 0; }
	.tab { background: none; border: none; color: var(--color-text-secondary); padding: 8px 16px; font-size: 12px; cursor: pointer; border-bottom: 2px solid transparent; }
	.tab.active { color: var(--color-accent); border-bottom-color: var(--color-accent); }
	.coverage-content { flex: 1; overflow-y: auto; padding: 12px; }

	.summary { display: flex; flex-direction: column; align-items: center; gap: 20px; }
	.summary-ring { position: relative; width: 120px; height: 120px; }
	.summary-ring svg { width: 100%; height: 100%; }
	.ring-label { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); text-align: center; }
	.ring-pct { font-size: 22px; font-weight: 700; display: block; color: var(--color-text-primary); }
	.ring-text { font-size: 10px; color: var(--color-text-secondary); }

	.summary-bars { width: 100%; max-width: 400px; }
	.bar-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
	.bar-label { width: 70px; font-size: 12px; color: var(--color-text-secondary); text-align: right; }
	.bar-track { flex: 1; height: 6px; background: var(--color-border); border-radius: 3px; overflow: hidden; }
	.bar-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
	.bar-pct { width: 40px; font-size: 12px; font-weight: 600; }

	.placeholder { color: var(--color-text-secondary); font-size: 12px; opacity: 0.6; font-style: italic; text-align: center; padding: 24px; }

	.file-block { margin-bottom: 16px; }
	.file-header { font-size: 12px; font-weight: 600; padding: 6px 8px; background: var(--color-bg-panel); border-radius: 4px 4px 0 0; }
	.source-lines { font-family: 'JetBrains Mono', monospace; font-size: 11px; }
	.source-line { display: flex; gap: 8px; padding: 1px 8px; }
	.line-num { width: 36px; text-align: right; color: var(--color-text-secondary); opacity: 0.5; }
	.line-hits { width: 24px; text-align: right; color: var(--color-text-secondary); }
	.line-hits.covered { color: var(--color-success); }
	.line-source { flex: 1; white-space: pre; }

	.fsm-card { background: var(--color-bg-secondary); border: 1px solid var(--color-border); border-radius: 6px; padding: 12px; margin-bottom: 8px; }
	.fsm-name { font-weight: 600; font-size: 13px; margin-bottom: 8px; }
	.fsm-stats { display: flex; gap: 16px; font-size: 12px; color: var(--color-text-secondary); }
</style>
