import { z } from "zod";
import { Memory, MemoryAttachment, ProfileRule, Conversation, Stats } from './types';

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

const legacySearchResultSchema = z
  .object({
    id: z.string().min(1),
    source: z.string(),
    content: z.string(),
    score: z.number(),
    category: z.string().optional(),
    source_agent: z.string().optional(),
    vector_score: z.number().optional(),
    rerank_score: z.number().optional(),
    parent_id: z.string().nullable().optional(),
    tags: z.array(z.string()).optional(),
    attachments: z
      .array(
        z.object({
          key: z.string(),
          filename: z.string(),
          mime_type: z.string().optional(),
          size_bytes: z.number().nonnegative().optional(),
          url: z.string().optional(),
          created_at: z.string().optional(),
        }),
      )
      .optional(),
    filename: z.string().optional(),
    file_key: z.string().optional(),
    file_id: z.string().optional(),
    multimodal_type: z.string().optional(),
    page_number: z.number().nullable().optional(),
    chunk_index: z.number().int().nullable().optional(),
    total_chunks: z.number().int().nullable().optional(),
    chunk_info: z
      .object({ index: z.number().int(), total: z.number().int() })
      .optional(),
    is_visual_anchor: z.boolean().optional(),
    matching_pages: z.array(z.number()).optional(),
    citation: z.string().optional(),
    url: z.string().optional(),
    retrieval_method: z.string().optional(),
  })
  .passthrough();
export type LegacySearchResult = z.infer<typeof legacySearchResultSchema>;

export async function searchMemory(
  query?: string,
  category?: string,
  sourceAgent?: string,
  limit: number = 5,
  scope: string = "all",
  imageBase64?: string,
  signal?: AbortSignal,
): Promise<LegacySearchResult[]> {
  const res = await checkedFetch("/api/v1/search_memory", {
    method: "POST",
    headers: getHeaders(),
    signal,
    body: JSON.stringify({
      query: query || null,
      image_base64: imageBase64 || null,
      category,
      source_agent: sourceAgent,
      limit,
      scope,
    }),
  });
  return z
    .object({ results: z.array(legacySearchResultSchema) })
    .parse(await res.json()).results;
}

const fileSearchResultSchema = z.object({
  id: z.string(), source: z.string(), content: z.string(), score: z.number(),
  filename: z.string().optional(), file_key: z.string().optional(), file_id: z.string().optional(),
  multimodal_type: z.string().optional(), page_number: z.number().nullable().optional(),
  chunk_index: z.number().nullable().optional(), total_chunks: z.number().nullable().optional(),
  vector_score: z.number().optional(), rerank_score: z.number().optional(),
  matching_pages: z.array(z.number()).optional(), citation: z.string().optional(), url: z.string().optional(),
}).passthrough();
export type FileSearchResult = z.infer<typeof fileSearchResultSchema>;

export async function searchFiles(query?: string, limit: number = 5, imageBase64?: string, signal?: AbortSignal): Promise<FileSearchResult[]> {
  const res = await checkedFetch('/api/v1/search_files', {
    method: 'POST', headers: getHeaders(), signal,
    body: JSON.stringify({ query: query || null, image_base64: imageBase64 || null, limit }),
  });
  return z.object({ results: z.array(fileSearchResultSchema) }).parse(await res.json()).results;
}

const recoveryReferenceSchema = z.object({ key: z.string().min(1).max(1024), job_id: z.string().min(1).max(255) });
export type UploadRecoveryReference = z.infer<typeof recoveryReferenceSchema>;
const recoveryResultSchema = recoveryReferenceSchema.extend({ state: z.string().min(1), verified: z.literal(true) });

export async function recoverUpload(reference: UploadRecoveryReference) {
  const checked = recoveryReferenceSchema.parse(reference);
  const response = await checkedFetch('/api/v1/files/upload/recover', {
    method: 'POST', headers: getHeaders(), body: JSON.stringify(checked),
  });
  const result = recoveryResultSchema.parse(await response.json());
  if (result.key !== checked.key || result.job_id !== checked.job_id) throw new Error('Recovery response does not match the requested upload');
  return result;
}

