/**
 * sanoTTS 中文 Node/WASM 隔离引擎。
 *
 * 上游当前把中文标为 browser-only，但其 Emscripten 声学运行时本身支持
 * Node。这里复用外部检出中的原文件，不复制 GPL 运行时或模型进项目。
 */
import {createRequire} from 'node:module';
import {readFile, lstat} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {dirname, join, resolve, sep} from 'node:path';
import {pathToFileURL} from 'node:url';

const require = createRequire(import.meta.url);
const VOICE_KEY = 'chinese-xiaoya';
const MAX_SECONDS = 20;

function inside(root, path) {
  const prefix = root.endsWith(sep) ? root : root + sep;
  return path === root || path.startsWith(prefix);
}

async function regularFile(root, ...parts) {
  const path = resolve(root, ...parts);
  if (!inside(root, path)) throw new Error('sanotts_source_path_escape');
  const stat = await lstat(path);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('sanotts_source_file_invalid');
  return path;
}

async function readJson(path) {
  return JSON.parse(await readFile(path, 'utf8'));
}

function widenF16(bytes, meta) {
  const head = Number(meta.meta_bytes);
  const count = Number(meta.weight_floats);
  if (!Number.isInteger(head) || !Number.isInteger(count) || head < 0 || count <= 0)
    throw new Error('sanotts_f16_metadata_invalid');
  if (bytes.length !== head + 2 * count) throw new Error('sanotts_f16_size_mismatch');
  const output = new Uint8Array(head + 4 * count);
  output.set(bytes.subarray(0, head));
  const source = new DataView(bytes.buffer, bytes.byteOffset + head, 2 * count);
  const target = new DataView(output.buffer, head, 4 * count);
  for (let index = 0; index < count; index += 1) {
    const bits = source.getUint16(index * 2, true);
    const exponent = (bits >> 10) & 0x1f;
    const fraction = bits & 0x3ff;
    const sign = (bits & 0x8000) ? -1 : 1;
    let value;
    if (exponent === 0) value = sign * fraction * 5.960464477539063e-8;
    else if (exponent === 31) value = fraction ? Number.NaN : sign * Number.POSITIVE_INFINITY;
    else value = sign * 2 ** (exponent - 25) * (1024 + fraction);
    target.setFloat32(index * 4, value, true);
  }
  return output;
}

function toHeap(module, bytes) {
  const pointer = module._malloc(bytes.length);
  if (!pointer) throw new Error('sanotts_wasm_allocation_failed');
  module.HEAPU8.set(bytes, pointer);
  return pointer;
}

function pcm16Wave(samples, sampleRate) {
  const dataBytes = samples.length * 2;
  const output = Buffer.allocUnsafe(44 + dataBytes);
  output.write('RIFF', 0); output.writeUInt32LE(36 + dataBytes, 4);
  output.write('WAVEfmt ', 8); output.writeUInt32LE(16, 16);
  output.writeUInt16LE(1, 20); output.writeUInt16LE(1, 22);
  output.writeUInt32LE(sampleRate, 24); output.writeUInt32LE(sampleRate * 2, 28);
  output.writeUInt16LE(2, 32); output.writeUInt16LE(16, 34);
  output.write('data', 36); output.writeUInt32LE(dataBytes, 40);
  for (let index = 0; index < samples.length; index += 1) {
    const value = Math.max(-1, Math.min(1, samples[index]));
    output.writeInt16LE(Math.round(value * (value < 0 ? 32768 : 32767)), 44 + index * 2);
  }
  return output;
}

/** 对外部源码做最小可复现指纹，不把绝对路径公开给 HTTP 调用者。 */
async function fingerprint(paths) {
  const hash = createHash('sha256');
  for (const path of paths) hash.update(await readFile(path));
  return hash.digest('hex');
}

