import { z } from 'zod';
import { getApiKey, ApiError } from './api';

const evidence = z.object({ source_type: z.string(), source_id: z.string(), quote: z.string(), source_role: z.string().nullable().optional() });
const memory = z.object({ id: z.string(), content: z.string(), revision: z.number(), status: z.string(), writer_id: z.string(), project_id: z.string().nullable() });
const proposal = z.object({ id: z.string(), content: z.string(), revision: z.number(), status: z.string(), writer_id: z.string(), project_id: z.string().nullable(), evidence: z.array(evidence), conflicts: z.array(z.string()).default([]), accepted_memory_id: z.string().optional() });
const revision = z.object({ revision: z.number(), writer_id: z.string(), status: z.string(), created_at: z.string(), snapshot: memory });
export type Proposal = z.infer<typeof proposal>;
export type ReviewMemory = z.infer<typeof memory>;
export type Revision = z.infer<typeof revision>;

async function request<T>(path: string, schema: z.ZodType<T>, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/v1/review${path}`, { ...init, headers: { Authorization: `Bearer ${getApiKey()}`, 'Content-Type': 'application/json' } });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = z.object({ detail: z.union([z.string(), z.unknown()]) }).safeParse(body);
    throw new ApiError(response.status, detail.success ? typeof detail.data.detail === 'string' ? detail.data.detail : JSON.stringify(detail.data.detail) : `Request failed (${response.status})`);
  }
  return schema.parse(body);
}
export const listProposals = (offset: number, signal?: AbortSignal) => request(`/proposals?limit=20&offset=${offset}`, z.object({ proposals: z.array(proposal), total: z.number() }), { signal });
export const getMemory = (id: string, signal?: AbortSignal) => request(`/memories/${encodeURIComponent(id)}`, z.object({ memory }), { signal });
export const getHistory = (id: string, signal?: AbortSignal) => request(`/memories/${encodeURIComponent(id)}/history`, z.object({ revisions: z.array(revision) }), { signal });
export const resolveProposal = (id: string, data: { action: 'approve' | 'reject'; expected_revision: number; content?: string; supersedes: string[] }) => request(`/proposals/${encodeURIComponent(id)}/resolve`, z.object({ proposal, memory: memory.optional() }), { method: 'POST', body: JSON.stringify(data) });
export const restoreMemory = (id: string, data: { revision: number; expected_revision: number }) => request(`/memories/${encodeURIComponent(id)}/restore`, z.object({ memory }), { method: 'POST', body: JSON.stringify(data) });
