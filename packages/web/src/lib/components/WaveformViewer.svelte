<script lang="ts">
  export interface WaveValue {
    time: number;
    value: string;
  }
  export interface Signal {
    name: string;
    values: WaveValue[];
  }

  export let signals: Signal[] = [];
  export let timeStart = 0;
  export let timeEnd = 100;
  export let timeUnit = 'ns';

  const ROW_HEIGHT = 30;
  const NAME_WIDTH = 120;
  const HEADER_HEIGHT = 40;

  let width = 800;
  let container: HTMLDivElement;

  $: pxPerNs = (width - NAME_WIDTH) / Math.max(1, timeEnd - timeStart);
  $: svgHeight = signals.length * ROW_HEIGHT + HEADER_HEIGHT;
  $: gridTicks = computeTicks(timeStart, timeEnd);

  function computeTicks(start: number, end: number): number[] {
    const span = end - start;
    const step = Math.max(1, Math.round(span / 10));
    const ticks: number[] = [];
    for (let t = start; t <= end; t += step) ticks.push(t);
    return ticks;
  }

  function timeToX(t: number): number {
    return NAME_WIDTH + (t - timeStart) * pxPerNs;
  }

  function colorFor(value: string): string {
    if (value === 'x' || value === 'X') return '#f38ba8';
    if (value === 'z' || value === 'Z') return '#f9e2af';
    return '#a6e3a1';
  }

  function zoomIn() {
    const mid = (timeStart + timeEnd) / 2;
    const half = (timeEnd - timeStart) / 4;
    timeStart = Math.max(0, mid - half);
    timeEnd = mid + half;
  }
  function zoomOut() {
    const mid = (timeStart + timeEnd) / 2;
    const half = (timeEnd - timeStart);
    timeStart = Math.max(0, mid - half);
    timeEnd = mid + half;
  }
  function resetZoom() {
    timeStart = 0;
    let maxT = 100;
    for (const sig of signals) {
      for (const v of sig.values) if (v.time > maxT) maxT = v.time;
    }
    timeEnd = maxT;
  }

  function onResize() {
    if (container) width = container.clientWidth;
  }
</script>

<svelte:window on:resize={onResize} />

<div class="waveform-viewer" bind:this={container}>
  <div class="toolbar">
    <button on:click={zoomIn}>Zoom In</button>
    <button on:click={zoomOut}>Zoom Out</button>
    <button on:click={resetZoom}>Fit</button>
    <span class="range">{timeStart.toFixed(0)} - {timeEnd.toFixed(0)} {timeUnit}</span>
    <span class="count">{signals.length} signals</span>
  </div>

  <svg viewBox={`0 0 ${width} ${svgHeight}`} class="waveform" preserveAspectRatio="none">
    <!-- Name gutter -->
    <rect x="0" y="0" width={NAME_WIDTH} height={svgHeight} fill="#181825" />
    <line x1={NAME_WIDTH} y1="0" x2={NAME_WIDTH} y2={svgHeight} stroke="#45475a" />

    <!-- Time axis -->
    <line x1={NAME_WIDTH} y1={HEADER_HEIGHT - 5} x2={width} y2={HEADER_HEIGHT - 5} stroke="#6c7086" />
    {#each gridTicks as t}
      {@const x = timeToX(t)}
      <line x1={x} y1={HEADER_HEIGHT - 10} x2={x} y2={svgHeight} stroke="#313244" stroke-width="1" />
      <text x={x + 2} y={HEADER_HEIGHT - 12} fill="#a6adc8" font-size="9" font-family="monospace">
        {t}
      </text>
    {/each}

    <!-- Signals -->
    {#each signals as sig, i}
      {@const rowY = HEADER_HEIGHT + i * ROW_HEIGHT}

      <rect x="0" y={rowY} width={NAME_WIDTH - 1} height={ROW_HEIGHT}
        fill={i % 2 === 0 ? '#1e1e2e' : '#181825'} />
      <text x="8" y={rowY + ROW_HEIGHT / 2 + 4} fill="#cdd6f4"
        font-family="monospace" font-size="11">{sig.name}</text>

      {#each sig.values as v, j}
        {@const x = timeToX(v.time)}
        {@const nextX =
          j + 1 < sig.values.length ? timeToX(sig.values[j + 1].time) : width}
        {@const yHigh = rowY + 5}
        {@const yLow = rowY + ROW_HEIGHT - 5}
        {@const c = colorFor(v.value)}

        {#if v.value === '1'}
          <line x1={x} y1={yHigh} x2={nextX} y2={yHigh} stroke={c} stroke-width="2" />
          <line x1={x} y1={yHigh} x2={x} y2={yLow} stroke={c} stroke-width="1" />
        {:else if v.value === '0'}
          <line x1={x} y1={yLow} x2={nextX} y2={yLow} stroke={c} stroke-width="2" />
          <line x1={x} y1={yHigh} x2={x} y2={yLow} stroke={c} stroke-width="1" />
        {:else}
          <!-- Bus / unknown: hex-like shape -->
          <line x1={x} y1={yHigh} x2={nextX} y2={yHigh} stroke={c} stroke-width="1.5" />
          <line x1={x} y1={yLow} x2={nextX} y2={yLow} stroke={c} stroke-width="1.5" />
          <text x={x + 3} y={rowY + ROW_HEIGHT / 2 + 4} fill={c}
            font-family="monospace" font-size="9">{v.value}</text>
        {/if}
      {/each}

      <line x1={NAME_WIDTH} y1={rowY + ROW_HEIGHT} x2={width} y2={rowY + ROW_HEIGHT}
        stroke="#313244" />
    {/each}
  </svg>
</div>

<style>
  .waveform-viewer {
    background: #1e1e2e;
    border-radius: 8px;
    padding: 0.5rem;
    color: #cdd6f4;
    font-family: system-ui, sans-serif;
  }
  .toolbar {
    display: flex;
    gap: 0.5rem;
    align-items: center;
    padding: 0.5rem;
    border-bottom: 1px solid #313244;
  }
  .toolbar button {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    padding: 0.3rem 0.75rem;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.8rem;
  }
  .toolbar button:hover {
    background: #45475a;
  }
  .range {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    color: #a6adc8;
  }
  .count {
    margin-left: auto;
    font-size: 0.75rem;
    color: #6c7086;
  }
  .waveform {
    display: block;
    width: 100%;
    background: #1e1e2e;
  }
</style>
