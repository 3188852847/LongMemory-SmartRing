import {expect, test, type Page} from '@playwright/test';

function syntheticWav() {
  const data = Buffer.alloc(44 + 16000 * 2 * 3);
  data.write('RIFF',0); data.writeUInt32LE(data.length-8,4); data.write('WAVEfmt ',8);
  data.writeUInt32LE(16,16); data.writeUInt16LE(1,20); data.writeUInt16LE(1,22);
  data.writeUInt32LE(16000,24); data.writeUInt32LE(32000,28); data.writeUInt16LE(2,32);
  data.writeUInt16LE(16,34); data.write('data',36); data.writeUInt32LE(data.length-44,40);
  return data;
}
const builtinSkin = {
  schema_version:1,id:'rose-night-v1',name:'合成皮肤',description:'浏览器任务合成档案',
  target:{board:'viewe-smartring-plus',width:360,height:360,color_format:'RGB565',skin_api:1},
  palette:{background:'#171B26',background_edge:'#090B10',foreground:'#F7F4F8',muted:'#CBD1DC',accent:'#DF72A8',listening:'#69D5FF',thinking:'#F7C65A',happy:'#7DE2B8',concerned:'#8AA8FF',warning:'#F0B34B',error:'#F16C73',charging:'#8DE39E'},
  face:{eye_width:22,eye_height:36,mouth_width:38},motion:{blink_seconds:5.4,speaking_seconds:.52},manifest_sha256:'a'.repeat(64),
};
async function mockWorkspace(page:Page) {
  const writes:Array<{path:string;body:Record<string, unknown>}> = [];
  const unexpected:string[] = [];
  let profile = {version:1,reference_id:null as string|null,transcript:'',style:''};
  let digest = 'a'.repeat(64);
  const references = [{id:'synthetic-reference',label:'合成录音',transcript:'这是合成原文。',duration_seconds:3,sha256:'b'.repeat(64)}];
  let skins = [builtinSkin];
  const snapshot = () => ({profile,profile_digest:digest,references,preview_text:'固定合成测试文本',service_state:'ready',activation:'next_synthesis'});
  // 未定义 API 直接返回错误，绝不透传到服务或日用接口。
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    const body = request.method() === 'GET' ? {} : request.postDataJSON() ?? {};
    if (request.method() !== 'GET') writes.push({path,body});
    let response:unknown;
    if (path === '/api/session') response = {csrf:'synthetic-token'};
    else if (path === '/api/chat-config') response = {enabled:true,model:'fake',role:'合成助手',provider:'fake'};
    else if (path === '/api/voice-profile' && request.method() === 'GET') response = snapshot();
    else if (path === '/api/voice-references') response = {item:references[0],references};
    else if (path === '/api/voice-profile/preview') {await route.fulfill({contentType:'audio/wav',body:syntheticWav()}); return;}
    else if (path === '/api/voice-profile') {
      if (body.expected_profile_digest !== digest) {await route.fulfill({status:409,json:{error:'voice_profile_changed'}});return;}
      profile = body.profile; digest = 'c'.repeat(64); response = snapshot();
    } else if (path === '/api/round-skins/custom') {
      skins = [builtinSkin,{...builtinSkin,id:'local-custom-v1',name:'我的自定义皮肤',palette:{...builtinSkin.palette,...body.palette},face:body.face,manifest_sha256:'d'.repeat(64)}];
      response = {enabled:true,selected_skin:'rose-night-v1',custom_skin_id:'local-custom-v1',skins};
    } else if (path === '/api/round-skins') response = {enabled:true,selected_skin:'rose-night-v1',custom_skin_id:'local-custom-v1',skins};
    else if (path === '/api/round-wallpapers/device') response = {wallpaper_api:1,active_valid:false,rollback_available:false};
    else if (path === '/api/round-skins/device') {await route.fulfill({status:409,json:{error:'device_offline'}});return;}
    else if (path === '/api/round-wallpapers') response = {enabled:true,items:[],device_delivery:{enabled:false}};
    else {unexpected.push(path);await route.fulfill({status:503,json:{error:'synthetic_not_configured'}});return;}
    await route.fulfill({json:response});
  });
  return {writes,unexpected};
}

