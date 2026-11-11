// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoriesTab } from '../components/tabs/MemoriesTab';
import { ToastProvider } from '../components/ui/Toast';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('retries a failed list request at the HTTP boundary', async () => {
  const request = vi.fn().mockResolvedValueOnce(new Response('{}', { status: 503 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ memories: [], total: 0, pages: 1, page: 1 }), { status: 200 }));
  vi.stubGlobal('fetch', request);
  render(<ToastProvider><MemoriesTab refreshVersion={0} onMutation={() => {}} onOpenNewModal={() => {}} onOpenEditModal={() => {}} /></ToastProvider>);
  fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
  expect(await screen.findByText('No memory records match the selected filter criteria')).toBeTruthy();
  expect(request).toHaveBeenCalledTimes(2);
});