export class SanoChineseEngine {
  static async load(sourceRoot) {
    const root = resolve(sourceRoot);
    const web = resolve(root, 'web');
    const runtimeJs = await regularFile(root, 'web', 'snt_voice.js');
    const runtimeWasm = await regularFile(root, 'web', 'snt_voice.wasm');
    const voiceDir = resolve(web, 'voices', VOICE_KEY);
    const metaPath = await regularFile(root, 'web', 'voices', VOICE_KEY, 'meta.json');
    const zhModule = await regularFile(root, 'web', 'g2p-lazy', 'zh', 'zh_g2p.mjs');
    const meta = await readJson(metaPath);
    if (meta.key !== VOICE_KEY || meta.phoneme_type !== 'pinyin' || meta.weights !== 'f16')
      throw new Error('sanotts_chinese_contract_mismatch');
    const frontPath = await regularFile(root, 'web', 'voices', VOICE_KEY, meta.front);
    const decoderPath = await regularFile(root, 'web', 'voices', VOICE_KEY, meta.dec);
    const manifestPath = await regularFile(root, 'web', 'g2p-lazy', 'zh', 'manifest.json');
    const unicodePath = await regularFile(root, 'web', 'g2p-lazy', 'zh', 'unicode_tables.mjs');
    const manifest = await readJson(manifestPath);
    const tableNames = Object.values(manifest.files || {}).map(item => item?.file);
    if (tableNames.length !== 3 || tableNames.some(name => typeof name !== 'string'))
      throw new Error('sanotts_g2p_manifest_invalid');
    const tablePaths = [];
    for (const name of tableNames) {
      tablePaths.push(await regularFile(root, 'web', 'g2p-lazy', 'zh', name));
    }

    // Emscripten 生成物提供 CommonJS 导出，并在 Node 下从 locateFile 读取 wasm。
    const factory = require(runtimeJs);
    const voice = await factory({locateFile: name => name === 'snt_voice.wasm' ? runtimeWasm : join(dirname(runtimeJs), name)});
    const zh = await import(pathToFileURL(zhModule).href);
    const localFetch = async resource => {
      const path = resolve(String(resource));
      if (!inside(resolve(web, 'g2p-lazy', 'zh'), path))
        return {ok:false, status:403, arrayBuffer:async()=>new ArrayBuffer(0)};
      try {
        const bytes = await readFile(path);
        return {ok:true, status:200, arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)};
      } catch {
        return {ok:false, status:404, arrayBuffer:async()=>new ArrayBuffer(0)};
      }
    };
    const g2p = await zh.loadZhG2P(resolve(web, 'g2p-lazy', 'zh') + sep, localFetch);
    const front = widenF16(new Uint8Array(await readFile(frontPath)), meta.front_dims);
    const decoder = widenF16(new Uint8Array(await readFile(decoderPath)), meta.dec_dims);
    const sourceFingerprint = await fingerprint([
      runtimeJs, runtimeWasm, metaPath, frontPath, decoderPath, zhModule, unicodePath,
      manifestPath, ...tablePaths,
    ]);
    return new SanoChineseEngine({voice, g2p, meta, front, decoder, sourceFingerprint});
  }

  constructor({voice, g2p, meta, front, decoder, sourceFingerprint}) {
    this.voice = voice;
    this.g2p = g2p;
    this.meta = meta;
    this.front = front;
    this.decoder = decoder;
    this.sourceFingerprint = sourceFingerprint;
  }

  synthesize(text, {speakingRate=1}={}) {
    if (typeof text !== 'string' || !text.trim() || text.length > 600)
      throw new Error('sanotts_text_invalid');
    if (!Number.isFinite(speakingRate) || speakingRate < 0.75 || speakingRate > 1.5)
      throw new Error('sanotts_speaking_rate_invalid');
    const ids = this.g2p.textToIds(text.trim(), this.meta.phoneme_id_map).ids;
    const frontPointer = toHeap(this.voice, this.front);
    const decoderPointer = toHeap(this.voice, this.decoder);
    const idsPointer = toHeap(this.voice, new Uint8Array(ids.buffer, ids.byteOffset, ids.byteLength));
    const outputCapacity = Math.round(this.meta.sample_rate * MAX_SECONDS);
    const outputPointer = this.voice._malloc(outputCapacity * 4);
    const started = performance.now();
    try {
      const count = this.voice._snt_voice_synthesize(
        frontPointer, decoderPointer, idsPointer, ids.length,
        this.meta.length_scale / speakingRate, outputPointer, outputCapacity,
      );
      if (count < 1) throw new Error(`sanotts_synthesis_failed_${count}`);
      const samples = this.voice.HEAPF32.slice(outputPointer >> 2, (outputPointer >> 2) + count);
      return {
        wave: pcm16Wave(samples, this.meta.sample_rate),
        sampleRate: this.meta.sample_rate,
        sampleCount: count,
        phonemeCount: ids.length,
        synthesisMs: Math.round((performance.now() - started) * 100) / 100,
      };
    } finally {
      [frontPointer, decoderPointer, idsPointer, outputPointer].forEach(pointer => this.voice._free(pointer));
    }
  }
}
