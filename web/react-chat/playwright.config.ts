import {defineConfig, devices} from '@playwright/test';
import {mkdirSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const repository=resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const python=process.env.SMART_RING_TEST_PYTHON || resolve(repository,'.venv/Scripts/python.exe');
function testPort(value:string|undefined,fallback:number) {
  const port=Number(value ?? fallback);
  if(!Number.isInteger(port)||port<1024||port>65535||[8767,8000,8003].includes(port))throw new Error('需要独立的合成测试端口');
  return port;
}
const port=testPort(process.env.SMART_RING_TEST_PORT,18777);
const observationPort=testPort(process.env.SMART_RING_OBSERVABILITY_TEST_PORT,18892);
if(port===observationPort)throw new Error('普通主机与观测主机必须使用不同端口');
const origin=`http://127.0.0.1:${port}`,observationOrigin=`http://127.0.0.1:${observationPort}`;
const temporary=resolve(repository,`data/test-tmp/browser-ci-${process.pid}`);
mkdirSync(temporary,{recursive:true});
const host=(script:string,port:number)=>({
  command:`"${python}" scripts/development/${script} --port ${port}`,
  cwd:repository,
  env:{PYTHONPATH:resolve(repository,'src'),PYTHONDONTWRITEBYTECODE:'1',TEMP:temporary,TMP:temporary},
  url:`http://127.0.0.1:${port}/chat-react`,reuseExistingServer:false,timeout:20_000,
});

/**
 * 浏览器验收只连接临时 Fake 控制台。服务脚本创建独立数据库，
 * 不读取 .env、个人记忆、校园模型或圆屏控制通道。
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: true,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: {timeout: 5_000},
  outputDir: 'test-results',
  reporter: [['list'], ['html', {open: 'never', outputFolder: 'playwright-report'}]],
  use: {
    baseURL: origin,
    // 本地可复用已安装的 Chromium 系浏览器；未指定时由 Playwright 使用其固定版本。
    launchOptions: {executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined},
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  // 每份合成 spec 进入一个项目；诊断用例需要带事件种子的专用主机。
  // 实际 SDK/HTTP 验收放在 e2e-live，由显式 z-live 配置另行装配。
  projects: [
    {name:'chromium',testIgnore:'**/observability.spec.ts',use:{...devices['Desktop Chrome']}},
    {name:'observability',testMatch:'**/observability.spec.ts',use:{...devices['Desktop Chrome'],baseURL:observationOrigin}},
  ],
  webServer:[host('playwright_console.py',port),host('observability_browser.py',observationPort)],
});
