import {mechanismFixture} from '../src/tests/fixtures/hyMechanisms';
import {test,expect,type Page} from '@playwright/test';

const item={item_id:'synthetic-1',content:'周末会去河边散步，通常带着相机。希望智慧圆屏记住这些小习惯，在合适的时候自然聊起。',kind:'l2_fact',revision:'a'.repeat(64),source_event_ids:['synthetic-source-one','synthetic-source-two'],recorded_at:'2026-10-19T09:30:00Z',valid_from:null,valid_to:null,state:'ACTIVE'};
const status={method:'hy_memory_pro_chat',write_enabled:true,use_enabled:true,management_capabilities:{listing:true,detail:true},deferred_observation:{supported:true,awaiting_completion:1,running_or_queued:0,last_result:{state:'completed',warning_code:null}}};
const caps={protocol:1,profile:true,history:true,operations:true,correction:true,deletion:true,write_enabled:true,use_enabled:true,revision_check:'exclusive_owner_serialized',native_atomic_revision:false};
async function synthetic(page:Page,options:{empty?:boolean;error?:boolean;unsupported?:boolean;uncertain?:boolean;long?:boolean;delay?:boolean}={}) {
  let releaseList=()=>{};const listGate=options.delay?new Promise<void>(resolve=>{releaseList=resolve;}):Promise.resolve();
  const writes:string[]=[];const errors:string[]=[];const external:string[]=[];const unexpected:string[]=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',async route=>{const request=route.request();const url=new URL(request.url());
    if(url.hostname!=='127.0.0.1'){external.push(url.origin);await route.abort();return;}
    if(!url.pathname.startsWith('/api/')){await route.continue();return;}
    const ok=(data:unknown,status=200)=>route.fulfill({status,json:data});
    if(url.pathname==='/api/memory-engine/identity')return ok({schema_version:1,configured:true,method:'hy_memory_pro_chat',representation:'method_defined',legacy_sqlite:false,state:'available'});
    if(url.pathname==='/api/memory-engine/hy/mechanisms')return ok(mechanismFixture);
    if(url.pathname==='/api/session')return ok({csrf:'synthetic-csrf'});
    if(url.pathname==='/api/memory-config')return ok({configured:true,representation:'method_defined',method:'hy_memory_pro_chat',database:null,management_capabilities:{listing:true,detail:true}});
    if(url.pathname==='/api/memory-engine')return ok(status);
    if(url.pathname==='/api/memory-engine/hy/workspace')return options.unsupported?ok({error:'memory_backend_capability_unsupported'},501):ok(caps);
    if(url.pathname==='/api/memory-engine/items'){
      await listGate;
      if(options.error)return ok({error:'hy_management_unavailable'},503);
      const offset=Number(url.searchParams.get('offset')??0);
      return ok({items:options.empty?[]:offset?[{...item,item_id:'synthetic-last',content:'最后一条合成记忆。',source_event_ids:null,recorded_at:null}]:[item,{...item,item_id:'synthetic-2',kind:'l3_summary',content:'最近聊过一次工作节奏：上午集中写作，下午处理杂事。',source_event_ids:null,recorded_at:null},{...item,item_id:'synthetic-3',content:options.long?'很长的合成内容。'.repeat(160):'家里的猫叫豆包，喜欢趴在窗台晒太阳。',source_event_ids:[]},{...item,item_id:'synthetic-4',kind:'l4_identity',content:'更喜欢先听建议的理由，再决定要不要行动。'}],total:options.empty?0:26,offset,limit:25});
    }
    if(url.pathname==='/api/memory-engine/items/synthetic-1')return ok(item);
    if(url.pathname.endsWith('/sources/synthetic-source-one'))return ok({event_id:'synthetic-source-one',role:'user',content:'我周末一般去河边，带着相机随便走走。',occurred_at:'2026-10-19T09:29:00Z',state:'completed',session_id:'synthetic-session',attempt_id:'synthetic-attempt'});
    if(url.pathname.endsWith('/sources/synthetic-source-two'))return ok({error:'memory_item_or_source_not_found'},404);
    if(url.pathname==='/api/memory-engine/hy/profile')return ok({item:{...item,kind:'l0_basic_info',content:'喜欢散步与摄影；希望交流先说明理由。\n这份合成画像需要沿来源核对。'}});
    if(url.pathname==='/api/memory-engine/hy/operations')return ok({items:options.uncertain?[{request_id:'synthetic-operation',action:'correct',item_id:'synthetic-1',source_event_id:'synthetic-source-one',revision:item.revision,state:'uncertain',occurred_at:'2026-10-19T10:00:00Z',error_code:'hy_management_outcome_uncertain'}]:[],total:options.uncertain?1:0,offset:0,limit:25});
    if(url.pathname.endsWith('/history'))return ok({items:[{event:'UPDATE',old_memory:'周末喜欢在公园散步。',new_memory:item.content,created_at:'2026-10-19T09:30:00Z'}],limited:false,recording_complete:false});
    if(url.pathname.endsWith('/corrections')||url.pathname.endsWith('/deletion')){writes.push(request.postData()??'');await new Promise(resolve=>setTimeout(resolve,150));return options.uncertain?ok({error:'hy_management_outcome_uncertain'},503):ok({state:'completed',request_id:JSON.parse(request.postData()!).request_id,replayed:false,platform_sources_preserved:true});}
    unexpected.push(url.pathname);return ok({error:'unexpected_synthetic_endpoint'},501);
  });
  return {writes,errors,external,unexpected,releaseList};
}
async function noHorizontalOverflow(page:Page) {expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true);}