export async function uploadFile(
  file: File,
  prefix: string = "files",
): Promise<{ success: true; file: MemoryAttachment; error?: never } | { success: false; file?: never; error: string; recovery?: UploadRecoveryReference }> {
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
        .object({ message: z.string(), key: z.string().min(1).max(1024), job_id: z.string().min(1).max(255) })
        .safeParse(detail.success ? detail.data.detail : null);
      const error = recoverable.success
        ? `${recoverable.data.message}. Recovery reference: ${recoverable.data.key}, job ${recoverable.data.job_id}`
        : detail.success
          ? typeof detail.data.detail === "string"
            ? detail.data.detail
            : JSON.stringify(detail.data.detail)
          : `Upload failed (${res.status})`;
      return { success: false, error, ...(recoverable.success ? { recovery: { key: recoverable.data.key, job_id: recoverable.data.job_id } } : {}) };
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

const fileSchema = z.object({
  id: z.string().min(1), key: z.string().min(1), filename: z.string(),
  mime_type: z.string().nullish().transform(v => v ?? undefined),
  size_bytes: z.number().int().nonnegative().safe(), source_agent: z.string().nullish().transform(v => v ?? undefined),
  extracted_text_length: z.number().int().nonnegative().safe(), total_chunks: z.number().int().nonnegative().safe(), indexing_status: z.string(),
  url: z.string().nullish().transform(v => v ?? undefined), created_at: z.string(),
  updated_at: z.string().nullish().transform(v => v ?? undefined),
});
const chunkSchema = z.object({
  id: z.string().min(1), file_key: z.string().min(1), chunk_index: z.number().int().nonnegative(), total_chunks: z.number().int().nonnegative(),
  page_number: z.number().nullish().transform(v => v ?? undefined),
  is_visual_anchor: z.boolean().nullish().transform(v => v ?? undefined),
  content: z.string(), created_at: z.string(),
});
const jobSchema = z.object({ key: z.string().min(1), job_id: z.string().min(1), state: z.string().min(1) });

export async function deleteStorageFile(key: string) {
  const res = await checkedFetch('/api/v1/files/delete', {
    method: 'POST', headers: getHeaders(), body: JSON.stringify({ key }),
  });
  return jobSchema.extend({ cleanup: z.enum(['pending', 'completed']) }).parse(await res.json());
}

export async function fetchIndexedFiles(limit = 100, signal?: AbortSignal) {
  const res = await checkedFetch(`/api/v1/files/indexed?limit=${limit}`, { headers: getHeaders(), signal });
  return z.object({ files: z.array(fileSchema), count: z.number().int().nonnegative().safe() }).parse(await res.json());
}

export async function reindexStorageFile(key: string) {
  const res = await checkedFetch('/api/v1/files/reindex', {
    method: 'POST', headers: getHeaders(), body: JSON.stringify({ key }),
  });
  return jobSchema.parse(await res.json());
}

export async function fetchFileChunks(key: string, signal?: AbortSignal) {
  const res = await checkedFetch(`/api/v1/files/chunks?key=${encodeURIComponent(key)}`, { headers: getHeaders(), signal });
  return z.object({ key: z.string().min(1), chunks: z.array(chunkSchema), count: z.number().int().nonnegative().safe() }).parse(await res.json());
}

export async function importConversationsFile(file: File, platform?: string) {
  const formData = new FormData();
  formData.append('file', file);
  const url = platform ? `/api/v1/conversations/import_file?platform=${encodeURIComponent(platform)}` : '/api/v1/conversations/import_file';
  const res = await checkedFetch(url, { method: 'POST', headers: { Authorization: `Bearer ${getApiKey()}` }, body: formData });
  return importSchema.parse(await res.json());
}
