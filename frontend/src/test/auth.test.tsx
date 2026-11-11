// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App } from '../App';

const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function deferred() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>(done => { resolve = done; });
  return { promise, resolve };
}
const stats = { total_memories: 0, total_storage_files: 0, total_profile_rules: 0, total_chat_logs: 0 };
afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

it('keeps protected content unmounted and reports invalid credentials', async () => {
  const request = vi.fn().mockResolvedValue(response({}, 401));
  vi.stubGlobal('fetch', request);
  render(<App />);
  expect(request).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('Master API Key'), { target: { value: 'bad' } });
  fireEvent.click(screen.getByRole('button', { name: 'Authorize Connection' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Invalid master key');
  expect(request).toHaveBeenCalledTimes(1);
});

it('reports a connection failure and retries successfully', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new TypeError('offline')).mockResolvedValue(response(stats)));
  render(<App />);
  fireEvent.change(screen.getByLabelText('Master API Key'), { target: { value: 'key' } });
  fireEvent.click(screen.getByRole('button', { name: 'Authorize Connection' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Network error');
  fireEvent.click(screen.getByRole('button', { name: 'Authorize Connection' }));
  expect(await screen.findByRole('button', { name: 'Connected' })).toBeTruthy();
});

it('blocks editing and resubmitting while authentication is pending', async () => {
  const pending = deferred();
  const request = vi.fn().mockReturnValue(pending.promise);
  vi.stubGlobal('fetch', request);
  render(<App />);
  const input = screen.getByLabelText('Master API Key');
  fireEvent.change(input, { target: { value: 'first' } });
  fireEvent.submit(input.closest('form')!);
  expect(input.hasAttribute('disabled')).toBe(true);
  fireEvent.change(input, { target: { value: 'second' } });
  fireEvent.submit(input.closest('form')!);
  expect(localStorage.getItem('gigamind_master_key')).toBe('first');
  expect(request).toHaveBeenCalledTimes(1);
  await act(async () => pending.resolve(response({}, 401)));
});

it('keeps the newer rejection when an older refresh succeeds late', async () => {
  const old = deferred();
  const newer = deferred();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(stats)).mockReturnValueOnce(old.promise).mockReturnValueOnce(newer.promise));
  localStorage.setItem('gigamind_master_key', 'key');
  render(<App />);
  fireEvent.click(await screen.findByTitle('Refresh telemetry'));
  fireEvent.click(screen.getByTitle('Refresh telemetry'));
  await act(async () => newer.resolve(response({}, 401)));
  expect((await screen.findByRole('alert')).textContent).toContain('Invalid master key');
  await act(async () => old.resolve(response(stats)));
  expect(screen.getByRole('alert').textContent).toContain('Invalid master key');
  expect(screen.queryByRole('button', { name: 'Connected' })).toBeNull();
});

it('aborts an in-flight authentication on unmount', async () => {
  localStorage.setItem('gigamind_master_key', 'key');
  let signal: AbortSignal | undefined;
  vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => {
    signal = init.signal ?? undefined;
    return new Promise<Response>(() => {});
  }));
  const view = render(<App />);
  await waitFor(() => expect(signal).toBeDefined());
  view.unmount();
  expect(signal?.aborted).toBe(true);
});
