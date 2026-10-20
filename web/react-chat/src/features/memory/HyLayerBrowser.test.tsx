import {afterEach,expect,test,vi} from 'vitest';
import {act,fireEvent,render,screen,within} from '@testing-library/react';
import {MemoryRouter,useLocation} from 'react-router-dom';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {ApiError,ChatApi} from '../../api';
import {parseHyLayerDetail,parseHyLayerPage,type HyLayerId} from '../../api/hyLayerData';
import {KnownMemoryEngine} from '../../tests/memoryEngine';
import {graphPage,layerDetail,layerPage,profileRecord,profileVersions,semanticRecord,storedRecord} from '../../tests/fixtures/hyLayerData';
import {semanticStatusFixture,semanticTaskFixture} from '../../tests/fixtures/hySemantic';
import {HyLayerBrowser} from './HyLayerBrowser';

afterEach(()=>vi.restoreAllMocks());
function Coordinate(){return <output aria-label="当前坐标">{useLocation().search}</output>;}
function setup(layer:HyLayerId='l2_fact',route='',response?:(url:string)=>unknown){
  const request=vi.spyOn(ChatApi.prototype,'request').mockImplementation(async url=>{
    const custom=response?.(url);if(custom!==undefined)return await custom as never;
    if(url===`/api/memory-engine/hy/layers/${layer}?limit=20&offset=0&state=all`)return layerPage(layer) as never;
    if(url.includes('/items/'))return layerDetail(layer,layer==='l0_basic_info'?profileRecord:storedRecord(layer)) as never;
    throw new Error('unexpected synthetic request '+url);
  });
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter initialEntries={[`/memories?view=mechanisms&mechanism_tab=layers&layer=${layer}${route}`]}><KnownMemoryEngine kind="hy"><HyLayerBrowser layer={layer} title={layer}/><Coordinate/></KnownMemoryEngine></MemoryRouter></QueryClientProvider>);
  return request;
}

test('L1展示SDK RAW真实记录，未自动读取混合ACTIVE条目或平台来源',async()=>{
  const request=setup('l1_raw');expect(await screen.findByText('合成 l1_raw 保存正文 0：周末沿河散步。')).toBeTruthy();
  expect(screen.getByText('SDK 中实际保存的 RAW 原始记忆，独立于平台原话账本。')).toBeTruthy();
  expect(request.mock.calls.map(([url])=>url)).toEqual(['/api/memory-engine/hy/layers/l1_raw?limit=20&offset=0&state=all']);
});

test('服务端分页保留未知总数，末页总数与状态筛选来自响应',async()=>{
  const request=setup('l2_fact','',url=>{
    if(url.endsWith('offset=0&state=all'))return layerPage('l2_fact',{items:Array.from({length:20},(_,i)=>storedRecord('l2_fact',i)),total:null,has_more:true});
    if(url.endsWith('offset=20&state=all'))return layerPage('l2_fact',{items:[storedRecord('l2_fact',20)],offset:20,total:21});
    if(url.endsWith('offset=0&state=superseded'))return layerPage('l2_fact',{items:[storedRecord('l2_fact',3,{status:'superseded',is_latest:false})],state:'superseded'});
  });
  await screen.findByText('合成 l2_fact 保存正文 0：周末沿河散步。');expect(screen.getAllByText(/总数未知/).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole('button',{name:'下一页'}));await screen.findByText('合成 l2_fact 保存正文 20：周末沿河散步。');
  expect(screen.getByRole('button',{name:'下一页'}).hasAttribute('disabled')).toBe(true);expect(screen.getByLabelText('当前坐标').textContent).toContain('layer_offset=20');
  fireEvent.change(screen.getByRole('combobox',{name:'本层记录状态'}),{target:{value:'superseded'}});await screen.findByText('历史版本');
  expect(request.mock.calls.some(([url])=>url.endsWith('offset=0&state=superseded'))).toBe(true);
});

test('冷开详情链接等待本页读取结束，避免同页面并发争抢owner读锁',async()=>{
  let finish!:(value:unknown)=>void;const pending=new Promise(resolve=>{finish=resolve;});
  const record=storedRecord('l2_fact');
  const request=setup('l2_fact','&layer_item='+record.item_id,url=>url.includes('/items/')?layerDetail('l2_fact',record):pending);
  await screen.findByRole('status',{name:'正在读取本层内容'});
  expect(request.mock.calls.some(([url])=>url.includes('/items/'))).toBe(false);
  await act(async()=>finish(layerPage('l2_fact')));
  await within(screen.getByRole('dialog')).findByText(record.content);
  expect(request.mock.calls.map(([url])=>url)).toEqual(['/api/memory-engine/hy/layers/l2_fact?limit=20&offset=0&state=all','/api/memory-engine/hy/layers/l2_fact/items/'+record.item_id]);
});

