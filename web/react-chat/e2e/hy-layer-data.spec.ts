import {test,expect,type Page} from '@playwright/test';
import {HY_LAYERS,type HyLayerId} from '../src/api/hyLayerData';
import {mechanismFixture} from '../src/tests/fixtures/hyMechanisms';
import {graphPage,layerDetail,layerPage,profileRecord,profileVersions,semanticRecord,storedRecord} from '../src/tests/fixtures/hyLayerData';
import {semanticStatusFixture,semanticTaskFixture} from '../src/tests/fixtures/hySemantic';
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

for(const width of [1366,390])test(`L2来源可信与注入许可冷链接滚动 ${width}`,async({page},info)=>{
  await page.setViewportSize({width,height:844});const state=await synthetic(page);
  const rows=[
    storedRecord('l2_fact',0,{content:'合成来源样例：用户原话。',provenance:{status:'verbatim_user',semantic_source_complete:true,dependency_basis:'verbatim_current_input',injection_allowed:true}}),
    storedRecord('l2_fact',1,{content:'合成来源样例：用户明确纠正。',provenance:{status:'explicit_correction',semantic_source_complete:true,dependency_basis:'explicit_correction',injection_allowed:false}}),
    storedRecord('l2_fact',2,{content:'合成来源样例：模型概括。',provenance:{status:'model_inference_unverified',semantic_source_complete:false,dependency_basis:'scope_context_envelope',injection_allowed:false}}),
    storedRecord('l2_fact',3,{content:'合成来源样例：来源未知。'}),
  ];
  await page.route('**/api/memory-engine/hy/layers/l2_fact**',route=>{
    const req=route.request(),url=new URL(req.url());state.calls.push({path:url.pathname+url.search,method:req.method()});
    const id=url.pathname.includes('/items/')?decodeURIComponent(url.pathname.split('/').at(-1)!):null;
    return route.fulfill({json:id?layerDetail('l2_fact',rows.find(item=>item.item_id===id)!):layerPage('l2_fact',{items:rows,total:4})});
  });
  await page.goto('/memories?view=mechanisms&mechanism_tab=layers&layer=l2_fact&layer_item='+rows[2].item_id);
  if(width===390)await largerReading(page);
  const drawer=page.getByRole('dialog');await expect(drawer.getByText('未证实模型推断',{exact:true})).toBeVisible();
  await expect(drawer.getByText('当前禁止注入',{exact:true})).toBeVisible();await expect(drawer.getByText('尚未证实完整',{exact:true})).toBeVisible();
  await expect(drawer.getByText(/不是模型真实引用或逐句归因/)).toBeVisible();await noOverflow(page);
  await page.screenshot({path:info.outputPath(`provenance-detail-${width}.png`),animations:'disabled'});
  await page.keyboard.press('Escape');await expect(drawer).toBeHidden();
  const records=page.locator('.hy-layer-records');await expect(records.getByText('用户原话',{exact:true})).toBeVisible();await expect(records.getByText('用户明确纠正',{exact:true})).toBeVisible();
  await expect(records.getByText('来源可信类型未知',{exact:true})).toBeVisible();await expect(records.getByText('注入许可未知',{exact:true})).toBeVisible();
  await records.getByText(rows[1].content,{exact:true}).evaluate(el=>el.scrollIntoView({block:'center'}));const before=await page.evaluate(()=>scrollY);expect(before).toBeGreaterThan(100);
  await page.screenshot({path:info.outputPath(`provenance-list-${width}.png`),animations:'disabled'});
  await page.reload();await expect(records.getByText(rows[1].content,{exact:true})).toBeVisible();await expect.poll(()=>page.evaluate(()=>scrollY)).toBeGreaterThan(100);
  await page.goBack();await expect(drawer).toBeVisible();await expect(drawer.getByText('未证实模型推断',{exact:true})).toBeVisible();
  await page.goForward();await expect(drawer).toBeHidden();await noOverflow(page);
  expect(state.calls.every(call=>call.method==='GET')).toBe(true);expect(state.errors).toEqual([]);
});

