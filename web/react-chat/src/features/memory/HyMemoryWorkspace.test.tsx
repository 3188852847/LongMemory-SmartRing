import {afterEach,expect,test,vi} from 'vitest';
import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {MemoryRouter,Route,Routes} from 'react-router-dom';
import {ChatApi,ApiError,type EngineItem} from '../../api';
import {HyMemoryWorkspace,memoryTime} from './HyMemoryWorkspace';
import {MemoryDomainRoute} from './MemoryDomainRoute';

afterEach(()=>vi.restoreAllMocks());
const item:EngineItem={item_id:'synthetic-1',content:'合成用户周末照顾一只猫。',kind:'l2_fact',revision:'a'.repeat(64),source_event_ids:['source-one','source-two'],recorded_at:null,valid_from:null,valid_to:null,state:'ACTIVE'};
const status={method:'hy_memory_pro_chat',write_enabled:true,use_enabled:true,management_capabilities:{listing:true,detail:true},deferred_observation:{supported:true,awaiting_completion:2,running_or_queued:1,last_result:{state:'uncertain',warning_code:'synthetic-warning'}}};
const workspace={protocol:1,profile:false,history:true,operations:true,correction:true,deletion:true,write_enabled:true,use_enabled:true};
function setup(route='/memories',override?:(path:string,method:string,body:unknown)=>unknown|Promise<unknown>) {
  const request=vi.spyOn(ChatApi.prototype,'request').mockImplementation(async(path,method='GET',body)=>{
    const custom=await override?.(path,method,body);if(custom!==undefined)return custom as never;
    if(path==='/api/memory-engine')return status as never;
    if(path==='/api/memory-engine/hy/workspace')return workspace as never;
    if(path.startsWith('/api/memory-engine/items?'))return {items:[item],total:26,limit:25,offset:Number(new URLSearchParams(path.split('?')[1]).get('offset'))} as never;
    if(path==='/api/memory-engine/items/synthetic-1')return item as never;
    if(path.startsWith('/api/memory-engine/hy/operations?'))return {items:[],total:0,limit:25,offset:0} as never;
    if(path==='/api/memory-engine/hy/items/synthetic-1/history')return {items:[],limited:false,recording_complete:false} as never;
    throw new Error(`unexpected synthetic path ${path}`);
  });
  render(<MemoryRouter initialEntries={[route]}><HyMemoryWorkspace api={new ChatApi()} method="hy_memory_pro_chat" capabilities={{listing:true,detail:true}}/></MemoryRouter>);
  return request;
}

test('真实分页、本页筛选与任务导航，不调用全库 search 或旧数据库',async()=>{
  const request=setup();
  expect(await screen.findByText(item.content)).toBeTruthy();
  expect(screen.getByRole('link',{name:'我的记忆'})).toBeTruthy();
  expect(screen.queryByRole('link',{name:'生活场景'})).toBeNull();
  fireEvent.change(screen.getByLabelText('在本页查找'),{target:{value:'不匹配'}});
  expect(await screen.findByText('本页没有符合筛选条件的记忆')).toBeTruthy();
  expect(request.mock.calls.some(([path])=>path.includes('search')||path.includes('/api/memories'))).toBe(false);
  fireEvent.click(screen.getByRole('button',{name:'下一页'}));
  await waitFor(()=>expect(request.mock.calls.some(([path])=>path==='/api/memory-engine/items?limit=25&offset=25')).toBe(true));
  expect((screen.getByLabelText('在本页查找') as HTMLInputElement).value).toBe('');
});

test('首次失败与重读、零条目与来源未知不会冒充成功',async()=>{
  let count=0;
  setup('/memories',(path)=>{if(path.startsWith('/api/memory-engine/items?')){if(count++===0)throw new ApiError('hy_management_unavailable',503);return {items:[],total:0,limit:25,offset:0};}});
  expect(await screen.findByText('记忆列表读取失败')).toBeTruthy();
  expect(screen.queryByText('这一页还没有记忆条目')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'重新读取列表'}));
  expect(await screen.findByText('这一页还没有记忆条目')).toBeTruthy();
  expect(screen.getByRole('button',{name:'下一页'}).hasAttribute('disabled')).toBe(true);
});

