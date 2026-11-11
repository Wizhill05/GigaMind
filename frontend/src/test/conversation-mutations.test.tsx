// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  act,
  within,
} from "@testing-library/react";
import { ConversationsTab } from "../components/tabs/ConversationsTab";
import { ToastProvider } from "../components/ui/Toast";
import { setApiKey } from "../api";

const list = () =>
  new Response(
    JSON.stringify({
      conversations: [
        {
          id: "1",
          title: "Example",
          platform: "claude",
          summary: "",
          source_agent: "user",
          messages: [],
          created_at: "",
          is_vectorized: false,
        },
      ],
      total: 1,
      total_vectorized: 0,
      page: 1,
      pages: 1,
    }),
  );
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});
it("retains a failed import for retry and reports pending indexing", async () => {
  const changed = vi.fn();
  let imports = 0;
  const fetcher = vi.fn((url: string) => {
    if (!url.includes("/import_file")) return Promise.resolve(list());
    imports++;
    return Promise.resolve(
      imports === 1
        ? new Response(JSON.stringify({ detail: "Bad export" }), {
            status: 400,
          })
        : new Response(
            JSON.stringify({
              success: true,
              ingested: 2,
              skipped: 1,
              pending_indexing: 2,
              total_processed: 3,
              message: "Imported",
            }),
          ),
    );
  });
  vi.stubGlobal("fetch", fetcher);
  const view = render(
    <ToastProvider>
      <ConversationsTab onOpenTranscript={() => {}} onMutation={changed} />
    </ToastProvider>,
  );
  fireEvent.click(screen.getByText("Import Chat History"));
  fireEvent.change(screen.getByLabelText("Import format"), {
    target: { value: "claude" },
  });
  const input = view.container.querySelector("input[type=file]");
  if (!input) throw new Error("missing file input");
  fireEvent.change(input, {
    target: {
      files: [new File(["{}"], "export.json", { type: "application/json" })],
    },
  });
  expect(await screen.findByText("Error: Bad export")).toBeTruthy();
  fireEvent.click(screen.getByText("Retry export.json"));
  expect(
    await screen.findByText("Imported 2; skipped 1; 2 pending indexing."),
  ).toBeTruthy();
  expect(changed).toHaveBeenCalledTimes(1);
  const importCalls = fetcher.mock.calls.filter(([url]) =>
    url.includes("/import_file"),
  );
  expect(importCalls).toHaveLength(2);
  expect(importCalls.every(([url]) => url.includes("platform=claude"))).toBe(
    true,
  );
});
it("keeps the row and displays a delete error", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(list())
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Delete denied" }), {
          status: 403,
        }),
      ),
  );
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(
    <ToastProvider>
      <ConversationsTab onOpenTranscript={() => {}} />
    </ToastProvider>,
  );
  await screen.findByText("Example");
  fireEvent.click(screen.getByTitle("Delete Transcript from Database"));
  await waitFor(() => expect(screen.getByText("Delete denied")).toBeTruthy());
  expect(screen.getByText("Example")).toBeTruthy();
});
it("blocks duplicate vectorization and preserves the row on failure", async () => {
  let resolve: (response: Response) => void = () => {};
  const pending = new Promise<Response>((r) => {
    resolve = r;
  });
  const fetcher = vi.fn((url: string) =>
    url.includes("/vectorize") ? pending : Promise.resolve(list()),
  );
  vi.stubGlobal("fetch", fetcher);
  render(
    <ToastProvider>
      <ConversationsTab onOpenTranscript={() => {}} />
    </ToastProvider>,
  );
  await screen.findByText("Example");
  const button = screen.getByText("Pending Vectorization");
  fireEvent.click(button);
  fireEvent.click(button);
  expect(
    fetcher.mock.calls.filter(([url]) => url.includes("/vectorize")),
  ).toHaveLength(1);
  resolve(
    new Response(JSON.stringify({ detail: "Vector service unavailable" }), {
      status: 503,
    }),
  );
  expect(await screen.findByText("Vector service unavailable")).toBeTruthy();
  expect(screen.getByText("Pending Vectorization")).toBeTruthy();
});
it("blocks App navigation and drawer close until a failed request settles", async () => {
  const { App } = await import("../App");
  const { within, act } = await import("@testing-library/react");
  localStorage.setItem("gigamind_master_key", "key");
  let resolve: (response: Response) => void = () => {};
  const pending = new Promise<Response>((r) => {
    resolve = r;
  });
  const fetcher = vi.fn((url: string) => {
    if (url.includes("/vectorize")) return pending;
    if (url.includes("/stats"))
      return Promise.resolve(
        new Response(
          JSON.stringify({
            total_memories: 0,
            total_storage_files: 0,
            total_profile_rules: 0,
            total_chat_logs: 1,
          }),
        ),
      );
    return Promise.resolve(list());
  });
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  const sidebar = within(await screen.findByRole("complementary"));
  fireEvent.click(sidebar.getByRole("button", { name: /Chat Transcripts/ }));
  await screen.findByText("Example");
  fireEvent.click(screen.getByText("Inspect"));
  fireEvent.click(screen.getByTitle("Generate Vector Embedding"));
  fireEvent.click(screen.getByTitle("Generate Vector Embedding"));
  expect(
    fetcher.mock.calls.filter(([url]) => url.includes("/vectorize")),
  ).toHaveLength(1);
  expect(
    sidebar.getByRole("button", { name: /Memories/ }).matches(":disabled"),
  ).toBe(true);
  expect(screen.getByTitle("Close Drawer").hasAttribute("disabled")).toBe(true);
  fireEvent.keyDown(window, { key: "k", ctrlKey: true });
  fireEvent.click(screen.getByText("New Memory"));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await act(async () =>
    resolve(
      new Response(JSON.stringify({ detail: "Unavailable" }), { status: 503 }),
    ),
  );
  expect(await screen.findByText("Unavailable")).toBeTruthy();
  expect(screen.getByTitle("Close Drawer").hasAttribute("disabled")).toBe(
    false,
  );
  expect(
    sidebar.getByRole("button", { name: /Memories/ }).matches(":disabled"),
  ).toBe(false);
  localStorage.clear();
});

