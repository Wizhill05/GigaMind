/** @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import React from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { SourceHistoryDialog } from "../components/SourceHistoryDialog";
import { getSourceProvenance } from "../sourceProvenanceApi";
import { setApiKey } from "../api";
import { MemoriesTab } from "../components/tabs/MemoriesTab";
import { ProfileRulesTab } from "../components/tabs/ProfileRulesTab";
import { ToastProvider } from "../components/ui/Toast";
import { FilesTab } from "../components/tabs/FilesTab";

const body = (id = "one", offset = 0) => ({
  head: {
    kind: "memory",
    source_id: id,
    revision: 21,
    active: false,
    creator_id: null,
    creator_provenance: "legacy_unknown",
  },
  receipts: Array.from(
    { length: Math.min(20, Math.max(0, 21 - offset)) },
    (_, index) => ({
      kind: "memory",
      source_id: id,
      revision: 21 - offset - index,
      operation:
        offset + index === 0
          ? "deleted"
          : 21 - offset - index === 1
            ? "created"
            : "updated",
      writer_id: "<writer>",
      writer_provenance: "authenticated",
      payload_hash: "a".repeat(64),
      source_revision: "17",
      timestamp: "2026-01-01T00:00:00+00:00",
    }),
  ),
  total: 21,
  limit: 20,
  offset,
});
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const props = {
  kind: "memory" as const,
  sourceId: "one",
  apiKey: "secret",
  onClose: vi.fn(),
};
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("renders validated history as literal text and pages with explicit credentials", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) =>
      json(body("one", String(input).includes("offset=20") ? 20 : 0)),
    );
  render(<SourceHistoryDialog {...props} />);
  expect(
    await screen.findByText("Original credential: Unknown (legacy)"),
  ).toBeInTheDocument();
  expect(screen.getByText("Status: Deleted")).toBeInTheDocument();
  expect(screen.getAllByText("Credential: <writer>")).toHaveLength(20);
  expect(screen.getAllByText("Source revision: 17")).toHaveLength(20);
  expect(
    screen.getByText(
      /Source authorship and factual accuracy require separate verification/,
    ),
  ).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith(
    expect.stringContaining("offset=0"),
    expect.objectContaining({ headers: { Authorization: "Bearer secret" } }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByText("Receipt 1: created");
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Previous" }));
  await screen.findByText("Receipt 21: deleted");
});

test("HTTP errors retain their status and dialog offers retry", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(json({ detail: "Denied" }, 401))
    .mockResolvedValueOnce(json(body()));
  await expect(
    getSourceProvenance({ kind: "memory", sourceId: "one", apiKey: "secret" }),
  ).rejects.toMatchObject({ status: 401 });
  fetcher
    .mockResolvedValueOnce(json({ detail: "Try later" }, 503))
    .mockResolvedValueOnce(json(body()));
  render(<SourceHistoryDialog {...props} />);
  await screen.findByText("Original credential: Unknown (legacy)");
  cleanup();
  render(<SourceHistoryDialog {...props} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Try later");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByText("Original credential: Unknown (legacy)");
  fetcher.mockResolvedValueOnce(json({ detail: "Forbidden" }, 403));
  await expect(
    getSourceProvenance({ kind: "memory", sourceId: "one", apiKey: "secret" }),
  ).rejects.toMatchObject({ status: 403 });
});

test("hides obsolete source and credential responses, and aborts on unmount", async () => {
  const resolvers: Array<(response: Response) => void> = [];
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(
    () =>
      new Promise((resolve) => {
        resolvers.push(resolve);
      }),
  );
  const view = render(<SourceHistoryDialog {...props} />);
  view.rerender(<SourceHistoryDialog {...props} sourceId="two" apiKey="new" />);
  expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
  await act(async () => {
    resolvers[1](json(body("two")));
  });
  await screen.findByText("Original credential: Unknown (legacy)");
  await act(async () => {
    resolvers[0](
      json({
        ...body(),
        head: {
          ...body().head,
          creator_id: "stale",
          creator_provenance: "authenticated",
        },
      }),
    );
  });
  expect(
    screen.queryByText("Original credential: stale"),
  ).not.toBeInTheDocument();
  view.rerender(
    <SourceHistoryDialog {...props} sourceId="two" apiKey="third" />,
  );
  expect(
    screen.queryByText("Original credential: Unknown (legacy)"),
  ).not.toBeInTheDocument();
  view.unmount();
  expect(fetcher.mock.calls[2][1]?.signal?.aborted).toBe(true);
  await act(async () => {
    resolvers[2](json(body("two")));
  });
});

test("never fetches without a credential, restores focus, and closes accessibly", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch");
  const close = vi.fn();
  const trigger = document.createElement("button");
  document.body.appendChild(trigger);
  trigger.focus();
  const view = render(
    <SourceHistoryDialog {...props} apiKey="" onClose={close} />,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "API key is required",
  );
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Close dialog" })).toHaveFocus();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(close).toHaveBeenCalledOnce();
  view.unmount();
  expect(trigger).toHaveFocus();
  trigger.remove();
});

test("rejects mismatched source identity", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(json(body("wrong")));
  render(<SourceHistoryDialog {...props} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("does not match");
  await waitFor(() =>
    expect(screen.queryByText("Status: Deleted")).not.toBeInTheDocument(),
  );
});

test.each(["counter", "writer", "order"])(
  "rejects inconsistent %s metadata",
  async (corruption) => {
    const data = body();
    if (corruption === "counter") data.head.revision = 1;
    if (corruption === "writer") data.receipts[0].writer_id = "";
    if (corruption === "order") data.receipts.reverse();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(data));
    render(<SourceHistoryDialog {...props} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "does not match",
    );
    expect(screen.queryByText("Status: Deleted")).not.toBeInTheDocument();
  },
);

test("memory history is reachable, refreshes, and suspends row keyboard editing", async () => {
  setApiKey("history-test-key");
  const edit = vi.fn();
  let requests = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path.includes("/provenance")) {
      requests++;
      return json(body());
    }
    return json({
      memories: [
        {
          id: "one",
          content: "source note",
          category: "general",
          source_agent: "claimed",
        },
      ],
      total: 1,
      page: 1,
      pages: 1,
    });
  });
  const tree = (refresh: number) => (
    <ToastProvider>
      <MemoriesTab
        refreshVersion={refresh}
        onMutation={() => {}}
        onOpenNewModal={() => {}}
        onOpenEditModal={edit}
      />
    </ToastProvider>
  );
  const view = render(tree(0));
  fireEvent.click(await screen.findByRole("button", { name: "History" }));
  await screen.findByText("Original credential: Unknown (legacy)");
  fireEvent.keyDown(window, { key: "ArrowDown" });
  fireEvent.keyDown(window, { key: "Enter" });
  expect(edit).not.toHaveBeenCalled();
  view.rerender(tree(1));
  await waitFor(() => expect(requests).toBe(2));
  fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("profile history uses the stored profile ID", async () => {
  setApiKey("history-test-key");
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) => {
      if (String(input).includes("/provenance")) {
        const data = body("stored/profile?x#y");
        return json({
          ...data,
          head: { ...data.head, kind: "profile" },
          receipts: data.receipts.map((receipt) => ({
            ...receipt,
            kind: "profile",
          })),
        });
      }
      return json({
        profile: [
          {
            id: "stored/profile?x#y",
            key: "editor",
            value: "vim",
            category: "general",
            source_agent: "claimed",
            updated_at: "2026-01-01",
          },
        ],
      });
    });
  render(
    <ToastProvider>
      <ProfileRulesTab refreshVersion={0} onOpenNewRuleModal={() => {}} />
    </ToastProvider>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "History" }));
  await screen.findByText("Original credential: Unknown (legacy)");
  expect(fetcher).toHaveBeenCalledWith(
    expect.stringContaining("/sources/profile/stored%2Fprofile%3Fx%23y/provenance"),
    expect.objectContaining({
      headers: { Authorization: "Bearer history-test-key" },
    }),
  );
});

test("keeps global command shortcuts inside the modal boundary", () => {
  const globalShortcut = vi.fn();
  window.addEventListener("keydown", globalShortcut);
  try {
    render(<SourceHistoryDialog {...props} apiKey="" />);
    fireEvent.keyDown(screen.getByRole("button", { name: "Close dialog" }), {
      ctrlKey: true,
      key: "k",
    });
    expect(globalShortcut).not.toHaveBeenCalled();
  } finally {
    window.removeEventListener("keydown", globalShortcut);
  }
});

test("file history distinguishes upload registration and verified bytes and refreshes by file ID", async () => {
  setApiKey("file-history-key");
  let revision = 2;
  const fileHistory = () => ({
    head: {
      kind: "file", source_id: "opaque-file-id", revision, active: true,
      creator_id: "original-uploader", creator_provenance: "authenticated",
    },
    receipts: Array.from({ length: revision }, (_, i) => ({
      kind: "file", source_id: "opaque-file-id", revision: revision - i,
      operation: revision - i === 1 ? "created" : "verified",
      writer_id: revision - i === 1 ? "original-uploader" : "recovery-admin",
      writer_provenance: "authenticated", payload_hash: "b".repeat(64),
      source_revision: null, timestamp: "2026-11-13T10:00:00+00:00",
    })),
    total: revision, limit: 20, offset: 0,
  });
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    if (String(input).includes("/provenance")) return json(fileHistory());
    return json({ files: [{
      id: "opaque-file-id", key: "files/object/name", filename: "report.txt",
      size_bytes: 5, total_chunks: 0, extracted_text_length: 0,
      indexing_status: "pending", created_at: "2026-11-13",
    }], count: 1 });
  });
  const tree = (refresh: number) => <ToastProvider><FilesTab refreshVersion={refresh} /></ToastProvider>;
  const view = render(tree(0));
  fireEvent.click(await screen.findByRole("button", { name: "Source history for report.txt" }));
  await screen.findByText("Original credential: original-uploader");
  expect(screen.getByText("Receipt 2: verified")).toBeInTheDocument();
  expect(screen.getByText(/Created records an upload registration/)).toHaveTextContent("physical cleanup may still be pending");
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/sources/file/opaque-file-id/provenance?limit=20&offset=0",
    expect.objectContaining({ headers: { Authorization: "Bearer file-history-key" } }),
  );
  revision = 3;
  view.rerender(tree(1));
  await screen.findByText("Receipt 3: verified");
  fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("verification receipts are valid only for files", async () => {
  const data = body();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(json({
    ...data,
    head: { ...data.head, active: true },
    receipts: data.receipts.map((receipt, index) => index === 0 ? { ...receipt, operation: "verified" } : receipt),
  }));
  await expect(getSourceProvenance({ kind: "memory", sourceId: "one", apiKey: "secret" })).rejects.toThrow("does not match");
});
