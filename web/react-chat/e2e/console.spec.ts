import {expect, test} from '@playwright/test';

test('文字聊天可保存并在刷新后恢复，React 页面可统一导航', async ({page, baseURL}) => {
  const external:string[] = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.protocol.startsWith('http') && url.origin !== new URL(baseURL!).origin) external.push(request.url());
  });

  await page.goto('/chat-react');
  await expect(page.getByRole('heading', {name:'聊聊今天'})).toBeVisible();
  await expect(page.getByRole('region', {name:'当前系统状态'})).toBeVisible();
  await expect(page.getByRole('region', {name:'本轮记忆证据'})).toContainText('WAITING');
  await page.getByRole('link', {name:'查看模型诊断'}).click();
  await expect(page).toHaveURL(/\/settings\?tab=model$/);
  await expect(page.getByRole('tab', {name:'模型与服务'})).toHaveAttribute('aria-selected', 'true');
  await page.getByRole('link', {name:'文字聊天'}).click();
  await page.getByRole('button', {name:'记忆命令'}).click();
  await expect(page.getByRole('dialog', {name:'可直接使用的记忆命令'})).toBeVisible();
  await page.locator('.ant-modal-close').click();
  await page.getByRole('textbox', {name:'消息'}).fill('我养了一只叫豆包的猫');
  await page.locator('button[type="submit"]').click();
  await expect(page.locator('.bubble.assistant').getByText('好的，我记住了。', {exact:true})).toBeVisible();
  await expect(page.getByRole('region', {name:'本轮记忆证据'})).toContainText('用户养了一只叫豆包的猫。');
  await page.getByRole('link', {name:'核对 L0 原话'}).click();
  await expect(page).toHaveURL(/\/memories\?memory_id=/);
  await expect(page.getByRole('heading', {name:'L1 原子记忆'})).toBeVisible();
  await expect(page.getByRole('heading', {name:'L0 原始来源'})).toBeVisible();
  await expect(page.getByText('我养了一只叫豆包的猫', {exact:true})).toBeVisible();
  await page.locator('.ant-drawer-close:visible').click();
  await expect(page).toHaveURL(/\/memories$/);
  await page.getByRole('link', {name:'文字聊天'}).click();

  await page.reload();
  await expect(page.locator('.bubble.user').getByText('我养了一只叫豆包的猫', {exact:true})).toBeVisible();
  await expect(page.locator('.bubble.assistant').getByText('好的，我记住了。', {exact:true})).toBeVisible();

  await page.getByRole('textbox', {name:'消息'}).fill('不要记住：我今天想喝茉莉花茶');
  await page.locator('button[type="submit"]').click();
  await expect(page.locator('.bubble.assistant').getByText(
    '本轮没有生成 L1 长期事实；原始对话 L0 仍保留用于审计。', {exact:true},
  )).toBeVisible();
  await expect(page.getByText('实际记忆操作结果')).toBeVisible();
  await expect(page.getByRole('alert').getByText(
    '本轮没有生成 L1 长期事实；原始对话 L0 仍保留用于审计。', {exact:true},
  )).toBeVisible();

  await page.getByRole('link', {name:'设备状态'}).click();
  await expect(page.getByRole('heading', {name:'设备与状态'})).toBeVisible();
  await page.getByRole('link', {name:'圆屏预览'}).click();
  await expect(page.getByRole('heading', {name:'圆屏状态预览'})).toBeVisible();
  await expect(page.getByRole('region', {name:'圆屏模拟画布'})).toBeVisible();
  await page.getByRole('link', {name:'设置中心'}).click();
  await expect(page.getByRole('heading', {name:'设置中心'})).toBeVisible();
  await expect(page.getByRole('tab', {name:'助手角色'})).toHaveAttribute('aria-selected', 'true');
  await page.getByRole('button', {name:'助手角色设置'}).click();
  await expect(page.getByRole('dialog', {name:'助手角色设置'})).toBeVisible();
  await page.getByRole('switch', {name:'启用结构化表达偏好'}).click();
  await page.getByRole('textbox', {name:'希望助手怎么称呼你（可留空）'}).fill('小林');
  await page.getByRole('button', {name:'保存并用于网页下一轮'}).click();
  await expect(page.getByText(/已保存版本 1/)).toBeVisible();
  await page.locator('.ant-modal-close').click();
  await page.getByRole('tab', {name:'外观与阅读'}).click();
  const themeSelect = page.getByRole('combobox', {name:'主题'});
  await expect(themeSelect).toBeVisible();
  await themeSelect.click();
  await page.locator('.ant-select-dropdown:visible').getByText('未来控制台（推荐）', {exact:true}).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'future');
  await page.getByRole('link', {name:'原始与原子记忆'}).click();
  await expect(page.getByRole('heading', {name:'原始与原子记忆'})).toBeVisible();
  await page.getByText('用户养了一只叫豆包的猫。', {exact:true}).click();
  await page.getByRole('button', {name:'记录变化'}).click();
  await page.getByRole('textbox', {name:'变化后的完整事实'}).fill('用户现在养了一只叫年糕的猫。');
  await page.getByLabel('变化生效时间').fill('2026-09-03T12:00');
  await page.getByRole('button', {name:'确认事实已经变化'}).click();
  await expect(page.getByText('变化已保存：旧事实保留历史有效期，新事实从指定时间开始生效。')).toBeVisible();
  await expect(page.locator('.detail-content')).toHaveText('用户现在养了一只叫年糕的猫。');
  await expect(page.locator('.ant-modal-wrap:visible')).toHaveCount(0);
  await page.locator('.ant-drawer-close:visible').click();
  await expect(page.locator('.ant-drawer-mask:visible')).toHaveCount(0);
  await page.getByRole('link', {name:'用户画像'}).click();
  await expect(page).toHaveURL(/\/personas$/);
  await expect(page.getByRole('heading', {name:'用户画像（L3）'})).toBeVisible();
  await expect(page.getByText('我的统一画像')).toBeVisible();
  await expect(page.getByText(/尚无已接受的画像认识/)).toBeVisible();
  await page.getByRole('link', {name:'实验中心'}).click();
  await expect(page).toHaveURL(/\/experiments-react$/);
  await expect(page.getByRole('heading', {name:'实验中心'})).toBeVisible();

  expect(external).toEqual([]);
});

test('窄窗口保留全部主导航且页面不产生横向溢出', async ({page}) => {
  await page.setViewportSize({width:390, height:844});
  await page.goto('/chat-react');
  await expect(page.getByRole('heading', {name:'聊聊今天'})).toBeVisible();
  await expect(page.getByRole('link', {name:'设备状态'})).toBeVisible();
  await expect(page.getByRole('link', {name:'圆屏预览'})).toBeVisible();
  await expect(page.getByRole('link', {name:'实验中心'})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.getByRole('link', {name:'设置中心'}).click();
  await expect(page.getByRole('heading', {name:'设置中心'})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('只读实验服务不能误启动模型作业', async ({page}) => {
  const starts:string[] = [];
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().endsWith('/api/experiment-jobs/start')) starts.push(request.url());
  });
  await page.goto('/experiments-react');
  await expect(page.getByText(/当前服务仅查看档案/)).toBeVisible();
  await expect(page.getByRole('button', {name:'预检与核对预算'})).toBeDisabled();
  expect(starts).toEqual([]);
});
