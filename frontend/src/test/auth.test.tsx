// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App } from '../App';

afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

it('keeps protected content unmounted and reports invalid credentials', async () => {
  const request = vi.fn().mockResolvedValue(new Response('{}', { status: 401 }));
  vi.stubGlobal('fetch', request);
  render(<App />);
  expect(request).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('Master API Key'), { target: { value: 'bad' } });
  fireEvent.click(screen.getByRole('button', { name: 'Authorize Connection' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Invalid master key');
  expect(request).toHaveBeenCalledTimes(1);
  expect(request.mock.calls[0][0]).toBe('/api/v1/stats');
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
