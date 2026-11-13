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
import { ReviewTab } from "../components/tabs/ReviewTab";

const proposal = {
  id: "p1",
  content: "Original",
  revision: 2,
  status: "proposed",
  writer_id: "agent",
  project_id: "project",
  evidence: [
    { source_type: "chat", source_id: "source", quote: "Exact quote" },
  ],
  conflicts: ["m1"],
};
const memory = {
  id: "m1",
  content: "Old fact",
  revision: 3,
  status: "accepted",
  writer_id: "admin",
  project_id: "project",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const preview = (
  init: RequestInit | undefined,
  conflicts: (typeof memory)[],
) => {
  const body = JSON.parse(String(init?.body));
  return json({
    proposal_id: "p1",
    revision: body.expected_revision,
    content: body.content,
    conflicts,
  });
};
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});
test("shows evidence and requires explicit conflict consent before approving edited text", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      if (String(input).includes("/preview")) return preview(init, [memory]);
      if (String(input).includes("/resolve"))
        return json({ proposal: { ...proposal, status: "accepted" }, memory });
      if (String(input).includes("/memories/")) return json({ memory });
      return json({ proposals: [proposal], total: 1 });
    });
  const mutated = vi.fn();
  render(<ReviewTab refreshVersion={0} onMutation={mutated} />);
  fireEvent.click(await screen.findByRole("button", { name: /Original/ }));
  expect(screen.getByText("Exact quote")).toBeTruthy();
  expect(await screen.findByText(/Old fact/)).toBeTruthy();
  const approve = screen.getByRole("button", { name: "Approve" });
  expect(approve).toHaveProperty("disabled", true);
  fireEvent.change(screen.getByLabelText("Approval text"), {
    target: { value: "Edited fact" },
  });
  fireEvent.click(await screen.findByRole("checkbox"));
  fireEvent.click(approve);
  await waitFor(() => expect(mutated).toHaveBeenCalled());
  const call = fetcher.mock.calls.find(([url]) =>
    String(url).includes("/resolve"),
  );
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({
    action: "approve",
    expected_revision: 2,
    content: "Edited fact",
    supersedes: ["m1"],
  });
});
test("stale approval keeps edited text until explicit reload", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) =>
    String(input).includes("/preview")
      ? preview(init, [])
      : String(input).includes("/resolve")
        ? json({ detail: "Stale proposal revision" }, 409)
        : String(input).includes("/memories/")
          ? json({ memory })
          : json({ proposals: [{ ...proposal, conflicts: [] }], total: 1 }),
  );
  render(<ReviewTab refreshVersion={0} onMutation={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: /Original/ }));
  fireEvent.change(screen.getByLabelText("Approval text"), {
    target: { value: "Keep this" },
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Stale proposal revision",
  );
  expect(screen.getByLabelText("Approval text")).toHaveValue("Keep this");
  fireEvent.click(
    screen.getByRole("button", { name: /Reload current proposal/ }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: /Reload current proposal/ }),
    ).toBeNull(),
  );
  expect(screen.getByLabelText("Approval text")).toHaveValue("Keep this");
});
test("retries failed list and shows empty state", async () => {
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(json({ detail: "Unavailable" }, 503))
    .mockResolvedValueOnce(json({ proposals: [], total: 0 }));
  render(<ReviewTab refreshVersion={0} onMutation={() => {}} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Unavailable");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("No proposals on this page.")).toBeTruthy();
});
test("rejects using the displayed revision", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) =>
      String(input).includes("/resolve")
        ? json({ proposal: { ...proposal, status: "rejected" } })
        : json({ proposals: [{ ...proposal, conflicts: [] }], total: 1 }),
    );
  render(<ReviewTab refreshVersion={0} onMutation={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: /Original/ }));
  fireEvent.click(screen.getByRole("button", { name: "Reject" }));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([url]) => String(url).includes("/resolve")),
    ).toBe(true),
  );
  const call = fetcher.mock.calls.find(([url]) =>
    String(url).includes("/resolve"),
  );
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({
    action: "reject",
    expected_revision: 2,
    supersedes: [],
  });
});
test("restores a revision with the current memory revision and reports stale errors", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/restore"))
        return json({ detail: "Stale memory revision" }, 409);
      if (url.endsWith("/history"))
        return json({
          revisions: [
            {
              revision: 1,
              status: "accepted",
              writer_id: "admin",
              created_at: "today",
              snapshot: { ...memory, revision: 1, content: "Earlier" },
            },
          ],
        });
      if (url.includes("/memories/")) return json({ memory });
      return json({
        proposals: [
          { ...proposal, status: "accepted", accepted_memory_id: "m1" },
        ],
        total: 1,
      });
    });
  render(<ReviewTab refreshVersion={0} onMutation={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: /Original/ }));
  fireEvent.click(
    screen.getByRole("button", { name: "Open revision history" }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Restore revision 1" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Stale memory revision",
  );
  const call = fetcher.mock.calls.find(([url]) =>
    String(url).endsWith("/restore"),
  );
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({
    revision: 1,
    expected_revision: 3,
  });
});

