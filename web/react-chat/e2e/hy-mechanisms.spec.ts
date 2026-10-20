import {test,expect,type Page} from '@playwright/test';
import {mechanismFixture} from '../src/tests/fixtures/hyMechanisms';
import {layerPage} from '../src/tests/fixtures/hyLayerData';
import type {HyLayerId} from '../src/api/hyLayerData';
import {largerReading} from './hy-test-appearance';

const hyIdentity={schema_version:1,configured:true,method:'hy_memory_pro_chat',representation:'method_defined',legacy_sqlite:false,state:'available'};
const legacyIdentity={...hyIdentity,method:'longmemory_daily_llm_v2',representation:'atomic_fact',legacy_sqlite:true};
const entry={item_id:'synthetic-item',content:'合成用户周末喜欢沿河散步。',kind:'l2_fact',revision:'a'.repeat(64),source_event_ids:['synthetic-source'],recorded_at:null,valid_from:null,valid_to:null,state:'active'};
async function synthetic(page:Page,options:{legacy?:boolean;identityBusy?:boolean;uninitialized?:boolean;gateIdentity?:boolean;mechanismsBusy?:boolean;catalog?:'empty'|'mismatch'|'delay'}={}) {
  const calls:Array<{path:string;method:string}>=[];const errors:string[]=[];const external:string[]=[];
  let identityBusy=Boolean(options.identityBusy);let mechanismsBusy=Boolean(options.mechanismsBusy);let releaseIdentity=()=>{};
  const gate=options.gateIdentity?new Promise<void>(resolve=>{releaseIdentity=resolve;}):Promise.resolve();
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url());
    if(url.hostname!=='127.0.0.1'){external.push(url.origin);return route.abort();}
    if(!url.pathname.startsWith('/api/'))return route.continue();
    calls.push({path:url.pathname,method:request.method()});
    const ok=(json:unknown,status=200)=>route.fulfill({status,json});
    if(url.pathname==='/api/session')return ok({csrf:'synthetic-csrf'});
    if(url.pathname==='/api/memory-engine/identity'){
      await gate;if(identityBusy)return ok({error:'memory_identity_busy'},503);
      return ok(options.uninitialized?{...legacyIdentity,method:null,state:'not_initialized'}:options.legacy?legacyIdentity:hyIdentity);
    }
    if(url.pathname==='/api/memory-engine/hy/mechanisms'){
      if(options.catalog==='delay')await new Promise(resolve=>setTimeout(resolve,1200));
      return mechanismsBusy?ok({error:'hy_mechanisms_busy'},503):ok(options.catalog==='empty'?{...mechanismFixture,mechanisms:[],layers:[]}:options.catalog==='mismatch'?{...mechanismFixture,sdk:{...mechanismFixture.sdk,version:'2.0.4'}}:mechanismFixture);
    }
    if(url.pathname.startsWith('/api/memory-engine/hy/layers/'))return ok(layerPage(url.pathname.split('/').pop() as HyLayerId));
    if(url.pathname==='/api/chat-config')return ok({enabled:true,database:'synthetic-only',model:'Synthetic model',role:'合成角色',provider:'fake',method:options.legacy?legacyIdentity.method:hyIdentity.method,retrieval:options.legacy?'keyword_dense_rrf_v1':'hy_chat_default_legacy'});
    if(url.pathname==='/api/device')return ok({connection_count:0,ready:false,read_status_supported:false,set_volume_supported:false});
    if(url.pathname==='/api/runtime-status')return ok({enabled:false,state:'launcher_unavailable',reason:null,services:{}});
    if(url.pathname==='/api/chats'&&request.method()==='GET')return ok({chats:[{chat_id:'synthetic-chat',title:'合成对话',turn_count:1}]});
    if(url.pathname==='/api/chats/synthetic-chat')return ok({chat_id:'synthetic-chat',title:'合成对话',pending:false,turns:[{request_id:'synthetic-turn',input:'合成提问：平时喜欢做什么？',answer:'合成回答：喜欢沿河散步。',status:'completed',writes:null,user_saved:true,duration_ms:5,retrieved:[{item_id:entry.item_id,content:entry.content,source_event_ids:['synthetic-source']}]}]});
    if(url.pathname==='/api/memory-config')return options.legacy?ok({configured:true,database:'synthetic.db',allow_delete:false,allow_clear:false,allow_correction:false}):ok({configured:true,database:null,representation:'method_defined',method:hyIdentity.method,management_capabilities:{listing:true,detail:true}});
    if(url.pathname==='/api/memory-engine')return ok({method:hyIdentity.method,write_enabled:true,use_enabled:true,management_capabilities:{listing:true,detail:true},deferred_observation:{supported:true,awaiting_completion:0,running_or_queued:0,last_result:{state:'not_run',warning_code:null}}});
    if(url.pathname==='/api/memory-engine/hy/workspace')return ok({protocol:1,profile:false,history:true,operations:true,correction:false,deletion:false});
    if(url.pathname==='/api/memory-engine/items')return ok({items:[entry],total:1,offset:0,limit:25});
    if(url.pathname==='/api/memory-engine/items/synthetic-item')return ok(entry);
    if(url.pathname==='/api/memory-engine/sources/synthetic-source')return ok({event_id:'synthetic-source',role:'user',content:'合成原话：我周末一般沿河走走。',occurred_at:null,state:'completed',session_id:'synthetic-chat',attempt_id:'synthetic-attempt'});
    if(url.pathname==='/api/memory-engine/hy/operations')return ok({items:[],total:0,offset:0,limit:25});
    if(url.pathname==='/api/memory-mode')return ok({write_enabled:true,use_enabled:true,scenario_use_enabled:false,persona_use_enabled:false,scenario_available:false,persona_available:false,persistent:false});
    if(url.pathname==='/api/memories')return ok({items:[],total:12,offset:0,limit:25});
    if(url.pathname==='/api/source-messages')return ok({items:[],total:0,offset:0,limit:25});
    if(url.pathname==='/api/memories/daily-review')return ok({local_date:'2026-10-21',items:[],total:0,limited:false,activity_counts:{added:0,corrected:0,changed:0,deleted:0},message_counts:{user:0,assistant:0,total:0,unlinked_user:0},quality_counts:{owner_confirmed_missed_extraction:0},deletions:[],deletions_limited:false});
    if(url.pathname==='/api/chat-memory-feedback/daily')return ok({current_total:0,total:0,current_counts:{},current_items:[],items:[],limited:false,current_limited:false});
    if(url.pathname==='/api/consolidation-status')return ok({background_enabled:false,stages:[]});
    return ok({error:'synthetic_unavailable'},501);
  });
  return {calls,errors,external,releaseIdentity,setIdentityBusy:(value:boolean)=>{identityBusy=value;},setMechanismsBusy:(value:boolean)=>{mechanismsBusy=value;}};
}
async function openNav(page:Page) {const toggle=page.getByRole('button',{name:'展开导航',exact:true});if(await toggle.isVisible())await toggle.click();}
async function noOverflow(page:Page) {
  const overflow=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,
    elements:[...document.querySelectorAll('main *')].filter(el=>el.getBoundingClientRect().right>innerWidth+1).map(el=>({tag:el.tagName,class:el.className,text:el.textContent?.slice(0,100),right:el.getBoundingClientRect().right})).slice(0,15)}));
  expect(overflow.scroll,JSON.stringify(overflow)).toBeLessThanOrEqual(overflow.width+1);
}

