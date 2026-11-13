import { z } from "zod";
import { ApiError } from "./api";

const kindSchema = z.enum(["memory", "profile", "file"]);
const integer = z.number().int().nonnegative().safe();
const receiptSchema = z.object({
  kind: kindSchema,
  source_id: z.string().min(1),
  revision: z.number().int().positive().safe(),
  operation: z.enum(["created", "updated", "deleted", "reset", "verified"]),
  writer_id: z.string().nullable(),
  writer_provenance: z.enum(["authenticated", "unattributed"]),
  payload_hash: z
    .string()
    .regex(/^[a-f0-9]{64}$/)
    .nullable(),
  source_revision: z.string().regex(/^\d+$/).nullable(),
  timestamp: z.iso
    .datetime({ offset: true })
    .refine(
      (value) => value.endsWith("Z") || value.endsWith("+00:00"),
      "Expected a UTC timestamp",
    ),
});
const provenanceSchema = z.object({
  head: z.object({
    kind: kindSchema,
    source_id: z.string().min(1),
    revision: integer,
    active: z.boolean(),
    creator_id: z.string().nullable(),
    creator_provenance: z.enum([
      "authenticated",
      "unattributed",
      "legacy_unknown",
    ]),
  }),
  receipts: z.array(receiptSchema),
  total: integer,
  limit: z.number().int().min(1).max(100),
  offset: integer,
});
export type SourceKind = z.infer<typeof kindSchema>;
export type SourceProvenance = z.infer<typeof provenanceSchema>;

export async function getSourceProvenance({
  kind,
  sourceId,
  apiKey,
  offset = 0,
  signal,
}: {
  kind: SourceKind;
  sourceId: string;
  apiKey: string;
  offset?: number;
  signal?: AbortSignal;
}): Promise<SourceProvenance> {
  if (!apiKey.trim()) throw new ApiError(401, "An API key is required.");
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > 1_000_000)
    throw new Error("Invalid history offset");
  const response = await fetch(
    `/api/v1/sources/${kind}/${encodeURIComponent(sourceId)}/provenance?limit=20&offset=${offset}`,
    {
      headers: { Authorization: `Bearer ${apiKey}` },
      signal,
    },
  );
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
  const parsed = provenanceSchema.safeParse(body);
  if (!parsed.success)
    throw new Error("The server returned invalid source history. Retry.");
  const result = parsed.data;
  const latest = result.receipts[0];
  if (
    result.head.kind !== kind ||
    result.head.source_id !== sourceId ||
    result.receipts.some(
      (receipt) => receipt.kind !== kind || receipt.source_id !== sourceId,
    ) ||
    result.offset !== offset ||
    result.limit !== 20 ||
    result.total !== result.head.revision ||
    (offset === 0 &&
      latest &&
      result.head.active !==
        !["deleted", "reset"].includes(latest.operation)) ||
    (result.head.creator_provenance !== "authenticated" &&
      result.head.creator_id !== null) ||
    (result.head.creator_provenance === "authenticated" &&
      !result.head.creator_id?.trim()) ||
    result.receipts.length !==
      Math.min(result.limit, Math.max(0, result.total - offset)) ||
    result.receipts.some(
      (receipt, index) =>
        receipt.revision !== result.total - offset - index ||
        (receipt.operation === "verified" && kind !== "file") ||
        (receipt.writer_provenance === "authenticated" &&
          !receipt.writer_id?.trim()) ||
        (receipt.writer_provenance === "unattributed" &&
          receipt.writer_id !== null),
    )
  ) {
    throw new Error("History response does not match the request.");
  }
  return result;
}
