import {expect, test} from '@playwright/test';
import type {ConsoleMessage, Dialog, Request, Response} from '@playwright/test';

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
  await page.getByRole('textbox', {name:'消息'}).fill('我养了一只叫豆包的猫');
  await page.locator('button[type="submit"]').click();
  await expect(page.locator('.bubble.assistant').getByText('好的，我记住了。', {exact:true})).toBeVisible();
  await page.getByRole('button', {name:'记忆证据', exact:true}).click();
  await page.reload();
  await expect(page.locator('.bubble.user').getByText('我养了一只叫豆包的猫', {exact:true})).toBeVisible();
  await expect(page.locator('.bubble.assistant').getByText('好的，我记住了。', {exact:true})).toBeVisible();

  await test.step('从文字聊天进入设备状态', async () => {
    const before = {url:page.url(),href:await page.getByRole('link', {name:'设备状态'}).getAttribute('href')};
    const dialogs:Array<{type:string;message:string}> = [];
    const network:Array<{path:string;method:string;status?:number;error?:string}> = [];
    const consoleErrors:string[] = [], pageErrors:string[] = [];
    const pathOf = (url:string) => {try {return new URL(url).pathname;} catch {return 'unavailable';}};
    // 只在这个导航步骤收集限量元数据，失败后写进CI日志；不读取凭据或请求正文。
    const onDialog = async (dialog:Dialog) => {
      if (dialogs.length < 6) dialogs.push({type:dialog.type(),message:dialog.message().slice(0,160)});
      await dialog.dismiss().catch(() => undefined); // 保持原默认dismiss；页面关闭时不另抛异步异常。
    };
    const onResponse = (response:Response) => {
      if (response.status() >= 400 && network.length < 8) network.push({path:pathOf(response.url()),method:response.request().method(),status:response.status()});
    };
    const onRequestFailed = (request:Request) => {
      if (network.length < 8) network.push({path:pathOf(request.url()),method:request.method(),error:request.failure()?.errorText?.slice(0,160)});
    };
    const onConsole = (message:ConsoleMessage) => {if (message.type() === 'error' && consoleErrors.length < 6) consoleErrors.push(message.text().slice(0,240));};
    const onPageError = (error:Error) => {if (pageErrors.length < 6) pageErrors.push(error.message.slice(0,240));};
    page.on('dialog',onDialog);page.on('response',onResponse);page.on('requestfailed',onRequestFailed);page.on('console',onConsole);page.on('pageerror',onPageError);
    try {
      await page.getByRole('link', {name:'设备状态'}).click();
      await expect(page.getByRole('heading', {name:'设备与状态'})).toBeVisible();
    } catch (error) {
      try {
        let timer:ReturnType<typeof setTimeout>|undefined;
        const snapshot = await Promise.race([
          page.evaluate(() => ({
            url:location.href,title:document.title,
            visibleHeadings:Array.from(document.querySelectorAll('h1,h2,h3,[role="heading"]'))
              .filter(node => node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden')
              .slice(0,12).map(node => node.textContent?.trim().slice(0,120)),
            loading:document.querySelector('.page-loading')?.textContent?.trim().slice(0,120) ?? null,
            routeError:document.body.textContent?.includes('Unexpected Application Error!') ?? false,
            chatDraftPresent:Boolean(document.querySelector('textarea[name="message"]')),
            chatDraftEmpty:(document.querySelector('textarea[name="message"]') as HTMLTextAreaElement|null)?.value === '',
          })).catch(() => ({unavailable:true})),
          new Promise(resolve => {timer=setTimeout(() => resolve({unavailable:true,reason:'snapshot_timeout'}),750);}),
        ]).finally(() => clearTimeout(timer));
        console.error('[console-device-navigation-failure]',JSON.stringify({before,url:page.url(),snapshot,dialogs,network,consoleErrors,pageErrors}));
      } catch { /* 诊断不可用也保留下面的原始断言异常。 */ }
      throw error;
    } finally {
      page.off('dialog',onDialog);page.off('response',onResponse);page.off('requestfailed',onRequestFailed);page.off('console',onConsole);page.off('pageerror',onPageError);
    }
  });
  await page.getByRole('link', {name:'圆屏预览'}).click();
  await expect(page.getByRole('heading', {name:'圆屏状态预览'})).toBeVisible();
  await expect(page.getByRole('region', {name:'圆屏模拟画布'})).toBeVisible();
  await page.getByRole('link', {name:'设置中心'}).click();
  await expect(page.getByRole('heading', {name:'助手设置'})).toBeVisible();
  await expect(page.getByRole('tab', {name:'角色设置'})).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByLabel('人格卡')).toBeVisible();
  await page.getByText('预设、历史与表达偏好').click();
  await page.getByRole('switch', {name:'启用结构化表达偏好'}).click();
  await page.getByRole('textbox', {name:'希望助手怎么称呼你（可留空）'}).fill('小林');
  await page.getByRole('button', {name:'保存并用于网页下一轮'}).click();
  await expect(page.getByText(/已保存版本 1/)).toBeVisible();
  await page.getByRole('tab', {name:'外观与阅读'}).click();
  const themeSelect = page.getByRole('combobox', {name:'主题'});
  await expect(themeSelect).toBeVisible();
  await themeSelect.click();
  await page.locator('.ant-select-dropdown:visible').getByText('未来控制台（推荐）', {exact:true}).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'future');
  expect(external).toEqual([]);
});

test('窄窗口保留全部主导航且页面不产生横向溢出', async ({page}) => {
  await page.setViewportSize({width:390, height:844});
  await page.goto('/chat-react');
  await expect(page.getByRole('heading', {name:'聊聊今天'})).toBeVisible();
  await page.getByRole('button', {name:'展开导航'}).click();
  await expect(page.getByRole('link', {name:'设备状态'})).toBeVisible();
  await expect(page.getByRole('link', {name:'圆屏预览'})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.getByRole('link', {name:'设置中心'}).click();
  await expect(page.getByRole('heading', {name:'助手设置'})).toBeVisible();
  await expect(page.getByRole('button', {name:'展开导航'})).toHaveAttribute('aria-expanded', 'false');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
