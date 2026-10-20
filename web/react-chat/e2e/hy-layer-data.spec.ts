import {test,expect,type Page} from '@playwright/test';
import {HY_LAYERS,type HyLayerId} from '../src/api/hyLayerData';
import {mechanismFixture} from '../src/tests/fixtures/hyMechanisms';
import {layerDetail,layerPage,profileRecord,profileVersions,storedRecord} from '../src/tests/fixtures/hyLayerData';
import {largerReading} from './hy-test-appearance';

type Mode='normal'|'empty'|'busy'|'error'|'scope'|'delay'|'mismatch';
const identity={schema_version:1,configured:true,method:'hy_memory_pro_chat',representation:'method_defined',legacy_sqlite:false,state:'available'};
const longContent='合成的长正文：只用于检查有界读取、长文本换行和详情滚动。'.repeat(1400);
function record(layer:HyLayerId,index=0){
  if(layer==='l3_summary')return storedRecord(layer,index,{content:longContent.slice(0,1024),content_chars:longContent.length,content_truncated:true});
  return storedRecord(layer,index,{source_raw_memory_id:layer==='l2_fact'?'synthetic-raw-linked':null,supersedes:layer==='l2_fact'?['synthetic-previous']:[]});
}
async function synthetic(page:Page,initialMode:Mode='normal'){
  let mode=initialMode;const calls:Array<{path:string;method:string}>=[],errors:string[]=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url());if(url.hostname!=='127.0.0.1')return route.abort();
    if(!url.pathname.startsWith('/api/'))return route.continue();calls.push({path:url.pathname+url.search,method:req.method()});
    const ok=(json:unknown,status=200)=>route.fulfill({json,status});
    if(url.pathname==='/api/session')return ok({csrf:'synthetic-only'});
    if(url.pathname==='/api/memory-engine/identity')return ok(identity);
    if(url.pathname==='/api/memory-engine/hy/mechanisms')return ok(mechanismFixture);
    const match=url.pathname.match(/^\/api\/memory-engine\/hy\/layers\/([^/]+)(?:\/items\/([^/]+))?$/);
    if(match){
      const layer=match[1] as HyLayerId,id=match[2]?decodeURIComponent(match[2]):null;
      if(!HY_LAYERS.includes(layer))return ok({error:'hy_layer_data_invalid_page'},400);
      if(mode==='delay')await new Promise(resolve=>setTimeout(resolve,1200));
      if(mode==='busy')return ok({error:'hy_layer_data_busy'},503);
      if(mode==='error')return ok({error:'hy_layer_data_unavailable'},503);
      if(id==='outside-scope')return ok({error:'not_found'},404);
      if(mode==='scope')return ok(id?layerDetail(layer,storedRecord(layer),{read_status:'unavailable',coverage:'unavailable',data_state:'unknown',reason_code:'profile_scope_unproven',item:null}):layerPage(layer,{items:[],read_status:'unavailable',coverage:'unavailable',data_state:'unknown',reason_code:'profile_scope_unproven',total:null,has_more:null}));
      if(id){
        if(layer==='l0_basic_info')return ok(layerDetail(layer,id==='profile'?profileRecord:profileVersions.find(item=>item.item_id===id)??storedRecord(layer,0,{item_id:id,native_id:id})));
        const item=record(layer,Number(id.match(/-(\d+)$/)?.[1]??0));
        return ok(layerDetail(layer,{...item,item_id:id,native_id:id,content:layer==='l3_summary'?longContent.slice(0,32768):id==='synthetic-previous'?'合成的被取代版本':id==='synthetic-raw-linked'?'合成 SDK RAW 关联正文':item.content}));
      }
      const offset=Number(url.searchParams.get('offset')??0),state=url.searchParams.get('state')??'all';
      if(mode==='mismatch')return ok(layerPage('l1_raw'));
      if(mode==='empty'||layer==='l5_knowledge')return ok(layerPage(layer,{items:[],total:0,has_more:false,data_state:'empty',offset,state:state as never}));
      if(layer==='l0_basic_info')return ok(layerPage(layer));
      if(layer==='l6_schema'||layer==='l7_intention')return ok(layerPage(layer,{items:layer==='l6_schema'?[record(layer)]:[],read_status:'partial',coverage:'vdb_only_graph_unopened',reason_code:'graph_store_not_open',total:null,data_state:layer==='l6_schema'?'present':'unknown'}));
      const items=layer==='l2_fact'&&offset===0&&state==='all'?Array.from({length:20},(_,i)=>record(layer,i)):[record(layer,offset)];
      return ok(layerPage(layer,{items,offset,state:state as never,total:layer==='l2_fact'&&offset===0&&state==='all'?null:offset+items.length,has_more:layer==='l2_fact'&&offset===0&&state==='all'}));
    }
    if(url.pathname==='/api/memory-engine/sources/synthetic-platform-source')return ok({event_id:'synthetic-platform-source',role:'user',content:'合成平台来源：我周末沿河散步。平台原话与SDK RAW分别核对。',state:'completed',occurred_at:null});
    if(url.pathname==='/api/chat-config')return ok({enabled:true,database:'synthetic-only',model:'Synthetic model',role:'合成角色',provider:'fake',method:identity.method,retrieval:'hy_chat_default_legacy'});
    if(url.pathname==='/api/device')return ok({connection_count:0,ready:false,read_status_supported:false});
    if(url.pathname==='/api/runtime-status')return ok({enabled:false,state:'launcher_unavailable',services:{}});
    if(url.pathname==='/api/chats')return ok({chats:[]});
    return ok({error:'synthetic_unavailable'},501);
  });
  return {calls,errors,setMode:(value:Mode)=>{mode=value;}};
}
async function noOverflow(page:Page){expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(await page.evaluate(()=>innerWidth+1));}
async function openLayer(page:Page,layer:HyLayerId){await page.goto(`/memories?view=mechanisms&mechanism_tab=layers&layer=${layer}`);await expect(page.getByRole('heading',{name:/已保存内容/})).toBeVisible();}

