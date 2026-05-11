<script lang="ts">
	import type { LvsReport } from '$lib/api/signoff';

	interface Props {
		report: LvsReport;
	}

	let { report }: Props = $props();

	let isMatch = $derived(report.verdict === 'MATCH');
	let badgeCls = $derived(
		isMatch
			? 'bg-emerald-500/15 border-emerald-400/40 text-emerald-300'
			: report.verdict === 'MISMATCH'
				? 'bg-red-500/15 border-red-400/40 text-red-300'
				: 'bg-slate-700/40 border-slate-600 text-slate-300'
	);

	let devicesMatch = $derived(report.layout.devices === report.schematic.devices);
	let netsMatch = $derived(report.layout.nets === report.schematic.nets);
</script>

<div class="space-y-4" data-testid="lvs-tab">
	<div
		class="rounded-md border p-6 flex items-center justify-between {badgeCls}"
		data-testid="lvs-verdict"
	>
		<div>
			<div class="text-xs uppercase tracking-wide opacity-80">Verdict</div>
			<div class="mt-1 text-4xl font-extrabold tracking-wide">{report.verdict}</div>
		</div>
		<div class="text-right text-sm opacity-80">
			<div>{report.layout.devices.toLocaleString()} devices · {report.layout.nets.toLocaleString()} nets</div>
			<div class="mt-1 text-xs">
				Physical-only filtered: {report.physical_only_filtered}
			</div>
		</div>
	</div>

	<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
		<div class="rounded-md border border-slate-700 bg-slate-900/60 p-4">
			<div class="text-xs uppercase tracking-wide text-slate-400">Layout</div>
			<dl class="mt-2 space-y-1 text-sm">
				<div class="flex justify-between">
					<dt class="text-slate-400">Devices</dt>
					<dd class="font-mono text-slate-100" data-testid="lvs-layout-devices">
						{report.layout.devices.toLocaleString()}
					</dd>
				</div>
				<div class="flex justify-between">
					<dt class="text-slate-400">Nets</dt>
					<dd class="font-mono text-slate-100">{report.layout.nets.toLocaleString()}</dd>
				</div>
			</dl>
		</div>
		<div class="rounded-md border border-slate-700 bg-slate-900/60 p-4">
			<div class="text-xs uppercase tracking-wide text-slate-400">Schematic</div>
			<dl class="mt-2 space-y-1 text-sm">
				<div class="flex justify-between">
					<dt class="text-slate-400">Devices</dt>
					<dd
						class="font-mono {devicesMatch ? 'text-emerald-300' : 'text-red-300'}"
						data-testid="lvs-schem-devices"
					>
						{report.schematic.devices.toLocaleString()}
					</dd>
				</div>
				<div class="flex justify-between">
					<dt class="text-slate-400">Nets</dt>
					<dd class="font-mono {netsMatch ? 'text-emerald-300' : 'text-red-300'}">
						{report.schematic.nets.toLocaleString()}
					</dd>
				</div>
			</dl>
		</div>
	</div>

	{#if report.mismatched_devices.length > 0 || report.mismatched_nets.length > 0}
		<div class="rounded-md border border-red-400/40 bg-red-500/10 overflow-hidden">
			<div class="px-4 py-2 text-xs uppercase tracking-wide text-red-200 border-b border-red-400/30">
				Mismatches
			</div>
			<div class="grid grid-cols-1 md:grid-cols-2">
				<div class="p-4">
					<div class="text-xs text-slate-400 mb-1">Devices ({report.mismatched_devices.length})</div>
					<ul class="text-xs font-mono text-red-200 space-y-0.5 max-h-48 overflow-auto">
						{#each report.mismatched_devices as d}
							<li>{d}</li>
						{/each}
					</ul>
				</div>
				<div class="p-4">
					<div class="text-xs text-slate-400 mb-1">Nets ({report.mismatched_nets.length})</div>
					<ul class="text-xs font-mono text-red-200 space-y-0.5 max-h-48 overflow-auto">
						{#each report.mismatched_nets as n}
							<li>{n}</li>
						{/each}
					</ul>
				</div>
			</div>
		</div>
	{/if}
</div>
