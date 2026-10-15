import {createHash} from 'node:crypto';
import {expect,test,type Page} from '@playwright/test';

async function preferences(page:Page,size='normal',motion='full') {
  await page.addInitScript(({size,motion})=>localStorage.setItem('longmemory:chat-appearance:v3',JSON.stringify({theme:'future',size,motion,density:'comfortable',chatWidth:'focused'})),{size,motion});
}
async function chooseRadio(page:Page,name:string) {const radio=page.getByRole('radio',{name,exact:true});await radio.locator('xpath=ancestor::label').click();await expect(radio).toBeChecked();}
async function fits(page:Page) {expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);}

for(const [width,height] of [[1366,768],[1440,900],[390,844]]) test(`日常聊天与实验准备 ${width}×${height}`,async({page},info)=>{
  await page.setViewportSize({width,height});await preferences(page);
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/chat-react');
  const input=page.getByRole('textbox',{name:'消息'});await expect(input).toBeEnabled();
  for(let index=0;index<8;index++) {await input.fill(`P合成短句 ${width} ${index}`);await page.getByRole('button',{name:'发送',exact:true}).click();await expect(input).toBeEnabled();await expect(input).toHaveValue('');}
  const article=page.locator('.messages article').last();
  await expect(article.locator('.speech-player')).not.toBeVisible();
  await expect(article.getByRole('button',{name:'没想起已有记忆'})).toHaveCount(0);
  const summary=article.locator('summary');await summary.focus();await page.keyboard.press('Enter');
  await expect(article.getByRole('button',{name:'网页朗读',exact:true})).toBeVisible();
  let speechRequests=0;
  await page.route('**/api/speech',route=>{speechRequests++;return route.fulfill({status:503,json:{error:'tts_service_unavailable'}});});
  await article.getByRole('button',{name:'网页朗读',exact:true}).click();
  await expect(article.getByText(/当前 TTS 服务没有就绪/)).toBeVisible();
  await expect(article.getByRole('link',{name:'打开声音设置'})).toBeVisible();
  await summary.click();await expect(article.locator('.speech-player')).not.toBeVisible();
  await summary.focus();await page.keyboard.press('Enter');
  await expect(article.getByText(/当前 TTS 服务没有就绪/)).toBeVisible();
  expect(speechRequests).toBe(1);
  await article.getByRole('button',{name:'没想起已有记忆'}).click();
  await expect(summary).toContainText('已记录');
  await article.getByRole('button',{name:/查看第 \d+ 轮记忆证据/}).click();
  await expect(page.getByRole('complementary',{name:'记忆证据面板'})).toBeVisible();
  await page.getByRole('button',{name:'收起面板'}).click();
  const messages=page.getByRole('region',{name:'聊天记录'});
  await messages.evaluate(node=>{node.scrollTop=0;node.dispatchEvent(new Event('scroll'));});
  await input.fill('P合成：回看时新增一条');await page.getByRole('button',{name:'发送',exact:true}).click();await expect(input).toHaveValue('');
  expect(await messages.evaluate(node=>node.scrollTop)).toBeLessThan(60);
  const box=await input.boundingBox();expect(box!.y).toBeGreaterThanOrEqual(0);expect(box!.y+box!.height).toBeLessThanOrEqual(height);
  await fits(page);await page.screenshot({path:info.outputPath('chat-lookback.png')});
  await page.goto('/experiments-react');
  await page.getByRole('button',{name:'查看准备步骤与命令'}).click();
  await expect(page.getByRole('heading',{name:'准备实验档案',exact:true})).toBeFocused();
  await expect(page.locator('.experiment-preparation-command').first()).toContainText('--provider fake --split dev');
  await expect(page.locator('.experiment-preparation-command').last()).toContainText('请替换为上一步输出的实际编号');
  await fits(page);await page.screenshot({path:info.outputPath('experiment-preparation.png')});
  await page.getByRole('button',{name:'前往运行实验核对能力'}).click();
  await expect(page.getByRole('button',{name:'没有可用来源？查看准备步骤'})).toBeVisible();
  await expect(page.getByRole('button',{name:'预检与核对预算'})).toBeDisabled();
  expect(errors).toEqual([]);
});

