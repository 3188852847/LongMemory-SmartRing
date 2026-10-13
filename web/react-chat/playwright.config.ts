import {defineConfig, devices} from '@playwright/test';

/**
 * 浏览器验收只连接临时 Fake 控制台。服务脚本创建独立数据库，
 * 不读取 .env、个人记忆、校园模型或圆屏控制通道。
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: {timeout: 5_000},
  outputDir: 'test-results',
  reporter: [['list'], ['html', {open: 'never', outputFolder: 'playwright-report'}]],
  use: {
    baseURL: 'http://127.0.0.1:18777',
    // 本地可复用已安装的 Chromium 系浏览器；未指定时由 Playwright 使用其固定版本。
    launchOptions: {executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined},
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [{name: 'chromium', use: {...devices['Desktop Chrome']}}],
  webServer: {
    command: '..\\..\\.venv\\Scripts\\python.exe ..\\..\\scripts\\development\\playwright_console.py --port 18777',
    url: 'http://127.0.0.1:18777/chat-react',
    reuseExistingServer: false,
    timeout: 20_000,
  },
});
