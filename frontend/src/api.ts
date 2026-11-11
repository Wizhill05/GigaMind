import { z } from "zod";
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

export async function fetchStats(signal?: AbortSignal): Promise<Stats> {
  return (await checkedFetch('/api/v1/stats', { headers: getHeaders(), signal })).json();
}

export async function fetchMemories(
  page: number = 1,
  limit: number = 20,
  category?: string,
  sourceAgent?: string,
  query?: string,
  signal?: AbortSignal
): Promise<{ memories: Memory[]; total: number; page: number; pages: number }> {
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
  data: { content?: string; category?: string; source_agent?: string; tags?: string[]; attachments?: MemoryAttachment[]; expected_revision?: number }
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

const profileRuleSchema = z.object({
  id: z.string().min(1), key: z.string(), value: z.string(), category: z.string(),
  source_agent: z.string(), updated_at: z.string(),
});

export async function fetchProfileRules(category?: string, sourceAgent?: string, signal?: AbortSignal): Promise<ProfileRule[]> {
  const params = new URLSearchParams();
  if (category) params.append('category', category);
  if (sourceAgent) params.append('source_agent', sourceAgent);
  const res = await checkedFetch(`/api/v1/get_profile?${params.toString()}`, { headers: getHeaders(), signal });
  return z.object({ profile: z.array(profileRuleSchema) }).parse(await res.json()).profile;
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

export async function deleteProfileRule(id: string): Promise<void> {
  const res = await checkedFetch(`/api/v1/profile/${encodeURIComponent(id)}`, { method: 'DELETE', headers: getHeaders() });
  z.object({ success: z.literal(true), id: z.string(), message: z.string() }).parse(await res.json());
}

const conversationSchema = z.object({
  id: z.string().min(1), platform: z.string(), title: z.string(), summary: z.string(),
  source_agent: z.string(), created_at: z.string(), is_vectorized: z.boolean().optional(),
  messages: z.array(z.object({
    role: z.string().min(1), content: z.string(), id: z.string().optional(),
    created_at: z.union([z.string(), z.number().finite()]).optional(),
  }).passthrough()),
});
const conversationListSchema = z.object({
  conversations: z.array(conversationSchema), total: z.number().int().nonnegative(), total_vectorized: z.number().int().nonnegative(),
  page: z.number().int().positive(), pages: z.number().int().nonnegative(),
});

export async function fetchConversations(
  page: number = 1, limit: number = 20, platform?: string, sourceAgent?: string, signal?: AbortSignal
): Promise<z.infer<typeof conversationListSchema>> {
  const params = new URLSearchParams({ page: String(page), limit: String(limit) });
  if (platform) params.append('platform', platform);
  if (sourceAgent) params.append('source_agent', sourceAgent);
  const res = await checkedFetch(`/api/v1/conversations?${params.toString()}`, { headers: getHeaders(), signal });
  return conversationListSchema.parse(await res.json());
}

const conversationMutationSchema = z.object({ success: z.literal(true), id: z.string(), message: z.string() });
const backfillSchema = z.object({ success: z.literal(true), message: z.string() });
const importSchema = z.object({ success: z.literal(true), ingested: z.number().int().nonnegative(), skipped: z.number().int().nonnegative(), pending_indexing: z.number().int().nonnegative(), total_processed: z.number().int().nonnegative(), message: z.string() });

export async function fetchConversation(id: string, signal?: AbortSignal) {
  const res = await checkedFetch(`/api/v1/conversations/${encodeURIComponent(id)}`, { headers: getHeaders(), signal });
  return z.object({ conversation: conversationSchema }).parse(await res.json()).conversation;
}

export async function deleteConversation(id: string) {
  const res = await checkedFetch(`/api/v1/conversations/${encodeURIComponent(id)}`, { method: 'DELETE', headers: getHeaders() });
  return conversationMutationSchema.parse(await res.json());
}

export async function vectorizeConversation(id: string) {
  const res = await checkedFetch(`/api/v1/conversations/${encodeURIComponent(id)}/vectorize`, { method: 'POST', headers: getHeaders() });
  return conversationMutationSchema.parse(await res.json());
}

export async function backfillConversationVectors() {
  const res = await checkedFetch('/api/v1/conversations/backfill_vectors', { method: 'POST', headers: getHeaders() });
  return backfillSchema.parse(await res.json());
}

const conversationSearchResultSchema = conversationSchema.extend({
  messages_count: z.number().int().nonnegative(), score: z.number().finite(),
  lexical_score: z.number().finite(), vector_score: z.number().finite().optional(),
  retrieval_method: z.enum(['lexical', 'vector', 'lexical+vector']),
  evidence: z.array(z.object({ role: z.string(), index: z.number().int(), text: z.string() }).passthrough()),
});
const conversationSearchSchema = z.object({ results: z.array(conversationSearchResultSchema), count: z.number().int().nonnegative(), query: z.string(), platform: z.string().nullable() });
export type ConversationSearchResult = z.infer<typeof conversationSearchResultSchema>;
export async function searchConversations(query: string, platform?: string, sourceAgent?: string, limit: number = 10, signal?: AbortSignal): Promise<ConversationSearchResult[]> {
  const res = await checkedFetch('/api/v1/conversations/search', {
    method: 'POST', headers: getHeaders(), signal,
    body: JSON.stringify({ query, platform, source_agent: sourceAgent, limit }),
  });
  return conversationSearchSchema.parse(await res.json()).results;
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

export async function uploadFile(
  file: File,
  prefix: string = "files",
): Promise<{ success: boolean; file?: MemoryAttachment; error?: string }> {
  try {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(
      `/api/v1/files/upload?prefix=${encodeURIComponent(prefix)}`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${getApiKey()}`,
        },
        body: formData,
      },
    );
    if (!res.ok) {
      const body: unknown = await res.json().catch(() => null);
      const detail = z.object({ detail: z.json() }).safeParse(body);
      const recoverable = z
        .object({ message: z.string(), key: z.string(), job_id: z.string() })
        .safeParse(detail.success ? detail.data.detail : null);
      const error = recoverable.success
        ? `${recoverable.data.message}. Recovery reference: ${recoverable.data.key}, job ${recoverable.data.job_id}`
        : detail.success
          ? typeof detail.data.detail === "string"
            ? detail.data.detail
            : JSON.stringify(detail.data.detail)
          : `Upload failed (${res.status})`;
      return { success: false, error };
    }
    const body: unknown = await res.json();
    return z
      .object({
        success: z.literal(true),
        file: z.object({
          key: z.string().min(1),
          filename: z.string().min(1),
          mime_type: z.string().optional(),
          size_bytes: z.number().int().nonnegative().optional(),
          url: z.string().optional(),
          created_at: z.string().optional(),
        }),
      })
      .parse(body);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Network error";
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

export async function importConversationsFile(file: File, platform?: string) {
  const formData = new FormData();
  formData.append('file', file);
  const url = platform ? `/api/v1/conversations/import_file?platform=${encodeURIComponent(platform)}` : '/api/v1/conversations/import_file';
  const res = await checkedFetch(url, { method: 'POST', headers: { Authorization: `Bearer ${getApiKey()}` }, body: formData });
  return importSchema.parse(await res.json());
}
