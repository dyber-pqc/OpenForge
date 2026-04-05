<script lang="ts">
	/**
	 * Timing analysis dashboard -- slack histogram, critical paths, clock summary.
	 */

	interface TimingPath {
		rank: number;
		slack_ns: number;
		start_point: string;
		end_point: string;
		delay_ns: number;
		levels: number;
		clock: string;
	}

	interface ClockDomain {
		name: string;
		period_ns: number;
		frequency_mhz: number;
		wns_ns: number;
		tns_ns: number;
		endpoints: number;
	}

	interface SlackBin {
		range_start: number;
		range_end: number;
		count: number;
	}

	let {
		wns = null,
		tns = null,
		paths = [],
		clocks = [],
		histogram = [],
		numEndpoints = 0,
		numViolated = 0
	}: {
		wns: number | null;
		tns: number | null;
		paths: TimingPath[];
		clocks: ClockDomain[];
		histogram: SlackBin[];
		numEndpoints: number;
		numViolated: number;
	} = $props();

	let activeTab = $state<'summary' | 'paths' | 'clocks'>('summary');
	let selectedPath = $state<TimingPath | null>(null);
	let pathFilter = $state<'all' | 'violated'>('all');

	function slackColor(ns: number | null): string {
		if (ns === null) return 'var(--color-text-secondary)';
		if (ns >= 0.5) return 'var(--color-success)';
		if (ns >= 0) return 'var(--color-warning)';
		return 'var(--color-error)';
	}

	let filteredPaths = $derived(
		pathFilter === 'violated' ? paths.filter(p => p.slack_ns < 0) : paths
	);

	// Histogram rendering
	let maxBinCount = $derived(
		histogram.length > 0 ? Math.max(...histogram.map(b => b.count)) : 1
	);
</script>

