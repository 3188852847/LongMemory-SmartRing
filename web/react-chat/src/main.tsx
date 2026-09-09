import {lazy, Suspense, useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Alert, Button, Input, Modal, Select} from 'antd';
import {QueryClientProvider, useQuery} from '@tanstack/react-query';
import {BrowserRouter, Navigate, Route, Routes} from 'react-router-dom';
import {ApiError, ChatApi, type Config, type DeviceStatus, type MemoryPageSummary, type Snapshot, type Summary, type Turn} from './api';
import {turnSummary} from '../../assets/chat-view.mjs';
import './style.css';
import {AppearanceProvider} from './AppearanceProvider';
import {AppShell, ConsoleNav} from './AppShell';
import {PageHeader} from './PageHeader';
import {SpeechPlayer} from './SpeechPlayer';
import {createConsoleQueryClient} from './queryClient';
import {modelFailure} from './modelHealth';
import {MemoryCommandHelp} from './MemoryCommandHelp';
import {loadSendShortcut, saveSendShortcut, shouldSendFromKeyboard, type SendShortcut} from './chatInput';
import {organizeChats, readPinnedChats, togglePinnedChat, writePinnedChats} from './chatSessions';
import {ConsoleStatusRail, TurnMemoryEvidence} from './ChatObservability';
import {chatFailure} from './chatFailure';

const DeviceApp = lazy(() => import('./DeviceApp').then(module => ({default: module.DeviceApp})));
const MemoryApp = lazy(() => import('./MemoryApp').then(module => ({default: module.MemoryApp})));
const ScenarioApp = lazy(() => import('./ScenarioApp').then(module => ({default: module.ScenarioApp})));
const PersonaApp = lazy(() => import('./PersonaApp').then(module => ({default: module.PersonaApp})));
const SettingsApp = lazy(() => import('./SettingsApp').then(module => ({default: module.SettingsApp})));
const ExperimentApp = lazy(() => import('./ExperimentApp').then(module => ({default: module.ExperimentApp})));
const RoundDisplayApp = lazy(() => import('./RoundDisplayApp').then(module => ({default: module.RoundDisplayApp})));

