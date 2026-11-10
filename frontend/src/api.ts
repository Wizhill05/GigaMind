import { Memory, MemoryAttachment, StorageFile, StorageChunk, ProfileRule, Conversation, SearchResult, Stats } from './types';

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

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); this.name = 'ApiError'; }
}

async function checkedFetch(input: string, init: RequestInit): Promise<Response> {
  let response: Response;
  try { response = await fetch(input, init); }
  catch (error) { if (typeof error === 'object' && error !== null && 'name' in error && error.name === 'AbortError') throw error; throw new ApiError(0, error instanceof Error ? `Network error: ${error.message}` : 'Network error'); }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : null;
    throw new ApiError(response.status, typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => typeof item?.msg === 'string' ? item.msg : JSON.stringify(item)).join('; ') : `Request failed (${response.status})`);
  }
  return response;
}

export async function fetchStats(): Promise<Stats> {
  return (await checkedFetch('/api/v1/stats', { headers: getHeaders() })).json();
}

export async function fetchMemories(
  page: number = 1,
  limit: number = 20,
  category?: string,
  sourceAgent?: string,
  query?: string,
  signal?: AbortSignal
): Promise<{ memories: Memory[]; total: number; page: number; pages: number } | null> {
  const params = new URLSearchParams({ page: String(page), limit: String(limit) });
  if (category) params.append('category', category);
  if (sourceAgent) params.append('source_agent', sourceAgent);
  if (query) params.append('q', query);
  return (await checkedFetch(`/api/v1/memories?${params.toString()}`, { headers: getHeaders(), signal })).json();
}

export async function addMemory(data: {
  content: string;
  category?: string;
  source_agent?: string;
  tags?: string[];
  attachments?: MemoryAttachment[];
  file_keys?: string[];
  media_url?: string;
  media_type?: string;
}): Promise<{ success: boolean; memory?: Memory } | null> {
    const res = await checkedFetch('/api/v1/add_memory', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    return await res.json();
}

export async function updateMemory(
  id: string,
  data: { content?: string; category?: string; source_agent?: string; tags?: string[]; attachments?: MemoryAttachment[] }
): Promise<{ success: boolean; memory?: Memory } | null> {
    const res = await checkedFetch(`/api/v1/memories/${id}`, {
      method: 'PUT',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    return await res.json();
}

export async function deleteMemory(id: string): Promise<boolean> {
  await checkedFetch(`/api/v1/memories/${id}`, { method: 'DELETE', headers: getHeaders() });
  return true;
}

export async function exportMemories(format: 'json' | 'csv' = 'json'): Promise<void> {
  const res = await checkedFetch(`/api/v1/memories/export?format=${format}`, { headers: getHeaders() });
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `gigamind_memories_export.${format}`;
  document.body.appendChild(a);
  try {
    a.click();
  } finally {
    window.URL.revokeObjectURL(url);
    a.remove();
  }
}

export async function hardResetMemories(password: string): Promise<{ success: boolean; count?: number; message?: string }> {
  const res = await checkedFetch('/api/v1/memories/reset', {
    method: 'POST',
    headers: getHeaders(),
    body: JSON.stringify({ password }),
  });
  return res.json();
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
    const res = await checkedFetch('/api/v1/set_profile_rule', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    return await res.json();
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
): Promise<{ conversations: Conversation[]; total: number; total_vectorized?: number; page: number; pages: number } | null> {
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

export async function deleteConversation(id: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/v1/conversations/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: getHeaders(),
    });
    return res.ok;
  } catch (err) {
    console.error('deleteConversation error:', err);
    return false;
  }
}

export async function vectorizeConversation(id: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/v1/conversations/${encodeURIComponent(id)}/vectorize`, {
      method: 'POST',
      headers: getHeaders(),
    });
    return res.ok;
  } catch (err) {
    console.error('vectorizeConversation error:', err);
    return false;
  }
}

export async function backfillConversationVectors(): Promise<boolean> {
  try {
    const res = await fetch('/api/v1/conversations/backfill_vectors', {
      method: 'POST',
      headers: getHeaders(),
    });
    return res.ok;
  } catch (err) {
    console.error('backfillConversationVectors error:', err);
    return false;
  }
}

export async function searchConversations(
  query: string,
  platform?: string,
  sourceAgent?: string,
  limit: number = 10
): Promise<any[] | null> {
  try {
    const res = await fetch('/api/v1/conversations/search', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ query, platform, source_agent: sourceAgent, limit }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.results || [];
  } catch (err) {
    console.error('searchConversations error:', err);
    return null;
  }
}

export async function searchMemory(
  query?: string,
  category?: string,
  sourceAgent?: string,
  limit: number = 5,
  scope: string = 'all',
  imageBase64?: string
): Promise<SearchResult[] | null> {
  try {
    const res = await fetch('/api/v1/search_memory', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({
        query: query || null,
        image_base64: imageBase64 || null,
        category,
        source_agent: sourceAgent,
        limit,
        scope
      }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.results || [];
  } catch (err) {
    console.error('searchMemory error:', err);
    return null;
  }
}

export async function searchFiles(query?: string, limit: number = 5, imageBase64?: string): Promise<SearchResult[] | null> {
  try {
    const res = await fetch('/api/v1/search_files', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({
        query: query || null,
        image_base64: imageBase64 || null,
        limit
      }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.results || [];
  } catch (err) {
    console.error('searchFiles error:', err);
    return null;
  }
}

export async function searchMultimodal(
  query?: string,
  imageBase64?: string,
  scope: string = 'all',
  limit: number = 5
): Promise<SearchResult[] | null> {
  try {
    const res = await fetch('/api/v1/search_multimodal', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({
        query: query || null,
        image_base64: imageBase64 || null,
        scope,
        limit
      }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.results || [];
  } catch (err) {
    console.error('searchMultimodal error:', err);
    return null;
  }
}

export async function uploadFile(file: File, prefix: string = 'files'): Promise<{ success: boolean; file?: MemoryAttachment; error?: string }> {
  try {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`/api/v1/files/upload?prefix=${encodeURIComponent(prefix)}`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${getApiKey()}`,
      },
      body: formData,
    });
    if (!res.ok) {
      const errJson = (await res.json().catch(() => ({}))) as { detail?: string };
      return { success: false, error: errJson.detail || 'Upload failed' };
    }
    return await res.json();
  } catch (err: unknown) {
    console.error('uploadFile error:', err);
    const message = err instanceof Error ? err.message : 'Network error';
    return { success: false, error: message };
  }
}

