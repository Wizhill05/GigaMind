// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import React from "react";
import {
  render,
  screen,
  waitFor,
  fireEvent,
  cleanup,
  act,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CoordinationTab } from "../components/tabs/CoordinationTab";
import { setApiKey } from "../api";

const issue = (revision = 1) => ({
  id: "issue-1",
  memory_id: "mem-1",
  writer_id: "agent",
  project_id: null,
  status: "open",
  revision,
  reason: "Incorrect",
  created_at: "now",
  updated_at: "now",
});
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});
it("loads scoped pages and resolves using the current revision after a conflict", async () => {
  localStorage.setItem("gigamind_master_key", "test-key");
  let revision = 1;
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method === "POST") {
        if (revision === 1) {
          revision = 2;
          return json({ detail: "Stale issue revision" }, 409);
        }
        return json({ issue: { ...issue(3), status: "resolved" } });
      }
      if (url.includes("/handoffs")) return json({ handoffs: [], total: 21 });
      return json({ issues: [issue(revision)], total: 21 });
    });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(
    <React.StrictMode>
      <CoordinationTab refreshVersion={0} />
    </React.StrictMode>,
  );
  fireEvent.click(await screen.findByText("Select issue issue-1"));
  fireEvent.click(screen.getByText("Resolve"));
  expect(await screen.findByText(/Stale issue revision/)).toBeTruthy();
  expect(screen.getByText("Resolve").hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByText("Select issue issue-1"));
  expect(screen.getByText("Resolve").hasAttribute("disabled")).toBe(true);
  expect(screen.getByText("Reload issue")).toBeTruthy();
  fireEvent.click(screen.getByText("Reload issue"));
  await screen.findByText(/Selected issue: issue-1 · Revision: 2/);
  fireEvent.click(screen.getByText("Dismiss"));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.filter(([, init]) => init?.method === "POST"),
    ).toHaveLength(2),
  );
  const posts = fetcher.mock.calls.filter(
    ([, init]) => init?.method === "POST",
  );
  expect(JSON.parse(String(posts[1][1]?.body))).toEqual({
    status: "dismissed",
    expected_revision: 2,
  });
  await waitFor(() => expect(screen.queryByText(/Selected issue:/)).toBeNull());
  fireEvent.click(screen.getByText("Next"));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([url]) => String(url).includes("offset=20")),
    ).toBe(true),
  );
  fireEvent.change(screen.getByLabelText("Project ID"), {
    target: { value: "project-a" },
  });
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(
        ([url]) =>
          String(url).includes("project_id=project-a") &&
          String(url).includes("offset=0"),
      ),
    ).toBe(true),
  );
});

it("retries a failed load without sending an unauthenticated request", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) => {
      if (String(input).includes("handoffs"))
        return json({ handoffs: [], total: 0 });
      return json({ issues: [issue()], total: 1 });
    });
  render(<CoordinationTab refreshVersion={0} />);
  await screen.findByText("API key is required");
  expect(fetcher).not.toHaveBeenCalled();
  localStorage.setItem("gigamind_master_key", "test-key");
  fireEvent.click(screen.getByText("Retry"));
  expect(await screen.findByText("Select issue issue-1")).toBeTruthy();
});

function deferred() {
  let finish: (response: Response) => void = () => {};
  const promise = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  return { promise, finish };
}
const report = (task_name: string) => ({
  id: "report-1",
  writer_id: "agent",
  project_id: null,
  revision: 1,
  created_at: "now",
  updated_at: "now",
  status: "working",
  record_type: "agent_report",
  task_name,
  summary: "Agent claim",
  verified_outcomes: ["Reported outcome"],
  unresolved: [],
  next_actions: [],
});
function mount() {
  setApiKey("key");
  return render(<CoordinationTab refreshVersion={0} />);
}

