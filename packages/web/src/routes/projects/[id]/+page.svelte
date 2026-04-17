<script lang="ts">
	/**
	 * Project detail page -- fetches project data and redirects to IDE view.
	 */

	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { currentProject, appendConsole, fileTree } from '$lib/stores/project';
	import { onMount } from 'svelte';
	import type { Project } from '$lib/api/client';

	let projectId = $derived($page.params.id ?? '');
	let loading = $state(true);
	let error = $state<string | null>(null);

	// Demo project data
	const demoProjects: Record<string, Project & { description: string }> = {
		'1': {
			id: '1',
			name: 'kyber-accelerator',
			top_module: 'kyber_top',
			target_pdk: 'SKY130',
			created_at: '2025-12-01T00:00:00Z',
			description: 'CRYSTALS-Kyber hardware accelerator'
		},
		'2': {
			id: '2',
			name: 'dilithium-sign',
			top_module: 'dilithium_top',
			target_pdk: 'GF180',
			created_at: '2025-11-15T00:00:00Z',
			description: 'CRYSTALS-Dilithium digital signature engine'
		},
		'3': {
			id: '3',
			name: 'aes-sbox-masked',
			top_module: 'aes_sbox',
			target_pdk: 'SKY130',
			created_at: '2025-10-20T00:00:00Z',
			description: 'DOM-masked AES S-box implementation'
		},
	};

	onMount(async () => {
		try {
			// Try API first, fall back to demo data
			const demo = demoProjects[projectId];
			if (demo) {
				currentProject.set(demo);
				appendConsole(`Loaded project: ${demo.name}`, 'success');

				// Set demo file tree
				fileTree.set([
					{
						name: 'src',
						path: 'src',
						type: 'directory',
						children: [
							{
								name: 'rtl',
								path: 'src/rtl',
								type: 'directory',
								children: [
									{ name: `${demo.top_module}.sv`, path: `src/rtl/${demo.top_module}.sv`, type: 'file' },
									{ name: 'ntt_butterfly.sv', path: 'src/rtl/ntt_butterfly.sv', type: 'file' },
									{ name: 'keccak_core.sv', path: 'src/rtl/keccak_core.sv', type: 'file' },
								]
							},
							{
								name: 'tb',
								path: 'src/tb',
								type: 'directory',
								children: [
									{ name: `tb_${demo.top_module}.sv`, path: `src/tb/tb_${demo.top_module}.sv`, type: 'file' },
								]
							}
						]
					},
					{
						name: 'constraints',
						path: 'constraints',
						type: 'directory',
						children: [
							{ name: 'timing.sdc', path: 'constraints/timing.sdc', type: 'file' },
						]
					},
					{ name: 'openforge.yaml', path: 'openforge.yaml', type: 'file' },
				]);

				// Navigate to IDE view with project loaded
				goto('/');
			} else {
				error = `Project not found: ${projectId}`;
			}
		} catch (e) {
			error = `Failed to load project: ${e}`;
		} finally {
			loading = false;
		}
	});
</script>

<svelte:head>
	<title>Loading Project - OpenForge EDA</title>
</svelte:head>

<div class="loading-page">
	{#if loading}
		<div class="loading-content">
			<div class="spinner-large"></div>
			<p class="loading-text">Loading project...</p>
			<p class="loading-id">ID: {projectId}</p>
		</div>
	{:else if error}
		<div class="error-content">
			<div class="error-icon">!</div>
			<p class="error-text">{error}</p>
			<a href="/projects" class="back-link">Back to Projects</a>
		</div>
	{/if}
</div>

<style>
	.loading-page {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		background: var(--color-bg-primary);
	}

	.loading-content, .error-content {
		text-align: center;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 12px;
	}

	.spinner-large {
		width: 40px;
		height: 40px;
		border: 3px solid var(--color-border);
		border-top-color: var(--color-accent);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	.loading-text {
		font-size: 16px;
		color: var(--color-text-primary);
		margin: 0;
	}

	.loading-id {
		font-size: 12px;
		color: var(--color-text-secondary);
		font-family: 'JetBrains Mono', monospace;
		margin: 0;
	}

	.error-icon {
		width: 48px;
		height: 48px;
		border-radius: 50%;
		background: var(--color-error);
		color: white;
		font-size: 24px;
		font-weight: 700;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.error-text {
		font-size: 14px;
		color: var(--color-text-primary);
		margin: 0;
	}

	.back-link {
		color: var(--color-accent);
		text-decoration: none;
		font-size: 13px;
	}

	.back-link:hover {
		text-decoration: underline;
	}
</style>
