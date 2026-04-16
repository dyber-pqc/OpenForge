<script lang="ts">
  import { onDestroy } from 'svelte';
  import { api } from '$lib/api/openforge';
  import { updateJob } from '$lib/stores/jobs';

  export let projectId: string;
  export let defaultTop: string = 'top';

  let topModule = defaultTop;
  let sources = '';
  let pdk = 'sky130';
  let isRunning = false;
  let currentJobId: string | null = null;
  let logLines: string[] = [];
  let errorMessage = '';
  let logWs: WebSocket | null = null;

  async function runSynthesis() {
    errorMessage = '';
    logLines = [];
    isRunning = true;

    const sourceList = sources
      .split('\n')
      .map((s) => s.trim())
      .filter((s) => s.length > 0);

    if (sourceList.length === 0) {
      errorMessage = 'Add at least one source file.';
      isRunning = false;
      return;
    }

    try {
      const result = await api.submitSynthesis(projectId, topModule, sourceList, pdk);
      currentJobId = result.job_id;

      logWs = api.connectJobLog(currentJobId, (line) => {
        logLines = [...logLines, line];
      });

      logWs.onclose = () => {
        isRunning = false;
      };
      logWs.onerror = () => {
        isRunning = false;
      };
    } catch (err) {
      errorMessage = err instanceof Error ? err.message : String(err);
      isRunning = false;
    }
  }

  function clearLog() {
    logLines = [];
  }

  onDestroy(() => {
    logWs?.close();
  });
</script>

<div class="synth-runner">
  <h2>Synthesis</h2>

  <label>
    Top Module
    <input type="text" bind:value={topModule} disabled={isRunning} />
  </label>

  <label>
    PDK
    <select bind:value={pdk} disabled={isRunning}>
      <option value="sky130">Sky130</option>
      <option value="gf180">GF180</option>
      <option value="ihp-sg13g2">IHP SG13G2</option>
    </select>
  </label>

  <label>
    Source Files (one per line)
    <textarea bind:value={sources} rows="6" disabled={isRunning}
      placeholder="rtl/top.v&#10;rtl/alu.v"></textarea>
  </label>

  <div class="actions">
    <button on:click={runSynthesis} disabled={isRunning}>
      {isRunning ? 'Running...' : 'Run Synthesis'}
    </button>
    <button on:click={clearLog} disabled={isRunning || logLines.length === 0} class="secondary">
      Clear Log
    </button>
  </div>

  {#if errorMessage}
    <div class="error">{errorMessage}</div>
  {/if}

  {#if currentJobId}
    <div class="job-id">Job: <code>{currentJobId}</code></div>
  {/if}

  {#if logLines.length > 0}
    <pre class="log">{#each logLines as line}{line}
{/each}</pre>
  {/if}
</div>

<style>
  .synth-runner {
    background: #1e1e2e;
    color: #cdd6f4;
    padding: 1rem;
    border-radius: 8px;
    font-family: system-ui, sans-serif;
  }
  h2 {
    margin-top: 0;
    color: #89b4fa;
  }
  label {
    display: block;
    margin: 0.75rem 0;
    font-size: 0.9rem;
  }
  input,
  textarea,
  select {
    display: block;
    width: 100%;
    margin-top: 0.25rem;
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 0.5rem;
    font-family: inherit;
  }
  textarea {
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.85rem;
  }
  .actions {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.75rem;
  }
  button {
    background: #89b4fa;
    color: #1e1e2e;
    border: none;
    padding: 0.5rem 1.5rem;
    border-radius: 4px;
    cursor: pointer;
    font-weight: 600;
  }
  button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  button.secondary {
    background: #45475a;
    color: #cdd6f4;
  }
  .error {
    background: #f38ba8;
    color: #1e1e2e;
    padding: 0.5rem;
    border-radius: 4px;
    margin-top: 0.75rem;
  }
  .job-id {
    margin-top: 0.75rem;
    font-size: 0.85rem;
    color: #a6adc8;
  }
  .job-id code {
    background: #313244;
    padding: 0.15rem 0.4rem;
    border-radius: 3px;
  }
  .log {
    background: #11111b;
    padding: 1rem;
    border-radius: 4px;
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 11px;
    max-height: 400px;
    overflow-y: auto;
    margin-top: 0.75rem;
    white-space: pre-wrap;
  }
</style>
