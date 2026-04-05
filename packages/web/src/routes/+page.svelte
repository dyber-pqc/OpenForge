<script lang="ts">
	import Editor from '$lib/components/editor/Editor.svelte';
	import Console from '$lib/components/console/Console.svelte';
	import Hierarchy from '$lib/components/hierarchy/Hierarchy.svelte';
	import WaveformViewer from '$lib/components/waveform/WaveformViewer.svelte';
	import SecurityDashboard from '$lib/components/security/SecurityDashboard.svelte';
	import TimingDashboard from '$lib/components/timing/TimingDashboard.svelte';
	import FileExplorer from '$lib/components/explorer/FileExplorer.svelte';
	import Toolbar from '$lib/components/toolbar/Toolbar.svelte';
	import StatusBar from '$lib/components/statusbar/StatusBar.svelte';
	import {
		currentProject,
		leftSidebarOpen,
		rightSidebarOpen,
		bottomPanelOpen,
		bottomPanelTab,
		leftPanelTab,
		rightPanelTab,
		openFiles,
		appendConsole
	} from '$lib/stores/project';

	let projectName = $derived($currentProject?.name ?? 'OpenForge EDA');

	// Panel sizes (persisted via CSS custom properties, drag to resize)
	let leftPanelWidth = $state(260);
	let rightPanelWidth = $state(260);
	let bottomPanelHeight = $state(220);
	let isDraggingLeft = $state(false);
	let isDraggingRight = $state(false);
	let isDraggingBottom = $state(false);

	// Restore panel sizes from localStorage
	function restoreSizes() {
		try {
			const saved = localStorage.getItem('ide-panel-sizes');
			if (saved) {
				const s = JSON.parse(saved);
				leftPanelWidth = s.left ?? 260;
				rightPanelWidth = s.right ?? 260;
				bottomPanelHeight = s.bottom ?? 220;
			}
		} catch { /* ignore */ }
	}

	function saveSizes() {
		localStorage.setItem('ide-panel-sizes', JSON.stringify({
			left: leftPanelWidth,
			right: rightPanelWidth,
			bottom: bottomPanelHeight
		}));
	}

	$effect(() => {
		restoreSizes();
	});

	function onMouseMove(e: MouseEvent) {
		if (isDraggingLeft) {
			leftPanelWidth = Math.max(160, Math.min(500, e.clientX - 48)); // 48 = activity bar
		} else if (isDraggingRight) {
			rightPanelWidth = Math.max(160, Math.min(500, window.innerWidth - e.clientX));
		} else if (isDraggingBottom) {
			const mainTop = document.querySelector('.ide-main')?.getBoundingClientRect().top ?? 0;
			const mainBottom = window.innerHeight - 24; // 24 = status bar
			bottomPanelHeight = Math.max(100, Math.min(500, mainBottom - e.clientY));
		}
	}

	function onMouseUp() {
		if (isDraggingLeft || isDraggingRight || isDraggingBottom) {
			isDraggingLeft = false;
			isDraggingRight = false;
			isDraggingBottom = false;
			saveSizes();
		}
	}

	let hasProject = $derived($currentProject !== null || $openFiles.length > 0);
	let showWelcome = $derived(!hasProject && $openFiles.length === 0);
</script>

<svelte:head>
	<title>{projectName}</title>
</svelte:head>

<svelte:window onmousemove={onMouseMove} onmouseup={onMouseUp} />

<div
	class="ide-layout"
	class:dragging={isDraggingLeft || isDraggingRight || isDraggingBottom}
