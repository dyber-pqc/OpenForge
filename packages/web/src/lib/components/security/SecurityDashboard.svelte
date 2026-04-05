<script lang="ts">
	/**
	 * Security analysis dashboard -- Dyber's crypto verification suite visualization.
	 * Shows side-channel, constant-time, entropy, and FIPS compliance results.
	 */

	interface SecurityScore {
		category: string;
		score: number; // 0-100
		status: 'pass' | 'fail' | 'warn' | 'pending';
		findings: number;
		details: string;
	}

	let {
		scores = [],
		overallScore = null
	}: {
		scores: SecurityScore[];
		overallScore: number | null;
	} = $props();

	function statusColor(status: string): string {
		switch (status) {
			case 'pass': return 'var(--color-success)';
			case 'fail': return 'var(--color-error)';
			case 'warn': return 'var(--color-warning)';
			default: return 'var(--color-text-secondary)';
		}
	}

	function scoreColor(score: number): string {
		if (score >= 80) return 'var(--color-success)';
		if (score >= 60) return 'var(--color-warning)';
		return 'var(--color-error)';
	}

	const defaultScores: SecurityScore[] = [
		{ category: 'Constant-Time', score: 0, status: 'pending', findings: 0, details: 'Run CT analysis to check timing independence' },
		{ category: 'Power SCA', score: 0, status: 'pending', findings: 0, details: 'Run TVLA to detect power leakage' },
		{ category: 'Fault Injection', score: 0, status: 'pending', findings: 0, details: 'Run fault simulation to test resilience' },
		{ category: 'Entropy Flow', score: 0, status: 'pending', findings: 0, details: 'Verify entropy source to sink paths' },
		{ category: 'FIPS 140-3', score: 0, status: 'pending', findings: 0, details: 'Check FIPS compliance requirements' },
		{ category: 'Key Handling', score: 0, status: 'pending', findings: 0, details: 'Verify key zeroization and isolation' },
	];

	let displayScores = $derived(scores.length > 0 ? scores : defaultScores);
</script>

<div class="security-dashboard">
	<!-- Overall Score -->
	<div class="overall-score">
		<div class="score-ring">
			<svg viewBox="0 0 100 100">
				<circle cx="50" cy="50" r="42" fill="none" stroke="var(--color-border)" stroke-width="6" />
				{#if overallScore !== null}
					<circle
						cx="50" cy="50" r="42"
						fill="none"
						stroke={scoreColor(overallScore)}
						stroke-width="6"
						stroke-dasharray={`${overallScore * 2.64} 264`}
						stroke-linecap="round"
						transform="rotate(-90 50 50)"
					/>
				{/if}
			</svg>
			<div class="score-text">
				{#if overallScore !== null}
					<span class="score-number" style="color: {scoreColor(overallScore)}">{overallScore}</span>
				{:else}
					<span class="score-number pending">--</span>
				{/if}
				<span class="score-label">Security</span>
			</div>
		</div>
	</div>

	<!-- Category Cards -->
	<div class="category-grid">
		{#each displayScores as cat}
			<div class="category-card">
				<div class="card-header">
					<span class="card-title">{cat.category}</span>
					<span class="card-status" style="color: {statusColor(cat.status)}">
						{cat.status.toUpperCase()}
					</span>
				</div>
				<div class="card-bar">
					<div
						class="card-fill"
						style="width: {cat.score}%; background: {statusColor(cat.status)}"
					></div>
				</div>
				<div class="card-details">
					<span class="card-score">{cat.score > 0 ? `${cat.score}/100` : '--'}</span>
					{#if cat.findings > 0}
						<span class="card-findings" style="color: var(--color-error)">
							{cat.findings} finding{cat.findings !== 1 ? 's' : ''}
						</span>
					{/if}
				</div>
				<p class="card-desc">{cat.details}</p>
			</div>
		{/each}
	</div>
</div>

<style>
	.security-dashboard {
		padding: 12px;
		display: flex;
		flex-direction: column;
		gap: 16px;
		height: 100%;
		overflow-y: auto;
	}

	.overall-score {
		display: flex;
		justify-content: center;
		padding: 8px;
	}

	.score-ring {
		position: relative;
		width: 100px;
		height: 100px;
	}

	.score-ring svg {
		width: 100%;
		height: 100%;
	}

	.score-text {
		position: absolute;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		text-align: center;
	}

	.score-number {
		font-size: 24px;
		font-weight: 700;
		display: block;
		line-height: 1;
	}

	.score-number.pending {
		color: var(--color-text-secondary);
	}

	.score-label {
		font-size: 10px;
		color: var(--color-text-secondary);
		text-transform: uppercase;
	}

	.category-grid {
		display: grid;
		grid-template-columns: 1fr;
		gap: 8px;
	}

	.category-card {
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 6px;
		padding: 10px;
	}

	.card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 6px;
	}

	.card-title {
		font-size: 12px;
		font-weight: 600;
		color: var(--color-text-primary);
	}

	.card-status {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.5px;
	}

	.card-bar {
		height: 3px;
		background: var(--color-border);
		border-radius: 2px;
		overflow: hidden;
		margin-bottom: 6px;
	}

	.card-fill {
		height: 100%;
		border-radius: 2px;
		transition: width 0.3s;
	}

	.card-details {
		display: flex;
		justify-content: space-between;
		font-size: 11px;
		margin-bottom: 4px;
	}

	.card-score {
		color: var(--color-text-secondary);
	}

	.card-desc {
		font-size: 10px;
		color: var(--color-text-secondary);
		opacity: 0.7;
		margin: 0;
	}
</style>
