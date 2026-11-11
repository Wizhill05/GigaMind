import React, { useEffect, useRef, useState } from "react";
import { ApiError, getApiKey } from "../../api";
import {
  deleteKnowledge,
  getKnowledgeHistory,
  listKnowledge,
  restoreKnowledge,
  type History,
  type Knowledge,
} from "../../knowledgeApi";

export function KnowledgeTab({ refreshVersion }: { refreshVersion: number }) {
  const [q, setQ] = useState("");
  const [project, setProject] = useState("");
  const [status, setStatus] = useState("accepted");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ memories: Knowledge[]; total: number }>({
    memories: [],
    total: 0,
  });
  const [selected, setSelected] = useState<Knowledge | null>(null);
  const [history, setHistory] = useState<History>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [conflict, setConflict] = useState(false);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const key = getApiKey();
    setError("");
    listKnowledge(q, project, status, offset, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted && getApiKey() === key) setData(result);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError("Could not load knowledge.");
      });
    return () => controller.abort();
  }, [q, project, status, offset, refreshVersion, version]);
  useEffect(() => {
    const controller = new AbortController();
    const key = getApiKey();
    setHistory([]);
    if (selected)
      getKnowledgeHistory(selected.id, controller.signal)
        .then((result) => {
          if (!controller.signal.aborted && getApiKey() === key)
            setHistory(result.revisions);
        })
        .catch(() => {
          if (!controller.signal.aborted) setError("Could not load history.");
        });
    return () => controller.abort();
  }, [selected]);
  async function mutate(action: () => Promise<unknown>) {
    if (busyRef.current || conflict) return;
    busyRef.current = true;
    setBusy(true);
    try {
      await action();
      setSelected(null);
      setVersion((v) => v + 1);
      setError("");
    } catch (err) {
      const stale = err instanceof ApiError && err.status === 409;
      setConflict(stale);
      setError(
        stale
          ? "This record changed. Reload before trying again."
          : "Action failed.",
      );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  const reload = () => {
    setSelected(null);
    setConflict(false);
    setVersion((v) => v + 1);
  };
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Approved knowledge</h1>
      <p className="text-sm text-gray-400">
        Canonical records used by memory retrieval. Legacy source notes are
        listed under Memories.
      </p>
      <div className="flex gap-2 flex-wrap">
        <label>
          Search{" "}
          <input
            className="bg-[#222] p-2"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        <label>
          Project{" "}
          <input
            className="bg-[#222] p-2"
            placeholder="Global scope"
            value={project}
            onChange={(e) => {
              setProject(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        <label>
          Status{" "}
          <select
            className="bg-[#222] p-2"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            <option>accepted</option>
            <option>superseded</option>
            <option>deleted</option>
            <option>expired</option>
          </select>
        </label>
      </div>
      {error && (
        <div role="alert">
          {error} <button onClick={reload}>Reload</button>
        </div>
      )}
      <p>{data.total} records</p>
      {data.memories.map((m) => (
        <article key={m.id} className="border border-[#333] p-4 space-y-2">
          <p>{m.content}</p>
          <p className="text-xs text-gray-400">
            {m.kind ?? "record"} · {m.project_id ?? "Global scope"} ·{" "}
            {m.writer_id} · revision {m.revision} · {m.status}
          </p>
          {m.evidence.map((e, i) => (
            <p key={i} className="text-sm">
              {e.source_type} / {e.source_id}
              {e.source_role ? ` (${e.source_role})` : ""}: {e.quote}
            </p>
          ))}
          <button onClick={() => setSelected(m)} className="text-orange-400">
            History and actions
          </button>
        </article>
      ))}
      <div className="flex gap-4">
        <button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 20))}
        >
          Previous
        </button>
        <span>Page {Math.floor(offset / 20) + 1}</span>
        <button
          disabled={offset + 20 >= data.total}
          onClick={() => setOffset(offset + 20)}
        >
          Next
        </button>
      </div>
      {selected && (
        <div className="border border-[#555] p-4 space-y-3">
          <h2>History: {selected.content}</h2>
          {selected.status === "accepted" && (
            <button
              disabled={busy || conflict}
              onClick={() => {
                if (
                  window.confirm(
                    `Delete this accepted record at revision ${selected.revision}?`,
                  )
                )
                  void mutate(() =>
                    deleteKnowledge(selected.id, selected.revision),
                  );
              }}
            >
              Delete accepted record
            </button>
          )}
          {history.map((r) => (
            <div key={r.revision} className="border-t border-[#333] pt-2">
              <p>
                Revision {r.revision} · {r.status}
              </p>
              <p>{r.snapshot.content}</p>
              <button
                disabled={busy || conflict || r.revision === selected.revision}
                onClick={() =>
                  void mutate(() =>
                    restoreKnowledge(
                      selected.id,
                      r.revision,
                      selected.revision,
                    ),
                  )
                }
              >
                Restore revision {r.revision}
              </button>
            </div>
          ))}
          <button onClick={() => setSelected(null)}>Close</button>
        </div>
      )}
    </section>
  );
}
