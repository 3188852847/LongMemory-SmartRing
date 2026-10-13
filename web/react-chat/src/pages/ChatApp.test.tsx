import {afterEach, describe, expect, test, vi} from 'vitest';
import {fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {ChatApi, type Snapshot, type Turn} from '../api';
import {ChatApp} from './ChatApp';

const turn = (index: number): Turn => ({request_id:`synthetic-${index}`, input:`合成输入 ${index}`,
  answer:`合成回答 ${index}`, status:'completed', writes:[], user_saved:true, duration_ms:1,
  retrieved:[{item_id:`memory-${index}`, content:`合成证据 ${index}`, source_event_ids:['synthetic-source']}]});

function mount(snapshot: Snapshot, override?: (path: string, method: string, body: unknown) => unknown) {
  localStorage.clear();
  vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
  const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path, method = 'GET', body) => {
    const result = override?.(path, method, body);
    if (result !== undefined) return result;
    if (path === '/api/chat-config') return {enabled:true, database:'synthetic.db', provider:'fake', model:'Fake', role:'测试'};
    if (path === '/api/chats') return {chats:[{chat_id:snapshot.chat_id, title:snapshot.title, turn_count:snapshot.turns.length}]};
    if (path === `/api/chats/${snapshot.chat_id}`) return snapshot;
    if (path === '/api/device') return {ready:false, connection_count:0};
    if (path.startsWith('/api/memories?')) return {total:2,items:[]};
    throw new Error(`unexpected synthetic request: ${method} ${path}`);
  });
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}>
    <MemoryRouter><ChatApp/></MemoryRouter></QueryClientProvider>);
  return request;
}

afterEach(() => vi.restoreAllMocks());

describe('聊天工作区', () => {
  test('任意轮次证据可核对，辅助面板切换不清空草稿，收起返回键盘入口', async () => {
    mount({chat_id:'chat-synthetic', title:'合成会话', pending:false, turns:[turn(1),turn(2)]});
    await screen.findByText('合成回答 2');
    const input = screen.getByRole('textbox', {name:'消息'});
    fireEvent.change(input, {target:{value:'未发送的合成草稿'}});
    fireEvent.click(screen.getByRole('button', {name:'查看第 1 轮记忆证据'}));
    const evidence = screen.getByRole('region', {name:'本轮记忆证据'});
    expect(within(evidence).getByText('合成证据 1')).toBeTruthy();
    expect(within(evidence).getByRole('link', {name:'核对 L0 原话'}).getAttribute('href')).toBe('/memories?memory_id=memory-1');
    fireEvent.click(screen.getByRole('button', {name:'会话', exact:true}));
    expect(screen.getByRole('textbox', {name:'查找会话'})).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name:'收起面板'}));
    expect(document.activeElement).toBe(screen.getByRole('button', {name:'会话', exact:true}));
    expect((input as HTMLTextAreaElement).value).toBe('未发送的合成草稿');
    expect(screen.queryByRole('region', {name:'本轮记忆证据'})).toBeNull();
    fireEvent.click(screen.getByRole('button', {name:'记忆证据', exact:true}));
    expect(screen.getByText('合成证据 2')).toBeTruthy();
    fireEvent.keyDown(screen.getByRole('complementary', {name:'记忆证据面板'}), {key:'Escape'});
    expect(document.activeElement).toBe(screen.getByRole('button', {name:'记忆证据', exact:true}));
  });

  test('发送与记忆反馈仍经过原请求，反馈不重答', async () => {
    const request = mount({chat_id:'chat-synthetic', title:'合成会话', pending:false, turns:[]}, (path, method) => {
      if (path.endsWith('/messages') && method === 'POST') return turn(1);
      if (path.endsWith('/memory-feedback') && method === 'POST') return {feedback:{kind:'recall_miss', revision:1}};
    });
    await screen.findByText('会话已恢复，可以继续聊。');
    fireEvent.change(screen.getByRole('textbox', {name:'消息'}), {target:{value:'合成输入 1'}});
    fireEvent.click(screen.getByRole('button', {name:'发送', exact:true}));
    await screen.findByText('合成回答 1');
    expect((screen.getByRole('textbox', {name:'消息'}) as HTMLTextAreaElement).value).toBe('');
    fireEvent.click(screen.getByRole('button', {name:'没想起已有记忆'}));
    await screen.findByText('本轮记忆表现已记录；没有重答，也没有修改 L0–L3。');
    expect(request.mock.calls.filter(([path]) => path.endsWith('/messages'))).toHaveLength(1);
    expect(request.mock.calls.find(([path]) => path.endsWith('/memory-feedback'))?.[2]).toEqual({kind:'recall_miss',expected_revision:0});
  });

  test('40 轮限制明确显示，仍可以进入会话和新聊天', async () => {
    mount({chat_id:'chat-synthetic', title:'合成会话', pending:false, turns:Array.from({length:40}, (_,i) => turn(i))});
    await screen.findByText('合成回答 39');
    expect((screen.getByRole('textbox', {name:'消息'}) as HTMLTextAreaElement).disabled).toBe(true);
    expect((screen.getByRole('button', {name:'发送', exact:true}) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', {name:'新聊天'}) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByRole('status').textContent).toContain('已达 40 轮');
  });

  test('结果未知时保留只查询入口，不重复写入', async () => {
    const request = mount({chat_id:'chat-synthetic', title:'合成会话', pending:true, turns:[]});
    const query = await screen.findByRole('button', {name:'只查询结果，不重发'});
    await waitFor(() => expect((query as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(query);
    await screen.findByText('后台仍在处理，没有重发。');
    expect(request.mock.calls.every(([,method]) => method === undefined || method === 'GET')).toBe(true);
  });
});