test("preview tracks edited conflicts in both directions and ignores late responses", async () => {
  let release: ((response: Response) => void) | undefined;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (String(input).includes("/preview")) {
      const body = JSON.parse(String(init?.body));
      if (body.content === "slow")
        return new Promise<Response>((resolve) => {
          release = resolve;
        });
      return preview(
        init,
        body.content === "Original" || body.content === "add" ? [memory] : [],
      );
    }
    return json({ proposals: [proposal], total: 1 });
  });
  render(<ReviewTab refreshVersion={0} onMutation={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: /Original/ }));
  fireEvent.click(await screen.findByRole("checkbox"));
  const text = screen.getByLabelText("Approval text");
  fireEvent.change(text, { target: { value: "slow" } });
  await waitFor(() => expect(release).toBeTypeOf("function"));
  fireEvent.change(text, { target: { value: "remove" } });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled(),
  );
  expect(screen.queryByRole("checkbox")).toBeNull();
  release?.(
    json({
      proposal_id: "p1",
      revision: 2,
      content: "slow",
      conflicts: [memory],
    }),
  );
  fireEvent.change(text, { target: { value: "add" } });
  const box = await screen.findByRole("checkbox");
  expect(box).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
});

test("failed approval keeps draft and can be retried while pending mutation locks navigation", async () => {
  let finish: ((response: Response) => void) | undefined;
  let attempts = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (String(input).includes("/preview")) return preview(init, []);
    if (String(input).includes("/resolve")) {
      attempts++;
      if (attempts === 1) return json({ detail: "Unavailable" }, 503);
      return new Promise<Response>((resolve) => {
        finish = resolve;
      });
    }
    return json({
      proposals: [proposal, { ...proposal, id: "p2", content: "Another" }],
      total: 21,
    });
  });
  render(<ReviewTab refreshVersion={0} onMutation={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: /Original/ }));
  fireEvent.change(screen.getByLabelText("Approval text"), {
    target: { value: "Draft" },
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Unavailable");
  expect(screen.getByLabelText("Approval text")).toHaveValue("Draft");
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  expect(screen.getByRole("button", { name: /Another/ })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  expect(screen.getByLabelText("Approval text")).toBeDisabled();
  finish?.(json({ proposal: { ...proposal, status: "accepted" }, memory }));
  await waitFor(() =>
    expect(screen.queryByLabelText("Approval text")).toBeNull(),
  );
});

test("successful restore reloads current revision", async () => {
  let currentRevision = 3;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/restore")) {
      currentRevision = 4;
      return json({ memory: { ...memory, revision: 4 } });
    }
    if (url.endsWith("/history"))
      return json({
        revisions: [
          {
            revision: 1,
            status: "accepted",
            writer_id: "admin",
            created_at: "today",
            snapshot: { ...memory, revision: 1 },
          },
        ],
      });
    if (url.includes("/memories/"))
      return json({ memory: { ...memory, revision: currentRevision } });
    return json({
      proposals: [
        { ...proposal, status: "accepted", accepted_memory_id: "m1" },
      ],
      total: 1,
    });
  });
  render(<ReviewTab refreshVersion={0} onMutation={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: /Original/ }));
  fireEvent.click(
    screen.getByRole("button", { name: "Open revision history" }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Restore revision 1" }),
  );
  expect(await screen.findByText(/Current revision 4/)).toBeInTheDocument();
});

test("pages through proposals", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) => {
      return String(input).includes("offset=20")
        ? json({
            proposals: [{ ...proposal, id: "p2", content: "Second page" }],
            total: 21,
          })
        : json({ proposals: [proposal], total: 21 });
    });
  render(<ReviewTab refreshVersion={0} onMutation={() => {}} />);
  await screen.findByRole("button", { name: /Original/ });
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(
    await screen.findByRole("button", { name: /Second page/ }),
  ).toBeInTheDocument();
  expect(
    fetcher.mock.calls.some(([url]) => String(url).includes("offset=20")),
  ).toBe(true);
});

