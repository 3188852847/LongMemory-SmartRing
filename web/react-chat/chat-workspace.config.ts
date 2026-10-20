import {mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {defineConfig} from '@playwright/test';
import base from './playwright.config';

// C 独立端口；解释器可由主会话提供，但源码和临时输出必须属于本工作树。
const temporary = resolve('../../data/test-tmp/browser-c');
mkdirSync(temporary, {recursive:true});
const python = process.env.SMART_RING_TEST_PYTHON || resolve('../../.venv/Scripts/python.exe');
export default defineConfig({
  ...base,
  projects:[{name:'chromium'}],
  testMatch: 'chat-workspace.spec.ts',
  use: {...base.use, baseURL:'http://127.0.0.1:18831'},
  webServer: {
    command:`"${python}" "../../scripts/development/playwright_console.py" --port 18831`,
    env:{PYTHONPATH:resolve('../../src'), TEMP:temporary, TMP:temporary},
    url:'http://127.0.0.1:18831/chat-react',
    reuseExistingServer:false,
    timeout:20_000,
  },
});
