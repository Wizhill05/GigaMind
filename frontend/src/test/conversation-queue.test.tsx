// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ConversationsTab } from "../components/tabs/ConversationsTab";
import { JobsTab } from "../components/tabs/JobsTab";
import { ToastProvider } from "../components/ui/Toast";
import { setApiKey } from "../api";

const conversation = { id: "1", title: "Example", platform: "claude", summary: "", source_agent: "user", messages: [], created_at: "", is_vectorized: false, index_status: "not_indexed", index_job_id: null, index_error: null };
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const list = () => response({ conversations: [conversation], total: 1, total_vectorized: 0, page: 1, pages: 1 });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); localStorage.clear(); });

it("acknowledges a queued job without claiming completion", async () => {
  let queued = false;
  const fetcher = vi.fn((url: string) => {
    if (url.endsWith("/vectorize")) { queued = true; return Promise.resolve(response({ success: true, id: "1", job_id: "job-1", state: "queued", message: "Queued" }, 202)); }
    return Promise.resolve(queued ? response({ conversations: [{ ...conversation, index_status: "queued", index_job_id: "job-1" }], total: 1, total_vectorized: 0, page: 1, pages: 1 }) : list());
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ToastProvider><ConversationsTab onOpenTranscript={() => {}} /></ToastProvider>);
  fireEvent.click(await screen.findByText("Pending Vectorization"));
  expect(await screen.findByText(/Indexing queued. Job job-1/)).toBeInTheDocument();
  expect(await screen.findByText("Indexing queued · Job job-1")).toBeInTheDocument();
  expect(screen.queryByText("Vectorized")).not.toBeInTheDocument();
});

it("retries only the failed bounded batch and keeps its cursor", async () => {
  let calls = 0;
  const bodies: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    if (!url.includes("backfill_vectors")) return Promise.resolve(list());
    bodies.push(JSON.parse(String(init?.body)));
    calls++;
    if (calls === 1) return Promise.resolve(response({ success: true, queued: 20, skipped: 0, next_cursor: "next", message: "Queued" }, 202));
    if (calls === 2) return Promise.resolve(response({ detail: "Unavailable" }, 503));
    return Promise.resolve(response({ success: true, queued: 2, skipped: 1, next_cursor: null, message: "Queued" }, 202));
  }));
  render(<ToastProvider><ConversationsTab onOpenTranscript={() => {}} /></ToastProvider>);
  await screen.findByText("Example");
  fireEvent.click(screen.getByText("Queue indexing batch"));
  fireEvent.click(await screen.findByText("Queue next batch"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Unavailable");
  fireEvent.click(screen.getByText("Queue next batch"));
  await screen.findByText(/Batch queued 2; skipped 1/);
  expect(bodies).toEqual([{ cursor: null, limit: 20 }, { cursor: "next", limit: 20 }, { cursor: "next", limit: 20 }]);
});

it("retries a failed conversation job with its original payload", async () => {
  const job = { id: "old", kind: "index_conversation", payload: { conversation_id: "1" }, state: "failed", result: null, error: "failure", attempts: 1, max_attempts: 3, created_at: "", updated_at: "", available_at: "" };
  let submitted: unknown;
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === "POST") { submitted = JSON.parse(String(init.body)); return Promise.resolve(response({ ...job, id: "new", state: "queued" })); }
    return Promise.resolve(url.includes("/jobs?") ? response({ jobs: [job] }) : response(job));
  }));
  render(<JobsTab refreshVersion={0} />);
  fireEvent.click(await screen.findByText(/index_conversation · failed · old/));
  fireEvent.click(await screen.findByText("Retry indexing"));
  fireEvent.click(screen.getByText("Confirm retry"));
  await waitFor(() => expect(submitted).toMatchObject({ kind: "index_conversation", payload: { conversation_id: "1" }, max_attempts: 3 }));
});

it("ignores a late batch response after credentials change", async () => {
  setApiKey("old");
  let finish: (value: Response) => void = () => {};
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  const fetcher = vi.fn((url: string) => url.includes("backfill_vectors") ? pending : Promise.resolve(list()));
  vi.stubGlobal("fetch", fetcher);
  render(<ToastProvider><ConversationsTab onOpenTranscript={() => {}} /></ToastProvider>);
  await screen.findByText("Example");
  fireEvent.click(screen.getByText("Queue indexing batch"));
  setApiKey("new");
  finish(response({ success: true, queued: 20, skipped: 0, next_cursor: "next", message: "Queued" }, 202));
  await waitFor(() => expect(screen.getByText("Queue indexing batch").closest("button")).toBeEnabled());
  expect(screen.queryByText(/Batch queued/)).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => url.includes("backfill_vectors"))).toHaveLength(1);
});
