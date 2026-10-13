import {defineConfig} from 'vitest/config';
// 独立资源前缀；生产服务不公开开发源文件，也不需要常驻 Node。
export default defineConfig({
  base: '/react-chat/',
  build: {manifest: true, rolldownOptions: {input: {index: 'index.html', launcher: 'launcher.html'}}},
  test: {environment: 'jsdom', setupFiles: './src/tests/setup.ts', clearMocks: true,
    include: ['src/**/*.test.{ts,tsx}']},
});