for(const viewport of [{width:1920,height:1080},{width:1366,height:768},{width:390,height:844}])test(`全局Hy身份与机制探索 ${viewport.width}`,async({page},info)=>{
  await page.setViewportSize(viewport);const state=await synthetic(page,{gateIdentity:true});
  await page.goto('/overview',{waitUntil:'domcontentloaded'});await expect(page.getByRole('heading',{name:'系统总览',exact:true})).toBeVisible();
  await openNav(page);await expect(page.getByRole('link',{name:'记忆机制',exact:true})).toBeVisible();await expect(page.getByRole('link',{name:'原话与事实'})).toHaveCount(0);
  state.releaseIdentity();await expect(page.getByRole('link',{name:'我的记忆',exact:true})).toBeVisible();
  expect(state.calls.some(call=>call.path==='/api/memory-config'||call.path==='/api/memory-engine/items'||call.path==='/api/memories')).toBe(false);
  await noOverflow(page);await page.screenshot({animations:'disabled',path:info.outputPath(`overview-hy-${viewport.width}.png`),fullPage:true});
  await page.getByRole('link',{name:'记忆机制',exact:true}).click();await expect(page).toHaveURL(/view=mechanisms/);await expect(page.getByText('本次装配声明')).toBeVisible();
  await page.screenshot({animations:'disabled',path:info.outputPath(`mechanisms-path-${viewport.width}.png`),fullPage:true});await noOverflow(page);
  if(viewport.width<760)await page.getByLabel('选择全部机制').selectOption('coding_route');else await page.getByRole('navigation',{name:'完整机制目录'}).getByRole('button',{name:/coding/}).click();
  await expect(page.getByRole('heading',{name:/coding.*代码场景/})).toBeVisible();
  await page.getByRole('button',{name:'L0–L7 分层',exact:true}).click();await page.getByRole('button',{name:/Hy L7/}).click();await expect(page.getByRole('heading',{name:/Hy L7/})).toBeVisible();
  await page.screenshot({animations:'disabled',path:info.outputPath(`mechanisms-layers-${viewport.width}.png`),fullPage:true});await noOverflow(page);
  await page.reload();await expect(page.getByRole('heading',{name:/Hy L7/})).toBeVisible();await openNav(page);
  await expect(page.getByRole('link',{name:'记忆机制',exact:true})).toHaveAttribute('aria-current','page');await expect(page.getByRole('link',{name:'我的记忆',exact:true})).not.toHaveAttribute('aria-current','page');
  expect(state.calls.some(call=>call.path==='/api/memory-engine/items'||call.path==='/api/memory-config')).toBe(false);expect(state.errors).toEqual([]);expect(state.external).toEqual([]);
});