const api = new ChatApi();
const queryClient = createConsoleQueryClient();
function memoryWarning(turn: Turn) {
  return turn.memory_warning === 'l1_persistence_failed'
    ? '本轮 L0 原始对话已保存，但 L1 记忆写入失败。'
    : '本轮 L0 原始对话已保存，但 L1 记忆提取失败。';
}
function memoryCommandAlert(status: string) {
  if (status === 'applied' || status === 'explained' || status === 'cancelled') return 'success' as const;
  if (status === 'confirmation_required' || status === 'content_required' || status === 'write_paused' || status === 'content_invalid') return 'warning' as const;
  return 'info' as const;
}
function ChatApp() {
  const [config, setConfig] = useState<Config>();
  const [chats, setChats] = useState<Summary[]>([]);
  const [chat, setChat] = useState<Snapshot>();
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(true);
  const [unknown, setUnknown] = useState(false);
  const [notice, setNotice] = useState('正在连接本机服务…');
  const [rename, setRename] = useState(false);
  const [checkingModel, setCheckingModel] = useState(false);
  const [sendShortcut, setSendShortcut] = useState<SendShortcut>(() => loadSendShortcut());
  const [chatSearch, setChatSearch] = useState('');
  const [pinnedChats, setPinnedChats] = useState<string[]>([]);
  const [title, setTitle] = useState('');
  // ref 在同一事件循环内立即锁定，避免 React 尚未重绘时的双击重复写入。
  const locked = useRef(false);
  const selectionKey = useRef('');
  const pinnedKey = useRef('');
  const turnsEnd = useRef<HTMLDivElement>(null);
  const deviceStatus = useQuery({queryKey:['device-status'], enabled:Boolean(config?.enabled), retry:false,
    queryFn:() => api.request<DeviceStatus>('/api/device'), refetchInterval:5000});
  const memoryCount = useQuery({queryKey:['chat-active-memory-count'], enabled:Boolean(config?.enabled), retry:false,
    queryFn:() => api.request<MemoryPageSummary>('/api/memories?q=&state=active&offset=0&limit=1'), staleTime:30000});
  useEffect(() => {turnsEnd.current?.scrollIntoView({block: 'nearest'});}, [chat?.turns.length]);
  async function list() {
    const data = await api.request<{chats: Summary[]}>('/api/chats'); setChats(data.chats); return data.chats;
  }
  async function load(id: string) {
    const data = await api.request<Snapshot>(`/api/chats/${id}`); setChat({...data, chat_id: id}); setUnknown(data.pending);
    try {localStorage.setItem(selectionKey.current, id);} catch { /* 仅保存会话 ID，禁用存储时降级。 */ }
    return data;
  }
  async function create() {
    const data = await api.request<Snapshot>('/api/chats', 'POST'); await load(data.chat_id); await list();
  }
  useEffect(() => {
    // 不使用 StrictMode 双挂载；初始化只创建一次空会话，不调用回答模型。
    void (async () => {
      try {
        await api.bootstrap(); const info = await api.request<Config>('/api/chat-config'); setConfig(info);
        if (!info.enabled) {setNotice('文字聊天尚未启用，请通过启动面板启动文字服务。'); return;}
        selectionKey.current = `longmemory:last-chat:${info.database}`;
        pinnedKey.current = `longmemory:pinned-chats:${info.database}`;
        try {setPinnedChats(readPinnedChats(localStorage, pinnedKey.current));} catch { /* 会话列表仍可正常使用。 */ }
        const rows = await list(); let previous: string | null = null;
        try {previous = localStorage.getItem(selectionKey.current);} catch { /* 默认最近会话。 */ }
        if (rows.length) {const loaded = await load(rows.find(c => c.chat_id === previous)?.chat_id ?? rows[0].chat_id); setNotice(loaded.pending ? '消息仍在处理，请只查询结果。' : '会话已恢复，可以继续聊。');}
        else {await create(); setNotice('新聊天已就绪。');}
      } catch (error) {setNotice(chatFailure(error, 'read'));} finally {setBusy(false);}
    })();
  }, []);
  async function action(work: () => Promise<void>) {
    if (locked.current) return; locked.current = true; setBusy(true);
    try {await work();} catch (error) {setNotice(chatFailure(error, 'operation'));} finally {locked.current = false; setBusy(false);}
  }
  function changeChat(id?: string) {
    if (busy || unknown || (draft && !confirm('这会清空尚未发送的草稿，继续吗？'))) return;
    void action(async () => {if (id) await load(id); else await create(); setDraft(''); setNotice('会话已切换；长期记忆保留。');});
  }
  async function send() {
    if (!chat || busy || unknown || !draft.trim() || chat.turns.length >= 40) return;
    await action(async () => {
      setNotice('正在处理，请勿重复发送…');
      try {
        const turn = await api.request<Turn>(`/api/chats/${chat.chat_id}/messages`, 'POST', {text: draft, request_id: crypto.randomUUID()});
        setChat({...chat, turns: [...chat.turns, turn]}); setDraft('');
        setChats(rows => rows.map(row => row.chat_id === chat.chat_id ? {...row, turn_count: chat.turns.length + 1} : row));
        if (turn.writes?.some(item => item.operation !== 'noop')) {
          // 只在服务明确报告实际变更后刷新数量；NOOP 只是增加来源，不增加有效 L1。
          void queryClient.invalidateQueries({queryKey:['chat-active-memory-count']});
        }
        const modelProblem=modelFailure(turn.error);
        if(modelProblem)setConfig(current=>current?{...current,model_health:{state:'unavailable',code:String(turn.error),checked_at:new Date().toISOString()}}:current);
        setNotice(modelProblem
          ? `${modelProblem} 本轮用户输入可能已经保存，但没有伪造助手回答。`
          : turn.memory_processing === 'source_only'
          ? `回答已完成，但${memoryWarning(turn).replace('本轮 ', '')}不要把它误认为“不该记”。`
          : turn.retrieval_warning === 'dense_retrieval_failed'
            ? '回答已完成，但本地 BGE 检索失败，本轮已明确降级为关键词检索。'
          : turn.status === 'completed' ? '本轮完成，可展开查看记忆证据。' : '本轮未完成；输入可能已保存，请查看过程。');
      } catch (error) {setUnknown(true); setNotice(chatFailure(error, 'write'));}
    });
  }
  async function checkModel(){if(checkingModel||config?.provider!=='openai_compatible')return;setCheckingModel(true);
    try{const health=await api.request<NonNullable<Config['model_health']>>('/api/chat-model/check','POST',{});setConfig(current=>current?{...current,model_health:health}:current);
      setNotice(health.state==='available'?'模型连接验证通过；这不代表回答质量或圆屏链路已经验收。':modelFailure(health.code)??'模型连接验证失败。');
    }catch(error){
      const problem = error instanceof ApiError ? modelFailure(error.code) : undefined;
      setNotice(problem ?? chatFailure(error, 'read'));
    }finally{setCheckingModel(false);}}
  const disabled = busy || unknown || !chat;
  const visibleChats = organizeChats(chats, pinnedChats, chatSearch);
  function toggleCurrentPin() {
    if (!chat || !pinnedKey.current) return;
    const next = togglePinnedChat(pinnedChats, chat.chat_id);
    setPinnedChats(next);
    let saved = false;
    try {saved = writePinnedChats(localStorage, pinnedKey.current, next);} catch { /* 只降级当前页面状态。 */ }
    setNotice(saved ? (next.includes(chat.chat_id) ? '当前会话已置顶。' : '当前会话已取消置顶。') : '置顶已在本页生效，但浏览器未能保存。');
  }
  const sidebar = <>
      <ConsoleNav active="chat" legacyPath="/chat"/>
      <section className="chat-sidebar-panel" aria-labelledby="chat-session-heading">
        <div className="chat-sidebar-heading"><h2 id="chat-session-heading">会话</h2><Button size="small" disabled={disabled} onClick={() => changeChat()}>新建</Button></div>
        <label htmlFor="chat-search">查找会话</label><Input id="chat-search" allowClear aria-label="查找会话" value={chatSearch} onChange={event => setChatSearch(event.target.value)} placeholder="按名称搜索"/>
        <label htmlFor="conversation">当前会话</label><Select id="conversation" className="wide" aria-label="最近会话" value={chat?.chat_id} disabled={busy || unknown}
          notFoundContent="没有匹配的会话" options={visibleChats.map(c => ({value: c.chat_id, label: `${pinnedChats.includes(c.chat_id) ? '★ ' : ''}${c.title} · ${c.turn_count} 轮`}))} onChange={changeChat}/>
        <div className="chat-session-actions"><Button size="small" disabled={disabled} onClick={() => {setTitle(chat?.title ?? ''); setRename(true);}}>重命名</Button>
          <Button size="small" disabled={disabled} onClick={toggleCurrentPin}>{chat && pinnedChats.includes(chat.chat_id) ? '取消置顶' : '置顶'}</Button></div>
      </section>
    </>;
  const latestTurn = chat?.turns.at(-1);
  return <><AppShell subtitle="你的日常聊天空间" className="chat-shell" sidebar={sidebar}><ConsoleStatusRail config={config} device={deviceStatus.data} deviceFailed={deviceStatus.isError} activeMemoryCount={memoryCount.data?.total}/><PageHeader eyebrow="日常使用" title="聊聊今天" description="在这里用文字继续日常对话；新事实是否进入长期记忆，可以在本轮证据中核对。" action={<div className="page-header-actions"><span>{chat?.turns.length ?? 0} / 40 轮</span><MemoryCommandHelp/></div>}/>
      {config?.provider==='openai_compatible'&&<Alert showIcon type={config.model_health?.state==='available'?'success':config.model_health?.state==='unavailable'?'error':'info'}
        title={config.model_health?.state==='available'?'模型服务最近验证可用':config.model_health?.state==='unavailable'?'模型服务最近验证失败':'模型服务尚未验证'}
        description={config.model_health?.state==='unavailable'?(modelFailure(config.model_health.code)??'模型调用失败。'):'检测只发送固定合成短句，不读取或写入个人记忆，也不自动重试。'}
        action={<Button loading={checkingModel} disabled={busy||unknown}
          onClick={()=>void checkModel()}>检测模型连接</Button>}/>}<div className="chat-workspace"><section className="messages" aria-label="聊天记录">{!chat?.turns.length && <div className="empty"><h2>今天想聊些什么？</h2><p>可以说说今天的事，也可以继续上次的话题。</p></div>}
        {chat?.turns.map((turn, i) => <article key={i}><div className="bubble user"><strong>你</strong><p>{turn.input}</p></div><div className="bubble assistant"><strong>助手</strong><p>{turn.answer ?? '未获得完整回答。'}</p>{turn.answer&&<SpeechPlayer api={api} text={turn.answer}/>}</div>
          {turn.memory_command && <Alert className="memory-command-result" showIcon type={memoryCommandAlert(turn.memory_command.status)} title="实际记忆操作结果" description={turn.memory_command.notice}/>}
          {turn.memory_processing === 'source_only' && <p className="memory-warning">{memoryWarning(turn)} 可继续聊天，之后需要重新整理这条来源。</p>}
          {turn.retrieval_warning === 'dense_retrieval_failed' && <p className="memory-warning">本轮本地 BGE 检索失败，已使用关键词结果继续回答；展开过程可查看实际策略。</p>}
          {Boolean(turn.scenario_retrieved?.length) && <p className="scenario-trace">本轮使用 L2：{turn.scenario_retrieved!.map(item => item.title).join('、')}</p>}
          {Boolean(turn.persona_retrieved?.length) && <p className="scenario-trace">本轮使用 L3：{turn.persona_retrieved!.map(item => item.label).join('、')}</p>}
          <details className="turn-summary"><summary>{turnSummary(turn)}</summary><p>右侧“本轮记忆证据”展示最近一轮；完整过程仍可在那里展开。</p></details></article>)}<div ref={turnsEnd}/></section><aside className="chat-evidence-column"><h2>本轮记忆证据</h2><TurnMemoryEvidence turn={latestTurn}/></aside></div>
      <form className="chat-composer" onSubmit={event => {event.preventDefault(); void send();}}><Input.TextArea aria-label="消息" value={draft} maxLength={1000} rows={3} disabled={disabled || (chat?.turns.length ?? 0) >= 40} onChange={event => setDraft(event.target.value)}
        onKeyDown={event => {if (shouldSendFromKeyboard({...event, isComposing: event.nativeEvent.isComposing}, sendShortcut)) {event.preventDefault(); void send();}}}
        placeholder="写下想说的话…"/>
        <div className="send-row"><div><small>发送会先保存原始输入，再按当前提取策略生成长期记忆。</small><Select size="small" aria-label="发送快捷键" value={sendShortcut}
          options={[{value:'enter',label:'Enter 发送 · Shift+Enter 换行'},{value:'ctrl_enter',label:'Ctrl+Enter 发送 · Enter 换行'}]}
          onChange={value => {setSendShortcut(value); saveSendShortcut(value);}}/></div><Button type="primary" htmlType="submit" disabled={disabled || !draft.trim() || (chat?.turns.length ?? 0) >= 40}>发送</Button></div></form>
      <p className="chat-status" role="status"><i aria-hidden="true"/>{notice}</p>{unknown && <Button disabled={busy} onClick={() => void action(async () => {if (!chat) return; const result = await load(chat.chat_id); if (!result.pending && result.turns.length > chat.turns.length) setDraft(''); setNotice(result.pending ? '后台仍在处理，没有重发。' : '已查询。服务中断时不能据此保证未写入，请检查过程。');})}>只查询结果，不重发</Button>}
      <details className="runtime"><summary>运行配置与记忆说明</summary><p>{config?.enabled ? `${config.model} · ${config.role} · ${config.provider}` : '聊天未启用'}</p>{config?.provider === 'fake' && <p>Fake 是离线工程替身，不具备角色和多轮理解能力。</p>}<p>提取：{config?.method === 'longmemory_daily_llm_v2' ? '模型辅助 P3.2（失败保留 L0）' : '规则基线'}；检索：{config?.retrieval === 'keyword_dense_rrf_v1' ? '关键词＋本地 BGE 融合 P3.2' : '关键词基线'}。网页不自动驱动圆屏播放。</p>{config?.enabled && <p>记忆库：{config.database}</p>}</details>
    </AppShell>
    <Modal title="重命名聊天" open={rename} onCancel={() => setRename(false)} confirmLoading={busy} okText="保存" cancelText="取消" okButtonProps={{disabled: !title.trim() || busy}}
      onOk={() => void action(async () => {await api.request(`/api/chats/${chat?.chat_id}/title`, 'POST', {title}); await list(); if (chat) setChat({...chat,title}); setRename(false);})}><Input aria-label="聊天名称" maxLength={60} value={title} onChange={event => setTitle(event.target.value)}/></Modal>
  </>;
}