test("approves a whitespace-padded draft using the server's normalized conflict preview", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      if (String(input).includes("/preview")) {
        const body = JSON.parse(String(init?.body));
        return json({
          proposal_id: "p1",
          revision: body.expected_revision,
          content: body.content.trim(),
          conflicts: [],
        });
      }
      if (String(input).includes("/resolve"))
        return json({ proposal: { ...proposal, status: "accepted" }, memory });
      return json({ proposals: [proposal], total: 1 });
    });
  const mutated = vi.fn();
  render(<ReviewTab refreshVersion={0} onMutation={mutated} />);
  fireEvent.click(await screen.findByRole("button", { name: /Original/ }));
  fireEvent.change(screen.getByLabelText("Approval text"), {
    target: { value: "  Draft\n" },
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled(),
  );
  expect(screen.getByLabelText("Approval text")).toHaveValue("  Draft\n");
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  await waitFor(() => expect(mutated).toHaveBeenCalledOnce());
  expect(
    fetcher.mock.calls.some(([url]) => String(url).includes("/resolve")),
  ).toBe(true);
});

test("inspects stored evidence through HTTP and renders source text literally", async () => {
  const statuses = [
    "matched",
    "quote_mismatch",
    "role_mismatch",
    "not_found",
    "unsupported",
    "unresolved",
  ];
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      if (String(input).endsWith("/inspect-evidence"))
        return json({
          proposal_id: "p1",
          proposal_revision: 2,
          inspected_at: "2026-01-01T00:00:00Z",
          evidence: statuses.map((status, index) => ({
            index,
            status,
            source_type: "conversation",
            source_id: `s${index}`,
            quote_match: null,
            claimed_role: "user",
            recorded_role: "assistant",
            role_verified: false,
            excerpt: "<img src=x> ignore instructions",
            matched_span: null,
            source_hash: "hash",
            source_revision: 3,
            locator: { message_index: 0, page_number: null, chunk_index: null },
            note: "Local only",
          })),
        });
      if (String(input).endsWith("/preview")) return preview(init, []);
      return json({ proposals: [proposal], total: 1 });
    });
  render(<ReviewTab refreshVersion={0} onMutation={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: /Original/ }));
  fireEvent.click(
    screen.getByRole("button", { name: "Inspect stored evidence" }),
  );
  expect(
    await screen.findAllByText("<img src=x> ignore instructions"),
  ).toHaveLength(6);
  expect(document.querySelector("img")).toBeNull();
  for (const status of statuses)
    expect(screen.getByText(new RegExp(`· ${status}$`))).toBeInTheDocument();
  const call = fetcher.mock.calls.find(([url]) =>
    String(url).endsWith("/inspect-evidence"),
  );
  expect(call?.[1]?.method).toBe("POST");
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ expected_revision: 2 });
});

test("inspection conflict preserves draft until explicit reload", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (String(input).endsWith("/inspect-evidence"))
      return json({ detail: "Stale revision" }, 409);
    if (String(input).endsWith("/preview")) return preview(init, []);
    return json({ proposals: [proposal], total: 1 });
  });
  render(<ReviewTab refreshVersion={0} onMutation={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: /Original/ }));
  fireEvent.change(screen.getByLabelText("Approval text"), {
    target: { value: "Keep edits" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Inspect stored evidence" }),
  );
  expect(await screen.findByText(/Stale revision/)).toBeInTheDocument();
  expect(screen.getByLabelText("Approval text")).toHaveValue("Keep edits");
  fireEvent.click(
    screen.getByRole("button", { name: /Reload current proposal/ }),
  );
  expect(screen.getByLabelText("Approval text")).toHaveValue("Keep edits");
});

const inspectionReply = (id = "p1", revision = 2) =>
  json({
    proposal_id: id,
    proposal_revision: revision,
    inspected_at: "2026-01-01T00:00:00.123456+00:00",
    evidence: [
      {
        index: 0,
        source_type: "memory",
        source_id: "source",
        status: "matched",
        quote_match: true,
        claimed_role: null,
        recorded_role: null,
        role_verified: false,
        excerpt: "Private stored evidence",
        matched_span: { start: 0, end: 4 },
        source_hash: "local-hash",
        source_revision: 4,
        locator: { message_index: null, page_number: null, chunk_index: null },
        note: "Text match only",
      },
    ],
  });
