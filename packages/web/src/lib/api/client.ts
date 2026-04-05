/** OpenForge API client for the web frontend. */

const API_BASE = '/api';

export interface Project {
	id: string;
	name: string;
	top_module: string;
	target_pdk: string;
	created_at: string;
}

export interface VerificationJob {
	id: string;
	project_id: string;
	status: 'queued' | 'running' | 'passed' | 'failed' | 'error';
	engines: string[];
	created_at: string;
	completed_at?: string;
	results?: Record<string, StepResult>;
}

export interface StepResult {
	status: string;
	duration: number;
	output: string;
	errors: string[];
	artifacts: Record<string, string>;
}

export interface ToolStatus {
	name: string;
	installed: boolean;
	version: string;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
	const res = await fetch(`${API_BASE}${path}`, {
		headers: { 'Content-Type': 'application/json' },
		...options
	});
	if (!res.ok) {
		throw new Error(`API error: ${res.status} ${res.statusText}`);
	}
	return res.json();
}

// Projects
export const listProjects = () => request<Project[]>('/projects/');
export const getProject = (id: string) => request<Project>(`/projects/${id}`);
export const createProject = (data: { name: string; top_module: string; target_pdk: string }) =>
	request<Project>('/projects/', { method: 'POST', body: JSON.stringify(data) });
export const deleteProject = (id: string) =>
	request<void>(`/projects/${id}`, { method: 'DELETE' });

// Verification
export const startVerification = (projectId: string, engines: string[]) =>
	request<VerificationJob>('/verify/', {
		method: 'POST',
		body: JSON.stringify({ project_id: projectId, engines })
	});
export const getVerificationStatus = (jobId: string) =>
	request<VerificationJob>(`/verify/${jobId}`);
export const getVerificationResults = (jobId: string) =>
	request<VerificationJob>(`/verify/${jobId}/results`);

// WebSocket for live updates
export function connectWebSocket(
	onMessage: (data: Record<string, unknown>) => void,
	onClose?: () => void
): WebSocket {
	const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
	const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

	ws.onmessage = (event) => {
		try {
			const data = JSON.parse(event.data);
			onMessage(data);
		} catch {
			console.warn('Invalid WS message:', event.data);
		}
	};

	ws.onclose = () => onClose?.();

	return ws;
}
