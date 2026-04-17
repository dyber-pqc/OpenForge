<script lang="ts">
	/**
	 * Verification page -- test runner, formal verification, coverage, security.
	 */

	import CoverageView from '$lib/components/reports/CoverageView.svelte';
	import SecurityDashboard from '$lib/components/security/SecurityDashboard.svelte';
	import { appendConsole, runningJob, verificationJobs } from '$lib/stores/project';
	import type { VerificationJob } from '$lib/api/client';

	let activeTab = $state<'tests' | 'formal' | 'coverage' | 'security'>('tests');
	let isRunning = $state(false);

	// Demo test data
	interface TestCase {
		name: string;
		module: string;
		status: 'pass' | 'fail' | 'running' | 'pending';
		duration_ms: number | null;
		assertions: number;
		failures: number;
	}

	let tests = $state<TestCase[]>([
		{ name: 'tb_ntt_butterfly_basic', module: 'ntt_butterfly', status: 'pass', duration_ms: 234, assertions: 48, failures: 0 },
		{ name: 'tb_ntt_butterfly_edge', module: 'ntt_butterfly', status: 'pass', duration_ms: 567, assertions: 32, failures: 0 },
		{ name: 'tb_keccak_permute', module: 'keccak_core', status: 'pass', duration_ms: 1200, assertions: 100, failures: 0 },
		{ name: 'tb_keccak_squeeze', module: 'keccak_core', status: 'fail', duration_ms: 890, assertions: 64, failures: 2 },
		{ name: 'tb_axi_read', module: 'axi_slave', status: 'pass', duration_ms: 345, assertions: 24, failures: 0 },
		{ name: 'tb_axi_write', module: 'axi_slave', status: 'pass', duration_ms: 412, assertions: 36, failures: 0 },
		{ name: 'tb_key_manager_zeroize', module: 'key_manager', status: 'pending', duration_ms: null, assertions: 0, failures: 0 },
		{ name: 'tb_top_integration', module: 'kyber_top', status: 'pending', duration_ms: null, assertions: 0, failures: 0 },
	]);

	// Formal verification properties
	interface FormalProperty {
		name: string;
		type: 'assert' | 'assume' | 'cover';
		status: 'proven' | 'failed' | 'bounded' | 'pending';
		engine: string;
		depth: number | null;
	}

	let formalProps = $state<FormalProperty[]>([
		{ name: 'no_key_leak', type: 'assert', status: 'proven', engine: 'sby', depth: null },
		{ name: 'axi_handshake', type: 'assert', status: 'proven', engine: 'sby', depth: null },
		{ name: 'ntt_correct', type: 'assert', status: 'bounded', engine: 'bmc', depth: 20 },
		{ name: 'keccak_absorb_ready', type: 'assert', status: 'proven', engine: 'sby', depth: null },
		{ name: 'zeroize_complete', type: 'assert', status: 'pending', engine: '', depth: null },
		{ name: 'entropy_flow', type: 'cover', status: 'proven', engine: 'sby', depth: null },
		{ name: 'full_round', type: 'cover', status: 'bounded', engine: 'bmc', depth: 50 },
	]);

	let passingTests = $derived(tests.filter((t) => t.status === 'pass').length);
	let failingTests = $derived(tests.filter((t) => t.status === 'fail').length);
	let pendingTests = $derived(tests.filter((t) => t.status === 'pending').length);

	function statusColor(status: string): string {
		switch (status) {
			case 'pass': case 'proven': return 'var(--color-success)';
			case 'fail': case 'failed': return 'var(--color-error)';
			case 'running': return 'var(--color-accent)';
			case 'bounded': return 'var(--color-warning)';
			default: return 'var(--color-text-secondary)';
		}
	}

	function statusIcon(status: string): string {
		switch (status) {
			case 'pass': case 'proven': return '\u2713';
			case 'fail': case 'failed': return '\u2717';
			case 'running': return '...';
			case 'bounded': return '~';
			default: return '\u25CB';
		}
	}

	function runAllTests() {
		isRunning = true;
		appendConsole('Running all testbenches...', 'info');
		runningJob.set({ name: 'Test Runner', progress: 0 });

		let idx = 0;
		const interval = setInterval(() => {
			if (idx < tests.length) {
				const test = tests[idx];
				if (test.status === 'pending') {
					tests[idx] = { ...test, status: 'pass', duration_ms: Math.floor(Math.random() * 1000) + 200, assertions: Math.floor(Math.random() * 40) + 10, failures: 0 };
					appendConsole(`PASS: ${test.name} (${tests[idx].duration_ms}ms)`, 'success');
				}
				runningJob.set({ name: 'Test Runner', progress: Math.floor(((idx + 1) / tests.length) * 100) });
				idx++;
			} else {
				clearInterval(interval);
				isRunning = false;
				runningJob.set(null);
				appendConsole(`Test run complete: ${passingTests + pendingTests} passed, ${failingTests} failed`, failingTests > 0 ? 'warning' : 'success');
			}
		}, 600);
	}
