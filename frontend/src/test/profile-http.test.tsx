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
import { ProfileRulesTab } from "../components/tabs/ProfileRulesTab";

const rule = {
  id: "a/b",
  key: "editor",
  value: "vim",
  category: "coding",
  source_agent: "user",
  updated_at: "2025-01-01",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});

it("shows a list failure and retries", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(json({ detail: "Unavailable" }, 503))
      .mockResolvedValueOnce(json({ profile: [rule] })),
  );
  render(<ProfileRulesTab refreshVersion={0} onOpenNewRuleModal={() => {}} />);
  expect(await screen.findByText(/Unavailable/)).toBeTruthy();
  fireEvent.click(screen.getByText("Retry"));
  expect(await screen.findByText("editor")).toBeTruthy();
});

it("aborts old filter requests and on unmount", async () => {
  const signals: AbortSignal[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((_url: string, init: RequestInit) => {
      if (init.signal) signals.push(init.signal);
      return new Promise(() => {});
    }),
  );
  const view = render(
    <ProfileRulesTab refreshVersion={0} onOpenNewRuleModal={() => {}} />,
  );
  fireEvent.change(screen.getByDisplayValue("All Categories"), {
    target: { value: "coding" },
  });
  expect(signals[0].aborted).toBe(true);
  view.unmount();
  expect(signals[1].aborted).toBe(true);
});

it("keeps failed deletion visible and retries only once while pending", async () => {
  let resolveDelete: (response: Response) => void = () => {};
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(json({ profile: [rule] }))
    .mockResolvedValueOnce(json({ detail: "Denied" }, 503))
    .mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          resolveDelete = resolve;
        }),
    )
    .mockResolvedValueOnce(json({ profile: [] }));
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const onMutation = vi.fn();
  render(
    <ProfileRulesTab
      refreshVersion={0}
      onOpenNewRuleModal={() => {}}
      onMutation={onMutation}
    />,
  );
  expect(await screen.findByText("editor")).toBeTruthy();
  fireEvent.click(screen.getByText("Delete"));
  expect(await screen.findByText(/Denied/)).toBeTruthy();
  fireEvent.click(screen.getByText("Delete"));
  fireEvent.click(screen.getByText("Delete"));
  expect(
    fetchMock.mock.calls.filter(([url]) => String(url).includes("/profile/")),
  ).toHaveLength(2);
  resolveDelete(json({ success: true, id: "a/b", message: "deleted" }));
  await waitFor(() => expect(onMutation).toHaveBeenCalledOnce());
  await waitFor(() => expect(screen.queryByText("editor")).toBeNull());
  expect(
    fetchMock.mock.calls.some(([url]) =>
      String(url).includes("/profile/a%2Fb"),
    ),
  ).toBe(true);
  expect(
    String(fetchMock.mock.calls[fetchMock.mock.calls.length - 1]?.[0]),
  ).toContain("get_profile");
});

it("rejects an old credential response and retries with the new key", async () => {
  let resolveOld: (response: Response) => void = () => {};
  const fetchMock = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          resolveOld = resolve;
        }),
    )
    .mockResolvedValueOnce(json({ profile: [rule] }));
  vi.stubGlobal("fetch", fetchMock);
  const { setApiKey } = await import("../api");
  setApiKey("old");
  render(<ProfileRulesTab refreshVersion={0} onOpenNewRuleModal={() => {}} />);
  setApiKey("new");
  resolveOld(json({ profile: [rule] }));
  expect(await screen.findByText(/Credentials changed/)).toBeTruthy();
  expect(screen.queryByText("editor")).toBeNull();
  fireEvent.click(screen.getByText("Retry"));
  expect(await screen.findByText("editor")).toBeTruthy();
});

it("ignores a deletion completed after credentials change", async () => {
  let resolveDelete: (response: Response) => void = () => {};
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(json({ profile: [rule] }))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveDelete = resolve;
          }),
      ),
  );
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const { setApiKey } = await import("../api");
  setApiKey("old");
  const onMutation = vi.fn();
  render(
    <ProfileRulesTab
      refreshVersion={0}
      onOpenNewRuleModal={() => {}}
      onMutation={onMutation}
    />,
  );
  fireEvent.click(await screen.findByText("Delete"));
  setApiKey("new");
  resolveDelete(json({ success: true, id: "a/b", message: "deleted" }));
  expect(await screen.findByText(/Credentials changed/)).toBeTruthy();
  await waitFor(() =>
    expect(screen.getByText("Add Rule").closest("button")?.disabled).toBe(
      false,
    ),
  );
  expect(onMutation).not.toHaveBeenCalled();
});

