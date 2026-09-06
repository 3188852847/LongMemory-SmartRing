import {afterEach, describe, expect, test, vi} from 'vitest';
import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import {ChatApi} from './api';
import {ScenarioApp} from './ScenarioApp';
import {createConsoleQueryClient} from './queryClient';

afterEach(() => vi.restoreAllMocks());

describe('L2 生活场景页', () => {
  test('只读加载不会写入，显式填写后才创建候选', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    const calls: Array<[string, string | undefined, unknown]> = [];
    vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path: string, method?: string, body?: unknown) => {
      calls.push([path, method, body]);
      if (path === '/api/memory-config') return {configured:true,database:'synthetic.db',allow_scenario_management:true,scenario_model_preview_available:false,scenario_model:null};
      if (path.startsWith('/api/scenarios?')) return {items:[],total:0,limit:100,offset:0};
      if (path === '/api/scenario-source-inbox') return {items:[
        {id:'l1-a',content:'用户工作日午后经常聊天。',subject_id:'user:self',recorded_at:'2026-09-06T09:00:00Z',source_message_count:1},
        {id:'l1-b',content:'用户忙碌时希望得到温和问候。',subject_id:'user:self',recorded_at:'2026-09-06T10:00:00Z',source_message_count:1},
      ],total:2,limited:false,selection_is_semantic:false};
      if (path.startsWith('/api/memories?')) return {items:[
        {id:'l1-a',content:'用户工作日午后经常聊天。',subject_id:'user:self',state:'active'},
        {id:'l1-b',content:'用户忙碌时希望得到温和问候。',subject_id:'user:self',state:'active'},
      ],total:2,limit:100,offset:0};
      if (path === '/api/scenarios' && method === 'POST') return {id:'scenario-1'};
      if (path === '/api/scenarios/scenario-1') return {id:'scenario-1',subject_id:'user:self',title:'午后陪伴',summary:'工作日下午适合温和问候。',generated_at:'2026-09-06T10:00:00Z',valid_from:null,valid_to:null,status:'candidate',generator_name:'manual_console',generator_version:'1',revision:1,sources:[],lifecycle_events:[]};
      throw new Error(`unexpected ${method ?? 'GET'} ${path}`);
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><MemoryRouter><ScenarioApp/></MemoryRouter></QueryClientProvider>);

    const createButton = await screen.findByRole('button',{name:'新建 L2 候选'});
    await waitFor(() => expect(createButton.hasAttribute('disabled')).toBe(false));
    expect(calls.filter(([, method]) => method === 'POST')).toHaveLength(0);
    fireEvent.click(createButton);
    expect(await screen.findByText('只显示待整理 L1（2）')).toBeTruthy();
    expect(screen.getByText('待整理只表示尚未被当前 L2 覆盖')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('场景标题'), {target:{value:'午后陪伴'}});
    fireEvent.change(screen.getByLabelText('场景总结'), {target:{value:'工作日下午适合温和问候。'}});
    // Ant Design 多选框的键盘交互比直接操作隐藏 input 更接近真实使用。
    fireEvent.mouseDown(screen.getByLabelText('L1 来源'));
    fireEvent.click(await screen.findByText(/用户工作日午后经常聊天。/));
    fireEvent.mouseDown(screen.getByLabelText('L1 来源'));
    fireEvent.click(await screen.findByText(/用户忙碌时希望得到温和问候。/));
    fireEvent.click(screen.getByRole('button',{name:'创建待复核候选'}));

    await waitFor(() => expect(calls.filter(([path, method]) => path === '/api/scenarios' && method === 'POST')).toHaveLength(1));
    const body = calls.find(([path, method]) => path === '/api/scenarios' && method === 'POST')?.[2] as {confirm_candidate:boolean;source_memory_ids:string[];creation_kind:string};
    expect(body.confirm_candidate).toBe(true);
    expect(body.source_memory_ids).toEqual(['l1-a','l1-b']);
    expect(body.creation_kind).toBe('manual');
    view.unmount(); client.clear();
  });

  test('接受先显示独立确认窗，确认前不发送复核请求', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    const calls: Array<[string, string | undefined, unknown]> = [];
    const scenario = {id:'scenario-1',subject_id:'user:self',title:'午后陪伴',summary:'工作日下午适合温和问候。',generated_at:'2026-09-06T10:00:00Z',valid_from:null,valid_to:null,status:'candidate',generator_name:'manual_console',generator_version:'1',revision:1};
    vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path: string, method?: string, body?: unknown) => {
      calls.push([path, method, body]);
      if (path === '/api/memory-config') return {configured:true,database:'synthetic.db',allow_scenario_management:true,scenario_model_preview_available:false,scenario_model:null};
      if (path.startsWith('/api/scenarios?')) return {items:[scenario],total:1,limit:100,offset:0};
      if (path === '/api/scenario-source-inbox') return {items:[],total:0,limited:false,selection_is_semantic:false};
      if (path.startsWith('/api/memories?')) return {items:[],total:0,limit:100,offset:0};
      if (path === '/api/scenarios/scenario-1' && (method === undefined || method === 'GET')) return {...scenario,sources:[],lifecycle_events:[]};
      if (path === '/api/scenarios/scenario-1/reviews' && method === 'POST') return {reviewed:true,status:'active',revision:2};
      throw new Error(`unexpected ${method ?? 'GET'} ${path}`);
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><MemoryRouter><ScenarioApp/></MemoryRouter></QueryClientProvider>);

    fireEvent.click(await screen.findByRole('button',{name:'查看来源'}));
    await waitFor(() => expect(calls.some(([path]) => path === '/api/scenarios/scenario-1')).toBe(true));
    await screen.findByText('生成方式');
    const accept = await screen.findByRole('button',{name:/接\s*受/,hidden:true});
    fireEvent.click(accept);
    expect(await screen.findByText('确认接受 L2 场景')).toBeTruthy();
    expect(screen.getByText(/接受只改变复核状态/)).toBeTruthy();
    expect(calls.filter(([path, method]) => path.endsWith('/reviews') && method === 'POST')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button',{name:/确\s*认\s*接\s*受/}));
    await waitFor(() => expect(calls.filter(([path, method]) => path.endsWith('/reviews') && method === 'POST')).toHaveLength(1));
    view.unmount(); client.clear();
  });

  test('模型只生成不落库草稿，用户另行确认后才创建候选', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    const calls: Array<[string, string | undefined, unknown]> = [];
    vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path: string, method?: string, body?: unknown) => {
      calls.push([path, method, body]);
      if (path === '/api/memory-config') return {configured:true,database:'synthetic.db',allow_scenario_management:true,scenario_model_preview_available:true,scenario_model:'synthetic-model'};
      if (path.startsWith('/api/scenarios?')) return {items:[],total:0,limit:100,offset:0};
      if (path === '/api/scenario-source-inbox') return {items:[],total:0,limited:false,selection_is_semantic:false};
      if (path.startsWith('/api/memories?')) return {items:[
        {id:'l1-a',content:'用户周五要答辩。',subject_id:'user:self',state:'active'},
        {id:'l1-b',content:'用户正在修改 PPT。',subject_id:'user:self',state:'active'},
      ],total:2,limit:100,offset:0};
      if (path === '/api/scenario-proposals' && method === 'POST') return {title:'准备答辩',summary:'用户周五要答辩并正在修改 PPT。',source_memory_ids:['l1-a','l1-b'],generator_name:'model_assisted_console',generator_version:'l2-scenario-preview-v1',model:'synthetic-model',persisted:false};
      if (path === '/api/scenarios' && method === 'POST') return {id:'scenario-1'};
      if (path === '/api/scenarios/scenario-1') return {id:'scenario-1',subject_id:'user:self',title:'准备答辩',summary:'用户周五要答辩并正在修改 PPT。',generated_at:'2026-09-06T10:00:00Z',valid_from:null,valid_to:null,status:'candidate',generator_name:'model_assisted_console',generator_version:'l2-scenario-preview-v1',revision:1,sources:[],lifecycle_events:[]};
      throw new Error(`unexpected ${method ?? 'GET'} ${path}`);
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><MemoryRouter><ScenarioApp/></MemoryRouter></QueryClientProvider>);

    const createButton = await screen.findByRole('button',{name:'新建 L2 候选'});
    await waitFor(() => expect(createButton.hasAttribute('disabled')).toBe(false));
    fireEvent.click(createButton);
    fireEvent.mouseDown(screen.getByLabelText('L1 来源'));
    fireEvent.click(await screen.findByText('用户周五要答辩。'));
    fireEvent.mouseDown(screen.getByLabelText('L1 来源'));
    fireEvent.click(await screen.findByText('用户正在修改 PPT。'));
    fireEvent.click(screen.getByRole('button',{name:'用学校模型生成草稿'}));
    expect(await screen.findByText('确认发送所选 L1 给学校模型')).toBeTruthy();
    expect(calls.filter(([path]) => path === '/api/scenario-proposals')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button',{name:'生成不落库草稿'}));
    await waitFor(() => expect(calls.filter(([path]) => path === '/api/scenario-proposals')).toHaveLength(1));
    expect(calls.filter(([path]) => path === '/api/scenarios')).toHaveLength(0);
    expect((screen.getByLabelText('场景标题') as HTMLInputElement).value).toBe('准备答辩');
    fireEvent.click(screen.getByRole('button',{name:'创建待复核候选'}));
    await waitFor(() => expect(calls.filter(([path]) => path === '/api/scenarios')).toHaveLength(1));
    const body = calls.find(([path]) => path === '/api/scenarios')?.[2] as {creation_kind:string};
    expect(body.creation_kind).toBe('model_assisted');
    view.unmount(); client.clear();
  });

  test('结束已接受场景先确认，随后留下生命周期操作请求', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    const calls: Array<[string, string | undefined, unknown]> = [];
    const scenario = {id:'scenario-1',subject_id:'user:self',title:'准备答辩',summary:'用户本周正在准备答辩。',generated_at:'2026-09-06T10:00:00Z',valid_from:null,valid_to:null,status:'active',generator_name:'manual_console',generator_version:'1',revision:2};
    vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path: string, method?: string, body?: unknown) => {
      calls.push([path, method, body]);
      if (path === '/api/memory-config') return {configured:true,database:'synthetic.db',allow_scenario_management:true,scenario_model_preview_available:false,scenario_model:null};
      if (path.startsWith('/api/scenarios?')) return {items:[scenario],total:1,limit:100,offset:0};
      if (path === '/api/scenario-source-inbox') return {items:[],total:0,limited:false,selection_is_semantic:false};
      if (path.startsWith('/api/memories?')) return {items:[],total:0,limit:100,offset:0};
      if (path === '/api/scenarios/scenario-1' && (method === undefined || method === 'GET')) return {...scenario,sources:[],lifecycle_events:[]};
      if (path === '/api/scenarios/scenario-1/lifecycle' && method === 'POST') return {ended:true,status:'stale',revision:3};
      throw new Error(`unexpected ${method ?? 'GET'} ${path}`);
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><MemoryRouter><ScenarioApp/></MemoryRouter></QueryClientProvider>);

    fireEvent.click(await screen.findByRole('button',{name:'查看来源'}));
    await screen.findByText('生命周期记录');
    fireEvent.click(await screen.findByRole('button',{name:'结束场景'}));
    expect(await screen.findByText('确认结束这个 L2 场景')).toBeTruthy();
    expect(calls.filter(([path, method]) => path.endsWith('/lifecycle') && method === 'POST')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button',{name:/确\s*认\s*结\s*束/}));
    await waitFor(() => expect(calls.filter(([path, method]) => path.endsWith('/lifecycle') && method === 'POST')).toHaveLength(1));
    const body = calls.find(([path, method]) => path.endsWith('/lifecycle') && method === 'POST')?.[2];
    expect(body).toEqual({action:'manual_end',expected_revision:2,confirm_action:true});
    view.unmount(); client.clear();
  });
});
