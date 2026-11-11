/** @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import React from "react";
import { afterEach, expect, test, vi } from "vitest";
import {
  cleanup,
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { JobsTab } from "../components/tabs/JobsTab";

const job = {
  id: "one",
  kind: "index_file",
  payload: { key: "file" },
  state: "queued",
  result: null,
  error: null,
  attempts: 0,
  max_attempts: 3,
  created_at: "today",
  updated_at: "today",
  available_at: "today",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  localStorage.clear();
  sessionStorage.clear();
});
test("cancel conflict refreshes and keeps the error visible", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      if (init?.method === "POST")
        return json({ detail: "Already completed" }, 409);
      return String(input).includes("?") ? json({ jobs: [job] }) : json(job);
    });
  render(<JobsTab refreshVersion={0} />);
  fireEvent.click(
    await screen.findByRole("button", { name: /index_file · queued/ }),
  );
  fireEvent.click(await screen.findByRole("button", { name: "Cancel job" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm cancel" }));
  expect(await screen.findByText("Already completed")).toBeInTheDocument();
  await waitFor(() =>
    expect(
      fetcher.mock.calls.filter(([url]) => String(url).includes("?")).length,
    ).toBeGreaterThan(2),
  );
});
test("global refresh reloads the list", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(json({ jobs: [] }));
  const view = render(<JobsTab refreshVersion={0} />);
  await screen.findByText("No jobs on this page.");
  view.rerender(<JobsTab refreshVersion={1} />);
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
});
test("failed index retry creates a new job with a fresh idempotency key", async () => {
  const failed = { ...job, state: "failed", error: "Index failed" };
  const created = { ...job, id: "two" };
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      if (init?.method === "POST") return json(created);
      if (String(input).includes("?")) return json({ jobs: [failed] });
      return json(String(input).endsWith("/two") ? created : failed);
    });
  render(<JobsTab refreshVersion={0} />);
  fireEvent.click(
    await screen.findByRole("button", { name: /index_file · failed/ }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Retry indexing" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Confirm retry" }));
  expect(await screen.findByText("Job two")).toBeInTheDocument();
  const post = fetcher.mock.calls.find(([, init]) => init?.method === "POST");
  expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({
    kind: "index_file",
    payload: { key: "file" },
    idempotency_key: expect.any(String),
  });
});
test("failed retry preserves the server error", async () => {
  const failed = { ...job, state: "failed", error: "Index failed" };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (init?.method === "POST")
      return json({ detail: "Resource forgotten" }, 409);
    return String(input).includes("?")
      ? json({ jobs: [failed] })
      : json(failed);
  });
  render(<JobsTab refreshVersion={0} />);
  fireEvent.click(
    await screen.findByRole("button", { name: /index_file · failed/ }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Retry indexing" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Confirm retry" }));
  expect(await screen.findByText("Resource forgotten")).toBeInTheDocument();
});
test("pages and ignores a stale response after refresh", async () => {
  let resolveOld: (response: Response) => void = () => {};
  const old = new Promise<Response>((resolve) => {
    resolveOld = resolve;
  });
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockReturnValueOnce(old)
    .mockResolvedValueOnce(
      json({
        jobs: Array.from({ length: 20 }, (_, i) => ({
          ...job,
          id: String(i),
          state: "completed",
        })),
      }),
    )
    .mockResolvedValue(json({ jobs: [] }));
  const view = render(<JobsTab refreshVersion={0} />);
  view.rerender(<JobsTab refreshVersion={1} />);
  await screen.findByRole("button", { name: /index_file · completed · 0/ });
  await act(async () => {
    resolveOld(json({ jobs: [job] }));
    await old;
  });
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByText("No jobs on this page.");
  expect(
    fetcher.mock.calls.some(([url]) => String(url).includes("offset=20")),
  ).toBe(true);
  expect(
    screen.queryByRole("button", { name: /index_file · queued/ }),
  ).not.toBeInTheDocument();
});

test("retry works without randomUUID and locks navigation until completion", async () => {
  const failed = { ...job, state: "failed" };
  let finish: (response: Response) => void = () => {};
  const post = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  vi.stubGlobal("crypto", {
    getRandomValues: crypto.getRandomValues.bind(crypto),
  });
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      if (init?.method === "POST") return post;
      return String(input).includes("?")
        ? json({ jobs: [failed, { ...failed, id: "other" }] })
        : json(String(input).endsWith("/two") ? { ...job, id: "two" } : failed);
    });
  render(<JobsTab refreshVersion={0} />);
  fireEvent.click(await screen.findByRole("button", { name: /failed · one/ }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Retry indexing" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Confirm retry" }));
  expect(screen.getByRole("button", { name: /failed · other/ })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
  const call = fetcher.mock.calls.find(([, init]) => init?.method === "POST");
  expect(JSON.parse(String(call?.[1]?.body)).idempotency_key).toMatch(
    /^[0-9a-f]{32}$/,
  );
  await act(async () => {
    finish(json({ ...job, id: "two" }));
    await post;
  });
  expect(await screen.findByText("Job two")).toBeInTheDocument();
});

test("polls pending jobs until completed and stops on unmount", async () => {
  vi.useFakeTimers();
  let state = "queued";
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async () => json({ jobs: [{ ...job, state }] }));
  const view = render(<JobsTab refreshVersion={0} />);
  await act(async () => {});
  expect(fetcher).toHaveBeenCalledTimes(1);
  state = "running";
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(fetcher).toHaveBeenCalledTimes(2);
  state = "completed";
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(fetcher).toHaveBeenCalledTimes(3);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(fetcher).toHaveBeenCalledTimes(3);
  view.unmount();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(fetcher).toHaveBeenCalledTimes(3);
});

test("cleanup retry uses file deletion and selects its returned job", async () => {
  const failed = { ...job, kind: "delete_file", state: "failed" };
  const created = { ...job, id: "cleanup", kind: "delete_file" };
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      if (init?.method === "POST")
        return json({
          key: "file",
          job_id: "cleanup",
          state: "queued",
          cleanup: "pending",
        });
      return String(input).includes("?")
        ? json({ jobs: [failed] })
        : json(String(input).endsWith("/cleanup") ? created : failed);
    });
  render(<JobsTab refreshVersion={0} />);
  fireEvent.click(
    await screen.findByRole("button", { name: /delete_file · failed/ }),
  );
  fireEvent.click(await screen.findByRole("button", { name: "Retry cleanup" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm retry" }));
  expect(await screen.findByText("Job cleanup")).toBeInTheDocument();
  expect(
    fetcher.mock.calls.some(
      ([url, init]) =>
        String(url).endsWith("/files/delete") && init?.method === "POST",
    ),
  ).toBe(true);
});

test("pauses polling while hidden and aborts an in-flight load on unmount", async () => {
  vi.useFakeTimers();
  const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(json({ jobs: [job] }));
  const view = render(<JobsTab refreshVersion={0} />);
  await act(async () => {});
  expect(fetcher).toHaveBeenCalledTimes(1);
  await act(async () => {
    hidden.mockReturnValue(true);
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(15000);
  });
  expect(fetcher).toHaveBeenCalledTimes(1);
  let finish: (response: Response) => void = () => {};
  const late = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  fetcher.mockReturnValueOnce(late);
  await act(async () => {
    hidden.mockReturnValue(false);
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(fetcher).toHaveBeenCalledTimes(2);
  const signal = fetcher.mock.calls[1]?.[1]?.signal;
  view.unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => {
    finish(json({ jobs: [job] }));
    await late;
    await vi.advanceTimersByTimeAsync(15000);
  });
  expect(fetcher).toHaveBeenCalledTimes(2);
});

test("ignores late selected-job details and hides failed-load actions", async () => {
  let finish: (response: Response) => void = () => {};
  const late = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  let failDetail = false;
  const other = { ...job, id: "other", state: "completed" };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("?")) return json({ jobs: [job, other] });
    if (url.endsWith("/one")) return late;
    return failDetail ? json({ detail: "detail offline" }, 503) : json(other);
  });
  render(<JobsTab refreshVersion={0} />);
  fireEvent.click(await screen.findByRole("button", { name: /queued · one/ }));
  fireEvent.click(screen.getByRole("button", { name: /completed · other/ }));
  await screen.findByText("Job other");
  await act(async () => {
    finish(json(job));
    await late;
  });
  expect(screen.queryByText("Job one")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Cancel job" }),
  ).not.toBeInTheDocument();
  failDetail = true;
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await screen.findByText("detail offline");
  expect(screen.queryByText("Job other")).not.toBeInTheDocument();
});

test("App gates Jobs and header refresh reloads selected detail", async () => {
  const { App } = await import("../App");
  let details = 0;
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) => {
      const url = String(input);
      if (url.startsWith("/api/v1/jobs?"))
        return json({ jobs: [{ ...job, state: "completed" }] });
      if (url === "/api/v1/jobs/one") {
        details++;
        return json({ ...job, state: "completed" });
      }
      return json({
        total_memories: 0,
        total_storage_files: 0,
        total_profile_rules: 0,
        total_chat_logs: 0,
      });
    });
  render(<App />);
  expect(fetcher).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: "Jobs" }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Master API Key"), {
    target: { value: "master" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Authorize Connection" }));
  const sidebar = within(await screen.findByRole("complementary"));
  fireEvent.click(sidebar.getByRole("button", { name: "Jobs" }));
  fireEvent.click(
    await screen.findByRole("button", { name: /completed · one/ }),
  );
  await screen.findByText("Job one");
  const before = details;
  fireEvent.click(screen.getByTitle("Refresh telemetry"));
  await waitFor(() => expect(details).toBeGreaterThan(before));
  expect(screen.getByText("Job one")).toBeInTheDocument();
});
