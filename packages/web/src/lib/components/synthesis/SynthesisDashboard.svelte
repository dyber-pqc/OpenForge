<script lang="ts">
	/**
	 * Synthesis results dashboard -- shows resource utilization, cell usage,
	 * timing estimates, and synthesis flow progress.
	 */

	interface CellUsage {
		type: string;
		count: number;
		area: number;
	}

	interface SynthesisResult {
		gate_count: number;
		ff_count: number;
		lut_count: number;
		area_um2: number;
		wns_ns: number | null;
		tns_ns: number | null;
		cell_usage: CellUsage[];
		duration_s: number;
		warnings: number;
		errors: number;
		status: 'running' | 'passed' | 'failed' | 'pending';
		current_stage: string;
	}

	let {
		result = null
	}: {
		result: SynthesisResult | null;
	} = $props();

	const stages = [
		{ name: 'Read', icon: '1' },
		{ name: 'Elaborate', icon: '2' },
		{ name: 'Optimize', icon: '3' },
		{ name: 'Map', icon: '4' },
		{ name: 'Write', icon: '5' },
	];

	function stageStatus(name: string): 'done' | 'active' | 'pending' {
		if (!result) return 'pending';
		const idx = stages.findIndex(s => s.name === name);
		const currentIdx = stages.findIndex(s => s.name === result!.current_stage);
		if (idx < currentIdx) return 'done';
		if (idx === currentIdx) return 'active';
		return 'pending';
	}

	function formatArea(um2: number): string {
		if (um2 >= 1e6) return `${(um2 / 1e6).toFixed(2)} mm\u00B2`;
		return `${um2.toFixed(1)} \u00B5m\u00B2`;
	}

	function slackColor(ns: number | null): string {
		if (ns === null) return 'var(--color-text-secondary)';
		if (ns >= 0) return 'var(--color-success)';
		return 'var(--color-error)';
	}

	// Sort cell usage by count descending, take top 10
	let topCells = $derived(
		result?.cell_usage
			?.sort((a, b) => b.count - a.count)
			.slice(0, 12) ?? []
	);
	let maxCellCount = $derived(
		topCells.length > 0 ? topCells[0].count : 1
	);
</script>

