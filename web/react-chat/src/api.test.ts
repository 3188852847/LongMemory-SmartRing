import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ChatApi} from './api.ts';

test('bootstrap and writes use CSRF without persisting or retrying content', async () => {
  const original = globalThis.fetch;
  const calls: {path: string; options?: RequestInit}[] = [];
  globalThis.fetch = async (path, options) => {
    calls.push({path: String(path), options});
    return new Response(JSON.stringify(calls.length === 1 ? {csrf:'synthetic'} : {error:'chat_busy'}), {status: calls.length === 1 ? 200 : 409});
  };
  try {
    const api = new ChatApi(); await api.bootstrap();
    await assert.rejects(api.request('/api/chats/test/messages', 'POST', {text:'合成输入'}), /chat_busy/);
    assert.equal(calls.length, 2);
    assert.equal((calls[1].options?.headers as Record<string,string>)['X-Console-CSRF'], 'synthetic');
    assert.equal(calls[1].options?.credentials, 'same-origin');
  } finally {globalThis.fetch = original;}
});

test('GET recovery does not replay a write', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (_path, options) => {
    assert.equal(options?.method, 'GET'); assert.equal(options?.body, undefined);
    return new Response(JSON.stringify({pending: false, turns: []}));
  };
  try {assert.deepEqual(await new ChatApi().request('/api/chats/test'), {pending:false, turns:[]});}
  finally {globalThis.fetch = original;}
});