test('详情只在选择后读取单条原话，单来源失败保留其他来源入口',async()=>{
  const request=setup('/memories?item=synthetic-1',(path)=>{if(path.endsWith('/sources/source-one'))throw new ApiError('missing',404);if(path.endsWith('/sources/source-two'))return {event_id:'source-two',role:'assistant',content:'合成助手建议养猫，不是用户事实。',occurred_at:null,state:'archived',session_id:null,attempt_id:null};});
  const dialog=await screen.findByRole('dialog',{name:'记忆详情'});
  await within(dialog).findByText('依据是什么');
  expect(request.mock.calls.some(([path])=>path.includes('/sources/'))).toBe(false);
  fireEvent.change(within(dialog).getByRole('combobox',{name:'选择一条来源回看'}),{target:{value:'source-one'}});
  expect(await screen.findByText('这条来源未读到')).toBeTruthy();
  fireEvent.change(within(dialog).getByRole('combobox',{name:'选择一条来源回看'}),{target:{value:'source-two'}});
  expect(await screen.findByText('助手原话（不是用户事实）')).toBeTruthy();
  expect(screen.getByText('合成助手建议养猫，不是用户事实。')).toBeTruthy();
  expect(request.mock.calls.filter(([path])=>path.includes('/sources/')).length).toBe(2);
});

test('来源未知与历史空结果均不推断成无来源/从未变化',async()=>{
  setup('/memories?item=synthetic-1',(path)=>path==='/api/memory-engine/items/synthetic-1'?{...item,source_event_ids:null}:undefined);
  const dialog=await screen.findByRole('dialog',{name:'记忆详情'});
  expect(await within(dialog).findByText(/引擎没有提供来源关联/)).toBeTruthy();
  expect(within(dialog).queryByRole('combobox')).toBeNull();
  fireEvent.click(await within(dialog).findByRole('button',{name:'读取这条变化记录'}));
  expect(await within(dialog).findByText('未读到变化记录。可能尚无变化，也可能引擎未开启历史记录。')).toBeTruthy();
});

test('扩展未接通仍可浏览，画像不跨越范围能力',async()=>{
  const request=setup('/memories?view=profile',(path)=>{if(path==='/api/memory-engine/hy/workspace')throw new ApiError('unsupported',501);});
  expect(await screen.findByText('基本画像暂不可读取')).toBeTruthy();
  await screen.findByText('当前引擎尚未接通这项管理能力。');
  expect(request.mock.calls.some(([path])=>path.endsWith('/hy/profile'))).toBe(false);
});

test('状态视图区分处理结果/等待回执/未启用能力',async()=>{
  setup('/memories?view=status');
  expect(await screen.findByText('结果不确定')).toBeTruthy();
  expect(screen.getByText('等待设备完成回执')).toBeTruthy();
  expect(screen.getByText('2')).toBeTruthy();
  expect(screen.getByText(/图谱、意图和深层认知加工未启用/)).toBeTruthy();
});

test('更正明确来源、阻止双击；成功后真实回读',async()=>{
  let resolveWrite!:(value:unknown)=>void;let writes=0;let corrected=false;let lastRequestId='';
  const request=setup('/memories?item=synthetic-1',(path,method,body)=>{
    if(path.endsWith('/corrections')){expect(method).toBe('POST');expect(body).toMatchObject({revision:item.revision,content:'合成用户现在照顾一只狗。'});expect((body as {request_id:string}).request_id).toMatch(/^[a-f0-9-]{36}$/);lastRequestId=(body as {request_id:string}).request_id;writes++;return new Promise(resolve=>{resolveWrite=value=>{corrected=true;resolve(value);};});}
    if(path==='/api/memory-engine/items/synthetic-1'&&corrected)return {...item,content:'合成用户现在照顾一只狗。',revision:'b'.repeat(64)};
  });
  fireEvent.click(await screen.findByRole('button',{name:'纠正这条记忆'}));
  // rc 组件在 NODE_ENV=test 时统一生成 test-id，嵌套弹层标题 ID 冲突；从可见表单定位。
  const modal=(await screen.findByLabelText('正确的内容')).closest('[role=dialog]') as HTMLElement;
  fireEvent.change(within(modal).getByLabelText('正确的内容'),{target:{value:'合成用户现在照顾一只狗。'}});
  fireEvent.click(within(modal).getByRole('checkbox'));
  const save=within(modal).getByRole('button',{name:'保存纠正'});
  fireEvent.click(save);fireEvent.click(save);
  await waitFor(()=>expect(writes).toBe(1));
  resolveWrite({request_id:lastRequestId,state:'completed',replayed:false,platform_sources_preserved:true});
  expect(await screen.findByText(/纠正已完成。平台原话保留/)).toBeTruthy();
  await waitFor(()=>expect(request.mock.calls.filter(([path])=>path==='/api/memory-engine/items/synthetic-1').length).toBeGreaterThan(1));
});

