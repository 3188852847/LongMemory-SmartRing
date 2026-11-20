import {afterEach, describe, expect, test, vi} from 'vitest';
import {fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {ApiError, ChatApi, type Snapshot, type Turn} from '../api';
import {ChatApp} from './ChatApp';
import {MemoryEngineProvider} from '../app/MemoryEngineProvider';
import {KnownMemoryEngine, hyIdentity, legacyIdentity} from '../tests/memoryEngine';

const turn = (index: number): Turn => ({request_id:`synthetic-${index}`, input:`合成输入 ${index}`,
  answer:`合成回答 ${index}`, status:'completed', writes:[], user_saved:true, duration_ms:1,
  retrieved:[{item_id:`memory-${index}`, content:`合成证据 ${index}`, source_event_ids:['synthetic-source']}]});

function mount(snapshot: Snapshot, override?: (path: string, method: string, body: unknown) => unknown,
  Engine: typeof MemoryEngineProvider = KnownMemoryEngine) {
  localStorage.clear();
  vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
  const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path, method = 'GET', body) => {
    const result = override?.(path, method, body);
    if (result !== undefined) {
      if (method === 'POST' && path.endsWith('/messages')) {
        const saved = await result as Turn;
        if (!snapshot.turns.some(item => item.request_id === saved.request_id)) snapshot.turns = [...snapshot.turns, saved];
      }
      return result;
    }
    if (path === '/api/chat-config') return {enabled:true, database:'synthetic.db', provider:'fake', model:'Fake', role:'测试'};
    if (path === '/api/chats') return {chats:[{chat_id:snapshot.chat_id, title:snapshot.title, turn_count:snapshot.turns.length}]};
    if (path === `/api/chats/${snapshot.chat_id}`) return snapshot;
    if (path.startsWith('/api/companion/dialogue')) return {enabled:true, messages:[]};
    if (path === '/api/device') return {ready:false, connection_count:0};
    throw new Error(`unexpected synthetic request: ${method} ${path}`);
  });
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}>
    <MemoryRouter><Engine><ChatApp/></Engine></MemoryRouter></QueryClientProvider>);
  return request;
}

afterEach(() => vi.restoreAllMocks());