for(const viewport of [{width:1920,height:1080},{width:1366,height:768},{width:390,height:844}])test(`逐层内容分页详情与视口 ${viewport.width}`,async({page},info)=>{
  await page.setViewportSize(viewport);await page.emulateMedia({reducedMotion:'reduce'});const state=await synthetic(page);
  await openLayer(page,'l2_fact');if(viewport.width===390){await largerReading(page);await expect(page.locator('html')).toHaveAttribute('data-reading','larger');}
  await expect(page.getByText('合成 l2_fact 保存正文 0：周末沿河散步。',{exact:true})).toBeVisible();await expect(page.getByText('总数未知',{exact:true})).toBeVisible();await noOverflow(page);
  await page.locator('.hy-layer-browser').evaluate(el=>el.scrollIntoView({block:'start'}));expect(await page.evaluate(()=>scrollY)).toBeGreaterThan(100);
  await page.screenshot({path:info.outputPath(`layer-content-${viewport.width}.png`),animations:'disabled'});
  const next=page.getByRole('button',{name:'下一页',exact:true});await next.click();await expect(page.getByText('合成 l2_fact 保存正文 20：周末沿河散步。',{exact:true})).toBeVisible();await expect(page).toHaveURL(/layer_offset=20/);
  expect(await page.evaluate(()=>scrollY)).toBeGreaterThan(100);await expect(page.getByRole('button',{name:'下一页',exact:true})).toBeDisabled();
  const details=page.getByRole('button',{name:'查看全文与来源',exact:true});await details.focus();await page.keyboard.press('Enter');const drawer=page.getByRole('dialog',{name:/Hy L2.*内容详情/});await expect(drawer).toBeVisible();
  await drawer.getByRole('combobox',{name:'分层详情平台来源'}).selectOption('synthetic-platform-source');await expect(drawer.getByText('合成平台来源：我周末沿河散步。平台原话与SDK RAW分别核对。')).toBeVisible();
  await page.screenshot({path:info.outputPath(`layer-source-${viewport.width}.png`),animations:'disabled'});
  await drawer.getByRole('button',{name:'查看被取代版本 synthetic-previous'}).click();await expect(drawer.getByText('合成的被取代版本')).toBeVisible();
  await page.goBack();await expect(drawer.getByText('合成 l2_fact 保存正文 20：周末沿河散步。',{exact:true})).toBeVisible();await page.keyboard.press('Escape');await expect(drawer).toBeHidden();await expect(details).toBeFocused();
  expect(await page.evaluate(()=>scrollY)).toBeGreaterThan(100);await page.reload();await expect(page).toHaveURL(/layer_offset=20/);await expect(page.getByText('合成 l2_fact 保存正文 20：周末沿河散步。',{exact:true})).toBeVisible();await expect.poll(()=>page.evaluate(()=>scrollY)).toBeGreaterThan(100);
  await page.getByRole('combobox',{name:'本层记录状态'}).selectOption('archived');await expect(page).toHaveURL(/layer_state=archived/);expect(state.calls.some(call=>call.path.endsWith('offset=0&state=archived'))).toBe(true);
  await noOverflow(page);expect(state.errors).toEqual([]);expect(state.calls.every(call=>call.method==='GET')).toBe(true);
});

