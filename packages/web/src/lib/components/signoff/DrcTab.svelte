<script lang="ts">
	import type { DrcReport } from '$lib/api/signoff';
	import { severityBg, severityClass } from '$lib/api/signoff';

	interface Props {
		report: DrcReport;
	}

	let { report }: Props = $props();

	let badge = $derived(severityBg(report.severity));
	let textCls = $derived(severityClass(report.severity));
	let maxCount = $derived(
		report.top_rules.length > 0 ? Math.max(...report.top_rules.map((r) => r.count)) : 1
	);
</script>

<div class="space-y-4" data-testid="drc-tab">
	<div class="grid grid-cols-1 md:grid-cols-3 gap-3">
		<div class="rounded-md border border-slate-700 bg-slate-900/60 p-4">
			<div class="text-xs uppercase tracking-wide text-slate-400">Rule deck</div>
			<div class="mt-1 font-mono text-sm text-slate-100 break-all" data-testid="drc-rule-deck">
				{report.rule_deck || '—'}
			</div>
			<div class="mt-2 text-xs text-slate-400">
				{report.rules_loaded} rules loaded
			</div>
		</div>

		<div class="rounded-md border p-4 {badge}">
			<div class="text-xs uppercase tracking-wide text-slate-300">Total violations</div>
			<div class="mt-1 text-3xl font-bold {textCls}" data-testid="drc-total">
				{report.total_violations.toLocaleString()}
			</div>
			<div class="mt-2 text-xs text-slate-300 capitalize">Severity: {report.severity}</div>
		</div>

		<div class="rounded-md border border-slate-700 bg-slate-900/60 p-4">
			<div class="text-xs uppercase tracking-wide text-slate-400">Distinct rules</div>
			<div class="mt-1 text-3xl font-bold text-slate-100">
				{report.top_rules.length}
			</div>
			<div class="mt-2 text-xs text-slate-400">in top-N table</div>
		</div>
	</div>

	<div class="rounded-md border border-slate-700 bg-slate-900/60 overflow-hidden">
		<div
			class="px-4 py-2 text-xs uppercase tracking-wide text-slate-300 border-b border-slate-700 bg-slate-800/60"
		>
			Top 10 violating rules
		</div>
		<table class="w-full text-sm">
			<thead class="bg-slate-800/40 text-slate-400 text-xs uppercase">
				<tr>
					<th class="text-left px-4 py-2">Rule</th>
					<th class="text-right px-4 py-2 w-32">Violations</th>
					<th class="text-left px-4 py-2 w-1/3">Share</th>
				</tr>
			</thead>
			<tbody data-testid="drc-rule-rows">
				{#each report.top_rules as r}
					<tr class="border-t border-slate-800 hover:bg-slate-800/40">
						<td class="px-4 py-2 font-mono text-slate-200">{r.rule}</td>
						<td class="px-4 py-2 text-right font-mono text-slate-100">
							{r.count.toLocaleString()}
						</td>
						<td class="px-4 py-2">
							<div class="h-2 w-full rounded bg-slate-800 overflow-hidden">
								<div
									class="h-2 bg-cyan-400/70"
									style="width: {(r.count / maxCount) * 100}%"
								></div>
							</div>
						</td>
					</tr>
				{:else}
					<tr>
						<td class="px-4 py-3 text-slate-500" colspan="3">No violations.</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</div>
