import React, { useEffect, useRef, useState } from 'react';
import { ApiError } from '../../api';
import { Handoff, Issue, listHandoffs, listIssues, resolveIssue } from '../../coordinationApi';

export const CoordinationTab: React.FC<{ refreshVersion: number }> = ({ refreshVersion }) => {
  const [project, setProject] = useState('');
  const [offset, setOffset] = useState(0);
  const [reload, setReload] = useState(0);
  const [handoffs, setHandoffs] = useState<Handoff[]>([]);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [totals, setTotals] = useState({ handoffs: 0, issues: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [target, setTarget] = useState<Issue | null>(null);
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const generation = useRef(0);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; generation.current++; }, []);
  useEffect(() => {
    if (lock.current) return;
    const controller = new AbortController();
    const current = ++generation.current;
    setLoading(true); setError(''); setHandoffs([]); setIssues([]); setTotals({ handoffs: 0, issues: 0 });
    Promise.all([listHandoffs(project, offset, controller.signal), listIssues(project, offset, controller.signal)]).then(([h, i]) => {
      if (controller.signal.aborted || current !== generation.current || lock.current) return;
      setHandoffs(h.handoffs); setIssues(i.issues); setTotals({ handoffs: h.total, issues: i.total }); setLoading(false);
    }).catch((e: unknown) => {
      if (controller.signal.aborted || current !== generation.current || lock.current) return;
      setError(e instanceof Error ? e.message : 'Unable to load coordination records'); setLoading(false);
    });
    return () => controller.abort();
  }, [project, offset, reload, refreshVersion]);
  const changeScope = (value: string) => { if (lock.current) return; setTarget(null); setConflict(false); setProject(value); setOffset(0); };
  const act = async (status: 'resolved' | 'dismissed') => {
    if (lock.current || !target || conflict || !window.confirm(`${status === 'resolved' ? 'Resolve' : 'Dismiss'} issue ${target.id}?`)) return;
    lock.current = true; generation.current++; setBusy(true); setError('');
    try {
      await resolveIssue(target, status);
      if (!mounted.current) return;
      setTarget(null); setReload(v => v + 1);
    } catch (e) {
      if (!mounted.current) return;
      setLoading(false);
      setError(e instanceof Error ? e.message : 'Resolution failed');
      if (e instanceof ApiError && e.status === 409) setConflict(true);
    } finally { lock.current = false; if (mounted.current) setBusy(false); }
  };
  const reloadConflict = () => {
    if (lock.current || !target) return;
    lock.current = true; setBusy(true); setError('');
    const controller = new AbortController();
    listIssues(project, offset, controller.signal).then(result => {
      if (!mounted.current) return;
      setIssues(result.issues); setTotals(t => ({ ...t, issues: result.total }));
      const current = result.issues.find(i => i.id === target.id);
      if (current) { setTarget(current); setConflict(false); } else setError('Issue is no longer on this page. Change scope or page to find it.');
    }).catch((e: unknown) => { if (mounted.current) setError(e instanceof Error ? e.message : 'Reload failed'); }).finally(() => { lock.current = false; if (mounted.current) setBusy(false); });
  };
  const button = 'border border-[#444] px-3 py-2 text-xs disabled:opacity-40 hover:border-[#ff6b00]';
  return <section className="space-y-6 text-sm">
    <div><h1 className="text-xl font-semibold">Coordination</h1><p className="text-[#8a8f9e]">Handoffs are authenticated agent reports, not approved facts. Reported outcomes are claims.</p></div>
    <label className="block">Project ID (blank for global admin records) <input aria-label="Project ID" className="ml-2 bg-[#1c1c1c] border border-[#444] p-2" value={project} disabled={busy} onChange={e => changeScope(e.target.value)} /></label>
    {error && <div role="alert" className="text-red-400">{error} {!conflict && !target && <button className={button} onClick={() => setReload(v => v + 1)}>Retry</button>}</div>}
    {loading && <p>Loading coordination records…</p>}
    <div className="space-y-3"><h2 className="text-lg">Authenticated agent handoff reports ({totals.handoffs})</h2>{handoffs.map(h => <article key={h.id} className="border border-[#333] bg-[#141414] p-4 space-y-2"><h3 className="font-semibold">{h.task_name}</h3><p>{h.summary}</p><p className="text-[#8a8f9e]">Writer: {h.writer_id} · Project: {h.project_id ?? 'Global'} · {h.created_at} · Status: {h.status}</p>{([['Reported outcomes', h.verified_outcomes], ['Unresolved', h.unresolved], ['Next actions', h.next_actions]] as const).map(([label, items]) => <div key={label}><strong>{label}</strong><ul className="list-disc ml-5">{items.map((item, index) => <li key={index}>{item}</li>)}</ul></div>)}</article>)}</div>
    <div className="space-y-3"><h2 className="text-lg">Memory issues ({totals.issues})</h2>{issues.map(i => <article key={i.id} className="border border-[#333] bg-[#141414] p-4 space-y-2"><p>Memory ID: {i.memory_id} · Authenticated reporter: {i.writer_id}</p><p>{i.reason}</p><p>Status: {i.status} · Revision: {i.revision} · Project: {i.project_id ?? 'Global'}</p><button className={button} disabled={busy || i.status !== 'open'} onClick={() => { if (!lock.current) { setTarget(i); setConflict(false); setError(''); } }}>Select issue {i.id}</button></article>)}</div>
    {target && <div className="border border-[#ff6b00] p-4 space-y-2"><p>Selected issue: {target.id} · Revision: {target.revision} · {target.status}</p>{conflict && <p role="status">This issue changed. Reload its current revision before taking action.</p>}<div className="flex gap-2"><button className={button} disabled={busy || conflict || target.status !== 'open'} onClick={() => void act('resolved')}>Resolve</button><button className={button} disabled={busy || conflict || target.status !== 'open'} onClick={() => void act('dismissed')}>Dismiss</button>{conflict && <button className={button} disabled={busy} onClick={reloadConflict}>Reload issue</button>}</div></div>}
    <div className="flex gap-3 items-center"><button className={button} disabled={busy || offset === 0} onClick={() => { setTarget(null); setConflict(false); setOffset(Math.max(0, offset - 20)); }}>Previous</button><span>Offset {offset}</span><button className={button} disabled={busy || offset + 20 >= Math.max(totals.handoffs, totals.issues)} onClick={() => { setTarget(null); setConflict(false); setOffset(offset + 20); }}>Next</button></div>
  </section>;
};
