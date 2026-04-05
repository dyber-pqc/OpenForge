<script lang="ts">
	/**
	 * File tree explorer with icons, context menu, and editor integration.
	 */

	import { fileTree, openFiles, activeFileIndex, type FileNode } from '$lib/stores/project';

	let contextMenu = $state<{ x: number; y: number; node: FileNode } | null>(null);
	let renamingPath = $state<string | null>(null);
	let renameValue = $state('');

	const FILE_ICONS: Record<string, { icon: string; color: string }> = {
		sv: { icon: 'SV', color: '#a6e3a1' },
		v: { icon: 'V', color: '#89b4fa' },
		vhd: { icon: 'VH', color: '#cba6f7' },
		vhdl: { icon: 'VH', color: '#cba6f7' },
		py: { icon: 'Py', color: '#f9e2af' },
		sdc: { icon: 'SD', color: '#fab387' },
		lib: { icon: 'LB', color: '#94e2d5' },
		def: { icon: 'DF', color: '#f5c2e7' },
		lef: { icon: 'LF', color: '#f5c2e7' },
		tcl: { icon: 'Tc', color: '#74c7ec' },
		yaml: { icon: 'YM', color: '#eba0ac' },
		yml: { icon: 'YM', color: '#eba0ac' },
		json: { icon: 'JS', color: '#f9e2af' },
		md: { icon: 'Md', color: '#89b4fa' },
		txt: { icon: 'Tx', color: '#a6adc8' },
		vcd: { icon: 'WF', color: '#a6e3a1' },
		fst: { icon: 'WF', color: '#a6e3a1' },
	};

	function getFileIcon(name: string): { icon: string; color: string } {
		const ext = name.split('.').pop()?.toLowerCase() ?? '';
		return FILE_ICONS[ext] ?? { icon: 'F', color: 'var(--color-text-secondary)' };
	}

	function getLanguage(name: string): string {
		const ext = name.split('.').pop()?.toLowerCase() ?? '';
		const langMap: Record<string, string> = {
			sv: 'systemverilog', v: 'verilog', vhd: 'vhdl', vhdl: 'vhdl',
			py: 'python', tcl: 'tcl', sdc: 'tcl', json: 'json',
			yaml: 'yaml', yml: 'yaml', md: 'markdown', txt: 'plaintext'
		};
		return langMap[ext] ?? 'plaintext';
	}

	let expandedDirs = $state<Set<string>>(new Set());

	function toggleDir(path: string) {
		const newSet = new Set(expandedDirs);
		if (newSet.has(path)) {
			newSet.delete(path);
		} else {
			newSet.add(path);
		}
		expandedDirs = newSet;
	}

	function openFile(node: FileNode) {
		// Check if already open
		const existing = $openFiles.findIndex((f) => f.path === node.path);
		if (existing >= 0) {
			activeFileIndex.set(existing);
			return;
		}

		// Open new tab with placeholder content
		openFiles.update((files) => [
			...files,
			{
				path: node.path,
				name: node.name,
				content: `// ${node.name}\n// Loading file content from server...`,
				language: getLanguage(node.name),
				modified: false
			}
		]);
		activeFileIndex.set($openFiles.length - 1);
	}

	function handleContextMenu(e: MouseEvent, node: FileNode) {
		e.preventDefault();
		contextMenu = { x: e.clientX, y: e.clientY, node };
	}

	function closeContextMenu() {
		contextMenu = null;
	}

	function handleContextAction(action: string) {
		if (!contextMenu) return;
		const node = contextMenu.node;

		switch (action) {
			case 'open':
				if (node.type === 'file') openFile(node);
				break;
			case 'rename':
				renamingPath = node.path;
				renameValue = node.name;
				break;
			case 'delete':
				// Would call API to delete
				break;
			case 'newFile':
				// Would call API to create file
				break;
			case 'newFolder':
				// Would call API to create folder
				break;
		}
		closeContextMenu();
	}

	// Close context menu on click outside
	function handleWindowClick() {
		if (contextMenu) closeContextMenu();
	}

	// Default demo file tree
	const defaultTree: FileNode[] = [
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
						{ name: 'top.sv', path: 'src/rtl/top.sv', type: 'file', language: 'systemverilog' },
						{ name: 'ntt_butterfly.sv', path: 'src/rtl/ntt_butterfly.sv', type: 'file', language: 'systemverilog' },
						{ name: 'keccak_core.sv', path: 'src/rtl/keccak_core.sv', type: 'file', language: 'systemverilog' },
						{ name: 'axi_slave.v', path: 'src/rtl/axi_slave.v', type: 'file', language: 'verilog' },
						{ name: 'key_manager.sv', path: 'src/rtl/key_manager.sv', type: 'file', language: 'systemverilog' },
					]
				},
				{
					name: 'tb',
					path: 'src/tb',
					type: 'directory',
					children: [
						{ name: 'tb_top.sv', path: 'src/tb/tb_top.sv', type: 'file', language: 'systemverilog' },
						{ name: 'ntt_tb.sv', path: 'src/tb/ntt_tb.sv', type: 'file', language: 'systemverilog' },
					]
				},
			]
		},
		{
			name: 'constraints',
			path: 'constraints',
			type: 'directory',
			children: [
				{ name: 'timing.sdc', path: 'constraints/timing.sdc', type: 'file', language: 'tcl' },
				{ name: 'pins.sdc', path: 'constraints/pins.sdc', type: 'file', language: 'tcl' },
			]
		},
		{
			name: 'lib',
			path: 'lib',
			type: 'directory',
			children: [
				{ name: 'sky130_fd_sc_hd.lib', path: 'lib/sky130_fd_sc_hd.lib', type: 'file' },
			]
		},
		{ name: 'openforge.yaml', path: 'openforge.yaml', type: 'file' },
	];

	let displayTree = $derived($fileTree.length > 0 ? $fileTree : defaultTree);
