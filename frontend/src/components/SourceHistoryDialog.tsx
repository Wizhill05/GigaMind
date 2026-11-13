import React, { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { useDialogFocus } from "../hooks/useDialogFocus";
import {
  getSourceProvenance,
  type SourceKind,
  type SourceProvenance,
} from "../sourceProvenanceApi";

interface Props {
  kind: SourceKind;
  sourceId: string;
  apiKey: string;
  onClose: () => void;
}
type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; data: SourceProvenance };
const buttonClass =
  "px-3 py-1.5 border border-[#333333] text-[#c1c5d0] hover:text-white hover:border-[#ff6b00]/40 disabled:opacity-40 text-xs";

function History({ kind, sourceId, apiKey }: Omit<Props, "onClose">) {
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<LoadState>({ status: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setState({ status: "loading" });
    if (!apiKey.trim()) {
      setState({
        status: "error",
        message: "An API key is required to view history.",
      });
    } else {
      getSourceProvenance({
        kind,
        sourceId,
        apiKey,
        offset,
        signal: controller.signal,
      }).then(
        (data) => {
          if (current) setState({ status: "loaded", data });
        },
        (error) => {
          if (current)
            setState({
              status: "error",
              message:
                error instanceof Error
                  ? error.message
                  : "Could not load history.",
            });
        },
      );
    }
    return () => {
      current = false;
      controller.abort();
    };
  }, [kind, sourceId, apiKey, offset, attempt]);

  if (state.status === "loading")
    return <p role="status">Loading history...</p>;
  if (state.status === "error")
    return (
      <div className="space-y-3">
        <p role="alert">Could not load history: {state.message}</p>
        <button
          className={buttonClass}
          onClick={() => setAttempt((n) => n + 1)}
        >
          Retry
        </button>
      </div>
    );
  const { head, receipts, total } = state.data;
  const creator =
    head.creator_provenance === "legacy_unknown"
      ? "Unknown (legacy)"
      : head.creator_provenance === "unattributed"
        ? "Unattributed"
        : (head.creator_id ?? "Unknown");
  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <p>Original credential: {creator}</p>
        <p>Status: {head.active ? "Active" : "Deleted"}</p>
        <p>History revision: {head.revision}</p>
      </div>
      <p className="text-[#8a8f9e]">
        Recorded credentials identify the submitting account. Source authorship
        and factual accuracy require separate verification.
      </p>
      {kind === "file" && (
        <p className="text-[#8a8f9e]">
          Created records an upload registration. Verified records a remote
          checksum match, which is separate from indexing. Deleted records
          forgetting; physical cleanup may still be pending. These receipts do
          not establish who authored the file.
        </p>
      )}
      <h4 className="text-white font-semibold">Receipts</h4>
      {receipts.length === 0 ? (
        <p>No receipts on this page.</p>
      ) : (
        <ol className="space-y-3">
          {receipts.map((receipt) => (
            <li
              key={receipt.revision}
              className="border border-[#333333] p-3 space-y-1 break-all"
            >
              <p className="text-white">
                Receipt {receipt.revision}: {receipt.operation}
              </p>
              <p>
                Credential:{" "}
                {receipt.writer_provenance === "unattributed"
                  ? "Unattributed"
                  : (receipt.writer_id ?? "Unknown")}
              </p>
              <p>
                Time:{" "}
                <time dateTime={receipt.timestamp}>{receipt.timestamp}</time>
              </p>
              <p>Payload hash: {receipt.payload_hash ?? "Unavailable"}</p>
              <p>Source revision: {receipt.source_revision ?? "Unavailable"}</p>
            </li>
          ))}
        </ol>
      )}
      <div className="flex items-center justify-between gap-3">
        <button
          className={buttonClass}
          disabled={offset === 0}
          onClick={() => {
            setState({ status: "loading" });
            setOffset(Math.max(0, offset - 20));
          }}
        >
          Previous
        </button>
        <span>
          {total === 0
            ? "0 receipts"
            : `${offset + 1}–${Math.min(offset + receipts.length, total)} of ${total}`}
        </span>
        <button
          className={buttonClass}
          disabled={offset + 20 >= total || offset + 20 > 1_000_000}
          onClick={() => {
            setState({ status: "loading" });
            setOffset(offset + 20);
          }}
        >
          Next
        </button>
      </div>
    </div>
  );
}

export function SourceHistoryDialog({
  kind,
  sourceId,
  apiKey,
  onClose,
}: Props) {
  const dialogRef = useDialogFocus(true);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
  }, []);
  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);
  return (
    <div
      className="fixed inset-0 bg-[#0f0f0f]/85 backdrop-blur-md z-50 flex items-center justify-center p-4 font-sans"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Source history"
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          if (
            (event.ctrlKey || event.metaKey) &&
            event.key.toLowerCase() === "k"
          ) {
            event.preventDefault();
            event.stopPropagation();
          }
        }}
        className="bg-[#181818] border border-[#262626] max-w-xl w-full p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto"
      >
        <div className="flex justify-between items-center border-b border-[#262626] pb-3">
          <h3 className="text-sm font-semibold text-white">Source history</h3>
          <span className="text-xs text-[#8a8f9e] break-all">
            {kind}: {sourceId}
          </span>
          <button
            ref={closeRef}
            aria-label="Close dialog"
            onClick={onClose}
            className="text-[#8a8f9e] hover:text-white"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="text-xs text-[#c1c5d0]">
          <History
            key={JSON.stringify([kind, sourceId, apiKey])}
            kind={kind}
            sourceId={sourceId}
            apiKey={apiKey}
          />
        </div>
      </div>
    </div>
  );
}
