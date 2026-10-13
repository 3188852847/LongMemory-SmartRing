import {expect, test} from '@playwright/test';

const sizes = [
  {width:1366,height:768,reading:'normal'},
  {width:1440,height:900,reading:'normal'},
  {width:390,height:844,reading:'normal'},
  {width:1366,height:768,reading:'larger'},
];

for (const size of sizes) test(`聊天滚动、证据与输入 ${size.width}×${size.height} ${size.reading}`, async ({page}) => {
  await page.setViewportSize({width:size.width,height:size.height});
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.addInitScript(reading => localStorage.setItem('longmemory:chat-appearance:v3',
    JSON.stringify({theme:'future',size:reading,motion:'reduce',density:'comfortable',chatWidth:'focused'})), size.reading);
  const snapshot = {chat_id:'synthetic-chat',title:'合成验收会话',pending:false,turns:Array.from({length:20},(_,i) => ({
    request_id:`synthetic-${i}`,input:`合成问题 ${i}：${'长文字内容用于检查换行。'.repeat(12)}`,
    answer:`合成回答 ${i}：${'仅用于验证布局和任务操作。'.repeat(15)}`,status:'completed',user_saved:true,duration_ms:1,writes:[],
    retrieved:[{item_id:`memory-${i}`,content:`合成证据 ${i}`,source_event_ids:['synthetic-source']}],
  }))};
  const posts:string[] = [];
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'POST') posts.push(path);
    let body:unknown;
    if (path === '/api/session') body = {csrf:'synthetic-csrf'};
    else if (path === '/api/chat-config') body = {enabled:true,database:'synthetic.db',provider:'fake',model:'Fake',role:'测试'};
    else if (path === '/api/chats') body = {chats:[{chat_id:snapshot.chat_id,title:snapshot.title,turn_count:snapshot.turns.length}]};
    else if (path === `/api/chats/${snapshot.chat_id}`) body = snapshot;
    else if (path === `/api/chats/${snapshot.chat_id}/messages`) {
      const incoming = request.postDataJSON();
      const next = {...snapshot.turns[0],request_id:incoming.request_id,input:incoming.text,answer:'发送后的合成回答'};
      snapshot.turns.push(next); body = next;
    } else if (path.endsWith('/memory-feedback')) body = {feedback:{kind:'recall_miss',revision:1,occurred_at:'2026-10-14T00:00:00Z'}};
    else if (path === '/api/device') body = {ready:false,connection_count:0};
    else if (path === '/api/memories') body = {total:20,offset:0,limit:1,items:[]};
    else if (path === '/api/runtime-status') body = {enabled:false,state:'unknown',services:{}};
    else throw new Error(`C 浏览器用例出现未声明的请求：${request.method()} ${path}`);
    await route.fulfill({json:body});
  });
  await page.goto('/chat-react');
  await expect(page.getByText('会话已恢复，可以继续聊。')).toBeVisible();
  const input = page.getByRole('textbox',{name:'消息'});
  const composer = page.locator('.chat-composer');
  await input.fill('尚未发送的合成草稿');
  await expect(input).toBeInViewport();
  await expect(page.getByRole('button',{name:'发送',exact:true})).toBeInViewport();
  const before = await composer.boundingBox();
  const history = page.getByRole('region',{name:'聊天记录'});
  expect(await history.evaluate(node => node.scrollHeight > node.clientHeight)).toBe(true);
  await history.evaluate(node => {node.scrollTop = 0;});
  const firstEvidence = page.getByRole('button',{name:'查看第 1 轮记忆证据'});
  await firstEvidence.scrollIntoViewIfNeeded();
  const readingPosition = await history.evaluate(node => node.scrollTop);
  await firstEvidence.click();
  await expect(page.getByRole('region',{name:'本轮记忆证据'})).toContainText('合成证据 0');
  await expect(input).toHaveValue('尚未发送的合成草稿');
  await expect(input).toBeInViewport();
  expect((await composer.boundingBox())?.y).toBeCloseTo(before!.y, 0);
  await page.getByRole('button',{name:'收起面板'}).click();
  await expect(page.getByRole('button',{name:'记忆证据',exact:true})).toBeFocused();
  await expect(history).toBeVisible();
  // 辅助切换后保留浏览位置，不把读旧消息的用户带回最后一轮。
  expect(await history.evaluate(node => node.scrollTop)).toBeCloseTo(readingPosition, 0);
  await page.getByRole('button',{name:'会话',exact:true}).click();
  await page.getByRole('textbox',{name:'查找会话'}).fill('不存在的合成会话');
  await expect(input).toHaveValue('尚未发送的合成草稿');
  await page.getByRole('heading',{name:'会话管理'}).press('Escape');
  await expect(page.getByRole('button',{name:'会话',exact:true})).toBeFocused();
  await input.fill('发送合成消息');
  await page.getByRole('button',{name:'发送',exact:true}).click();
  await expect(page.getByText('发送后的合成回答',{exact:true})).toBeVisible();
  await expect(input).toHaveValue('');
  await expect(input).toBeInViewport();
  await page.locator('.messages article').last().getByRole('button',{name:'没想起已有记忆'}).click();
  await expect(page.getByRole('status')).toContainText('本轮记忆表现已记录');
  await page.reload();
  await expect(page.getByText('发送后的合成回答',{exact:true})).toBeVisible();
  if (size.width <= 760) await page.getByRole('button',{name:'展开导航'}).click();
  await page.getByRole('link',{name:'系统总览',exact:true}).click();
  await expect(page.getByRole('heading',{name:'系统总览'})).toBeVisible();
  if (size.width > 760) await expect(page.getByText('查看服务、回答与圆屏链路详情')).toBeInViewport();
  await page.goBack();
  await expect(page.getByText('会话已恢复，可以继续聊。')).toBeVisible();
  await expect(page.getByRole('heading',{name:'聊聊今天'})).toBeVisible();
  await expect(input).toBeInViewport();
  await page.goForward();
  await expect(page.getByRole('heading',{name:'系统总览'})).toBeVisible();
  await page.goBack();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 1)).toBe(true);
  expect(posts.filter(path => path.endsWith('/messages'))).toHaveLength(1);
  await page.screenshot({path:test.info().outputPath('chat-workspace.png')});
});