export async function fetchFiles(prefix: string = '', limit: number = 100): Promise<{ enabled: boolean; files: MemoryAttachment[] } | null> {
  try {
    const res = await fetch(`/api/v1/files?prefix=${encodeURIComponent(prefix)}&limit=${limit}`, {
      headers: getHeaders(),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.error('fetchFiles error:', err);
    return null;
  }
}

export async function deleteStorageFile(key: string): Promise<boolean> {
  try {
    const res = await fetch('/api/v1/files/delete', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ key }),
    });
    if (res.ok) return true;

    // Fallback to path parameter DELETE endpoint
    const fallbackRes = await fetch(`/api/v1/files/${encodeURIComponent(key)}`, {
      method: 'DELETE',
      headers: getHeaders(),
    });
    return fallbackRes.ok;
  } catch (err) {
    console.error('deleteStorageFile error:', err);
    return false;
  }
}

export async function fetchIndexedFiles(limit: number = 100): Promise<{ files: StorageFile[]; count: number } | null> {
  try {
    const res = await fetch(`/api/v1/files/indexed?limit=${limit}`, {
      headers: getHeaders(),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.error('fetchIndexedFiles error:', err);
    return null;
  }
}

export async function reindexStorageFile(key: string): Promise<boolean> {
  try {
    const res = await fetch('/api/v1/files/reindex', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ key }),
    });
    return res.ok;
  } catch (err) {
    console.error('reindexStorageFile error:', err);
    return false;
  }
}

export async function fetchFileChunks(key: string): Promise<{ key: string; chunks: StorageChunk[]; count: number } | null> {
  try {
    const res = await fetch(`/api/v1/files/chunks?key=${encodeURIComponent(key)}`, {
      headers: getHeaders(),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.error('fetchFileChunks error:', err);
    return null;
  }
}

export async function importConversationsFile(file: File, platform?: string): Promise<{ success: boolean; ingested: number; skipped: number; message: string } | null> {
  try {
    const formData = new FormData();
    formData.append('file', file);
    const url = platform ? `/api/v1/conversations/import_file?platform=${encodeURIComponent(platform)}` : '/api/v1/conversations/import_file';
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${getApiKey()}`,
      },
      body: formData,
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.error('importConversationsFile error:', err);
    return null;
  }
}
