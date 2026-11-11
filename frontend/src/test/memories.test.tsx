// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoriesTab } from '../components/tabs/MemoriesTab';
import { ToastProvider } from '../components/ui/Toast';

const list = (content: string, page = 1) => new Response(JSON.stringify({ memories: content ? [{ id: content, content, category: 'coding', source_agent: 'gpt' }] : [], total: 11, page, pages: 2 }));
function deferred() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>(done => { resolve = done; });
  return { promise, resolve };
}
function mount() {
  const onMutation = vi.fn();
  render(<ToastProvider><MemoriesTab refreshVersion={0} onMutation={onMutation} onOpenNewModal={() => {}} onOpenEditModal={() => {}} /></ToastProvider>);
  return onMutation;
}
const search = () => screen.getByPlaceholderText(/Filter memory records/);
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it('retries a failed list request', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response('{}', { status: 503 })).mockResolvedValueOnce(list('recovered')));
  mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
  expect(await screen.findByText('recovered')).toBeTruthy();
});

it('debounces search from page two and ignores a late old response', async () => {
  const old = deferred();
  const request = vi.fn((url: string) => {
    const params = new URL(url, 'http://localhost').searchParams;
    if (params.get('page') === '2') return old.promise;
    return Promise.resolve(list(params.get('q') ? 'new result' : 'first'));
  });
  vi.stubGlobal('fetch', request);
  mount();
  await screen.findByText('first');
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
  fireEvent.change(search(), { target: { value: 'needle' } });
  await screen.findByText('new result', {}, { timeout: 1500 });
  expect(screen.getByText('Page 1 of 2')).toBeTruthy();
  await act(async () => old.resolve(list('stale', 2)));
  expect(screen.queryByText('stale')).toBeNull();
  expect(screen.getByText('new result')).toBeTruthy();
});

it('keeps page two after the initial debounce interval', async () => {
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(list(url.includes('page=2') ? 'second' : 'first', url.includes('page=2') ? 2 : 1))));
  mount();
  await screen.findByText('first');
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  await screen.findByText('second');
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 450)); });
  expect(screen.getByText('Page 2 of 2')).toBeTruthy();
});

it('keeps a row on failed delete and preserves filters after success', async () => {
  let deletes = 0;
  const request = vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === 'DELETE') return Promise.resolve(new Response('{}', { status: ++deletes === 1 ? 503 : 200 }));
    return Promise.resolve(list(deletes === 2 ? 'remaining' : 'target'));
  });
  vi.stubGlobal('fetch', request);
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  const mutation = mount();
  await screen.findByText('target');
  fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'coding' } });
  fireEvent.change(screen.getAllByRole('combobox')[1], { target: { value: 'gpt' } });
  fireEvent.change(search(), { target: { value: 'needle' } });
  await waitFor(() => expect(request.mock.calls.some(([url]) => url.includes('q=needle'))).toBe(true), { timeout: 1500 });
  await screen.findByText('target');
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
  expect(await screen.findByText(/Request failed \(503\)/)).toBeTruthy();
  expect(screen.getByText('target')).toBeTruthy();
  expect(mutation).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
  await screen.findByText('remaining');
  expect(mutation).toHaveBeenCalledTimes(1);
  const listCalls = request.mock.calls.filter(([, init]) => !init?.method);
  const last = listCalls[listCalls.length - 1]?.[0] ?? '';
  expect(last).toContain('category=coding');
  expect(last).toContain('source_agent=gpt');
  expect(last).toContain('q=needle');
});

it('recovers from last-row deletion while filters change', async () => {
  const pending = deferred();
  const request = vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === 'DELETE') return pending.promise;
    const params = new URL(url, 'http://localhost').searchParams;
    return Promise.resolve(list(params.get('category') ? 'filtered' : params.get('page') === '2' ? 'last' : 'first', Number(params.get('page'))));
  });
  vi.stubGlobal('fetch', request);
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  const mutation = mount();
  await screen.findByText('first');
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  await screen.findByText('last');
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
  fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'coding' } });
  await screen.findByText('filtered');
  await act(async () => pending.resolve(new Response('{}')));
  expect(screen.getByText('Page 1 of 2')).toBeTruthy();
  expect(screen.getByText('filtered')).toBeTruthy();
  expect(mutation).toHaveBeenCalledTimes(1);
  expect(request.mock.calls.every(([url]) => !url.includes('page=0'))).toBe(true);
});

it('returns to page one after deleting its last page-two row', async () => {
  let deleted = false;
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === 'DELETE') {
      deleted = true;
      return Promise.resolve(new Response('{}'));
    }
    return Promise.resolve(list(url.includes('page=2') ? 'last' : deleted ? 'page one refreshed' : 'first', url.includes('page=2') ? 2 : 1));
  }));
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  const mutation = mount();
  await screen.findByText('first');
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  await screen.findByText('last');
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
  await screen.findByText('page one refreshed');
  expect(screen.getByText('Page 1 of 2')).toBeTruthy();
  expect(mutation).toHaveBeenCalledTimes(1);
});