test('到达分页上限仍有后续记录时，说明边界且不请求越界下一页',async()=>{
  const request=setup('l2_fact','&layer_offset=10000',url=>url.endsWith('offset=10000&state=all')?layerPage('l2_fact',{offset:10000,total:null,has_more:true}):undefined);
  await screen.findByText('已到本次浏览上限，后续记录尚未读取，不代表全层结束。可返回前页或刷新本层。');
  const next=screen.getByRole('button',{name:'下一页'});
  expect(next.hasAttribute('disabled')).toBe(true);fireEvent.click(next);
  expect(request.mock.calls.map(([url])=>url)).toEqual(['/api/memory-engine/hy/layers/l2_fact?limit=20&offset=10000&state=all']);
});

test('L0聚合字段、独立版本数与版本详情，不把链头差异当完整画像',async()=>{
  const request=setup('l0_basic_info','',url=>{
    if(url.endsWith('/items/synthetic-profile-old'))return layerDetail('l0_basic_info',profileVersions[0]);
  });
  await screen.findByText('茶');expect(screen.getByText('合成城市')).toBeTruthy();expect(screen.getByText('已完整读取 2 个原生版本用于聚合。')).toBeTruthy();
  expect(screen.getByText('空值（null）')).toBeTruthy();expect(screen.getByText('空文本（已保存）')).toBeTruthy();expect(screen.getAllByText('该字段原生版本来源未提供').length).toBe(2);
  expect(screen.getByRole('combobox',{name:'本层记录状态'}).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button',{name:'核对聚合来源与原生版本'}));
  const drawer=await screen.findByRole('dialog',{name:'l0_basic_info内容详情'});await within(drawer).findByText('L0 原生存储版本');
  fireEvent.click(within(drawer).getByRole('button',{name:'查看原生版本 synthetic-profile-old'}));await within(drawer).findByText('喜欢的饮品：茶');
  expect(request.mock.calls.some(([url])=>url.endsWith('/l0_basic_info/items/synthetic-profile-old'))).toBe(true);
});

test('详情读取单条来源与原生版本关联，无额外模型或管理请求',async()=>{
  const record=storedRecord('l3_summary',0,{supersedes:['synthetic-old-summary'],source_raw_memory_id:'synthetic-raw'});
  const request=setup('l3_summary','&layer_item='+record.item_id,url=>{
    if(url.endsWith('/items/'+record.item_id))return layerDetail('l3_summary',record);
    if(url.endsWith('/sources/synthetic-platform-source'))return {event_id:'synthetic-platform-source',role:'user',content:'合成平台原话，与RAW正文分别核对。',state:'completed',occurred_at:null};
    if(url.endsWith('/items/synthetic-old-summary'))return layerDetail('l3_summary',storedRecord('l3_summary',1,{item_id:'synthetic-old-summary',native_id:'synthetic-old-summary',content:'合成旧版本',is_latest:false}));
  });
  const drawer=await screen.findByRole('dialog',{name:'l3_summary内容详情'});await within(drawer).findByText(record.content);
  fireEvent.change(within(drawer).getByRole('combobox',{name:'分层详情平台来源'}),{target:{value:'synthetic-platform-source'}});await within(drawer).findByText('合成平台原话，与RAW正文分别核对。');
  fireEvent.click(within(drawer).getByRole('button',{name:'查看被取代版本 synthetic-old-summary'}));await within(drawer).findByText('合成旧版本');
  expect(request.mock.calls.every(([,method])=>!method||method==='GET')).toBe(true);
});

test('L6关闭但仍可有存量，部分范围与未知总数不伪装为空',async()=>{
  setup('l6_schema','',url=>url.includes('/layers/l6_schema?')?layerPage('l6_schema',{read_status:'partial',coverage:'vdb_only_graph_unopened',reason_code:'graph_store_not_open',total:null}):undefined);
  expect(await screen.findByText('合成 l6_schema 保存正文 0：周末沿河散步。')).toBeTruthy();expect(screen.getByText('当前生成已关闭')).toBeTruthy();
  expect(screen.getByText('只覆盖部分存储范围')).toBeTruthy();expect(screen.getAllByText(/总数未知/).length).toBeGreaterThan(0);
});

test.each(['l4_identity','l5_knowledge'] as const)('%s历史/保留层的真实空数据与配置状态分开',async layer=>{
  setup(layer,'',url=>url.includes(`/layers/${layer}?`)?layerPage(layer,{items:[],total:0,data_state:'empty'}):undefined);
  expect(await screen.findByText('本层尚无已保存内容')).toBeTruthy();expect(screen.getByText(layer==='l4_identity'?'仅历史兼容':'保留层')).toBeTruthy();
});

test('L0范围证明不足为不可读取，不显示空画像或借用其他范围',async()=>{
  const request=setup('l0_basic_info','',()=>layerPage('l0_basic_info',{items:[],total:null,has_more:null,read_status:'unavailable',coverage:'unavailable',reason_code:'profile_scope_unproven',data_state:'unknown'}));
  expect(await screen.findByText('当前无法读取本层内容')).toBeTruthy();expect(screen.getByText(/尚未证明基本画像属于当前拥有者/)).toBeTruthy();
  expect(screen.queryByText('本层尚无已保存内容')).toBeNull();expect(request.mock.calls.length).toBe(1);
});

test('busy不自动重试，失败与零记录分开；手动恢复',async()=>{
  let busy=true;const request=setup('l2_fact','',()=>busy?Promise.reject(new ApiError('hy_layer_data_busy',503)):layerPage('l2_fact'));
  expect(await screen.findByText('本层内容读取失败')).toBeTruthy();expect(request.mock.calls.length).toBe(1);busy=false;
  fireEvent.click(screen.getByRole('button',{name:'重试本层'}));await screen.findByText('合成 l2_fact 保存正文 0：周末沿河散步。');expect(request.mock.calls.length).toBe(2);
});

test('长正文截断和未知来源有明确边界',async()=>{
  const record=storedRecord('l2_fact',0,{content:'有界合成内容',content_chars:40000,content_truncated:true,source_event_ids:null});
  setup('l2_fact','&layer_item='+record.item_id,url=>url.includes('/items/')?layerDetail('l2_fact',record):undefined);
  const drawer=await screen.findByRole('dialog',{name:'l2_fact内容详情'});expect(await within(drawer).findByText('详情正文已截断，原文共 40000 字符')).toBeTruthy();
  expect(within(drawer).getByText('来源关联未提供，不能按零来源解释。')).toBeTruthy();
});

test('越范围404不从别层补读，未确认身份不允许手动绕过读取门控',async()=>{
  const request=vi.spyOn(ChatApi.prototype,'request').mockRejectedValue(new ApiError('not_found',404));
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
  const view=render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/memories?layer_item=outside-scope']}><KnownMemoryEngine kind="hy"><HyLayerBrowser layer="l2_fact" title="L2"/></KnownMemoryEngine></MemoryRouter></QueryClientProvider>);
  const drawer=await screen.findByRole('dialog',{name:'L2内容详情'});
  expect(await within(drawer).findByText('该记录不存在，或不属于当前层和读取范围；未从其他范围补读。')).toBeTruthy();
  expect(request.mock.calls.every(([url])=>url.startsWith('/api/memory-engine/hy/layers/l2_fact'))).toBe(true);view.unmount();request.mockClear();
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/memories?layer_item=outside-scope']}><KnownMemoryEngine kind="hy" value={{phase:'error'}}><HyLayerBrowser layer="l2_fact" title="L2"/></KnownMemoryEngine></MemoryRouter></QueryClientProvider>);
  expect(screen.getByRole('button',{name:'刷新本层'}).hasAttribute('disabled')).toBe(true);expect(request).not.toHaveBeenCalled();
  expect(screen.getByText('当前引擎身份尚未确认，未读取或展示分层详情')).toBeTruthy();
});

test('协议校验拒绝错层、错ID与将部分范围伪装为准确总数',()=>{
  expect(()=>parseHyLayerPage(layerPage('l2_fact'),'l1_raw',0,'all')).toThrow();
  expect(()=>parseHyLayerPage(layerPage('l6_schema',{coverage:'vdb_only_graph_unopened',total:0}),'l6_schema',0,'all')).toThrow();
  expect(()=>parseHyLayerDetail(layerDetail('l2_fact'),'l2_fact','other')).toThrow();
  expect(parseHyLayerPage(layerPage('l2_fact',{total:null}),'l2_fact',0,'all').total).toBeNull();
});

test('L6原生图更新时间、隔离和依据，来源未知不补造；无执行按钮',async()=>{
  const record=semanticRecord('l6_schema',{derivation_state:'isolated',evidence_memory_ids:null,updated_at:null});
  const request=setup('l6_schema','&layer_item='+record.item_id,url=>url.includes('/items/')?layerDetail('l6_schema',record,{coverage:'graph_complete'}):graphPage({items:[record]}));
  const drawer=await screen.findByRole('dialog');await within(drawer).findByText('依据关联未知，不能解释为没有来源。');
  expect(within(drawer).getByText(/当前派生已隔离/)).toBeTruthy();expect(within(drawer).getByText('原生更新时间')).toBeTruthy();
  expect(request.mock.calls.every(([,method])=>!method||method==='GET')).toBe(true);
  expect(request.mock.calls.some(([url])=>url.includes('/semantic/'))).toBe(false);
});

test('L7到期意图不说已完成，真实更新时间与派生依据分别展示',async()=>{
  const record=semanticRecord('l7_intention',{derivation_state:'expired',evidence_memory_ids:['synthetic-source-memory'],valid_until:'2026-10-20T01:00:00Z'});
  setup('l7_intention','&layer_item='+record.item_id,url=>url.includes('/items/')?layerDetail('l7_intention',record):layerPage('l7_intention',{generation_state:'configured',items:[record]}));
  const drawer=await screen.findByRole('dialog');await within(drawer).findByText('synthetic-source-memory');
  expect(within(drawer).getByText('意图已过期')).toBeTruthy();expect(within(drawer).getByText(/有效期已过，不表示意图已经执行或完成/)).toBeTruthy();
});

test('实例按需手动读取，busy保留旧快照且不重试；冷任务链接按页后状态后任务串行读取',async()=>{
  let busy=false;
  const request=setup('l6_schema','&semantic_task=synthetic-evolve-task',url=>{
    if(url.endsWith('/semantic/status'))return busy?Promise.reject(new ApiError('hy_semantic_busy',503)):semanticStatusFixture({schema_state:'isolated'});
    if(url.endsWith('/semantic/tasks/synthetic-evolve-task'))return semanticTaskFixture({state:'uncertain',finished_at:null,elapsed_ms:null,reason_code:'worker_timeout'});
    if(url.includes('/layers/'))return graphPage();
  });
  await screen.findByText('任务耗时');expect(await screen.findByText('结果不确定')).toBeTruthy();
  expect(request.mock.calls.map(([url])=>url)).toEqual(['/api/memory-engine/hy/layers/l6_schema?limit=20&offset=0&state=all','/api/memory-engine/hy/semantic/status','/api/memory-engine/hy/semantic/tasks/synthetic-evolve-task']);
  fireEvent.click(screen.getByLabelText('分层接入与运行证据').querySelector('summary')!);
  const refresh=await screen.findByRole('button',{name:'刷新实例状态'});
  busy=true;fireEvent.click(refresh);
  await screen.findByText('未取得新实例状态，以下保留上次快照');expect(request.mock.calls.length).toBe(4);
  expect(screen.getByText(/上次运行开关快照/)).toBeTruthy();expect(request.mock.calls.every(([,method])=>!method||method==='GET')).toBe(true);
});

test('语义状态501仍保留未知实例；任务404不当作零任务或已完成',async()=>{
  const request=setup('l6_schema','&semantic_task=synthetic-missing-task',url=>{
    if(url.endsWith('/semantic/status'))return Promise.reject(new ApiError('memory_backend_capability_unsupported',501));
    if(url.endsWith('/semantic/tasks/synthetic-missing-task'))return Promise.reject(new ApiError('not_found',404));
    if(url.includes('/layers/'))return graphPage();
  });
  await screen.findByText('该任务不存在或不在可读范围，没有从其他范围补读。');
  expect(screen.getByText('实例能力尚未确认')).toBeTruthy();expect(screen.queryByText('任务已完成',{exact:true})).toBeNull();
  expect(request.mock.calls.map(([url])=>url).filter(url=>url.includes('/semantic/'))).toHaveLength(2);
});

test('冻结AB图页隔离原因在空页也直接显示，不等实例读取或伪装空层',async()=>{
  setup('l6_schema','',()=>graphPage({items:[],total:0,data_state:'empty',reason_code:'schema_injection_isolated'}));
  await screen.findByText('本层图式派生已隔离');expect(screen.queryByText('本层尚无已保存内容')).toBeNull();
  expect(screen.getByText('派生已隔离',{exact:true})).toBeTruthy();
});

test.each(['add:'+'a'.repeat(64)+':expiry','management:synthetic-operation'])('自动任务ID冷链接串行读取并保留原ID：%s',async id=>{
  const taskPath='/api/memory-engine/hy/semantic/tasks/'+encodeURIComponent(id);
  const request=setup('l6_schema','&semantic_task='+encodeURIComponent(id),url=>{
    if(url.endsWith('/semantic/status'))return semanticStatusFixture();
    if(url===taskPath)return semanticTaskFixture({task_id:id});
    if(url.includes('/layers/'))return graphPage();
  });
  await screen.findByText(id,{exact:true});expect(screen.getByRole('textbox',{name:'语义任务 ID',hidden:true}).getAttribute('value')).toBe(id);
  expect(request.mock.calls.map(([url])=>url)).toEqual(['/api/memory-engine/hy/layers/l6_schema?limit=20&offset=0&state=all','/api/memory-engine/hy/semantic/status',taskPath]);
  expect(request.mock.calls.every(([,method])=>!method||method==='GET')).toBe(true);
});
