// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ConversationsTab } from '../components/tabs/ConversationsTab';
import { ToastProvider } from '../components/ui/Toast';

const list = () => new Response(JSON.stringify({conversations: [{id:'1', title:'Example', platform:'claude', summary:'', source_agent:'user', messages:[], created_at:'', is_vectorized:false}], total:1, total_vectorized:0, page:1, pages:1}));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
it('retains a failed import for retry and reports pending indexing', async () => {
  const changed = vi.fn();
  const fetcher = vi.fn().mockResolvedValueOnce(list()).mockResolvedValueOnce(new Response(JSON.stringify({detail:'Bad export'}), {status:400})).mockResolvedValueOnce(new Response(JSON.stringify({success:true, ingested:2, skipped:1, pending_indexing:2, total_processed:3, message:'Imported'}))).mockResolvedValue(list());
  vi.stubGlobal('fetch', fetcher);
  const view = render(<ToastProvider><ConversationsTab onOpenTranscript={() => {}} onMutation={changed}/></ToastProvider>);
  fireEvent.click(screen.getByText('Import Chat History'));
  fireEvent.change(screen.getByLabelText('Import format'), {target:{value:'claude'}});
  const input = view.container.querySelector('input[type=file]');
  if (!input) throw new Error('missing file input');
  fireEvent.change(input, {target:{files:[new File(['{}'], 'export.json', {type:'application/json'})]}});
  expect(await screen.findByText('Error: Bad export')).toBeTruthy();
  fireEvent.click(screen.getByText('Retry export.json'));
  expect(await screen.findByText('Imported 2; skipped 1; 2 pending indexing.')).toBeTruthy();
  expect(changed).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[2][0]).toContain('platform=claude');
});
it('keeps the row and displays a delete error', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(list()).mockResolvedValueOnce(new Response(JSON.stringify({detail:'Delete denied'}), {status:403})));
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<ToastProvider><ConversationsTab onOpenTranscript={() => {}} /></ToastProvider>);
  await screen.findByText('Example');
  fireEvent.click(screen.getByTitle('Delete Transcript from Database'));
  await waitFor(() => expect(screen.getByText('Delete denied')).toBeTruthy());
  expect(screen.getByText('Example')).toBeTruthy();
});