<div class="timing-dashboard">
	<div class="tabs">
		{#each [['summary', 'Summary'], ['paths', 'Paths'], ['clocks', 'Clocks']] as [key, label]}
			<button
				class="tab"
				class:active={activeTab === key}
				onclick={() => (activeTab = key as typeof activeTab)}
			>{label}</button>
		{/each}
	</div>

	<div class="content">
		{#if activeTab === 'summary'}
			<!-- WNS / TNS cards -->
			<div class="metric-row">
				<div class="metric-card large">
					<div class="metric-label">Worst Negative Slack</div>
					<div class="metric-value" style="color: {slackColor(wns)}">
						{wns !== null ? `${wns.toFixed(3)} ns` : '--'}
					</div>
					<div class="metric-status" style="color: {slackColor(wns)}">
						{wns !== null ? (wns >= 0 ? 'TIMING MET' : 'TIMING VIOLATED') : 'NOT ANALYZED'}
					</div>
				</div>
				<div class="metric-card large">
					<div class="metric-label">Total Negative Slack</div>
					<div class="metric-value" style="color: {slackColor(tns)}">
						{tns !== null ? `${tns.toFixed(3)} ns` : '--'}
					</div>
					<div class="metric-sub">
						{numViolated} / {numEndpoints} endpoints violated
					</div>
				</div>
			</div>

			<!-- Slack Histogram -->
			{#if histogram.length > 0}
				<div class="section">
					<h3 class="section-title">Slack Distribution</h3>
					<div class="histogram">
						{#each histogram as bin}
							{@const pct = (bin.count / maxBinCount) * 100}
							{@const isNeg = bin.range_end <= 0}
							<div class="hist-col" title="{bin.range_start.toFixed(2)} to {bin.range_end.toFixed(2)} ns: {bin.count} endpoints">
								<div class="hist-bar-container">
									<div
										class="hist-bar"
										style="height: {pct}%; background: {isNeg ? 'var(--color-error)' : 'var(--color-success)'};"
									></div>
								</div>
								<div class="hist-label">{bin.range_start.toFixed(1)}</div>
							</div>
						{/each}
					</div>
					<div class="hist-axis-label">Slack (ns)</div>
				</div>
			{/if}

		{:else if activeTab === 'paths'}
			<div class="path-controls">
				<select bind:value={pathFilter}>
					<option value="all">All Paths ({paths.length})</option>
					<option value="violated">Violated Only ({paths.filter(p => p.slack_ns < 0).length})</option>
				</select>
			</div>

			<div class="paths-table">
				<div class="table-header">
					<span class="col-rank">#</span>
					<span class="col-slack">Slack</span>
					<span class="col-start">Start Point</span>
					<span class="col-end">End Point</span>
					<span class="col-delay">Delay</span>
					<span class="col-levels">Levels</span>
					<span class="col-clock">Clock</span>
				</div>
				{#each filteredPaths as path}
					<button
						class="table-row"
						class:selected={selectedPath === path}
						class:violated={path.slack_ns < 0}
						onclick={() => (selectedPath = path)}
					>
						<span class="col-rank">{path.rank}</span>
						<span class="col-slack" style="color: {slackColor(path.slack_ns)}">{path.slack_ns.toFixed(3)}</span>
						<span class="col-start" title={path.start_point}>{path.start_point}</span>
						<span class="col-end" title={path.end_point}>{path.end_point}</span>
						<span class="col-delay">{path.delay_ns.toFixed(3)}</span>
						<span class="col-levels">{path.levels}</span>
						<span class="col-clock">{path.clock}</span>
					</button>
				{/each}
			</div>

		{:else}
			<div class="clocks-table">
				<div class="table-header">
					<span class="col-name">Clock</span>
					<span class="col-period">Period</span>
					<span class="col-freq">Frequency</span>
					<span class="col-wns">WNS</span>
					<span class="col-tns">TNS</span>
					<span class="col-eps">Endpoints</span>
				</div>
				{#each clocks as clk}
					<div class="table-row">
						<span class="col-name">{clk.name}</span>
						<span class="col-period">{clk.period_ns.toFixed(2)} ns</span>
						<span class="col-freq">{clk.frequency_mhz.toFixed(1)} MHz</span>
						<span class="col-wns" style="color: {slackColor(clk.wns_ns)}">{clk.wns_ns.toFixed(3)}</span>
						<span class="col-tns" style="color: {slackColor(clk.tns_ns)}">{clk.tns_ns.toFixed(3)}</span>
						<span class="col-eps">{clk.endpoints}</span>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>

<style>
	.timing-dashboard { display: flex; flex-direction: column; height: 100%; }
	.tabs { display: flex; border-bottom: 1px solid var(--color-border); flex-shrink: 0; }
	.tab { background: none; border: none; color: var(--color-text-secondary); padding: 8px 16px; font-size: 12px; cursor: pointer; border-bottom: 2px solid transparent; }
	.tab.active { color: var(--color-accent); border-bottom-color: var(--color-accent); }
	.content { flex: 1; overflow-y: auto; padding: 12px; }

	.metric-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; }
	.metric-card { background: var(--color-bg-secondary); border: 1px solid var(--color-border); border-radius: 8px; padding: 16px; text-align: center; }
	.metric-card.large { padding: 20px; }
	.metric-label { font-size: 11px; text-transform: uppercase; color: var(--color-text-secondary); margin-bottom: 8px; }
	.metric-value { font-size: 28px; font-weight: 700; margin-bottom: 4px; }
	.metric-status { font-size: 11px; font-weight: 700; letter-spacing: 0.5px; }
	.metric-sub { font-size: 11px; color: var(--color-text-secondary); }

	.section { margin-bottom: 16px; }
	.section-title { font-size: 12px; font-weight: 600; text-transform: uppercase; color: var(--color-text-secondary); margin-bottom: 8px; }

	.histogram { display: flex; gap: 2px; height: 120px; align-items: flex-end; }
	.hist-col { flex: 1; display: flex; flex-direction: column; align-items: center; }
	.hist-bar-container { flex: 1; width: 100%; display: flex; align-items: flex-end; }
	.hist-bar { width: 100%; border-radius: 2px 2px 0 0; min-height: 1px; transition: height 0.3s; }
	.hist-label { font-size: 8px; color: var(--color-text-secondary); margin-top: 2px; }
	.hist-axis-label { text-align: center; font-size: 10px; color: var(--color-text-secondary); margin-top: 4px; }

	.path-controls { margin-bottom: 8px; }
	.path-controls select { background: var(--color-bg-secondary); border: 1px solid var(--color-border); color: var(--color-text-primary); padding: 4px 8px; border-radius: 4px; font-size: 12px; }

	.paths-table, .clocks-table { font-size: 11px; font-family: 'JetBrains Mono', monospace; }
	.table-header { display: flex; gap: 4px; padding: 6px 8px; font-weight: 600; color: var(--color-text-secondary); border-bottom: 1px solid var(--color-border); }
	.table-row { display: flex; gap: 4px; padding: 4px 8px; border: none; background: none; color: var(--color-text-primary); width: 100%; text-align: left; cursor: pointer; }
	.table-row:hover { background: var(--color-bg-secondary); }
	.table-row.selected { background: var(--color-border); }
	.table-row.violated { border-left: 2px solid var(--color-error); }

	.col-rank { width: 30px; } .col-slack { width: 70px; font-weight: 600; } .col-start, .col-end { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.col-delay { width: 60px; } .col-levels { width: 40px; text-align: center; } .col-clock { width: 60px; }
	.col-name { flex: 1; } .col-period { width: 80px; } .col-freq { width: 80px; } .col-wns { width: 70px; } .col-tns { width: 70px; } .col-eps { width: 70px; text-align: right; }
</style>
