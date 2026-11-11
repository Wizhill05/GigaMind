// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ConversationsTab } from '../components/tabs/ConversationsTab';
import { ToastProvider } from '../components/ui/Toast';
import { fetchConversations } from '../api';

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
  let resolve: (response: Response) => void = () => {};
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
  const signal = fetchMock.mock.calls[0][1].signal;
  view.unmount();
  expect(signal.aborted).toBe(true);
});

it('preserves imported tool and developer roles and message provenance', async () => {
  const response = await list('Imported').json();
  const messages = [
    { role: 'tool', content: 'Tool output', id: 'tool-1', created_at: 123 },
    { role: 'developer', content: 'Source instruction', id: 'dev-1', created_at: '2026-01-01' },
    { role: 'unknown', content: 'Unattributed source' },
  ];
  response.conversations[0].messages = messages;
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(response))));
  expect((await fetchConversations()).conversations[0]?.messages).toEqual(messages);
});

it('rejects malformed list counts', async () => {
  const response = await list('Malformed').json();
  response.total = -1;
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(response))));
  await expect(fetchConversations()).rejects.toThrow();
});
