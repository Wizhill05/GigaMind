// @vitest-environment jsdom
import React from "react";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CoordinationTab } from "../components/tabs/CoordinationTab";

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
  render(<React.StrictMode><CoordinationTab refreshVersion={0} /></React.StrictMode>);
  fireEvent.click(await screen.findByText("Select issue issue-1"));
  fireEvent.click(screen.getByText("Resolve"));
  expect(await screen.findByText(/Stale issue revision/)).toBeTruthy();
  expect(screen.getByText("Resolve").hasAttribute("disabled")).toBe(true);
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