function deferredResponse() {
  let finish: (response: Response) => void = () => {};
  const promise = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  return { promise, finish };
}

it("retains the source and releases the lock when backfill fails", async () => {
  const pending = deferredResponse();
  const changed = vi.fn();
  const fetcher = vi.fn((url: string) =>
    url.includes("backfill_vectors")
      ? pending.promise
      : Promise.resolve(list()),
  );
  vi.stubGlobal("fetch", fetcher);
  render(
    <ToastProvider>
      <ConversationsTab onOpenTranscript={() => {}} onMutation={changed} />
    </ToastProvider>,
  );
  await screen.findByText("Example");
  const button = screen.getByText("Vectorize All").closest("button");
  if (!button) throw new Error("Missing backfill action");
  fireEvent.click(button);
  fireEvent.click(button);
  expect(button).toBeDisabled();
  await act(async () =>
    pending.finish(
      new Response(JSON.stringify({ detail: "Backfill unavailable" }), {
        status: 503,
      }),
    ),
  );
  await screen.findByText("Backfill unavailable");
  expect(button).toBeEnabled();
  expect(button.querySelector(".animate-spin")).toBeNull();
  expect(screen.getByText("Example")).toBeInTheDocument();
  expect(changed).not.toHaveBeenCalled();
  expect(
    fetcher.mock.calls.filter(([url]) => url.includes("backfill_vectors")),
  ).toHaveLength(1);
});

