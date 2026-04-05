<script lang="ts">
	interface ModuleNode {
		name: string;
		type: string;
		children?: ModuleNode[];
		expanded?: boolean;
	}

	let modules = $state<ModuleNode[]>([
		{
			name: 'top',
			type: 'module',
			expanded: true,
			children: [
				{
					name: 'ntt_butterfly',
					type: 'module',
					children: [
						{ name: 'mult_stage', type: 'module' },
						{ name: 'mod_reduce', type: 'module' }
					]
				},
				{
					name: 'keccak_core',
					type: 'module',
					children: [
						{ name: 'theta', type: 'module' },
						{ name: 'rho_pi', type: 'module' },
						{ name: 'chi_iota', type: 'module' }
					]
				},
				{ name: 'axi_slave', type: 'module' },
				{ name: 'key_manager', type: 'module' }
			]
		}
	]);

	function toggle(node: ModuleNode) {
		node.expanded = !node.expanded;
		modules = [...modules]; // trigger reactivity
	}
</script>

<div class="hierarchy">
	{#each modules as node}
		{@render moduleTree(node, 0)}
	{/each}
</div>

{#snippet moduleTree(node: ModuleNode, depth: number)}
	<div class="tree-node" style="padding-left: {depth * 16 + 8}px">
		{#if node.children?.length}
			<button class="toggle" onclick={() => toggle(node)}>
				{node.expanded ? '\u25BC' : '\u25B6'}
			</button>
		{:else}
			<span class="spacer"></span>
		{/if}
		<span class="icon">M</span>
		<span class="name">{node.name}</span>
	</div>
	{#if node.expanded && node.children}
		{#each node.children as child}
			{@render moduleTree(child, depth + 1)}
		{/each}
	{/if}
{/snippet}

<style>
	.hierarchy {
		font-size: 12px;
		padding: 4px 0;
	}

	.tree-node {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 2px 0;
		cursor: pointer;
	}

	.tree-node:hover {
		background: var(--color-bg-primary);
	}

	.toggle {
		background: none;
		border: none;
		color: var(--color-text-secondary);
		font-size: 8px;
		cursor: pointer;
		width: 14px;
		text-align: center;
		padding: 0;
	}

	.spacer {
		width: 14px;
	}

	.icon {
		color: var(--color-accent);
		font-size: 10px;
		font-weight: 700;
		width: 16px;
		height: 16px;
		display: flex;
		align-items: center;
		justify-content: center;
		background: var(--color-bg-panel);
		border-radius: 3px;
	}

	.name {
		color: var(--color-text-primary);
	}
</style>