for(const viewport of [{width:1920,height:1080},{width:1366,height:768},{width:390,height:844}])test(`内容、详情与来源 ${viewport.width}`,async({page},testInfo)=>{
  await page.setViewportSize(viewport);const state=await synthetic(page);
  await page.goto('/memories');await expect(page.getByRole('heading',{name:'我的记忆',exact:true})).toBeVisible();
  await expect(page.getByText(item.content,{exact:true})).toBeVisible();await noHorizontalOverflow(page);
  await page.screenshot({animations:'disabled',path:testInfo.outputPath(`hy-items-${viewport.width}.png`),fullPage:true});
  await page.getByRole('button',{name:'查看详情'}).first().click();
  const drawer=page.getByRole('dialog',{name:'记忆详情'});await expect(drawer).toBeVisible();
  const select=drawer.getByRole('combobox',{name:'选择一条来源回看'});await select.selectOption('synthetic-source-one');
  await expect(drawer.getByText('我周末一般去河边，带着相机随便走走。')).toBeVisible();
  await page.screenshot({animations:'disabled',path:testInfo.outputPath(`hy-source-${viewport.width}.png`)});
  await drawer.getByRole('button',{name:'核对并读取 SDK 历史'}).click();await expect(drawer.getByText('SDK 历史记录当前已关闭；平台管理操作审计仍可单独核对。')).toBeVisible();
  await expect(drawer.getByRole('button',{name:'核对并读取 SDK 历史'})).toBeFocused();
  await page.keyboard.press('Escape');await expect(drawer).not.toBeVisible();
  await expect(page.getByRole('button',{name:'查看详情'}).first()).toBeFocused();
  await page.getByRole('button',{name:'下一页'}).click();await expect(page.getByText('最后一条合成记忆。')).toBeVisible();
  await page.reload();await expect(page.getByText('最后一条合成记忆。')).toBeVisible();
  expect(state.errors).toEqual([]);expect(state.external).toEqual([]);expect(state.unexpected).toEqual([]);expect(state.writes).toEqual([]);
});

test('大字号、长内容、减少动态、键盘与纠正草稿',async({page},testInfo)=>{
  await page.setViewportSize({width:1366,height:768});await page.emulateMedia({reducedMotion:'reduce'});const state=await synthetic(page,{long:true});
  await page.goto('/memories');await page.evaluate(()=>document.documentElement.dataset.reading='larger');
  await expect(page.getByText(item.content,{exact:true})).toBeVisible();await noHorizontalOverflow(page);
  await page.getByRole('button',{name:'查看详情'}).first().focus();await page.keyboard.press('Enter');
  const drawer=page.getByRole('dialog',{name:'记忆详情'});await drawer.getByRole('button',{name:'纠正这条记忆'}).click();
  const modal=page.getByRole('dialog',{name:'纠正这条记忆'});await expect(modal).toBeVisible();
  await modal.getByLabel('正确的内容').fill('周末现在更喜欢去植物园散步。');
  await page.screenshot({animations:'disabled',path:testInfo.outputPath('hy-correction-large.png')});
  await page.keyboard.press('Tab');expect(await modal.evaluate(el=>el.contains(document.activeElement))).toBe(true);
  await modal.getByRole('checkbox').check();await modal.getByRole('button',{name:'保存纠正'}).dblclick();
  await expect(page.getByText(/纠正已完成。平台原话保留/)).toBeVisible();expect(state.writes).toHaveLength(1);expect(state.errors).toEqual([]);
});