<div class="synth-dashboard">
	<!-- Flow Progress -->
	<div class="flow-progress">
		{#each stages as stage, i}
			{@const status = stageStatus(stage.name)}
			<div class="stage" class:done={status === 'done'} class:active={status === 'active'}>
				<div class="stage-circle">
					{#if status === 'done'}
						<span class="check">&#10003;</span>
					{:else}
						{stage.icon}
					{/if}
				</div>
				<span class="stage-label">{stage.name}</span>
			</div>
			{#if i < stages.length - 1}
				<div class="stage-connector" class:done={status === 'done'}></div>
			{/if}
		{/each}
	</div>

	{#if result}
		<!-- Summary Cards -->
		<div class="summary-grid">
			<div class="card">
				<div class="card-label">Gates</div>
				<div class="card-value">{result.gate_count.toLocaleString()}</div>
			</div>
			<div class="card">
				<div class="card-label">Flip-Flops</div>
				<div class="card-value">{result.ff_count.toLocaleString()}</div>
			</div>
			<div class="card">
				<div class="card-label">Area</div>
				<div class="card-value">{formatArea(result.area_um2)}</div>
			</div>
			<div class="card">
				<div class="card-label">WNS</div>
				<div class="card-value" style="color: {slackColor(result.wns_ns)}">
					{result.wns_ns !== null ? `${result.wns_ns.toFixed(3)} ns` : '--'}
				</div>
			</div>
			<div class="card">
				<div class="card-label">Duration</div>
				<div class="card-value">{result.duration_s.toFixed(1)}s</div>
			</div>
			<div class="card">
				<div class="card-label">Messages</div>
				<div class="card-value">
					{#if result.errors > 0}
						<span style="color: var(--color-error)">{result.errors}E</span>
					{/if}
					{#if result.warnings > 0}
						<span style="color: var(--color-warning)">{result.warnings}W</span>
					{/if}
					{#if result.errors === 0 && result.warnings === 0}
						<span style="color: var(--color-success)">Clean</span>
					{/if}
				</div>
			</div>
		</div>

		<!-- Cell Usage Bar Chart -->
		<div class="section">
			<h3 class="section-title">Cell Usage</h3>
			<div class="cell-chart">
				{#each topCells as cell}
					<div class="cell-row">
						<span class="cell-name" title={cell.type}>{cell.type}</span>
						<div class="cell-bar-track">
							<div
								class="cell-bar-fill"
								style="width: {(cell.count / maxCellCount) * 100}%"
							></div>
						</div>
						<span class="cell-count">{cell.count}</span>
					</div>
				{/each}
			</div>
		</div>
	{:else}
		<div class="empty-state">
			<p>No synthesis results available</p>
			<p class="hint">Run <code>openforge synth</code> or click Synthesize in the toolbar</p>
		</div>
	{/if}
</div>

<style>
	.synth-dashboard { padding: 16px; overflow-y: auto; height: 100%; }

	.flow-progress {
		display: flex; align-items: center; justify-content: center;
		gap: 0; margin-bottom: 20px; padding: 12px 0;
	}
	.stage { display: flex; flex-direction: column; align-items: center; gap: 4px; }
	.stage-circle {
		width: 32px; height: 32px; border-radius: 50%;
		display: flex; align-items: center; justify-content: center;
		font-size: 12px; font-weight: 700;
		background: var(--color-bg-secondary); border: 2px solid var(--color-border);
		color: var(--color-text-secondary);
	}
	.stage.done .stage-circle { background: var(--color-success); border-color: var(--color-success); color: var(--color-bg-primary); }
	.stage.active .stage-circle { background: var(--color-accent); border-color: var(--color-accent); color: var(--color-bg-primary); animation: pulse 1.5s infinite; }
	.stage-label { font-size: 10px; color: var(--color-text-secondary); }
	.stage.done .stage-label { color: var(--color-success); }
	.stage.active .stage-label { color: var(--color-accent); }
	.check { font-size: 14px; }
	.stage-connector { width: 40px; height: 2px; background: var(--color-border); margin-bottom: 18px; }
	.stage-connector.done { background: var(--color-success); }

	@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }

	.summary-grid {
		display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 16px;
	}
	.card {
		background: var(--color-bg-secondary); border: 1px solid var(--color-border);
		border-radius: 6px; padding: 10px; text-align: center;
	}
	.card-label { font-size: 10px; text-transform: uppercase; color: var(--color-text-secondary); margin-bottom: 4px; }
	.card-value { font-size: 18px; font-weight: 600; color: var(--color-text-primary); }

	.section { margin-bottom: 16px; }
	.section-title {
		font-size: 12px; font-weight: 600; text-transform: uppercase;
		color: var(--color-text-secondary); margin-bottom: 8px;
		padding-bottom: 4px; border-bottom: 1px solid var(--color-border);
	}

	.cell-chart { display: flex; flex-direction: column; gap: 4px; }
	.cell-row { display: flex; align-items: center; gap: 8px; }
	.cell-name {
		width: 140px; font-size: 11px; font-family: 'JetBrains Mono', monospace;
		color: var(--color-text-secondary); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;
	}
	.cell-bar-track { flex: 1; height: 8px; background: var(--color-border); border-radius: 4px; overflow: hidden; }
	.cell-bar-fill { height: 100%; background: var(--color-accent); border-radius: 4px; transition: width 0.3s; }
	.cell-count { width: 50px; text-align: right; font-size: 11px; color: var(--color-text-primary); font-weight: 600; }

	.empty-state { text-align: center; padding: 40px; color: var(--color-text-secondary); }
	.hint { font-size: 12px; opacity: 0.5; margin-top: 8px; }
	code { background: var(--color-bg-secondary); padding: 2px 6px; border-radius: 3px; font-size: 11px; }
</style>
