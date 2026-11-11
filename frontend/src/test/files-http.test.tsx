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
import { FilesTab } from "../components/tabs/FilesTab";
import { MemoriesTab } from "../components/tabs/MemoriesTab";
import { ToastProvider } from "../components/ui/Toast";
import { setApiKey } from "../api";

const file = {
  id: "1",
  key: "a/b",
  filename: "example.txt",
  size_bytes: 1,
  extracted_text_length: 0,
  total_chunks: 0,
  indexing_status: "pending",
  created_at: "2026-01-01",
};
const list = () => new Response(JSON.stringify({ files: [file], count: 1 }));
const mount = () =>
  render(
    <ToastProvider>
      <FilesTab />
    </ToastProvider>,
  );
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});

it("shows a list error and retries", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 503 }))
      .mockResolvedValueOnce(list()),
  );
  mount();
  fireEvent.click(await screen.findByText("Retry"));
  expect(await screen.findByText("example.txt")).toBeTruthy();
});

it("preserves a file on delete failure and guards a pending request", async () => {
  let resolve: (response: Response) => void = () => {};
  const pending = new Promise<Response>((r) => {
    resolve = r;
  });
  const fetcher = vi.fn((url: string) =>
    url.includes("/delete") ? pending : Promise.resolve(list()),
  );
  vi.stubGlobal("fetch", fetcher);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  mount();
  await screen.findByText("example.txt");
  const button = screen.getByTitle("Delete File from R2");
  fireEvent.click(button);
  fireEvent.click(button);
  expect(
    fetcher.mock.calls.filter(([url]) => url.includes("/delete")),
  ).toHaveLength(1);
  resolve(new Response("{}", { status: 409 }));
  await screen.findByText(/409/);
  expect(screen.getByText("example.txt")).toBeTruthy();
});

it("reports pending cleanup and queued indexing with job references", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve(
        url.includes("/delete")
          ? new Response(
              JSON.stringify({
                key: "a/b",
                job_id: "del-job",
                state: "queued",
                cleanup: "pending",
              }),
              { status: 202 },
            )
          : url.includes("/reindex")
            ? new Response(
                JSON.stringify({
                  key: "a/b",
                  job_id: "index-job",
                  state: "queued",
                }),
                { status: 202 },
              )
            : list(),
      ),
    ),
  );
  vi.spyOn(window, "confirm").mockReturnValue(true);
  mount();
  await screen.findByText("example.txt");
  fireEvent.click(screen.getByTitle("Re-Index Vectors"));
  await screen.findByText(/Indexing queued.*index-job/);
  await waitFor(() =>
    expect(screen.getByTitle("Re-Index Vectors").hasAttribute("disabled")).toBe(
      false,
    ),
  );
  fireEvent.click(screen.getByTitle("Delete File from R2"));
  expect(await screen.findByText(/Cleanup pending.*del-job/)).toBeTruthy();
});

it("shows and retries file list errors in Memories", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve(
        url.includes("memories?")
          ? new Response(JSON.stringify({ memories: [], pages: 1, total: 0 }))
          : new Response("{}", { status: 503 }),
      ),
    ),
  );
  render(
    <ToastProvider>
      <MemoriesTab
        refreshVersion={0}
        onMutation={() => {}}
        onOpenNewModal={() => {}}
        onOpenEditModal={() => {}}
      />
    </ToastProvider>,
  );
  fireEvent.click(screen.getByText(/Indexed Files/));
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.getByText("Retry")).toBeTruthy();
});

it("ignores chunk responses after unmount", async () => {
  let resolve: (response: Response) => void = () => {};
  const pending = new Promise<Response>((r) => {
    resolve = r;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      url.includes("/chunks?") ? pending : Promise.resolve(list()),
    ),
  );
  const view = mount();
  await screen.findByText("example.txt");
  fireEvent.click(screen.getByTitle("Inspect Semantic Chunks"));
  view.unmount();
  resolve(new Response(JSON.stringify({ key: "a/b", chunks: [], count: 0 })));
  await pending;
  expect(screen.queryByText("example.txt")).toBeNull();
});

function deferred() {
  let finish: (response: Response) => void = () => {};
  const promise = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  return { promise, finish };
}
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
const chunk = (key: string, content: string) => ({
  id: key,
  file_key: key,
  chunk_index: 0,
  total_chunks: 1,
  content,
  created_at: "now",
});

it("ignores the previous file chunks after selecting a different file", async () => {
  const old = deferred();
  const second = { ...file, id: "2", key: "other", filename: "second.txt" };
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.includes("/chunks?"))
      return url.includes("key=other")
        ? Promise.resolve(
            json({
              key: "other",
              chunks: [chunk("other", "Current file chunk")],
              count: 1,
            }),
          )
        : old.promise;
    return Promise.resolve(json({ files: [file, second], count: 2 }));
  });
  mount();
  await screen.findByText("second.txt");
  fireEvent.click(screen.getAllByTitle("Inspect Semantic Chunks")[0]);
  await screen.findByText("Loading semantic chunks...");
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  fireEvent.click(screen.getAllByTitle("Inspect Semantic Chunks")[1]);
  await screen.findByText("Current file chunk");
  await act(async () => {
    old.finish(
      json({ key: "a/b", chunks: [chunk("a/b", "Old file chunk")], count: 1 }),
    );
    await old.promise;
  });
  expect(screen.queryByText("Old file chunk")).not.toBeInTheDocument();
  expect(screen.getByText("Current file chunk")).toBeInTheDocument();
  const calls = fetcher.mock.calls.filter(([url]) =>
    String(url).includes("/chunks?"),
  );
  expect(calls[0]?.[1]?.signal?.aborted).toBe(true);
});