it("hides prior scope and ignores late responses that disregard cancellation", async () => {
  const oldH = deferred(),
    oldI = deferred();
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input),
      handoffs = url.includes("/handoffs");
    if (url.includes("project_id=a"))
      return Promise.resolve(
        handoffs
          ? json({
              handoffs: [{ ...report("Current scope"), project_id: "a" }],
              total: 1,
            })
          : json({ issues: [], total: 0 }),
      );
    return handoffs ? oldH.promise : oldI.promise;
  });
  const view = mount();
  fireEvent.change(screen.getByLabelText("Project ID"), {
    target: { value: "a" },
  });
  await screen.findByText("Current scope");
  await act(async () => {
    oldH.finish(json({ handoffs: [report("Old scope")], total: 1 }));
    oldI.finish(json({ issues: [issue()], total: 1 }));
    await Promise.all([oldH.promise, oldI.promise]);
  });
  expect(screen.queryByText("Old scope")).not.toBeInTheDocument();
  expect(screen.queryByText("Select issue issue-1")).not.toBeInTheDocument();
  expect(fetcher.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
  const newest = fetcher.mock.calls[fetcher.mock.calls.length - 1]?.[1]?.signal;
  view.unmount();
  expect(newest?.aborted).toBe(true);
});

it("settles a changed-credential load and retries without exposing the old result", async () => {
  const oldH = deferred(),
    oldI = deferred();
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const handoffs = String(input).includes("/handoffs");
    const headers = new Headers(init?.headers);
    if (headers.get("Authorization") === "Bearer key")
      return handoffs ? oldH.promise : oldI.promise;
    return Promise.resolve(
      handoffs
        ? json({ handoffs: [report("Replacement view")], total: 1 })
        : json({ issues: [], total: 0 }),
    );
  });
  mount();
  setApiKey("replacement");
  await act(async () => {
    oldH.finish(json({ handoffs: [report("Old private report")], total: 1 }));
    oldI.finish(json({ issues: [issue()], total: 1 }));
    await Promise.all([oldH.promise, oldI.promise]);
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("API key changed");
  expect(screen.queryByText("Old private report")).not.toBeInTheDocument();
  expect(screen.queryByText(/Loading coordination/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Retry"));
  await screen.findByText("Replacement view");
});

it("preserves a failed resolution during refresh and refetches before retrying with the current revision", async () => {
  const pending = deferred();
  let revision = 1,
    status = "open",
    posts = 0;
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation((input, init) => {
      if (init?.method === "POST") {
        posts++;
        if (posts === 1) return pending.promise;
        status = "resolved";
        revision++;
        return Promise.resolve(json({ issue: { ...issue(revision), status } }));
      }
      return Promise.resolve(
        String(input).includes("/handoffs")
          ? json({ handoffs: [], total: 0 })
          : json({ issues: [{ ...issue(revision), status }], total: 1 }),
      );
    });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const view = mount();
  fireEvent.click(await screen.findByText("Select issue issue-1"));
  fireEvent.click(screen.getByText("Resolve"));
  fireEvent.click(screen.getByText("Resolve"));
  expect(posts).toBe(1);
  const reads = fetcher.mock.calls.filter(
    ([, init]) => init?.method !== "POST",
  ).length;
  view.rerender(<CoordinationTab refreshVersion={1} />);
  await act(async () => pending.finish(json({ detail: "Unavailable" }, 503)));
  expect(await screen.findByRole("alert")).toHaveTextContent("Unavailable");
  expect(screen.getByText(/Selected issue: issue-1/)).toBeInTheDocument();
  expect(
    fetcher.mock.calls.filter(([, init]) => init?.method !== "POST"),
  ).toHaveLength(reads);
  revision = 2;
  fireEvent.click(screen.getByText("Retry"));
  await screen.findByText(/Selected issue: issue-1 · Revision: 2/);
  fireEvent.click(screen.getByText("Resolve"));
  await waitFor(() =>
    expect(screen.queryByText(/Selected issue:/)).not.toBeInTheDocument(),
  );
  expect(await screen.findByText(/Status: resolved/)).toBeInTheDocument();
  const mutations = fetcher.mock.calls.filter(
    ([, init]) => init?.method === "POST",
  );
  expect(JSON.parse(String(mutations[1]?.[1]?.body))).toEqual({
    status: "resolved",
    expected_revision: 2,
  });
});

it.each(["unmount", "credentials"])(
  "aborts or discards conflict reload after %s",
  async (mode) => {
    const pending = deferred();
    let reads = 0;
    let signal: AbortSignal | null | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      if (init?.method === "POST")
        return Promise.resolve(json({ detail: "Stale" }, 409));
      if (String(input).includes("/handoffs"))
        return Promise.resolve(json({ handoffs: [], total: 0 }));
      reads++;
      if (reads === 2) {
        signal = init?.signal;
        return pending.promise;
      }
      return Promise.resolve(json({ issues: [issue()], total: 1 }));
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const view = mount();
    fireEvent.click(await screen.findByText("Select issue issue-1"));
    fireEvent.click(screen.getByText("Resolve"));
    await screen.findByText("Reload issue");
    fireEvent.click(screen.getByText("Reload issue"));
    await waitFor(() => expect(reads).toBe(2));
    if (mode === "unmount") {
      view.unmount();
      expect(signal?.aborted).toBe(true);
    } else setApiKey("replacement");
    await act(async () => {
      pending.finish(json({ issues: [issue(2)], total: 1 }));
      await pending.promise;
    });
    if (mode === "credentials") {
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "API key changed",
      );
      expect(screen.queryByText(/Selected issue:/)).not.toBeInTheDocument();
      expect(screen.getByText("Retry")).toBeEnabled();
    }
  },
);

it("discards resolution success after credentials change and releases the mutation lock", async () => {
  const pending = deferred();
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) =>
    init?.method === "POST"
      ? pending.promise
      : Promise.resolve(
          String(input).includes("/handoffs")
            ? json({ handoffs: [], total: 0 })
            : json({ issues: [issue()], total: 1 }),
        ),
  );
  vi.spyOn(window, "confirm").mockReturnValue(true);
  mount();
  fireEvent.click(await screen.findByText("Select issue issue-1"));
  fireEvent.click(screen.getByText("Resolve"));
  setApiKey("replacement");
  await act(async () =>
    pending.finish(json({ issue: { ...issue(2), status: "resolved" } })),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("API key changed");
  expect(screen.getByLabelText("Project ID")).toBeEnabled();
  expect(screen.queryByText(/Selected issue:/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Status: resolved/)).not.toBeInTheDocument();
});

