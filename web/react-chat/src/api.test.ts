import {afterEach, describe, expect, test, vi} from 'vitest';
import {ChatApi} from './api.ts';

afterEach(() => vi.unstubAllGlobals());

describe('ChatApi', () => {
test('bootstrap and writes use CSRF without persisting or retrying content', async () => {
  const calls: {path: string; options?: RequestInit}[] = [];
  vi.stubGlobal('fetch', vi.fn(async (path, options) => {
    calls.push({path: String(path), options});
    return new Response(JSON.stringify(calls.length === 1 ? {csrf:'synthetic'} : {error:'chat_busy'}), {status: calls.length === 1 ? 200 : 409});
  }));
  const api = new ChatApi(); await api.bootstrap();
  await expect(api.request('/api/chats/test/messages', 'POST', {text:'合成输入'})).rejects.toThrow(/chat_busy/);
  expect(calls).toHaveLength(2);
  expect((calls[1].options?.headers as Record<string,string>)['X-Console-CSRF']).toBe('synthetic');
  expect(calls[1].options?.credentials).toBe('same-origin');
});

test('GET recovery does not replay a write', async () => {
  vi.stubGlobal('fetch', vi.fn(async (_path, options) => {
    expect(options?.method).toBe('GET'); expect(options?.body).toBeUndefined();
    return new Response(JSON.stringify({pending: false, turns: []}));
  }));
  await expect(new ChatApi().request('/api/chats/test')).resolves.toEqual({pending:false, turns:[]});
});
});