async function semanticSynthetic(page:Page,options:{legacy?:boolean;isolated?:boolean}={}){
  const state=await synthetic(page);let busy=false;
  await page.route('**/api/memory-engine/hy/semantic/**',route=>{
    const req=route.request(),url=new URL(req.url());state.calls.push({path:url.pathname,method:req.method()});
    if(url.pathname.endsWith('/status'))return route.fulfill({status:busy?503:200,json:busy?{error:'hy_semantic_busy'}:semanticStatusFixture({schema_state:options.isolated?'isolated':'ready',task_counts:{running:1},management_available:false})});
    return route.fulfill({json:semanticTaskFixture({task_id:decodeURIComponent(url.pathname.split('/').at(-1)!),state:'uncertain',finished_at:null,elapsed_ms:null,reason_code:'worker_timeout'})});
  });
  for(const layer of ['l6_schema','l7_intention'] as const)await page.route(`**/api/memory-engine/hy/layers/${layer}**`,route=>{
    const req=route.request(),url=new URL(req.url());state.calls.push({path:url.pathname+url.search,method:req.method()});
    const item=semanticRecord(layer,{content:layer==='l6_schema'?'合成图式：周末通过散步恢复精力。':'合成未来意图：曾计划周末散步。',derivation_state:layer==='l6_schema'?(options.isolated?'isolated':'ready'):'expired',
      evidence_memory_ids:layer==='l6_schema'?['synthetic-fact-evidence','synthetic-summary-evidence']:null,updated_at:layer==='l6_schema'?'2026-10-20T01:02:03Z':null,valid_until:layer==='l7_intention'?'2026-10-20T04:00:00Z':null});
    const read={generation_state:'configured' as const,...(layer==='l6_schema'?options.legacy?{coverage:'graph_only_legacy_vdb_present' as const,read_status:'partial' as const,reason_code:'legacy_vdb_schema_not_in_graph_page'}:{coverage:'graph_complete' as const,read_status:'readable' as const,reason_code:null}:{})};
    return route.fulfill({json:url.pathname.includes('/items/')?layerDetail(layer,item,read):layer==='l6_schema'?graphPage({...read,items:[item],total:options.legacy?null:1}):layerPage(layer,{generation_state:'configured',items:[item]})});
  });
  return {...state,setStatusBusy:()=>{busy=true;}};
}

test('自动add/management任务ID冷链接、编码GET和浏览器返回',async({page},info)=>{
  const state=await semanticSynthetic(page);
  const automatic='add:'+'a'.repeat(64)+':expiry',management='management:synthetic-operation';
  await page.goto(`/memories?view=mechanisms&mechanism_tab=layers&layer=l6_schema&semantic_task=${encodeURIComponent(automatic)}`);
  const panel=page.getByLabel('分层接入与运行证据');await panel.locator('summary').click();
  await expect(panel.getByText(automatic,{exact:true})).toBeVisible();await expect(panel.getByRole('textbox',{name:'语义任务 ID'})).toHaveValue(automatic);
  expect(state.calls.some(call=>call.path.endsWith('/tasks/'+encodeURIComponent(automatic)))).toBe(true);
  await panel.getByRole('textbox',{name:'语义任务 ID'}).fill(management);await panel.getByRole('button',{name:'读取任务'}).click();
  await expect(panel.getByText(management,{exact:true})).toBeVisible();expect(state.calls.some(call=>call.path.endsWith('/tasks/'+encodeURIComponent(management)))).toBe(true);
  await page.goBack();await expect(panel.getByText(automatic,{exact:true})).toBeVisible();
  await page.screenshot({path:info.outputPath('automatic-task-id.png'),animations:'disabled'});
  expect(state.calls.every(call=>call.method==='GET')).toBe(true);expect(state.errors).toEqual([]);
});

for(const width of [1366,390])test(`真实契约图式、意图与只读任务快照 ${width}`,async({page},info)=>{
  await page.setViewportSize({width,height:844});const state=await semanticSynthetic(page,{legacy:true,isolated:true});
  await openLayer(page,'l6_schema');if(width===390)await largerReading(page);
  await expect(page.getByText('合成图式：周末通过散步恢复精力。',{exact:true})).toBeVisible();
  await expect(page.getByText(/本页读取原生图库；旧向量存储中另有 L6/)).toBeVisible();
  expect(state.calls.some(call=>call.path.includes('/semantic/'))).toBe(false);
  await page.getByRole('button',{name:'查看全文与来源'}).click();const drawer=page.getByRole('dialog');
  await expect(drawer.getByText('synthetic-fact-evidence',{exact:true})).toBeVisible();await expect(drawer.getByText(/当前派生已隔离/)).toBeVisible();
  await expect(drawer.getByText('原生更新时间',{exact:true})).toBeVisible();await page.screenshot({path:info.outputPath(`semantic-graph-${width}.png`),animations:'disabled'});
  await page.keyboard.press('Escape');await page.getByLabel('分层接入与运行证据').locator('summary').click();
  await page.getByRole('button',{name:'读取实例状态'}).click();await expect(page.getByText(/图式派生状态：已隔离/)).toBeVisible();
  await expect(page.getByText('已认领，运行中',{exact:true})).toBeVisible();await expect(page.getByText(/执行与主动联系均未授权/)).toBeVisible();
  await page.getByRole('textbox',{name:'语义任务 ID'}).fill('synthetic-evolve-task');await page.getByRole('button',{name:'读取任务'}).click();
  await expect(page).toHaveURL(/semantic_task=synthetic-evolve-task/);await expect(page.getByText('结果不确定',{exact:true})).toBeVisible();
  await expect(page.getByText(/本状态不会自动重试/)).toBeVisible();await noOverflow(page);
  await page.screenshot({path:info.outputPath(`semantic-status-task-${width}.png`),animations:'disabled',fullPage:true});
  state.setStatusBusy();await page.getByRole('button',{name:'刷新实例状态'}).click();await expect(page.getByText('未取得新实例状态，以下保留上次快照')).toBeVisible();
  const reads=state.calls.filter(call=>call.path.endsWith('/semantic/status')).length;await page.waitForTimeout(100);expect(state.calls.filter(call=>call.path.endsWith('/semantic/status'))).toHaveLength(reads);
  await page.getByRole('button',{name:/Hy L7 /}).click();await expect(page.getByText('意图已过期',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'查看全文与来源'}).click();await expect(drawer.getByText('依据关联未知，不能解释为没有来源。')).toBeVisible();
  await expect(drawer.getByText(/有效期已过，不表示意图已经执行或完成/)).toBeVisible();await page.keyboard.press('Escape');
  await page.goBack();await expect(drawer).toBeVisible();
  await page.goBack();await expect(drawer).toBeHidden();
  await page.goBack();await expect(page).toHaveURL(/layer=l6_schema/);await expect(page.getByText('合成图式：周末通过散步恢复精力。',{exact:true})).toBeVisible();
  expect(state.calls.every(call=>call.method==='GET')).toBe(true);expect(state.errors).toEqual([]);
});