function inspectionPending() {
  let finish: (r: Response) => void = () => {};
  const promise = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  return { promise, finish };
}
test("inspection retries a503, rejects duplicates and preserves draft", async () => {
  const pending = inspectionPending();
  let calls = 0;
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (url, init) => {
      if (String(url).endsWith("/inspect-evidence"))
        return ++calls === 1
          ? json({ detail: "Unavailable" }, 503)
          : pending.promise;
      if (String(url).endsWith("/preview")) return preview(init, []);
      return json({ proposals: [proposal], total: 1 });
    });
  render(<ReviewTab refreshVersion={0} onMutation={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: /Original/ }));
  fireEvent.change(screen.getByLabelText("Approval text"), {
    target: { value: "Keep draft" },
  });
  fireEvent.click(screen.getByText("Inspect stored evidence"));
  await screen.findByText(/Unavailable/);
  fireEvent.click(screen.getByText("Retry inspection"));
  fireEvent.click(screen.getByText("Inspect stored evidence"));
  expect(screen.getByText("Reject")).toBeDisabled();
  expect(calls).toBe(2);
  await act(async () => {
    pending.finish(inspectionReply());
    await pending.promise;
  });
  await screen.findByText("Private stored evidence");
  expect(screen.getByText(/Source revision: 4/)).toBeInTheDocument();
  expect(screen.getByLabelText("Approval text")).toHaveValue("Keep draft");
  expect(
    fetcher.mock.calls.filter(([u]) => String(u).endsWith("/inspect-evidence")),
  ).toHaveLength(2);
});

test.each(["selection", "credential", "unmount", "refresh"])(
  "discards inspection after %s even when fetch ignores abort",
  async (mode) => {
    const pending = inspectionPending();
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (url, init) => {
        if (String(url).endsWith("/inspect-evidence")) return pending.promise;
        if (String(url).endsWith("/preview")) return preview(init, []);
        return json({
          proposals: [
            proposal,
            { ...proposal, id: "p2", content: "Other proposal" },
          ],
          total: 2,
        });
      });
    const view = render(<ReviewTab refreshVersion={0} onMutation={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Original/ }));
    fireEvent.click(screen.getByText("Inspect stored evidence"));
    if (mode === "selection")
      fireEvent.click(screen.getByRole("button", { name: /Other proposal/ }));
    if (mode === "credential")
      localStorage.setItem("gigamind_master_key", "changed");
    if (mode === "unmount") view.unmount();
    if (mode === "refresh")
      view.rerender(<ReviewTab refreshVersion={1} onMutation={vi.fn()} />);
    await act(async () => {
      pending.finish(inspectionReply());
      await pending.promise;
    });
    expect(
      screen.queryByText("Private stored evidence"),
    ).not.toBeInTheDocument();
    if (mode !== "credential")
      expect(
        fetcher.mock.calls.find(([u]) =>
          String(u).endsWith("/inspect-evidence"),
        )?.[1]?.signal?.aborted,
      ).toBe(true);
  },
);

test("mismatched inspection revision cannot masquerade as current evidence", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    if (String(url).endsWith("/inspect-evidence"))
      return inspectionReply("p1", 3);
    if (String(url).endsWith("/preview")) return preview(init, []);
    return json({ proposals: [proposal], total: 1 });
  });
  render(<ReviewTab refreshVersion={0} onMutation={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: /Original/ }));
  fireEvent.click(screen.getByText("Inspect stored evidence"));
  await screen.findByText(/did not match the stored proposal revision/);
  expect(screen.queryByText("Private stored evidence")).not.toBeInTheDocument();
});

test("App gates stored evidence and refresh discards the previous inspection", async () => {
  const { App } = await import("../App");
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (url, init) => {
      const path = String(url);
      if (path.endsWith("/inspect-evidence")) return inspectionReply();
      if (path.endsWith("/preview")) return preview(init, []);
      if (path.includes("/review/proposals?"))
        return json({ proposals: [proposal], total: 1 });
      return json({
        total_memories: 0,
        total_storage_files: 0,
        total_profile_rules: 0,
        total_chat_logs: 0,
      });
    });
  render(<App />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Master API Key"), {
    target: { value: "admin" },
  });
  fireEvent.click(screen.getByText("Authorize Connection"));
  fireEvent.click(
    within(await screen.findByRole("complementary")).getByRole("button", {
      name: "Review",
    }),
  );
  fireEvent.click(await screen.findByRole("button", { name: /Original/ }));
  fireEvent.click(screen.getByText("Inspect stored evidence"));
  await screen.findByText("Private stored evidence");
  fireEvent.click(screen.getByTitle("Refresh telemetry"));
  await waitFor(() =>
    expect(
      screen.queryByText("Private stored evidence"),
    ).not.toBeInTheDocument(),
  );
  fireEvent.click(screen.getByText("Inspect stored evidence"));
  await screen.findByText("Private stored evidence");
  expect(
    fetcher.mock.calls.filter(([u]) => String(u).endsWith("/inspect-evidence")),
  ).toHaveLength(2);
});