>
	<!-- Menu Bar + Toolbar -->
	<header class="menu-toolbar-bar">
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
		<div class="toolbar-area">
			<Toolbar />
		</div>
	</header>

	<!-- Main IDE Area -->
	<div class="ide-main">
		<!-- Left Panel: Explorer / Hierarchy -->
		{#if $leftSidebarOpen}
			<aside class="left-panel" style="width: {leftPanelWidth}px">
				<div class="panel-tab-bar">
					<button
						class="panel-tab"
						class:active={$leftPanelTab === 'explorer'}
						onclick={() => leftPanelTab.set('explorer')}
					>Explorer</button>
					<button
						class="panel-tab"
						class:active={$leftPanelTab === 'hierarchy'}
						onclick={() => leftPanelTab.set('hierarchy')}
					>Hierarchy</button>
					<button
						class="panel-collapse-btn"
						onclick={() => leftSidebarOpen.set(false)}
						title="Collapse"
					>&#10005;</button>
				</div>
				<div class="panel-body">
					{#if $leftPanelTab === 'explorer'}
						<FileExplorer />
					{:else}
						<Hierarchy />
					{/if}
				</div>
			</aside>
			<div
				class="divider vertical"
				onmousedown={() => (isDraggingLeft = true)}
				role="separator"
			></div>
		{:else}
			<button class="collapsed-panel-btn left" onclick={() => leftSidebarOpen.set(true)} title="Show Explorer">
				&#9654;
			</button>
		{/if}

		<!-- Center Content (Editor + Bottom Panel) -->
		<div class="center-area">
			<!-- Editor Area -->
			<div class="editor-area" style={$bottomPanelOpen ? `flex: 1; min-height: 200px;` : 'flex: 1;'}>
				{#if showWelcome}
					<!-- Welcome Page -->
					<div class="welcome-page">
						<div class="welcome-content">
							<div class="welcome-logo">
								<span class="wl-text">OpenForge</span>
								<span class="wl-badge">EDA</span>
							</div>
							<p class="welcome-subtitle">Cloud-Native Electronic Design Automation</p>

							<div class="welcome-grid">
								<div class="welcome-section">
									<h3 class="section-title">Start</h3>
									<a href="/projects" class="welcome-link">New Project...</a>
									<button class="welcome-link" onclick={() => appendConsole('Open Project dialog not yet implemented', 'warning')}>Open Project...</button>
									<button class="welcome-link" onclick={() => appendConsole('Import not yet implemented', 'warning')}>Import from Git...</button>
								</div>
								<div class="welcome-section">
									<h3 class="section-title">Recent</h3>
									<button class="welcome-link">kyber-accelerator</button>
									<button class="welcome-link">dilithium-sign</button>
									<button class="welcome-link">aes-sbox-masked</button>
								</div>
								<div class="welcome-section">
									<h3 class="section-title">Tools</h3>
									<div class="tool-row">
										<span class="tool-name">Yosys</span>
										<span class="tool-status installed">Installed</span>
									</div>
									<div class="tool-row">
										<span class="tool-name">OpenROAD</span>
										<span class="tool-status installed">Installed</span>
									</div>
									<div class="tool-row">
										<span class="tool-name">Verilator</span>
										<span class="tool-status installed">Installed</span>
									</div>
									<div class="tool-row">
										<span class="tool-name">openforge-ct</span>
										<span class="tool-status installed">Installed</span>
									</div>
								</div>
								<div class="welcome-section">
									<h3 class="section-title">Learn</h3>
									<button class="welcome-link">Documentation</button>
									<button class="welcome-link">Examples</button>
									<button class="welcome-link">Keyboard Shortcuts</button>
								</div>
							</div>

							<div class="welcome-footer">
								<span class="version-tag">v0.1.0</span>
								<span class="footer-sep">|</span>
								<span class="footer-text">Python 3.12 + Rust + SvelteKit</span>
							</div>
						</div>
					</div>
				{:else}
					<Editor />
				{/if}
			</div>

			<!-- Bottom Panel Divider -->
			{#if $bottomPanelOpen}
				<div
					class="divider horizontal"
					onmousedown={() => (isDraggingBottom = true)}
					role="separator"
				></div>

				<!-- Bottom Panel -->
				<div class="bottom-panel" style="height: {bottomPanelHeight}px">
					<div class="panel-tab-bar bottom">
						<button
							class="panel-tab"
							class:active={$bottomPanelTab === 'console'}
							onclick={() => bottomPanelTab.set('console')}
						>Console</button>
						<button
							class="panel-tab"
							class:active={$bottomPanelTab === 'problems'}
							onclick={() => bottomPanelTab.set('problems')}
						>Problems</button>
						<button
							class="panel-tab"
							class:active={$bottomPanelTab === 'waveforms'}
							onclick={() => bottomPanelTab.set('waveforms')}
						>Waveforms</button>
						<button
							class="panel-tab"
							class:active={$bottomPanelTab === 'reports'}
							onclick={() => bottomPanelTab.set('reports')}
						>Reports</button>
						<button
							class="panel-tab"
							class:active={$bottomPanelTab === 'timing'}
							onclick={() => bottomPanelTab.set('timing')}
						>Timing</button>
						<div class="tab-spacer"></div>
						<button
							class="panel-collapse-btn"
							onclick={() => bottomPanelOpen.set(false)}
							title="Collapse"
						>&#10005;</button>
					</div>
					<div class="bottom-content">
						{#if $bottomPanelTab === 'console'}
							<Console />
						{:else if $bottomPanelTab === 'problems'}
							<div class="tab-placeholder">
								<span class="placeholder-icon">&#10003;</span>
								<span>No problems detected</span>
							</div>
						{:else if $bottomPanelTab === 'waveforms'}
							<WaveformViewer signals={[]} timescale={{ magnitude: 1, unit: 'ns' }} />
						{:else if $bottomPanelTab === 'reports'}
							<div class="tab-placeholder">
								<span class="placeholder-icon">&#128196;</span>
								<span>Run verification to generate reports</span>
							</div>
						{:else if $bottomPanelTab === 'timing'}
							<TimingDashboard />
						{/if}
					</div>
				</div>
			{:else}
				<button class="collapsed-panel-btn bottom" onclick={() => bottomPanelOpen.set(true)} title="Show Panel">
					Console | Problems | Waveforms | Reports | Timing
				</button>
			{/if}
		</div>

		<!-- Right Panel: Properties / Security -->
		{#if $rightSidebarOpen}
			<div
				class="divider vertical"
				onmousedown={() => (isDraggingRight = true)}
				role="separator"
			></div>
			<aside class="right-panel" style="width: {rightPanelWidth}px">
				<div class="panel-tab-bar">
					<button
						class="panel-tab"
						class:active={$rightPanelTab === 'properties'}
						onclick={() => rightPanelTab.set('properties')}
					>Properties</button>
					<button
						class="panel-tab"
						class:active={$rightPanelTab === 'security'}
						onclick={() => rightPanelTab.set('security')}
					>Security</button>
					<button
						class="panel-collapse-btn"
						onclick={() => rightSidebarOpen.set(false)}
						title="Collapse"
					>&#10005;</button>
				</div>
				<div class="panel-body">
					{#if $rightPanelTab === 'properties'}
						<div class="properties-panel">
							<div class="prop-section">
								<h4 class="prop-section-title">Module</h4>
								<div class="prop-row">
									<span class="prop-key">Name</span>
									<span class="prop-val">top</span>
								</div>
								<div class="prop-row">
									<span class="prop-key">Ports</span>
									<span class="prop-val">12</span>
								</div>
								<div class="prop-row">
									<span class="prop-key">Instances</span>
									<span class="prop-val">4</span>
								</div>
							</div>
							<div class="prop-section">
								<h4 class="prop-section-title">Signal</h4>
								<p class="prop-placeholder">Select a signal or module to view properties</p>
							</div>
						</div>
					{:else}
						<SecurityDashboard />
					{/if}
				</div>
			</aside>
		{:else}
			<button class="collapsed-panel-btn right" onclick={() => rightSidebarOpen.set(true)} title="Show Properties">
				&#9664;
			</button>
		{/if}
	</div>

	<!-- Status Bar -->
	<StatusBar />
</div>

<style>
	.ide-layout {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: var(--color-bg-primary);
	}

	.ide-layout.dragging {
		cursor: col-resize;
		user-select: none;
	}

	/* === Menu + Toolbar Bar === */
	.menu-toolbar-bar {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 0 8px;
		height: 36px;
		background: var(--color-bg-secondary);
		border-bottom: 1px solid var(--color-border);
		flex-shrink: 0;
	}

	.menu-bar {
		display: flex;
		gap: 2px;
		flex-shrink: 0;
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

	.toolbar-area {
		flex: 1;
		display: flex;
		justify-content: flex-end;
		height: 100%;
	}

	/* === IDE Main Area === */
	.ide-main {
		display: flex;
		flex: 1;
		overflow: hidden;
	}

	/* === Left Panel === */
	.left-panel {
		background: var(--color-bg-secondary);
		display: flex;
		flex-direction: column;
		flex-shrink: 0;
		overflow: hidden;
		min-width: 160px;
	}

	/* === Right Panel === */
	.right-panel {
		background: var(--color-bg-secondary);
		display: flex;
		flex-direction: column;
		flex-shrink: 0;
		overflow: hidden;
		min-width: 160px;
	}

	/* === Panel Tab Bar === */
	.panel-tab-bar {
		display: flex;
		align-items: center;
		background: var(--color-bg-panel);
		border-bottom: 1px solid var(--color-border);
		flex-shrink: 0;
		padding: 0 4px;
	}

	.panel-tab-bar.bottom {
		background: var(--color-bg-secondary);
	}

	.panel-tab {
		background: none;
		border: none;
		color: var(--color-text-secondary);
		padding: 6px 12px;
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		border-bottom: 2px solid transparent;
		text-transform: uppercase;
		letter-spacing: 0.3px;
	}

	.panel-tab:hover {
		color: var(--color-text-primary);
	}

	.panel-tab.active {
		color: var(--color-accent);
		border-bottom-color: var(--color-accent);
	}

	.panel-collapse-btn {
		background: none;
		border: none;
		color: var(--color-text-secondary);
		font-size: 12px;
		cursor: pointer;
		padding: 4px 6px;
		margin-left: auto;
		border-radius: 3px;
	}

	.panel-collapse-btn:hover {
		background: var(--color-bg-primary);
		color: var(--color-text-primary);
	}

	.tab-spacer {
		flex: 1;
	}

	.panel-body {
		flex: 1;
		overflow: hidden;
	}

	/* === Dividers === */
	.divider {
		flex-shrink: 0;
		background: var(--color-border);
		z-index: 5;
	}

	.divider.vertical {
		width: 3px;
		cursor: col-resize;
	}

	.divider.horizontal {
		height: 3px;
		cursor: row-resize;
	}

	.divider:hover {
		background: var(--color-accent);
	}

	/* === Collapsed Panel Buttons === */
	.collapsed-panel-btn {
		background: var(--color-bg-secondary);
		border: none;
		color: var(--color-text-secondary);
		cursor: pointer;
		font-size: 10px;
		flex-shrink: 0;
	}

	.collapsed-panel-btn.left {
		width: 16px;
		writing-mode: vertical-lr;
		padding: 12px 2px;
		border-right: 1px solid var(--color-border);
	}

	.collapsed-panel-btn.right {
		width: 16px;
		writing-mode: vertical-lr;
		padding: 12px 2px;
		border-left: 1px solid var(--color-border);
	}

	.collapsed-panel-btn.bottom {
		height: 22px;
		width: 100%;
		padding: 2px 12px;
		border-top: 1px solid var(--color-border);
		font-size: 11px;
		letter-spacing: 0.5px;
	}

	.collapsed-panel-btn:hover {
		background: var(--color-bg-primary);
		color: var(--color-accent);
	}

	/* === Center Area === */
	.center-area {
		flex: 1;
		display: flex;
		flex-direction: column;
		overflow: hidden;
		min-width: 300px;
	}

	.editor-area {
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}

	/* === Bottom Panel === */
	.bottom-panel {
		background: var(--color-bg-secondary);
		display: flex;
		flex-direction: column;
		flex-shrink: 0;
		overflow: hidden;
		min-height: 100px;
	}

	.bottom-content {
		flex: 1;
		overflow: hidden;
	}

	.tab-placeholder {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		height: 100%;
		font-size: 12px;
		color: var(--color-text-secondary);
		opacity: 0.6;
		font-style: italic;
	}

	.placeholder-icon {
		font-size: 16px;
	}

	/* === Properties Panel === */
	.properties-panel {
		padding: 8px;
		overflow-y: auto;
		height: 100%;
	}

	.prop-section {
		margin-bottom: 16px;
	}

	.prop-section-title {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: var(--color-text-secondary);
		margin: 0 0 8px 0;
		padding-bottom: 4px;
		border-bottom: 1px solid var(--color-border);
	}

	.prop-row {
		display: flex;
		justify-content: space-between;
		padding: 3px 4px;
		font-size: 12px;
		border-radius: 3px;
	}

	.prop-row:hover {
		background: rgba(255, 255, 255, 0.03);
	}

	.prop-key {
		color: var(--color-text-secondary);
	}

	.prop-val {
		color: var(--color-text-primary);
		font-weight: 500;
		font-family: 'JetBrains Mono', monospace;
		font-size: 11px;
	}

	.prop-placeholder {
		font-size: 12px;
		color: var(--color-text-secondary);
		opacity: 0.6;
		font-style: italic;
		margin: 0;
	}

	/* === Welcome Page === */
	.welcome-page {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		background: var(--color-bg-primary);
	}

	.welcome-content {
		text-align: center;
		max-width: 640px;
		padding: 40px;
	}

	.welcome-logo {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 10px;
		margin-bottom: 8px;
	}

	.wl-text {
		font-size: 36px;
		font-weight: 800;
		color: var(--color-accent);
		letter-spacing: -0.5px;
	}

	.wl-badge {
		font-size: 14px;
		background: var(--color-accent);
		color: var(--color-bg-primary);
		padding: 4px 10px;
		border-radius: 6px;
		font-weight: 700;
		letter-spacing: 1px;
	}

	.welcome-subtitle {
		color: var(--color-text-secondary);
		font-size: 14px;
		margin-bottom: 36px;
	}

	.welcome-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 24px;
		text-align: left;
	}

	.welcome-section {
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 8px;
		padding: 16px;
	}

	.section-title {
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: var(--color-text-secondary);
		margin: 0 0 12px 0;
	}

	.welcome-link {
		display: block;
		background: none;
		border: none;
		color: var(--color-accent);
		text-decoration: none;
		padding: 4px 0;
		font-size: 13px;
		cursor: pointer;
		text-align: left;
		width: 100%;
	}

	.welcome-link:hover {
		text-decoration: underline;
	}

	.tool-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 4px 0;
		font-size: 12px;
	}

	.tool-name {
		color: var(--color-text-primary);
		font-family: 'JetBrains Mono', monospace;
		font-size: 11px;
	}

	.tool-status {
		font-size: 10px;
		font-weight: 600;
	}

	.tool-status.installed {
		color: var(--color-success);
	}

	.welcome-footer {
		margin-top: 32px;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		color: var(--color-text-secondary);
		font-size: 11px;
		opacity: 0.5;
	}

	.version-tag {
		font-family: 'JetBrains Mono', monospace;
	}

	.footer-sep {
		opacity: 0.4;
	}
</style>
