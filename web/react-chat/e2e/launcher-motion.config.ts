import {defineConfig} from '@playwright/test';
import config from '../playwright.config';

// F 的验收仅启动 launcher.spec 自己的随机端口合成主机，不启动默认控制台主机。
export default defineConfig({...config, projects:[{name:'chromium'}], testDir: '.', testMatch: 'launcher.spec.ts', webServer: undefined});
