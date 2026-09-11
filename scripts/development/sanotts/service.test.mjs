import assert from 'node:assert/strict';
import {after, before, test} from 'node:test';
import {createSanoServer} from './service.mjs';

const calls = [];
const engine = {
  sourceFingerprint: 'synthetic-fingerprint',
  synthesize(text, options) {
    calls.push({text, options});
    return {wave: Buffer.from('RIFFsynthetic'), synthesisMs: 12.5};
  },
};
const server = createSanoServer(engine);
let base;

before(async () => {
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  base = `http://127.0.0.1:${server.address().port}`;
});

after(async () => new Promise(resolve => server.close(resolve)));

test('health and capabilities disclose bounded runtime facts', async () => {
  const health = await fetch(`${base}/health`);
  assert.equal(health.status, 200);
  assert.deepEqual(await health.json(), {
    ready: true, provider: 'sanotts', voice: 'xiaoya',
    source_fingerprint: 'synthetic-fingerprint',
  });
  const capabilities = await (await fetch(`${base}/v1/capabilities`)).json();
  assert.deepEqual(capabilities.delivery_modes, ['buffered']);
  assert.equal(capabilities.cancellation, 'none');
});

test('fixed speech request returns wave and passes bounded controls', async () => {
  const response = await fetch(`${base}/v1/audio/speech`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({input: '你好', response_format: 'wav', stream: false, speed: 1.1}),
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'audio/wav');
  assert.equal(Buffer.from(await response.arrayBuffer()).toString(), 'RIFFsynthetic');
  assert.deepEqual(calls.at(-1), {text: '你好', options: {speakingRate: 1.1}});
});

test('browser origins and unsupported streaming are rejected', async () => {
  const browser = await fetch(`${base}/v1/audio/speech`, {
    method: 'POST', headers: {'Content-Type': 'application/json', Origin: 'http://127.0.0.1:8767'},
    body: JSON.stringify({input: '不应执行'}),
  });
  assert.equal(browser.status, 403);
  const streaming = await fetch(`${base}/v1/audio/speech`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({input: '不应执行', stream: true}),
  });
  assert.equal(streaming.status, 400);
  assert.equal(calls.length, 1);
});
