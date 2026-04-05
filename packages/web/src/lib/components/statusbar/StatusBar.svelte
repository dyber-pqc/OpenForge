<script lang="ts">
	/**
	 * IDE status bar -- file info, running jobs, PDK, git, tools.
	 */

	import { currentProject, activeFile, toolStatus } from '$lib/stores/project';

	let {
		gitBranch = 'main',
		runningJob = null
	}: {
		gitBranch?: string;
		runningJob?: { name: string; progress?: number } | null;
	} = $props();

	let cursorLine = $state(1);
	let cursorCol = $state(1);
	let notifications = $state(0);

	let filePath = $derived($activeFile?.path ?? 'No file open');
	let language = $derived($activeFile?.language ?? '');
	let pdk = $derived($currentProject?.target_pdk ?? 'SKY130');
	let topModule = $derived($currentProject?.top_module ?? '(none)');
</script>

<footer class="status-bar">
	<!-- Left section: file info -->
	<div class="status-section left">
		<span class="status-item branch" title="Git branch">
			<span class="branch-icon">Y</span>
			{gitBranch}
		</span>
		<span class="status-item" title="Current file">
			{filePath}
		</span>
		{#if $activeFile}
			<span class="status-item dim">
				Ln {cursorLine}, Col {cursorCol}
			</span>
			<span class="status-item dim">
				{language}
			</span>
		{/if}
	</div>

	<!-- Center section: running job -->
	<div class="status-section center">
		{#if runningJob}
			<div class="job-indicator">
				<span class="spinner"></span>
				<span class="job-name">{runningJob.name}</span>
				{#if runningJob.progress !== undefined}
					<span class="job-progress">{runningJob.progress}%</span>
				{/if}
			</div>
		{/if}
	</div>

	<!-- Right section: PDK, tools, notifications -->
	<div class="status-section right">
		<span class="status-item" title="Target PDK">
			<span class="pdk-badge">{pdk}</span>
		</span>
		<span class="status-item dim" title="Top module">
			Top: {topModule}
		</span>

		{#if $toolStatus.length > 0}
			<span class="status-item dim" title="Installed tools">
				{$toolStatus.filter((t) => t.installed).length}/{$toolStatus.length} tools
			</span>
		{/if}

		<button class="status-item notification-btn" title="Notifications">
			<span class="bell-icon">B</span>
			{#if notifications > 0}
				<span class="notification-badge">{notifications}</span>
			{/if}
		</button>
	</div>
</footer>

<style>
	.status-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 12px;
		height: 24px;
		background: var(--color-accent);
		color: var(--color-bg-primary);
		font-size: 11px;
		font-weight: 500;
		flex-shrink: 0;
		gap: 8px;
	}

	.status-section {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.status-section.left {
		flex: 1;
	}

	.status-section.center {
		flex: 0 0 auto;
	}

	.status-section.right {
		flex: 1;
		justify-content: flex-end;
	}

	.status-item {
		display: flex;
		align-items: center;
		gap: 4px;
		white-space: nowrap;
	}

	.status-item.dim {
		opacity: 0.75;
	}

	.branch-icon {
		font-weight: 700;
		font-size: 12px;
	}

	.branch {
		font-weight: 600;
	}

	.pdk-badge {
		background: rgba(0, 0, 0, 0.2);
		padding: 1px 6px;
		border-radius: 3px;
		font-size: 10px;
		font-weight: 600;
	}

	/* Running job */
	.job-indicator {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.spinner {
		width: 10px;
		height: 10px;
		border: 2px solid rgba(0, 0, 0, 0.2);
		border-top-color: var(--color-bg-primary);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	.job-name {
		font-weight: 500;
	}

	.job-progress {
		opacity: 0.75;
	}

	/* Notifications */
	.notification-btn {
		background: none;
		border: none;
		color: inherit;
		cursor: pointer;
		position: relative;
		padding: 0;
		font: inherit;
	}

	.bell-icon {
		font-weight: 700;
		font-size: 12px;
	}

	.notification-badge {
		position: absolute;
		top: -4px;
		right: -6px;
		background: var(--color-error);
		color: white;
		font-size: 8px;
		font-weight: 700;
		width: 12px;
		height: 12px;
		border-radius: 50%;
		display: flex;
		align-items: center;
		justify-content: center;
	}
</style>
