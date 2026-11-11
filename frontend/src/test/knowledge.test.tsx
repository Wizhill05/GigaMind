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
    if (url.endsWith("/history")) return Promise.resolve(json({ revisions: [] }));
    if (url.endsWith("/delete")) return new Promise(resolve => { finish = resolve; });
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
  expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("/delete"))).toHaveLength(1);
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
  fireEvent.change(screen.getByLabelText("Project"), { target: { value: "new" } });
  expect(screen.queryByText("History and actions")).not.toBeInTheDocument();
  expect(screen.getByText("Loading knowledge...")).toBeInTheDocument();
});
