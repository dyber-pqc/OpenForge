<script lang="ts">
	/**
	 * Physical design dashboard -- floorplan/placement/routing flow control
	 * with area/power/congestion metrics and DRC/LVS status.
	 */

	interface FlowStage {
		name: string;
		status: 'pending' | 'running' | 'done' | 'failed';
		duration_s: number | null;
	}

	interface PDMetrics {
		area_um2: number;
		utilization_pct: number;
		wirelength_um: number;
		drc_violations: number;
		power_mw: number;
		wns_ns: number | null;
		tns_ns: number | null;
	}

	let {
		stages = [
			{ name: 'Floorplan', status: 'pending', duration_s: null },
			{ name: 'Placement', status: 'pending', duration_s: null },
			{ name: 'CTS', status: 'pending', duration_s: null },
			{ name: 'Routing', status: 'pending', duration_s: null },
			{ name: 'Signoff', status: 'pending', duration_s: null },
		],
		metrics = null
	}: {
		stages: FlowStage[];
		metrics: PDMetrics | null;
	} = $props();

	let activeTab = $state<'flow' | 'metrics' | 'drc'>('flow');

	function statusIcon(status: string): string {
		switch (status) {
			case 'done': return '\u2705';
			case 'running': return '\u23F3';
			case 'failed': return '\u274C';
			default: return '\u26AA';
		}
	}

	function statusColor(status: string): string {
		switch (status) {
			case 'done': return 'var(--color-success)';
			case 'running': return 'var(--color-accent)';
			case 'failed': return 'var(--color-error)';
			default: return 'var(--color-text-secondary)';
		}
	}

	function formatArea(um2: number): string {
		if (um2 >= 1e6) return `${(um2 / 1e6).toFixed(3)} mm\u00B2`;
		return `${um2.toFixed(0)} \u00B5m\u00B2`;
	}
</script>