test('画像、变化、处理状态和旧书签守卫',async({page},testInfo)=>{
  const state=await synthetic(page);
  await page.goto('/personas');await expect(page).toHaveURL(/\/memories\?view=profile$/);
  await expect(page.getByText(/这份合成画像需要沿来源核对/)).toBeVisible();await page.screenshot({animations:'disabled',path:testInfo.outputPath('hy-profile.png'),fullPage:true});
  await page.getByRole('button',{name:'记录与变化',exact:true}).click();await expect(page.getByText('还没有管理操作记录')).toBeVisible();
  await page.getByRole('button',{name:'处理状态',exact:true}).click();await expect(page.getByText('等待设备完成回执')).toBeVisible();
  expect(state.unexpected).toEqual([]);expect(state.errors).toEqual([]);
});

test('加载、空、失败、未知来源及能力拒绝',async({browser},testInfo)=>{
  for(const name of ['delay','empty','error','unsupported'] as const){const page=await browser.newPage({viewport:{width:390,height:844}});const state=await synthetic(page,{[name]:true});
    await page.goto('/memories');
    if(name==='delay'){await expect(page.getByRole('status',{name:'正在读取记忆'})).toBeVisible();state.releaseList();}
    if(name==='empty')await expect(page.getByText('这一页还没有记忆条目')).toBeVisible();
    else if(name==='error')await expect(page.getByText('记忆列表读取失败')).toBeVisible();
    else await expect(page.getByText(item.content,{exact:true})).toBeVisible();
    if(name==='unsupported'){await page.getByRole('button',{name:'基本画像',exact:true}).click();await expect(page.getByText('基本画像暂不可读取')).toBeVisible();}
    await noHorizontalOverflow(page);await page.screenshot({animations:'disabled',path:testInfo.outputPath(`hy-state-${name}.png`),fullPage:true});expect(state.errors).toEqual([]);expect(state.unexpected).toEqual([]);await page.close();
  }
});

test('未知结果明确显示并阻止重新提交',async({page},testInfo)=>{
  const state=await synthetic(page,{uncertain:true});await page.goto('/memories?view=activity');
  await expect(page.getByText('结果不确定',{exact:true})).toBeVisible();await page.getByRole('button',{name:'核对条目'}).click();
  await expect(page.getByText('这条记忆有未确认操作')).toBeVisible();await expect(page.getByRole('button',{name:'纠正这条记忆'})).toBeDisabled();
  await page.screenshot({animations:'disabled',path:testInfo.outputPath('hy-uncertain.png'),fullPage:true});expect(state.writes).toEqual([]);
});

test('窄屏大字号与跨页草稿保护',async({page},testInfo)=>{
  await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:'reduce'});
  const state=await synthetic(page);
  await page.route('**/synthetic-start',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:'<meta charset="utf-8"><a href="/memories">打开合成记忆页</a>'}));
  await page.goto('/synthetic-start');await page.getByRole('link',{name:'打开合成记忆页'}).click();
  await expect(page.getByText(item.content,{exact:true})).toBeVisible();await page.evaluate(()=>document.documentElement.dataset.reading='larger');
  await noHorizontalOverflow(page);await page.screenshot({animations:'disabled',path:testInfo.outputPath('hy-mobile-large.png'),fullPage:true});
  await page.getByRole('button',{name:'查看详情'}).first().click();await page.getByRole('button',{name:'纠正这条记忆'}).click();
  const modal=page.getByRole('dialog',{name:'纠正这条记忆'});await modal.getByLabel('正确的内容').fill('合成草稿仍在，不应被浏览器返回丢弃。');
  // 第一次返回只撤销详情的 query 坐标，仍在同一页面；草稿应继续保留。
  await page.goBack();await expect(modal.getByLabel('正确的内容')).toHaveValue('合成草稿仍在，不应被浏览器返回丢弃。');
  const dialog=page.waitForEvent('dialog');const back=page.goBack({timeout:5000}).catch(()=>null);const warning=await dialog;
  expect(warning.type()).toBe('beforeunload');await warning.dismiss();await back;
  await expect(modal.getByLabel('正确的内容')).toHaveValue('合成草稿仍在，不应被浏览器返回丢弃。');expect(state.writes).toEqual([]);
});
