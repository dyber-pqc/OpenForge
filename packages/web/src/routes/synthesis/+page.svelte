<script lang="ts">
	/**
	 * Synthesis page -- run synthesis, configure options, view results.
	 */

	import SynthesisDashboard from '$lib/components/synthesis/SynthesisDashboard.svelte';
	import { currentProject, appendConsole, runningJob } from '$lib/stores/project';

	let targetPDK = $state($currentProject ? undefined : 'SKY130');
	let optimization = $state<'speed' | 'area' | 'balanced'>('balanced');
	let flatten = $state(false);
	let clockPeriod = $state('10.0');
	let effort = $state<'low' | 'medium' | 'high'>('medium');

	let synthResult = $state<any>(null);
	let isRunning = $state(false);

	$effect(() => {
		if ($currentProject) {
			targetPDK = $currentProject.target_pdk;
		}
	});

	function runSynthesis() {
		isRunning = true;
		appendConsole('Starting synthesis flow...', 'info');
		appendConsole(`Target PDK: ${targetPDK}`, 'info');
		appendConsole(`Optimization: ${optimization}`, 'info');
		appendConsole(`Clock period: ${clockPeriod} ns`, 'info');
		runningJob.set({ name: 'Synthesis', progress: 0 });

		// Simulate progress
		let progress = 0;
		const stages = ['Reading design...', 'Elaborating...', 'Optimizing logic...', 'Technology mapping...', 'Writing results...'];
		const interval = setInterval(() => {
			progress += 20;
			const stageIdx = Math.min(Math.floor(progress / 20), stages.length - 1);
			appendConsole(stages[stageIdx], 'info');
			runningJob.set({ name: 'Synthesis', progress });

			if (progress >= 100) {
				clearInterval(interval);
				isRunning = false;
				runningJob.set(null);
				appendConsole('Synthesis completed successfully.', 'success');

				synthResult = {
					gate_count: 12847,
					ff_count: 1024,
					lut_count: 0,
					area_um2: 245000,
					wns_ns: 0.342,
					tns_ns: 0.0,
					cell_usage: [
						{ type: 'sky130_fd_sc_hd__nand2_1', count: 2341, area: 8.3 },
						{ type: 'sky130_fd_sc_hd__nor2_1', count: 1892, area: 8.3 },
						{ type: 'sky130_fd_sc_hd__inv_1', count: 1456, area: 5.0 },
						{ type: 'sky130_fd_sc_hd__dfxtp_1', count: 1024, area: 26.3 },
						{ type: 'sky130_fd_sc_hd__and2_1', count: 876, area: 8.3 },
						{ type: 'sky130_fd_sc_hd__or2_1', count: 654, area: 8.3 },
						{ type: 'sky130_fd_sc_hd__xor2_1', count: 543, area: 16.6 },
						{ type: 'sky130_fd_sc_hd__mux2_1', count: 421, area: 16.6 },
						{ type: 'sky130_fd_sc_hd__buf_1', count: 312, area: 5.0 },
						{ type: 'sky130_fd_sc_hd__a21oi_1', count: 234, area: 8.3 },
					],
					duration_s: 12.4,
					warnings: 3,
					errors: 0,
					status: 'passed',
					current_stage: 'Write',
				};
			}
		}, 800);
	}
</script>

<svelte:head>
	<title>Synthesis - OpenForge EDA</title>
</svelte:head>