it("ignores a late filter response even when fetch ignores abort", async () => {
  let finish: (response: Response) => void = () => {};
  const old = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  const fetcher = vi.fn((url: string) =>
    url.includes("category=coding")
      ? Promise.resolve(
          json({ profile: [{ ...rule, value: "Current filter" }] }),
        )
      : old,
  );
  vi.stubGlobal("fetch", fetcher);
  render(<ProfileRulesTab refreshVersion={0} onOpenNewRuleModal={() => {}} />);
  fireEvent.change(screen.getByDisplayValue("All Categories"), {
    target: { value: "coding" },
  });
  await screen.findByText("Current filter");
  await act(async () => {
    finish(json({ profile: [{ ...rule, value: "Old filter" }] }));
    await old;
  });
  expect(screen.queryByText("Old filter")).not.toBeInTheDocument();
  expect(screen.getByText("Current filter")).toBeInTheDocument();
});

it("suppresses deletion side effects after unmount", async () => {
  let finish: (response: Response) => void = () => {};
  const pending = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  const changed = vi.fn();
  const fetcher = vi.fn((url: string, init?: RequestInit) =>
    init?.method === "DELETE"
      ? pending
      : Promise.resolve(json({ profile: [rule] })),
  );
  vi.stubGlobal("fetch", fetcher);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const view = render(
    <ProfileRulesTab
      refreshVersion={0}
      onOpenNewRuleModal={() => {}}
      onMutation={changed}
    />,
  );
  fireEvent.click(await screen.findByText("Delete"));
  view.unmount();
  await act(async () => {
    finish(json({ success: true, id: rule.id, message: "Deleted" }));
    await pending;
  });
  expect(changed).not.toHaveBeenCalled();
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("preserves category, source and text filters after successful deletion", async () => {
  let deleted = false;
  const fetcher = vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === "DELETE") {
      deleted = true;
      return Promise.resolve(
        json({ success: true, id: rule.id, message: "Deleted" }),
      );
    }
    return Promise.resolve(json({ profile: deleted ? [] : [rule] }));
  });
  vi.stubGlobal("fetch", fetcher);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<ProfileRulesTab refreshVersion={0} onOpenNewRuleModal={() => {}} />);
  await screen.findByText("editor");
  fireEvent.change(screen.getByDisplayValue("All Categories"), {
    target: { value: "coding" },
  });
  await screen.findByText("editor");
  fireEvent.change(screen.getByDisplayValue("All Source Agents"), {
    target: { value: "user" },
  });
  await screen.findByText("editor");
  fireEvent.change(
    screen.getByPlaceholderText("Search rule keys or values..."),
    { target: { value: "editor" } },
  );
  fireEvent.click(screen.getByText("Delete"));
  await screen.findByText("No profile rules match search criteria");
  expect(screen.getByDisplayValue("coding")).toBeInTheDocument();
  expect(screen.getByDisplayValue("User")).toHaveValue("user");
  expect(screen.getByDisplayValue("editor")).toBeInTheDocument();
  const last = fetcher.mock.calls[fetcher.mock.calls.length - 1]?.[0];
  expect(last).toContain("category=coding");
  expect(last).toContain("source_agent=user");
});

it("gates profile reads and refreshes App statistics and filtered rows after deletion and header refresh", async () => {
  const { App } = await import("../App");
  let deleted = false;
  const fetcher = vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === "DELETE") {
      deleted = true;
      return Promise.resolve(
        json({ success: true, id: rule.id, message: "Deleted" }),
      );
    }
    if (url.includes("/get_profile?"))
      return Promise.resolve(json({ profile: deleted ? [] : [rule] }));
    return Promise.resolve(
      json({
        total_memories: 0,
        total_storage_files: 0,
        total_profile_rules: deleted ? 0 : 1,
        total_chat_logs: 0,
      }),
    );
  });
  vi.stubGlobal("fetch", fetcher);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<App />);
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Master API Key"), {
    target: { value: "master" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Authorize Connection" }));
  const sidebar = within(await screen.findByRole("complementary"));
  fireEvent.click(sidebar.getByRole("button", { name: /Profile Rules/ }));
  await screen.findByText("editor");
  fireEvent.change(screen.getByDisplayValue("All Categories"), {
    target: { value: "coding" },
  });
  await screen.findByText("editor");
  fireEvent.click(screen.getByText("Delete"));
  await screen.findByText("No profile rules match search criteria");
  await waitFor(() =>
    expect(
      fetcher.mock.calls.filter(([url]) => url.endsWith("/stats")),
    ).toHaveLength(2),
  );
  deleted = false;
  fireEvent.click(screen.getByTitle("Refresh telemetry"));
  await screen.findByText("editor");
  expect(screen.getByDisplayValue("coding")).toBeInTheDocument();
  const profileCalls = fetcher.mock.calls.filter(([url]) =>
    url.includes("/get_profile?"),
  );
  expect(profileCalls[profileCalls.length - 1]?.[0]).toContain(
    "category=coding",
  );
});
