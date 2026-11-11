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
import { OverviewTab } from "../components/tabs/OverviewTab";
import { VectorSearchLabTab } from "../components/tabs/VectorSearchLabTab";
import { CommandPalette } from "../components/CommandPalette";
import { searchMemory } from "../api";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
const result = (content: string) => ({
  id: content,
  source: "memory",
  content,
  score: 0.12345,
});
const cases = ["overview", "lab", "palette"] as const;
function renderSearch(kind: (typeof cases)[number]) {
  return render(
    kind === "overview" ? (
      <OverviewTab stats={null} onNavigateTab={vi.fn()} />
    ) : kind === "lab" ? (
      <VectorSearchLabTab />
    ) : (
      <CommandPalette isOpen onClose={vi.fn()} />
    ),
  );
}
function enter(kind: (typeof cases)[number], value: string) {
  const placeholder =
    kind === "overview"
      ? /Query memory database/
      : kind === "lab"
        ? /Enter prompt query/
        : /Type a command/;
  fireEvent.change(screen.getByPlaceholderText(placeholder), {
    target: { value },
  });
  if (kind !== "palette") {
    const form = screen.getByPlaceholderText(placeholder).closest("form");
    if (!form) throw new Error("Search form missing");
    fireEvent.submit(form);
  }
}
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});

test.each(cases)(
  "%s ignores obsolete responses even when fetch ignores abort",
  async (kind) => {
    let finish: (response: Response) => void = () => {};
    const pending = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (_url, init) => {
        const body = JSON.parse(String(init?.body));
        return body.query === "old"
          ? pending
          : json({ results: [result("Current source")] });
      });
    renderSearch(kind);
    enter(kind, "old");
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    enter(kind, "new");
    expect(await screen.findByText("Current source")).toBeInTheDocument();
    expect(fetcher.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    await act(async () => {
      finish(json({ results: [result("Obsolete source")] }));
      await pending;
    });
    expect(screen.queryByText("Obsolete source")).not.toBeInTheDocument();
    expect(screen.getByText(/Raw score: 0.1235/)).toBeInTheDocument();
  },
);

