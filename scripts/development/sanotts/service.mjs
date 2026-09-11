/** sanoTTS 本机隔离服务：只暴露固定的 OpenAI 兼容音频端点。 */
import http from 'node:http';
import {pathToFileURL} from 'node:url';
import {SanoChineseEngine} from './engine.mjs';

const MAX_BODY_BYTES = 8192;
const ALLOWED_FIELDS = new Set(['input', 'response_format', 'stream', 'speed', 'voice', 'model']);

function json(response, status, body) {
  const data = Buffer.from(JSON.stringify(body));
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': data.length,
    'Cache-Control': 'no-store',
  });
  response.end(data);
}

async function readBody(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) throw new Error('request_too_large');
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

function validate(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error('invalid_request');
  if (Object.keys(body).some(key => !ALLOWED_FIELDS.has(key))) throw new Error('unknown_field');
  if (typeof body.input !== 'string' || !body.input.trim() || body.input.length > 600)
    throw new Error('invalid_input');
  if (body.response_format !== undefined && body.response_format !== 'wav')
    throw new Error('unsupported_format');
  if (body.stream !== undefined && body.stream !== false) throw new Error('streaming_not_supported');
  if (body.voice !== undefined && body.voice !== 'xiaoya') throw new Error('unsupported_voice');
  if (body.model !== undefined && body.model !== 'chinese-xiaoya') throw new Error('unsupported_model');
  const speed = body.speed === undefined ? 1 : body.speed;
  if (typeof speed !== 'number' || !Number.isFinite(speed) || speed < 0.75 || speed > 1.5)
    throw new Error('invalid_speed');
  return {text: body.input.trim(), speed};
}

export function createSanoServer(engine) {
  let busy = false;
  const server = http.createServer(async (request, response) => {
    response.setHeader('X-Content-Type-Options', 'nosniff');
    try {
      // 这个端点只供本机小智子进程调用；浏览器不应借用户记忆触发语音生成。
      if (request.headers.origin) {
        request.resume();
        return json(response, 403, {error: 'browser_request_rejected'});
      }
      if (request.method === 'GET' && request.url === '/health') {
        return json(response, 200, {
          ready: true,
          provider: 'sanotts',
          voice: 'xiaoya',
          source_fingerprint: engine.sourceFingerprint,
        });
      }
      if (request.method === 'GET' && request.url === '/v1/capabilities') {
        return json(response, 200, {
          contract_version: 2,
          provider_id: 'sanotts',
          delivery_modes: ['buffered'],
          output_mime_types: ['audio/wav'],
          controls: ['speaking_rate'],
          cancellation: 'none',
          max_text_chars: 600,
        });
      }
      if (request.method !== 'POST' || request.url !== '/v1/audio/speech') {
        request.resume();
        return json(response, 404, {error: 'not_found'});
      }
      if (!String(request.headers['content-type'] || '').toLowerCase().startsWith('application/json')) {
        request.resume();
        return json(response, 415, {error: 'json_required'});
      }
      if (busy) {
        request.resume();
        return json(response, 409, {error: 'service_busy'});
      }
      const {text, speed} = validate(await readBody(request));
      busy = true;
      try {
        const result = engine.synthesize(text, {speakingRate: speed});
        response.writeHead(200, {
          'Content-Type': 'audio/wav',
          'Content-Length': result.wave.length,
          'Cache-Control': 'no-store',
          'X-Synthesis-Milliseconds': String(result.synthesisMs),
        });
        response.end(result.wave);
      } finally {
        busy = false;
      }
    } catch (error) {
      const code = error instanceof SyntaxError ? 'invalid_json' : String(error?.message || 'request_failed');
      const clientErrors = new Set([
        'request_too_large', 'invalid_request', 'unknown_field', 'invalid_input',
        'unsupported_format', 'streaming_not_supported', 'unsupported_voice',
        'unsupported_model', 'invalid_speed', 'invalid_json',
      ]);
      if (!response.headersSent) json(response, clientErrors.has(code) ? 400 : 500, {error: code});
      else response.destroy();
    }
  });
  return server;
}

function parseArguments(argv) {
  const result = {host: '127.0.0.1', port: 18769, source: '', expectedFingerprint: ''};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!value || !['--host', '--port', '--source', '--expected-fingerprint'].includes(key)) throw new Error('invalid_arguments');
    if (key === '--host') result.host = value;
    if (key === '--port') result.port = Number(value);
    if (key === '--source') result.source = value;
    if (key === '--expected-fingerprint') result.expectedFingerprint = value;
  }
  if (result.host !== '127.0.0.1' || !Number.isInteger(result.port) || result.port < 1024 || result.port > 65535)
    throw new Error('unsafe_listen_address');
  if (!result.source) throw new Error('source_required');
  if (result.expectedFingerprint && !/^[0-9a-f]{64}$/.test(result.expectedFingerprint))
    throw new Error('fingerprint_invalid');
  return result;
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const engine = await SanoChineseEngine.load(options.source);
  if (options.expectedFingerprint && engine.sourceFingerprint !== options.expectedFingerprint)
    throw new Error('source_fingerprint_mismatch');
  const server = createSanoServer(engine);
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(options.port, options.host, resolve);
  });
  process.stdout.write(`sanoTTS ready on ${options.host}:${options.port}\n`);
  const close = () => {
    server.close(() => process.exit(0));
    // 独立调试时可能残留 keep-alive 连接；主动关闭，避免终端看似停止但端口仍被占用。
    server.closeAllConnections?.();
    setTimeout(() => process.exit(0), 1000).unref();
  };
  process.once('SIGINT', close);
  process.once('SIGTERM', close);
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  main().catch(error => {
    const systemCode = String(error?.code || '');
    if (systemCode === 'EADDRINUSE') error = new Error('port_in_use');
    if (systemCode === 'EACCES') error = new Error('listen_denied');
    const safe = new Set([
      'invalid_arguments', 'unsafe_listen_address', 'source_required',
      'fingerprint_invalid', 'source_fingerprint_mismatch',
      'sanotts_source_file_invalid', 'sanotts_chinese_contract_mismatch',
      'sanotts_g2p_manifest_invalid', 'port_in_use', 'listen_denied',
    ]);
    const code = safe.has(String(error?.message)) ? error.message : 'local_environment_unavailable';
    process.stderr.write(`sanoTTS failed to start: ${code}.\n`);
    process.exit(3);
  });
}