for (const viewport of [{width:1366,height:768},{width:1440,height:900},{width:390,height:844}]) {
  test(`设置分类、声音草稿与圆屏编辑 ${viewport.width}×${viewport.height}`, async ({page}) => {
    await page.setViewportSize(viewport);
    const {writes,unexpected} = await mockWorkspace(page);
    await page.goto('/settings?tab=voice');
    for (const name of ['设置总览','模型与服务','记忆后端','助手表达','声音与克隆','外观与阅读','主动交流']) {
      const tab = page.getByRole('tab',{name,exact:true});
      await expect(tab).toBeVisible();
      if (viewport.width > 600) {
        const box = await tab.boundingBox();
        expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
      }
    }
    await page.getByLabel('表达指令（可留空）').fill('温柔亲切地说话');
    await page.getByRole('tab',{name:'助手表达',exact:true}).click();
    await page.goBack();
    await expect(page.getByLabel('表达指令（可留空）')).toHaveValue('温柔亲切地说话');
    await page.getByText('添加参考录音',{exact:true}).click();
    await page.getByLabel('参考录音文件').setInputFiles({name:'合成录音.wav',mimeType:'audio/wav',buffer:syntheticWav()});
    await page.getByLabel('录音原文',{exact:true}).fill('这是合成原文。');
    await page.getByRole('button',{name:'上传到参考库'}).click();
    await expect(page.getByText(/录音已加入参考库/)).toBeVisible();
    expect(writes.some(item=>item.path==='/api/voice-profile')).toBe(false);
    await page.getByRole('button',{name:'试听草稿',exact:true}).click();
    await expect(page.getByLabel('CosyVoice 声音草稿试听')).toBeVisible();
    expect(writes.some(item=>item.path==='/api/voice-profile')).toBe(false);
    await page.getByRole('button',{name:'保存日用声线',exact:true}).click();
    await expect(page.getByText(/从下一次合成开始使用/)).toBeVisible();
    expect(writes.find(item=>item.path==='/api/voice-profile')?.body.expected_profile_digest).toBe('a'.repeat(64));
    await page.goto('/display-preview');
    await expect(page.getByRole('region',{name:'圆屏模拟画布'})).toBeVisible();
    await page.getByRole('tab',{name:'皮肤',exact:true}).click();
    await page.getByRole('button',{name:'从当前皮肤开始编辑'}).click();
    await page.getByLabel('眼睛宽度',{exact:true}).fill('30');
    await page.getByLabel('眼睛宽度',{exact:true}).press('Tab');
    await expect(page.locator('.round-display')).toHaveCSS('--round-eye-width','30px');
    if (viewport.width > 1100) {
      const canvas = await page.getByRole('region',{name:'圆屏模拟画布'}).boundingBox();
      const editor = await page.getByRole('region',{name:'本机自定义皮肤编辑器'}).boundingBox();
      expect(canvas!.x + canvas!.width).toBeLessThanOrEqual(editor!.x);
    }
    await page.getByRole('tab',{name:'实机验证'}).click();
    await expect(page.getByRole('button',{name:'应用到真机',exact:true})).toBeDisabled();
    await page.goBack();
    await expect(page.getByLabel('眼睛宽度',{exact:true})).toHaveValue('30');
    await page.getByRole('button',{name:'保存为“我的自定义皮肤”'}).click();
    await expect(page.getByRole('region',{name:'本机自定义皮肤编辑器'})).toHaveCount(0);
    await page.getByRole('tab',{name:'实机验证'}).click();
    await page.getByRole('button',{name:'检测真机皮肤能力'}).click();
    await expect(page.getByText('圆屏当前离线',{exact:true})).toBeVisible();
    await expect(page.getByRole('button',{name:'应用到真机',exact:true})).toBeDisabled();
    expect(writes.some(item=>item.path==='/api/round-skins/device')).toBe(false);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    expect(unexpected).toEqual([]);
  });
}

test('大字号、减少动画与键盘分类导航', async ({page}) => {
  await page.setViewportSize({width:1366,height:768});
  await page.emulateMedia({reducedMotion:'reduce'});
  await mockWorkspace(page);
  await page.goto('/settings?tab=appearance');
  await page.getByRole('combobox',{name:'字号',exact:true}).click();
  await page.locator('.ant-select-dropdown:visible').getByText('更大',{exact:true}).click();
  await expect(page.locator('html')).toHaveAttribute('data-reading','larger');
  await page.getByRole('tab',{name:'声音与克隆',exact:true}).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('表达指令（可留空）')).toBeVisible();
  await page.goto('/display-preview');
  await expect(page.locator('.round-face .eye').first()).toHaveCSS('animation-name','none');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
