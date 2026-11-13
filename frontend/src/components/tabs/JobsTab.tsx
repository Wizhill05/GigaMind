import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../api";
import {
  cancelJob,
  getJob,
  Job,
  listJobs,
  retryCleanup,
  retryIndex,
} from "../../jobsApi";

const button =
  "border border-[#555] px-3 py-2 text-sm disabled:opacity-40 hover:border-orange-400";
const pending = (job: Job) =>
  ["queued", "running", "retrying"].includes(job.state);
const message = (error: unknown) =>
  error instanceof Error ? error.message : "Request failed";

export function JobsTab({ refreshVersion }: { refreshVersion: number }) {
  const [page, setPage] = useState(0);
  const [reload, setReload] = useState(0);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<"cancel" | "retry" | null>(null);
  const inFlight = useRef(false);
  const [visible, setVisible] = useState(!document.hidden);
  const refresh = () => {
    if (!inFlight.current) setReload((n) => n + 1);
  };
  useEffect(() => {
    const onVisibility = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    Promise.all([
      listJobs(page * 20, controller.signal),
      selected ? getJob(selected, controller.signal) : Promise.resolve(null),
    ]).then(
      ([result, item]) => {
        if (controller.signal.aborted) return;
        setJobs(result.jobs);
        setDetail(item);
        setError("");
        setLoading(false);
      },
      (e) => {
        if (!controller.signal.aborted) {
          setDetail(null);
          setConfirm(null);
          setError(message(e));
          setLoading(false);
        }
      },
    );
    return () => controller.abort();
  }, [page, selected, reload, refreshVersion]);
  useEffect(() => {
    if (
      !visible ||
      busy ||
      loading ||
      (!jobs.some(pending) && !(detail && pending(detail)))
    )
      return;
    const timer = window.setTimeout(refresh, 5000);
    return () => window.clearTimeout(timer);
  }, [visible, loading, jobs, detail, busy]);
  async function act() {
    if (!detail || !confirm || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setActionError("");
    try {
      if (confirm === "cancel") await cancelJob(detail.id);
      else if (detail.kind === "index_file" || detail.kind === "index_conversation") {
        const result = await retryIndex(detail);
        setSelected(result.id);
      } else {
        const key = detail.payload.key;
        if (typeof key !== "string" || !key)
          throw new Error(
            "The file key is unavailable; cleanup cannot be retried.",
          );
        const result = await retryCleanup(key);
        setSelected(result.job_id);
      }
      setConfirm(null);
      setReload((n) => n + 1);
    } catch (e) {
      setActionError(message(e));
      if (e instanceof ApiError && e.status === 409) {
        setConfirm(null);
        setReload((n) => n + 1);
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="space-y-5">
      <div className="flex justify-between">
        <h1 className="text-xl font-semibold">Jobs</h1>
        <button className={button} disabled={busy} onClick={refresh}>
          Refresh
        </button>
      </div>
      <p className="text-sm text-[#aaa]">
        Index jobs process files and conversations for search. Cleanup jobs remove file data;
        accepted cleanup does not mean bytes have been deleted.
      </p>
      {error && (
        <p role="alert" className="text-red-400">
          {error}{" "}
          <button className="underline" disabled={busy} onClick={refresh}>
            Retry load
          </button>
        </p>
      )}
      {actionError && (
        <p role="alert" className="text-red-400">
          {actionError}
        </p>
      )}
      {loading && <p role="status">Loading jobs…</p>}
      <div className="space-y-2">
        {jobs.map((item) => (
          <button
            key={item.id}
            disabled={busy}
            className="block w-full text-left border border-[#333] p-3 hover:border-orange-400"
            onClick={() => {
              if (inFlight.current) return;
              setConfirm(null);
              setSelected(item.id);
            }}
          >
            {item.kind} · {item.state} · {item.id}
          </button>
        ))}
      </div>
      {!loading && jobs.length === 0 && <p>No jobs on this page.</p>}
      <div className="flex gap-3 items-center">
        <button
          className={button}
          disabled={busy || page === 0}
          onClick={() => {
            if (!inFlight.current) setPage((p) => p - 1);
          }}
        >
          Previous
        </button>
        <span>Page {page + 1}</span>
        <button
          className={button}
          disabled={busy || jobs.length < 20}
          onClick={() => {
            if (!inFlight.current) setPage((p) => p + 1);
          }}
        >
          Next
        </button>
      </div>
      {!loading && !error && detail && detail.id === selected && (
        <article className="border border-[#333] p-4 space-y-3">
          <h2 className="font-semibold">Job {detail.id}</h2>
          <p>
            {detail.kind} · {detail.state} · Attempt {detail.attempts} of{" "}
            {detail.max_attempts}
          </p>
          <p>
            Created: {detail.created_at} · Updated: {detail.updated_at} ·
            Available: {detail.available_at}
          </p>
          <p>Payload: {JSON.stringify(detail.payload)}</p>
          <p>Result: {JSON.stringify(detail.result)}</p>
          {detail.error && (
            <p className="text-red-400">Error: {detail.error}</p>
          )}
          {pending(detail) && (
            <button
              className={button}
              disabled={busy || confirm !== null}
              onClick={() => {
                if (!inFlight.current) setConfirm("cancel");
              }}
            >
              Cancel job
            </button>
          )}
          {detail.state === "failed" &&
            ["index_file", "index_conversation", "delete_file"].includes(detail.kind) && (
              <button
                className={button}
                disabled={busy || confirm !== null}
                onClick={() => {
                  if (!inFlight.current) setConfirm("retry");
                }}
              >
                Retry {detail.kind === "delete_file" ? "cleanup" : "indexing"}
              </button>
            )}
          {confirm && (
            <div
              role="region"
              aria-label="Confirm job action"
              className="border border-orange-500 p-3 space-y-2"
            >
              <p>
                {confirm === "cancel"
                  ? "Cancel this job? Cancellation does not restore deleted files."
                  : "Retry this operation? The resource may have changed or been removed."}
              </p>
              <button
                className={button}
                disabled={busy}
                onClick={() => void act()}
              >
                Confirm {confirm}
              </button>{" "}
              <button
                className={button}
                disabled={busy}
                onClick={() => {
                  if (!inFlight.current) setConfirm(null);
                }}
              >
                Back
              </button>
            </div>
          )}
        </article>
      )}
    </section>
  );
}
