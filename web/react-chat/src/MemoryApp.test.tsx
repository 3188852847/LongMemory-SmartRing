import {afterEach,describe,expect,test,vi} from 'vitest';
import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {ChatApi} from './api';
import {MemoryApp} from './MemoryApp';

afterEach(()=>vi.restoreAllMocks());

describe('每日记忆回顾',()=>{
  test('从圆屏质量样本直达指定用户 L0',async()=>{
    vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype,'request').mockImplementation(async path=>{
      if(path==='/api/memory-config') return {configured:true,database:'synthetic.db',allow_delete:true,allow_correction:true,allow_change:true,allow_promote_source:true} as never;
      if(path==='/api/memory-mode') return {write_enabled:true,use_enabled:true,scenario_use_enabled:false,scenario_available:true,persona_use_enabled:false,persona_available:true,persistent:false,l0_archived_when_write_disabled:true} as never;
      if(path==='/api/consolidation-status') return {background_enabled:false,stages:[]} as never;
      if(path.startsWith('/api/memories/daily-review')) return {local_date:'2026-09-10',utc_offset_minutes:480,items:[],total:0,limited:false,activity_counts:{added:0,corrected:0,changed:0,deleted:0},message_counts:{user:1,assistant:1,total:2,unlinked_user:1},quality_counts:{owner_confirmed_missed_extraction:0},deletions:[],deletions_limited:false} as never;
      if(path.startsWith('/api/chat-memory-feedback/daily')) return {local_date:'2026-09-10',utc_offset_minutes:480,total:0,limited:false,action_counts:{memory_ok:0,recall_miss:0,wrong_memory:0,memory_irrelevant:0},items:[],current_total:0,current_limited:false,current_counts:{memory_ok:0,recall_miss:0,wrong_memory:0,memory_irrelevant:0},current_items:[]} as never;
      if(path.startsWith('/api/memories?')) return {items:[],total:0,limit:25,offset:0} as never;
      if(path==='/api/source-messages/l0-user') return {id:'l0-user',role:'user',content:'合成圆屏问题',created_at:'2026-09-10T01:00:00Z',derived_memories:[],revision:'a'.repeat(64)} as never;
      throw new Error(`unexpected test path: ${path}`);
    });
    const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/memories?l0_message_id=l0-user']}><MemoryApp/></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText('合成圆屏问题')).toBeTruthy();
    expect(screen.getByText(/已从圆屏质量反馈打开对应用户 L0/)).toBeTruthy();
  });

  test('从当天回顾直达已有的追加式纠正确认窗',async()=>{
    const item={id:'memory-1',content:'用户喜欢乌龙茶。',truncated:false,state:'active' as const,activity:'added' as const,
      recorded_at:'2026-09-09T08:00:00+00:00',subject_id:'user:self'};
    vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype,'request').mockImplementation(async path=>{
      if(path==='/api/memory-config') return {configured:true,database:'synthetic.db',allow_delete:true,allow_correction:true,allow_change:true,allow_promote_source:true} as never;
      if(path==='/api/memory-mode') return {write_enabled:true,use_enabled:true,scenario_use_enabled:false,scenario_available:true,persona_use_enabled:false,persona_available:true,persistent:false,l0_archived_when_write_disabled:true} as never;
      if(path==='/api/consolidation-status') return {background_enabled:false,stages:[]} as never;
      if(path.startsWith('/api/memories/daily-review')) return {local_date:'2026-09-09',utc_offset_minutes:480,items:[item],total:1,limited:false,activity_counts:{added:1,corrected:0,changed:0,deleted:1},message_counts:{user:3,assistant:3,total:6,unlinked_user:1},quality_counts:{owner_confirmed_missed_extraction:0},deletions:[{id:'deletion-1',memory_id:'deleted-memory-1',subject_id:'user:self',deleted_at:'2026-09-09T09:00:00+00:00'}],deletions_limited:false} as never;
      if(path.startsWith('/api/chat-memory-feedback/daily')) return {local_date:'2026-09-09',utc_offset_minutes:480,total:1,limited:false,action_counts:{memory_ok:0,recall_miss:1,wrong_memory:0,memory_irrelevant:0},items:[{chat_id:'chat-1',chat_title:'猫咪',request_id:'request-1',kind:'recall_miss',revision:1,occurred_at:'2026-09-09T09:30:00+00:00',is_current:true}],current_total:1,current_limited:false,current_counts:{memory_ok:0,recall_miss:1,wrong_memory:0,memory_irrelevant:0},current_items:[{chat_id:'chat-1',chat_title:'猫咪',request_id:'request-1',kind:'recall_miss',revision:1,occurred_at:'2026-09-09T09:30:00+00:00'}]} as never;
      if(path.startsWith('/api/source-messages?')) return {items:[{id:'source-unlinked',role:'user',content:'我最近开始晨跑。',truncated:false,created_at:'2026-09-09T07:00:00+00:00',linked_memory_count:0}],total:1,limit:25,offset:0} as never;
      if(path==='/api/memories/memory-1') return {...item,revision:'a'.repeat(64),valid_from:null,valid_to:null,retired_at:null,superseded_by_id:null,sources:[]} as never;
      if(path.startsWith('/api/memories?')) return {items:[item],total:1,limit:25,offset:0} as never;
      throw new Error(`unexpected test path: ${path}`);
    });

    const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
    render(<QueryClientProvider client={client}><MemoryRouter><MemoryApp/></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText(/每日记忆回顾/)).toBeTruthy();
    expect((await screen.findAllByText('用户喜欢乌龙茶。')).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('新增 1')).toBeTruthy();
    expect(screen.getByText(/当天归档 L0：用户 3 条，助手 3 条/)).toBeTruthy();
    expect(screen.getByText(/其中 1 条用户原话没有形成 L1/)).toBeTruthy();
    expect(screen.getByText('删除 1')).toBeTruthy();
    expect(screen.getByText('没想起 1')).toBeTruthy();
    fireEvent.click(screen.getByText(/回看当前判断/));
    expect(screen.getByRole('link',{name:'查看回答与证据'}).getAttribute('href')).toBe('/chat-react?chat_id=chat-1&request_id=request-1');
    fireEvent.click(screen.getByText(/查看删除审计/));
    expect(screen.getByText('deleted-memory-1')).toBeTruthy();
    expect(screen.getByText(/不保留被删正文/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'核对当天未形成 L1 的原话'}));
    await waitFor(()=>expect(screen.getByText('我最近开始晨跑。')).toBeTruthy());
    const today=new Date();
    const expectedDate=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
    expect(screen.getByLabelText('L0 日期').getAttribute('value')).toBe(expectedDate);
    fireEvent.click(screen.getByText('L1 原子记忆 · 1'));
    const correctionButton=screen.getByRole('button',{name:'直接纠正'});
    await waitFor(()=>expect(correctionButton.hasAttribute('disabled')).toBe(false));
    fireEvent.click(correctionButton);
    expect(await screen.findByText('纠正 L1')).toBeTruthy();
    expect(screen.getByText(/新建 L1，并保留旧记录/)).toBeTruthy();
  });

  test('把未关联的用户 L0 补成 L1 并保留原来源', async () => {
    const source = {
      id: 'source-unlinked',
      role: 'user' as const,
      content: '我最近开始晨跑。',
      truncated: false,
      created_at: '2026-09-09T07:00:00+00:00',
      linked_memory_count: 0,
    };
    const promoted = {
      id: 'memory-promoted',
      content: '用户最近开始每天晨跑。',
      truncated: false,
      state: 'active' as const,
      recorded_at: '2026-09-09T08:00:00+00:00',
      subject_id: 'user:self',
    };
    const calls: Array<{path: string; method: string; body: unknown}> = [];
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path, method = 'GET', body) => {
      calls.push({path, method, body});
      if (path === '/api/memory-config') return {configured: true, database: 'synthetic.db', allow_delete: true, allow_correction: true, allow_change: true, allow_promote_source: true} as never;
      if (path === '/api/memory-mode') return {write_enabled: true, use_enabled: true, scenario_use_enabled: false, scenario_available: true, persona_use_enabled: false, persona_available: true, persistent: false, l0_archived_when_write_disabled: true} as never;
      if (path === '/api/consolidation-status') return {background_enabled: false, stages: []} as never;
      if (path.startsWith('/api/memories/daily-review')) return {local_date: '2026-09-09', utc_offset_minutes: 480, items: [], total: 0, limited: false, activity_counts: {added: 0, corrected: 0, changed: 0, deleted: 0}, message_counts: {user: 1, assistant: 0, total: 1, unlinked_user: 1}, quality_counts: {owner_confirmed_missed_extraction: calls.some(call => call.path.endsWith('/promote') && call.method === 'POST') ? 1 : 0}, deletions: [], deletions_limited: false} as never;
      if (path.startsWith('/api/chat-memory-feedback/daily')) return {local_date:'2026-09-09',utc_offset_minutes:480,total:0,limited:false,action_counts:{memory_ok:0,recall_miss:0,wrong_memory:0,memory_irrelevant:0},items:[],current_total:0,current_limited:false,current_counts:{memory_ok:0,recall_miss:0,wrong_memory:0,memory_irrelevant:0},current_items:[]} as never;
      if (path.startsWith('/api/source-messages?')) return {items: [source], total: 1, limit: 25, offset: 0} as never;
      if (path === '/api/source-messages/source-unlinked') return {...source, revision: 'b'.repeat(64), derived_memories: []} as never;
      if (path === '/api/source-messages/source-unlinked/promote' && method === 'POST') return {memory_id: promoted.id, created_new_memory: true} as never;
      if (path === '/api/memories/memory-promoted') return {...promoted, revision: 'c'.repeat(64), valid_from: null, valid_to: null, retired_at: null, superseded_by_id: null, sources: [{source_message_id: source.id, source_type: 'user_stated', linked_at: promoted.recorded_at, message: source}]} as never;
      if (path.startsWith('/api/memories?')) return {items: method === 'GET' && calls.some(call => call.path.endsWith('/promote') && call.method === 'POST') ? [promoted] : [], total: 0, limit: 25, offset: 0} as never;
      throw new Error(`unexpected test path: ${path}`);
    });

    const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
    render(<QueryClientProvider client={client}><MemoryRouter><MemoryApp/></MemoryRouter></QueryClientProvider>);
    await screen.findByText(/L1 原子记忆已加载/);
    fireEvent.click(screen.getByText(/L0 原始记录/));
    fireEvent.click(await screen.findByText(source.content));
    fireEvent.click(await screen.findByRole('button', {name: '补成 L1'}));
    fireEvent.change(screen.getByLabelText('补记后的完整 L1'), {target: {value: promoted.content}});
    fireEvent.click(screen.getByRole('button', {name: '确认补成 L1'}));

    await waitFor(() => expect(calls).toContainEqual({
      path: '/api/source-messages/source-unlinked/promote',
      method: 'POST',
      body: {content: promoted.content, revision: 'b'.repeat(64), confirm_promote: true},
    }));
    expect(await screen.findByText('已从原 L0 补成 L1，并保留原话来源。')).toBeTruthy();
    expect(await screen.findByText(/当天所有者确认漏记 1 条/)).toBeTruthy();
    expect((await screen.findAllByText(promoted.content)).length).toBeGreaterThanOrEqual(1);
  });
});
