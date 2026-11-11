import { z } from "zod";
import { ApiError, getApiKey } from "./api";

const client = z.object({
  id: z.string().min(1),
  name: z.string(),
  scopes: z.array(z.string()),
  project_ids: z.array(z.string()),
  revoked: z.boolean(),
  created_at: z.string().nullable(),
  expires_at: z.string().nullable(),
  last_used_at: z.string().nullable(),
  revision: z.number().int().nonnegative(),
});
export type Client = z.infer<typeof client>;
const issued = z.object({ client, token: z.string().min(1) });
async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api/v1/admin/clients${path}`, {
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
export const listClients = (offset: number, signal: AbortSignal) =>
  request(
    `?limit=20&offset=${offset}`,
    z.object({ clients: z.array(client) }),
    { signal },
  );
export const createClient = (data: {
  name: string;
  scopes: string[];
  project_ids: string[];
  expires_at: string | null;
}) => request("", issued, { method: "POST", body: JSON.stringify(data) });
export const rotateClient = (id: string, revision: number) =>
  request(`/${encodeURIComponent(id)}/rotate`, issued, {
    method: "POST",
    body: JSON.stringify({ expected_revision: revision }),
  });
export const revokeClient = (id: string) =>
  request(`/${encodeURIComponent(id)}/revoke`, z.object({ client }), {
    method: "POST",
  });
