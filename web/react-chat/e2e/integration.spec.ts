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
  await Promise.all([page.waitForEvent('dialog').then(dialog => dialog.dismiss()),
    page.getByRole('link', {name: '设备状态', exact: true}).click()]);
  await expect(page).toHaveURL(/\/chat-react$/);
  await expect(input).toHaveValue('不能因导航丢失的合成草稿');
  await Promise.all([page.waitForEvent('dialog').then(dialog => dialog.dismiss()),
    page.evaluate(() => history.back())]);
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

test('H01 回看期间新回答不拉底，回到最新恢复跟随', async ({page}) => {
  await page.goto('/chat-react');
  const input=page.getByRole('textbox',{name:'消息'});
  await expect(input).toBeEnabled();
  await page.getByRole('button',{name:'新聊天',exact:true}).click();
  await expect(input).toBeEnabled();
  for(let i=0;i<8;i++) {
    await input.fill(`合成回看问题 ${i}。${'仅验证独立测试界面的滚动位置。'.repeat(12)}`);
    await page.getByRole('button',{name:'发送',exact:true}).click();
    await expect(page.locator('.messages article')).toHaveCount(i+1);
  }
  const messages=page.getByRole('region',{name:'聊天记录'});
  await messages.evaluate(node=>{node.scrollTop=0;node.dispatchEvent(new Event('scroll'));});
  await expect(page.getByRole('button',{name:'回到最新'})).toBeVisible();
  await page.getByRole('button',{name:'查看第 3 轮记忆证据'}).click();
  await expect(page.getByRole('heading',{name:'第 3 轮记忆证据'})).toBeVisible();
  await page.getByRole('button',{name:'收起面板'}).click();
  const before=await messages.evaluate(node=>node.scrollTop);
  await input.fill('合成新回答抵达期间继续回看');
  await page.getByRole('button',{name:'发送',exact:true}).click();
  await expect(page.locator('.messages article')).toHaveCount(9);
  expect(await messages.evaluate(node=>node.scrollTop)).toBeCloseTo(before,0);
  await page.getByRole('button',{name:'回到最新'}).click();
  await expect.poll(()=>messages.evaluate(node=>node.scrollHeight-node.clientHeight-node.scrollTop)).toBeLessThan(48);
});

test('H04 390px 来源抽屉标题和全部动作可见，关闭保留筛选', async ({page}, info) => {
  await page.setViewportSize({width:390,height:844});
  await page.goto('/memories');
  const search=page.getByRole('searchbox',{name:'搜索当前层级'});
  await expect(search).toBeEnabled();
  await search.fill('乌龙茶');await search.press('Enter');
  await page.locator('.memory-item').first().getByRole('button',{name:'查看来源'}).click();
  const drawer=page.getByRole('dialog',{name:'事实记忆（L1）'});
  await expect(drawer).toBeVisible();
  await expect.poll(async()=>{const box=await drawer.boundingBox();return Boolean(box && box.x>=0 && box.x+box.width<=391);}).toBe(true);
  for(const name of ['事实时间线','纠正错误','记录变化',/删\s*除/,'Close']) {
    const button=drawer.getByRole('button',{name,exact:true});
    await expect(button).toBeVisible();
    const box=await button.boundingBox();expect(box!.x).toBeGreaterThanOrEqual(0);expect(box!.x+box!.width).toBeLessThanOrEqual(391);
  }
  const title=await drawer.locator('.ant-drawer-title').boundingBox();expect(title!.width).toBeGreaterThan(80);
  await page.screenshot({path:info.outputPath('h04-source-390.png'),fullPage:true});
  await drawer.getByRole('button',{name:'Close',exact:true}).click();
  await expect(drawer).not.toBeVisible();await expect(search).toHaveValue('乌龙茶');
});

test('H07 新页面归零和焦点、历史返回恢复文档位置与筛选', async ({page}) => {
  await page.setViewportSize({width:1366,height:768});
  await page.addInitScript(()=>localStorage.setItem('longmemory:chat-appearance:v3',
    JSON.stringify({theme:'future',size:'larger',motion:'reduce',density:'comfortable',chatWidth:'focused'})));
  await page.goto('/memories');
  const search=page.getByRole('searchbox',{name:'搜索当前层级'});
  await expect(search).toBeEnabled();
  await search.fill('茶');await search.press('Enter');
  await page.getByRole('button',{name:'每日回顾',exact:true}).click();
  await expect(page.getByRole('button',{name:'每日回顾',exact:true})).toHaveAttribute('aria-pressed','true');
  // 查询切换和日报读取会改变文档高度；先确认可滚动布局，再建立返回恢复的测试坐标。
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollHeight-innerHeight)).toBeGreaterThan(0);
  await page.evaluate(()=>window.scrollTo(0,5000));
  await expect.poll(()=>page.evaluate(()=>scrollY)).toBeGreaterThan(0);
  const before=await page.evaluate(()=>scrollY);expect(before).toBeGreaterThan(0);
  await page.getByRole('link',{name:'系统总览',exact:true}).click();
  await expect(page.getByRole('heading',{name:'系统总览',exact:true})).toBeVisible();
  await expect.poll(()=>page.evaluate(()=>scrollY)).toBe(0);
  await expect.poll(()=>page.evaluate(()=>document.activeElement?.id)).toBe('main-content');
  await page.goBack();
  await expect(page.getByRole('button',{name:'每日回顾',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect.poll(()=>page.evaluate(()=>scrollY)).toBeCloseTo(before,0);
  await page.getByRole('button',{name:'浏览记忆',exact:true}).click();await expect(search).toHaveValue('茶');
});

test('H11 父级失败不保留连接中或已保存承诺', async ({page}) => {
  await page.route('**/api/**',route=>route.fulfill({status:503,json:{error:'console_internal_error'}}));
  await page.goto('/settings?tab=overview');
  await expect(page.getByText('设置服务当前不可用')).toBeVisible();
  await expect(page.getByText('设置服务读取失败').first()).toBeVisible();
  await expect(page.getByText('连接中',{exact:true})).toHaveCount(0);
  await expect(page.getByText('读取中',{exact:true})).toHaveCount(0);
  await expect(page.getByText('下次启动选择已保存',{exact:true})).toHaveCount(0);
});

test('G 页面读取真实认证摘要，返回版本和设备未确认语义', async ({page}) => {
  const summary=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/observability');
  await page.goto('/device?view=diagnostics');
  const response=await summary;expect(response.status()).toBe(200);expect(response.request().method()).toBe('GET');
  const body=await response.json();expect(body.schema_version).toBe(1);expect(body.device_playback).toBe('unconfirmed');
  expect(Array.isArray(body.requests)).toBe(true);
  await expect(page.getByText(/设备播放仍未确认/)).toBeVisible();
});