function ConsoleApp() {
  return <QueryClientProvider client={queryClient}><AppearanceProvider><BrowserRouter><Routes>
    <Route path="/device" element={<Suspense fallback={<p className="page-loading">正在加载设备控制…</p>}><DeviceApp/></Suspense>}/>
    <Route path="/display-preview" element={<Suspense fallback={<p className="page-loading">正在加载圆屏预览…</p>}><RoundDisplayApp/></Suspense>}/>
    <Route path="/chat-react" element={<ChatApp/>}/>
    <Route path="/memories" element={<Suspense fallback={<p className="page-loading">正在加载记忆管理…</p>}><MemoryApp/></Suspense>}/>
    <Route path="/scenarios" element={<Suspense fallback={<p className="page-loading">正在加载生活场景…</p>}><ScenarioApp/></Suspense>}/>
    <Route path="/personas" element={<Suspense fallback={<p className="page-loading">正在加载用户画像…</p>}><PersonaApp/></Suspense>}/>
    <Route path="/settings" element={<Suspense fallback={<p className="page-loading">正在加载个性化设置…</p>}><SettingsApp/></Suspense>}/>
    <Route path="/experiments-react" element={<Suspense fallback={<p className="page-loading">正在加载实验档案…</p>}><ExperimentApp/></Suspense>}/>
    <Route path="*" element={<Navigate to="/chat-react" replace/>}/>
  </Routes></BrowserRouter></AppearanceProvider></QueryClientProvider>;
}

createRoot(document.getElementById('root')!).render(<ConsoleApp/>);
