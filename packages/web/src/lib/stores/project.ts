/** Svelte stores for project state management. */

import { writable, derived } from 'svelte/store';
import type { Project, VerificationJob } from '$lib/api/client';

// Current project
export const currentProject = writable<Project | null>(null);

// Navigation / routing state
export const currentView = writable<'ide' | 'projects' | 'synthesis' | 'verification'>('ide');

// Project file tree
export interface FileNode {
	name: string;
	path: string;
	type: 'file' | 'directory';
	children?: FileNode[];
	language?: string;
}

export const fileTree = writable<FileNode[]>([]);

// Open files in editor
export interface OpenFile {
	path: string;
	name: string;
	content: string;
	language: string;
	modified: boolean;
}

export const openFiles = writable<OpenFile[]>([]);
export const activeFileIndex = writable<number>(0);
export const activeFile = derived(
	[openFiles, activeFileIndex],
	([$files, $idx]) => $files[$idx] ?? null
);

// Verification state
export const verificationJobs = writable<VerificationJob[]>([]);
export const activeJob = writable<VerificationJob | null>(null);

// Console output
export interface ConsoleLine {
	text: string;
	level: 'info' | 'warning' | 'error' | 'success' | 'debug';
	timestamp: string;
}

export const consoleLines = writable<ConsoleLine[]>([
	{
		text: 'OpenForge EDA v0.1.0 - Ready',
		level: 'success',
		timestamp: new Date().toISOString()
	}
]);

export function appendConsole(text: string, level: ConsoleLine['level'] = 'info') {
	consoleLines.update((lines) => [
		...lines,
		{ text, level, timestamp: new Date().toISOString() }
	]);
}

// Tool status
export interface ToolInfo {
	name: string;
	installed: boolean;
	version: string;
}

export const toolStatus = writable<ToolInfo[]>([]);

// Running job state
export interface RunningJob {
	name: string;
	progress?: number;
}

export const runningJob = writable<RunningJob | null>(null);

// UI state
export const leftSidebarOpen = writable(true);
export const rightSidebarOpen = writable(true);
export const bottomPanelOpen = writable(true);
export const bottomPanelTab = writable<'console' | 'problems' | 'waveforms' | 'reports' | 'timing'>(
	'console'
);
export const leftPanelTab = writable<'explorer' | 'hierarchy'>('explorer');
export const rightPanelTab = writable<'properties' | 'security'>('properties');

// Activity bar (left icon sidebar)
export const activityBarSelection = writable<'explorer' | 'hierarchy' | 'search' | 'git' | 'extensions'>('explorer');

// Projects list (for projects page)
export const projectsList = writable<Project[]>([]);