for(const width of [1366,390])test(`L6/L7五轴证据与旧协议未知状态 ${width}`,async({page},info)=>{
  await page.setViewportSize({width,height:844});const state=await synthetic(page);
  await openLayer(page,'l6_schema');if(width===390)await largerReading(page);
  const panel=page.getByLabel('分层接入与运行证据');
  await panel.locator('summary').click();
  await expect(panel.getByText('未启用',{exact:true})).toBeVisible();
  await expect(panel.getByText('部分覆盖',{exact:true})).toBeVisible();
  await expect(panel.getByText('未知',{exact:true})).toHaveCount(3);
  await expect(panel.getByText(/本次运行开关快照/)).toBeVisible();
  await expect(panel.getByText(/原生最后更新时间尚未提供/)).toBeVisible();
  await expect(panel.getByText('已启用',{exact:true})).toHaveCount(0);
  await expect(panel.getByRole('button',{name:'读取实例状态'})).toBeVisible();
  await expect(panel.getByRole('button',{name:'读取任务'})).toBeDisabled();
  await panel.evaluate(el=>el.scrollIntoView({block:'start'}));
  await noOverflow(page);await page.screenshot({path:info.outputPath(`layer-capability-${width}.png`),animations:'disabled'});
  await panel.locator('summary').click();
  await page.getByRole('button',{name:/Hy L7 /}).click();
  await expect(page.getByText('当前页没有返回记录，整层是否为空尚不能确认')).toBeInViewport();
  await expect(panel.locator('summary')).toContainText('部分覆盖');
  await page.goBack();await expect(page).toHaveURL(/layer=l6_schema/);
  await expect(page.getByText('合成 l6_schema 保存正文 0：周末沿河散步。',{exact:true})).toBeVisible();
  state.setMode('busy');await page.getByRole('button',{name:'刷新本层'}).click();
  await expect(page.getByText('本层内容读取失败')).toBeVisible();await expect(panel).toHaveCount(0);
  expect(state.calls.every(call=>call.method==='GET')).toBe(true);expect(state.errors).toEqual([]);
});

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
  await page.getByRole('button',{name:/Hy L0 /}).click();await expect(page.getByText('茶',{exact:true})).toBeInViewport();
  await page.screenshot({path:info.outputPath('layer-zero-profile.png'),animations:'disabled',fullPage:true});
  await page.getByRole('button',{name:'核对聚合来源与原生版本'}).click();const drawer=page.getByRole('dialog',{name:/Hy L0.*内容详情/});await expect(drawer.getByRole('heading',{name:'L0 原生存储版本',exact:true})).toBeVisible();await page.screenshot({path:info.outputPath('layer-zero-versions.png'),animations:'disabled'});await drawer.getByRole('button',{name:'查看原生版本 synthetic-profile-old'}).click();await expect(drawer.getByText('喜欢的饮品：茶',{exact:true})).toBeVisible();await page.keyboard.press('Escape');
  for(const layer of HY_LAYERS.slice(1)){
    const number=HY_LAYERS.indexOf(layer),button=page.getByRole('button',{name:new RegExp(`Hy L${number} `)});await button.click();await expect(button).toHaveAttribute('aria-pressed','true');
    if(layer==='l5_knowledge')await expect(page.getByText('本层尚无已保存内容')).toBeInViewport();
    else if(layer==='l7_intention')await expect(page.getByText('当前页没有返回记录，整层是否为空尚不能确认')).toBeInViewport();
    else {await expect(page.locator('.hy-layer-records')).toContainText(layer==='l3_summary'?'合成的长正文':'合成 '+layer+' 保存正文');await expect(page.locator('.hy-layer-record-content').first()).toBeInViewport();}
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
