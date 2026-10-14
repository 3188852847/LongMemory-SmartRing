import {defineConfig} from '@playwright/test';

/** 所有文档、资源和 API 均由本地合成路由提供，不启动日用或后端服务。 */
export default defineConfig({
  testDir:'.',testMatch:'data-workspaces.spec.ts',workers:1,retries:0,
  outputDir:'../test-results/data-workspaces',reporter:'list',
  use:{baseURL:'http://127.0.0.1:18814',channel:'msedge',screenshot:'only-on-failure',trace:'retain-on-failure'},
});
