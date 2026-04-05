<script lang="ts">
	/**
	 * Project management page -- grid of project cards with create/import/search.
	 */

	import { projectsList } from '$lib/stores/project';
	import type { Project } from '$lib/api/client';

	// Demo data
	const demoProjects: (Project & { status: string; description: string })[] = [
		{
			id: '1',
			name: 'kyber-accelerator',
			top_module: 'kyber_top',
			target_pdk: 'SKY130',
			created_at: '2025-12-01T00:00:00Z',
			status: 'passing',
			description: 'CRYSTALS-Kyber hardware accelerator with NTT butterfly, Keccak core, and AXI interface.'
		},
		{
			id: '2',
			name: 'dilithium-sign',
			top_module: 'dilithium_top',
			target_pdk: 'GF180',
			created_at: '2025-11-15T00:00:00Z',
			status: 'warning',
			description: 'CRYSTALS-Dilithium digital signature engine with constant-time signing.'
		},
		{
			id: '3',
			name: 'aes-sbox-masked',
			top_module: 'aes_sbox',
			target_pdk: 'SKY130',
			created_at: '2025-10-20T00:00:00Z',
			status: 'passing',
			description: 'DOM-masked AES S-box implementation with SCA countermeasures.'
		},
		{
			id: '4',
			name: 'sha3-keccak',
			top_module: 'keccak_top',
			target_pdk: 'ASAP7',
			created_at: '2025-09-10T00:00:00Z',
			status: 'failing',
			description: 'Keccak-f[1600] permutation with configurable rounds and padding.'
		},
		{
			id: '5',
			name: 'trng-entropy',
			top_module: 'trng_top',
			target_pdk: 'SKY130',
			created_at: '2025-08-05T00:00:00Z',
			status: 'passing',
			description: 'Ring-oscillator based true random number generator with online health tests.'
		},
		{
			id: '6',
			name: 'pqc-coprocessor',
			top_module: 'pqc_top',
			target_pdk: 'GF180',
			created_at: '2025-07-01T00:00:00Z',
			status: 'pending',
			description: 'Post-quantum cryptographic coprocessor integrating Kyber and Dilithium.'
		},
	];

	let searchQuery = $state('');
	let sortBy = $state<'name' | 'date' | 'status'>('date');
	let showCreateModal = $state(false);

	// Create form
	let newName = $state('');
	let newTopModule = $state('');
	let newPDK = $state('SKY130');

	let filteredProjects = $derived(() => {
		let list = [...demoProjects];

		// Filter
		if (searchQuery.trim()) {
			const q = searchQuery.toLowerCase();
			list = list.filter(
				(p) =>
					p.name.toLowerCase().includes(q) ||
					p.top_module.toLowerCase().includes(q) ||
					p.target_pdk.toLowerCase().includes(q) ||
					p.description.toLowerCase().includes(q)
			);
		}

		// Sort
		if (sortBy === 'name') {
			list.sort((a, b) => a.name.localeCompare(b.name));
		} else if (sortBy === 'date') {
			list.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
		} else if (sortBy === 'status') {
			const order = { failing: 0, warning: 1, passing: 2, pending: 3 };
			list.sort((a, b) => (order[a.status as keyof typeof order] ?? 4) - (order[b.status as keyof typeof order] ?? 4));
		}

		return list;
	});

	function statusColor(status: string): string {
		switch (status) {
			case 'passing': return 'var(--color-success)';
			case 'warning': return 'var(--color-warning)';
			case 'failing': return 'var(--color-error)';
			default: return 'var(--color-text-secondary)';
		}
	}

	function formatDate(iso: string): string {
		return new Date(iso).toLocaleDateString('en-US', {
			year: 'numeric',
			month: 'short',
			day: 'numeric'
		});
	}

	function handleCreate() {
		// Would call API
		showCreateModal = false;
		newName = '';
		newTopModule = '';
		newPDK = 'SKY130';
	}
</script>

<svelte:head>
	<title>Projects - OpenForge EDA</title>
</svelte:head>