test.each(cases)(
  "%s distinguishes failed requests from empty results and retries",
  async (kind) => {
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json({ detail: "Unavailable" }, 503))
      .mockResolvedValue(json({ results: [] }));
    renderSearch(kind);
    enter(kind, "query");
    expect(await screen.findByRole("alert")).toHaveTextContent("Unavailable");
    expect(
      screen.queryByText("No source matches found"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Retry search"));
    expect(
      await screen.findByText("No source matches found"),
    ).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(2);
  },
);

test.each(cases)(
  "%s clears a late response after credential replacement and can retry",
  async (kind) => {
    localStorage.setItem("gigamind_master_key", "old");
    let finish: (response: Response) => void = () => {};
    const pending = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockReturnValueOnce(pending)
      .mockResolvedValue(json({ results: [] }));
    renderSearch(kind);
    enter(kind, "query");
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    localStorage.setItem("gigamind_master_key", "new");
    await act(async () => {
      finish(json({ results: [result("Old credential source")] }));
      await pending;
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "API key changed",
    );
    expect(screen.queryByText("Old credential source")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Retry search"));
    await screen.findByText("No source matches found");
    expect(fetcher.mock.calls[1]?.[1]?.headers).toMatchObject({
      Authorization: "Bearer new",
    });
  },
);

test.each(["overview", "lab"] as const)(
  "%s submits once and never submits an unconfirmed draft",
  async (kind) => {
    let finish: (response: Response) => void = () => {};
    const pending = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    const fetcher = vi.spyOn(globalThis, "fetch").mockReturnValue(pending);
    const view = renderSearch(kind);
    enter(kind, "query");
    const input = screen.getByRole("textbox");
    const form = input.closest("form");
    if (!form) throw new Error("Search form missing");
    fireEvent.submit(form);
    expect(fetcher).toHaveBeenCalledTimes(1);
    fireEvent.change(input, { target: { value: "private draft" } });
    view.rerender(
      kind === "overview" ? (
        <OverviewTab stats={null} onNavigateTab={vi.fn()} />
      ) : (
        <VectorSearchLabTab />
      ),
    );
    expect(fetcher).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(fetcher.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    await act(async () => {
      finish(json({ results: [result("Late source")] }));
      await pending;
    });
    expect(screen.queryByText("Late source")).not.toBeInTheDocument();
  },
);

test("closed palette never searches and discards a response after close", async () => {
  let finish: (response: Response) => void = () => {};
  const pending = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  const fetcher = vi.spyOn(globalThis, "fetch").mockReturnValue(pending);
  const view = render(<CommandPalette isOpen={false} onClose={vi.fn()} />);
  expect(fetcher).not.toHaveBeenCalled();
  view.rerender(<CommandPalette isOpen onClose={vi.fn()} />);
  enter("palette", "query");
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  view.rerender(<CommandPalette isOpen={false} onClose={vi.fn()} />);
  expect(fetcher.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
  await act(async () => {
    finish(json({ results: [result("Closed source")] }));
    await pending;
  });
  view.rerender(<CommandPalette isOpen onClose={vi.fn()} />);
  expect(screen.queryByText("Closed source")).not.toBeInTheDocument();
  view.unmount();
});

test("search response validation preserves file provenance and reports invalid payloads", async () => {
  const file = {
    ...result("Literal evidence"),
    source: "file",
    filename: "source.pdf",
    file_key: "files/source.pdf",
    page_number: null,
    chunk_index: null,
    vector_score: 0.3,
    rerank_score: 0.2,
    citation: "source.pdf (Page 3)",
    matching_pages: [3],
    parent_id: null,
    extra_evidence: { source_role: "assistant" },
    attachments: [
      {
        key: "attachment",
        filename: "diagram.png",
        url: "https://example.test/file",
      },
    ],
  };
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(json({ results: [file] }))
    .mockResolvedValueOnce(json({ results: [{ ...file, score: "high" }] }));
  expect(await searchMemory("query")).toEqual([file]);
  await expect(searchMemory("query")).rejects.toThrow();
});

test("Overview shows the actual MCP endpoint and reports rejected clipboard access", async () => {
  const writeText = vi.fn().mockRejectedValue(new Error("Denied"));
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  renderSearch("overview");
  expect(screen.getByText(window.location.origin + "/mcp")).toBeInTheDocument();
  fireEvent.click(screen.getByTitle("Copy MCP Endpoint"));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Could not copy endpoint",
  );
  expect(writeText).toHaveBeenCalledWith(window.location.origin + "/mcp");
});

test("image reads cannot restore replaced, old-credential or unmounted selections", async () => {
  class Reader {
    static instances: Reader[] = [];
    result: string | null = null;
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    aborted = false;
    constructor() {
      Reader.instances.push(this);
    }
    abort() {
      this.aborted = true;
    }
    readAsDataURL() {}
    finish(bytes: string) {
      this.result = "data:image/png;base64," + bytes;
      this.onload?.();
    }
  }
  vi.stubGlobal("FileReader", Reader);
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(json({ results: [] }));
  const view = renderSearch("lab");
  const input = screen
    .getByTitle("Search with Image Screenshot / Diagram")
    .querySelector("input");
  if (!input) throw new Error("Image input missing");
  const choose = (name: string) =>
    fireEvent.change(input, {
      target: { files: [new File(["bytes"], name, { type: "image/png" })] },
    });
  choose("old.png");
  choose("current.png");
  const old = Reader.instances[0],
    current = Reader.instances[1];
  if (!old || !current) throw new Error("Readers missing");
  expect(old.aborted).toBe(true);
  act(() => old.finish("old-bytes"));
  expect(screen.queryByText("old.png")).not.toBeInTheDocument();
  act(() => current.finish("current-bytes"));
  fireEvent.click(screen.getByText("Run source search"));
  await screen.findByText("No source matches found");
  expect(
    JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body)).image_base64,
  ).toBe("current-bytes");
  localStorage.setItem("gigamind_master_key", "replacement");
  fireEvent.click(screen.getByText("Run source search"));
  expect(screen.getByRole("alert")).toHaveTextContent("API key changed");
  expect(fetcher).toHaveBeenCalledTimes(1);
  choose("changed-key.png");
  localStorage.setItem("gigamind_master_key", "another-replacement");
  const changed = Reader.instances[2];
  if (!changed) throw new Error("Reader missing");
  act(() => changed.finish("private-bytes"));
  expect(screen.getByRole("alert")).toHaveTextContent("API key changed");
  expect(screen.queryByText("changed-key.png")).not.toBeInTheDocument();
  choose("unmounted.png");
  const last = Reader.instances[3];
  if (!last) throw new Error("Reader missing");
  view.unmount();
  expect(last.aborted).toBe(true);
  act(() => last.finish("late-bytes"));
  expect(fetcher).toHaveBeenCalledTimes(1);
});

test.each(cases)("%s aborts its pending request on unmount", async (kind) => {
  let finish: (response: Response) => void = () => {};
  const pending = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  const fetcher = vi.spyOn(globalThis, "fetch").mockReturnValue(pending);
  const view = renderSearch(kind);
  enter(kind, "query");
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  view.unmount();
  expect(fetcher.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
  await act(async () => {
    finish(json({ results: [result("Unmounted source")] }));
    await pending;
  });
  expect(screen.queryByText("Unmounted source")).not.toBeInTheDocument();
});

test.each(["network", "unauthorized"])(
  "Overview reports a %s error and permits retry",
  async (failure) => {
    const fetcher = vi.spyOn(globalThis, "fetch");
    if (failure === "network")
      fetcher.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    else
      fetcher.mockResolvedValueOnce(
        json({ detail: "Invalid credential" }, 401),
      );
    fetcher.mockResolvedValue(json({ results: [] }));
    renderSearch("overview");
    enter("overview", "query");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      failure === "network" ? "Network error" : "Invalid credential",
    );
    fireEvent.click(screen.getByText("Retry search"));
    await screen.findByText("No source matches found");
    expect(fetcher).toHaveBeenCalledTimes(2);
  },
);

test("Lab displays source citations and preserves raw metadata without confidence claims", async () => {
  const source = {
    ...result("Literal source quotation"),
    source: "file",
    filename: "notes.pdf",
    citation: "notes.pdf (Page 4)",
    page_number: 4,
    retrieval_method: "lexical",
    attachments: [{ key: "diagram", filename: "diagram.png" }],
  };
  vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ results: [source] }));
  renderSearch("lab");
  enter("lab", "query");
  await screen.findByText("Literal source quotation");
  expect(screen.getByText("notes.pdf (Page 4)")).toBeInTheDocument();
  expect(screen.getByText("diagram.png")).toBeInTheDocument();
  expect(screen.getByText("Retrieval: lexical")).toBeInTheDocument();
  expect(screen.queryByText(/% match/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Show Raw JSON"));
  expect(screen.getByText(/"page_number": 4/)).toHaveTextContent(
    '"citation": "notes.pdf (Page 4)"',
  );
});
