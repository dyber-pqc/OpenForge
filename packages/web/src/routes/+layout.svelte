<script lang="ts">
	import '../app.css';
	import { currentProject, activityBarSelection, currentView } from '$lib/stores/project';
	import { page } from '$app/stores';

	let { children } = $props();

	let projectName = $derived($currentProject?.name ?? 'No Project');

	// Activity bar items
	const activityItems = [
		{ id: 'explorer' as const, label: 'Explorer', icon: 'E', shortcut: 'Ctrl+Shift+E' },
		{ id: 'hierarchy' as const, label: 'Hierarchy', icon: 'H', shortcut: 'Ctrl+Shift+H' },
		{ id: 'search' as const, label: 'Search', icon: 'S', shortcut: 'Ctrl+Shift+F' },
		{ id: 'git' as const, label: 'Git', icon: 'G', shortcut: 'Ctrl+Shift+G' },
		{ id: 'extensions' as const, label: 'Extensions', icon: 'X', shortcut: 'Ctrl+Shift+X' },
	] as const;

	// Top nav items
	const navItems = [
		{ label: 'IDE', href: '/', view: 'ide' as const },
		{ label: 'Projects', href: '/projects', view: 'projects' as const },
		{ label: 'Synthesis', href: '/synthesis', view: 'synthesis' as const },
		{ label: 'Verification', href: '/verification', view: 'verification' as const },
	];

	let showProjectSelector = $state(false);
	let showUserMenu = $state(false);

	function isActive(href: string): boolean {
		const path = $page.url.pathname;
		if (href === '/') return path === '/';
		return path.startsWith(href);
	}

	function closeMenus() {
		showProjectSelector = false;
		showUserMenu = false;
	}
</script>

<svelte:window onclick={closeMenus} />