</script>

<svelte:window onclick={handleWindowClick} />

<div class="file-explorer">
	<div class="explorer-header">
		<span class="header-title">EXPLORER</span>
		<div class="header-actions">
			<button class="action-icon" title="New File" onclick={() => handleContextAction('newFile')}>+</button>
			<button class="action-icon" title="New Folder" onclick={() => handleContextAction('newFolder')}>D</button>
			<button class="action-icon" title="Refresh">R</button>
		</div>
	</div>

	<div class="tree-container">
		{#each displayTree as node}
			{@render treeNode(node, 0)}
		{/each}
	</div>
</div>

{#snippet treeNode(node: FileNode, depth: number)}
	<div
		class="tree-item"
		class:selected={false}
		style="padding-left: {depth * 16 + 8}px"
		ondblclick={() => node.type === 'file' && openFile(node)}
		oncontextmenu={(e) => handleContextMenu(e, node)}
		role="treeitem"
		tabindex="0"
	>
		{#if node.type === 'directory'}
			<button class="toggle-btn" onclick={() => toggleDir(node.path)}>
				{expandedDirs.has(node.path) ? '\u25BC' : '\u25B6'}
			</button>
			<span class="folder-icon">{expandedDirs.has(node.path) ? '\uD83D\uDCC2' : '\uD83D\uDCC1'}</span>
			<span class="node-name dir-name">{node.name}</span>
		{:else}
			<span class="toggle-spacer"></span>
			{@const fi = getFileIcon(node.name)}
			<span class="file-type-icon" style="color: {fi.color}">{fi.icon}</span>
			<span class="node-name">{node.name}</span>
		{/if}
	</div>
	{#if node.type === 'directory' && expandedDirs.has(node.path) && node.children}
		{#each node.children as child}
			{@render treeNode(child, depth + 1)}
		{/each}
	{/if}
{/snippet}

<!-- Context Menu -->
{#if contextMenu}
	<div
		class="context-menu"
		style="left: {contextMenu.x}px; top: {contextMenu.y}px"
		role="menu"
	>
		{#if contextMenu.node.type === 'file'}
			<button class="ctx-item" onclick={() => handleContextAction('open')} role="menuitem">Open</button>
			<button class="ctx-item" onclick={() => handleContextAction('open')} role="menuitem">Open to the Side</button>
			<div class="ctx-divider"></div>
		{/if}
		<button class="ctx-item" onclick={() => handleContextAction('newFile')} role="menuitem">New File</button>
		<button class="ctx-item" onclick={() => handleContextAction('newFolder')} role="menuitem">New Folder</button>
		<div class="ctx-divider"></div>
		<button class="ctx-item" onclick={() => handleContextAction('rename')} role="menuitem">Rename</button>
		<button class="ctx-item danger" onclick={() => handleContextAction('delete')} role="menuitem">Delete</button>
	</div>
{/if}

<style>
	.file-explorer {
		display: flex;
		flex-direction: column;
		height: 100%;
		font-size: 12px;
	}

	.explorer-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 12px;
		border-bottom: 1px solid var(--color-border);
		flex-shrink: 0;
	}

	.header-title {
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.8px;
		color: var(--color-text-secondary);
	}

	.header-actions {
		display: flex;
		gap: 2px;
	}

	.action-icon {
		background: none;
		border: none;
		color: var(--color-text-secondary);
		width: 22px;
		height: 22px;
		display: flex;
		align-items: center;
		justify-content: center;
		cursor: pointer;
		border-radius: 3px;
		font-size: 12px;
		font-weight: 600;
	}

	.action-icon:hover {
		background: var(--color-bg-primary);
		color: var(--color-text-primary);
	}

	.tree-container {
		flex: 1;
		overflow-y: auto;
		padding: 4px 0;
	}

	.tree-item {
		display: flex;
		align-items: center;
		gap: 4px;
		padding-top: 2px;
		padding-bottom: 2px;
		padding-right: 8px;
		cursor: pointer;
		user-select: none;
	}

	.tree-item:hover {
		background: rgba(255, 255, 255, 0.04);
	}

	.tree-item.selected {
		background: rgba(122, 162, 247, 0.12);
	}

	.toggle-btn {
		background: none;
		border: none;
		color: var(--color-text-secondary);
		font-size: 8px;
		cursor: pointer;
		width: 16px;
		height: 16px;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		padding: 0;
	}

	.toggle-spacer {
		width: 16px;
		flex-shrink: 0;
	}

	.folder-icon {
		font-size: 13px;
		flex-shrink: 0;
		width: 18px;
		text-align: center;
	}

	.file-type-icon {
		font-size: 9px;
		font-weight: 700;
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
		flex-shrink: 0;
		width: 18px;
		height: 16px;
		display: flex;
		align-items: center;
		justify-content: center;
		background: var(--color-bg-panel);
		border-radius: 2px;
	}

	.node-name {
		color: var(--color-text-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.dir-name {
		font-weight: 500;
	}

	/* Context Menu */
	.context-menu {
		position: fixed;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 6px;
		padding: 4px 0;
		min-width: 160px;
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
		z-index: 1000;
	}

	.ctx-item {
		display: block;
		width: 100%;
		background: none;
		border: none;
		color: var(--color-text-primary);
		padding: 6px 16px;
		font-size: 12px;
		text-align: left;
		cursor: pointer;
	}

	.ctx-item:hover {
		background: var(--color-accent);
		color: var(--color-bg-primary);
	}

	.ctx-item.danger:hover {
		background: var(--color-error);
	}

	.ctx-divider {
		height: 1px;
		background: var(--color-border);
		margin: 4px 0;
	}
</style>
