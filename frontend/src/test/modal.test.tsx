// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryModal } from '../components/modals/MemoryModal';
import { RuleModal } from '../components/modals/RuleModal';

afterEach(() => { cleanup(); vi.useRealTimers(); });
it.each(['memory', 'rule'])('%s keeps draft after failure and closes after retry', async kind => {
  const close = vi.fn();
  const save = vi.fn().mockRejectedValueOnce(new Error('Save failed')).mockResolvedValueOnce(undefined);
  render(kind === 'memory' ? <MemoryModal isOpen onClose={close} onSave={save} /> : <RuleModal isOpen onClose={close} onSave={save} />);
  const first = screen.getByPlaceholderText(kind === 'memory' ? 'Enter memory statement or factual context...' : 'e.g. primary_programming_language');
  fireEvent.change(first, { target: { value: 'draft' } });
  if (kind === 'rule') fireEvent.change(screen.getByPlaceholderText('e.g. Python / TypeScript with strict typing'), { target: { value: 'value' } });
  fireEvent.click(screen.getByRole('button', { name: kind === 'memory' ? 'Save Memory' : 'Save Rule' }));
  await screen.findByRole('alert');
  expect((first as HTMLInputElement).value).toBe('draft');
  fireEvent.click(screen.getByRole('button', { name: kind === 'memory' ? 'Save Memory' : 'Save Rule' }));
  await waitFor(() => expect(close).toHaveBeenCalledTimes(1));
});
it.each(['memory', 'rule'])('%s cannot close with Escape during save', async kind => {
  vi.useFakeTimers();
  const close = vi.fn();
  const save = vi.fn(() => new Promise<void>(() => {}));
  render(kind === 'memory' ? <MemoryModal isOpen onClose={close} onSave={save} /> : <RuleModal isOpen onClose={close} onSave={save} />);
  fireEvent.change(screen.getByPlaceholderText(kind === 'memory' ? 'Enter memory statement or factual context...' : 'e.g. primary_programming_language'), { target: { value: 'draft' } });
  if (kind === 'rule') fireEvent.change(screen.getByPlaceholderText('e.g. Python / TypeScript with strict typing'), { target: { value: 'value' } });
  fireEvent.click(screen.getByRole('button', { name: kind === 'memory' ? 'Save Memory' : 'Save Rule' }));
  fireEvent.keyDown(window, { key: 'Escape' });
  act(() => { vi.advanceTimersByTime(250); });
  expect(close).not.toHaveBeenCalled();
});

it.each(['memory', 'rule'])('%s traps focus and restores it on close', kind => {
  const opener = document.createElement('button');
  document.body.appendChild(opener);
  opener.focus();
  const modal = (open: boolean) => kind === 'memory'
    ? <MemoryModal isOpen={open} onClose={() => {}} onSave={async () => {}} />
    : <RuleModal isOpen={open} onClose={() => {}} onSave={async () => {}} />;
  const { rerender } = render(modal(true));
  const first = screen.getByRole('button', { name: 'Close dialog' });
  const last = screen.getByRole('button', { name: kind === 'memory' ? 'Save Memory' : 'Save Rule' });
  last.focus();
  fireEvent.keyDown(document, { key: 'Tab' });
  expect(document.activeElement).toBe(first);
  fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
  expect(document.activeElement).toBe(last);
  rerender(modal(false));
  expect(document.activeElement).toBe(opener);
  opener.remove();
});
