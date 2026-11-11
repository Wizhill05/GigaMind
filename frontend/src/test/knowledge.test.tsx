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
  within,
} from "@testing-library/react";
import { KnowledgeTab } from "../components/tabs/KnowledgeTab";

const memory = {
  id: "one",
  content: "Approved fact",
  project_id: null,
  writer_id: "writer",
  revision: 2,
  status: "accepted",
  evidence: [
    { source_type: "file", source_id: "source", quote: "Evidence text" },
  ],
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});
test("filters, pages, displays evidence and recovers from a delete conflict", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/history"))
        return json({
          revisions: [
            {
              revision: 1,
              status: "accepted",
              snapshot: { ...memory, revision: 1 },
            },
          ],
        });
      if (url.endsWith("/delete")) return json({ detail: "stale" }, 409);
      if (init?.method === "POST") return json({ memory });
      return json({ memories: [memory], total: 21 });
    });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<KnowledgeTab refreshVersion={0} />);
  expect(await screen.findByText(/Evidence text/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() =>
    expect(fetcher).toHaveBeenLastCalledWith(
      expect.stringContaining("offset=20"),
      expect.anything(),
    ),
  );
  fireEvent.change(screen.getByLabelText("Project"), {
    target: { value: "a" },
  });
  await waitFor(() =>
    expect(fetcher).toHaveBeenLastCalledWith(
      expect.stringContaining("project_id=a"),
      expect.anything(),
    ),
  );
  fireEvent.click(screen.getByText("History and actions"));
  fireEvent.click(screen.getByText("Delete accepted record"));
  expect(await screen.findByRole("alert")).toHaveTextContent("changed");
  expect(screen.getByText("Delete accepted record")).toBeDisabled();
  fireEvent.click(screen.getByText("Reload"));
  expect(screen.queryByText("Delete accepted record")).not.toBeInTheDocument();
});
test("ignores a late list response and restores using the current revision", async () => {
  let finish: (response: Response) => void = () => {};
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/history"))
        return Promise.resolve(
          json({
            revisions: [
              {
                revision: 1,
                status: "accepted",
                snapshot: { ...memory, revision: 1 },
              },
            ],
          }),
        );
      if (url.endsWith("/restore")) return Promise.resolve(json({ memory }));
      if (url.includes("project_id=a"))
        return Promise.resolve(json({ memories: [memory], total: 1 }));
      return new Promise((resolve) => {
        finish = resolve;
      });
    });
  render(<KnowledgeTab refreshVersion={0} />);
  fireEvent.change(screen.getByLabelText("Project"), {
    target: { value: "a" },
  });
  expect(await screen.findByText("Approved fact")).toBeInTheDocument();
  await act(async () =>
    finish(
      json({ memories: [{ ...memory, content: "Stale fact" }], total: 1 }),
    ),
  );
  expect(screen.queryByText("Stale fact")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("History and actions"));
  fireEvent.click(await screen.findByText("Restore revision 1"));
  await waitFor(() =>
    expect(fetcher).toHaveBeenCalledWith(
      expect.stringContaining("/restore"),
      expect.objectContaining({
        body: JSON.stringify({ revision: 1, expected_revision: 2 }),
      }),
    ),
  );
});

test("locks navigation during a mutation and retains the action after a server error", async () => {
  let finish: (response: Response) => void = () => {};
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/history"))
      return Promise.resolve(json({ revisions: [] }));
    if (url.endsWith("/delete"))
      return new Promise((resolve) => {
        finish = resolve;
      });
    return Promise.resolve(json({ memories: [memory], total: 21 }));
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<KnowledgeTab refreshVersion={0} />);
  fireEvent.click(await screen.findByText("History and actions"));
  fireEvent.click(screen.getByText("Delete accepted record"));
  expect(screen.getByLabelText("Project")).toBeDisabled();
  expect(screen.getByText("Next")).toBeDisabled();
  expect(screen.getByText("History and actions")).toBeDisabled();
  expect(screen.getByText("Close")).toBeDisabled();
  fireEvent.click(screen.getByText("Delete accepted record"));
  expect(
    fetcher.mock.calls.filter(([url]) => String(url).endsWith("/delete")),
  ).toHaveLength(1);
  await act(async () => finish(json({ detail: "Try again later" }, 503)));
  expect(await screen.findByRole("alert")).toHaveTextContent("Try again later");
  expect(screen.getByText("Delete accepted record")).toBeEnabled();
});

test("hides old results while the next scope loads", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    if (String(input).includes("project_id=")) return new Promise(() => {});
    return Promise.resolve(json({ memories: [memory], total: 1 }));
  });
  render(<KnowledgeTab refreshVersion={0} />);
  expect(await screen.findByText("History and actions")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Project"), {
    target: { value: "new" },
  });
  expect(screen.queryByText("History and actions")).not.toBeInTheDocument();
  expect(screen.getByText("Loading knowledge...")).toBeInTheDocument();
});

