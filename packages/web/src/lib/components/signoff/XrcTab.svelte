<script lang="ts">
	import type { XrcReport } from '$lib/api/signoff';
	import { formatCap, formatLength, formatRes } from '$lib/api/signoff';

	interface Props {
		report: XrcReport;
	}

	let { report }: Props = $props();

	let worstC = $derived(report.worst_net.c);
	let typC = $derived(report.total_c_ff.typ);
</script>

<div class="space-y-4" data-testid="xrc-tab">
	<div class="grid grid-cols-1 md:grid-cols-3 gap-3">
		<div class="rounded-md border border-slate-700 bg-slate-900/60 p-4">
			<div class="text-xs uppercase tracking-wide text-slate-400">Total wirelength</div>
			<div class="mt-1 text-2xl font-bold text-cyan-300" data-testid="xrc-wirelength">
				{formatLength(report.total_wirelength_um)}
			</div>
		</div>
		<div class="rounded-md border border-slate-700 bg-slate-900/60 p-4">
			<div class="text-xs uppercase tracking-wide text-slate-400">Total R</div>
			<div class="mt-1 text-2xl font-bold text-cyan-300" data-testid="xrc-r">
				{formatRes(report.total_r_ohm)}
			</div>
		</div>
		<div class="rounded-md border border-slate-700 bg-slate-900/60 p-4">
			<div class="text-xs uppercase tracking-wide text-slate-400">Coupling pairs</div>
			<div class="mt-1 text-2xl font-bold text-cyan-300" data-testid="xrc-coupling">
				{report.coupling_pairs.toLocaleString()}
			</div>
		</div>
	</div>

	<div class="rounded-md border border-slate-700 bg-slate-900/60 overflow-hidden">
		<div
			class="px-4 py-2 text-xs uppercase tracking-wide text-slate-300 border-b border-slate-700 bg-slate-800/60"
		>
			Capacitance corner sweep
		</div>
		<table class="w-full text-sm">
			<thead class="bg-slate-800/40 text-slate-400 text-xs uppercase">
				<tr>
					<th class="text-left px-4 py-2">Quantity</th>
					<th class="text-right px-4 py-2">min</th>
					<th class="text-right px-4 py-2">typ</th>
					<th class="text-right px-4 py-2">max</th>
				</tr>
			</thead>
			<tbody data-testid="xrc-corner-table">
				<tr class="border-t border-slate-800">
					<td class="px-4 py-2 text-slate-300">Total C</td>
					<td class="px-4 py-2 text-right font-mono text-slate-100">
						{formatCap(report.total_c_ff.min)}
					</td>
					<td class="px-4 py-2 text-right font-mono text-cyan-300">
						{formatCap(report.total_c_ff.typ)}
					</td>
					<td class="px-4 py-2 text-right font-mono text-slate-100">
						{formatCap(report.total_c_ff.max)}
					</td>
				</tr>
				<tr class="border-t border-slate-800">
					<td class="px-4 py-2 text-slate-300">
						Worst-case net
						<span class="ml-2 text-xs text-slate-500 font-mono">{report.worst_net.name}</span>
					</td>
					<td class="px-4 py-2 text-right font-mono text-slate-500">—</td>
					<td class="px-4 py-2 text-right font-mono text-yellow-300" data-testid="xrc-worst-c">
						{formatCap(worstC)} / {formatRes(report.worst_net.r)}
					</td>
					<td class="px-4 py-2 text-right font-mono text-slate-500">
						{typC > 0 ? `${((worstC / typC) * 100).toFixed(2)}%` : '—'}
					</td>
				</tr>
			</tbody>
		</table>
	</div>

	<div class="rounded-md border border-slate-700 bg-slate-900/60 p-4">
		<div class="text-xs uppercase tracking-wide text-slate-400 mb-2">SPEF artifacts</div>
		{#if Object.keys(report.spef_files).length === 0}
			<div class="text-sm text-slate-500">No SPEF files written.</div>
		{:else}
			<ul class="space-y-1 text-sm" data-testid="xrc-spef-list">
				{#each Object.entries(report.spef_files) as [corner, path]}
					<li class="flex items-center justify-between">
						<span class="text-slate-300 font-mono">{corner}</span>
						<a
							href="/api/files/{encodeURIComponent(path)}"
							class="text-cyan-300 hover:text-cyan-200 underline font-mono text-xs"
							download
						>
							{path}
						</a>
					</li>
				{/each}
			</ul>
		{/if}
	</div>
</div>
