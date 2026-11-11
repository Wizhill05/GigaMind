import { z } from "zod";
import { ApiError, getApiKey } from "./api";

const id = z.string().min(1);
const count = z.number().int().nonnegative().safe();
const base = {
  id,
  writer_id: id,
  project_id: id.nullable(),
  revision: count.refine((n) => n > 0),
  created_at: z.string(),
  updated_at: z.string(),
  status: z.string(),
};
const handoff = z.object({
  ...base,
  record_type: z.literal("agent_report"),
  task_name: z.string(),
  summary: z.string(),
  verified_outcomes: z.array(z.string()),
  unresolved: z.array(z.string()),
  next_actions: z.array(z.string()),
});
const issue = z.object({ ...base, memory_id: id, reason: z.string() });
export type Handoff = z.infer<typeof handoff>;
export type Issue = z.infer<typeof issue>;
async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  init: RequestInit = {},
): Promise<T> {
  if (!getApiKey()) throw new Error("API key is required");
  const response = await fetch(`/api/v1/review${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${getApiKey()}`,
      "Content-Type": "application/json",
    },
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = z.object({ detail: z.unknown() }).safeParse(body);
    throw new ApiError(
      response.status,
      detail.success && typeof detail.data.detail === "string"
        ? detail.data.detail
        : `Request failed (${response.status})`,
    );
  }
  return schema.parse(body);
}
function query(project: string, offset: number) {
  const params = new URLSearchParams({ limit: "20", offset: String(offset) });
  if (project) params.set("project_id", project);
  return params;
}
export const listHandoffs = (
  project: string,
  offset: number,
  signal: AbortSignal,
) =>
  request(
    `/handoffs?${query(project, offset)}`,
    z.object({ handoffs: z.array(handoff), total: count }),
    { signal },
  );
export const listIssues = (
  project: string,
  offset: number,
  signal: AbortSignal,
) =>
  request(
    `/issues?${query(project, offset)}`,
    z.object({ issues: z.array(issue), total: count }),
    { signal },
  );
export const resolveIssue = (target: Issue, status: "resolved" | "dismissed") =>
  request(
    `/issues/${encodeURIComponent(target.id)}/resolve`,
    z.object({ issue }),
    {
      method: "POST",
      body: JSON.stringify({ status, expected_revision: target.revision }),
    },
  );
