import {defineConfig,devices} from '@playwright/test';
import {fileURLToPath} from 'node:url';
import {dirname,resolve} from 'node:path';

const frontendRoot=dirname(fileURLToPath(import.meta.url));
const repositoryRoot=resolve(frontendRoot,'../..');
const python=process.env.SMART_RING_TEST_PYTHON ?? resolve(repositoryRoot,'.venv/Scripts/python.exe');
const assets=process.env.SMART_RING_TEST_OTTO_ASSETS;
export default defineConfig({
  testDir:'./e2e',testMatch:'p-experience.spec.ts',workers:1,retries:0,timeout:45_000,
  expect:{timeout:7000},outputDir:'test-results/p-experience',reporter:[['list']],
  use:{baseURL:'http://127.0.0.1:18891',trace:'retain-on-failure',screenshot:'only-on-failure',
    launchOptions:{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined}},
  projects:[{name:'edge',use:{...devices['Desktop Chrome']}}],
  webServer:{command:`"${python}" scripts/development/playwright_console.py --port 18891${assets?` --otto-assets "${assets}"`:''}`,
    cwd:repositoryRoot,env:{PYTHONPATH:resolve(repositoryRoot,'src')},url:'http://127.0.0.1:18891/chat-react',reuseExistingServer:false,timeout:20_000},
});
