import {afterEach,expect,test,vi} from 'vitest';
import {fireEvent,render,screen,within} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {ApiError,ChatApi} from '../../api';
import {parseHyMechanisms} from '../../api/hyMechanisms';
import {mechanismFixture} from '../../tests/fixtures/hyMechanisms';
import {KnownMemoryEngine} from '../../tests/memoryEngine';
import {HyMechanismsWorkspace} from './HyMechanismsWorkspace';
afterEach(()=>vi.restoreAllMocks());
function setup(route='/memories?view=mechanisms',response:unknown=mechanismFixture,kind:'hy'|'legacy'='hy') {
  const request=vi.spyOn(ChatApi.prototype,'request').mockImplementation(async path=>{if(path==='/api/memory-engine/hy/mechanisms')return response as never;throw new Error('unexpected '+path);});
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter initialEntries={[route]}><KnownMemoryEngine kind={kind}><HyMechanismsWorkspace/></KnownMemoryEngine></MemoryRouter></QueryClientProvider>);
  return request;
}

test('完整动态目录、选择与真实来源入口；不调用SDK列表/检索/配置',async()=>{
  const request=setup();const directory=await screen.findByRole('navigation',{name:'完整机制目录'});
  expect(within(directory).getAllByRole('button').length).toBe(mechanismFixture.mechanisms.length);
  for(const item of mechanismFixture.mechanisms)expect(within(directory).getByRole('button',{name:new RegExp(item.title.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'))})).toBeTruthy();
  fireEvent.click(within(directory).getByRole('button',{name:/来源与平台处理状态/}));
  expect(screen.getByRole('link',{name:'从条目选择单条平台来源'}).getAttribute('href')).toBe('/memories?view=items');
  expect(request.mock.calls.map(([p])=>p)).toEqual(['/api/memory-engine/hy/mechanisms']);
});

test('八层编号与平台来源分开；关闭/保留不当作零',async()=>{
  setup('/memories?view=mechanisms&mechanism_tab=layers&layer=l7_intention');
  expect(await screen.findByText('平台原话不等于 Hy L0')).toBeTruthy();
  expect(screen.getByRole('heading',{name:/Hy L7/})).toBeTruthy();
  expect(screen.getByText('条目数量：未知。该声明接口不扫描或计数，不能用 0 代替未知。')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:/Hy L4/}));expect(screen.getByRole('heading',{name:/Hy L4/})).toBeTruthy();
  expect(screen.getAllByText('保留层').length).toBeGreaterThan(0);
});

test('模式/场景及全部边界可探索，不出现启用开关',async()=>{
  setup('/memories?view=mechanisms&mechanism_tab=boundaries');
  expect(await screen.findByRole('heading',{name:'模式与场景'})).toBeTruthy();
  expect(screen.getAllByRole('button',{name:'查看机制与证据'}).length).toBe(mechanismFixture.mechanisms.length);
  expect(screen.queryByRole('switch')).toBeNull();
  fireEvent.click(screen.getAllByRole('button',{name:'查看机制与证据'})[1]);expect(await screen.findByRole('heading',{name:/System 2/})).toBeTruthy();
});

test('SDK历史关闭与平台审计分开，注入缺口如实说明',async()=>{
  setup('/memories?view=mechanisms&mechanism=sdk_history');
  expect(await screen.findByText('SDK 历史开关与平台管理审计不同。当前关闭时不能用空历史推断没有发生变化。')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'证据入口'}));
  expect(screen.getByRole('link',{name:'查看管理记录'}).getAttribute('href')).toBe('/memories?view=activity');
  expect(screen.getByText(/没有逐次最终注入证据接口/)).toBeTruthy();
});

test('busy保留旧快照和原时间，不轮询或伪装最新',async()=>{
  const request=setup();await screen.findByText('本次装配声明');
  request.mockRejectedValue(new ApiError('hy_mechanisms_busy',503));fireEvent.click(screen.getByRole('button',{name:'刷新声明'}));
  expect(await screen.findByText('未取得新声明，以下保留上次快照')).toBeTruthy();expect(screen.getByText('上次装配声明')).toBeTruthy();
  expect(screen.queryByText('本次装配声明')).toBeNull();expect(request.mock.calls.length).toBe(2);
});

test('首次错误、空目录与版本不符分开，不读取旧库',async()=>{
  setup('/memories?view=mechanisms',{...mechanismFixture,sdk:{version:'2.0.4',source_commit:'other'}});
  expect(await screen.findByText(/机制快照结构或固定版本不匹配/)).toBeTruthy();expect(screen.queryByText('本次装配声明')).toBeNull();
});

test('空目录不推断为空库',async()=>{
  setup('/memories?view=mechanisms',{...mechanismFixture,mechanisms:[]});expect(await screen.findByText('接口没有提供机制条目；这不表示记忆库为空')).toBeTruthy();
});

test('追加目录项不用改前端穷尽列表',async()=>{
  const extra={...mechanismFixture.mechanisms[0],id:'extra-family',group:'future',title:'合成新增机制族',integration:'unknown'};
  setup('/memories?view=mechanisms',{...mechanismFixture,mechanisms:[...mechanismFixture.mechanisms,extra]});expect(await screen.findByRole('button',{name:/合成新增机制族/})).toBeTruthy();
});

test('旧引擎直接机制书签保留兼容，不调用Hy接口',async()=>{
  const request=setup('/memories?view=mechanisms',undefined,'legacy');expect(await screen.findByText('原记忆引擎，当前未选择 Hy')).toBeTruthy();expect(request).not.toHaveBeenCalled();
});

test('协议拒绝冒充计数、重复标识和本机路径',()=>{
  expect(()=>parseHyMechanisms({...mechanismFixture,layers:[{...mechanismFixture.layers[0],count:0}]})).toThrow();
  expect(()=>parseHyMechanisms({...mechanismFixture,mechanisms:[mechanismFixture.mechanisms[0],mechanismFixture.mechanisms[0]]})).toThrow();
  expect(()=>parseHyMechanisms({...mechanismFixture,mechanisms:[{...mechanismFixture.mechanisms[0],evidence:['D:/private/config.yaml']}]})).toThrow();
});
