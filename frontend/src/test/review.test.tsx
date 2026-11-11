/** @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import React from 'react';
import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ReviewTab } from '../components/tabs/ReviewTab';

const proposal = { id: 'p1', content: 'Original', revision: 2, status: 'proposed', writer_id: 'agent', project_id: 'project', evidence: [{ source_type: 'chat', source_id: 'source', quote: 'Exact quote' }], conflicts: ['m1'] };
const memory = { id: 'm1', content: 'Old fact', revision: 3, status: 'accepted', writer_id: 'admin', project_id: 'project' };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
test('shows evidence and requires explicit conflict consent before approving edited text', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    if (String(input).includes('/resolve')) return json({ proposal: { ...proposal, status: 'accepted' }, memory });
    if (String(input).includes('/memories/')) return json({ memory });
    return json({ proposals: [proposal], total: 1 });
  });
  const mutated = vi.fn(); render(<ReviewTab refreshVersion={0} onMutation={mutated} />);
  fireEvent.click(await screen.findByRole('button', { name: /Original/ }));
  expect(screen.getByText('Exact quote')).toBeTruthy();
  expect(await screen.findByText(/Old fact/)).toBeTruthy();
  const approve = screen.getByRole('button', { name: 'Approve' }); expect(approve).toHaveProperty('disabled', true);
  fireEvent.change(screen.getByLabelText('Approval text'), { target: { value: 'Edited fact' } });
  fireEvent.click(screen.getByRole('checkbox')); fireEvent.click(approve);
  await waitFor(() => expect(mutated).toHaveBeenCalled());
  const call = fetcher.mock.calls.find(([url]) => String(url).includes('/resolve'));
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ action: 'approve', expected_revision: 2, content: 'Edited fact', supersedes: ['m1'] });
});
test('stale approval keeps edited text until explicit reload', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => String(input).includes('/resolve') ? json({ detail: 'Stale proposal revision' }, 409) : String(input).includes('/memories/') ? json({ memory }) : json({ proposals: [{ ...proposal, conflicts: [] }], total: 1 }));
  render(<ReviewTab refreshVersion={0} onMutation={() => {}} />); fireEvent.click(await screen.findByRole('button', { name: /Original/ }));
  fireEvent.change(screen.getByLabelText('Approval text'), { target: { value: 'Keep this' } }); fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Stale proposal revision');
  expect(screen.getByLabelText('Approval text')).toHaveValue('Keep this');
  fireEvent.click(screen.getByRole('button', { name: /Reload current proposal/ }));
  await waitFor(() => expect(screen.queryByRole('button', { name: /Reload current proposal/ })).toBeNull());
  expect(screen.getByLabelText('Approval text')).toHaveValue('Keep this');
});
test('retries failed list and shows empty state', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(json({ detail: 'Unavailable' }, 503)).mockResolvedValueOnce(json({ proposals: [], total: 0 }));
  render(<ReviewTab refreshVersion={0} onMutation={() => {}} />); expect(await screen.findByRole('alert')).toHaveTextContent('Unavailable'); fireEvent.click(screen.getByRole('button', { name: 'Retry' })); expect(await screen.findByText('No proposals on this page.')).toBeTruthy();
});
test('rejects using the displayed revision', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async input => String(input).includes('/resolve') ? json({ proposal: { ...proposal, status: 'rejected' } }) : json({ proposals: [{ ...proposal, conflicts: [] }], total: 1 }));
  render(<ReviewTab refreshVersion={0} onMutation={() => {}} />); fireEvent.click(await screen.findByRole('button', { name: /Original/ })); fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url).includes('/resolve'))).toBe(true));
  const call = fetcher.mock.calls.find(([url]) => String(url).includes('/resolve')); expect(JSON.parse(String(call?.[1]?.body))).toEqual({ action: 'reject', expected_revision: 2, supersedes: [] });
});
test('restores a revision with the current memory revision and reports stale errors', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const url = String(input);
    if (url.endsWith('/restore')) return json({ detail: 'Stale memory revision' }, 409);
    if (url.endsWith('/history')) return json({ revisions: [{ revision: 1, status: 'accepted', writer_id: 'admin', created_at: 'today', snapshot: { ...memory, revision: 1, content: 'Earlier' } }] });
    if (url.includes('/memories/')) return json({ memory });
    return json({ proposals: [{ ...proposal, status: 'accepted', accepted_memory_id: 'm1' }], total: 1 });
  });
  render(<ReviewTab refreshVersion={0} onMutation={() => {}} />); fireEvent.click(await screen.findByRole('button', { name: /Original/ })); fireEvent.click(screen.getByRole('button', { name: 'Open revision history' })); fireEvent.click(await screen.findByRole('button', { name: 'Restore revision 1' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Stale memory revision');
  const call = fetcher.mock.calls.find(([url]) => String(url).endsWith('/restore')); expect(JSON.parse(String(call?.[1]?.body))).toEqual({ revision: 1, expected_revision: 3 });
});