test('全部机制、边界与单条来源有真实入口，SDK历史关闭不假装可读',async({page},info)=>{
  const state=await synthetic(page);await page.goto('/memories?view=mechanisms&mechanism_tab=boundaries');
  await expect(page.getByRole('button',{name:'查看机制与证据'})).toHaveCount(mechanismFixture.mechanisms.length);
  await page.getByRole('button',{name:'查看机制与证据'}).last().click();await expect(page.getByRole('navigation',{name:'完整机制目录'})).toBeVisible();
  await page.getByRole('button',{name:'证据入口',exact:true}).click();await page.getByRole('link',{name:'选择条目核对来源'}).click();
  await expect(page.getByText(entry.content,{exact:true})).toBeVisible();await page.getByRole('button',{name:'查看详情'}).click();
  const drawer=page.getByRole('dialog',{name:'记忆详情'});await drawer.getByLabel('选择一条来源回看').selectOption('synthetic-source');await expect(drawer.getByText('合成原话：我周末一般沿河走走。')).toBeVisible();
  await drawer.getByRole('button',{name:'核对并读取 SDK 历史'}).click();await expect(drawer.getByText(/SDK 历史记录当前已关闭/)).toBeVisible();
  expect(state.calls.some(call=>call.path.endsWith('/history'))).toBe(false);await page.screenshot({animations:'disabled',path:info.outputPath('source-and-history-boundary.png')});expect(state.errors).toEqual([]);
});

test('繁忙保留旧快照且无紧密轮询；首次忙保留未知身份',async({browser},info)=>{
  const page=await browser.newPage();const state=await synthetic(page);await page.goto('/memories?view=mechanisms');await expect(page.getByText('本次装配声明')).toBeVisible();
  state.setMechanismsBusy(true);await page.getByRole('button',{name:'刷新声明'}).click();await expect(page.getByText('上次装配声明')).toBeVisible();await expect(page.getByText(/以下保留上次快照/)).toBeVisible();
  expect(state.calls.filter(call=>call.path.endsWith('/hy/mechanisms'))).toHaveLength(2);await page.screenshot({animations:'disabled',path:info.outputPath('mechanisms-busy-stale.png'),fullPage:true});await page.close();
  const cold=await browser.newPage();const coldState=await synthetic(cold,{identityBusy:true});await cold.goto('/overview');await expect(cold.getByText(/引擎暂忙/)).toBeVisible();await expect(cold.getByRole('link',{name:'原话与事实'})).toHaveCount(0);
  expect(coldState.calls.filter(call=>call.path.endsWith('/identity'))).toHaveLength(1);await cold.close();
});

