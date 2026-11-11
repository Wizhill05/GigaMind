/** @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import React from "react";
import { afterEach, expect, test, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { ClientsTab } from "../components/tabs/ClientsTab";
const client = {
  id: "one",
  name: "Agent",
  scopes: ["memory:read"],
  project_ids: ["p"],
  revoked: false,
  created_at: null,
  expires_at: null,
  last_used_at: null,
  revision: 2,
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});
test("creates a scoped client and keeps the one-time token through a failed refresh", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(json({ clients: [] }))
    .mockResolvedValueOnce(json({ client, token: "secret-token" }))
    .mockResolvedValueOnce(json({ detail: "offline" }, 503));
  render(<ClientsTab refreshVersion={0} />);
  await screen.findByText("No clients on this page.");
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "Agent" },
  });
  fireEvent.change(screen.getByLabelText("Project IDs (comma separated)"), {
    target: { value: "p" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create client" }));
  expect(await screen.findByText("secret-token")).toBeInTheDocument();
  expect(await screen.findByText(/offline/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create client" })).toBeDisabled();
  const body = fetcher.mock.calls[1][1]?.body;
  expect(JSON.parse(String(body))).toMatchObject({
    project_ids: ["p"],
    scopes: ["memory:read", "memory:propose"],
  });
  expect(localStorage.getItem("secret-token")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Dismiss token" }));
  expect(screen.queryByText("secret-token")).not.toBeInTheDocument();
});
test("rotation conflict remains visible and revoke requires confirmation", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(json({ clients: [client] }))
    .mockResolvedValueOnce(json({ detail: "stale revision" }, 409))
    .mockResolvedValueOnce(json({ client: { ...client, revoked: true } }))
    .mockResolvedValueOnce(json({ clients: [] }));
  render(<ClientsTab refreshVersion={0} />);
  fireEvent.click(await screen.findByRole("button", { name: "Rotate Agent" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm rotate" }));
  expect(await screen.findByText(/stale revision/)).toBeInTheDocument();
  expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({
    expected_revision: 2,
  });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "Revoke Agent" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm revoke" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(4));
});
test("paginates and reloads on global refresh", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(
      json({
        clients: Array.from({ length: 20 }, (_, i) => ({
          ...client,
          id: String(i),
          name: `Agent ${i}`,
        })),
      }),
    )
    .mockResolvedValue(json({ clients: [] }));
  const view = render(<ClientsTab refreshVersion={0} />);
  fireEvent.click(await screen.findByRole("button", { name: "Next" }));
  await waitFor(() =>
    expect(fetcher).toHaveBeenLastCalledWith(
      expect.stringContaining("offset=20"),
      expect.anything(),
    ),
  );
  view.rerender(<ClientsTab refreshVersion={1} />);
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
});

test("ignores an older list response after refresh", async () => {
  let resolveOld: (response: Response) => void = () => {};
  const old = new Promise<Response>((resolve) => {
    resolveOld = resolve;
  });
  vi.spyOn(globalThis, "fetch")
    .mockReturnValueOnce(old)
    .mockResolvedValueOnce(json({ clients: [client] }));
  const view = render(<ClientsTab refreshVersion={0} />);
  view.rerender(<ClientsTab refreshVersion={1} />);
  expect(await screen.findByText("Agent")).toBeInTheDocument();
  resolveOld(json({ clients: [] }));
  await waitFor(() =>
    expect(
      screen.queryByText("No clients on this page."),
    ).not.toBeInTheDocument(),
  );
});
