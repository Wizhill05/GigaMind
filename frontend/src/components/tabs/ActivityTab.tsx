import React, { useEffect, useState } from "react";
import { listActivity, ActivityEvent } from "../../reviewApi";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; events: ActivityEvent[]; total: number };
const descriptions: Record<string, string> = {
  proposed: "proposed",
  propose: "proposed",
  approve: "approved",
  reject: "rejected",
  supersede: "superseded",
  restore: "restored",
};
export function ActivityTab({ refreshVersion }: { refreshVersion: number }) {
  const [project, setProject] = useState("");
  const [page, setPage] = useState(0);
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState<State>({ kind: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    listActivity(project.trim(), page * 20, controller.signal).then(
      (result) => {
        if (!controller.signal.aborted) setState({ kind: "loaded", ...result });
      },
      (error) => {
        if (!controller.signal.aborted)
          setState({
            kind: "error",
            message:
              error instanceof Error
                ? error.message
                : "Unable to load activity.",
          });
      },
    );
    return () => controller.abort();
  }, [project, page, refreshVersion, retry]);
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Activity</h1>
      <label className="block text-sm">
        Project ID{" "}
        <input
          className="ml-2 bg-[#1c1c1c] border border-[#444] p-2 text-white"
          value={project}
          onChange={(e) => {
            setProject(e.target.value);
            setPage(0);
          }}
          placeholder="All visible projects"
        />
      </label>
      {state.kind === "loading" && <p role="status">Loading activity…</p>}
      {state.kind === "error" && (
        <div role="alert">
          <p>{state.message}</p>
          <button
            className="text-orange-400"
            onClick={() => setRetry((n) => n + 1)}
          >
            Retry
          </button>
        </div>
      )}
      {state.kind === "loaded" && (
        <>
          {state.events.length === 0 ? (
            <p>No activity found.</p>
          ) : (
            <ol className="space-y-3">
              {state.events.map((event) => (
                <li
                  key={event.id}
                  className="border border-[#262626] bg-[#141414] p-4 space-y-1"
                >
                  <p>
                    <strong>{event.writer_id}</strong>{" "}
                    {descriptions[event.action] ?? event.action}{" "}
                    <span className="font-mono break-all">
                      {event.target_id}
                    </span>
                  </p>
                  <p className="text-sm text-[#a5aab5]">
                    {event.project_id ?? "Global"} ·{" "}
                    <time dateTime={event.created_at}>{event.created_at}</time>
                  </p>
                </li>
              ))}
            </ol>
          )}
          <div className="flex gap-4 items-center text-sm">
            <button disabled={page === 0} onClick={() => setPage((n) => n - 1)}>
              Previous
            </button>
            <span>
              Page {page + 1} · {state.total} events
            </span>
            <button
              disabled={(page + 1) * 20 >= state.total}
              onClick={() => setPage((n) => n + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </section>
  );
}
