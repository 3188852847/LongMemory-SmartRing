import {defineConfig} from '@playwright/test';
const url=process.env.Z_HY_LIVE_URL;
if(!url||!/^http:\/\/127\.0\.0\.1:\d+$/.test(url)||!process.env.Z_HY_LIVE_EVIDENCE)throw new Error('Explicit isolated Z backend and evidence required');
export default defineConfig({testDir:'./e2e-live',testMatch:'hy-release-live.spec.ts',workers:1,retries:0,timeout:45000,
  outputDir:process.env.Z_HY_LIVE_EVIDENCE,reporter:[['list']],
  use:{baseURL:url,launchOptions:{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH},
    trace:'retain-on-failure',screenshot:'only-on-failure',video:'off'}});
