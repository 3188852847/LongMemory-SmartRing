import {afterEach,expect,test,vi} from 'vitest';
import {fireEvent,render,screen,within} from '@testing-library/react';
import {MemoryRouter,useLocation} from 'react-router-dom';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {ApiError,ChatApi} from '../../api';
import {parseHyLayerDetail,parseHyLayerPage,type HyLayerId} from '../../api/hyLayerData';
import {KnownMemoryEngine} from '../../tests/memoryEngine';
import {layerDetail,layerPage,profileRecord,profileVersions,storedRecord} from '../../tests/fixtures/hyLayerData';
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
