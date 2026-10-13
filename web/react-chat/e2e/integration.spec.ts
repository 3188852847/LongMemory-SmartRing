import {expect, test} from '@playwright/test';

for (const viewport of [{width: 1366, height: 768}, {width: 1440, height: 900}, {width: 390, height: 844}]) {
  test(`C/F 聊天输入与持续光效 ${viewport.width}`, async ({page}) => {
    await page.setViewportSize(viewport);
    await page.goto('/chat-react');
    const input = page.getByRole('textbox', {name: '消息'});
    await expect(input).toBeEnabled();
    await input.fill('只保留在浏览器的合成草稿');
    const toggle = page.getByRole('button', {name: '持续光效'});
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(page.locator('html')).toHaveAttribute('data-ambient', 'off');
    const box = await input.boundingBox();
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 1)).toBe(true);
    await page.emulateMedia({reducedMotion: 'reduce'});
    await expect(page.locator('.atmosphere-ring')).toHaveCSS('animation-name', 'none');
  });
}

test('跨页点击与历史返回拒绝离页时保留聊天草稿', async ({page}) => {
  await page.goto('/overview');
  await page.getByRole('link', {name: '文字聊天', exact: true}).click();
  const input = page.getByRole('textbox', {name: '消息'});
  await expect(input).toBeEnabled();
  await input.fill('不能因导航丢失的合成草稿');
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('link', {name: '设备状态', exact: true}).click();
  await expect(page).toHaveURL(/\/chat-react$/);
  await expect(input).toHaveValue('不能因导航丢失的合成草稿');
  page.once('dialog', dialog => dialog.dismiss());
  await page.evaluate(() => history.back());
  await expect(page).toHaveURL(/\/chat-react$/);
  await expect(input).toHaveValue('不能因导航丢失的合成草稿');
  await input.fill('');
  await page.getByRole('link', {name: '设备状态', exact: true}).click();
  await expect(page).toHaveURL(/\/device$/);
});

test('E/G 摘要刷新只读，保留未知执行与硬件未确认', async ({page}) => {
  const writes: string[] = [];
  page.on('request', request => {if (request.method() !== 'GET') writes.push(new URL(request.url()).pathname);});
  let reads = 0;
  await page.route('**/api/observability', route => {
    if (++reads > 1) return route.fulfill({status: 504, json: {error: 'console_timeout'}});
    return route.fulfill({json: {schema_version: 1, scope: 'current_process', capacity: 100,
      persistence: 'disabled', device_playback: 'unconfirmed', coverage: [], uncovered: [], logs: [],
      requests: [{request_id: 'a'.repeat(24), time: '2026-10-14T00:00:00Z', operation: 'device',
        stage: 'request', outcome: 'unknown', code: 'bridge_timeout', status: 504, duration_ms: 20, stages: []}]}});
  });
  await page.goto('/device?view=diagnostics');
  await expect(page.getByText('执行结果未知，请重新读取状态')).toBeVisible();
  await expect(page.getByText(/设备播放仍未确认/)).toBeVisible();
  await page.getByRole('button', {name: '刷新摘要'}).click();
  await expect(page.getByText('摘要暂不可读取')).toBeVisible();
  await expect(page.getByText('执行结果未知，请重新读取状态')).toBeVisible();
  expect(reads).toBe(2);
  expect(writes).toEqual([]);
});
