// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { ApiError, fetchMemories } from '../api';
afterEach(() => vi.unstubAllGlobals());
it('reports structured validation details', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: [{ msg: 'Invalid query' }] }), { status: 422 })));
  await expect(fetchMemories()).rejects.toMatchObject({ name: 'ApiError', status: 422, message: 'Invalid query' } satisfies Partial<ApiError>);
});
it('preserves cancellation and sends the search query', async () => {
  const abort = new DOMException('cancelled', 'AbortError');
  const fetchMock = vi.fn().mockRejectedValue(abort);
  vi.stubGlobal('fetch', fetchMock);
  await expect(fetchMemories(1, 10, undefined, undefined, 'hello')).rejects.toBe(abort);
  expect(fetchMock.mock.calls[0][0]).toContain('q=hello');
});