it("keeps the file and releases controls when deletion is unauthorized", async () => {
  const changed = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve(
        url.includes("/delete")
          ? json({ detail: "Credential revoked" }, 401)
          : list(),
      ),
    ),
  );
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(
    <ToastProvider>
      <FilesTab onMutation={changed} />
    </ToastProvider>,
  );
  await screen.findByText("example.txt");
  fireEvent.click(screen.getByTitle("Delete File from R2"));
  await screen.findByText("Credential revoked");
  expect(screen.getByText("example.txt")).toBeInTheDocument();
  expect(screen.getByTitle("Delete File from R2")).toBeEnabled();
  expect(changed).not.toHaveBeenCalled();
});

it.each(["Files", "Memories"])(
  "settles old-credential reads in %s and permits retry",
  async (view) => {
    const pending = deferred();
    let reads = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.includes("memories?"))
          return Promise.resolve(json({ memories: [], pages: 1, total: 0 }));
        reads++;
        return reads === 1 ? pending.promise : Promise.resolve(list());
      }),
    );
    setApiKey("old");
    if (view === "Files") mount();
    else {
      render(
        <ToastProvider>
          <MemoriesTab
            refreshVersion={0}
            onMutation={() => {}}
            onOpenNewModal={() => {}}
            onOpenEditModal={() => {}}
          />
        </ToastProvider>,
      );
      fireEvent.click(screen.getByText(/Indexed Files/));
    }
    await waitFor(() => expect(reads).toBe(1));
    setApiKey("replacement");
    await act(async () => {
      pending.finish(list());
      await pending.promise;
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Credentials changed",
    );
    expect(screen.queryByText("example.txt")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Retry"));
    await screen.findByText("example.txt");
  },
);

it.each(["Files", "Memories"])(
  "clears %s indexing progress after credentials change without applying a stale acknowledgement",
  async (view) => {
    const pending = deferred();
    const changed = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.includes("/reindex")
          ? pending.promise
          : Promise.resolve(
              url.includes("memories?")
                ? json({ memories: [], pages: 1, total: 0 })
                : list(),
            ),
      ),
    );
    setApiKey("old");
    if (view === "Files")
      render(
        <ToastProvider>
          <FilesTab onMutation={changed} />
        </ToastProvider>,
      );
    else {
      render(
        <ToastProvider>
          <MemoriesTab
            refreshVersion={0}
            onMutation={changed}
            onOpenNewModal={() => {}}
            onOpenEditModal={() => {}}
          />
        </ToastProvider>,
      );
      fireEvent.click(screen.getByText(/Indexed Files/));
    }
    await screen.findByText("example.txt");
    const button =
      view === "Files"
        ? screen.getByTitle("Re-Index Vectors")
        : screen.getByTitle("Re-extract text and re-generate embeddings");
    fireEvent.click(button);
    setApiKey("replacement");
    await act(async () => {
      pending.finish(
        json({ key: "a/b", job_id: "stale-job", state: "queued" }, 202),
      );
      await pending.promise;
    });
    expect(button).toBeEnabled();
    expect(changed).not.toHaveBeenCalled();
    expect(screen.queryByText(/stale-job/)).not.toBeInTheDocument();
  },
);

it("gates Files reads, refreshes source data through the header and updates stats on cleanup admission", async () => {
  const { App } = await import("../App");
  let filename = "example.txt",
    deleted = false;
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/delete")) {
      deleted = true;
      return Promise.resolve(
        json(
          {
            key: "a/b",
            job_id: "cleanup-job",
            state: "queued",
            cleanup: "pending",
          },
          202,
        ),
      );
    }
    if (url.includes("/indexed?"))
      return Promise.resolve(
        json({
          files: deleted ? [] : [{ ...file, filename }],
          count: deleted ? 0 : 1,
        }),
      );
    return Promise.resolve(
      json({
        total_memories: 0,
        total_storage_files: deleted ? 0 : 1,
        total_profile_rules: 0,
        total_chat_logs: 0,
      }),
    );
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<App />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Master API Key"), {
    target: { value: "admin" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Authorize Connection" }));
  const sidebar = within(await screen.findByRole("complementary"));
  fireEvent.click(sidebar.getByRole("button", { name: /Files & Storage/ }));
  await screen.findByText("example.txt");
  filename = "updated.txt";
  fireEvent.click(screen.getByTitle("Refresh telemetry"));
  await screen.findByText("updated.txt");
  fireEvent.click(screen.getByTitle("Delete File from R2"));
  await screen.findByText(/Cleanup pending.*cleanup-job/);
  await waitFor(() =>
    expect(
      fetcher.mock.calls.filter(([url]) => String(url).endsWith("/stats")),
    ).toHaveLength(3),
  );
  expect(screen.queryByText("updated.txt")).not.toBeInTheDocument();
});
