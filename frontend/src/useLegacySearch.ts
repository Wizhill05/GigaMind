import { useCallback, useEffect, useRef, useState } from "react";
import { getApiKey, searchMemory, type LegacySearchResult } from "./api";

type Query = {
  query?: string;
  image?: string;
  category?: string;
  sourceAgent?: string;
  limit?: number;
  scope?: string;
};

type SearchState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; results: LegacySearchResult[] };

export function useLegacySearch() {
  const current = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const [state, setState] = useState<SearchState>({ kind: "idle" });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      current.current?.abort();
      current.current = null;
    };
  }, []);
  const clear = useCallback(() => {
    current.current?.abort();
    current.current = null;
    if (mounted.current) setState({ kind: "idle" });
  }, []);
  const run = useCallback(async (input: Query) => {
    if (current.current || (!input.query?.trim() && !input.image)) return;
    const controller = new AbortController();
    current.current = controller;
    const key = getApiKey();
    setState({ kind: "loading" });
    const ownsRequest = () =>
      mounted.current &&
      current.current === controller &&
      !controller.signal.aborted;
    try {
      const found = await searchMemory(
        input.query,
        input.category,
        input.sourceAgent,
        input.limit,
        input.scope,
        input.image,
        controller.signal,
      );
      if (ownsRequest() && getApiKey() === key)
        setState({ kind: "ready", results: found });
    } catch (error) {
      if (ownsRequest() && getApiKey() === key)
        setState({
          kind: "error",
          message: error instanceof Error ? error.message : "Search failed.",
        });
    } finally {
      if (ownsRequest()) {
        if (getApiKey() !== key) {
          setState({
            kind: "error",
            message:
              "API key changed. Search again with the current credential.",
          });
        }
        current.current = null;
      }
    }
  }, []);
  return {
    results: state.kind === "ready" ? state.results : null,
    pending: state.kind === "loading",
    error: state.kind === "error" ? state.message : "",
    run,
    clear,
  };
}