describe('聊天工作区', () => {
  test.each([
    {order:'冷身份先于配置', configFirst:false, ready:false},
    {order:'配置先于冷身份', configFirst:true, ready:false},
    {order:'身份已就绪', configFirst:false, ready:true},
  ])('聊天配置与引擎身份协调：$order', async ({configFirst, ready}) => {
    let release!: () => void;
    const delayedResponse = new Promise<void>(resolve => {release = resolve;});
    const coldIdentity = {...legacyIdentity,method:null,state:'not_initialized'};
    const identity = vi.fn().mockResolvedValue(hyIdentity);
    if (!ready) identity.mockReturnValueOnce(configFirst ? delayedResponse.then(() => coldIdentity) : coldIdentity);
    const config = {enabled:true, database:'synthetic.db', provider:'fake', model:'Fake', role:'测试', method:hyIdentity.method};
    mount({chat_id:'synthetic-cold', title:'合成会话', pending:false, turns:[turn(1)]}, path => {
      if (path === '/api/memory-engine/identity') return identity();
      if (path === '/api/chat-config') return configFirst ? config : delayedResponse.then(() => config);
    }, MemoryEngineProvider);

    if (configFirst) await screen.findByText('合成回答 1');
    else if (ready) await waitFor(() => expect(identity).toHaveBeenCalledTimes(1));
    else await waitFor(() => expect(identity).toHaveBeenCalledTimes(1));
    expect(identity).toHaveBeenCalledTimes(1);
    release();
    await screen.findByText('合成回答 1');
    fireEvent.click(screen.getByRole('button', {name:'查看第 1 轮记忆证据'}));
    const link = await screen.findByRole('link', {name:'核对条目与平台来源'});
    expect(link.getAttribute('href')).toBe('/memories?item=memory-1');
    expect(identity).toHaveBeenCalledTimes(ready ? 1 : 2);
  });

  test('重新核对仍未初始化时保留中立入口，后续操作不循环查询', async () => {
    const identity = vi.fn().mockResolvedValue({...legacyIdentity, method:null, state:'not_initialized'});
    mount({chat_id:'synthetic-cold', title:'合成会话', pending:false, turns:[turn(1)]}, path => {
      if (path === '/api/memory-engine/identity') return identity();
      if (path === '/api/chat-config') return {enabled:true, database:'synthetic.db', method:hyIdentity.method};
    }, MemoryEngineProvider);
    await waitFor(() => expect(identity).toHaveBeenCalledTimes(2));
    fireEvent.click(await screen.findByRole('button', {name:'查看第 1 轮记忆证据'}));
    const link = await screen.findByRole('link', {name:'核对条目与平台来源'});
    expect(link.getAttribute('href')).toBe('/memories?item=memory-1');
    expect(identity).toHaveBeenCalledTimes(2);
  });

  test('共享历史按实际时间穿插三端消息，网页证据仍绑定原轮次', async () => {
    const local = {...turn(1), event_id:'local-u', assistant_event_id:'local-a'};
    const rows = [
      {id:'local-u', role:'user', text:local.input, at:'2026-11-20T10:00:00Z', channel:'web'},
      {id:'qq-reply', role:'assistant', text:'合成 QQ 主动问候', at:'2026-11-20T10:01:00Z', channel:'qq', proactive:true},
      {id:'local-a', role:'assistant', text:local.answer, at:'2026-11-20T10:02:00Z', channel:'web'},
      {id:'screen-u', role:'user', text:'合成圆屏原话', at:'2026-11-20T10:03:00Z', channel:'screen'},
    ];
    mount({chat_id:'shared', title:'合成会话', pending:false, turns:[local]}, path =>
      path === '/api/companion/dialogue?active=1' ? {enabled:true, messages:rows} : undefined);
    await screen.findByText('合成圆屏原话');
    const messages = screen.getByRole('region', {name:'聊天记录'});
    expect(Array.from(messages.querySelectorAll('.bubble p'), p => p.textContent)).toEqual(rows.map(row => row.text));
    expect(within(messages).getByText(/QQ · 主动联系/)).toBeTruthy();
    expect(within(messages).getByRole('button',{name:'查看第 1 轮记忆证据'})).toBeTruthy();
  });

  test('向前翻页保留阅读锚点，刷新消息后保留读过的页和滚出首页的消息', async () => {
    const row = (n: number) => ({id:`r${n}`, role:'assistant', text:`共享行 ${n}`,
      channel:'qq', proactive:false, at:new Date(Date.UTC(2026,10,21,10,0,n)).toISOString()});
    let first = 1;
    const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
    const request = mount({chat_id:'pages', title:'合成会话', pending:false, turns:[]}, path => {
      if (path.endsWith('?active=1')) return {enabled:true, messages:Array.from({length:60}, (_, i) => row(first + i))};
      if (path.endsWith('?before=r1&limit=60')) return {enabled:true, messages:[row(-1), row(0)]};
    });
    await screen.findByText('共享行 60');
    const viewport = screen.getByRole('region', {name:'聊天记录'});
    const top = screen.getByText('共享行 1').closest('article')!;
    const original = top.getBoundingClientRect();
    vi.spyOn(top, 'getBoundingClientRect').mockImplementation(() =>
      ({...original, top: screen.queryByText('共享行 -1') ? 120 : 0, bottom:180}) as DOMRect);
    fireEvent.click(screen.getByRole('button',{name:'更早的对话'}));
    await screen.findByText('共享行 -1');
    expect(viewport.scrollTop).toBe(120);
    expect(request.mock.calls.some(([p]) => p.includes('before=') && p.includes('active='))).toBe(false);
    expect(screen.queryByRole('button',{name:'更早的对话'})).toBeNull();
    first = 2;
    hidden.mockReturnValue(true); fireEvent(document, new Event('visibilitychange'));
    hidden.mockReturnValue(false); fireEvent(document, new Event('visibilitychange'));
    await screen.findByText('共享行 61');
    expect(screen.getAllByText('共享行 1')).toHaveLength(1);
    expect(screen.getAllByText('共享行 -1')).toHaveLength(1);
    expect(viewport.scrollTop).toBe(120);
  });

  test('切换会话时丢弃上一会话的慢速翻页结果', async () => {
    const rows = Array.from({length:60}, (_, i) => ({id:`r${i}`, role:'user', text:`合成 ${i}`, channel:'qq',
      at:new Date(Date.UTC(2026,10,21,10,0,i)).toISOString()}));
    let finish!: (page: unknown) => void;
    mount({chat_id:'first', title:'合成会话', pending:false, turns:[]}, (path, method) => {
      if (path.endsWith('?active=1')) return {enabled:true, messages:rows};
      if (path.includes('before=r0')) return new Promise(resolve => {finish = resolve;});
      if (path === '/api/chats' && method === 'POST') return {chat_id:'next'};
      if (path === '/api/chats/next') return {chat_id:'next', title:'另一个会话', pending:false, turns:[]};
    });
    fireEvent.click(await screen.findByRole('button',{name:'更早的对话'}));
    await waitFor(() => expect(finish).toBeTypeOf('function'));
    fireEvent.click(screen.getByRole('button',{name:'新聊天'}));
    await screen.findByText('另一个会话');
    finish({enabled:true,messages:[{...rows[0],id:'late',text:'上一次翻页'}]});
    await waitFor(() => expect(screen.getByRole('button',{name:'更早的对话'}).hasAttribute('disabled')).toBe(false));
    expect(screen.queryByText('上一次翻页')).toBeNull();
  });

  test('后台打开聊天页不会登记网页可接收消息，回到前台后开始同步', async () => {
    const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
    const request = mount({chat_id:'visibility', title:'合成会话', pending:false, turns:[]});
    await screen.findByText('会话已恢复，可以继续聊。');
    expect(request.mock.calls.some(([path]) => path.startsWith('/api/companion/dialogue'))).toBe(false);
    hidden.mockReturnValue(false);
    fireEvent(document, new Event('visibilitychange'));
    await waitFor(() => expect(request.mock.calls.some(([path]) => path === '/api/companion/dialogue?active=1')).toBe(true));
  });

  test('回看时新回答不拉底，明确返回最新后恢复跟随', async () => {
    mount({chat_id:'chat-synthetic',title:'合成会话',pending:false,turns:[turn(1)]}, (path, method) => {
      if (path.endsWith('/messages') && method === 'POST') return turn(2);
    });
    await screen.findByText('会话已恢复，可以继续聊。');
    const messages = screen.getByRole('region', {name:'聊天记录'});
    Object.defineProperties(messages, {scrollHeight:{value:1000,configurable:true},clientHeight:{value:200,configurable:true}});
    messages.scrollTop = 120; fireEvent.scroll(messages);
    fireEvent.change(screen.getByRole('textbox', {name:'消息'}), {target:{value:'新的合成问题'}});
    fireEvent.click(screen.getByRole('button', {name:'发送'}));
    await screen.findByText('合成回答 2');
    expect(messages.scrollTop).toBe(120);
    fireEvent.click(screen.getByRole('button',{name:'回到最新'}));
    expect(messages.scrollTop).toBe(1000);
  });
  test('任意轮次证据可核对，辅助面板切换不清空草稿，收起返回键盘入口', async () => {
    mount({chat_id:'chat-synthetic', title:'合成会话', pending:false, turns:[turn(1),turn(2)]});
    await screen.findByText('合成回答 2');
    const input = screen.getByRole('textbox', {name:'消息'});
    fireEvent.change(input, {target:{value:'未发送的合成草稿'}});
    fireEvent.click(screen.getByRole('button', {name:'查看第 1 轮记忆证据'}));
    const evidence = screen.getByRole('region', {name:'本轮记忆证据'});
    expect(within(evidence).getByText('合成证据 1')).toBeTruthy();
    expect(within(evidence).getByRole('link', {name:'核对条目与平台来源'}).getAttribute('href')).toBe('/memories?item=memory-1');
    fireEvent.click(screen.getByRole('button', {name:'会话'}));
    expect(screen.getByRole('textbox', {name:'查找会话'})).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name:'收起面板'}));
    expect(document.activeElement).toBe(screen.getByRole('button', {name:'会话'}));
    expect((input as HTMLTextAreaElement).value).toBe('未发送的合成草稿');
    expect(screen.queryByRole('region', {name:'本轮记忆证据'})).toBeNull();
    fireEvent.click(screen.getByRole('button', {name:'记忆证据'}));
    expect(screen.getByText('合成证据 2')).toBeTruthy();
    fireEvent.keyDown(screen.getByRole('complementary', {name:'记忆证据面板'}), {key:'Escape'});
    expect(document.activeElement).toBe(screen.getByRole('button', {name:'记忆证据'}));
  });

  test('发送与记忆反馈仍经过原请求，反馈不重答', async () => {
    const request = mount({chat_id:'chat-synthetic', title:'合成会话', pending:false, turns:[]}, (path, method) => {
      if (path.endsWith('/messages') && method === 'POST') return turn(1);
      if (path.endsWith('/memory-feedback') && method === 'POST') return {feedback:{kind:'recall_miss', revision:1}};
    });
    await screen.findByText('会话已恢复，可以继续聊。');
    fireEvent.change(screen.getByRole('textbox', {name:'消息'}), {target:{value:'合成输入 1'}});
    fireEvent.click(screen.getByRole('button', {name:'发送'}));
    await screen.findByText('合成回答 1');
    expect((screen.getByRole('textbox', {name:'消息'}) as HTMLTextAreaElement).value).toBe('');
    expect(screen.queryByRole('button', {name:'没想起已有记忆'})).toBeNull();
    fireEvent.click(screen.getByText('朗读与反馈', {selector:'summary'}));
    fireEvent.click(await screen.findByRole('button', {name:'没想起已有记忆'}));
    await screen.findByText('本轮记忆表现已记录；没有重答，也没有修改原话、事实、场景或画像。');
    expect(request.mock.calls.filter(([path]) => path.endsWith('/messages'))).toHaveLength(1);
    expect(request.mock.calls.find(([path]) => path.endsWith('/memory-feedback'))?.[2]).toEqual({kind:'recall_miss',expected_revision:0});
  });


  test.each([false, true])('模型恢复后从服务读取最近状态，应用命令保留原状态（查询找回=%s）', async lookup => {
    const snapshot:Snapshot = {chat_id:'chat-model',title:'模型状态',pending:false,turns:[]};
    const previous = {state:'unavailable',code:'model_unreachable',checked_at:'2026-11-20T08:00:00+00:00'};
    const available = {state:'available',code:null,checked_at:'2026-11-21T08:00:00+00:00'};
    let modelAnswered = false;
    const request = mount(snapshot, (path, method, body) => {
      if (path === '/api/chat-config') return {enabled:true,provider:'openai_compatible',database:'test.db',
        model:'测试',role:'测试',model_health:modelAnswered ? available : previous};
      if (method === 'POST' && path.endsWith('/messages')) {
        const {text,request_id} = body as {text:string; request_id:string};
        modelAnswered = text === '交给模型回答';
        const result:Turn = {...turn(modelAnswered ? 2 : 1),input:text,request_id,
          answer_source:modelAnswered ? 'model' : 'application_command'};
        snapshot.turns = [...snapshot.turns, result];
        if (modelAnswered && lookup) throw new ApiError('chat_archive_unavailable',503);
        return result;
      }
    });
    await screen.findByText(/会话已恢复，可以继续聊/);
    fireEvent.click(screen.getByRole('button', {name:'运行状态'}));
    await screen.findByText('模型服务最近验证失败');
    const input = screen.getByRole('textbox', {name:'消息'});
    const send = screen.getByRole('button', {name:'发送'});
    fireEvent.change(input, {target:{value:'应用内命令'}});
    fireEvent.click(send);
    await screen.findByText('合成回答 1');
    expect(screen.getByText('模型服务最近验证失败')).toBeTruthy();
    expect(request.mock.calls.filter(([path]) => path === '/api/chat-config')).toHaveLength(1);
    fireEvent.change(input, {target:{value:'交给模型回答'}});
    fireEvent.click(send);
    if (lookup) fireEvent.click(await screen.findByRole('button', {name:'只查询结果，不重发'}));
    await screen.findByText('模型服务最近验证可用');
    expect(request.mock.calls.filter(([path]) => path.endsWith('/messages'))).toHaveLength(2);
    expect(request.mock.calls.some(([path]) => path === '/api/chat-model/check')).toBe(false);
  });

  test('40 轮限制明确显示，仍可以进入会话和新聊天', async () => {
    mount({chat_id:'chat-synthetic', title:'合成会话', pending:false, turns:Array.from({length:40}, (_,i) => turn(i))});
    await screen.findByText('合成回答 39');
    expect((screen.getByRole('textbox', {name:'消息'}) as HTMLTextAreaElement).disabled).toBe(true);
    expect((screen.getByRole('button', {name:'发送'}) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', {name:'新聊天'}) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByRole('status', {name:'聊天操作状态'}).textContent).toContain('已达 40 轮');
  });

  test('结果未知时保留只查询入口，不重复写入', async () => {
    const request = mount({chat_id:'chat-synthetic', title:'合成会话', pending:true, turns:[]});
    const query = await screen.findByRole('button', {name:'只查询结果，不重发'});
    await waitFor(() => expect((query as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(query);
    await screen.findByText('后台仍在处理，没有重发。');
    expect(request.mock.calls.every(([,method]) => method === undefined || method === 'GET')).toBe(true);
  });

  test.each([false, true])('其他标签的同文消息保留本页草稿，显式发送时按内容复用请求号（编辑=%s）', async edited => {
    const snapshot: Snapshot = {chat_id:'chat-synthetic', title:'合成会话', pending:false, turns:[]};
    const posts: Array<{text:string; request_id:string}> = [];
    const draft = '同一条合成消息';
    mount(snapshot, (path, method, body) => {
      if (method !== 'POST' || !path.endsWith('/messages')) return;
      const post = body as typeof posts[number];
      posts.push(post);
      if (posts.length === 1) throw new ApiError('chat_busy', 409);
      return {...turn(2), input:post.text, request_id:post.request_id};
    });
    await screen.findByText('会话已恢复，可以继续聊。');
    const input = screen.getByRole<HTMLTextAreaElement>('textbox', {name:'消息'});
    const send = screen.getByRole('button', {name:'发送'});
    fireEvent.change(input, {target:{value:draft}});
    fireEvent.click(send);
    const query = await screen.findByRole('button', {name:'只查询结果，不重发'});
    snapshot.turns = [{...turn(1), input:draft}];
    fireEvent.click(query);
    await screen.findByText('合成回答 1');
    expect(input.value).toBe(draft);
    expect(posts).toHaveLength(1);
    if (edited) fireEvent.change(input, {target:{value:'编辑后的合成消息'}});
    fireEvent.click(send);
    await screen.findByText('合成回答 2');
    expect(posts).toHaveLength(2);
    expect(posts[0].request_id).toBeTruthy();
    expect(posts[1].request_id === posts[0].request_id).toBe(!edited);
    expect(input.value).toBe('');
  });

  test('断线后即使其他请求仍在处理也能认出自己的轮次，连续查询只读', async () => {
    const snapshot: Snapshot = {chat_id:'chat-synthetic', title:'合成会话', pending:false, turns:[]};
    let requestId: string | undefined;
    const request = mount(snapshot, (path, method, body) => {
      if (method === 'POST' && path.endsWith('/messages')) {
        requestId = (body as {request_id:string}).request_id;
        throw new TypeError('synthetic disconnect');
      }
    });
    await screen.findByText('会话已恢复，可以继续聊。');
    fireEvent.click(screen.getByRole('button', {name:'运行状态'}));
    const input = screen.getByRole<HTMLTextAreaElement>('textbox', {name:'消息'});
    fireEvent.change(input, {target:{value:'合成输入 1'}});
    fireEvent.click(screen.getByRole('button', {name:'发送'}));
    const query = await screen.findByRole('button', {name:'只查询结果，不重发'});
    snapshot.pending = true;
    fireEvent.click(query);
    await screen.findByText('后台仍在处理，没有重发。');
    expect(input.value).toBe('合成输入 1');
    snapshot.turns = [{...turn(1), request_id:requestId, writes:[{operation:'add'}]}];
    fireEvent.click(query);
    await screen.findByText('合成回答 1');
    expect(input.value).toBe('');
    expect(input.disabled).toBe(true);
    snapshot.pending = false;
    fireEvent.click(query);
    await waitFor(() => expect(input.disabled).toBe(false));
    expect(request.mock.calls.filter(([,method]) => method === 'POST')).toHaveLength(1);
  });
});
