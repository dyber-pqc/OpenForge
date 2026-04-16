// OpenForge API client — talks to the FastAPI backend.

export type JobStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface Job {
  id: string;
  type: string;
  status: JobStatus;
  progress: number;
  project_id?: string;
  user_id?: string;
  error?: string;
  result?: any;
  created_at?: string;
  started_at?: string;
  finished_at?: string;
}

export interface Project {
  id: string;
  name: string;
  path?: string;
  created_at?: string;
}

export interface FileNode {
  name: string;
  path: string;
  type: 'file' | 'dir';
  size?: number;
}

export interface Tool {
  name: string;
  version?: string;
  installed: boolean;
  description?: string;
}

export interface LoginResult {
  access_token: string;
  token_type: string;
  username: string;
}

export class OpenForgeApi {
  private baseUrl: string;
  private token: string | null = null;

  constructor(baseUrl: string = 'http://localhost:8000') {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  setToken(token: string | null): void {
    this.token = token;
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  private headers(extra: Record<string, string> = {}): Record<string, string> {
    const h: Record<string, string> = {
      'Content-Type': 'application/json',
      ...extra,
    };
    if (this.token) h['Authorization'] = `Bearer ${this.token}`;
    return h;
  }

  private async request<T>(
    path: string,
    init: RequestInit = {},
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const res = await fetch(url, {
      ...init,
      headers: { ...this.headers(), ...(init.headers || {}) },
    });
    if (!res.ok) {
      let detail: string = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail || JSON.stringify(body);
      } catch {
        /* ignore */
      }
      throw new Error(`${res.status} ${detail}`);
    }
    if (res.status === 204) return undefined as unknown as T;
    return (await res.json()) as T;
  }

  // ------------------------------------------------------------- auth
  async login(username: string, password: string): Promise<LoginResult> {
    const body = new URLSearchParams({ username, password });
    const res = await fetch(`${this.baseUrl}/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });
    if (!res.ok) throw new Error(`Login failed: ${res.status}`);
    const data = (await res.json()) as LoginResult;
    this.setToken(data.access_token);
    return data;
  }

  async register(username: string, password: string, email?: string): Promise<void> {
    await this.request('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, password, email }),
    });
  }

  async logout(): Promise<void> {
    try {
      await this.request('/auth/logout', { method: 'POST' });
    } finally {
      this.setToken(null);
    }
  }

  async me(): Promise<{ username: string; email?: string; roles: string[] }> {
    return this.request('/auth/me');
  }

  // ------------------------------------------------------------- projects
  async listProjects(): Promise<Project[]> {
    return this.request('/projects');
  }

  async createProject(name: string): Promise<Project> {
    return this.request('/projects', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  }

  async openProject(id: string): Promise<Project> {
    return this.request(`/projects/${id}`);
  }

  async deleteProject(id: string): Promise<void> {
    await this.request(`/projects/${id}`, { method: 'DELETE' });
  }

  // ------------------------------------------------------------- jobs
  async submitSynthesis(
    projectId: string,
    top: string,
    sources: string[],
    pdk = 'sky130',
  ): Promise<{ job_id: string }> {
    return this.request('/synth', {
      method: 'POST',
      body: JSON.stringify({
        project_id: projectId,
        top_module: top,
        sources,
        pdk,
      }),
    });
  }

  async submitSimulation(
    projectId: string,
    top: string,
    sources: string[],
    testbench: string,
  ): Promise<{ job_id: string }> {
    return this.request('/verify/simulate', {
      method: 'POST',
      body: JSON.stringify({
        project_id: projectId,
        top_module: top,
        sources,
        testbench,
      }),
    });
  }

  async submitTiming(projectId: string, top: string): Promise<{ job_id: string }> {
    return this.request('/analyze/timing', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, top_module: top }),
    });
  }

  async submitPnr(projectId: string, top: string): Promise<{ job_id: string }> {
    return this.request('/synth/pnr', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, top_module: top }),
    });
  }

  async getJob(jobId: string): Promise<Job> {
    return this.request(`/jobs/${jobId}`);
  }

  async listJobs(status?: string): Promise<Job[]> {
    const q = status ? `?status=${encodeURIComponent(status)}` : '';
    return this.request(`/jobs${q}`);
  }

  async cancelJob(jobId: string): Promise<void> {
    await this.request(`/jobs/${jobId}/cancel`, { method: 'POST' });
  }

  // ------------------------------------------------------------- websocket
  private wsUrl(path: string): string {
    return `${this.baseUrl.replace(/^http/, 'ws')}${path}`;
  }

  connectJobUpdates(onUpdate: (job: Job) => void): WebSocket {
    const ws = new WebSocket(this.wsUrl('/ws/jobs'));
    ws.onmessage = (e: MessageEvent) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'job_update' && msg.job) {
          onUpdate(msg.job as Job);
        } else if (msg.type === 'initial' && Array.isArray(msg.jobs)) {
          for (const j of msg.jobs) onUpdate(j as Job);
        }
      } catch (err) {
        console.error('bad ws message', err);
      }
    };
    return ws;
  }

  connectJobLog(jobId: string, onLine: (line: string) => void): WebSocket {
    const ws = new WebSocket(this.wsUrl(`/ws/job/${jobId}/log`));
    ws.onmessage = (e: MessageEvent) => onLine(String(e.data));
    return ws;
  }

  // ------------------------------------------------------------- tools
  async listTools(): Promise<Tool[]> {
    return this.request('/tools');
  }

  async installTool(name: string): Promise<void> {
    await this.request(`/tools/${encodeURIComponent(name)}/install`, {
      method: 'POST',
    });
  }

  // ------------------------------------------------------------- files
  async readFile(projectId: string, path: string): Promise<string> {
    const q = `?project_id=${encodeURIComponent(projectId)}&path=${encodeURIComponent(path)}`;
    const res = await fetch(`${this.baseUrl}/files/read${q}`, {
      headers: this.headers(),
    });
    if (!res.ok) throw new Error(`readFile: ${res.status}`);
    return res.text();
  }

  async writeFile(projectId: string, path: string, content: string): Promise<void> {
    await this.request('/files/write', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, path, content }),
    });
  }

  async listFiles(projectId: string): Promise<FileNode[]> {
    return this.request(`/files?project_id=${encodeURIComponent(projectId)}`);
  }
}

export const api = new OpenForgeApi();