test('不确定写入禁用重复提交，绝不显示成功',async()=>{
  let writes=0;
  setup('/memories?item=synthetic-1',(path)=>{if(path.endsWith('/deletion')){writes++;throw new ApiError('hy_management_outcome_uncertain',503);}});
  fireEvent.click(await screen.findByRole('button',{name:'删除这条记忆'}));
  const modal=(await screen.findByText('删除这条引擎记忆',{selector:'.ant-modal-title span'})).closest('[role=dialog]') as HTMLElement;
  expect(within(modal).getByText(/不是全部隐私数据擦除/)).toBeTruthy();
  fireEvent.click(within(modal).getByRole('checkbox'));
  fireEvent.click(within(modal).getByRole('button',{name:/确认删除条目/}));
  expect(await within(modal).findByText(/操作结果不确定/)).toBeTruthy();
  expect(within(modal).getByRole('button',{name:/确认删除条目/}).hasAttribute('disabled')).toBe(true);
  expect(writes).toBe(1);
  expect(screen.queryByText(/引擎条目已删除/)).toBeNull();
});

test('时间未知及无效格式如实呈现',()=>{expect(memoryTime(null)).toBe('时间未记录');expect(memoryTime('invalid')).toBe('时间格式未知');});

test('确定性删除拒绝保留说明，不误报不确定或永久锁住条目',async()=>{
  let writes=0;
  setup('/memories?item=synthetic-1',path=>{if(path.endsWith('/deletion')){writes++;throw new ApiError('hy_management_delete_evolution_refused',409);}});
  fireEvent.click(await screen.findByRole('button',{name:'删除这条记忆'}));
  const modal=(await screen.findByText('删除这条引擎记忆',{selector:'.ant-modal-title span'})).closest('[role=dialog]') as HTMLElement;
  fireEvent.click(within(modal).getByRole('checkbox'));
  fireEvent.click(within(modal).getByRole('button',{name:/确认删除条目/}));
  expect(await within(modal).findByText('操作未执行')).toBeTruthy();
  expect(within(modal).getByText(/不能单独删除，以免恢复旧事实。当前有效条目/)).toBeTruthy();
  expect(within(modal).queryByText(/结果未确认，已禁止重复提交/)).toBeNull();
  expect(writes).toBe(1);
  fireEvent.click(within(modal).getByRole('button',{name:'取消'}));
  await waitFor(()=>expect(screen.getByRole('button',{name:'纠正这条记忆'}).hasAttribute('disabled')).toBe(false));
});

test('组装画像在自己的详情核对，不把聚合编号交给普通条目 get',async()=>{
  const request=setup('/memories?view=profile',(path)=>{
    if(path==='/api/memory-engine/hy/workspace')return {...workspace,profile:true};
    if(path==='/api/memory-engine/hy/profile')return {item:{...item,item_id:'assembled-profile',kind:'l0_basic_info',source_event_ids:null}};
  });
  fireEvent.click(await screen.findByRole('button',{name:'核对画像详情与来源'}));
  const dialog=await screen.findByRole('dialog',{name:'记忆详情'});
  expect(await within(dialog).findByText('基本信息')).toBeTruthy();
  expect(within(dialog).queryByRole('button',{name:'纠正这条记忆'})).toBeNull();
  expect(request.mock.calls.some(([path])=>path.includes('/items/assembled-profile'))).toBe(false);
});

test('旧记忆书签先确认引擎再跳到新任务，不挂载旧页',async()=>{
  vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
  vi.spyOn(ChatApi.prototype,'request').mockResolvedValue({representation:'method_defined'});
  const legacy=vi.fn(()=> <p>不应挂载</p>);
  const Legacy=legacy;
  render(<MemoryRouter initialEntries={['/personas']}><Routes><Route path="/personas" element={<MemoryDomainRoute legacy={<Legacy/>} view="profile"/>}/><Route path="/memories" element={<p>新记忆任务</p>}/></Routes></MemoryRouter>);
  expect(await screen.findByText('新记忆任务')).toBeTruthy();expect(legacy).not.toHaveBeenCalled();
});
