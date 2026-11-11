import { z } from "zod";
import { ApiError, getApiKey } from "./api";

const job = z.object({
  id: z.string().min(1),
  kind: z.string(),
  payload: z.record(z.string(), z.unknown()),
  state: z.enum([
    "queued",
    "running",
    "retrying",
    "completed",
    "failed",
    "cancelled",
  ]),
  result: z.unknown().nullable(),
  error: z.string().nullable(),
  attempts: z.number().int().nonnegative(),
  max_attempts: z.number().int().positive(),
  created_at: z.string(),
  updated_at: z.string(),
  available_at: z.string(),
});
export type Job = z.infer<typeof job>;
async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
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
export const listJobs = (offset: number, signal: AbortSignal) =>
  request(`/jobs?limit=20&offset=${offset}`, z.object({ jobs: z.array(job) }), {
    signal,
  });
export const getJob = (id: string, signal: AbortSignal) =>
  request(`/jobs/${encodeURIComponent(id)}`, job, { signal });
export const cancelJob = (id: string) =>
  request(`/jobs/${encodeURIComponent(id)}/cancel`, job, { method: "POST" });
const requestId = () => {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
};
export const retryIndex = (item: Job) =>
  request("/jobs", job, {
    method: "POST",
    body: JSON.stringify({
      kind: "index_file",
      payload: item.payload,
      idempotency_key: requestId(),
      max_attempts: item.max_attempts,
    }),
  });
export const retryCleanup = (key: string) =>
  request(
    "/files/delete",
    z.object({
      key: z.string(),
      job_id: z.string().min(1),
      state: z.string(),
      cleanup: z.enum(["pending", "completed"]),
    }),
    { method: "POST", body: JSON.stringify({ key }) },
  );
