import {defineConfig, devices} from '@playwright/test';
import {fileURLToPath} from 'node:url';
import {dirname, resolve} from 'node:path';

const frontendRoot = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(frontendRoot, '../..');
const python = process.env.SMART_RING_TEST_PYTHON ?? resolve(repositoryRoot, '.venv/Scripts/python.exe');

/** D 独立验收：端口独立，源码显式来自本工作树。浏览器所有 API 都由合成响应接管。 */
export default defineConfig({
  testDir:'./e2e', testMatch:'settings-display.spec.ts', workers:1,
  timeout:30_000, expect:{timeout:5_000},
  outputDir:'test-results/settings-display', reporter:[['list']],
  use:{baseURL:'http://127.0.0.1:18874',
    launchOptions:{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined},
    screenshot:'only-on-failure', trace:'retain-on-failure'},
  projects:[{name:'chromium',use:{...devices['Desktop Chrome']}}],
  webServer:{
    command:`"${python}" scripts/development/playwright_console.py --port 18874`,
    cwd:repositoryRoot, env:{PYTHONPATH:resolve(repositoryRoot,'src')},
    url:'http://127.0.0.1:18874/chat-react', reuseExistingServer:false, timeout:20_000,
  },
});
