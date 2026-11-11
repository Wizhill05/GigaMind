// @vitest-environment jsdom
import React from "react";
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Header } from "../components/Header";
import { ToastProvider } from "../components/ui/Toast";
import { setApiKey } from "../api";

const ok = (name: string) =>
  new Response(
    JSON.stringify({
      success: true,
      file: { key: `files/${name}`, filename: name },
    }),
    { status: 202 },
  );
const fail = () =>
  new Response(
    JSON.stringify({
      detail: {
        message: "Upload outcome unknown",
        key: "files/recover",
        job_id: "job-1",
      },
    }),
    { status: 503 },
  );
const file = (name: string) => new File(["data"], name);
function mount() {
  const refresh = vi.fn();
  const view = render(
    <ToastProvider>
      <Header
        onRefresh={refresh}
        isAuthenticated
        onOpenNewMemoryModal={() => {}}
        onOpenCommandPalette={() => {}}
      />
    </ToastProvider>,
  );
  const input = view.container.querySelector("input[type=file]");
  if (!(input instanceof HTMLInputElement))
    throw new Error("missing upload input");
  return { ...view, input, refresh };
}
beforeEach(() => setApiKey("first"));
afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it("rejects duplicate batches, sequences files and refreshes once for mixed outcomes", async () => {
  let resolve: (response: Response) => void = () => {};
  const pending = new Promise<Response>((r) => {
    resolve = r;
  });
  const fetchMock = vi.fn((url: string) => {
    expect(url).toBe("/api/v1/files/upload?prefix=files");
    return fetchMock.mock.calls.length === 1
      ? pending
      : Promise.resolve(fail());
  });
  vi.stubGlobal("fetch", fetchMock);
  const { input, refresh } = mount();
  fireEvent.change(input, { target: { files: [file("one"), file("two")] } });
  fireEvent.change(input, { target: { files: [file("duplicate")] } });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(input.disabled).toBe(true);
  resolve(ok("one"));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  expect(
    screen.getByText(/Uploaded one & queued vector indexing/),
  ).toBeTruthy();
  expect(
    screen.getByText(/Recovery reference: files\/recover, job job-1/),
  ).toBeTruthy();
});

it("allows reselection after failure, without refreshing for an all-failed batch", async () => {
  const fetchMock = vi.fn((url: string) => {
    expect(url).toBe("/api/v1/files/upload?prefix=files");
    return Promise.resolve(
      fetchMock.mock.calls.length === 1 ? fail() : ok("same"),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  const { input, refresh } = mount();
  const same = file("same");
  fireEvent.change(input, { target: { files: [same] } });
  await screen.findByText(/Recovery reference: files\/recover, job job-1/);
  await waitFor(() => expect(input.disabled).toBe(false));
  expect(refresh).not.toHaveBeenCalled();
  expect(input.value).toBe("");
  fireEvent.change(input, { target: { files: [same] } });
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Recovery reference: files/recover, job job-1",
  );
});

it.each(["credential", "unmount"])(
  "stops after %s changes during an upload",
  async (mode) => {
    let resolve: (response: Response) => void = () => {};
    const fetchMock = vi.fn((url: string) => {
      expect(url).toBe("/api/v1/files/upload?prefix=files");
      return new Promise<Response>((r) => {
        resolve = r;
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const { input, refresh, unmount } = mount();
    fireEvent.change(input, { target: { files: [file("one"), file("two")] } });
    if (mode === "credential") setApiKey("second");
    else unmount();
    await act(async () => {
      resolve(ok("one"));
    });
    if (mode === "credential") await waitFor(() => expect(input).toBeEnabled());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(refresh).not.toHaveBeenCalled();
    expect(screen.queryByText(/Uploaded one/)).toBeNull();
  },
);

it("locks credential and action controls during the batch and snapshots the original selection", async () => {
  let resolve: (response: Response) => void = () => {};
  const pending = new Promise<Response>((done) => {
    resolve = done;
  });
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockReturnValueOnce(pending)
    .mockResolvedValue(ok("two"));
  const { input, refresh } = mount();
  fireEvent.click(screen.getByRole("button", { name: "Connected" }));
  const selected = [file("one"), file("two")];
  fireEvent.change(input, { target: { files: selected } });
  selected[1] = file("replaced");
  expect(screen.getByRole("button", { name: "Connected" })).toBeDisabled();
  expect(screen.getByText("Save & Connect")).toBeDisabled();
  expect(screen.getByText("Disconnect")).toBeDisabled();
  expect(screen.getByRole("button", { name: "New Memory" })).toBeDisabled();
  expect(screen.getByTitle("Refresh telemetry")).toBeDisabled();
  fireEvent.keyDown(screen.getByPlaceholderText("Enter GIGAMIND_API_KEY..."), {
    key: "Enter",
  });
  expect(refresh).not.toHaveBeenCalled();
  await act(async () => {
    resolve(ok("one"));
    await pending;
  });
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  const body = fetcher.mock.calls[1]?.[1]?.body;
  expect(body).toBeInstanceOf(FormData);
  if (!(body instanceof FormData)) throw new Error("Missing multipart body");
  const uploaded = body.get("file");
  expect(uploaded).toBeInstanceOf(File);
  if (!(uploaded instanceof File)) throw new Error("Missing file");
  expect(uploaded.name).toBe("two");
  expect(screen.getByRole("button", { name: "Connected" })).toBeEnabled();
});

it("keeps recovery references after toast expiry until the user dismisses them", async () => {
  vi.useFakeTimers();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(fail());
  const { input, refresh } = mount();
  await act(async () => {
    fireEvent.change(input, { target: { files: [file("unknown")] } });
  });
  expect(input).toBeEnabled();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Recovery reference: files/recover, job job-1",
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Recovery reference: files/recover, job job-1",
  );
  expect(refresh).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Dismiss upload errors"));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("settles an obsolete batch without leaking references and allows a new credential batch", async () => {
  let resolve: (response: Response) => void = () => {};
  const pending = new Promise<Response>((done) => {
    resolve = done;
  });
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockReturnValueOnce(pending)
    .mockResolvedValue(ok("new"));
  const { input, refresh } = mount();
  fireEvent.change(input, {
    target: { files: [file("old"), file("not-sent")] },
  });
  setApiKey("second");
  await act(async () => {
    resolve(fail());
    await pending;
  });
  await waitFor(() => expect(input).toBeEnabled());
  expect(screen.queryByText(/Recovery reference/)).not.toBeInTheDocument();
  expect(refresh).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { files: [file("new")] } });
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(fetcher.mock.calls[1]?.[1]?.headers).toMatchObject({
    Authorization: "Bearer second",
  });
});
