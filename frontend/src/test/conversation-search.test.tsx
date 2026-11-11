// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ConversationsTab } from '../components/tabs/ConversationsTab';
import { ToastProvider } from '../components/ui/Toast';
import { setApiKey } from '../api';

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {status});
const list = () => json({conversations: [], total: 0, total_vectorized: 0, page: 1, pages: 1});
const result = (title: string) => ({id:title, title, platform:'claude', summary:'', source_agent:'user', created_at:'', messages:[{role:'tool', content:'literal needle', id:'m1', created_at:123}], messages_count:1, score:0.75, lexical_score:1, retrieval_method:'lexical', evidence:[{role:'tool', index:0, text:'literal needle', id:'m1', created_at:123}]});
const search = (title?: string) => json({query:'needle', platform:null, count:title ? 1 : 0, results:title ? [result(title)] : []});
const mount = () => render(<ToastProvider><ConversationsTab onOpenTranscript={() => {}} /></ToastProvider>);
const submit = (query: string) => { fireEvent.change(screen.getByPlaceholderText(/Search conversation sessions/), {target:{value:query}}); fireEvent.click(screen.getByText('Search Transcripts')); };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); localStorage.clear(); });

it('ignores overlapping searches and filter changes, and aborts on unmount', async () => {
  const pending: {resolve: (r: Response) => void; signal: AbortSignal}[] = [];
  vi.stubGlobal('fetch', vi.fn((url: string, init: RequestInit) => url.includes('/search') ? new Promise<Response>(resolve => pending.push({resolve, signal: init.signal!})) : Promise.resolve(list())));
  const view = mount(); submit('old'); await waitFor(() => expect(pending).toHaveLength(1));
  submit('new'); await waitFor(() => expect(pending).toHaveLength(2));
  await act(async () => pending[1].resolve(search('New'))); expect(await screen.findByText('New')).toBeTruthy();
  await act(async () => pending[0].resolve(search('Old'))); expect(screen.queryByText('Old')).toBeNull();
  fireEvent.change(screen.getAllByRole('combobox')[0], {target:{value:'claude'}}); await waitFor(() => expect(pending).toHaveLength(3));
  expect(screen.queryByText('New')).toBeNull(); view.unmount(); expect(pending[2].signal.aborted).toBe(true);
});

it('rejects an old credential response', async () => {
  let resolve!: (r: Response) => void;
  vi.stubGlobal('fetch', vi.fn((url: string) => url.includes('/search') ? new Promise<Response>(r => {resolve = r;}) : Promise.resolve(list())));
  setApiKey('old'); mount(); submit('needle'); await waitFor(() => expect(resolve).toBeDefined()); setApiKey('new');
  await act(async () => resolve(search('Secret'))); expect(screen.queryByText('Secret')).toBeNull();
});

it('shows errors and retries, distinguishes empty results and renders literal evidence', async () => {
  let calls = 0;
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(url.includes('/search') ? (++calls === 1 ? json({detail:'Unavailable'}, 503) : calls === 2 ? search() : search('Match')) : list())));
  mount(); submit('needle'); expect((await screen.findByRole('alert')).textContent).toContain('Unavailable');
  fireEvent.click(screen.getByText('Retry search')); expect(await screen.findByText(/No conversation transcripts matched/)).toBeTruthy();
  fireEvent.click(screen.getByText('Search Transcripts')); expect(await screen.findByText('tool: literal needle')).toBeTruthy(); expect(screen.getByText(/lexical · score/)).toBeTruthy();
});

it('invalidates a standalone search after deletion and refetches', async () => {
  let calls = 0;
  vi.stubGlobal('fetch', vi.fn((url: string, init: RequestInit) => Promise.resolve(url.includes('/search') ? (++calls === 1 ? search('Delete me') : search()) : init?.method === 'DELETE' ? json({success:true, id:'Delete me', message:'Deleted'}) : list())));
  vi.spyOn(window, 'confirm').mockReturnValue(true); mount(); submit('needle'); await screen.findByText('Delete me');
  fireEvent.click(screen.getByTitle('Delete Transcript from Database'));
  await screen.findByText(/No conversation transcripts matched/); expect(screen.queryByText('Delete me')).toBeNull(); expect(calls).toBe(2);
});
