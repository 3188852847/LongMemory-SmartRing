import {mkdirSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {defineConfig} from '@playwright/test';
import base from './playwright.config';

const frontend = dirname(fileURLToPath(import.meta.url));
const repository = resolve(frontend, '../..');
const temporary = resolve(repository, 'data/test-tmp/browser-j');
mkdirSync(temporary, {recursive: true});
const python = process.env.SMART_RING_TEST_PYTHON;
if (!python) throw new Error('请指定已核对的 SMART_RING_TEST_PYTHON，不自动创建或安装解释器。');
if (!process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH) throw new Error('请指定已有 Edge，不自动下载浏览器。');

/** J 使用一个离线合成主机；launcher.spec 自己启动另一随机端口替身。 */
export default defineConfig({...base,
  testMatch: ['console.spec.ts', 'chat-workspace.spec.ts', 'settings-display.spec.ts',
    'data-workspaces.spec.ts', 'launcher.spec.ts', 'integration.spec.ts'],
  outputDir: 'test-results/integration', reporter: [['list']],
  use: {...base.use, baseURL: 'http://127.0.0.1:18881'},
  webServer: {
    command: `"${python}" scripts/development/playwright_console.py --port 18881`,
    cwd: repository,
    env: {PYTHONPATH: resolve(repository, 'src'), PYTHONDONTWRITEBYTECODE: '1', TEMP: temporary, TMP: temporary},
    url: 'http://127.0.0.1:18881/chat-react', reuseExistingServer: false, timeout: 20_000,
  },
});
