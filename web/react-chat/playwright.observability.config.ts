import {mkdirSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {defineConfig} from '@playwright/test';
import base from './playwright.config';

const repository = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const temporary = resolve(repository, 'data/test-tmp/browser-q');
mkdirSync(temporary, {recursive: true});
const python = process.env.SMART_RING_TEST_PYTHON;
const edge = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
if (!python || !edge) throw new Error('Q 验收必须显式指定现有 Python 与 Edge；不下载运行环境。');
if (process.version !== 'v24.19.0') throw new Error('Q 验收固定 Node 24.19.0。');

export default defineConfig({...base,
  testMatch: 'observability.spec.ts', workers: 1,
  outputDir: 'test-results/observability', reporter: [['list']],
  use: {...base.use, baseURL: 'http://127.0.0.1:18892', launchOptions: {executablePath: edge}},
  webServer: {
    command: `"${python}" scripts/development/observability_browser.py --port 18892`,
    cwd: repository,
    env: {PYTHONPATH: resolve(repository, 'src'), PYTHONDONTWRITEBYTECODE: '1', TEMP: temporary, TMP: temporary},
    url: 'http://127.0.0.1:18892/chat-react', reuseExistingServer: false, timeout: 20_000,
  },
});
