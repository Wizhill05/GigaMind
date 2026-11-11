import { z } from "zod";
import { ApiError, getApiKey } from "./api";

const evidence = z.object({
  source_type: z.string(),
  source_id: z.string(),
  quote: z.string(),
  source_role: z.string().nullable().optional(),
});
const memory = z.object({
  id: z.string().min(1),
  content: z.string(),
  project_id: z.string().nullable(),
  writer_id: z.string(),
  revision: z.number().int().positive().safe(),
  status: z.string(),
  kind: z.string().optional(),
  valid_from: z.string().nullable().optional(),
  valid_until: z.string().nullable().optional(),
  evidence: z.array(evidence).default([]),
});
const history = z.object({
  revisions: z.array(
    z.object({
      revision: z.number().int().positive().safe(),
      status: z.string(),
      snapshot: memory,
    }),
  ),
});
export type Knowledge = z.infer<typeof memory>;
export type History = z.infer<typeof history>["revisions"];

async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api/v1/review${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${getApiKey()}`,
      "Content-Type": "application/json",
    },
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = z.object({ detail: z.string() }).safeParse(body);
    throw new ApiError(
      response.status,
      detail.success
        ? detail.data.detail
        : `Request failed (${response.status})`,
    );
  }
  return schema.parse(body);
}
export function listKnowledge(
  q: string,
  project: string,
  status: string,
  offset: number,
  signal: AbortSignal,
) {
  const params = new URLSearchParams({
    q,
    status,
    limit: "20",
    offset: String(offset),
  });
  if (project) params.set("project_id", project);
  return request(
    `/knowledge?${params}`,
    z.object({
      memories: z.array(memory),
      total: z.number().int().nonnegative().safe(),
    }),
    { signal },
  );
}
export const getKnowledgeHistory = (id: string, signal: AbortSignal) =>
  request(`/memories/${encodeURIComponent(id)}/history`, history, { signal });
export const deleteKnowledge = (id: string, expected_revision: number) =>
  request(`/memories/${encodeURIComponent(id)}/delete`, z.object({ memory }), {
    method: "POST",
    body: JSON.stringify({ expected_revision }),
  });
export const restoreKnowledge = (
  id: string,
  revision: number,
  expected_revision: number,
) =>
  request(`/memories/${encodeURIComponent(id)}/restore`, z.object({ memory }), {
    method: "POST",
    body: JSON.stringify({ revision, expected_revision }),
  });
export const setKnowledgeValidity = (id: string, expected_revision: number, valid_from: string | null, valid_until: string | null) =>
  request(`/memories/${encodeURIComponent(id)}/validity`, z.object({ memory }), {
    method: "POST",
    body: JSON.stringify({ expected_revision, valid_from, valid_until }),
  });
