// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { ApiError, fetchMemories, uploadFile } from "../api";
afterEach(() => vi.unstubAllGlobals());
it("reports structured validation details", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: [{ msg: "Invalid query" }] }), {
          status: 422,
        }),
      ),
  );
  await expect(fetchMemories()).rejects.toMatchObject({
    name: "ApiError",
    status: 422,
    message: "Invalid query",
  } satisfies Partial<ApiError>);
});
it("preserves cancellation and sends the search query", async () => {
  const abort = new DOMException("cancelled", "AbortError");
  const fetchMock = vi.fn().mockRejectedValue(abort);
  vi.stubGlobal("fetch", fetchMock);
  await expect(
    fetchMemories(1, 10, undefined, undefined, "hello"),
  ).rejects.toBe(abort);
  expect(fetchMock.mock.calls[0][0]).toContain("q=hello");
});

it("renders recoverable upload errors as text with the recovery reference", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              message: "Upload outcome unknown",
              key: "files/key",
              job_id: "pending-job",
            },
          }),
          { status: 503 },
        ),
      ),
  );
  const result = await uploadFile(new File(["abc"], "a.txt"));
  expect(result).toEqual({
    success: false,
    error:
      "Upload outcome unknown. Recovery reference: files/key, job pending-job",
  });
});
it("rejects malformed upload success rather than passing unchecked data into attachments", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ success: true, file: { key: 1 } }), {
          status: 202,
        }),
      ),
  );
  expect((await uploadFile(new File(["abc"], "a.txt"))).success).toBe(false);
});
