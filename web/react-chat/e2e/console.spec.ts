import {expect, test} from '@playwright/test';

test('文字聊天可保存并在刷新后恢复，React 页面可统一导航', async ({page, baseURL}) => {
  const external:string[] = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.protocol.startsWith('http') && url.origin !== new URL(baseURL!).origin) external.push(request.url());
  });

  await page.goto('/chat-react');
  await expect(page.getByRole('heading', {name:'聊聊今天'})).toBeVisible();
  await page.getByRole('textbox', {name:'消息'}).fill('我养了一只叫豆包的猫');
  await page.locator('button[type="submit"]').click();
  await expect(page.locator('.bubble.assistant').getByText('好的，我记住了。', {exact:true})).toBeVisible();

  await page.reload();
  await expect(page.locator('.bubble.user').getByText('我养了一只叫豆包的猫', {exact:true})).toBeVisible();
  await expect(page.locator('.bubble.assistant').getByText('好的，我记住了。', {exact:true})).toBeVisible();

  await page.getByRole('link', {name:'设备与状态'}).click();
  await expect(page.getByRole('heading', {name:'设备与状态'})).toBeVisible();
  await page.getByRole('link', {name:'个性化设置'}).click();
  await expect(page.getByRole('heading', {name:'个性化设置'})).toBeVisible();
  await page.getByRole('link', {name:'记忆管理'}).click();
  await expect(page.getByRole('heading', {name:'记忆管理'})).toBeVisible();
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
  await page.getByRole('link', {name:'实验中心'}).click();
  await expect(page).toHaveURL(/\/experiments-react$/);
  await expect(page.getByRole('heading', {name:'实验中心'})).toBeVisible();

  expect(external).toEqual([]);
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
