import {expect,test} from '@playwright/test';

test('全新浏览器会话的身份与聊天并发挂载共享Cookie和CSRF，可直接发送',async({page})=>{
  let bootstraps=0;
  const rejected:string[]=[];
  page.on('request',request=>{if(new URL(request.url()).pathname==='/api/session')bootstraps++;});
  page.on('response',response=>{if(response.status()===403)rejected.push(new URL(response.url()).pathname);});
  // 使用实际一次性 Fake HTTP 主机；不拦截会话或写请求来替代真实安全检查。
  await page.goto('/chat-react');
  const input=page.getByRole('textbox',{name:'消息'});
  await expect(input).toBeEnabled();
  await input.fill('不要记住：合成会话并发检查');
  const response=page.waitForResponse(response=>response.request().method()==='POST'&&new URL(response.url()).pathname.endsWith('/messages'));
  await page.getByRole('button',{name:'发送',exact:true}).click();
  expect((await response).status()).toBe(200);
  await expect(page.locator('.bubble.user').getByText('不要记住：合成会话并发检查',{exact:true})).toBeVisible();
  await expect(input).toBeEnabled();
  expect(bootstraps).toBe(1);
  expect(rejected).toEqual([]);
});
