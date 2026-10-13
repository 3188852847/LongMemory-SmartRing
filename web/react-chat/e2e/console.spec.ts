import {expect, test} from '@playwright/test';

test('文字聊天可保存并在刷新后恢复，React 页面可统一导航', async ({page, baseURL}) => {
  const external:string[] = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.protocol.startsWith('http') && url.origin !== new URL(baseURL!).origin) external.push(request.url());
  });

  await page.goto('/chat-react');
  await expect(page.getByRole('heading', {name:'聊聊今天'})).toBeVisible();
  await page.getByRole('button', {name:'记忆证据', exact:true}).click();
  await expect(page.getByRole('region', {name:'本轮记忆证据'})).toContainText('WAITING');
  await page.getByRole('button', {name:'运行状态', exact:true}).click();
  await expect(page.getByRole('region', {name:'当前系统状态'})).toBeVisible();
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
  await page.getByRole('button', {name:'记忆证据', exact:true}).click();
  await expect(page.getByRole('region', {name:'本轮记忆证据'})).toContainText('用户养了一只叫豆包的猫。');
  await page.getByRole('link', {name:'核对 L0 原话'}).click();
  await expect(page).toHaveURL(/\/memories\?memory_id=/);
  const memoryDetail = page.getByRole('dialog', {name:'L1 原子记忆'});
  await expect(memoryDetail).toBeVisible();
  await expect(memoryDetail.getByRole('heading', {name:'L0 原始来源'})).toBeVisible();
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
  await expect(page.getByRole('heading', {name:'助手设置'})).toBeVisible();
  await expect(page.getByRole('tab', {name:'助手表达'})).toHaveAttribute('aria-selected', 'true');
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
  const l1Row = page.locator('.memory-browser .memory-item').filter({
    hasText:'用户养了一只叫豆包的猫。',
  });
  await expect(l1Row).toHaveCount(1);
  await l1Row.click();
  await page.getByRole('button', {name:'记录变化'}).click();
  await page.getByRole('textbox', {name:'变化后的完整事实'}).fill('用户现在养了一只叫年糕的猫。');
  await page.getByLabel('变化生效时间').fill('2026-09-03T12:00');
  await page.getByRole('button', {name:'确认事实已经变化'}).click();
  await expect(page.getByText('变化已保存：旧事实保留历史有效期，新事实从指定时间开始生效。')).toBeVisible();
  await expect(page.locator('.detail-content')).toHaveText('用户现在养了一只叫年糕的猫。');
  await expect(page.locator('.ant-modal-wrap:visible')).toHaveCount(0);
  await memoryDetail.getByRole('button', {name:'事实时间线'}).click();
  const temporalHistory = page.getByRole('dialog', {name:'事实变化时间线'});
  await expect(temporalHistory).toContainText('用户养了一只叫豆包的猫。');
  await expect(temporalHistory).toContainText('用户现在养了一只叫年糕的猫。');
  await expect(temporalHistory).toContainText('第 1/2 段');
  await expect(temporalHistory).toContainText('第 2/2 段');
  await temporalHistory.locator('.ant-modal-close').click();

  await memoryDetail.getByRole('button', {name:'纠正错误'}).click();
  await page.getByRole('textbox', {name:'纠正后的完整事实'}).fill('用户现在养了一只叫布丁的猫。');
  await page.getByRole('button', {name:'确认旧事实有误并保存'}).click();
  await expect(page.getByText('纠正已保存：新 L1 生效，旧 L1 保留为已取代历史。')).toBeVisible();
  await expect(page.locator('.detail-content')).toHaveText('用户现在养了一只叫布丁的猫。');
  await expect(page.locator('.ant-modal-wrap:visible')).toHaveCount(0);
  // 每日回顾已由 E 移入独立任务；先关闭来源抽屉再进入，不穿过遮罩操作。
  const deletedMemoryId = await memoryDetail.locator('.ant-descriptions-item').filter({
    hasText:'记忆 ID',
  }).locator('.ant-descriptions-item-content').innerText();
  await memoryDetail.locator('.ant-drawer-close').click();
  await page.getByRole('button', {name:'每日回顾', exact:true}).click();
  const dailyReview = page.locator('.ant-card').filter({hasText:'每日记忆回顾'}).first();
  await expect(dailyReview).toContainText('纠正 1');
  await expect(dailyReview).toContainText('事实变化 1');
  await expect(dailyReview.locator('.ant-list-item').filter({
    hasText:'用户现在养了一只叫年糕的猫。',
  })).toContainText('已退役');
  await expect(dailyReview.locator('.ant-list-item').filter({
    hasText:'用户现在养了一只叫布丁的猫。',
  })).toContainText('当前');
  await page.getByRole('button', {name:'浏览记忆', exact:true}).click();
  await page.locator('.memory-browser .memory-item').filter({hasText:'用户现在养了一只叫布丁的猫。'}).getByRole('button', {name:'查看来源'}).click();
  await memoryDetail.getByRole('button', {name:/删\s*除/}).click();
  const deleteDialog = page.getByRole('dialog', {name:'删除这条 L1 记忆？'});
  await expect(deleteDialog).toBeVisible();
  await deleteDialog.getByText('我理解以上影响，只删除这一条 L1。').click();
  await deleteDialog.getByRole('button', {name:'确认删除 L1'}).click();
  await expect(page.getByText('L1 已删除；L0 原始对话仍保留。')).toBeVisible();
  await expect(page.locator('.ant-drawer-mask:visible')).toHaveCount(0);
  await expect(page.getByRole('tab', {name:'L1 原子记忆 · 4'})).toBeVisible();
  await expect(page.locator('.memory-browser .memory-item').filter({
    hasText:'用户现在养了一只叫布丁的猫。',
  })).toHaveCount(0);
  await page.getByRole('button', {name:'每日回顾', exact:true}).click();
  await expect(dailyReview).toContainText('事实变化 1');
  await expect(dailyReview).toContainText('删除 1');
  await dailyReview.getByText('查看删除审计（1）').click();
  await expect(dailyReview.getByText(/已删除 L1：/).locator('code')).toHaveText(deletedMemoryId);
  await page.getByRole('button', {name:'浏览记忆', exact:true}).click();
  await page.getByRole('tab', {name:/^L0 原始记录/}).click();
  await expect(page.locator('.memory-browser .memory-item').filter({
    hasText:'我养了一只叫豆包的猫',
  })).toHaveCount(1);
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
  await page.getByRole('button', {name:'展开导航'}).click();
  await expect(page.getByRole('link', {name:'设备状态'})).toBeVisible();
  await expect(page.getByRole('link', {name:'圆屏预览'})).toBeVisible();
  await expect(page.getByRole('link', {name:'实验中心'})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.getByRole('link', {name:'设置中心'}).click();
  await expect(page.getByRole('heading', {name:'助手设置'})).toBeVisible();
  await expect(page.getByRole('button', {name:'展开导航'})).toHaveAttribute('aria-expanded', 'false');
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

test('所有者可合并并恢复重复 L1，矛盾候选没有合并入口', async ({page}) => {
  await page.goto('/memories');
  await expect(page.getByRole('heading', {name:'原始与原子记忆'})).toBeVisible();
  await page.getByRole('button', {name:'重复与关系复核', exact:true}).click();
  await page.getByRole('button', {name:'扫描当前 L1'}).click();

  const duplicate = page.locator('.quality-candidate-item').filter({hasText:'规范化重复'});
  await expect(duplicate).toContainText('用户喜欢乌龙茶。');
  await expect(duplicate).toContainText('此人喜欢乌龙茶');
  await duplicate.getByRole('button', {name:'保留 A，合并 B'}).click();
  const mergeDialog = page.getByRole('dialog', {name:'确认合并这两条重复 L1？'});
  await expect(mergeDialog).toBeVisible();
  await mergeDialog.getByRole('button', {name:'确认合并'}).click();
  await expect(page.getByText(/重复 L1 已合并/)).toBeVisible();
  const keptMemoryDetail = page.getByRole('dialog', {name:'L1 原子记忆'});
  await expect(keptMemoryDetail).toContainText('我喜欢乌龙茶。');
  await expect(keptMemoryDetail).toContainText('我确实喜欢乌龙茶');
  await keptMemoryDetail.locator('.ant-drawer-close').click();
  await expect(page.locator('.ant-drawer-mask:visible')).toHaveCount(0);

  await page.getByText('查看重复合并历史（1）').click();
  await expect(page.getByText(/账本完整 1\/1/)).toBeVisible();
  await expect(page.getByRole('button', {name:/L0 source-d · 用户陈述/})).toBeVisible();
  await page.getByRole('button', {name:'恢复被合并项'}).click();
  const restoreDialog = page.getByRole('dialog', {name:'恢复这条被合并的 L1？'});
  await expect(restoreDialog).toBeVisible();
  await restoreDialog.getByRole('button', {name:'确认恢复'}).click();
  await expect(page.getByText(/被合并的 L1 已恢复为当前记忆/)).toBeVisible();
  await expect(page.getByText('已恢复', {exact:true})).toBeVisible();
  await expect(page.getByRole('button', {name:'重新保留 A，合并 B'})).toBeEnabled();
  await expect(page.getByRole('button', {name:'保留 B，合并 A'})).toBeDisabled();

  const conflict = page.locator('.quality-candidate-item').filter({hasText:'可能矛盾'});
  await expect(conflict).toContainText('用户喜欢喝咖啡。');
  await expect(conflict).toContainText('用户不喜欢喝咖啡。');
  await expect(conflict.getByRole('button', {name:/合并/})).toHaveCount(0);
});