<div class="synthesis-page">
	<div class="page-layout">
		<!-- Configuration Panel -->
		<aside class="config-panel">
			<div class="config-header">
				<h2 class="config-title">Synthesis Configuration</h2>
			</div>

			<div class="config-body">
				<div class="config-section">
					<h3 class="section-label">Target</h3>
					<div class="form-group">
						<label class="form-label">PDK</label>
						<select bind:value={targetPDK} class="form-select">
							<option value="SKY130">SkyWater SKY130</option>
							<option value="GF180">GlobalFoundries GF180MCU</option>
							<option value="ASAP7">ASAP7</option>
							<option value="NANGATE45">NanGate 45nm</option>
						</select>
					</div>
					<div class="form-group">
						<label class="form-label">Clock Period (ns)</label>
						<input type="text" bind:value={clockPeriod} class="form-input" />
					</div>
				</div>

				<div class="config-section">
					<h3 class="section-label">Optimization</h3>
					<div class="form-group">
						<label class="form-label">Strategy</label>
						<div class="radio-group">
							{#each [['speed', 'Speed'], ['area', 'Area'], ['balanced', 'Balanced']] as [val, label]}
								<label class="radio-label">
									<input type="radio" bind:group={optimization} value={val} />
									<span>{label}</span>
								</label>
							{/each}
						</div>
					</div>
					<div class="form-group">
						<label class="form-label">Effort</label>
						<select bind:value={effort} class="form-select">
							<option value="low">Low (fast)</option>
							<option value="medium">Medium</option>
							<option value="high">High (slow)</option>
						</select>
					</div>
				</div>

				<div class="config-section">
					<h3 class="section-label">Options</h3>
					<label class="checkbox-label">
						<input type="checkbox" bind:checked={flatten} />
						<span>Flatten hierarchy</span>
					</label>
				</div>

				<div class="config-actions">
					<button
						class="run-btn"
						onclick={runSynthesis}
						disabled={isRunning}
					>
						{#if isRunning}
							<span class="run-spinner"></span>
							Running...
						{:else}
							<span class="play-icon">&#9654;</span>
							Run Synthesis
						{/if}
					</button>
				</div>
			</div>
		</aside>

		<!-- Results Area -->
		<main class="results-area">
			<SynthesisDashboard result={synthResult} />
		</main>
	</div>
</div>

<style>
	.synthesis-page {
		height: 100%;
		overflow: hidden;
		background: var(--color-bg-primary);
	}

	.page-layout {
		display: flex;
		height: 100%;
	}

	/* Config Panel */
	.config-panel {
		width: 300px;
		background: var(--color-bg-secondary);
		border-right: 1px solid var(--color-border);
		display: flex;
		flex-direction: column;
		flex-shrink: 0;
		overflow-y: auto;
	}

	.config-header {
		padding: 16px;
		border-bottom: 1px solid var(--color-border);
	}

	.config-title {
		font-size: 14px;
		font-weight: 600;
		margin: 0;
		color: var(--color-text-primary);
	}

	.config-body {
		padding: 16px;
		display: flex;
		flex-direction: column;
		gap: 20px;
	}

	.config-section {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.section-label {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: var(--color-text-secondary);
		margin: 0;
		padding-bottom: 4px;
		border-bottom: 1px solid var(--color-border);
	}

	.form-group {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.form-label {
		font-size: 12px;
		color: var(--color-text-secondary);
	}

	.form-input, .form-select {
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		color: var(--color-text-primary);
		padding: 6px 10px;
		border-radius: 4px;
		font-size: 12px;
		outline: none;
	}

	.form-input:focus, .form-select:focus {
		border-color: var(--color-accent);
	}

	.radio-group {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.radio-label {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 12px;
		color: var(--color-text-primary);
		cursor: pointer;
	}

	.radio-label input {
		accent-color: var(--color-accent);
	}

	.checkbox-label {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 12px;
		color: var(--color-text-primary);
		cursor: pointer;
	}

	.checkbox-label input {
		accent-color: var(--color-accent);
	}

	.config-actions {
		padding-top: 8px;
	}

	.run-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		width: 100%;
		padding: 10px;
		background: var(--color-accent);
		color: var(--color-bg-primary);
		border: none;
		border-radius: 6px;
		font-size: 13px;
		font-weight: 600;
		cursor: pointer;
	}

	.run-btn:hover:not(:disabled) {
		opacity: 0.9;
	}

	.run-btn:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.play-icon {
		font-size: 11px;
	}

	.run-spinner {
		width: 14px;
		height: 14px;
		border: 2px solid rgba(0, 0, 0, 0.2);
		border-top-color: var(--color-bg-primary);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	/* Results */
	.results-area {
		flex: 1;
		overflow: hidden;
	}
</style>
