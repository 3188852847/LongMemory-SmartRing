import {afterEach,expect,test,vi} from 'vitest';
import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {Link,MemoryRouter} from 'react-router-dom';
import {ApiError,ChatApi} from '../api';
import {MemoryEngineProvider,useMemoryEngine,useMemorySummary,memoryEngineLabel,parseMemoryIdentity} from './MemoryEngineProvider';
import {ConsoleNav} from '../components/AppShell';
import {hyIdentity,legacyIdentity} from '../tests/memoryEngine';

afterEach(()=>vi.restoreAllMocks());
function Surface(){const engine=useMemoryEngine();const count=useMemorySummary();return <><p>聊天主体始终可用</p><p role="status">{memoryEngineLabel(engine)}</p><p>{engine.issue}</p><p>{count.data?.total}</p><button onClick={engine.refresh}>重新读取身份</button><ConsoleNav active="overview" legacyPath="/chat"/><Link to="/device">到设备</Link></>;}
function mount(route='/overview') {return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter initialEntries={[route]}><MemoryEngineProvider><Surface/></MemoryEngineProvider></MemoryRouter></QueryClientProvider>);}

test('冷加载身份未返回时保持中立且不阻塞主体，Hy 不取旧配置或统计',async()=>{
  vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
  let finish!:(value:unknown)=>void;
  const request=vi.spyOn(ChatApi.prototype,'request').mockImplementation(async path=>{if(path==='/api/memory-engine/identity')return await new Promise<unknown>(resolve=>{finish=resolve;}) as never;throw new Error('unexpected '+path);});
  mount();expect(screen.getByText('聊天主体始终可用')).toBeTruthy();
  expect(screen.queryByRole('link',{name:'原话与事实'})).toBeNull();
  expect(screen.getByRole('link',{name:'记忆机制'})).toBeTruthy();
  await waitFor(()=>expect(finish).toBeTypeOf('function'));finish(hyIdentity);
  await screen.findByRole('link',{name:'我的记忆'});
  expect(request.mock.calls.map(([p])=>p)).toEqual(['/api/memory-engine/identity']);
  fireEvent.click(screen.getByRole('link',{name:'到设备'}));
  expect(request.mock.calls.length).toBe(1);
});

test('只有已确认旧引擎才保留旧导航和旧统计',async()=>{
  vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
  const request=vi.spyOn(ChatApi.prototype,'request').mockImplementation(async path=>{if(path==='/api/memory-engine/identity')return legacyIdentity as never;if(path.startsWith('/api/memories?'))return {total:7} as never;throw new Error(path);});
  mount();await screen.findByRole('link',{name:'原话与事实'});await screen.findByText('7');
  expect(request.mock.calls.some(([p])=>p.startsWith('/api/memory-engine/items'))).toBe(false);
});

test('未初始化且method=null不猜旧方法，不读库',async()=>{
  vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
  const request=vi.spyOn(ChatApi.prototype,'request').mockResolvedValue({...legacyIdentity,method:null,state:'not_initialized'});
  mount();await screen.findAllByText('记忆已配置，尚未初始化');
  expect(screen.queryByRole('link',{name:'原话与事实'})).toBeNull();
  expect(request.mock.calls.length).toBe(1);
});

test('首次繁忙不回退旧引擎，手动刷新才重试',async()=>{
  vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
  let available=false;const request=vi.spyOn(ChatApi.prototype,'request').mockImplementation(async()=>{if(!available)throw new ApiError('memory_identity_busy',503);return hyIdentity as never;});
  mount();await screen.findByText('busy');expect(screen.queryByRole('link',{name:'原话与事实'})).toBeNull();
  expect(request.mock.calls.length).toBe(1);available=true;fireEvent.click(screen.getByRole('button',{name:'重新读取身份'}));
  await screen.findByRole('link',{name:'我的记忆'});expect(request.mock.calls.length).toBe(2);
});

test('刷新失败保留上次Hy入口并明示上次确认',async()=>{
  vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
  let failed=false;vi.spyOn(ChatApi.prototype,'request').mockImplementation(async()=>{if(failed)throw new ApiError('memory_identity_unavailable',503);return hyIdentity as never;});
  mount('/memories?view=mechanisms');await screen.findByRole('link',{name:'我的记忆'});
  const nav=screen.getByRole('navigation',{name:'控制台导航'});expect(within(nav).getByRole('link',{name:'记忆机制'}).getAttribute('aria-current')).toBe('page');
  expect(within(nav).getByRole('link',{name:'我的记忆'}).getAttribute('aria-current')).toBeNull();
  failed=true;fireEvent.click(screen.getByRole('button',{name:'重新读取身份'}));await screen.findByText('Hy-Memory（上次确认）');
  expect(screen.getByRole('link',{name:'我的记忆'})).toBeTruthy();expect(screen.queryByRole('link',{name:'生活场景'})).toBeNull();
});

test('畸形身份不按旧版猜测',()=>{
  expect(()=>parseMemoryIdentity({configured:true})).toThrow();
  expect(()=>parseMemoryIdentity({...hyIdentity,representation:'atomic_fact'})).toThrow();
  expect(()=>parseMemoryIdentity({...hyIdentity,state:'unconfigured',configured:false})).toThrow();
  expect(()=>parseMemoryIdentity({...hyIdentity,state:'not_initialized',method:null})).toThrow();
  expect(parseMemoryIdentity({...legacyIdentity,method:null,state:'not_initialized'}).method).toBeNull();
});
