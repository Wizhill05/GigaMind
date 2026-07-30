import { Memory, ProfileRule, Conversation, SearchResult, Stats } from './types';

const API_KEY_KEY = 'gigamind_master_key';

export function getApiKey(): string {
  return localStorage.getItem(API_KEY_KEY) || '';
}

export function setApiKey(key: string): void {
  if (key) {
    localStorage.setItem(API_KEY_KEY, key);
  } else {
    localStorage.removeItem(API_KEY_KEY);
  }
}

function getHeaders(): HeadersInit {
  const key = getApiKey();
  return {
    'Authorization': `Bearer ${key}`,
    'Content-Type': 'application/json',
  };
}

export async function fetchStats(): Promise<Stats | null> {
  try {
    const res = await fetch('/api/v1/stats', { headers: getHeaders() });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.error('fetchStats error:', err);
    return null;
  }
}

export async function fetchMemories(
  page: number = 1,
  limit: number = 20,
  category?: string,
  sourceAgent?: string
): Promise<{ memories: Memory[]; total: number; page: number; pages: number } | null> {
  try {
    const params = new URLSearchParams({ page: String(page), limit: String(limit) });
    if (category) params.append('category', category);
    if (sourceAgent) params.append('source_agent', sourceAgent);

    const res = await fetch(`/api/v1/memories?${params.toString()}`, { headers: getHeaders() });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.error('fetchMemories error:', err);
    return null;
  }
}

export async function addMemory(data: {
  content: string;
  category?: string;
  source_agent?: string;
  tags?: string[];
}): Promise<{ success: boolean; memory?: Memory } | null> {
  try {
    const res = await fetch('/api/v1/add_memory', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.error('addMemory error:', err);
    return null;
  }
}

export async function updateMemory(
  id: string,
  data: { content?: string; category?: string; source_agent?: string; tags?: string[] }
): Promise<{ success: boolean; memory?: Memory } | null> {
  try {
    const res = await fetch(`/api/v1/memories/${id}`, {
      method: 'PUT',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.error('updateMemory error:', err);
    return null;
  }
}

export async function deleteMemory(id: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/v1/memories/${id}`, {
      method: 'DELETE',
      headers: getHeaders(),
    });
    return res.ok;
  } catch (err) {
    console.error('deleteMemory error:', err);
    return false;
  }
}

export async function exportMemories(format: 'json' | 'csv' = 'json'): Promise<void> {
  try {
    const res = await fetch(`/api/v1/memories/export?format=${format}`, { headers: getHeaders() });
    if (!res.ok) throw new Error('Export failed');
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `gigamind_memories_export.${format}`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
  } catch (err) {
    console.error('exportMemories error:', err);
  }
}

export async function hardResetMemories(password: string): Promise<{ success: boolean; count?: number; message?: string } | null> {
  try {
    const res = await fetch('/api/v1/memories/reset', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ password }),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      return { success: false, message: errData.detail || 'Password verification failed' };
    }
    return await res.json();
  } catch (err: any) {
    console.error('hardResetMemories error:', err);
    return { success: false, message: err.message || 'Network error' };
  }
}

export async function fetchProfileRules(category?: string, sourceAgent?: string): Promise<ProfileRule[] | null> {
  try {
    const params = new URLSearchParams();
    if (category) params.append('category', category);
    if (sourceAgent) params.append('source_agent', sourceAgent);

    const res = await fetch(`/api/v1/get_profile?${params.toString()}`, { headers: getHeaders() });
    if (!res.ok) return null;
    const data = await res.json();
    return data.profile || [];
  } catch (err) {
    console.error('fetchProfileRules error:', err);
    return null;
  }
}

export async function setProfileRule(data: {
  key: string;
  value: string;
  category?: string;
  source_agent?: string;
}): Promise<{ success: boolean; rule?: ProfileRule } | null> {
  try {
    const res = await fetch('/api/v1/set_profile_rule', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.error('setProfileRule error:', err);
    return null;
  }
}

export async function deleteProfileRule(id: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/v1/profile/${id}`, {
      method: 'DELETE',
      headers: getHeaders(),
    });
    return res.ok;
  } catch (err) {
    console.error('deleteProfileRule error:', err);
    return false;
  }
}

export async function fetchConversations(
  page: number = 1,
  limit: number = 20,
  platform?: string,
  sourceAgent?: string
): Promise<{ conversations: Conversation[]; total: number; page: number; pages: number } | null> {
  try {
    const params = new URLSearchParams({ page: String(page), limit: String(limit) });
    if (platform) params.append('platform', platform);
    if (sourceAgent) params.append('source_agent', sourceAgent);

    const res = await fetch(`/api/v1/conversations?${params.toString()}`, { headers: getHeaders() });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.error('fetchConversations error:', err);
    return null;
  }
}

export async function searchMemory(
  query: string,
  category?: string,
  sourceAgent?: string,
  limit: number = 5
): Promise<SearchResult[] | null> {
  try {
    const res = await fetch('/api/v1/search_memory', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ query, category, source_agent: sourceAgent, limit }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.results || [];
  } catch (err) {
    console.error('searchMemory error:', err);
    return null;
  }
}