test("ignores late history and aborts in-flight history on unmount", async () => {
  const other = { ...memory, id: "other", content: "Other fact" };
  let finishOld: (response: Response) => void = () => {};
  let finishOther: (response: Response) => void = () => {};
  const old = new Promise<Response>((resolve) => {
    finishOld = resolve;
  });
  const otherLate = new Promise<Response>((resolve) => {
    finishOther = resolve;
  });
  let blockOther = false;
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/one/history")) return old;
      if (url.endsWith("/other/history"))
        return blockOther
          ? otherLate
          : json({
              revisions: [
                {
                  revision: 1,
                  status: "accepted",
                  snapshot: {
                    ...other,
                    revision: 1,
                    content: "Other first version",
                  },
                },
              ],
            });
      return json({ memories: [memory, other], total: 2 });
    });
  const view = render(<KnowledgeTab refreshVersion={0} />);
  const first = (await screen.findByText("Approved fact")).closest("article");
  const second = screen.getByText("Other fact").closest("article");
  if (!first || !second) throw new Error("Knowledge rows missing");
  fireEvent.click(within(first).getByText("History and actions"));
  fireEvent.click(within(second).getByText("History and actions"));
  await screen.findByText("Other first version");
  expect(
    fetcher.mock.calls.find(([url]) =>
      String(url).endsWith("/one/history"),
    )?.[1]?.signal?.aborted,
  ).toBe(true);
  await act(async () => {
    finishOld(
      json({
        revisions: [
          {
            revision: 1,
            status: "accepted",
            snapshot: { ...memory, content: "Stale old history" },
          },
        ],
      }),
    );
    await old;
  });
  expect(screen.queryByText("Stale old history")).not.toBeInTheDocument();
  blockOther = true;
  view.rerender(<KnowledgeTab refreshVersion={1} />);
  await waitFor(() =>
    expect(
      fetcher.mock.calls.filter(([url]) =>
        String(url).endsWith("/other/history"),
      ),
    ).toHaveLength(2),
  );
  const pendingCalls = fetcher.mock.calls.filter(([url]) =>
    String(url).endsWith("/other/history"),
  );
  const pending = pendingCalls[pendingCalls.length - 1]?.[1]?.signal;
  view.unmount();
  expect(pending?.aborted).toBe(true);
  await act(async () => {
    finishOther(json({ revisions: [] }));
    await otherLate;
  });
});

test("explicit conflict reload uses the new revision", async () => {
  let revision = 2;
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/history")) return json({ revisions: [] });
      if (init?.method === "POST") {
        if (revision === 2) {
          revision = 3;
          return json({ detail: "stale" }, 409);
        }
        revision = 4;
        return json({ memory: { ...memory, revision: 4, status: "deleted" } });
      }
      return json({
        memories: revision === 4 ? [] : [{ ...memory, revision }],
        total: revision === 4 ? 0 : 1,
      });
    });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<KnowledgeTab refreshVersion={0} />);
  fireEvent.click(await screen.findByText("History and actions"));
  fireEvent.click(screen.getByText("Delete accepted record"));
  await screen.findByRole("alert");
  expect(screen.getByText("Delete accepted record")).toBeDisabled();
  expect(screen.getByText("History and actions")).toBeDisabled();
  fireEvent.click(screen.getByText("History and actions"));
  expect(screen.getByText("Delete accepted record")).toBeDisabled();
  fireEvent.click(screen.getByText("Reload"));
  await screen.findByText(/revision 3/);
  fireEvent.click(screen.getByText("Delete accepted record"));
  await screen.findByText("0 records");
  const requests = fetcher.mock.calls.filter(
    ([, init]) => init?.method === "POST",
  );
  expect(requests.map(([, init]) => JSON.parse(String(init?.body)))).toEqual([
    { expected_revision: 2 },
    { expected_revision: 3 },
  ]);
});

test("global refresh during a failed mutation preserves retry state", async () => {
  let finish: (response: Response) => void = () => {};
  const pending = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      if (init?.method === "POST") return pending;
      return String(input).endsWith("/history")
        ? json({ revisions: [] })
        : json({ memories: [memory], total: 1 });
    });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const view = render(<KnowledgeTab refreshVersion={0} />);
  fireEvent.click(await screen.findByText("History and actions"));
  fireEvent.click(screen.getByText("Delete accepted record"));
  const listCalls = fetcher.mock.calls.filter(([url]) =>
    String(url).includes("/knowledge?"),
  ).length;
  view.rerender(<KnowledgeTab refreshVersion={1} />);
  await act(async () => {
    finish(json({ detail: "retry later" }, 503));
    await pending;
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("retry later");
  expect(screen.getByText("Delete accepted record")).toBeEnabled();
  expect(
    fetcher.mock.calls.filter(([url]) => String(url).includes("/knowledge?")),
  ).toHaveLength(listCalls);
});

test("App gates knowledge and header refresh updates the selected revision", async () => {
  const { App } = await import("../App");
  let revision = 2,
    histories = 0;
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/api/v1/review/knowledge?"))
        return json({ memories: [{ ...memory, revision }], total: 1 });
      if (url.endsWith("/history")) {
        histories++;
        return json({
          revisions: [
            {
              revision: 1,
              status: "accepted",
              snapshot: { ...memory, revision: 1, content: "Original fact" },
            },
          ],
        });
      }
      if (init?.method === "POST")
        return json({ memory: { ...memory, revision: 4 } });
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
    screen.queryByRole("button", { name: "Approved Knowledge" }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Master API Key"), {
    target: { value: "master" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Authorize Connection" }));
  const sidebar = within(await screen.findByRole("complementary"));
  fireEvent.click(sidebar.getByRole("button", { name: "Approved Knowledge" }));
  fireEvent.click(await screen.findByText("History and actions"));
  await screen.findByText("Original fact");
  const before = histories;
  revision = 3;
  fireEvent.click(screen.getByTitle("Refresh telemetry"));
  await screen.findByText(/revision 3/);
  await waitFor(() => expect(histories).toBeGreaterThan(before));
  fireEvent.click(await screen.findByText("Restore revision 1"));
  await waitFor(() =>
    expect(fetcher).toHaveBeenCalledWith(
      expect.stringContaining("/restore"),
      expect.objectContaining({
        body: JSON.stringify({ revision: 1, expected_revision: 3 }),
      }),
    ),
  );
});
