import { useEffect, useRef, useState } from 'react';
import { getApiKey } from './api';
export function useConversationMutation() {
  const locked = useRef(false);
  const mounted = useRef(true);
  const [busy, setBusy] = useState(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; locked.current = false; }; }, []);
  const run = async (action: (valid: () => boolean) => Promise<void>, onError: (error: unknown) => void) => {
    if (locked.current) return;
    locked.current = true; setBusy(true);
    const key = getApiKey();
    const valid = () => mounted.current && getApiKey() === key;
    try { await action(valid); } catch (error) { if (valid()) onError(error); }
    finally { locked.current = false; if (mounted.current) setBusy(false); }
  };
  return { busy, locked, run };
}
export type ConversationMutation = ReturnType<typeof useConversationMutation>;
