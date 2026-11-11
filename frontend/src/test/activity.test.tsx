/** @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest';
import React from 'react';
import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ActivityTab } from '../components/tabs/ActivityTab';

const event = (id: string) => ({ id, project_id: 'a', writer_id: 'writer', action: 'proposed', target_id: id, revision: 1, status: 'recorded', created_at: '2026-01-01', updated_at: '2026-01-01' });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
test('shows newest first, pages, filters and retains filter on refresh', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => json({ events: [event('new'), event('old')], total: 21 }));
  const view = render(<ActivityTab refreshVersion={0} />);
  expect(await screen.findByText('new')).toBeInTheDocument();
  expect(screen.getAllByRole('listitem')[0]).toHaveTextContent('new');
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  await waitFor(() => expect(fetcher).toHaveBeenLastCalledWith(expect.stringContaining('offset=20'), expect.anything()));
  fireEvent.change(screen.getByLabelText('Project ID'), { target: { value: 'a' } });
  await waitFor(() => expect(fetcher).toHaveBeenLastCalledWith(expect.stringContaining('offset=0&project_id=a'), expect.anything()));
  view.rerender(<ActivityTab refreshVersion={1} />);
  await waitFor(() => expect(fetcher).toHaveBeenLastCalledWith(expect.stringContaining('project_id=a'), expect.anything()));
});
test('shows 401 and retries to empty', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(json({ detail: 'Unauthorized' }, 401)).mockResolvedValueOnce(json({ events: [], total: 0 }));
  render(<ActivityTab refreshVersion={0} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Unauthorized');
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  expect(await screen.findByText('No activity found.')).toBeInTheDocument();
});
test('ignores a late response after filter changes', async () => {
  let finish: (response: Response) => void = () => {};
  vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValue(json({ events: [event('current')], total: 1 }));
  render(<ActivityTab refreshVersion={0} />);
  fireEvent.change(screen.getByLabelText('Project ID'), { target: { value: 'a' } });
  expect(await screen.findByText('current')).toBeInTheDocument();
  finish(json({ events: [event('stale')], total: 1 }));
  await waitFor(() => expect(screen.queryByText('stale')).not.toBeInTheDocument());
});
