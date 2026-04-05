<script lang="ts">
	/**
	 * Main toolbar with action buttons, dropdown menus, and keyboard shortcut hints.
	 */

	import { appendConsole } from '$lib/stores/project';

	let activeDropdown = $state<string | null>(null);

	interface ToolbarAction {
		label: string;
		shortcut?: string;
		action: () => void;
		accent?: boolean;
		separator?: boolean;
	}

	const fileActions: ToolbarAction[] = [
		{ label: 'New Project', shortcut: 'Ctrl+Shift+N', action: () => dispatch('newProject') },
		{ label: 'Open Project', shortcut: 'Ctrl+O', action: () => dispatch('openProject') },
		{ label: 'Save', shortcut: 'Ctrl+S', action: () => dispatch('save') },
		{ label: 'Save All', shortcut: 'Ctrl+Shift+S', action: () => dispatch('saveAll') },
		{ separator: true, label: '', action: () => {} },
		{ label: 'Import Files...', action: () => dispatch('import') },
		{ label: 'Export Results...', action: () => dispatch('export') },
	];

	const simulateActions: ToolbarAction[] = [
		{ label: 'Run Simulation', shortcut: 'F5', action: () => handleSimulate() },
		{ label: 'Run Testbench', shortcut: 'Ctrl+F5', action: () => handleSimulate() },
		{ separator: true, label: '', action: () => {} },
		{ label: 'View Waveforms', action: () => {} },
		{ label: 'Simulation Settings...', action: () => {} },
	];

	const synthActions: ToolbarAction[] = [
		{ label: 'Run Synthesis', shortcut: 'F6', action: () => handleSynthesize() },
		{ label: 'Run Place & Route', shortcut: 'F7', action: () => {} },
		{ separator: true, label: '', action: () => {} },
		{ label: 'Timing Analysis', action: () => {} },
		{ label: 'Power Analysis', action: () => {} },
		{ label: 'Synthesis Settings...', action: () => {} },
	];

	const verifyActions: ToolbarAction[] = [
		{ label: 'Run All Checks', shortcut: 'F8', action: () => handleVerify() },
		{ label: 'Formal Verification', action: () => {} },
		{ label: 'Security Analysis', action: () => {} },
		{ separator: true, label: '', action: () => {} },
		{ label: 'Coverage Report', action: () => {} },
		{ label: 'Verification Settings...', action: () => {} },
	];

	function dispatch(event: string) {
		appendConsole(`Action: ${event}`, 'info');
	}

	function handleSimulate() {
		appendConsole('Starting simulation...', 'info');
		appendConsole('Simulation engine not yet connected to backend.', 'warning');
	}

	function handleSynthesize() {
		appendConsole('Starting synthesis...', 'info');
		appendConsole('Synthesis engine not yet connected to backend.', 'warning');
	}

	function handleVerify() {
		appendConsole('Starting full verification...', 'info');
		appendConsole('Verification flow not yet connected to backend.', 'warning');
	}

	function toggleDropdown(name: string) {
		activeDropdown = activeDropdown === name ? null : name;
	}

	function closeDropdowns() {
		activeDropdown = null;
	}

	function executeAction(action: ToolbarAction) {
		action.action();
		closeDropdowns();
	}
</script>

<svelte:window onclick={closeDropdowns} />