<div class="projects-page">
	<!-- Header -->
	<div class="page-header">
		<div class="header-left">
			<h1 class="page-title">Projects</h1>
			<span class="project-count">{demoProjects.length} projects</span>
		</div>
		<div class="header-actions">
			<button class="action-btn secondary" onclick={() => {}}>
				<span class="btn-icon">&#8595;</span>
				Import Project
			</button>
			<button class="action-btn primary" onclick={() => (showCreateModal = true)}>
				<span class="btn-icon">+</span>
				New Project
			</button>
		</div>
	</div>

	<!-- Search / Filter Bar -->
	<div class="filter-bar">
		<div class="search-input-wrapper">
			<span class="search-icon">Q</span>
			<input
				type="text"
				bind:value={searchQuery}
				placeholder="Search projects..."
				class="search-input"
			/>
		</div>
		<div class="sort-group">
			<span class="sort-label">Sort by:</span>
			<select bind:value={sortBy} class="sort-select">
				<option value="date">Last Modified</option>
				<option value="name">Name</option>
				<option value="status">Status</option>
			</select>
		</div>
	</div>

	<!-- Project Grid -->
	<div class="project-grid">
		{#each filteredProjects() as project}
			<a href="/projects/{project.id}" class="project-card">
				<div class="card-header">
					<div class="card-title-row">
						<h3 class="card-title">{project.name}</h3>
						<span class="status-badge" style="color: {statusColor(project.status)}">
							{project.status.toUpperCase()}
						</span>
					</div>
					<span class="card-pdk">{project.target_pdk}</span>
				</div>
				<p class="card-desc">{project.description}</p>
				<div class="card-footer">
					<span class="card-module">Top: {project.top_module}</span>
					<span class="card-date">{formatDate(project.created_at)}</span>
				</div>
			</a>
		{/each}
	</div>
</div>

<!-- Create Project Modal -->
{#if showCreateModal}
	<div class="modal-overlay" onclick={() => (showCreateModal = false)} role="dialog">
		<div class="modal" onclick={(e) => e.stopPropagation()}>
			<div class="modal-header">
				<h2 class="modal-title">New Project</h2>
				<button class="modal-close" onclick={() => (showCreateModal = false)}>&#10005;</button>
			</div>
			<div class="modal-body">
				<div class="form-group">
					<label class="form-label">Project Name</label>
					<input
						type="text"
						bind:value={newName}
						placeholder="my-project"
						class="form-input"
					/>
				</div>
				<div class="form-group">
					<label class="form-label">Top Module</label>
					<input
						type="text"
						bind:value={newTopModule}
						placeholder="top"
						class="form-input"
					/>
				</div>
				<div class="form-group">
					<label class="form-label">Target PDK</label>
					<select bind:value={newPDK} class="form-input">
						<option value="SKY130">SkyWater SKY130</option>
						<option value="GF180">GlobalFoundries GF180MCU</option>
						<option value="ASAP7">ASAP7 (academic)</option>
						<option value="NANGATE45">NanGate 45nm</option>
					</select>
				</div>
			</div>
			<div class="modal-footer">
				<button class="action-btn secondary" onclick={() => (showCreateModal = false)}>Cancel</button>
				<button
					class="action-btn primary"
					onclick={handleCreate}
					disabled={!newName.trim()}
				>Create Project</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.projects-page {
		padding: 24px 32px;
		overflow-y: auto;
		height: 100%;
		background: var(--color-bg-primary);
	}

	/* Header */
	.page-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 20px;
	}

	.header-left {
		display: flex;
		align-items: baseline;
		gap: 12px;
	}

	.page-title {
		font-size: 24px;
		font-weight: 700;
		margin: 0;
		color: var(--color-text-primary);
	}

	.project-count {
		font-size: 13px;
		color: var(--color-text-secondary);
	}

	.header-actions {
		display: flex;
		gap: 8px;
	}

	.action-btn {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 8px 16px;
		border-radius: 6px;
		font-size: 13px;
		font-weight: 500;
		cursor: pointer;
		border: 1px solid var(--color-border);
	}

	.action-btn.primary {
		background: var(--color-accent);
		color: var(--color-bg-primary);
		border-color: var(--color-accent);
	}

	.action-btn.primary:hover {
		opacity: 0.9;
	}

	.action-btn.primary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.action-btn.secondary {
		background: var(--color-bg-secondary);
		color: var(--color-text-primary);
	}

	.action-btn.secondary:hover {
		background: var(--color-border);
	}

	.btn-icon {
		font-weight: 700;
	}

	/* Filter Bar */
	.filter-bar {
		display: flex;
		gap: 12px;
		margin-bottom: 20px;
		align-items: center;
	}

	.search-input-wrapper {
		display: flex;
		align-items: center;
		gap: 8px;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 6px;
		padding: 0 12px;
		flex: 1;
		max-width: 400px;
	}

	.search-icon {
		color: var(--color-text-secondary);
		font-weight: 700;
		font-size: 14px;
	}

	.search-input {
		background: none;
		border: none;
		color: var(--color-text-primary);
		padding: 8px 0;
		font-size: 13px;
		outline: none;
		flex: 1;
	}

	.search-input::placeholder {
		color: var(--color-text-secondary);
		opacity: 0.5;
	}

	.sort-group {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.sort-label {
		font-size: 12px;
		color: var(--color-text-secondary);
	}

	.sort-select {
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		color: var(--color-text-primary);
		padding: 6px 10px;
		border-radius: 4px;
		font-size: 12px;
		outline: none;
	}

	/* Project Grid */
	.project-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
		gap: 16px;
	}

	.project-card {
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 10px;
		padding: 20px;
		text-decoration: none;
		color: inherit;
		transition: border-color 0.15s, box-shadow 0.15s;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.project-card:hover {
		border-color: var(--color-accent);
		box-shadow: 0 4px 16px rgba(122, 162, 247, 0.1);
	}

	.card-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
	}

	.card-title-row {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.card-title {
		font-size: 16px;
		font-weight: 600;
		margin: 0;
		color: var(--color-text-primary);
	}

	.status-badge {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.5px;
	}

	.card-pdk {
		font-size: 10px;
		font-weight: 600;
		background: var(--color-bg-primary);
		color: var(--color-accent);
		padding: 2px 8px;
		border-radius: 4px;
		letter-spacing: 0.3px;
	}

	.card-desc {
		font-size: 12px;
		color: var(--color-text-secondary);
		line-height: 1.5;
		margin: 0;
	}

	.card-footer {
		display: flex;
		justify-content: space-between;
		font-size: 11px;
		color: var(--color-text-secondary);
		opacity: 0.7;
	}

	.card-module {
		font-family: 'JetBrains Mono', monospace;
	}

	/* Modal */
	.modal-overlay {
		position: fixed;
		top: 0;
		left: 0;
		right: 0;
		bottom: 0;
		background: rgba(0, 0, 0, 0.6);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 200;
	}

	.modal {
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 12px;
		width: 420px;
		max-width: 90vw;
		box-shadow: 0 16px 48px rgba(0, 0, 0, 0.4);
	}

	.modal-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 16px 20px;
		border-bottom: 1px solid var(--color-border);
	}

	.modal-title {
		font-size: 16px;
		font-weight: 600;
		margin: 0;
	}

	.modal-close {
		background: none;
		border: none;
		color: var(--color-text-secondary);
		font-size: 16px;
		cursor: pointer;
		padding: 4px;
		border-radius: 4px;
	}

	.modal-close:hover {
		background: var(--color-bg-primary);
		color: var(--color-text-primary);
	}

	.modal-body {
		padding: 20px;
		display: flex;
		flex-direction: column;
		gap: 16px;
	}

	.form-group {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.form-label {
		font-size: 12px;
		font-weight: 500;
		color: var(--color-text-secondary);
	}

	.form-input {
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		color: var(--color-text-primary);
		padding: 8px 12px;
		border-radius: 6px;
		font-size: 13px;
		outline: none;
	}

	.form-input:focus {
		border-color: var(--color-accent);
	}

	.modal-footer {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 12px 20px;
		border-top: 1px solid var(--color-border);
	}
</style>