<div class="app-shell">
	<!-- Top Navigation Bar -->
	<header class="top-nav">
		<div class="nav-left">
			<a href="/" class="logo-link">
				<span class="logo-text">OpenForge</span>
				<span class="logo-badge">EDA</span>
			</a>

			<nav class="main-nav">
				{#each navItems as item}
					<a
						href={item.href}
						class="nav-link"
						class:active={isActive(item.href)}
					>
						{item.label}
					</a>
				{/each}
			</nav>
		</div>

		<div class="nav-center">
			<!-- Project Selector -->
			<div class="project-selector-wrapper">
				<button
					class="project-selector"
					onclick={(e) => { e.stopPropagation(); showProjectSelector = !showProjectSelector; }}
				>
					<span class="project-icon">P</span>
					<span class="project-name">{projectName}</span>
					<span class="dropdown-arrow">{showProjectSelector ? '\u25B2' : '\u25BC'}</span>
				</button>

				{#if showProjectSelector}
					<div class="project-dropdown" onclick={(e) => e.stopPropagation()}>
						<div class="dropdown-search">
							<input type="text" placeholder="Search projects..." />
						</div>
						<div class="dropdown-items">
							<button class="dropdown-project active">
								<span class="proj-dot"></span>
								kyber-accelerator
							</button>
							<button class="dropdown-project">
								<span class="proj-dot"></span>
								dilithium-sign
							</button>
							<button class="dropdown-project">
								<span class="proj-dot"></span>
								aes-sbox-masked
							</button>
						</div>
						<div class="dropdown-footer">
							<a href="/projects">Manage Projects</a>
						</div>
					</div>
				{/if}
			</div>
		</div>

		<div class="nav-right">
			<button class="nav-icon-btn" title="Settings">
				<span class="icon-char">S</span>
			</button>
			<div class="user-menu-wrapper">
				<button
					class="user-avatar"
					onclick={(e) => { e.stopPropagation(); showUserMenu = !showUserMenu; }}
					title="User menu"
				>
					ZK
				</button>
				{#if showUserMenu}
					<div class="user-dropdown" onclick={(e) => e.stopPropagation()}>
						<div class="user-info">
							<strong>Zachary Kleckner</strong>
							<span class="user-email">zk@openforge.dev</span>
						</div>
						<div class="user-actions">
							<button class="user-action">Profile</button>
							<button class="user-action">Settings</button>
							<button class="user-action">Sign Out</button>
						</div>
					</div>
				{/if}
			</div>
		</div>
	</header>

	<div class="app-body">
		<!-- Activity Bar (left icon sidebar) -->
		<aside class="activity-bar">
			{#each activityItems as item}
				<button
					class="activity-btn"
					class:active={$activityBarSelection === item.id}
					title="{item.label} ({item.shortcut})"
					onclick={() => activityBarSelection.set(item.id)}
				>
					<span class="activity-icon">{item.icon}</span>
				</button>
			{/each}

			<div class="activity-spacer"></div>

			<button class="activity-btn" title="Settings">
				<span class="activity-icon">&#9881;</span>
			</button>
		</aside>

		<!-- Main Content Area -->
		<div class="app-content">
			{@render children()}
		</div>
	</div>
</div>

<style>
	.app-shell {
		display: flex;
		flex-direction: column;
		height: 100vh;
		overflow: hidden;
	}

	/* === Top Navigation Bar === */
	.top-nav {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 12px;
		height: 40px;
		background: var(--color-bg-secondary);
		border-bottom: 1px solid var(--color-border);
		flex-shrink: 0;
		z-index: 50;
	}

	.nav-left, .nav-right {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.nav-center {
		display: flex;
		align-items: center;
	}

	.logo-link {
		display: flex;
		align-items: center;
		gap: 6px;
		text-decoration: none;
		padding-right: 16px;
		border-right: 1px solid var(--color-border);
		margin-right: 8px;
	}

	.logo-text {
		font-weight: 700;
		font-size: 14px;
		color: var(--color-accent);
	}

	.logo-badge {
		font-size: 9px;
		background: var(--color-accent);
		color: var(--color-bg-primary);
		padding: 1px 5px;
		border-radius: 3px;
		font-weight: 700;
		letter-spacing: 0.5px;
	}

	.main-nav {
		display: flex;
		gap: 2px;
	}

	.nav-link {
		color: var(--color-text-secondary);
		text-decoration: none;
		padding: 6px 12px;
		font-size: 13px;
		border-radius: 4px;
		transition: all 0.1s;
	}

	.nav-link:hover {
		background: var(--color-bg-primary);
		color: var(--color-text-primary);
	}

	.nav-link.active {
		background: var(--color-bg-primary);
		color: var(--color-accent);
		font-weight: 500;
	}

	/* Project Selector */
	.project-selector-wrapper {
		position: relative;
	}

	.project-selector {
		display: flex;
		align-items: center;
		gap: 8px;
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		color: var(--color-text-primary);
		padding: 4px 12px;
		border-radius: 6px;
		cursor: pointer;
		font-size: 12px;
		min-width: 180px;
	}

	.project-selector:hover {
		border-color: var(--color-accent);
	}

	.project-icon {
		font-weight: 700;
		font-size: 10px;
		width: 18px;
		height: 18px;
		background: var(--color-accent);
		color: var(--color-bg-primary);
		border-radius: 3px;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.project-name {
		flex: 1;
		text-align: left;
	}

	.dropdown-arrow {
		font-size: 8px;
		color: var(--color-text-secondary);
	}

	.project-dropdown {
		position: absolute;
		top: 100%;
		left: 50%;
		transform: translateX(-50%);
		margin-top: 6px;
		width: 260px;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 8px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
		z-index: 100;
		overflow: hidden;
	}

	.dropdown-search {
		padding: 8px;
		border-bottom: 1px solid var(--color-border);
	}

	.dropdown-search input {
		width: 100%;
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		color: var(--color-text-primary);
		padding: 6px 10px;
		border-radius: 4px;
		font-size: 12px;
		outline: none;
	}

	.dropdown-search input:focus {
		border-color: var(--color-accent);
	}

	.dropdown-items {
		max-height: 200px;
		overflow-y: auto;
	}

	.dropdown-project {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		background: none;
		border: none;
		color: var(--color-text-primary);
		padding: 8px 12px;
		font-size: 12px;
		cursor: pointer;
		text-align: left;
	}

	.dropdown-project:hover {
		background: rgba(122, 162, 247, 0.1);
	}

	.dropdown-project.active {
		background: rgba(122, 162, 247, 0.15);
		color: var(--color-accent);
	}

	.proj-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--color-success);
		flex-shrink: 0;
	}

	.dropdown-footer {
		padding: 8px 12px;
		border-top: 1px solid var(--color-border);
		text-align: center;
	}

	.dropdown-footer a {
		color: var(--color-accent);
		text-decoration: none;
		font-size: 12px;
	}

	.dropdown-footer a:hover {
		text-decoration: underline;
	}

	/* User Menu */
	.nav-icon-btn {
		background: none;
		border: 1px solid transparent;
		color: var(--color-text-secondary);
		width: 28px;
		height: 28px;
		display: flex;
		align-items: center;
		justify-content: center;
		cursor: pointer;
		border-radius: 4px;
	}

	.nav-icon-btn:hover {
		background: var(--color-bg-primary);
		color: var(--color-text-primary);
	}

	.icon-char {
		font-size: 14px;
	}

	.user-menu-wrapper {
		position: relative;
	}

	.user-avatar {
		width: 28px;
		height: 28px;
		border-radius: 50%;
		background: var(--color-accent);
		color: var(--color-bg-primary);
		font-size: 10px;
		font-weight: 700;
		display: flex;
		align-items: center;
		justify-content: center;
		border: none;
		cursor: pointer;
	}

	.user-dropdown {
		position: absolute;
		top: 100%;
		right: 0;
		margin-top: 6px;
		width: 200px;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 8px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
		z-index: 100;
		overflow: hidden;
	}

	.user-info {
		padding: 12px;
		border-bottom: 1px solid var(--color-border);
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.user-info strong {
		font-size: 13px;
		color: var(--color-text-primary);
	}

	.user-email {
		font-size: 11px;
		color: var(--color-text-secondary);
	}

	.user-actions {
		padding: 4px 0;
	}

	.user-action {
		display: block;
		width: 100%;
		background: none;
		border: none;
		color: var(--color-text-primary);
		padding: 6px 12px;
		font-size: 12px;
		cursor: pointer;
		text-align: left;
	}

	.user-action:hover {
		background: rgba(122, 162, 247, 0.1);
	}

	/* === App Body === */
	.app-body {
		display: flex;
		flex: 1;
		overflow: hidden;
	}

	/* === Activity Bar === */
	.activity-bar {
		width: 48px;
		background: var(--color-bg-secondary);
		border-right: 1px solid var(--color-border);
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 8px 0;
		gap: 4px;
		flex-shrink: 0;
	}

	.activity-btn {
		width: 40px;
		height: 40px;
		display: flex;
		align-items: center;
		justify-content: center;
		background: none;
		border: none;
		color: var(--color-text-secondary);
		cursor: pointer;
		border-radius: 6px;
		position: relative;
	}

	.activity-btn:hover {
		color: var(--color-text-primary);
		background: rgba(255, 255, 255, 0.04);
	}

	.activity-btn.active {
		color: var(--color-accent);
	}

	.activity-btn.active::before {
		content: '';
		position: absolute;
		left: 0;
		top: 6px;
		bottom: 6px;
		width: 3px;
		background: var(--color-accent);
		border-radius: 0 2px 2px 0;
	}

	.activity-icon {
		font-size: 18px;
		font-weight: 700;
		font-family: 'Inter', sans-serif;
	}

	.activity-spacer {
		flex: 1;
	}

	/* === Main Content === */
	.app-content {
		flex: 1;
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}
</style>
