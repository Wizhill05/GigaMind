// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { FilesTab } from '../components/tabs/FilesTab';
import { ToastProvider } from '../components/ui/Toast';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); localStorage.clear(); });
const result = (content: string) => new Response(JSON.stringify({results: [{id:'1', source:'file', content, score:0.42, filename:'doc', file_key:'files/doc', page_number:2, chunk_index:0, total_chunks:3, vector_score:0.2, citation:'doc page 2'}]}));
const mount = () => render(<ToastProvider><FilesTab /></ToastProvider>);
const query = () => screen.getByPlaceholderText(/Search concepts/);

it('ignores an older search and displays literal evidence and raw scores', async () => {
  let resolve = (_response: Response) => {};
  const old = new Promise<Response>(r => { resolve = r; });
  let count = 0;
  vi.stubGlobal('fetch', vi.fn((url: string) => url.includes('search_files') ? (++count === 1 ? old : Promise.resolve(result('new evidence'))) : Promise.resolve(new Response(JSON.stringify({files: [], count: 0})))));
  mount(); fireEvent.change(query(), {target:{value:'first'}}); fireEvent.click(screen.getByText('Search Files'));
  fireEvent.change(query(), {target:{value:'second'}}); fireEvent.click(screen.getByText('Search Files'));
  expect(await screen.findByText('new evidence')).toBeInTheDocument();
  await act(async () => resolve(result('old evidence')));
  expect(screen.queryByText('old evidence')).not.toBeInTheDocument();
  expect(screen.getByText('Score: 0.42')).toBeInTheDocument();
  expect(screen.getByText(/files\/doc.*Page 2.*Chunk 1/)).toBeInTheDocument();
});

it.each([503, 413])('shows HTTP %s and retries an empty result', async status => {
  let count = 0;
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(url.includes('search_files') ? (++count === 1 ? new Response('{}', {status}) : new Response('{"results":[]}')) : new Response('{"files":[],"count":0}'))));
  mount(); fireEvent.change(query(), {target:{value:'needle'}}); fireEvent.click(screen.getByText('Search Files'));
  expect(await screen.findByRole('alert')).toHaveTextContent(String(status));
  fireEvent.click(screen.getByText('Retry'));
  expect(await screen.findByText(/No matching file chunks/)).toBeInTheDocument();
  expect(query()).toHaveValue('needle');
});

it('rejects results after credential replacement and retries with the new credential', async () => {
  let resolve = (_response: Response) => {};
  let count = 0;
  const old = new Promise<Response>(r => { resolve = r; });
  vi.stubGlobal('fetch', vi.fn((url: string) => url.includes('search_files') ? (++count === 1 ? old : Promise.resolve(result('fresh'))) : Promise.resolve(new Response('{"files":[],"count":0}'))));
  localStorage.setItem('gigamind_master_key', 'old');
  mount(); fireEvent.change(query(), {target:{value:'needle'}}); fireEvent.click(screen.getByText('Search Files'));
  localStorage.setItem('gigamind_master_key', 'new');
  await act(async () => resolve(result('stale')));
  expect(screen.queryByText('stale')).not.toBeInTheDocument();
  const alert = screen.getByText(/Search failed: Credentials changed/);
  fireEvent.click(within(alert).getByText('Retry'));
  expect(await screen.findByText('fresh')).toBeInTheDocument();
});

it('aborts a search on unmount', () => {
  let signal: AbortSignal | null | undefined;
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    if (url.includes('search_files')) { signal = init?.signal; return new Promise<Response>(() => {}); }
    return Promise.resolve(new Response('{"files":[],"count":0}'));
  }));
  const view = mount(); fireEvent.change(query(), {target:{value:'needle'}}); fireEvent.click(screen.getByText('Search Files'));
  view.unmount(); expect(signal?.aborted).toBe(true);
});

it('reruns an active search on refresh and ignores the prior response', async () => {
  let resolve = (_response: Response) => {};
  let count = 0;
  const old = new Promise<Response>(r => { resolve = r; });
  vi.stubGlobal('fetch', vi.fn((url: string) => url.includes('search_files') ? (++count === 1 ? old : Promise.resolve(result('refreshed'))) : Promise.resolve(new Response('{"files":[],"count":0}'))));
  const view = render(<ToastProvider><FilesTab refreshVersion={0} /></ToastProvider>);
  fireEvent.change(query(), {target:{value:'needle'}}); fireEvent.click(screen.getByText('Search Files'));
  view.rerender(<ToastProvider><FilesTab refreshVersion={1} /></ToastProvider>);
  expect(await screen.findByText('refreshed')).toBeInTheDocument();
  await act(async () => resolve(result('stale')));
  expect(screen.queryByText('stale')).not.toBeInTheDocument();
});

it('replaces an in-flight text search with an image query', async () => {
  let resolve = (_response: Response) => {};
  const old = new Promise<Response>(r => { resolve = r; });
  let count = 0;
  const fetcher = vi.fn((url: string) => url.includes('search_files') ? (++count === 1 ? old : Promise.resolve(result('image evidence'))) : Promise.resolve(new Response('{"files":[],"count":0}')));
  vi.stubGlobal('fetch', fetcher);
  mount(); fireEvent.change(query(), {target:{value:'needle'}}); fireEvent.click(screen.getByText('Search Files'));
  const input = document.querySelector('input[accept="image/*"]');
  if (!input) throw new Error('Image input missing');
  fireEvent.change(input, {target:{files:[new File(['image'], 'query.png', {type:'image/png'})]}});
  await screen.findByText(/Query Image:/);
  fireEvent.click(screen.getByText('Search Files'));
  expect(await screen.findByText('image evidence')).toBeInTheDocument();
  await act(async () => resolve(result('old text evidence')));
  expect(screen.queryByText('old text evidence')).not.toBeInTheDocument();
});

it('reruns search after an accepted deletion and ignores the pre-deletion response', async () => {
  let resolve = (_response: Response) => {};
  let count = 0;
  const old = new Promise<Response>(r => { resolve = r; });
  const file = {id:'1', key:'files/doc', filename:'doc', size_bytes:1, extracted_text_length:0, created_at:'2026-01-01', total_chunks:1, indexing_status:'indexed'};
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    if (url.includes('search_files')) return ++count === 1 ? old : Promise.resolve(new Response('{"results":[]}'));
    if (url.includes('/delete')) return Promise.resolve(new Response('{"key":"files/doc","job_id":"job","state":"queued","cleanup":"pending"}', {status:202}));
    return Promise.resolve(new Response(JSON.stringify({files:[file],count:1})));
  }));
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  mount(); await screen.findByText('doc');
  fireEvent.change(query(), {target:{value:'needle'}}); fireEvent.click(screen.getByText('Search Files'));
  fireEvent.click(screen.getByTitle('Delete File from R2'));
  expect(await screen.findByText(/No matching file chunks/)).toBeInTheDocument();
  await act(async () => resolve(result('deleted evidence')));
  expect(screen.queryByText('deleted evidence')).not.toBeInTheDocument();
});