test('旧引擎与未初始化兼容，method=null不冒充L1统计',async({browser})=>{
  const legacy=await browser.newPage();const state=await synthetic(legacy,{legacy:true});await legacy.goto('/overview');await expect(legacy.getByRole('link',{name:'原话与事实'})).toBeVisible();await expect(legacy.getByText('12 条有效 L1',{exact:true})).toBeVisible();
  await legacy.getByRole('link',{name:'原话与事实'}).click();await expect(legacy.getByRole('heading',{name:'原话与事实',exact:true})).toBeVisible();expect(state.calls.some(call=>call.path.endsWith('/hy/mechanisms'))).toBe(false);expect(state.errors).toEqual([]);await legacy.close();
  const uninitialized=await browser.newPage();const cold=await synthetic(uninitialized,{uninitialized:true});await uninitialized.goto('/overview');await expect(uninitialized.getByRole('link',{name:'查看记忆管理'}).getByText('记忆已配置，尚未初始化',{exact:true})).toBeVisible();await expect(uninitialized.getByRole('link',{name:'原话与事实'})).toHaveCount(0);expect(cold.calls.some(call=>call.path==='/api/memories'||call.path==='/api/memory-config')).toBe(false);await uninitialized.close();
});

test('窄屏大字号、键盘与其余页面冷加载的全局导航',async({page},info)=>{
  await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:'reduce'});const state=await synthetic(page);
  await page.goto('/memories?view=mechanisms');await expect(page.getByText('本次装配声明')).toBeVisible();await largerReading(page);await expect(page.locator('html')).toHaveAttribute('data-reading','larger');await noOverflow(page);
  await page.getByRole('button',{name:'模式与能力边界',exact:true}).focus();await page.keyboard.press('Enter');await expect(page.getByRole('heading',{name:'模式与场景'})).toBeVisible();await noOverflow(page);await page.screenshot({animations:'disabled',path:info.outputPath('mechanisms-mobile-large.png')});
  for(const path of ['/chat-react','/settings','/device','/display-preview','/experiments-react']) {
    await page.goto(path);await expect(page.getByRole('link',{name:'我的记忆',exact:true,includeHidden:true})).toHaveCount(1);await openNav(page);await expect(page.getByRole('link',{name:'我的记忆',exact:true})).toBeVisible();await expect(page.getByRole('link',{name:'记忆机制',exact:true})).toBeVisible();await expect(page.getByRole('link',{name:'用户画像',exact:true})).toHaveCount(0);
  }
  expect(state.calls.some(call=>call.path==='/api/memory-engine/items'||call.path==='/api/memories'||call.path==='/api/memory-config')).toBe(false);expect(state.calls.filter(call=>call.method!=='GET')).toEqual([]);expect(state.errors).toEqual([]);
});

test('机制加载、空目录、协议错误和首次繁忙保持各自语义',async({browser},info)=>{
  for(const mode of ['delay','empty','mismatch','busy'] as const){
    const page=await browser.newPage({viewport:{width:390,height:844}});
    const state=await synthetic(page,mode==='busy'?{mechanismsBusy:true}:{catalog:mode});await page.goto('/memories?view=mechanisms');
    if(mode==='delay')await expect(page.getByRole('status',{name:'正在读取机制声明'})).toBeVisible();
    else if(mode==='empty')await expect(page.getByText('接口没有提供机制条目；这不表示记忆库为空')).toBeVisible();
    else if(mode==='mismatch')await expect(page.getByText('机制快照结构或固定版本不匹配，未将它当作当前运行事实。')).toBeVisible();
    else await expect(page.getByText('暂时无法读取机制声明')).toBeVisible();
    await noOverflow(page);await page.screenshot({path:info.outputPath(`mechanisms-${mode}.png`),animations:'disabled'});
    if(mode==='delay')await expect(page.getByText('本次装配声明')).toBeVisible();
    expect(state.calls.filter(call=>call.path.endsWith('/hy/mechanisms'))).toHaveLength(1);
    expect(state.calls.some(call=>call.path==='/api/memories'||call.path==='/api/memory-config'||call.path==='/api/memory-engine/items')).toBe(false);
    expect(state.errors).toEqual([]);await page.close();
  }
});

