// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ConversationsTab } from '../components/tabs/ConversationsTab';
import { ToastProvider } from '../components/ui/Toast';

const list = (title: string) => new Response(JSON.stringify({ conversations: [{ id: title, title, platform: 'claude', summary: '', source_agent: 'user', messages: [], is_vectorized: false, created_at: '2026-01-01' }], total: 1, total_vectorized: 0, page: 1, pages: 1 }));
const mount = () => render(<ToastProvider><ConversationsTab onOpenTranscript={() => {}} /></ToastProvider>);
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('shows a failed list request and retries', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response('{}', { status: 503 })).mockResolvedValueOnce(list('Recovered')));
  mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
  expect(await screen.findByText('Recovered')).toBeTruthy();
});

it('ignores an older list response after a filter changes', async () => {
  let resolve!: (response: Response) => void;
  const old = new Promise<Response>(done => { resolve = done; });
  vi.stubGlobal('fetch', vi.fn().mockReturnValueOnce(old).mockResolvedValueOnce(list('New')));
  mount();
  fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'claude' } });
  await screen.findByText('New');
  await act(async () => resolve(list('Old')));
  expect(screen.queryByText('Old')).toBeNull();
});

it('aborts the list request on unmount', async () => {
  const fetchMock = vi.fn().mockReturnValue(new Promise(() => {}));
  vi.stubGlobal('fetch', fetchMock);
  const view = mount();
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  const signal = fetchMock.mock.calls[0][1].signal as AbortSignal;
  view.unmount();
  expect(signal.aborted).toBe(true);
});
