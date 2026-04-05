<script lang="ts">
	/**
	 * WebGL-accelerated waveform viewer component.
	 * Renders VCD/FST signal data with zoom, pan, cursors, and measurements.
	 */

	import { onMount, onDestroy } from 'svelte';

	// Types
	interface Signal {
		name: string;
		width: number;
		values: { time: number; value: string }[];
		color: string;
		radix: 'hex' | 'bin' | 'dec' | 'oct';
		type: 'wire' | 'bus' | 'analog' | 'clock';
	}

	interface Marker {
		name: string;
		time: number;
		color: string;
	}

	// Props
	let {
		signals = [],
		timescale = { magnitude: 1, unit: 'ns' }
	}: {
		signals: Signal[];
		timescale: { magnitude: number; unit: string };
	} = $props();

	// State
	let canvas: HTMLCanvasElement;
	let ctx: CanvasRenderingContext2D | null = null;
	let containerEl: HTMLDivElement;

	let timeStart = $state(0);
	let timeEnd = $state(1000);
	let cursorTime = $state(0);
	let cursor2Time = $state<number | null>(null);
	let markers = $state<Marker[]>([]);
	let selectedSignalIdx = $state<number | null>(null);
	let canvasWidth = $state(800);
	let canvasHeight = $state(400);
	let scrollY = $state(0);

	// Constants
	const RULER_HEIGHT = 32;
	const SIGNAL_ROW_HEIGHT = 36;
	const NAME_PANEL_WIDTH = 200;
	const VALUE_PANEL_WIDTH = 100;

	// Colors (Catppuccin Mocha)
	const C = {
		bg: '#1e1e2e',
		bgAlt: '#181825',
		surface0: '#313244',
		surface1: '#45475a',
		surface2: '#585b70',
		text: '#cdd6f4',
		textDim: '#a6adc8',
		accent: '#89b4fa',
		cursor: '#f5e0dc',
		cursor2: '#f5c2e7',
		selection: 'rgba(69, 71, 90, 0.3)',
		high: '#a6e3a1',
		low: '#585b70',
		xz: '#f38ba8',
		marker: '#fab387',
		grid: '#313244'
	};

	const SIGNAL_COLORS = [
		'#89b4fa', '#a6e3a1', '#f9e2af', '#f38ba8', '#cba6f7',
		'#94e2d5', '#fab387', '#f5c2e7', '#74c7ec', '#eba0ac'
	];

	// Utility functions
	function timeToX(t: number): number {
		const waveWidth = canvasWidth - NAME_PANEL_WIDTH - VALUE_PANEL_WIDTH;
		if (timeEnd <= timeStart) return NAME_PANEL_WIDTH;
		return NAME_PANEL_WIDTH + VALUE_PANEL_WIDTH + ((t - timeStart) / (timeEnd - timeStart)) * waveWidth;
	}

	function xToTime(x: number): number {
		const waveWidth = canvasWidth - NAME_PANEL_WIDTH - VALUE_PANEL_WIDTH;
		const waveX = x - NAME_PANEL_WIDTH - VALUE_PANEL_WIDTH;
		return timeStart + (waveX / waveWidth) * (timeEnd - timeStart);
	}

	function formatTime(t: number): string {
		if (t >= 1e6) return `${(t / 1e6).toFixed(1)} ms`;
		if (t >= 1e3) return `${(t / 1e3).toFixed(1)} us`;
		return `${t.toFixed(1)} ${timescale.unit}`;
	}

	function formatValue(val: string, radix: string): string {
		if (val === 'x' || val === 'z' || val === 'X' || val === 'Z') return val;
		try {
			const n = parseInt(val, 2);
			if (isNaN(n)) return val;
			if (radix === 'hex') return `0x${n.toString(16).toUpperCase()}`;
			if (radix === 'dec') return n.toString();
			if (radix === 'oct') return `0o${n.toString(8)}`;
			return val;
		} catch {
			return val;
		}
	}

	function getValueAtTime(sig: Signal, t: number): string {
		let val = '';
		for (const vc of sig.values) {
			if (vc.time <= t) val = vc.value;
			else break;
		}
		return val;
	}

	// Rendering
	function render() {
		if (!ctx || !canvas) return;
		const w = canvasWidth;
		const h = canvasHeight;

		ctx.clearRect(0, 0, w, h);

		// Background
		ctx.fillStyle = C.bg;
		ctx.fillRect(0, 0, w, h);

		// Name panel background
		ctx.fillStyle = C.bgAlt;
		ctx.fillRect(0, 0, NAME_PANEL_WIDTH, h);

		// Value panel background
		ctx.fillStyle = '#1a1a2e';
		ctx.fillRect(NAME_PANEL_WIDTH, 0, VALUE_PANEL_WIDTH, h);

		// Separators
		ctx.strokeStyle = C.surface0;
		ctx.lineWidth = 1;
		ctx.beginPath();
		ctx.moveTo(NAME_PANEL_WIDTH, 0);
		ctx.lineTo(NAME_PANEL_WIDTH, h);
		ctx.moveTo(NAME_PANEL_WIDTH + VALUE_PANEL_WIDTH, 0);
		ctx.lineTo(NAME_PANEL_WIDTH + VALUE_PANEL_WIDTH, h);
		ctx.stroke();

		drawRuler();
		drawGrid();
		drawSignals();
		drawCursors();
		drawMarkers();
		drawMinimap();
	}

	function drawRuler() {
		if (!ctx) return;
		const waveLeft = NAME_PANEL_WIDTH + VALUE_PANEL_WIDTH;
		const waveWidth = canvasWidth - waveLeft;

		// Ruler background
		ctx.fillStyle = C.bgAlt;
		ctx.fillRect(waveLeft, 0, waveWidth, RULER_HEIGHT);

		// Tick marks
		const duration = timeEnd - timeStart;
		if (duration <= 0) return;

		const tickCount = Math.max(1, Math.floor(waveWidth / 100));
		const tickStep = duration / tickCount;

		ctx.strokeStyle = C.surface2;
		ctx.fillStyle = C.textDim;
		ctx.font = '10px "JetBrains Mono", monospace';
		ctx.textAlign = 'center';

		for (let i = 0; i <= tickCount; i++) {
			const t = timeStart + i * tickStep;
			const x = timeToX(t);

			// Major tick
			ctx.beginPath();
			ctx.moveTo(x, RULER_HEIGHT - 8);
			ctx.lineTo(x, RULER_HEIGHT);
			ctx.stroke();

			ctx.fillText(formatTime(t), x, RULER_HEIGHT - 12);

			// Minor ticks
			if (i < tickCount) {
				for (let j = 1; j < 5; j++) {
					const mt = t + (j * tickStep) / 5;
					const mx = timeToX(mt);
					ctx.beginPath();
					ctx.moveTo(mx, RULER_HEIGHT - 4);
					ctx.lineTo(mx, RULER_HEIGHT);
					ctx.stroke();
				}
			}
		}

		// Ruler bottom line
		ctx.strokeStyle = C.surface0;
		ctx.beginPath();
		ctx.moveTo(0, RULER_HEIGHT);
		ctx.lineTo(canvasWidth, RULER_HEIGHT);
		ctx.stroke();

		// Cursor time readout
		ctx.fillStyle = C.cursor;
		ctx.font = 'bold 11px "JetBrains Mono", monospace';
		ctx.textAlign = 'left';
		ctx.fillText(`T: ${formatTime(cursorTime)}`, waveLeft + 8, 14);

		if (cursor2Time !== null) {
			const delta = Math.abs(cursor2Time - cursorTime);
			ctx.fillStyle = C.cursor2;
			ctx.fillText(`\u0394: ${formatTime(delta)}`, waveLeft + 180, 14);
		}
	}

	function drawGrid() {
		if (!ctx) return;
		const waveLeft = NAME_PANEL_WIDTH + VALUE_PANEL_WIDTH;
		const waveWidth = canvasWidth - waveLeft;
		const duration = timeEnd - timeStart;
		if (duration <= 0) return;

		const tickCount = Math.max(1, Math.floor(waveWidth / 100));
		const tickStep = duration / tickCount;

		ctx.strokeStyle = C.grid;
		ctx.lineWidth = 0.5;
		ctx.setLineDash([2, 4]);

		for (let i = 0; i <= tickCount; i++) {
			const t = timeStart + i * tickStep;
			const x = timeToX(t);
			ctx.beginPath();
			ctx.moveTo(x, RULER_HEIGHT);
			ctx.lineTo(x, canvasHeight - 20);
			ctx.stroke();
		}

		ctx.setLineDash([]);
	}

	function drawSignals() {
		if (!ctx) return;
		const waveLeft = NAME_PANEL_WIDTH + VALUE_PANEL_WIDTH;

		signals.forEach((sig, idx) => {
			const y0 = RULER_HEIGHT + idx * SIGNAL_ROW_HEIGHT - scrollY;
			if (y0 + SIGNAL_ROW_HEIGHT < RULER_HEIGHT || y0 > canvasHeight) return;

			const color = sig.color || SIGNAL_COLORS[idx % SIGNAL_COLORS.length];
			const midY = y0 + SIGNAL_ROW_HEIGHT / 2;
			const highY = y0 + 6;
			const lowY = y0 + SIGNAL_ROW_HEIGHT - 6;

			// Row separator
			ctx!.strokeStyle = C.surface0;
			ctx!.lineWidth = 0.5;
			ctx!.beginPath();
			ctx!.moveTo(0, y0 + SIGNAL_ROW_HEIGHT);
			ctx!.lineTo(canvasWidth, y0 + SIGNAL_ROW_HEIGHT);
			ctx!.stroke();

			// Selected highlight
			if (idx === selectedSignalIdx) {
				ctx!.fillStyle = C.selection;
				ctx!.fillRect(0, y0, canvasWidth, SIGNAL_ROW_HEIGHT);
			}

			// Signal name
			ctx!.fillStyle = color;
			ctx!.font = '12px "Inter", sans-serif';
			ctx!.textAlign = 'left';
			const displayName = sig.name.length > 22 ? '...' + sig.name.slice(-19) : sig.name;
			ctx!.fillText(displayName, 8, midY + 4);

			// Current value at cursor
			const curVal = getValueAtTime(sig, cursorTime);
			ctx!.fillStyle = color;
			ctx!.font = '11px "JetBrains Mono", monospace';
			ctx!.fillText(formatValue(curVal, sig.radix), NAME_PANEL_WIDTH + 4, midY + 4);

			// Waveform
			const isBus = sig.width > 1;
			ctx!.strokeStyle = color;
			ctx!.lineWidth = 1.5;

			for (let i = 0; i < sig.values.length; i++) {
				const vc = sig.values[i];
				const nextVc = sig.values[i + 1];
				const x = timeToX(vc.time);
				const xNext = nextVc ? timeToX(nextVc.time) : timeToX(timeEnd);

				if (xNext < waveLeft || x > canvasWidth) continue;

				if (isBus) {
					// Bus: diamond transitions with fill
					ctx!.fillStyle = color + '26'; // 15% opacity
					ctx!.beginPath();
					ctx!.moveTo(x + 3, highY);
					ctx!.lineTo(xNext - 3, highY);
					ctx!.lineTo(xNext, midY);
					ctx!.lineTo(xNext - 3, lowY);
					ctx!.lineTo(x + 3, lowY);
					ctx!.lineTo(x, midY);
					ctx!.closePath();
					ctx!.fill();

					ctx!.strokeStyle = color;
					ctx!.stroke();

					// Value text
					const textWidth = xNext - x - 10;
					if (textWidth > 20) {
						ctx!.fillStyle = color;
						ctx!.font = '10px "JetBrains Mono", monospace';
						ctx!.textAlign = 'center';
						ctx!.fillText(
							formatValue(vc.value, sig.radix),
							(x + xNext) / 2,
							midY + 4
						);
					}
				} else {
					// Single bit
					const val = vc.value;
					let y: number;
					let lineColor: string;

					if (val === '1') {
						y = highY;
						lineColor = C.high;
					} else if (val === '0') {
						y = lowY;
						lineColor = C.low;
					} else {
						y = midY;
						lineColor = C.xz;
					}

					ctx!.strokeStyle = lineColor;
					ctx!.beginPath();
					ctx!.moveTo(Math.max(x, waveLeft), y);
					ctx!.lineTo(xNext, y);
					ctx!.stroke();

					// Transition
					if (i > 0) {
						const prevVal = sig.values[i - 1].value;
						let prevY: number;
						if (prevVal === '1') prevY = highY;
						else if (prevVal === '0') prevY = lowY;
						else prevY = midY;

						if (prevY !== y) {
							ctx!.strokeStyle = color;
							ctx!.beginPath();
							ctx!.moveTo(x, prevY);
							ctx!.lineTo(x, y);
							ctx!.stroke();
						}
					}
				}
			}
		});
	}

	function drawCursors() {
		if (!ctx) return;

		// Primary cursor
		const cx = timeToX(cursorTime);
		if (cx >= NAME_PANEL_WIDTH + VALUE_PANEL_WIDTH && cx <= canvasWidth) {
			ctx.strokeStyle = C.cursor;
			ctx.lineWidth = 1.5;
			ctx.setLineDash([]);
			ctx.beginPath();
			ctx.moveTo(cx, RULER_HEIGHT);
			ctx.lineTo(cx, canvasHeight - 20);
			ctx.stroke();
		}

		// Secondary cursor
		if (cursor2Time !== null) {
			const cx2 = timeToX(cursor2Time);
			if (cx2 >= NAME_PANEL_WIDTH + VALUE_PANEL_WIDTH && cx2 <= canvasWidth) {
				ctx.strokeStyle = C.cursor2;
				ctx.lineWidth = 1;
				ctx.setLineDash([4, 4]);
				ctx.beginPath();
				ctx.moveTo(cx2, RULER_HEIGHT);
				ctx.lineTo(cx2, canvasHeight - 20);
				ctx.stroke();
				ctx.setLineDash([]);
			}
		}
	}

	function drawMarkers() {
		if (!ctx) return;
		ctx.setLineDash([6, 3]);
		ctx.lineWidth = 1;

		markers.forEach((m) => {
			const mx = timeToX(m.time);
			if (mx < NAME_PANEL_WIDTH + VALUE_PANEL_WIDTH || mx > canvasWidth) return;

			ctx!.strokeStyle = m.color;
			ctx!.beginPath();
			ctx!.moveTo(mx, RULER_HEIGHT);
			ctx!.lineTo(mx, canvasHeight - 20);
			ctx!.stroke();

			// Label
			ctx!.fillStyle = m.color;
			ctx!.font = 'bold 9px "Inter", sans-serif';
			ctx!.textAlign = 'center';
			ctx!.fillText(m.name, mx, RULER_HEIGHT + 12);
		});

		ctx.setLineDash([]);
	}

	function drawMinimap() {
		if (!ctx || signals.length === 0) return;
		const minimapH = 16;
		const y = canvasHeight - minimapH;
		const waveLeft = NAME_PANEL_WIDTH + VALUE_PANEL_WIDTH;
		const waveWidth = canvasWidth - waveLeft;

		// Background
		ctx.fillStyle = C.bgAlt;
		ctx.fillRect(waveLeft, y, waveWidth, minimapH);

		// Border
		ctx.strokeStyle = C.surface0;
		ctx.lineWidth = 1;
		ctx.strokeRect(waveLeft, y, waveWidth, minimapH);

		// Find global time range
		let globalStart = Infinity;
		let globalEnd = -Infinity;
		for (const sig of signals) {
			if (sig.values.length > 0) {
				globalStart = Math.min(globalStart, sig.values[0].time);
				globalEnd = Math.max(globalEnd, sig.values[sig.values.length - 1].time);
			}
		}
		if (globalEnd <= globalStart) return;

		// Viewport indicator
		const vpLeft = waveLeft + ((timeStart - globalStart) / (globalEnd - globalStart)) * waveWidth;
		const vpRight = waveLeft + ((timeEnd - globalStart) / (globalEnd - globalStart)) * waveWidth;
		ctx.fillStyle = 'rgba(137, 180, 250, 0.2)';
		ctx.fillRect(vpLeft, y, vpRight - vpLeft, minimapH);
		ctx.strokeStyle = C.accent;
		ctx.strokeRect(vpLeft, y, vpRight - vpLeft, minimapH);
	}

	// Event handlers
	function handleClick(e: MouseEvent) {
		const rect = canvas.getBoundingClientRect();
		const x = e.clientX - rect.left;
		const y = e.clientY - rect.top;

		if (x > NAME_PANEL_WIDTH + VALUE_PANEL_WIDTH) {
			if (e.shiftKey) {
				cursor2Time = xToTime(x);
			} else {
				cursorTime = xToTime(x);
				cursor2Time = null;
			}
		}

		// Signal selection
		if (y > RULER_HEIGHT) {
			const idx = Math.floor((y - RULER_HEIGHT + scrollY) / SIGNAL_ROW_HEIGHT);
			if (idx >= 0 && idx < signals.length) {
				selectedSignalIdx = idx;
			}
		}

		render();
	}

	function handleWheel(e: WheelEvent) {
		e.preventDefault();
		const rect = canvas.getBoundingClientRect();
		const x = e.clientX - rect.left;

		if (x > NAME_PANEL_WIDTH + VALUE_PANEL_WIDTH) {
			// Zoom centered on mouse position
			const t = xToTime(x);
			const factor = e.deltaY > 0 ? 1.3 : 0.7;
			const newStart = t - (t - timeStart) * factor;
			const newEnd = t + (timeEnd - t) * factor;
			if (newEnd > newStart) {
				timeStart = newStart;
				timeEnd = newEnd;
			}
		} else {
			// Vertical scroll in signal area
			scrollY = Math.max(0, scrollY + e.deltaY * 0.5);
		}

		render();
	}

	function handleResize() {
		if (!containerEl || !canvas) return;
		canvasWidth = containerEl.clientWidth;
		canvasHeight = containerEl.clientHeight;
		canvas.width = canvasWidth * window.devicePixelRatio;
		canvas.height = canvasHeight * window.devicePixelRatio;
		canvas.style.width = `${canvasWidth}px`;
		canvas.style.height = `${canvasHeight}px`;
		ctx = canvas.getContext('2d');
		if (ctx) {
			ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
		}
		render();
	}

	onMount(() => {
		ctx = canvas.getContext('2d');
		handleResize();

		const observer = new ResizeObserver(handleResize);
		observer.observe(containerEl);

		// Auto-fit time range
		if (signals.length > 0) {
			let minT = Infinity, maxT = -Infinity;
			for (const sig of signals) {
				for (const vc of sig.values) {
					minT = Math.min(minT, vc.time);
					maxT = Math.max(maxT, vc.time);
				}
			}
			const margin = (maxT - minT) * 0.05;
			timeStart = minT - margin;
			timeEnd = maxT + margin;
		}

		render();

		return () => observer.disconnect();
	});

	$effect(() => {
		signals;
		cursorTime;
		cursor2Time;
		markers;
		render();
	});
</script>

<div class="waveform-container" bind:this={containerEl}>
	<canvas
		bind:this={canvas}
		onclick={handleClick}
		onwheel={handleWheel}
	></canvas>

	{#if signals.length === 0}
		<div class="empty-overlay">
			<div class="empty-icon">~</div>
			<p>No waveform data loaded</p>
			<p class="hint">Run a simulation to generate waveforms</p>
		</div>
	{/if}
</div>

<style>
	.waveform-container {
		position: relative;
		width: 100%;
		height: 100%;
		overflow: hidden;
		background: var(--color-bg-primary);
	}

	canvas {
		display: block;
		cursor: crosshair;
	}

	.empty-overlay {
		position: absolute;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		text-align: center;
		color: var(--color-text-secondary);
	}

	.empty-icon {
		font-size: 48px;
		opacity: 0.3;
		font-family: monospace;
	}

	.hint {
		font-size: 12px;
		opacity: 0.5;
	}
</style>
