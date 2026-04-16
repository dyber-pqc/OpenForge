<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import {
    jobs,
    jobList,
    runningJobs,
    queuedJobs,
    completedJobs,
    failedJobs,
    updateJob,
    clearAllFinished,
  } from '$lib/stores/jobs';
  import { api } from '$lib/api/openforge';

  let ws: WebSocket | null = null;
  let connected = false;
  let filter: 'all' | 'running' | 'completed' | 'failed' = 'all';

  onMount(() => {
    ws = api.connectJobUpdates(updateJob);
    ws.onopen = () => (connected = true);
    ws.onclose = () => (connected = false);
    ws.onerror = () => (connected = false);
  });

  onDestroy(() => {
    ws?.close();
  });

  async function cancelJob(id: string) {
    try {
      await api.cancelJob(id);
    } catch (err) {
      console.error('cancel failed', err);
    }
  }

  function formatTime(ts?: string): string {
    if (!ts) return '-';
    try {
      return new Date(ts).toLocaleTimeString();
    } catch {
      return ts;
    }
  }

  $: filteredJobs = (() => {
    if (filter === 'running') return $runningJobs;
    if (filter === 'completed') return $completedJobs;
    if (filter === 'failed') return $failedJobs;
    return $jobList;
  })();
</script>

<div class="dashboard">
  <header>
    <h2>Job Dashboard</h2>
    <div class="status-dot" class:on={connected} title={connected ? 'Connected' : 'Disconnected'}></div>
  </header>

  <div class="summary">
    <div class="card queued">
      <div class="count">{$queuedJobs.length}</div>
      <div class="label">Queued</div>
    </div>
    <div class="card running">
      <div class="count">{$runningJobs.length}</div>
      <div class="label">Running</div>
    </div>
    <div class="card completed">
      <div class="count">{$completedJobs.length}</div>
      <div class="label">Completed</div>
    </div>
    <div class="card failed">
      <div class="count">{$failedJobs.length}</div>
      <div class="label">Failed</div>
    </div>
  </div>

  <div class="filters">
    <button class:active={filter === 'all'} on:click={() => (filter = 'all')}>All</button>
    <button class:active={filter === 'running'} on:click={() => (filter = 'running')}>Running</button>
    <button class:active={filter === 'completed'} on:click={() => (filter = 'completed')}>Completed</button>
    <button class:active={filter === 'failed'} on:click={() => (filter = 'failed')}>Failed</button>
    <button class="clear" on:click={clearAllFinished}>Clear Finished</button>
  </div>

  <div class="jobs">
    {#each filteredJobs as job (job.id)}
      <div class="job">
        <div class="job-head">
          <span class="type">{job.type}</span>
          <span class="status {job.status}">{job.status}</span>
          <span class="id">{job.id.slice(0, 8)}</span>
          <span class="time">{formatTime(job.created_at)}</span>
          {#if job.status === 'running' || job.status === 'queued'}
            <button class="cancel" on:click={() => cancelJob(job.id)}>Cancel</button>
          {/if}
        </div>
        {#if job.status === 'running'}
          <progress value={job.progress} max="1"></progress>
        {/if}
        {#if job.error}
          <div class="err">{job.error}</div>
        {/if}
      </div>
    {:else}
      <div class="empty">No jobs.</div>
    {/each}
  </div>
</div>

<style>
  .dashboard {
    color: #cdd6f4;
    font-family: system-ui, sans-serif;
    background: #1e1e2e;
    padding: 1rem;
    border-radius: 8px;
  }
  header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
  h2 {
    margin: 0;
    color: #89b4fa;
  }
  .status-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #f38ba8;
  }
  .status-dot.on {
    background: #a6e3a1;
  }
  .summary {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.5rem;
    margin: 1rem 0;
  }
  .card {
    background: #313244;
    padding: 0.75rem;
    border-radius: 6px;
    text-align: center;
  }
  .card .count {
    font-size: 1.5rem;
    font-weight: 700;
  }
  .card .label {
    font-size: 0.75rem;
    text-transform: uppercase;
    color: #a6adc8;
  }
  .card.running .count { color: #f9e2af; }
  .card.completed .count { color: #a6e3a1; }
  .card.failed .count { color: #f38ba8; }
  .card.queued .count { color: #89b4fa; }

  .filters {
    display: flex;
    gap: 0.25rem;
    margin-bottom: 0.75rem;
  }
  .filters button {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    padding: 0.35rem 0.75rem;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.8rem;
  }
  .filters button.active {
    background: #89b4fa;
    color: #1e1e2e;
    border-color: #89b4fa;
  }
  .filters .clear {
    margin-left: auto;
  }

  .jobs {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }
  .job {
    background: #313244;
    padding: 0.6rem;
    border-radius: 4px;
  }
  .job-head {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    font-size: 0.85rem;
  }
  .type {
    font-weight: 600;
    color: #89b4fa;
    min-width: 110px;
  }
  .id {
    font-family: 'JetBrains Mono', monospace;
    color: #a6adc8;
    font-size: 0.75rem;
  }
  .time {
    color: #a6adc8;
    font-size: 0.75rem;
    margin-left: auto;
  }
  .status {
    padding: 0.15rem 0.5rem;
    border-radius: 10px;
    font-size: 0.7rem;
    text-transform: uppercase;
    background: #45475a;
  }
  .status.running { background: #f9e2af; color: #1e1e2e; }
  .status.completed { background: #a6e3a1; color: #1e1e2e; }
  .status.failed { background: #f38ba8; color: #1e1e2e; }
  .status.queued { background: #89b4fa; color: #1e1e2e; }
  .status.cancelled { background: #6c7086; color: #cdd6f4; }
  progress {
    width: 100%;
    margin-top: 0.35rem;
    height: 4px;
  }
  .err {
    margin-top: 0.35rem;
    color: #f38ba8;
    font-size: 0.75rem;
    font-family: 'JetBrains Mono', monospace;
  }
  .cancel {
    background: #f38ba8;
    color: #1e1e2e;
    border: none;
    padding: 0.2rem 0.5rem;
    border-radius: 3px;
    cursor: pointer;
    font-size: 0.7rem;
  }
  .empty {
    color: #6c7086;
    text-align: center;
    padding: 2rem;
    font-style: italic;
  }
</style>
