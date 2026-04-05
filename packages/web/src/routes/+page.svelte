<script lang="ts">
	import Editor from '$lib/components/editor/Editor.svelte';
	import Console from '$lib/components/console/Console.svelte';
	import Hierarchy from '$lib/components/hierarchy/Hierarchy.svelte';
	import {
		currentProject,
		leftSidebarOpen,
		rightSidebarOpen,
		bottomPanelOpen,
		bottomPanelTab,
		appendConsole
	} from '$lib/stores/project';

	let projectName = $derived($currentProject?.name ?? 'OpenForge EDA');

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
</script>

<svelte:head>
	<title>{projectName}</title>
</svelte:head>

<div class="ide-layout">
	<!-- Top Bar -->
	<header class="top-bar">
		<div class="logo">
			<span class="logo-text">OpenForge</span>
			<span class="logo-badge">EDA</span>
		</div>
		<nav class="menu-bar">
			<button class="menu-item">File</button>
			<button class="menu-item">Edit</button>
			<button class="menu-item">View</button>
			<button class="menu-item">Project</button>
			<button class="menu-item">Verify</button>
			<button class="menu-item">Synthesize</button>
			<button class="menu-item">Analyze</button>
			<button class="menu-item">Tools</button>
			<button class="menu-item">Help</button>
		</nav>
		<div class="toolbar">
			<button class="tool-btn" title="New Project">New</button>
			<button class="tool-btn" title="Open Project">Open</button>
			<span class="separator"></span>
			<button class="tool-btn accent" title="Run Simulation" onclick={handleSimulate}>Simulate</button>
			<button class="tool-btn accent" title="Synthesize" onclick={handleSynthesize}>Synth</button>
			<button class="tool-btn accent" title="Verify All" onclick={handleVerify}>Verify</button>
		</div>
	</header>

	<!-- Main Content -->
	<div class="main-content">
		<!-- Left Sidebar -->
		{#if $leftSidebarOpen}
			<aside class="sidebar left">
				<div class="panel">
					<div class="panel-header">Project Explorer</div>
					<div class="panel-body">
						<p class="placeholder">Open a project to browse files</p>
					</div>
				</div>
				<div class="panel">
					<div class="panel-header">Hierarchy</div>
					<div class="panel-body">
						<Hierarchy />
					</div>
				</div>
			</aside>
		{/if}

		<!-- Center Editor -->
		<main class="editor-area">
			<Editor />
		</main>

		<!-- Right Sidebar -->
		{#if $rightSidebarOpen}
			<aside class="sidebar right">
				<div class="panel">
					<div class="panel-header">Properties</div>
					<div class="panel-body">
						<p class="placeholder">Select a signal or module to view properties</p>
					</div>
				</div>
				<div class="panel">
					<div class="panel-header">Security Score</div>
					<div class="panel-body">
						<div class="score-card">
							<div class="score-label">Overall</div>
							<div class="score-value">--</div>
						</div>
						<div class="score-grid">
							<div class="score-item">
								<span class="score-name">Power SCA</span>
								<span class="score-badge">--</span>
							</div>
							<div class="score-item">
								<span class="score-name">Timing</span>
								<span class="score-badge">--</span>
							</div>
							<div class="score-item">
								<span class="score-name">Fault</span>
								<span class="score-badge">--</span>
							</div>
							<div class="score-item">
								<span class="score-name">Entropy</span>
								<span class="score-badge">--</span>
							</div>
						</div>
					</div>
				</div>
			</aside>
		{/if}
	</div>

	<!-- Bottom Panel -->
	{#if $bottomPanelOpen}
		<div class="bottom-panel">
			<div class="panel-tabs">
				<button
					class="tab"
					class:active={$bottomPanelTab === 'console'}
					onclick={() => bottomPanelTab.set('console')}
				>Console</button>
				<button
					class="tab"
					class:active={$bottomPanelTab === 'problems'}
					onclick={() => bottomPanelTab.set('problems')}
				>Problems</button>
				<button
					class="tab"
					class:active={$bottomPanelTab === 'waveforms'}
					onclick={() => bottomPanelTab.set('waveforms')}
				>Waveforms</button>
				<button
					class="tab"
					class:active={$bottomPanelTab === 'reports'}
					onclick={() => bottomPanelTab.set('reports')}
				>Reports</button>
			</div>
			<div class="panel-content">
				{#if $bottomPanelTab === 'console'}
					<Console />
				{:else if $bottomPanelTab === 'problems'}
					<div class="tab-placeholder">No problems detected</div>
				{:else if $bottomPanelTab === 'waveforms'}
					<div class="tab-placeholder">Run simulation to view waveforms</div>
				{:else if $bottomPanelTab === 'reports'}
					<div class="tab-placeholder">Run verification to generate reports</div>
				{/if}
			</div>
		</div>
	{/if}

	<!-- Status Bar -->
	<footer class="status-bar">
		<span>Ready</span>
		<span class="spacer"></span>
		<span>PDK: {$currentProject?.target_pdk ?? 'SKY130'}</span>
		<span>Top: {$currentProject?.top_module ?? '(none)'}</span>
	</footer>
</div>

<style>
	.ide-layout {
		display: flex;
		flex-direction: column;
		height: 100vh;
		background: var(--color-bg-primary);
	}

	.top-bar {
		display: flex;
		align-items: center;
		gap: 16px;
		padding: 4px 12px;
		background: var(--color-bg-secondary);
		border-bottom: 1px solid var(--color-border);
		flex-shrink: 0;
	}

	.logo { display: flex; align-items: center; gap: 6px; padding-right: 12px; border-right: 1px solid var(--color-border); }
	.logo-text { font-weight: 700; font-size: 14px; color: var(--color-accent); }
	.logo-badge { font-size: 10px; background: var(--color-accent); color: var(--color-bg-primary); padding: 1px 4px; border-radius: 3px; font-weight: 600; }
	.menu-bar { display: flex; gap: 2px; }
	.menu-item { background: none; border: none; color: var(--color-text-secondary); padding: 4px 8px; font-size: 13px; cursor: pointer; border-radius: 4px; }
	.menu-item:hover { background: var(--color-bg-primary); color: var(--color-text-primary); }
	.toolbar { display: flex; align-items: center; gap: 4px; margin-left: auto; }
	.tool-btn { background: var(--color-bg-primary); border: 1px solid var(--color-border); color: var(--color-text-secondary); padding: 3px 10px; font-size: 12px; cursor: pointer; border-radius: 4px; }
	.tool-btn.accent { border-color: var(--color-accent); color: var(--color-accent); }
	.tool-btn:hover { background: var(--color-border); color: var(--color-text-primary); }
	.separator { width: 1px; height: 20px; background: var(--color-border); margin: 0 4px; }

	.main-content { display: flex; flex: 1; overflow: hidden; }
	.sidebar { width: 250px; background: var(--color-bg-secondary); display: flex; flex-direction: column; flex-shrink: 0; overflow-y: auto; }
	.sidebar.left { border-right: 1px solid var(--color-border); }
	.sidebar.right { border-left: 1px solid var(--color-border); }

	.panel { border-bottom: 1px solid var(--color-border); }
	.panel-header { padding: 6px 12px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--color-text-secondary); background: var(--color-bg-panel); }
	.panel-body { padding: 8px; }
	.placeholder { font-size: 12px; color: var(--color-text-secondary); opacity: 0.6; font-style: italic; padding: 4px; }

	.editor-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

	.score-card { text-align: center; padding: 8px; margin-bottom: 8px; }
	.score-label { font-size: 10px; text-transform: uppercase; color: var(--color-text-secondary); }
	.score-value { font-size: 28px; font-weight: 300; color: var(--color-text-secondary); }
	.score-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
	.score-item { display: flex; justify-content: space-between; padding: 4px 8px; background: var(--color-bg-primary); border-radius: 4px; font-size: 11px; }
	.score-name { color: var(--color-text-secondary); }
	.score-badge { color: var(--color-text-secondary); font-weight: 600; }

	.bottom-panel { height: 200px; background: var(--color-bg-secondary); border-top: 1px solid var(--color-border); flex-shrink: 0; display: flex; flex-direction: column; }
	.panel-tabs { display: flex; background: var(--color-bg-panel); border-bottom: 1px solid var(--color-border); }
	.tab { background: none; border: none; color: var(--color-text-secondary); padding: 6px 16px; font-size: 12px; cursor: pointer; border-bottom: 2px solid transparent; }
	.tab.active { color: var(--color-accent); border-bottom-color: var(--color-accent); }
	.panel-content { flex: 1; overflow: hidden; }
	.tab-placeholder { padding: 16px; font-size: 12px; color: var(--color-text-secondary); opacity: 0.6; font-style: italic; }

	.status-bar { display: flex; align-items: center; padding: 2px 12px; background: var(--color-accent); color: var(--color-bg-primary); font-size: 11px; font-weight: 500; flex-shrink: 0; gap: 16px; }
	.spacer { flex: 1; }
</style>