for(const viewport of [{width:1366,height:768},{width:390,height:844}])test(`非零滚动选择机制不会跳顶 ${viewport.width}`,async({page},info)=>{
  await page.setViewportSize(viewport);await page.emulateMedia({reducedMotion:'reduce'});const state=await synthetic(page);
  await page.goto('/memories?view=mechanisms');await expect(page.getByText('本次装配声明')).toBeVisible();
  if(viewport.width===390){await largerReading(page);await expect(page.locator('html')).toHaveAttribute('data-reading','larger');}
  const stage=page.locator('.mechanism-path button').nth(3);
  await stage.evaluate(el=>el.scrollIntoView({block:'center'}));
  const before=await page.evaluate(()=>scrollY);expect(before).toBeGreaterThan(100);
  await stage.click();await expect(stage).toHaveAttribute('aria-pressed','true');
  await expect.poll(()=>page.evaluate(()=>scrollY)).toBeGreaterThan(100);
  expect(Math.abs(await page.evaluate(()=>scrollY)-before)).toBeLessThan(5);
  await info.attach('stage-scroll-metrics',{body:JSON.stringify({viewport:viewport.width,before,after:await page.evaluate(()=>scrollY)}),contentType:'application/json'});
  await page.screenshot({path:info.outputPath('selected-stage-scroll.png'),animations:'disabled'});
  if(viewport.width>760){
    const target=page.getByRole('navigation',{name:'完整机制目录'}).getByRole('button').last();await target.evaluate(el=>el.scrollIntoView({block:'center'}));
    const directoryY=await page.evaluate(()=>scrollY);expect(directoryY).toBeGreaterThan(100);await target.click();await expect(target).toHaveAttribute('aria-pressed','true');
    expect(Math.abs(await page.evaluate(()=>scrollY)-directoryY)).toBeLessThan(5);
  }else{
    const selector=page.getByLabel('选择全部机制');await selector.evaluate(el=>el.scrollIntoView({block:'center'}));const directoryY=await page.evaluate(()=>scrollY);
    await selector.selectOption('coding_route');await expect(selector).toHaveValue('coding_route');expect(await page.evaluate(()=>scrollY)).toBeGreaterThan(100);
    expect(Math.abs(await page.evaluate(()=>scrollY)-directoryY)).toBeLessThan(viewport.height/2);
  }
  await page.goBack();await expect(stage).toHaveAttribute('aria-pressed','true');await expect.poll(()=>page.evaluate(()=>scrollY)).toBeGreaterThan(100);
  const tabs=page.getByRole('button',{name:'L0–L7 分层',exact:true});await tabs.evaluate(el=>el.scrollIntoView({block:'center'}));const tabsY=await page.evaluate(()=>scrollY);
  await tabs.click();await expect(page.getByRole('region',{name:'Hy 原生记忆分层'})).toBeVisible();expect(Math.abs(await page.evaluate(()=>scrollY)-tabsY)).toBeLessThan(5);
  const layer=page.getByRole('button',{name:/Hy L3/});await layer.evaluate(el=>el.scrollIntoView({block:'center'}));const layerY=await page.evaluate(()=>scrollY);expect(layerY).toBeGreaterThan(100);
  await layer.click();await expect(layer).toHaveAttribute('aria-pressed','true');expect(await page.evaluate(()=>scrollY)).toBeGreaterThan(100);
  const contentHeading=page.getByRole('heading',{name:/Hy L3/});await expect(contentHeading).toBeVisible();expect((await contentHeading.boundingBox())!.y).toBeLessThan(viewport.height-100);
  await expect(page.locator('.hy-layer-record-content').first()).toBeInViewport();
  await page.reload();await expect(page.getByRole('heading',{name:/Hy L3/})).toBeVisible();await expect.poll(()=>page.evaluate(()=>scrollY)).toBeGreaterThan(100);
  if(viewport.width===390)await expect(page.locator('html')).toHaveAttribute('data-reading','larger');
  if(viewport.width>760){await page.getByRole('link',{name:'系统总览',exact:true}).click();await expect(page.getByRole('heading',{name:'系统总览',exact:true})).toBeVisible();await expect.poll(()=>page.evaluate(()=>scrollY)).toBe(0);await expect(page.locator('#main-content')).toBeFocused();}
  expect(state.errors).toEqual([]);
});
