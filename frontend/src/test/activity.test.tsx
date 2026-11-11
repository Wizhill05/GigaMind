/** @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import React from "react";
import { afterEach, expect, test, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { ActivityTab } from "../components/tabs/ActivityTab";

const event = (id: string) => ({
  id,
  project_id: "a",
  writer_id: "writer",
  action: "proposed",
  target_id: id,
  revision: 1,
  status: "recorded",
  created_at: "2026-01-01",
  updated_at: "2026-01-01",
});
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});
test("shows newest first, pages, filters and retains filter on refresh", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async () =>
      json({ events: [event("new"), event("old")], total: 21 }),
    );
  const view = render(<ActivityTab refreshVersion={0} />);
  expect(await screen.findByText("new")).toBeInTheDocument();
  expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("new");
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() =>
    expect(fetcher).toHaveBeenLastCalledWith(
      expect.stringContaining("offset=20"),
      expect.anything(),
    ),
  );
  fireEvent.change(screen.getByLabelText("Project ID"), {
    target: { value: "a" },
  });
  await waitFor(() =>
    expect(fetcher).toHaveBeenLastCalledWith(
      expect.stringContaining("offset=0&project_id=a"),
      expect.anything(),
    ),
  );
  const beforeRefresh = fetcher.mock.calls.length;
  view.rerender(<ActivityTab refreshVersion={1} />);
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(beforeRefresh + 1));
  await waitFor(() =>
    expect(fetcher).toHaveBeenLastCalledWith(
      expect.stringContaining("project_id=a"),
      expect.anything(),
    ),
  );
});
test("shows 401 and retries to empty", async () => {
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(json({ detail: "Unauthorized" }, 401))
    .mockResolvedValueOnce(json({ events: [], total: 0 }));
  render(<ActivityTab refreshVersion={0} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Unauthorized");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("No activity found.")).toBeInTheDocument();
});
test("ignores a late response after filter changes", async () => {
  let finish: (response: Response) => void = () => {};
  vi.spyOn(globalThis, "fetch")
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    )
    .mockResolvedValue(json({ events: [event("current")], total: 1 }));
  render(<ActivityTab refreshVersion={0} />);
  fireEvent.change(screen.getByLabelText("Project ID"), {
    target: { value: "a" },
  });
  expect(await screen.findByText("current")).toBeInTheDocument();
  await act(async () => finish(json({ events: [event("stale")], total: 1 })));
  await waitFor(() =>
    expect(screen.queryByText("stale")).not.toBeInTheDocument(),
  );
});

test("app header refresh preserves the activity project filter", async () => {
  const { App } = await import("../App");
  const { within } = await import("@testing-library/react");
  let activityCalls = 0;
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) => {
      if (String(input).startsWith("/api/v1/review/activity")) {
        activityCalls++;
        return json({ events: [event("timeline-event")], total: 1 });
      }
      return json({
        total_memories: 0,
        total_storage_files: 0,
        total_profile_rules: 0,
        total_chat_logs: 0,
      });
    });
  localStorage.setItem("gigamind_master_key", "test-key");
  render(<App />);
  const sidebar = within(await screen.findByRole("complementary"));
  fireEvent.click(sidebar.getByRole("button", { name: "Activity" }));
  await screen.findByText("timeline-event");
  fireEvent.change(screen.getByLabelText("Project ID"), {
    target: { value: "demo-orchard" },
  });
  await waitFor(() =>
    expect(fetcher).toHaveBeenLastCalledWith(
      expect.stringContaining("project_id=demo-orchard"),
      expect.anything(),
    ),
  );
  const beforeRefresh = activityCalls;
  fireEvent.click(screen.getByTitle("Refresh telemetry"));
  await waitFor(() => expect(activityCalls).toBeGreaterThan(beforeRefresh));
  expect(screen.getByLabelText("Project ID")).toHaveValue("demo-orchard");
  const activityRequests = fetcher.mock.calls.filter(([url]) =>
    String(url).startsWith("/api/v1/review/activity"),
  );
  expect(String(activityRequests[activityRequests.length - 1]?.[0])).toContain(
    "project_id=demo-orchard",
  );
});
