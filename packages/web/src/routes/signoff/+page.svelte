<script lang="ts">
	import { onMount } from 'svelte';
	import { currentProject } from '$lib/stores/project';
	import {
		fetchDrc,
		fetchLvs,
		fetchXrc,
		MOCK_DRC,
		MOCK_LVS,
		MOCK_XRC,
		type DrcReport,
		type LvsReport,
		type XrcReport
	} from '$lib/api/signoff';
	import DrcTab from '$lib/components/signoff/DrcTab.svelte';
	import LvsTab from '$lib/components/signoff/LvsTab.svelte';
	import XrcTab from '$lib/components/signoff/XrcTab.svelte';

	type TabId = 'drc' | 'lvs' | 'xrc';

	let activeTab = $state<TabId>('drc');
	let loading = $state(true);
	let usingMock = $state(false);

	let drc = $state<DrcReport | null>(null);
	let lvs = $state<LvsReport | null>(null);
	let xrc = $state<XrcReport | null>(null);

	let projectId = $derived($currentProject?.id ?? 'mock-picorv32');

	async function load() {
		loading = true;
		usingMock = false;
		const [d, l, x] = await Promise.all([
			fetchDrc(projectId),
			fetchLvs(projectId),
			fetchXrc(projectId)
		]);
		if (!d && !l && !x) {
			usingMock = true;
			drc = MOCK_DRC;
			lvs = MOCK_LVS;
			xrc = MOCK_XRC;
		} else {
			drc = d ?? MOCK_DRC;
			lvs = l ?? MOCK_LVS;
			xrc = x ?? MOCK_XRC;
			usingMock = !d || !l || !x;
		}
		loading = false;
	}

	onMount(load);

	const tabs: { id: TabId; label: string }[] = [
		{ id: 'drc', label: 'DRC' },
		{ id: 'lvs', label: 'LVS' },
		{ id: 'xrc', label: 'xRC' }
	];
</script>

<div class="signoff-page h-full overflow-auto bg-slate-950 text-slate-100 p-6">
	<header class="mb-5 flex items-center justify-between">
		<div>
			<h1 class="text-2xl font-bold tracking-tight">Sign-off Dashboard</h1>
			<p class="text-sm text-slate-400 mt-1">
				DRC · LVS · xRC results for
				<span class="font-mono text-cyan-300">{projectId}</span>
			</p>
		</div>
		<button
			onclick={load}
			class="text-xs px-3 py-1.5 rounded border border-slate-600 hover:border-cyan-400 text-slate-300 hover:text-cyan-300"
		>
			Refresh
		</button>
	</header>

	{#if usingMock && !loading}
		<div
			class="mb-4 rounded border border-yellow-300/40 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-200"
		>
			Showing baked-in PicoRV32 sky130 mock data — the API returned no live
			sign-off reports for this project.
		</div>
	{/if}

	<nav class="flex gap-1 border-b border-slate-700 mb-4" role="tablist">
		{#each tabs as t}
			<button
				role="tab"
				aria-selected={activeTab === t.id}
				class="px-4 py-2 text-sm border-b-2 transition-colors -mb-px"
				class:border-cyan-400={activeTab === t.id}
				class:text-cyan-300={activeTab === t.id}
				class:border-transparent={activeTab !== t.id}
				class:text-slate-400={activeTab !== t.id}
				onclick={() => (activeTab = t.id)}
				data-testid={`tab-${t.id}`}
			>
				{t.label}
			</button>
		{/each}
	</nav>

	{#if loading}
		<div class="space-y-3" data-testid="signoff-skeleton">
			<div class="h-24 rounded bg-slate-800/50 animate-pulse"></div>
			<div class="h-48 rounded bg-slate-800/50 animate-pulse"></div>
			<div class="h-24 rounded bg-slate-800/50 animate-pulse"></div>
		</div>
	{:else}
		{#if activeTab === 'drc' && drc}
			<DrcTab report={drc} />
		{:else if activeTab === 'lvs' && lvs}
			<LvsTab report={lvs} />
		{:else if activeTab === 'xrc' && xrc}
			<XrcTab report={xrc} />
		{/if}
	{/if}
</div>