test('真实 Otto 循环、21 张解码、暂停与网页状态优先级',async({page},info)=>{
  test.skip(!process.env.SMART_RING_TEST_OTTO_ASSETS,'需要所有者已下载的固定资源目录显式输入');
  await preferences(page);await page.setViewportSize({width:1440,height:900});
  const writes:string[]=[];page.on('request',request=>{if(request.method()!=='GET')writes.push(new URL(request.url()).pathname);});
  await page.goto('/display-preview');
  const image=page.locator('.otto-screen img');await expect(image).toHaveAttribute('src',/neutral\/loop.gif$/);
  await expect.poll(()=>image.evaluate(node=>(node as HTMLImageElement).naturalWidth)).toBe(240);
  const geometry=await page.locator('.otto-screen').evaluate(node=>{const screen=node.getBoundingClientRect(),img=node.querySelector('img')!.getBoundingClientRect();return {screen:screen.width,image:img.width,margin:img.x-screen.x,background:getComputedStyle(node).backgroundColor};});
  expect(geometry.screen).toBeCloseTo(360,0);expect(geometry.image).toBeCloseTo(240,0);expect(geometry.margin).toBeCloseTo(60,0);expect(geometry.background).toBe('rgb(0, 0, 0)');
  await chooseRadio(page,'思考');await expect(image).toHaveAttribute('src',/thinking\/loop.gif$/);
  async function pixels(){return createHash('sha256').update(await image.screenshot()).digest('hex');}
  await expect.poll(()=>image.evaluate(node=>(node as HTMLImageElement).complete && (node as HTMLImageElement).naturalWidth===240)).toBe(true);
  const frames=new Set<string>();for(let index=0;index<10;index++){frames.add(await pixels());await page.waitForTimeout(200);}expect(frames.size).toBeGreaterThan(1);
  await page.getByRole('button',{name:'暂停动画'}).click();await expect(image).toHaveAttribute('src',/thinking\/still.gif$/);
  await expect.poll(()=>image.evaluate(node=>(node as HTMLImageElement).complete && (node as HTMLImageElement).naturalWidth===240)).toBe(true);
  const still=await pixels();await page.waitForTimeout(700);const afterPause=await pixels();expect(afterPause).toBe(still);await info.attach('otto-animation-observation',{body:JSON.stringify({geometry,loopFrameHashes:[...frames],still,afterPause}),contentType:'application/json'});
  await chooseRadio(page,'被打断');await expect(image).toHaveAttribute('src',/surprised\/still.gif$/);await expect(image).toHaveAttribute('src',/neutral\/still.gif$/);
  await chooseRadio(page,'逐张素材检查');
  const names=['neutral','happy','laughing','funny','sad','angry','crying','loving','embarrassed','surprised','shocked','thinking','winking','cool','relaxed','delicious','kissy','confident','sleepy','silly','confused'];
  for(const name of names){await page.getByRole('combobox',{name:'循环表情',exact:true}).click();await page.locator('.ant-select-dropdown:visible .ant-select-item-option-content').filter({hasText:new RegExp(` · ${name}$`)}).click();await expect(image).toHaveAttribute('src',new RegExp(`/${name}/still.gif$`));await expect.poll(()=>image.evaluate(node=>(node as HTMLImageElement).complete && (node as HTMLImageElement).naturalWidth===240)).toBe(true);}
  await expect(page.locator('.ant-select-dropdown:visible')).toHaveCount(0);await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:info.outputPath('otto-native.png'),fullPage:true});
  await page.route('**/api/otto-preview/thinking/still.gif',route=>route.abort());
  await chooseRadio(page,'跟随网页阶段');
  await chooseRadio(page,'思考');
  await expect(image).toHaveAttribute('src',/neutral\/still.gif$/);
  await expect(page.getByText(/thinking 不可用，回退平静/)).toBeVisible();
  expect(writes).toEqual([]);
});

