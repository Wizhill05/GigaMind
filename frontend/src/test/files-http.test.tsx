// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { FilesTab } from '../components/tabs/FilesTab';
import { MemoriesTab } from '../components/tabs/MemoriesTab';
import { ToastProvider } from '../components/ui/Toast';

const file = { id: '1', key: 'a/b', filename: 'example.txt', size_bytes: 1, extracted_text_length: 0, total_chunks: 0, indexing_status: 'pending', created_at: '2026-01-01' };
const list = () => new Response(JSON.stringify({ files: [file], count: 1 }));
const mount = () => render(<ToastProvider><FilesTab /></ToastProvider>);
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it('shows a list error and retries', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response('{}', { status: 503 })).mockResolvedValueOnce(list()));
  mount();
  fireEvent.click(await screen.findByText('Retry'));
  expect(await screen.findByText('example.txt')).toBeTruthy();
});

it('preserves a file on delete failure and guards a pending request', async () => {
  let resolve!: (response: Response) => void;
  const pending = new Promise<Response>(r => { resolve = r; });
  const fetcher = vi.fn((url: string) => url.includes('/delete') ? pending : Promise.resolve(list()));
  vi.stubGlobal('fetch', fetcher); vi.spyOn(window, 'confirm').mockReturnValue(true);
  mount(); await screen.findByText('example.txt');
  const button = screen.getByTitle('Delete File from R2');
  fireEvent.click(button); fireEvent.click(button);
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/delete'))).toHaveLength(1);
  resolve(new Response('{}', { status: 409 }));
  await screen.findByText(/409/);
  expect(screen.getByText('example.txt')).toBeTruthy();
});

it('reports pending cleanup and queued indexing with job references', async () => {
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(url.includes('/delete') ? new Response(JSON.stringify({key:'a/b',job_id:'del-job',state:'queued',cleanup:'pending'}), {status:202}) : url.includes('/reindex') ? new Response(JSON.stringify({key:'a/b',job_id:'index-job',state:'queued'}), {status:202}) : list())));
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  mount(); await screen.findByText('example.txt');
  fireEvent.click(screen.getByTitle('Re-Index Vectors'));
  await screen.findByText(/Indexing queued.*index-job/);
  await waitFor(() => expect(screen.getByTitle('Re-Index Vectors').hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByTitle('Delete File from R2'));
  expect(await screen.findByText(/Cleanup pending.*del-job/)).toBeTruthy();
});

it('shows and retries file list errors in Memories', async () => {
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(url.includes('memories?') ? new Response(JSON.stringify({memories:[], pages:1,total:0})) : new Response('{}', {status:503}))));
  render(<ToastProvider><MemoriesTab refreshVersion={0} onMutation={() => {}} onOpenNewModal={() => {}} onOpenEditModal={() => {}} /></ToastProvider>);
  fireEvent.click(screen.getByText(/Indexed Files/));
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.getByText('Retry')).toBeTruthy();
});

it('ignores chunk responses after unmount', async () => {
  let resolve!: (response: Response) => void;
  const pending = new Promise<Response>(r => { resolve = r; });
  vi.stubGlobal('fetch', vi.fn((url: string) => url.includes('/chunks?') ? pending : Promise.resolve(list())));
  const view = mount(); await screen.findByText('example.txt');
  fireEvent.click(screen.getByTitle('Inspect Semantic Chunks'));
  view.unmount();
  resolve(new Response(JSON.stringify({key:'a/b', chunks:[], count:0})));
  await pending;
  expect(screen.queryByText('example.txt')).toBeNull();
});