</script>

<svelte:head>
	<title>Verification - OpenForge EDA</title>
</svelte:head>

<div class="verification-page">
	<!-- Tab Bar -->
	<div class="tab-bar">
		{#each [['tests', 'Test Runner'], ['formal', 'Formal Verification'], ['coverage', 'Coverage'], ['security', 'Security']] as [key, label]}
			<button
				class="tab"
				class:active={activeTab === key}
				onclick={() => (activeTab = key as typeof activeTab)}
			>
				{label}
			</button>
		{/each}
		<div class="tab-spacer"></div>
		<button
			class="run-all-btn"
			onclick={runAllTests}
			disabled={isRunning}
		>
			{#if isRunning}
				<span class="btn-spinner"></span>
				Running...
			{:else}
				<span class="btn-play">&#9654;</span>
				Run All
			{/if}
		</button>
	</div>

	<!-- Content -->
	<div class="tab-content">
		{#if activeTab === 'tests'}
			<div class="test-runner">
				<!-- Summary bar -->
				<div class="test-summary">
					<div class="summary-stat">
						<span class="stat-value" style="color: var(--color-success)">{passingTests}</span>
						<span class="stat-label">Passing</span>
					</div>
					<div class="summary-stat">
						<span class="stat-value" style="color: var(--color-error)">{failingTests}</span>
						<span class="stat-label">Failing</span>
					</div>
					<div class="summary-stat">
						<span class="stat-value" style="color: var(--color-text-secondary)">{pendingTests}</span>
						<span class="stat-label">Pending</span>
					</div>
					<div class="summary-stat">
						<span class="stat-value">{tests.length}</span>
						<span class="stat-label">Total</span>
					</div>
				</div>

				<!-- Test list -->
				<div class="test-table">
					<div class="table-header">
						<span class="col-status">Status</span>
						<span class="col-name">Test Name</span>
						<span class="col-module">Module</span>
						<span class="col-assertions">Assertions</span>
						<span class="col-duration">Duration</span>
					</div>
					{#each tests as test}
						<div class="table-row" class:failed={test.status === 'fail'}>
							<span class="col-status">
								<span class="status-icon" style="color: {statusColor(test.status)}">{statusIcon(test.status)}</span>
							</span>
							<span class="col-name">{test.name}</span>
							<span class="col-module">{test.module}</span>
							<span class="col-assertions">
								{#if test.failures > 0}
									<span style="color: var(--color-error)">{test.failures} fail</span> / {test.assertions}
								{:else if test.assertions > 0}
									{test.assertions}
								{:else}
									--
								{/if}
							</span>
							<span class="col-duration">
								{test.duration_ms !== null ? `${test.duration_ms}ms` : '--'}
							</span>
						</div>
					{/each}
				</div>
			</div>

		{:else if activeTab === 'formal'}
			<div class="formal-section">
				<div class="formal-summary">
					<div class="summary-stat">
						<span class="stat-value" style="color: var(--color-success)">{formalProps.filter(p => p.status === 'proven').length}</span>
						<span class="stat-label">Proven</span>
					</div>
					<div class="summary-stat">
						<span class="stat-value" style="color: var(--color-warning)">{formalProps.filter(p => p.status === 'bounded').length}</span>
						<span class="stat-label">Bounded</span>
					</div>
					<div class="summary-stat">
						<span class="stat-value" style="color: var(--color-error)">{formalProps.filter(p => p.status === 'failed').length}</span>
						<span class="stat-label">Failed</span>
					</div>
					<div class="summary-stat">
						<span class="stat-value" style="color: var(--color-text-secondary)">{formalProps.filter(p => p.status === 'pending').length}</span>
						<span class="stat-label">Pending</span>
					</div>
				</div>

				<div class="formal-table">
					<div class="table-header">
						<span class="col-status">Status</span>
						<span class="col-name">Property</span>
						<span class="col-type">Type</span>
						<span class="col-engine">Engine</span>
						<span class="col-depth">Depth</span>
					</div>
					{#each formalProps as prop}
						<div class="table-row">
							<span class="col-status">
								<span class="status-icon" style="color: {statusColor(prop.status)}">{statusIcon(prop.status)}</span>
							</span>
							<span class="col-name">{prop.name}</span>
							<span class="col-type">
								<span class="type-badge" class:assert={prop.type === 'assert'} class:cover={prop.type === 'cover'}>
									{prop.type}
								</span>
							</span>
							<span class="col-engine">{prop.engine || '--'}</span>
							<span class="col-depth">{prop.depth !== null ? prop.depth : '--'}</span>
						</div>
					{/each}
				</div>
			</div>

		{:else if activeTab === 'coverage'}
			<CoverageView lineCoverage={[]} toggleCoverage={[]} fsmCoverage={[]} summaryPct={null} />

		{:else if activeTab === 'security'}
			<SecurityDashboard scores={[]} overallScore={null} />
		{/if}
	</div>
</div>

<style>
	.verification-page {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: var(--color-bg-primary);
	}

	/* Tab Bar */
	.tab-bar {
		display: flex;
		align-items: center;
		background: var(--color-bg-secondary);
		border-bottom: 1px solid var(--color-border);
		padding: 0 12px;
		flex-shrink: 0;
	}

	.tab {
		background: none;
		border: none;
		color: var(--color-text-secondary);
		padding: 10px 16px;
		font-size: 13px;
		cursor: pointer;
		border-bottom: 2px solid transparent;
		font-weight: 500;
	}

	.tab:hover {
		color: var(--color-text-primary);
	}

	.tab.active {
		color: var(--color-accent);
		border-bottom-color: var(--color-accent);
	}

	.tab-spacer {
		flex: 1;
	}

	.run-all-btn {
		display: flex;
		align-items: center;
		gap: 6px;
		background: var(--color-accent);
		color: var(--color-bg-primary);
		border: none;
		border-radius: 4px;
		padding: 6px 14px;
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
	}

	.run-all-btn:hover:not(:disabled) {
		opacity: 0.9;
	}

	.run-all-btn:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.btn-play {
		font-size: 10px;
	}

	.btn-spinner {
		width: 12px;
		height: 12px;
		border: 2px solid rgba(0, 0, 0, 0.2);
		border-top-color: var(--color-bg-primary);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	/* Content */
	.tab-content {
		flex: 1;
		overflow: hidden;
	}

	/* Test Runner */
	.test-runner, .formal-section {
		display: flex;
		flex-direction: column;
		height: 100%;
	}

	.test-summary, .formal-summary {
		display: flex;
		gap: 24px;
		padding: 16px 20px;
		border-bottom: 1px solid var(--color-border);
		background: var(--color-bg-secondary);
	}

	.summary-stat {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
	}

	.stat-value {
		font-size: 22px;
		font-weight: 700;
		color: var(--color-text-primary);
	}

	.stat-label {
		font-size: 10px;
		text-transform: uppercase;
		color: var(--color-text-secondary);
		letter-spacing: 0.3px;
	}

	/* Tables */
	.test-table, .formal-table {
		flex: 1;
		overflow-y: auto;
		font-size: 12px;
		font-family: 'JetBrains Mono', monospace;
	}

	.table-header {
		display: flex;
		gap: 4px;
		padding: 8px 16px;
		font-weight: 600;
		color: var(--color-text-secondary);
		font-size: 11px;
		border-bottom: 1px solid var(--color-border);
		position: sticky;
		top: 0;
		background: var(--color-bg-primary);
		z-index: 1;
	}

	.table-row {
		display: flex;
		gap: 4px;
		padding: 6px 16px;
		color: var(--color-text-primary);
		border-bottom: 1px solid rgba(61, 61, 92, 0.3);
	}

	.table-row:hover {
		background: rgba(255, 255, 255, 0.02);
	}

	.table-row.failed {
		background: rgba(247, 118, 142, 0.05);
		border-left: 2px solid var(--color-error);
	}

	.col-status { width: 50px; text-align: center; }
	.col-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.col-module { width: 120px; color: var(--color-text-secondary); }
	.col-assertions { width: 100px; }
	.col-duration { width: 80px; text-align: right; color: var(--color-text-secondary); }
	.col-type { width: 80px; }
	.col-engine { width: 80px; color: var(--color-text-secondary); }
	.col-depth { width: 60px; text-align: right; color: var(--color-text-secondary); }

	.status-icon {
		font-weight: 700;
		font-size: 13px;
	}

	.type-badge {
		font-size: 10px;
		font-weight: 600;
		padding: 1px 6px;
		border-radius: 3px;
		background: var(--color-bg-secondary);
		color: var(--color-text-secondary);
	}

	.type-badge.assert {
		color: var(--color-accent);
		background: rgba(122, 162, 247, 0.1);
	}

	.type-badge.cover {
		color: var(--color-success);
		background: rgba(158, 206, 106, 0.1);
	}
</style>