test('21 张 Otto 原始 GIF 均有真实画面变化',async({page},info)=>{
  test.skip(!process.env.SMART_RING_TEST_OTTO_ASSETS,'需要明确绑定已经下载的固定资源');
  // 逐张等待一次完整 GIF 周期内的变化；只扩大这条批量检查的时间预算。
  test.setTimeout(120_000);
  await preferences(page);await page.setViewportSize({width:1440,height:900});await page.goto('/display-preview');
  await chooseRadio(page,'逐张素材检查');
  const image=page.locator('.otto-screen img');
  const observations:Array<{name:string;hashes:string[];elapsed_ms:number}>=[];
  for(const name of ['neutral','happy','laughing','funny','sad','angry','crying','loving','embarrassed','surprised','shocked','thinking','winking','cool','relaxed','delicious','kissy','confident','sleepy','silly','confused']) {
    await page.getByRole('combobox',{name:'循环表情',exact:true}).click();
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option-content').filter({hasText:new RegExp(` · ${name}$`)}).click();
    await expect(page.locator('.ant-select-dropdown:visible')).toHaveCount(0);
    await expect(image).toHaveAttribute('src',new RegExp(`/${name}/loop.gif$`));
    await expect.poll(()=>image.evaluate(node=>(node as HTMLImageElement).complete && (node as HTMLImageElement).naturalWidth===240)).toBe(true);
    const start=Date.now(),hashes=new Set<string>();
    while(hashes.size<2 && Date.now()-start<3200) {
      const shot=await image.screenshot();const hash=createHash('sha256').update(shot).digest('hex');
      if(!hashes.has(hash)) {hashes.add(hash);await info.attach(`${name}-frame-${hashes.size}`,{body:shot,contentType:'image/png'});}
      if(hashes.size<2) await page.waitForTimeout(100);
    }
    observations.push({name,hashes:[...hashes],elapsed_ms:Date.now()-start});
    expect(hashes.size,`${name} 应有实际显示帧变化`).toBeGreaterThan(1);
  }
  await info.attach('otto-21-loop-observations',{body:JSON.stringify(observations),contentType:'application/json'});
});

for(const width of [1366,390]) test(`Otto 更大字号/减少动态/失败与无素材 ${width}`,async({page},info)=>{
  await page.setViewportSize({width,height:width===390?844:768});await preferences(page,'larger','reduce');await page.emulateMedia({reducedMotion:'reduce'});
  await page.goto('/display-preview');
  const image=page.locator('.otto-screen img');
  if(process.env.SMART_RING_TEST_OTTO_ASSETS){await expect(image).toHaveAttribute('src',/neutral\/still.gif$/);}
  for(const label of ['启动','待机','已唤醒','聆听','思考','说话','被打断','没听清','错误']) {const radio=page.getByRole('radio',{name:label,exact:true});await radio.locator('xpath=ancestor::label').click();await expect(radio).toBeChecked();const visible=radio.locator('xpath=ancestor::label');const measured=await visible.evaluate(node=>({scroll:node.scrollWidth,client:node.clientWidth,label:node.textContent,width:node.getBoundingClientRect().width}));expect(measured.scroll<=measured.client+1,JSON.stringify(measured)).toBe(true);const text=visible.getByText(label,{exact:true});expect(await text.evaluate(node=>getComputedStyle(node).textOverflow)).not.toBe('ellipsis');const bounds=await text.boundingBox(),target=await visible.boundingBox();expect(bounds!.x).toBeGreaterThanOrEqual(target!.x);expect(bounds!.x+bounds!.width).toBeLessThanOrEqual(target!.x+target!.width);}
  await fits(page);await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:info.outputPath('otto-large-reduce.png'),fullPage:true});
  await page.route('**/api/otto-preview',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({commit:'fixed',valid_count:0,items:[]})}));
  const refresh=page.getByRole('button',{name:'重新核对素材'});await refresh.focus();await page.keyboard.press('Enter');
  await expect(page.getByText('可用素材 0/21')).toBeVisible();await expect(image).toHaveCount(0);await expect(page.getByText('素材不可用',{exact:true})).toBeVisible();
  await page.route('**/api/otto-preview',route=>route.abort());await refresh.click();await expect(page.getByText('素材清单读取失败')).toBeVisible();
  await fits(page);
});
