<script lang="ts">
	// OpenForge EDA Web IDE - Main Page
	let projectName = $state('OpenForge EDA');
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
			<button class="tool-btn accent" title="Run Simulation">Simulate</button>
			<button class="tool-btn accent" title="Synthesize">Synth</button>
			<button class="tool-btn accent" title="Verify All">Verify</button>
		</div>
	</header>

	<!-- Main Content -->
	<div class="main-content">
		<!-- Left Sidebar -->
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
					<p class="placeholder">Module hierarchy will appear after synthesis</p>
				</div>
			</div>
		</aside>

		<!-- Center Editor -->
		<main class="editor-area">
			<div class="welcome">
				<h1>Welcome to OpenForge EDA</h1>
				<p>Cloud-native cryptographic hardware verification platform</p>
				<div class="actions">
					<button class="action-btn">New Project</button>
					<button class="action-btn">Open Project</button>
					<button class="action-btn">Open Example</button>
				</div>
			</div>
		</main>

		<!-- Right Sidebar -->
		<aside class="sidebar right">
			<div class="panel">
				<div class="panel-header">Properties</div>
				<div class="panel-body">
					<p class="placeholder">Select a signal or module to view properties</p>
				</div>
			</div>
		</aside>
	</div>

	<!-- Bottom Panel -->
	<div class="bottom-panel">
		<div class="panel-tabs">
			<button class="tab active">Console</button>
			<button class="tab">Problems</button>
			<button class="tab">Waveforms</button>
			<button class="tab">Reports</button>
		</div>
		<div class="panel-body console">
			<pre>OpenForge EDA v0.1.0 - Ready</pre>
		</div>
	</div>

	<!-- Status Bar -->
	<footer class="status-bar">
		<span>Ready</span>
		<span class="spacer"></span>
		<span>PDK: SKY130</span>
		<span>Top: (none)</span>
		<span>Tools: Checking...</span>
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

	.logo {
		display: flex;
		align-items: center;
		gap: 6px;
		padding-right: 12px;
		border-right: 1px solid var(--color-border);
	}

	.logo-text {
		font-weight: 700;
		font-size: 14px;
		color: var(--color-accent);
	}

	.logo-badge {
		font-size: 10px;
		background: var(--color-accent);
		color: var(--color-bg-primary);
		padding: 1px 4px;
		border-radius: 3px;
		font-weight: 600;
	}

	.menu-bar {
		display: flex;
		gap: 2px;
	}

	.menu-item {
		background: none;
		border: none;
		color: var(--color-text-secondary);
		padding: 4px 8px;
		font-size: 13px;
		cursor: pointer;
		border-radius: 4px;
	}

	.menu-item:hover {
		background: var(--color-bg-primary);
		color: var(--color-text-primary);
	}

	.toolbar {
		display: flex;
		align-items: center;
		gap: 4px;
		margin-left: auto;
	}

	.tool-btn {
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		color: var(--color-text-secondary);
		padding: 3px 10px;
		font-size: 12px;
		cursor: pointer;
		border-radius: 4px;
	}

	.tool-btn.accent {
		border-color: var(--color-accent);
		color: var(--color-accent);
	}

	.tool-btn:hover {
		background: var(--color-border);
		color: var(--color-text-primary);
	}

	.separator {
		width: 1px;
		height: 20px;
		background: var(--color-border);
		margin: 0 4px;
	}

	.main-content {
		display: flex;
		flex: 1;
		overflow: hidden;
	}

	.sidebar {
		width: 250px;
		background: var(--color-bg-secondary);
		border-right: 1px solid var(--color-border);
		display: flex;
		flex-direction: column;
		flex-shrink: 0;
		overflow-y: auto;
	}

	.sidebar.right {
		border-right: none;
		border-left: 1px solid var(--color-border);
	}

	.panel {
		border-bottom: 1px solid var(--color-border);
	}

	.panel-header {
		padding: 6px 12px;
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: var(--color-text-secondary);
		background: var(--color-bg-panel);
	}

	.panel-body {
		padding: 12px;
	}

	.placeholder {
		font-size: 12px;
		color: var(--color-text-secondary);
		opacity: 0.6;
		font-style: italic;
	}

	.editor-area {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		overflow: hidden;
	}

	.welcome {
		text-align: center;
	}

	.welcome h1 {
		font-size: 24px;
		font-weight: 300;
		color: var(--color-text-primary);
		margin-bottom: 8px;
	}

	.welcome p {
		font-size: 14px;
		color: var(--color-text-secondary);
		margin-bottom: 24px;
	}

	.actions {
		display: flex;
		gap: 12px;
		justify-content: center;
	}

	.action-btn {
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		color: var(--color-accent);
		padding: 8px 20px;
		font-size: 13px;
		cursor: pointer;
		border-radius: 6px;
	}

	.action-btn:hover {
		background: var(--color-border);
	}

	.bottom-panel {
		height: 200px;
		background: var(--color-bg-secondary);
		border-top: 1px solid var(--color-border);
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
	}

	.panel-tabs {
		display: flex;
		gap: 0;
		background: var(--color-bg-panel);
		border-bottom: 1px solid var(--color-border);
	}

	.tab {
		background: none;
		border: none;
		color: var(--color-text-secondary);
		padding: 6px 16px;
		font-size: 12px;
		cursor: pointer;
		border-bottom: 2px solid transparent;
	}

	.tab.active {
		color: var(--color-accent);
		border-bottom-color: var(--color-accent);
	}

	.console {
		flex: 1;
		overflow-y: auto;
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
		font-size: 12px;
		padding: 8px 12px;
	}

	.console pre {
		margin: 0;
		color: var(--color-success);
	}

	.status-bar {
		display: flex;
		align-items: center;
		padding: 2px 12px;
		background: var(--color-accent);
		color: var(--color-bg-primary);
		font-size: 11px;
		font-weight: 500;
		flex-shrink: 0;
		gap: 16px;
	}

	.spacer {
		flex: 1;
	}
</style>
