<script lang="ts">
	import { openFiles, activeFileIndex, activeFile } from '$lib/stores/project';

	function selectTab(index: number) {
		activeFileIndex.set(index);
	}

	function closeTab(index: number, event: MouseEvent) {
		event.stopPropagation();
		openFiles.update((files) => {
			const updated = [...files];
			updated.splice(index, 1);
			return updated;
		});
		// Adjust active index
		activeFileIndex.update((i) => (i >= index && i > 0 ? i - 1 : i));
	}
</script>

<div class="editor-container">
	{#if $openFiles.length > 0}
		<!-- Tab bar -->
		<div class="tab-bar">
			{#each $openFiles as file, i}
				<button
					class="tab"
					class:active={i === $activeFileIndex}
					onclick={() => selectTab(i)}
				>
					<span class="tab-name">{file.name}</span>
					{#if file.modified}
						<span class="modified-dot"></span>
					{/if}
					<button class="tab-close" onclick={(e) => closeTab(i, e)}>x</button>
				</button>
			{/each}
		</div>

		<!-- Editor area -->
		<div class="editor-content">
			{#if $activeFile}
				<!-- Monaco editor will be mounted here -->
				<pre class="code-preview">{$activeFile.content}</pre>
			{/if}
		</div>
	{:else}
		<div class="empty-state">
			<p>No files open</p>
			<p class="hint">Open a file from the Project Explorer</p>
		</div>
	{/if}
</div>

<style>
	.editor-container {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: var(--color-bg-primary);
	}

	.tab-bar {
		display: flex;
		background: var(--color-bg-panel);
		border-bottom: 1px solid var(--color-border);
		overflow-x: auto;
		flex-shrink: 0;
	}

	.tab {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 6px 12px;
		background: none;
		border: none;
		border-right: 1px solid var(--color-border);
		color: var(--color-text-secondary);
		font-size: 12px;
		cursor: pointer;
		white-space: nowrap;
	}

	.tab.active {
		background: var(--color-bg-primary);
		color: var(--color-text-primary);
		border-bottom: 2px solid var(--color-accent);
	}

	.tab-close {
		background: none;
		border: none;
		color: var(--color-text-secondary);
		font-size: 10px;
		cursor: pointer;
		padding: 0 2px;
		border-radius: 2px;
	}

	.tab-close:hover {
		background: var(--color-border);
		color: var(--color-error);
	}

	.modified-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--color-warning);
	}

	.editor-content {
		flex: 1;
		overflow: auto;
	}

	.code-preview {
		margin: 0;
		padding: 12px;
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
		font-size: 13px;
		line-height: 1.5;
		color: var(--color-text-primary);
		tab-size: 4;
	}

	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--color-text-secondary);
		gap: 8px;
	}

	.hint {
		font-size: 12px;
		opacity: 0.6;
	}
</style>