test('八层分别读取实际内容：聚合、RAW、历史、保留与部分图范围',async({page},info)=>{
  const state=await synthetic(page);await openLayer(page,'l0_basic_info');await expect(page.getByText('茶',{exact:true})).toBeVisible();await expect(page.getByText('合成城市',{exact:true})).toBeVisible();await expect(page.getByText('已完整读取 2 个原生版本用于聚合。')).toBeVisible();
  await page.screenshot({path:info.outputPath('layer-zero-profile.png'),animations:'disabled',fullPage:true});
  await page.getByRole('button',{name:'核对聚合来源与原生版本'}).click();const drawer=page.getByRole('dialog',{name:/Hy L0.*内容详情/});await expect(drawer.getByRole('heading',{name:'L0 原生存储版本',exact:true})).toBeVisible();await page.screenshot({path:info.outputPath('layer-zero-versions.png'),animations:'disabled'});await drawer.getByRole('button',{name:'查看原生版本 synthetic-profile-old'}).click();await expect(drawer.getByText('喜欢的饮品：茶',{exact:true})).toBeVisible();await page.keyboard.press('Escape');
  for(const layer of HY_LAYERS.slice(1)){
    const number=HY_LAYERS.indexOf(layer),button=page.getByRole('button',{name:new RegExp(`Hy L${number} `)});await button.click();await expect(button).toHaveAttribute('aria-pressed','true');
    if(layer==='l5_knowledge')await expect(page.getByText('本层尚无已保存内容')).toBeVisible();
    else if(layer==='l7_intention')await expect(page.getByText('当前页没有返回记录，整层是否为空尚不能确认')).toBeVisible();
    else await expect(page.locator('.hy-layer-records')).toContainText(layer==='l3_summary'?'合成的长正文':'合成 '+layer+' 保存正文');
    if(layer==='l6_schema'||layer==='l7_intention'){await expect(page.getByText('当前生成已关闭',{exact:true})).toBeVisible();await expect(page.getByText('只覆盖部分存储范围')).toBeVisible();}
    await noOverflow(page);
  }
  await page.screenshot({path:info.outputPath('layer-seven-partial.png'),animations:'disabled',fullPage:true});
  await page.goBack();await expect(page.getByRole('button',{name:/Hy L6 /})).toHaveAttribute('aria-pressed','true');await expect(page.locator('.hy-layer-records')).toContainText('l6_schema');
  await page.goForward();await expect(page.getByRole('button',{name:/Hy L7 /})).toHaveAttribute('aria-pressed','true');await expect(page.getByText('当前页没有返回记录，整层是否为空尚不能确认')).toBeVisible();
  expect(state.calls.some(call=>call.path.startsWith('/api/memory-engine/items')||call.path.startsWith('/api/source-messages'))).toBe(false);expect(state.errors).toEqual([]);
});

test('分层加载、真实空层、繁忙、错误、范围拒绝与错层响应',async({browser},info)=>{
  for(const mode of ['delay','empty','busy','error','scope','mismatch'] as const){
    const page=await browser.newPage({viewport:{width:390,height:844}});const state=await synthetic(page,mode);await openLayer(page,mode==='scope'?'l0_basic_info':'l2_fact');
    if(mode==='delay')await expect(page.getByRole('status',{name:'正在读取本层内容'})).toBeVisible();
    else if(mode==='empty')await expect(page.getByText('本层尚无已保存内容')).toBeVisible();
    else if(mode==='scope'){await expect(page.getByText('当前无法读取本层内容')).toBeVisible();await expect(page.getByText(/尚未证明基本画像属于当前拥有者/)).toBeVisible();await expect(page.getByText('本层尚无已保存内容')).toHaveCount(0);}
    else {await expect(page.getByText('本层内容读取失败')).toBeVisible();if(mode==='mismatch')await expect(page.getByText(/分层响应与请求范围或协议不一致/)).toBeVisible();}
    await noOverflow(page);await page.screenshot({path:info.outputPath(`layer-state-${mode}.png`),animations:'disabled'});
    expect(state.calls.filter(call=>/^\/api\/memory-engine\/hy\/layers\//.test(call.path))).toHaveLength(1);expect(state.errors).toEqual([]);await page.close();
  }
});

test('只读详情404、长正文截断与RAW关联不越范围补读',async({page})=>{
  const state=await synthetic(page);await openLayer(page,'l2_fact');await page.getByRole('button',{name:'查看全文与来源',exact:true}).first().click();const drawer=page.getByRole('dialog');await drawer.getByRole('button',{name:'核对关联的 Hy RAW 原始记忆'}).click();await expect(page).toHaveURL(/layer=l1_raw/);await expect(page.getByRole('dialog').getByText('合成 SDK RAW 关联正文')).toBeVisible();await page.keyboard.press('Escape');
  await page.goto('/memories?view=mechanisms&mechanism_tab=layers&layer=l2_fact&layer_item=outside-scope');await expect(page.getByText('详情读取失败')).toBeVisible();await expect(page.getByText('该记录不存在，或不属于当前层和读取范围；未从其他范围补读。')).toBeVisible();await page.keyboard.press('Escape');
  await openLayer(page,'l3_summary');await page.getByRole('button',{name:'查看全文与来源',exact:true}).click();await expect(page.getByRole('dialog').getByText(/详情正文已截断，原文共/)).toBeVisible();expect(state.calls.every(call=>call.method==='GET')).toBe(true);expect(state.errors).toEqual([]);
});

test('总览与聊天继续轻量，不预取任何层内容',async({page})=>{
  const state=await synthetic(page);for(const path of ['/overview','/chat-react']){await page.goto(path);await expect(page.getByRole('link',{name:'我的记忆',exact:true,includeHidden:true})).toHaveCount(1);}
  expect(state.calls.some(call=>call.path.startsWith('/api/memory-engine/hy/layers/')||call.path.startsWith('/api/memory-engine/items'))).toBe(false);expect(state.errors).toEqual([]);
});
