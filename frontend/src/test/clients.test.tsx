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
  sessionStorage.clear();
  vi.restoreAllMocks();
});
test("creates a scoped client and keeps the one-time token through a failed refresh", async () => {
  localStorage.setItem("gigamind_master_key", "master");
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
  expect(localStorage.getItem("gigamind_master_key")).toBe("master");
  expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain("secret-token");
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
  await act(async () => { resolveOld(json({ clients: [] })); await old; });
  await waitFor(() =>
    expect(
      screen.queryByText("No clients on this page."),
    ).not.toBeInTheDocument(),
  );
});

test("rejects duplicate and token-present submissions and offers manual copy", async () => {
  let resolveCreate: (response: Response) => void = () => {};
  const pending = new Promise<Response>((resolve) => { resolveCreate = resolve; });
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json({ clients: [] })).mockReturnValueOnce(pending).mockResolvedValue(json({ clients: [] }));
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
  render(<ClientsTab refreshVersion={0} />);
  await screen.findByText("No clients on this page.");
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Agent" } });
  fireEvent.change(screen.getByLabelText("Project IDs (comma separated)"), { target: { value: "p" } });
  const form = screen.getByRole("button", { name: "Create client" }).closest("form")!;
  fireEvent.submit(form); fireEvent.submit(form);
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(screen.getByLabelText("Name")).toBeDisabled();
  await act(async () => { resolveCreate(json({ client, token: "secret-token" })); await pending; });
  await screen.findByText("secret-token");
  fireEvent.submit(form);
  expect(fetcher).toHaveBeenCalledTimes(3);
  fireEvent.click(screen.getByRole("button", { name: "Copy token" }));
  expect(await screen.findByText(/copy manually/)).toBeInTheDocument();
});

test("reload after conflict clears stale confirmation and permits the new revision", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json({ clients: [client] })).mockResolvedValueOnce(json({ detail: "stale" }, 409)).mockResolvedValueOnce(json({ clients: [{ ...client, revision: 3 }] })).mockResolvedValueOnce(json({ client, token: "new-token" })).mockResolvedValue(json({ clients: [] }));
  render(<ClientsTab refreshVersion={0} />);
  fireEvent.click(await screen.findByRole("button", { name: "Rotate Agent" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm rotate" }));
  await screen.findByText(/stale/);
  fireEvent.click(screen.getByRole("button", { name: "Reload clients" }));
  fireEvent.click(await screen.findByRole("button", { name: "Rotate Agent" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm rotate" }));
  await screen.findByText("new-token");
  expect(JSON.parse(String(fetcher.mock.calls[3][1]?.body))).toEqual({ expected_revision: 3 });
});

test("failed create and revoke preserve draft and confirmation for retry", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json({ clients: [client] })).mockResolvedValueOnce(json({ detail: "create failed" }, 503)).mockResolvedValueOnce(json({ detail: "revoke failed" }, 503)).mockResolvedValueOnce(json({ client: { ...client, revoked: true } })).mockResolvedValue(json({ clients: [] }));
  render(<ClientsTab refreshVersion={0} />);
  await screen.findByText("Agent");
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Draft" } });
  fireEvent.change(screen.getByLabelText("Project IDs (comma separated)"), { target: { value: "p" } });
  fireEvent.click(screen.getByRole("button", { name: "Create client" }));
  await screen.findByText(/create failed/);
  expect(screen.getByLabelText("Name")).toHaveValue("Draft");
  fireEvent.click(screen.getByRole("button", { name: "Revoke Agent" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm revoke" }));
  await screen.findByText(/revoke failed/);
  fireEvent.click(screen.getByRole("button", { name: "Confirm revoke" }));
  await screen.findByText("No clients on this page.");
  expect(screen.getByLabelText("Name")).toHaveValue("Draft");
});

test("App gates clients until authenticated and header refresh reloads them", async () => {
  const { App } = await import("../App");
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => String(url).startsWith("/api/v1/admin/clients") ? json({ clients: [client] }) : json({ total_memories: 0, total_storage_files: 0, total_profile_rules: 0, total_chat_logs: 0 }));
  render(<App />);
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "Clients" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Master API Key"), { target: { value: "master" } });
  fireEvent.click(screen.getByRole("button", { name: "Authorize Connection" }));
  const sidebar = within(await screen.findByRole("complementary"));
  fireEvent.click(sidebar.getByRole("button", { name: "Clients" }));
  await screen.findByText("Agent");
  fireEvent.click(screen.getByTitle("Refresh telemetry"));
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => String(url).startsWith("/api/v1/admin/clients"))).toHaveLength(2));
}, 15000);
