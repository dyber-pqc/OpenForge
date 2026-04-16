// Authentication store for the OpenForge web UI.

import { writable, derived, get } from 'svelte/store';
import { api } from '../api/openforge';

export interface AuthState {
  username: string | null;
  token: string | null;
  authenticated: boolean;
  roles: string[];
}

const initial: AuthState = {
  username: null,
  token: null,
  authenticated: false,
  roles: [],
};

export const auth = writable<AuthState>(initial);

export const isAuthenticated = derived(auth, ($a) => $a.authenticated);
export const currentUser = derived(auth, ($a) => $a.username);

const TOKEN_KEY = 'openforge_token';
const USER_KEY = 'openforge_user';

function storageAvailable(): boolean {
  try {
    return typeof window !== 'undefined' && !!window.localStorage;
  } catch {
    return false;
  }
}

export function login(username: string, token: string, roles: string[] = []): void {
  auth.set({ username, token, authenticated: true, roles });
  api.setToken(token);
  if (storageAvailable()) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, username);
  }
}

export function logout(): void {
  auth.set(initial);
  api.setToken(null);
  if (storageAvailable()) {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }
}

export function loadStoredAuth(): boolean {
  if (!storageAvailable()) return false;
  const token = localStorage.getItem(TOKEN_KEY);
  const username = localStorage.getItem(USER_KEY);
  if (token && username) {
    auth.set({ token, username, authenticated: true, roles: [] });
    api.setToken(token);
    return true;
  }
  return false;
}

export async function performLogin(username: string, password: string): Promise<void> {
  const res = await api.login(username, password);
  login(res.username, res.access_token);
}

export async function performLogout(): Promise<void> {
  try {
    await api.logout();
  } catch {
    /* ignore */
  }
  logout();
}

export async function performRegister(
  username: string,
  password: string,
  email?: string,
): Promise<void> {
  await api.register(username, password, email);
}

export function getToken(): string | null {
  return get(auth).token;
}