<div class="pd-dashboard">
	<div class="tabs">
		{#each [['flow', 'Flow Control'], ['metrics', 'Metrics'], ['drc', 'DRC/LVS']] as [key, label]}
			<button class="tab" class:active={activeTab === key} onclick={() => (activeTab = key as typeof activeTab)}>
				{label}
			</button>
		{/each}
	</div>

	<div class="content">
		{#if activeTab === 'flow'}
			<div class="flow-pipeline">
				{#each stages as stage, i}
					<div class="pipeline-stage">
						<div class="stage-header">
							<span class="stage-icon" style="color: {statusColor(stage.status)}">{statusIcon(stage.status)}</span>
							<span class="stage-name">{stage.name}</span>
							{#if stage.duration_s !== null}
								<span class="stage-duration">{stage.duration_s.toFixed(1)}s</span>
							{/if}
						</div>
						<div class="stage-bar" style="background: {statusColor(stage.status)}; opacity: {stage.status === 'pending' ? 0.2 : 0.8}"></div>
					</div>
				{/each}
			</div>

			<div class="flow-actions">
				<button class="action-btn primary">Run Full Flow</button>
				<button class="action-btn">Run Selected</button>
				<button class="action-btn danger">Stop</button>
			</div>

			<div class="flow-config">
				<h3 class="section-title">Configuration</h3>
				<div class="config-row">
					<label>Utilization</label>
					<input type="range" min="40" max="90" value="70" />
					<span>70%</span>
				</div>
				<div class="config-row">
					<label>Aspect Ratio</label>
					<input type="number" value="1.0" step="0.1" min="0.5" max="2.0" />
				</div>
				<div class="config-row">
					<label>Core Margin (\u00B5m)</label>
					<input type="number" value="10" step="1" />
				</div>
			</div>

		{:else if activeTab === 'metrics'}
			{#if metrics}
				<div class="metrics-grid">
					<div class="metric">
						<div class="metric-label">Die Area</div>
						<div class="metric-value">{formatArea(metrics.area_um2)}</div>
					</div>
					<div class="metric">
						<div class="metric-label">Utilization</div>
						<div class="metric-value">{metrics.utilization_pct.toFixed(1)}%</div>
						<div class="metric-bar">
							<div class="metric-fill" style="width: {metrics.utilization_pct}%"></div>
						</div>
					</div>
					<div class="metric">
						<div class="metric-label">Wirelength</div>
						<div class="metric-value">{(metrics.wirelength_um / 1000).toFixed(1)} mm</div>
					</div>
					<div class="metric">
						<div class="metric-label">Power</div>
						<div class="metric-value">{metrics.power_mw.toFixed(2)} mW</div>
					</div>
					<div class="metric">
						<div class="metric-label">WNS</div>
						<div class="metric-value" style="color: {metrics.wns_ns !== null && metrics.wns_ns >= 0 ? 'var(--color-success)' : 'var(--color-error)'}">
							{metrics.wns_ns !== null ? `${metrics.wns_ns.toFixed(3)} ns` : '--'}
						</div>
					</div>
					<div class="metric">
						<div class="metric-label">DRC</div>
						<div class="metric-value" style="color: {metrics.drc_violations === 0 ? 'var(--color-success)' : 'var(--color-error)'}">
							{metrics.drc_violations} violations
						</div>
					</div>
				</div>
			{:else}
				<p class="empty">Run physical design flow to see metrics</p>
			{/if}

		{:else}
			<div class="drc-section">
				<div class="drc-actions">
					<button class="action-btn">Run DRC</button>
					<button class="action-btn">Run LVS</button>
				</div>
				<p class="empty">No DRC/LVS results available</p>
			</div>
		{/if}
	</div>
</div>

<style>
	.pd-dashboard { display: flex; flex-direction: column; height: 100%; }
	.tabs { display: flex; border-bottom: 1px solid var(--color-border); flex-shrink: 0; }
	.tab { background: none; border: none; color: var(--color-text-secondary); padding: 8px 16px; font-size: 12px; cursor: pointer; border-bottom: 2px solid transparent; }
	.tab.active { color: var(--color-accent); border-bottom-color: var(--color-accent); }
	.content { flex: 1; overflow-y: auto; padding: 12px; }

	.flow-pipeline { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
	.pipeline-stage { }
	.stage-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
	.stage-icon { font-size: 14px; }
	.stage-name { font-size: 13px; font-weight: 500; flex: 1; }
	.stage-duration { font-size: 11px; color: var(--color-text-secondary); }
	.stage-bar { height: 4px; border-radius: 2px; }

	.flow-actions { display: flex; gap: 8px; margin-bottom: 16px; }
	.action-btn { background: var(--color-bg-secondary); border: 1px solid var(--color-border); color: var(--color-text-primary); padding: 6px 16px; border-radius: 4px; font-size: 12px; cursor: pointer; }
	.action-btn.primary { border-color: var(--color-accent); color: var(--color-accent); }
	.action-btn.danger { border-color: var(--color-error); color: var(--color-error); }
	.action-btn:hover { background: var(--color-border); }

	.section-title { font-size: 12px; font-weight: 600; text-transform: uppercase; color: var(--color-text-secondary); margin-bottom: 8px; }
	.config-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 12px; }
	.config-row label { width: 120px; color: var(--color-text-secondary); }
	.config-row input[type="range"] { flex: 1; }
	.config-row input[type="number"] { width: 80px; background: var(--color-bg-secondary); border: 1px solid var(--color-border); color: var(--color-text-primary); padding: 3px 6px; border-radius: 3px; }

	.metrics-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
	.metric { background: var(--color-bg-secondary); border: 1px solid var(--color-border); border-radius: 6px; padding: 12px; }
	.metric-label { font-size: 10px; text-transform: uppercase; color: var(--color-text-secondary); margin-bottom: 4px; }
	.metric-value { font-size: 18px; font-weight: 600; }
	.metric-bar { height: 4px; background: var(--color-border); border-radius: 2px; margin-top: 6px; overflow: hidden; }
	.metric-fill { height: 100%; background: var(--color-accent); border-radius: 2px; }

	.drc-actions { display: flex; gap: 8px; margin-bottom: 16px; }
	.empty { text-align: center; color: var(--color-text-secondary); opacity: 0.6; font-style: italic; padding: 24px; }
</style>