it("gates App reads, refreshes the selected revision and locks navigation during resolution", async () => {
  const { App } = await import("../App");
  let revision = 1;
  const pending = deferred();
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation((input, init) => {
      const url = String(input);
      if (init?.method === "POST") return pending.promise;
      if (url.includes("/handoffs"))
        return Promise.resolve(json({ handoffs: [], total: 0 }));
      if (url.includes("/issues"))
        return Promise.resolve(json({ issues: [issue(revision)], total: 1 }));
      return Promise.resolve(
        json({
          total_memories: 0,
          total_storage_files: 0,
          total_profile_rules: 0,
          total_chat_logs: 0,
        }),
      );
    });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<App />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Master API Key"), {
    target: { value: "master" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Authorize Connection" }));
  const sidebar = within(await screen.findByRole("complementary"));
  fireEvent.click(sidebar.getByRole("button", { name: "Coordination" }));
  fireEvent.change(screen.getByLabelText("Project ID"), {
    target: { value: "a" },
  });
  fireEvent.click(await screen.findByText("Select issue issue-1"));
  revision = 2;
  fireEvent.click(screen.getByTitle("Refresh telemetry"));
  await screen.findByText(/Selected issue: issue-1 · Revision: 2/);
  fireEvent.click(screen.getByText("Resolve"));
  expect(sidebar.getByRole("button", { name: /Profile Rules/ })).toBeDisabled();
  fireEvent.click(sidebar.getByRole("button", { name: /Profile Rules/ }));
  expect(
    screen.getByRole("heading", { name: "Coordination" }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Project ID")).toBeDisabled();
  await act(async () => pending.finish(json({ detail: "App failure" }, 503)));
  expect(await screen.findByRole("alert")).toHaveTextContent("App failure");
  expect(sidebar.getByRole("button", { name: /Profile Rules/ })).toBeEnabled();
  const posts = fetcher.mock.calls.filter(
    ([, init]) => init?.method === "POST",
  );
  expect(JSON.parse(String(posts[0]?.[1]?.body))).toEqual({
    status: "resolved",
    expected_revision: 2,
  });
  expect(screen.getByLabelText("Project ID")).toHaveValue("a");
});
