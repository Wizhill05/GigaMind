// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Header } from '../components/Header';
import { ToastProvider } from '../components/ui/Toast';
import { setApiKey } from '../api';

const ok = (name: string) => new Response(JSON.stringify({ success: true, file: { key: `files/${name}`, filename: name } }), { status: 202 });
const fail = () => new Response(JSON.stringify({ detail: { message: 'Upload outcome unknown', key: 'files/recover', job_id: 'job-1' } }), { status: 503 });
const file = (name: string) => new File(['data'], name);
function mount() {
  const refresh = vi.fn();
  const view = render(<ToastProvider><Header onRefresh={refresh} isAuthenticated onOpenNewMemoryModal={() => {}} onOpenCommandPalette={() => {}} /></ToastProvider>);
  const input = view.container.querySelector('input[type=file]');
  if (!(input instanceof HTMLInputElement)) throw new Error('missing upload input');
  return { ...view, input, refresh };
}
beforeEach(() => setApiKey('first'));
afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

it('rejects duplicate batches, sequences files and refreshes once for mixed outcomes', async () => {
  let resolve!: (response: Response) => void;
  const pending = new Promise<Response>(r => { resolve = r; });
  const fetchMock = vi.fn((url: string) => {
    expect(url).toBe('/api/v1/files/upload?prefix=files');
    return fetchMock.mock.calls.length === 1 ? pending : Promise.resolve(fail());
  });
  vi.stubGlobal('fetch', fetchMock);
  const { input, refresh } = mount();
  fireEvent.change(input, { target: { files: [file('one'), file('two')] } });
  fireEvent.change(input, { target: { files: [file('duplicate')] } });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(input.disabled).toBe(true);
  resolve(ok('one'));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  expect(screen.getByText(/Uploaded one & queued vector indexing/)).toBeTruthy();
  expect(screen.getByText(/Recovery reference: files\/recover, job job-1/)).toBeTruthy();
});

it('allows reselection after failure, without refreshing for an all-failed batch', async () => {
  const fetchMock = vi.fn((url: string) => {
    expect(url).toBe('/api/v1/files/upload?prefix=files');
    return Promise.resolve(fetchMock.mock.calls.length === 1 ? fail() : ok('same'));
  });
  vi.stubGlobal('fetch', fetchMock);
  const { input, refresh } = mount();
  const same = file('same');
  fireEvent.change(input, { target: { files: [same] } });
  await screen.findByText(/Recovery reference: files\/recover, job job-1/);
  await waitFor(() => expect(input.disabled).toBe(false));
  expect(refresh).not.toHaveBeenCalled();
  expect(input.value).toBe('');
  fireEvent.change(input, { target: { files: [same] } });
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it.each(['credential', 'unmount'])('stops after %s changes during an upload', async mode => {
  let resolve!: (response: Response) => void;
  const fetchMock = vi.fn((url: string) => {
    expect(url).toBe('/api/v1/files/upload?prefix=files');
    return new Promise<Response>(r => { resolve = r; });
  });
  vi.stubGlobal('fetch', fetchMock);
  const { input, refresh, unmount } = mount();
  fireEvent.change(input, { target: { files: [file('one'), file('two')] } });
  if (mode === 'credential') setApiKey('second'); else unmount();
  resolve(ok('one'));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  await new Promise(r => setTimeout(r, 0));
  expect(refresh).not.toHaveBeenCalled();
  expect(screen.queryByText(/Uploaded one/)).toBeNull();
});
