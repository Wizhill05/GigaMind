// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
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
  await waitFor(() => expect(screen.getByText("Add Rule").closest("button")?.disabled).toBe(false));
  expect(onMutation).not.toHaveBeenCalled();
});
