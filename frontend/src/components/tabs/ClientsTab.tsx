import React, { useEffect, useRef, useState } from "react";
import {
  Client,
  createClient,
  listClients,
  revokeClient,
  rotateClient,
} from "../../clientsApi";

const scopes = [
  "memory:read",
  "memory:propose",
  "memory:write",
  "memory:approve",
  "memory:delete",
];
type ListState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; clients: Client[] };
const message = (error: unknown) =>
  error instanceof Error ? error.message : "Request failed.";
const input = "block w-full bg-[#1c1c1c] border border-[#444] p-2 text-white";
const button =
  "border border-[#555] px-3 py-2 text-sm disabled:opacity-40 hover:border-orange-400";
export function ClientsTab({ refreshVersion }: { refreshVersion: number }) {
  const [page, setPage] = useState(0);
  const [reload, setReload] = useState(0);
  const [list, setList] = useState<ListState>({ kind: "loading" });
  const [name, setName] = useState("");
  const [projects, setProjects] = useState("");
  const [expiry, setExpiry] = useState("");
  const [selected, setSelected] = useState<string[]>([
    "memory:read",
    "memory:propose",
  ]);
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [copyStatus, setCopyStatus] = useState("");
  const [error, setError] = useState("");
  const [confirmation, setConfirmation] = useState<{
    action: "rotate" | "revoke";
    client: Client;
  } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setList({ kind: "loading" });
    listClients(page * 20, controller.signal).then(
      (result) => {
        if (!controller.signal.aborted)
          setList({ kind: "loaded", clients: result.clients });
      },
      (error) => {
        if (!controller.signal.aborted)
          setList({ kind: "error", message: message(error) });
      },
    );
    return () => controller.abort();
  }, [page, reload, refreshVersion]);
  const refresh = () => setReload((n) => n + 1);
  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (inFlight.current || token || confirmation) return;
    const ids = projects
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean);
    if (
      !name.trim() ||
      !ids.length ||
      !selected.length ||
      (expiry &&
        (!Number.isFinite(new Date(expiry).getTime()) ||
          new Date(expiry).getTime() <= Date.now()))
    ) {
      setError(
        "Enter a name, project IDs, at least one scope, and a future expiry if specified.",
      );
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await createClient({
        name: name.trim(),
        scopes: selected,
        project_ids: ids,
        expires_at: expiry ? new Date(expiry).toISOString() : null,
      });
      setToken(result.token);
      setName("");
      refresh();
    } catch (e) {
      setError(message(e));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  async function confirmAction() {
    if (!confirmation || inFlight.current || token) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      if (confirmation.action === "rotate") {
        const result = await rotateClient(
          confirmation.client.id,
          confirmation.client.revision,
        );
        setToken(result.token);
      } else await revokeClient(confirmation.client.id);
      setConfirmation(null);
      refresh();
    } catch (e) {
      setError(message(e));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-xl font-semibold">Clients</h1>
        <button className={button} disabled={busy} onClick={refresh}>
          Refresh
        </button>
      </div>
      {token && (
        <div className="border border-orange-500 p-4 space-y-2" role="status">
          <p>
            Copy this token now. It will not be shown again after dismissal.
          </p>
          <code className="break-all block select-all">{token}</code>
          <div className="flex gap-2">
            <button
              className={button}
              onClick={async () => {
                try {
                  if (!navigator.clipboard?.writeText) throw new Error();
                  await navigator.clipboard.writeText(token);
                  setCopyStatus("Token copied.");
                } catch {
                  setCopyStatus("Unable to copy token. Select it and copy manually.");
                }
              }}
            >
              Copy token
            </button>
            <button className={button} onClick={() => { setToken(null); setCopyStatus(""); }}>
              Dismiss token
            </button>
          </div>
          {copyStatus && <p role="status">{copyStatus}</p>}
        </div>
      )}
      {error && (
        <div role="alert" className="text-red-400">
          {error}{" "}
          <button className="underline" disabled={busy} onClick={() => { setConfirmation(null); refresh(); }}>
            Reload clients
          </button>
        </div>
      )}
      <form onSubmit={create} className="border border-[#333] p-4 space-y-4">
        <fieldset disabled={busy || confirmation !== null} className="space-y-4">
        <h2 className="font-semibold">Create client</h2>
        <label className="block text-sm">
          Name
          <input
            className={input}
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={200}
            required
          />
        </label>
        <label className="block text-sm">
          Project IDs (comma separated)
          <input
            className={input}
            value={projects}
            onChange={(e) => setProjects(e.target.value)}
            required
          />
        </label>
        <fieldset>
          <legend className="text-sm">Scopes</legend>
          <div className="flex flex-wrap gap-4 mt-2">
            {scopes.map((scope) => (
              <label key={scope} className="text-sm">
                <input
                  type="checkbox"
                  checked={selected.includes(scope)}
                  onChange={(e) =>
                    setSelected(
                      e.target.checked
                        ? [...selected, scope]
                        : selected.filter((s) => s !== scope),
                    )
                  }
                />{" "}
                {scope}
              </label>
            ))}
          </div>
        </fieldset>
        <label className="block text-sm">
          Expiry (optional)
          <input
            className={input}
            type="datetime-local"
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
          />
        </label>
        <button className={button} disabled={busy || token !== null || confirmation !== null}>
          Create client
        </button>
        {token && (
          <p className="text-sm text-[#aaa]">
            Dismiss the current token before issuing another.
          </p>
        )}
        </fieldset>
      </form>
      {confirmation && (
        <div
          className="border border-orange-500 p-4 space-y-3"
          role="region"
          aria-label={`Confirm ${confirmation.action}`}
        >
          <p>
            {confirmation.action === "rotate"
              ? "Rotating invalidates the current token immediately."
              : "Revoking prevents this client from authenticating."}{" "}
            Confirm {confirmation.action} for {confirmation.client.name}?
          </p>
          <div className="flex gap-2">
            <button
              className={button}
              disabled={
                busy || token !== null
              }
              onClick={() => void confirmAction()}
            >
              Confirm {confirmation.action}
            </button>
            <button
              className={button}
              disabled={busy}
              onClick={() => setConfirmation(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {list.kind === "loading" && <p role="status">Loading clients…</p>}
      {list.kind === "error" && (
        <div role="alert">
          {list.message}{" "}
          <button className="underline" disabled={busy} onClick={refresh}>
            Retry
          </button>
        </div>
      )}
      {list.kind === "loaded" && (
        <>
          <div className="space-y-3">
            {list.clients.length === 0 && <p>No clients on this page.</p>}
            {list.clients.map((client) => (
              <article
                key={client.id}
                className="border border-[#333] p-4 space-y-2"
              >
                <h2 className="font-semibold">
                  {client.name} {client.revoked && "(revoked)"}
                </h2>
                <p className="text-sm text-[#aaa] break-all">
                  ID: {client.id} · Revision: {client.revision}
                </p>
                <p className="text-sm">
                  Projects: {client.project_ids.join(", ")} · Scopes:{" "}
                  {client.scopes.join(", ")}
                </p>
                <p className="text-sm text-[#aaa]">
                  Created: {client.created_at ?? "Unknown"} · Expires:{" "}
                  {client.expires_at ?? "Never"} · Last used:{" "}
                  {client.last_used_at ?? "Never"}
                </p>
                <div className="flex gap-2">
                  <button
                    className={button}
                    disabled={busy || client.revoked || token !== null || confirmation !== null}
                    onClick={() =>
                      setConfirmation({ action: "rotate", client })
                    }
                  >
                    Rotate {client.name}
                  </button>
                  <button
                    className={button}
                    disabled={busy || client.revoked || confirmation !== null}
                    onClick={() =>
                      setConfirmation({ action: "revoke", client })
                    }
                  >
                    Revoke {client.name}
                  </button>
                </div>
              </article>
            ))}
          </div>
          <div className="flex gap-3 items-center">
            <button
              className={button}
              disabled={busy || confirmation !== null || page === 0}
              onClick={() => setPage((p) => p - 1)}
            >
              Previous
            </button>
            <span>Page {page + 1}</span>
            <button
              className={button}
              disabled={busy || confirmation !== null || list.clients.length < 20}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </section>
  );
}
