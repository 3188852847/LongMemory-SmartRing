import {createHash} from 'node:crypto';
import {readFileSync, writeFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {expect, test} from '@playwright/test';

test.beforeEach(async({request,baseURL})=>{
  const session=await request.get('/api/session',{headers:{'X-Console-Bootstrap':'1'}});
  expect(session.ok()).toBe(true);
  const {csrf}=await session.json();
  const reset=await request.post('/api/q-fixture/reset',{headers:{'X-Console-CSRF':csrf,Origin:new URL(baseURL!).origin}});
  expect(reset.ok()).toBe(true);
  expect(await reset.json()).toEqual({fixture:'Q_SYNTHETIC_OBSERVABILITY_ONLY',capacity:100,seeded_requests:2});
});

const widths = [
  {width: 1366, height: 768, large: false}, {width: 1440, height: 900, large: true},
  {width: 390, height: 844, large: false}, {width: 390, height: 844, large: true},
];

for (const viewport of widths) {
  test(`Q 合成诊断：轮次／预算／键盘 ${viewport.width} 大字=${viewport.large}`, async ({page, browser}, info) => {
    const writes: string[] = [];
    const errors: string[] = [];
    page.on('request', request => {if (request.method() !== 'GET') writes.push(new URL(request.url()).pathname);});
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize(viewport);
    await page.emulateMedia({reducedMotion: 'reduce'});
    if (viewport.large) await page.addInitScript(() => localStorage.setItem('longmemory:chat-appearance:v3',
      JSON.stringify({theme:'future',size:'larger',motion:'reduce',density:'comfortable',chatWidth:'focused'})));
    const responsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/observability');
    await page.goto('/device?view=diagnostics');
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    expect(response.request().method()).toBe('GET');
    const summary = await response.json();
    expect(summary.device_playback).toBe('unconfirmed');
    expect(summary.voice.rounds).toHaveLength(2);
    expect(summary.log_retention.mode).toBe('dry_run');
    expect(summary.log_retention.deletion_available).toBe(false);
    expect(summary.log_retention.candidate_streams).toEqual([]);
    expect(summary.log_retention.unresolved_bytes).toBeGreaterThan(0);
    const panel = page.locator('.observability-panel');
    await expect(page.locator('html')).toHaveAttribute('data-reading', viewport.large ? 'larger' : 'normal');
    await expect(page.locator('html')).toHaveCSS('font-size', viewport.large ? '20px' : '16px');
    await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduce');
    await expect(panel.getByText('执行结果未知，请重新读取状态')).toBeVisible();
    await expect(panel.getByText(/设备播放仍未确认/)).toBeVisible();
    const voice = panel.locator('summary').filter({hasText: '语音轮次与缺失阶段'});
    await voice.focus(); await page.keyboard.press('Enter');
    await expect(voice.locator('..')).toHaveAttribute('open', '');
    await expect(panel.getByText(/事件序号缺失：3/)).toBeVisible();
    await expect(panel.getByText('语音包装器进程 · 模型超时', {exact: true})).toBeVisible();
    await expect(panel.getByText(/合成服务进程 · 合成服务生成失败/)).toBeVisible();
    await expect(panel.getByText(/合成服务事件存在缺号/)).toBeVisible();
    const rounds = panel.locator('article');
    await expect(rounds).toHaveCount(2);
    const failed = rounds.filter({hasText:'观察到失败'});
    const cancelled = rounds.filter({hasText:'已取消或已有新轮次'});
    await expect(failed).toHaveCount(1); await expect(cancelled).toHaveCount(1);
    await expect(failed.getByText(/编码音频已产生/)).toHaveCount(1); // 仅在“关联缺失”提示里出现。
    await expect(cancelled.getByText('语音包装器进程 · 编码音频已产生', {exact:true})).toBeVisible();
    const retention = panel.locator('summary').filter({hasText:'历次日志容量与保留预算'});
    await retention.focus(); await page.keyboard.press('Space');
    await expect(retention.locator('..')).toHaveAttribute('open', '');
    await expect(panel.getByText(/未执行删除/)).toBeVisible();
    await expect(panel.getByText(/超出预算且受保护/)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await voice.scrollIntoViewIfNeeded(); await voice.focus();
    expect(await voice.evaluate(node => getComputedStyle(node).outlineStyle)).not.toBe('none');
    await page.keyboard.press('Enter');
    await expect(voice.locator('..')).not.toHaveAttribute('open', '');
    await page.keyboard.press('Tab');
    await expect(retention).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(retention.locator('..')).not.toHaveAttribute('open', '');
    await voice.click(); await retention.click();
    const identity = await (await page.request.get('/api/q-fixture/identity')).json();
    expect(identity.fixture).toBe('Q_SYNTHETIC_OBSERVABILITY_ONLY');
    expect(identity.revision).toBe(execFileSync('git', ['rev-parse','HEAD'], {encoding:'utf8'}).trim());
    const manifest = readFileSync('dist/.vite/manifest.json');
    expect(identity.manifest_sha256).toBe(createHash('sha256').update(manifest).digest('hex'));
    const evidence = JSON.stringify({...identity, edge:browser.version(), viewport}, null, 2);
    writeFileSync(info.outputPath('q-build-identity.json'), evidence);
    await info.attach('q-build-identity', {body:evidence, contentType:'application/json'});
    await panel.screenshot({path:info.outputPath('q-panel.png')});
    await voice.evaluate(node => node.scrollIntoView({block:'start'}));
    await page.screenshot({path:info.outputPath('q-voice-viewport.png')});
    await retention.evaluate(node => node.scrollIntoView({block:'start'}));
    await page.screenshot({path:info.outputPath('q-budget-viewport.png')});
    expect(errors).toEqual([]); expect(writes).toEqual([]);
  });
}

test('Q 刷新失败保留上次摘要；只读 GET 不自动重试或重放业务', async ({page}) => {
  const writes: string[] = [];
  let reads = 0;
  page.on('request', request => {if (request.method() !== 'GET') writes.push(new URL(request.url()).pathname);});
  await page.route('**/api/observability', async route => {
    if (++reads > 1) return route.fulfill({status:504, json:{error:'console_timeout'}});
    return route.continue();
  });
  await page.goto('/device?view=diagnostics');
  const panel = page.locator('.observability-panel');
  await expect(panel.getByText('执行结果未知，请重新读取状态')).toBeVisible();
  await panel.getByRole('button', {name:'刷新摘要'}).click();
  await expect(panel.getByRole('alert')).toContainText('摘要暂不可读取');
  await expect(panel.getByText('执行结果未知，请重新读取状态')).toBeVisible();
  await panel.locator('summary').filter({hasText:'语音轮次与缺失阶段'}).click();
  await expect(panel.getByText(/事件序号缺失：3/)).toBeVisible();
  expect(reads).toBe(2); expect(writes).toEqual([]);
});

test('Q 正在读取与真实空数据模型明确展示缺失，不伪装零容量', async ({page}) => {
  let release!: () => void;
  const waiting = new Promise<void>(resolve => {release = resolve;});
  await page.route('**/api/observability', async route => {
    await waiting;
    const empty = await route.fetch({url:new URL('/api/q-fixture/empty',route.request().url()).href});
    await route.fulfill({response:empty});
  });
  await page.goto('/device?view=diagnostics');
  const panel = page.locator('.observability-panel');
  await expect(panel.getByRole('status').filter({hasText:'正在读取安全摘要'})).toBeVisible();
  release();
  await expect(panel.getByText(/重启前记录未加载/)).toBeVisible();
  await panel.locator('summary').filter({hasText:'语音轮次与缺失阶段'}).click();
  await expect(panel.getByText(/当前进程尚未收到语音事件/)).toBeVisible();
  await panel.locator('summary').filter({hasText:'历次日志容量与保留预算'}).click();
  await expect(panel.getByText('当前服务尚未提供日志容量统计。')).toBeVisible();
  await expect(panel.getByText(/固定目录已统计/)).toHaveCount(0);
});

test('Q 达到事件上限与观测持久化失败均明确提示，未提供清理动作', async ({page}) => {
  await page.route('**/api/observability', async route => {
    const snapshot = await route.fetch({url:new URL('/api/q-fixture/truncated',route.request().url()).href});
    await route.fulfill({response:snapshot});
  });
  await page.goto('/device?view=diagnostics');
  const panel = page.locator('.observability-panel');
  await expect(panel.getByText('诊断文件暂不可写入')).toBeVisible();
  await panel.locator('summary').filter({hasText:'语音轮次与缺失阶段'}).click();
  await expect(panel.getByText(/本轮达到摘要条目上限/)).toBeVisible();
  await expect(panel.locator('article li')).toHaveCount(128);
  await panel.locator('summary').filter({hasText:'历次日志容量与保留预算'}).click();
  await expect(panel.getByText(/统计范围不完整/)).toBeVisible();
  await expect(panel.getByRole('button')).toHaveCount(1);
  await expect(panel.getByRole('button', {name:/删除|清理|应用计划/})).toHaveCount(0);
});

test('S 兼容旧响应：缺少语音和容量字段仍显示原 HTTP 摘要', async ({page}, info) => {
  await page.setViewportSize({width:390, height:844});
  await page.route('**/api/observability', async route => {
    const response = await route.fetch();
    const snapshot = await response.json();
    delete snapshot.voice;
    delete snapshot.log_retention;
    snapshot.requests.forEach((row: Record<string, unknown>) => delete row.voice_round_id);
    await route.fulfill({response, json:snapshot});
  });
  await page.goto('/device?view=diagnostics');
  const panel = page.locator('.observability-panel');
  await expect(panel.getByText('执行结果未知，请重新读取状态')).toBeVisible();
  await panel.locator('summary').filter({hasText:'语音轮次与缺失阶段'}).click();
  await expect(panel.getByText(/当前进程尚未收到语音事件/)).toBeVisible();
  await panel.locator('summary').filter({hasText:'历次日志容量与保留预算'}).click();
  await expect(panel.getByText('当前服务尚未提供累计保留元数据。')).toBeVisible();
  await expect(panel.locator('article')).toHaveCount(0);
  await expect(panel.getByText(/固定目录已统计/)).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await panel.screenshot({path:info.outputPath('s-legacy-summary.png')});
});
