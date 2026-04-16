// Svelte stores for tracking EDA job state across the app.

import { writable, derived, get } from 'svelte/store';
import type { Job, JobStatus } from '../api/openforge';

export const jobs = writable<Map<string, Job>>(new Map());

export const runningJobs = derived(jobs, ($jobs) =>
  Array.from($jobs.values()).filter((j) => j.status === 'running'),
);

export const queuedJobs = derived(jobs, ($jobs) =>
  Array.from($jobs.values()).filter((j) => j.status === 'queued'),
);

export const completedJobs = derived(jobs, ($jobs) =>
  Array.from($jobs.values()).filter((j) => j.status === 'completed'),
);

export const failedJobs = derived(jobs, ($jobs) =>
  Array.from($jobs.values()).filter((j) => j.status === 'failed'),
);

export const jobList = derived(jobs, ($jobs) =>
  Array.from($jobs.values()).sort((a, b) => {
    const ta = a.created_at ? Date.parse(a.created_at) : 0;
    const tb = b.created_at ? Date.parse(b.created_at) : 0;
    return tb - ta;
  }),
);

export const activeCount = derived(
  [runningJobs, queuedJobs],
  ([$r, $q]) => $r.length + $q.length,
);

export function updateJob(job: Job): void {
  jobs.update((m) => {
    m.set(job.id, job);
    return new Map(m);
  });
}

export function clearJob(jobId: string): void {
  jobs.update((m) => {
    m.delete(jobId);
    return new Map(m);
  });
}

export function clearAllFinished(): void {
  jobs.update((m) => {
    for (const [id, j] of Array.from(m.entries())) {
      if (
        j.status === 'completed' ||
        j.status === 'failed' ||
        j.status === 'cancelled'
      ) {
        m.delete(id);
      }
    }
    return new Map(m);
  });
}

export function getJob(jobId: string): Job | undefined {
  return get(jobs).get(jobId);
}

export function jobsByStatus(status: JobStatus): Job[] {
  return Array.from(get(jobs).values()).filter((j) => j.status === status);
}

export function resetJobs(): void {
  jobs.set(new Map());
}
