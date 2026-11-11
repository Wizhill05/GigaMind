import React, { useEffect, useState } from "react";
import { ApiError } from "../../api";
import {
  getHistory,
  getMemory,
  listProposals,
  previewProposal,
  resolveProposal,
  restoreMemory,
  type Proposal,
  type ReviewMemory,
  type Revision,
} from "../../reviewApi";
const button =
  "border border-[#454545] px-3 py-1.5 hover:border-[#ff6b00] disabled:opacity-40";
const panel = "border border-[#303030] bg-[#171717] p-4 space-y-3";
const message = (e: unknown) =>
  e instanceof Error ? e.message : "Request failed";
export function ReviewTab({
  refreshVersion,
  onMutation,
}: {
  refreshVersion: number;
  onMutation: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const [reload, setReload] = useState(0);
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<Proposal[]>([]);
  const [selected, setSelected] = useState<Proposal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [content, setContent] = useState("");
  const [conflicts, setConflicts] = useState<ReviewMemory[]>([]);
  const [chosen, setChosen] = useState<string[]>([]);
  const [previewKey, setPreviewKey] = useState("");
  const [detailError, setDetailError] = useState("");
  const [detailReload, setDetailReload] = useState(0);
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [historyId, setHistoryId] = useState<string | null>(null);
  const [current, setCurrent] = useState<ReviewMemory | null>(null);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [historyReload, setHistoryReload] = useState(0);
  useEffect(() => {
    const c = new AbortController();
    setLoading(true);
    setError("");
    listProposals(offset, c.signal)
      .then((d) => {
        if (!c.signal.aborted) {
          setItems(d.proposals);
          setTotal(d.total);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) {
          setError(message(e));
          setLoading(false);
        }
      });
    return () => c.abort();
  }, [offset, reload, refreshVersion]);
  useEffect(() => {
    const c = new AbortController();
    setConflicts([]);
    setChosen([]);
    setPreviewKey("");
    if (selected?.status === "proposed" && content.trim() && !stale) {
      setDetailError("");
      const key = JSON.stringify([selected.id, selected.revision, content]);
      const timer = window.setTimeout(() => {
        previewProposal(selected.id, content, selected.revision, c.signal)
          .then((result) => {
            if (
              !c.signal.aborted &&
              result.proposal_id === selected.id &&
              result.revision === selected.revision &&
              result.content === content.trim()
            ) {
              setConflicts(result.conflicts);
              setPreviewKey(key);
            } else if (!c.signal.aborted) {
              setDetailError(
                "Preview response did not match the current draft. Please retry.",
              );
            }
          })
          .catch((e) => {
            if (!c.signal.aborted) {
              setDetailError(message(e));
              if (e instanceof ApiError && e.status === 409) setStale(true);
            }
          });
      }, 200);
      return () => {
        window.clearTimeout(timer);
        c.abort();
      };
    }
    return () => c.abort();
  }, [selected, content, detailReload, stale]);
  useEffect(() => {
    const c = new AbortController();
    setCurrent(null);
    setRevisions([]);
    setHistoryError("");
    if (historyId)
      Promise.all([
        getMemory(historyId, c.signal),
        getHistory(historyId, c.signal),
      ])
        .then(([m, h]) => {
          if (!c.signal.aborted) {
            setCurrent(m.memory);
            setRevisions(h.revisions);
          }
        })
        .catch((e) => {
          if (!c.signal.aborted) setHistoryError(message(e));
        });
    return () => c.abort();
  }, [historyId, historyReload]);
  async function resolve(action: "approve" | "reject") {
    if (!selected) return;
    setBusy(true);
    setDetailError("");
    try {
      await resolveProposal(selected.id, {
        action,
        expected_revision: selected.revision,
        ...(action === "approve" ? { content } : {}),
        supersedes: action === "approve" ? chosen : [],
      });
      setSelected(null);
      setReload((v) => v + 1);
      onMutation();
    } catch (e) {
      setDetailError(message(e));
      if (e instanceof ApiError && e.status === 409) setStale(true);
    } finally {
      setBusy(false);
    }
  }
  async function retryProposal() {
    if (!selected) return;
    setBusy(true);
    try {
      const page = await listProposals(offset);
      const fresh = page.proposals.find((p) => p.id === selected.id);
      if (!fresh) throw new Error("Proposal is no longer on this page.");
      setSelected(fresh);
      setStale(false);
      setItems(page.proposals);
      setTotal(page.total);
    } catch (e) {
      setDetailError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function restore(revision: number) {
    if (!current) return;
    setBusy(true);
    setHistoryError("");
    try {
      await restoreMemory(current.id, {
        revision,
        expected_revision: current.revision,
      });
      setHistoryReload((v) => v + 1);
      onMutation();
    } catch (e) {
      setHistoryError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="space-y-5 text-sm">
      <h1 className="text-xl font-semibold">Review proposals</h1>
      {loading ? (
        <p role="status">Loading proposals...</p>
      ) : error ? (
        <div role="alert">
          {error}{" "}
          <button className={button} onClick={() => setReload((v) => v + 1)}>
            Retry
          </button>
        </div>
      ) : (
        <>
          {items.length === 0 ? (
            <p>No proposals on this page.</p>
          ) : (
            <div className="space-y-2">
              {items.map((p) => (
                <button
                  key={p.id}
                  className={`${panel} w-full text-left hover:border-[#ff6b00]`}
                  disabled={busy}
                  onClick={() => {
                    setSelected(p);
                    setContent(p.content);
                    setStale(false);
                  }}
                >
                  <span className="text-[#ff6b00]">{p.status}</span> ·{" "}
                  {p.content}
                  <span className="block text-[#8a8f9e]">
                    {p.writer_id} · {p.project_id ?? "Global"} · revision{" "}
                    {p.revision}
                  </span>
                </button>
              ))}
            </div>
          )}
          <div className="flex gap-3 items-center">
            <button
              className={button}
              disabled={busy || offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 20))}
            >
              Previous
            </button>
            <span>
              {total ? offset + 1 : 0}–{Math.min(offset + 20, total)} of {total}
            </span>
            <button
              className={button}
              disabled={busy || offset + 20 >= total}
              onClick={() => setOffset(offset + 20)}
            >
              Next
            </button>
          </div>
        </>
      )}
      {selected && (
        <div className={panel}>
          <h2 className="text-lg">Proposal {selected.id}</h2>
          <p>
            Writer: {selected.writer_id} · Project:{" "}
            {selected.project_id ?? "Global"} · Status: {selected.status} ·
            Revision: {selected.revision}
          </p>
          <h3>Evidence</h3>
          {selected.evidence.length ? (
            selected.evidence.map((e, i) => (
              <blockquote key={i} className="border-l-2 border-[#ff6b00] pl-3">
                <p>{e.quote}</p>
                <p>
                  {e.source_type} · {e.source_id}
                  {e.source_role ? ` · ${e.source_role}` : ""}
                </p>
              </blockquote>
            ))
          ) : (
            <p>No evidence supplied.</p>
          )}
          {selected.status === "proposed" && (
            <>
              <label className="block">
                Approval text
                <textarea
                  className="block w-full bg-[#0f0f0f] border border-[#454545] p-2"
                  value={content}
                  disabled={busy}
                  onChange={(e) => {
                    setPreviewKey("");
                    setChosen([]);
                    setContent(e.target.value);
                  }}
                />
              </label>
              {conflicts.length > 0 && (
                <div>
                  <h3>Choose every record to supersede</h3>
                  {conflicts.map((c) => (
                    <label key={c.id} className="block">
                      <input
                        type="checkbox"
                        disabled={busy}
                        checked={chosen.includes(c.id)}
                        onChange={(e) =>
                          setChosen(
                            e.target.checked
                              ? [...chosen, c.id]
                              : chosen.filter((id) => id !== c.id),
                          )
                        }
                      />{" "}
                      {c.content} ({c.id}, revision {c.revision}, {c.status})
                    </label>
                  ))}
                </div>
              )}
              {!previewKey && !detailError && !stale && content.trim() && (
                <p role="status">Checking conflicts...</p>
              )}
              {detailError && (
                <p role="alert">
                  {detailError}{" "}
                  {!stale && (
                    <button
                      className={button}
                      disabled={busy}
                      onClick={() => setDetailReload((v) => v + 1)}
                    >
                      Retry preview
                    </button>
                  )}
                </p>
              )}
              {stale && (
                <button
                  className={button}
                  disabled={busy}
                  onClick={retryProposal}
                >
                  Reload current proposal and keep edits
                </button>
              )}
              <div className="flex gap-2">
                <button
                  className={button}
                  disabled={
                    busy ||
                    stale ||
                    !content.trim() ||
                    previewKey !==
                      JSON.stringify([
                        selected.id,
                        selected.revision,
                        content,
                      ]) ||
                    chosen.length !== conflicts.length
                  }
                  onClick={() => resolve("approve")}
                >
                  Approve
                </button>
                <button
                  className={button}
                  disabled={busy || stale}
                  onClick={() => resolve("reject")}
                >
                  Reject
                </button>
              </div>
            </>
          )}
          {selected.accepted_memory_id && (
            <button
              className={button}
              disabled={busy}
              onClick={() => setHistoryId(selected.accepted_memory_id ?? null)}
            >
              Open revision history
            </button>
          )}
        </div>
      )}
      {historyId && (
        <div className={panel}>
          <h2 className="text-lg">Revision history</h2>
          {historyError && (
            <p role="alert">
              {historyError}{" "}
              <button
                className={button}
                disabled={busy}
                onClick={() => setHistoryReload((v) => v + 1)}
              >
                Reload current record
              </button>
            </p>
          )}
          {!current && !historyError && <p role="status">Loading history...</p>}
          {current && (
            <>
              <p>
                Current revision {current.revision}: {current.content} (
                {current.status})
              </p>
              {revisions.map((r) => (
                <div
                  key={r.revision}
                  className="border-t border-[#303030] pt-2"
                >
                  <p>
                    Revision {r.revision} · {r.status} · {r.writer_id} ·{" "}
                    {r.created_at}
                  </p>
                  <p>{r.snapshot.content}</p>
                  <button
                    className={button}
                    disabled={busy || !!historyError}
                    onClick={() => restore(r.revision)}
                  >
                    Restore revision {r.revision}
                  </button>
                </div>
              ))}
            </>
          )}
          <button
            className={button}
            disabled={busy}
            onClick={() => setHistoryId(null)}
          >
            Close history
          </button>
        </div>
      )}
    </section>
  );
}
