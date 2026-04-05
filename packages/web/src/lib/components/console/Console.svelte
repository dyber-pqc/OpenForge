<script lang="ts">
	import { consoleLines, appendConsole } from '$lib/stores/project';
	import { onMount, tick } from 'svelte';

	let scrollContainer: HTMLDivElement;
	let commandInput = $state('');

	const levelColors: Record<string, string> = {
		info: 'var(--color-accent)',
		warning: 'var(--color-warning)',
		error: 'var(--color-error)',
		success: 'var(--color-success)',
		debug: 'var(--color-text-secondary)'
	};

	async function scrollToBottom() {
		await tick();
		if (scrollContainer) {
			scrollContainer.scrollTop = scrollContainer.scrollHeight;
		}
	}

	function handleCommand(event: KeyboardEvent) {
		if (event.key === 'Enter' && commandInput.trim()) {
			appendConsole(`$ ${commandInput}`, 'debug');
			appendConsole(`Command not connected to backend yet.`, 'warning');
			commandInput = '';
		}
	}

	$effect(() => {
		$consoleLines;
		scrollToBottom();
	});
</script>

<div class="console-container">
	<div class="console-output" bind:this={scrollContainer}>
		{#each $consoleLines as line}
			<div class="console-line">
				<span class="timestamp">{new Date(line.timestamp).toLocaleTimeString()}</span>
				<span style="color: {levelColors[line.level]}">{line.text}</span>
			</div>
		{/each}
	</div>
	<div class="console-input">
		<span class="prompt">$</span>
		<input
			type="text"
			bind:value={commandInput}
			onkeydown={handleCommand}
			placeholder="Type a command..."
		/>
	</div>
</div>

<style>
	.console-container {
		display: flex;
		flex-direction: column;
		height: 100%;
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
		font-size: 12px;
	}

	.console-output {
		flex: 1;
		overflow-y: auto;
		padding: 8px 12px;
	}

	.console-line {
		display: flex;
		gap: 8px;
		line-height: 1.6;
	}

	.timestamp {
		color: var(--color-text-secondary);
		opacity: 0.5;
		font-size: 10px;
		flex-shrink: 0;
	}

	.console-input {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 12px;
		border-top: 1px solid var(--color-border);
		background: var(--color-bg-panel);
	}

	.prompt {
		color: var(--color-success);
		font-weight: 700;
	}

	.console-input input {
		flex: 1;
		background: none;
		border: none;
		color: var(--color-text-primary);
		font-family: inherit;
		font-size: inherit;
		outline: none;
	}

	.console-input input::placeholder {
		color: var(--color-text-secondary);
		opacity: 0.4;
	}
</style>