<div class="toolbar">
	<!-- File Group -->
	<div class="toolbar-group">
		<div class="dropdown-container">
			<button
				class="tool-btn"
				title="New Project (Ctrl+Shift+N)"
				onclick={(e) => { e.stopPropagation(); toggleDropdown('file'); }}
			>
				<span class="btn-icon">+</span>
				<span class="btn-label">New</span>
			</button>
			{#if activeDropdown === 'file'}
				<div class="dropdown-menu" onclick={(e) => e.stopPropagation()}>
					{#each fileActions as item}
						{#if item.separator}
							<div class="dropdown-divider"></div>
						{:else}
							<button class="dropdown-item" onclick={() => executeAction(item)}>
								<span class="item-label">{item.label}</span>
								{#if item.shortcut}
									<span class="item-shortcut">{item.shortcut}</span>
								{/if}
							</button>
						{/if}
					{/each}
				</div>
			{/if}
		</div>

		<button class="tool-btn" title="Open Project (Ctrl+O)" onclick={() => dispatch('openProject')}>
			<span class="btn-icon">O</span>
			<span class="btn-label">Open</span>
		</button>

		<button class="tool-btn" title="Save (Ctrl+S)" onclick={() => dispatch('save')}>
			<span class="btn-icon">S</span>
			<span class="btn-label">Save</span>
		</button>
	</div>

	<span class="toolbar-separator"></span>

	<!-- Simulation Group -->
	<div class="toolbar-group">
		<div class="dropdown-container">
			<button
				class="tool-btn accent"
				title="Run Simulation (F5)"
				onclick={(e) => { e.stopPropagation(); toggleDropdown('simulate'); }}
			>
				<span class="btn-icon play">&#9654;</span>
				<span class="btn-label">Simulate</span>
			</button>
			{#if activeDropdown === 'simulate'}
				<div class="dropdown-menu" onclick={(e) => e.stopPropagation()}>
					{#each simulateActions as item}
						{#if item.separator}
							<div class="dropdown-divider"></div>
						{:else}
							<button class="dropdown-item" onclick={() => executeAction(item)}>
								<span class="item-label">{item.label}</span>
								{#if item.shortcut}
									<span class="item-shortcut">{item.shortcut}</span>
								{/if}
							</button>
						{/if}
					{/each}
				</div>
			{/if}
		</div>

		<div class="dropdown-container">
			<button
				class="tool-btn accent"
				title="Run Synthesis (F6)"
				onclick={(e) => { e.stopPropagation(); toggleDropdown('synth'); }}
			>
				<span class="btn-icon">&#9881;</span>
				<span class="btn-label">Synth</span>
			</button>
			{#if activeDropdown === 'synth'}
				<div class="dropdown-menu" onclick={(e) => e.stopPropagation()}>
					{#each synthActions as item}
						{#if item.separator}
							<div class="dropdown-divider"></div>
						{:else}
							<button class="dropdown-item" onclick={() => executeAction(item)}>
								<span class="item-label">{item.label}</span>
								{#if item.shortcut}
									<span class="item-shortcut">{item.shortcut}</span>
								{/if}
							</button>
						{/if}
					{/each}
				</div>
			{/if}
		</div>

		<div class="dropdown-container">
			<button
				class="tool-btn accent"
				title="Run Verification (F8)"
				onclick={(e) => { e.stopPropagation(); toggleDropdown('verify'); }}
			>
				<span class="btn-icon">&#10003;</span>
				<span class="btn-label">Verify</span>
			</button>
			{#if activeDropdown === 'verify'}
				<div class="dropdown-menu" onclick={(e) => e.stopPropagation()}>
					{#each verifyActions as item}
						{#if item.separator}
							<div class="dropdown-divider"></div>
						{:else}
							<button class="dropdown-item" onclick={() => executeAction(item)}>
								<span class="item-label">{item.label}</span>
								{#if item.shortcut}
									<span class="item-shortcut">{item.shortcut}</span>
								{/if}
							</button>
						{/if}
					{/each}
				</div>
			{/if}
		</div>
	</div>

	<span class="toolbar-separator"></span>

	<!-- View Group -->
	<div class="toolbar-group">
		<button class="tool-btn" title="Zoom In (Ctrl+=)">
			<span class="btn-icon">+</span>
		</button>
		<button class="tool-btn" title="Zoom Out (Ctrl+-)">
			<span class="btn-icon">-</span>
		</button>
		<button class="tool-btn" title="Search (Ctrl+Shift+F)">
			<span class="btn-icon">Q</span>
		</button>
	</div>
</div>

<style>
	.toolbar {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 0 8px;
		height: 100%;
	}

	.toolbar-group {
		display: flex;
		align-items: center;
		gap: 2px;
	}

	.toolbar-separator {
		width: 1px;
		height: 20px;
		background: var(--color-border);
		margin: 0 6px;
		flex-shrink: 0;
	}

	.tool-btn {
		display: flex;
		align-items: center;
		gap: 4px;
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		color: var(--color-text-secondary);
		padding: 3px 10px;
		font-size: 12px;
		cursor: pointer;
		border-radius: 4px;
		white-space: nowrap;
		height: 28px;
	}

	.tool-btn.accent {
		border-color: var(--color-accent);
		color: var(--color-accent);
	}

	.tool-btn:hover {
		background: var(--color-border);
		color: var(--color-text-primary);
	}

	.btn-icon {
		font-size: 11px;
		font-weight: 700;
		width: 14px;
		text-align: center;
	}

	.btn-icon.play {
		color: var(--color-success);
		font-size: 10px;
	}

	.btn-label {
		font-size: 12px;
	}

	/* Dropdown */
	.dropdown-container {
		position: relative;
	}

	.dropdown-menu {
		position: absolute;
		top: 100%;
		left: 0;
		margin-top: 4px;
		min-width: 220px;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 6px;
		padding: 4px 0;
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
		z-index: 100;
	}

	.dropdown-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		width: 100%;
		background: none;
		border: none;
		color: var(--color-text-primary);
		padding: 6px 16px;
		font-size: 12px;
		cursor: pointer;
		text-align: left;
	}

	.dropdown-item:hover {
		background: var(--color-accent);
		color: var(--color-bg-primary);
	}

	.dropdown-item:hover .item-shortcut {
		color: var(--color-bg-primary);
		opacity: 0.7;
	}

	.item-shortcut {
		color: var(--color-text-secondary);
		font-size: 11px;
		opacity: 0.6;
		margin-left: 24px;
	}

	.dropdown-divider {
		height: 1px;
		background: var(--color-border);
		margin: 4px 0;
	}
</style>
