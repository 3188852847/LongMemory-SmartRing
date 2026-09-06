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