it.each(["import", "backfill"])(
  "settles %s progress after a credential change without applying its late result",
  async (kind) => {
    const pending = deferredResponse();
    const changed = vi.fn();
    const fetcher = vi.fn((url: string) =>
      url.includes("/import_file") || url.includes("backfill_vectors")
        ? pending.promise
        : Promise.resolve(list()),
    );
    vi.stubGlobal("fetch", fetcher);
    setApiKey("old");
    const view = render(
      <ToastProvider>
        <ConversationsTab onOpenTranscript={() => {}} onMutation={changed} />
      </ToastProvider>,
    );
    await screen.findByText("Example");
    if (kind === "import") {
      fireEvent.click(screen.getByText("Import Chat History"));
      const input = view.container.querySelector("input[type=file]");
      if (!input) throw new Error("Missing file input");
      fireEvent.change(input, {
        target: {
          files: [new File(["{}"], "old.json", { type: "application/json" })],
        },
      });
    } else fireEvent.click(screen.getByText("Vectorize All"));
    setApiKey("new");
    await act(async () =>
      pending.finish(
        new Response(
          JSON.stringify({
            success: true,
            ingested: 1,
            skipped: 0,
            pending_indexing: 1,
            total_processed: 1,
            message: "Stale success",
          }),
        ),
      ),
    );
    expect(changed).not.toHaveBeenCalled();
    expect(screen.queryByText("Stale success")).not.toBeInTheDocument();
    expect(screen.getByText("Vectorize All").closest("button")).toBeEnabled();
    expect(view.container.querySelector(".animate-spin")).toBeNull();
    if (kind === "import") {
      expect(screen.queryByText("Retry old.json")).not.toBeInTheDocument();
      expect(
        screen.getByText(/Credentials changed. Refresh before importing/),
      ).toBeInTheDocument();
    }
  },
);

it("ignores mutation completion after the tab unmounts", async () => {
  const pending = deferredResponse();
  const changed = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      url.includes("/vectorize") ? pending.promise : Promise.resolve(list()),
    ),
  );
  const view = render(
    <ToastProvider>
      <ConversationsTab onOpenTranscript={() => {}} onMutation={changed} />
    </ToastProvider>,
  );
  await screen.findByText("Example");
  fireEvent.click(screen.getByText("Pending Vectorization"));
  view.unmount();
  await act(async () =>
    pending.finish(
      new Response(JSON.stringify({ success: true, id: "1", message: "Done" })),
    ),
  );
  expect(changed).not.toHaveBeenCalled();
});

it("refreshes App statistics, the list and the exact drawer source after vectorization", async () => {
  const { App } = await import("../App");
  setApiKey("admin");
  let vectorized = false;
  const current = () => ({
    id: "1",
    title: "Example",
    platform: "claude",
    summary: "",
    source_agent: "user",
    messages: [],
    created_at: "",
    is_vectorized: vectorized,
  });
  const fetcher = vi.fn((url: string) => {
    if (url.endsWith("/vectorize")) {
      vectorized = true;
      return Promise.resolve(
        new Response(
          JSON.stringify({ success: true, id: "1", message: "Done" }),
        ),
      );
    }
    if (url.endsWith("/stats"))
      return Promise.resolve(
        new Response(
          JSON.stringify({
            total_memories: 0,
            total_storage_files: 0,
            total_profile_rules: 0,
            total_chat_logs: 1,
          }),
        ),
      );
    if (url.endsWith("/conversations/1"))
      return Promise.resolve(
        new Response(JSON.stringify({ conversation: current() })),
      );
    return Promise.resolve(
      new Response(
        JSON.stringify({
          conversations: [current()],
          total: 1,
          total_vectorized: vectorized ? 1 : 0,
          page: 1,
          pages: 1,
        }),
      ),
    );
  });
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  const sidebar = within(await screen.findByRole("complementary"));
  fireEvent.click(sidebar.getByRole("button", { name: /Chat Transcripts/ }));
  await screen.findByText("Example");
  fireEvent.click(screen.getByText("Inspect"));
  fireEvent.click(screen.getByTitle("Generate Vector Embedding"));
  await screen.findByTitle("Vectorized (Click to re-vectorize)");
  await waitFor(() => expect(screen.getByTitle("Close Drawer")).toBeEnabled());
  expect(
    fetcher.mock.calls.filter(([url]) => url.endsWith("/stats")),
  ).toHaveLength(2);
  expect(
    fetcher.mock.calls.filter(([url]) => url.includes("/conversations?"))
      .length,
  ).toBeGreaterThan(1);
  expect(
    fetcher.mock.calls.filter(([url]) => url.endsWith("/conversations/1")),
  ).toHaveLength(1);
});
