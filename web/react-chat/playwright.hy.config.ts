import {defineConfig} from '@playwright/test';
const port=Number(process.env.HY_UI_PORT);
if(!port||!process.env.HY_UI_EVIDENCE_DIR)throw new Error('Explicit Y random port and evidence directory required');
export default defineConfig({testDir:'./e2e',testMatch:['hy-memory.spec.ts','hy-mechanisms.spec.ts'],workers:1,retries:0,timeout:30000,
  outputDir:process.env.HY_UI_EVIDENCE_DIR,reporter:[['list']],
  use:{baseURL:`http://127.0.0.1:${port}`,launchOptions:{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH},trace:'retain-on-failure',screenshot:'only-on-failure',video:'off'},
  webServer:{command:'node e2e/hy-static-server.mjs',url:`http://127.0.0.1:${port}/memories`,reuseExistingServer:false,timeout:15000},
});
