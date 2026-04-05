<script lang="ts">
	/**
	 * Reusable resizable panel with draggable divider.
	 * Supports horizontal and vertical orientations with min/max constraints.
	 */

	type Direction = 'horizontal' | 'vertical';

	let {
		direction = 'horizontal',
		initialSize = 250,
		minSize = 100,
		maxSize = 600,
		collapsed = false,
		storageKey = '',
		side = 'start',
		children,
		panel
	}: {
		direction?: Direction;
		initialSize?: number;
		minSize?: number;
		maxSize?: number;
		collapsed?: boolean;
		storageKey?: string;
		side?: 'start' | 'end';
		children: import('svelte').Snippet;
		panel: import('svelte').Snippet;
	} = $props();

	let size = $state(initialSize);
	let isCollapsed = $state(collapsed);
	let isDragging = $state(false);
	let containerEl: HTMLDivElement;

	// Restore from localStorage
	$effect(() => {
		if (storageKey) {
			const saved = localStorage.getItem(`panel-${storageKey}`);
			if (saved) {
				const parsed = JSON.parse(saved);
				size = parsed.size ?? initialSize;
				isCollapsed = parsed.collapsed ?? collapsed;
			}
		}
	});

	// Persist to localStorage
	function persist() {
		if (storageKey) {
			localStorage.setItem(`panel-${storageKey}`, JSON.stringify({ size, collapsed: isCollapsed }));
		}
	}

	function onPointerDown(e: PointerEvent) {
		e.preventDefault();
		isDragging = true;
		const target = e.currentTarget as HTMLElement;
		target.setPointerCapture(e.pointerId);
	}

	function onPointerMove(e: PointerEvent) {
		if (!isDragging || !containerEl) return;
		const rect = containerEl.getBoundingClientRect();

		let newSize: number;
		if (direction === 'horizontal') {
			if (side === 'start') {
				newSize = e.clientX - rect.left;
			} else {
				newSize = rect.right - e.clientX;
			}
		} else {
			if (side === 'start') {
				newSize = e.clientY - rect.top;
			} else {
				newSize = rect.bottom - e.clientY;
			}
		}

		size = Math.max(minSize, Math.min(maxSize, newSize));
	}

	function onPointerUp() {
		if (isDragging) {
			isDragging = false;
			persist();
		}
	}

	function toggleCollapse() {
		isCollapsed = !isCollapsed;
		persist();
	}

	let panelStyle = $derived(
		isCollapsed
			? 'display: none;'
			: direction === 'horizontal'
				? `width: ${size}px; min-width: ${minSize}px; max-width: ${maxSize}px;`
				: `height: ${size}px; min-height: ${minSize}px; max-height: ${maxSize}px;`
	);

	let containerClass = $derived(
		`resizable-container ${direction} side-${side}${isDragging ? ' dragging' : ''}`
	);
</script>

<div class={containerClass} bind:this={containerEl}>
	{#if side === 'start'}
		{#if !isCollapsed}
			<div class="resizable-panel" style={panelStyle}>
				{@render panel()}
			</div>
			<div
				class="divider {direction}"
				role="separator"
				tabindex="0"
				onpointerdown={onPointerDown}
				onpointermove={onPointerMove}
				onpointerup={onPointerUp}
			>
				<button class="collapse-btn" onclick={toggleCollapse} title="Collapse panel">
					{direction === 'horizontal' ? '\u25C0' : '\u25B2'}
				</button>
			</div>
		{:else}
			<button class="expand-btn {direction}" onclick={toggleCollapse} title="Expand panel">
				{direction === 'horizontal' ? '\u25B6' : '\u25BC'}
			</button>
		{/if}
		<div class="resizable-content">
			{@render children()}
		</div>
	{:else}
		<div class="resizable-content">
			{@render children()}
		</div>
		{#if !isCollapsed}
			<div
				class="divider {direction}"
				role="separator"
				tabindex="0"
				onpointerdown={onPointerDown}
				onpointermove={onPointerMove}
				onpointerup={onPointerUp}
			>
				<button class="collapse-btn" onclick={toggleCollapse} title="Collapse panel">
					{direction === 'horizontal' ? '\u25B6' : '\u25BC'}
				</button>
			</div>
			<div class="resizable-panel" style={panelStyle}>
				{@render panel()}
			</div>
		{:else}
			<button class="expand-btn {direction}" onclick={toggleCollapse} title="Expand panel">
				{direction === 'horizontal' ? '\u25C0' : '\u25B2'}
			</button>
		{/if}
	{/if}
</div>

<style>
	.resizable-container {
		display: flex;
		flex: 1;
		overflow: hidden;
	}

	.resizable-container.horizontal {
		flex-direction: row;
	}

	.resizable-container.vertical {
		flex-direction: column;
	}

	.resizable-container.dragging {
		cursor: col-resize;
		user-select: none;
	}

	.resizable-container.vertical.dragging {
		cursor: row-resize;
	}

	.resizable-panel {
		flex-shrink: 0;
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}

	.resizable-content {
		flex: 1;
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}

	.divider {
		flex-shrink: 0;
		background: var(--color-border);
		position: relative;
		z-index: 10;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.divider.horizontal {
		width: 3px;
		cursor: col-resize;
	}

	.divider.vertical {
		height: 3px;
		cursor: row-resize;
	}

	.divider:hover {
		background: var(--color-accent);
	}

	.collapse-btn {
		position: absolute;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		color: var(--color-text-secondary);
		font-size: 8px;
		width: 16px;
		height: 16px;
		border-radius: 3px;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		opacity: 0;
		transition: opacity 0.15s;
		z-index: 11;
	}

	.divider:hover .collapse-btn {
		opacity: 1;
	}

	.collapse-btn:hover {
		background: var(--color-accent);
		color: var(--color-bg-primary);
	}

	.expand-btn {
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		color: var(--color-text-secondary);
		font-size: 8px;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.expand-btn.horizontal {
		width: 16px;
		writing-mode: vertical-lr;
		padding: 8px 2px;
	}

	.expand-btn.vertical {
		height: 16px;
		padding: 2px 8px;
	}

	.expand-btn:hover {
		background: var(--color-accent);
		color: var(--color-bg-primary);
	}
</style>
