import {useEffect, useRef, useState} from 'react';
import {Alert, Button, Input, Modal, Select} from 'antd';
import {useQuery, useQueryClient} from '@tanstack/react-query';
import {useSearchParams} from 'react-router-dom';
import {ApiError, ChatApi, type Config, type DeviceStatus, type MemoryFeedbackKind, type MemoryPageSummary, type Snapshot, type Summary, type Turn} from '../api';
import {turnSummary} from '../../../assets/chat-view.mjs';
import {AppShell, ConsoleNav} from '../components/AppShell';
import {PageHeader} from '../components/PageHeader';
import {SpeechPlayer} from '../features/voice/SpeechPlayer';
import {modelFailure} from '../features/settings/modelHealth';
import {MemoryCommandHelp} from '../features/chat/MemoryCommandHelp';
import {loadSendShortcut, saveSendShortcut, shouldSendFromKeyboard, type SendShortcut} from '../features/chat/chatInput';
import {organizeChats, readPinnedChats, togglePinnedChat, writePinnedChats} from '../features/chat/chatSessions';
import {ConsoleStatusRail, MemoryFeedbackControls, TurnMemoryEvidence} from '../features/chat/ChatObservability';
import {chatFailure} from '../features/chat/chatFailure';
import '../styles/chat-workspace.css';

const api = new ChatApi();
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
/** 文字聊天页面串起输入、服务响应和记忆证据；请求仍通过统一 API 客户端。 */
export function ChatApp() {
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
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
  const [panel, setPanel] = useState<'sessions' | 'evidence' | 'runtime' | null>(null);
  const [evidenceIndex, setEvidenceIndex] = useState<number>();
  // ref 在同一事件循环内立即锁定，避免 React 尚未重绘时的双击重复写入。
  const locked = useRef(false);
  const selectionKey = useRef('');
  const pinnedKey = useRef('');
  const messages = useRef<HTMLElement>(null);
  const panelHeading = useRef<HTMLHeadingElement>(null);
  const deviceStatus = useQuery({queryKey:['device-status'], enabled:Boolean(config?.enabled), retry:false,
    queryFn:() => api.request<DeviceStatus>('/api/device'), refetchInterval:5000});
  const memoryCount = useQuery({queryKey:['chat-active-memory-count'], enabled:Boolean(config?.enabled), retry:false,
    queryFn:() => api.request<MemoryPageSummary>('/api/memories?q=&state=active&offset=0&limit=1'), staleTime:30000});
  const focusedRequestId = searchParams.get('request_id');
  useEffect(() => {
    const focused = focusedRequestId ? document.getElementById(`turn-${focusedRequestId}`) : null;
    const viewport = messages.current;
    if (!viewport) return;
    // 只滚动消息容器，不能让浏览器把整个外壳/输入区带出视口。
    viewport.scrollTop = focused
      ? viewport.scrollTop + focused.getBoundingClientRect().top - viewport.getBoundingClientRect().top - 12
      : viewport.scrollHeight;
  }, [chat?.chat_id, chat?.turns.length, focusedRequestId]);
  useEffect(() => setEvidenceIndex(undefined), [chat?.chat_id]);
  // 窄窗口打开面板时消息被切换出去，将焦点送到新内容，收起后返回入口。
  useEffect(() => {if (panel) panelHeading.current?.focus();}, [panel, evidenceIndex]);
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
        const linkedChat = searchParams.get('chat_id');
        if (rows.length) {const loaded = await load(rows.find(c => c.chat_id === linkedChat)?.chat_id ?? rows.find(c => c.chat_id === previous)?.chat_id ?? rows[0].chat_id); setNotice(loaded.pending ? '消息仍在处理，请只查询结果。' : linkedChat ? '已打开质量复核对应的聊天轮次。' : '会话已恢复，可以继续聊。');}
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
  async function setMemoryFeedback(turn:Turn, kind:MemoryFeedbackKind) {
    if (!chat || !turn.request_id) return;
    await action(async () => {
      const result = await api.request<{feedback:NonNullable<Turn['memory_feedback']>}>(
        `/api/chats/${chat.chat_id}/turns/${turn.request_id}/memory-feedback`, 'POST',
        {kind, expected_revision:turn.memory_feedback?.revision ?? 0},
      );
      setChat(current => current ? {...current, turns:current.turns.map(item =>
        item.request_id === turn.request_id ? {...item,memory_feedback:result.feedback} : item)} : current);
      setNotice('本轮记忆表现已记录；没有重答，也没有修改 L0–L3。');
    });
  }
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
  const sessions = <section className="chat-sidebar-panel" aria-labelledby="chat-session-heading">
        <div className="chat-sidebar-heading"><h2 id="chat-session-heading">会话</h2><Button size="small" disabled={disabled} onClick={() => changeChat()}>新建</Button></div>
        <label htmlFor="chat-search">查找会话</label><Input id="chat-search" name="chat-search" autoComplete="off" allowClear aria-label="查找会话" value={chatSearch} onChange={event => setChatSearch(event.target.value)} placeholder="按名称搜索…"/>
        <label htmlFor="conversation">当前会话</label><Select id="conversation" className="wide" aria-label="最近会话" value={chat?.chat_id} disabled={busy || unknown}
          notFoundContent="没有匹配的会话" options={visibleChats.map(c => ({value: c.chat_id, label: `${pinnedChats.includes(c.chat_id) ? '★ ' : ''}${c.title} · ${c.turn_count} 轮`}))} onChange={changeChat}/>
        <div className="chat-session-actions"><Button size="small" disabled={disabled} onClick={() => {setTitle(chat?.title ?? ''); setRename(true);}}>重命名</Button>
          <Button size="small" disabled={disabled} onClick={toggleCurrentPin}>{chat && pinnedChats.includes(chat.chat_id) ? '取消置顶' : '置顶'}</Button></div>
      </section>;
  const evidenceTurn = evidenceIndex === undefined ? chat?.turns.at(-1) : chat?.turns[evidenceIndex];
  const modelCheck = config?.provider==='openai_compatible'&&<Alert showIcon type={config.model_health?.state==='available'?'success':config.model_health?.state==='unavailable'?'error':'info'}
        title={config.model_health?.state==='available'?'模型服务最近验证可用':config.model_health?.state==='unavailable'?'模型服务最近验证失败':'模型服务尚未验证'}
        description={config.model_health?.state==='unavailable'?(modelFailure(config.model_health.code)??'模型调用失败。'):'检测只发送固定合成短句，不读取或写入个人记忆，也不自动重试。'}
        action={<Button loading={checkingModel} disabled={busy||unknown}
          onClick={()=>void checkModel()}>检测模型连接</Button>}/>;
  function closePanel() {
    if (panel) document.getElementById(`chat-tool-${panel}`)?.focus();
    setPanel(null);
  }
  function togglePanel(next: NonNullable<typeof panel>) {if (panel === next) closePanel(); else setPanel(next);}
  return <><AppShell subtitle="你的日常聊天空间" className="chat-shell" layout="workspace" sidebar={<ConsoleNav active="chat" legacyPath="/chat"/>}>
      <PageHeader eyebrow="日常使用" title="聊聊今天" action={<div className="page-header-actions"><span>{chat?.turns.length ?? 0} / 40 轮</span><MemoryCommandHelp/></div>}/>
      <div className="chat-tools" aria-label="聊天工作区工具">
        <span className="chat-current-title" title={chat?.title}>{chat?.title ?? '正在打开会话…'}</span>
        <Button id="chat-tool-sessions" aria-expanded={panel === 'sessions'} aria-controls={panel ? 'chat-aux-panel' : undefined} onClick={() => togglePanel('sessions')}>会话</Button>
        <Button id="chat-tool-evidence" aria-expanded={panel === 'evidence'} aria-controls={panel ? 'chat-aux-panel' : undefined} onClick={() => {setEvidenceIndex(undefined); togglePanel('evidence');}}>记忆证据</Button>
        <Button id="chat-tool-runtime" danger={config?.model_health?.state === 'unavailable'} aria-expanded={panel === 'runtime'} aria-controls={panel ? 'chat-aux-panel' : undefined} onClick={() => togglePanel('runtime')}>运行状态</Button>
        <Button disabled={disabled} onClick={() => changeChat()}>新聊天</Button>
      </div>
      <div className={`chat-workspace${panel ? ' has-panel' : ''}`}><section ref={messages} className="messages" aria-label="聊天记录" tabIndex={0}>{!chat?.turns.length && <div className="empty"><h2>今天想聊些什么？</h2><p>可以说说今天的事，也可以继续上次的话题。</p></div>}
        {chat?.turns.map((turn, i) => <article id={turn.request_id ? `turn-${turn.request_id}` : undefined} className={turn.request_id === focusedRequestId ? 'focused-chat-turn' : undefined} key={turn.request_id ?? i}><div className="bubble user"><strong>你</strong><p>{turn.input}</p></div><div className="bubble assistant"><strong>助手</strong><p>{turn.answer ?? '未获得完整回答。'}</p>{turn.answer&&<SpeechPlayer api={api} text={turn.answer}/>}<MemoryFeedbackControls turn={turn} disabled={busy || unknown} onSelect={kind => void setMemoryFeedback(turn,kind)}/></div>
          {turn.memory_command && <Alert className="memory-command-result" showIcon type={memoryCommandAlert(turn.memory_command.status)} title="实际记忆操作结果" description={turn.memory_command.notice}/>}
          {turn.follow_up_suggestion?.status === 'candidate_armed' && <Alert className="memory-command-result" showIcon type="success" title="一次性跟进已安排" description={`${new Date(turn.follow_up_suggestion.follow_up_at!).toLocaleString('zh-CN')} · ${turn.follow_up_suggestion.prompt_text}。到点仍会经过勿扰时段、频率和设备状态检查。`}/>}
          {turn.follow_up_suggestion?.status === 'candidate_created_requires_proactive_enabled' && <Alert className="memory-command-result" showIcon type="info" title="已保存跟进候选" description={`${new Date(turn.follow_up_suggestion.follow_up_at!).toLocaleString('zh-CN')} · ${turn.follow_up_suggestion.prompt_text}。主动交流总开关目前关闭，因此尚未安排播报；可在“设置中心 → 主动交流”开启后核对并启用。`}/>}
          {turn.follow_up_suggestion?.status === 'not_created' && <Alert className="memory-command-result" showIcon type="warning" title="跟进候选未保存" description="本轮聊天和长期记忆仍已保存；可稍后在设置中心手动创建跟进。"/>}
          {turn.memory_processing === 'source_only' && <p className="memory-warning">{memoryWarning(turn)} 可继续聊天，之后需要重新整理这条来源。</p>}
          {turn.retrieval_warning === 'dense_retrieval_failed' && <p className="memory-warning">本轮本地 BGE 检索失败，已使用关键词结果继续回答；展开过程可查看实际策略。</p>}
          {Boolean(turn.scenario_retrieved?.length) && <p className="scenario-trace">本轮使用 L2：{turn.scenario_retrieved!.map(item => item.title).join('、')}</p>}
          {Boolean(turn.persona_retrieved?.length) && <p className="scenario-trace">本轮使用 L3：{turn.persona_retrieved!.map(item => item.label).join('、')}</p>}
          <Button className="turn-evidence-action" aria-label={`查看第 ${i + 1} 轮记忆证据`} onClick={() => {setEvidenceIndex(i); setPanel('evidence');}}>{turnSummary(turn)}</Button></article>)}</section>
        {panel && <aside id="chat-aux-panel" className="chat-aux-panel" aria-label={panel === 'sessions' ? '会话管理' : panel === 'evidence' ? '记忆证据面板' : '运行状态面板'} onKeyDown={event => {if (event.key === 'Escape') {event.stopPropagation(); closePanel();}}}>
          <div className="chat-panel-heading"><h2 ref={panelHeading} tabIndex={-1}>{panel === 'sessions' ? '会话管理' : panel === 'evidence' ? evidenceIndex === undefined ? '本轮记忆证据' : `第 ${evidenceIndex + 1} 轮记忆证据` : '运行状态'}</h2><Button onClick={closePanel}>收起面板</Button></div>
          <div className="chat-panel-content">{panel === 'sessions' ? sessions : panel === 'evidence' ? <TurnMemoryEvidence turn={evidenceTurn}/> : <>
            <ConsoleStatusRail config={config} device={deviceStatus.data} deviceFailed={deviceStatus.isError} activeMemoryCount={memoryCount.data?.total}/>
            {modelCheck}<section className="chat-runtime-info"><h3>运行配置与记忆说明</h3><p>{config?.enabled ? `${config.model} · ${config.role} · ${config.provider}` : '聊天未启用'}</p>{config?.provider === 'fake' && <p>Fake 是离线工程替身，不具备角色和多轮理解能力。</p>}<p>提取：{config?.method === 'longmemory_daily_llm_v2' ? '模型辅助 P3.2（失败保留 L0）' : '规则基线'}；检索：{config?.retrieval === 'keyword_dense_rrf_v1' ? '关键词＋本地 BGE 融合 P3.2' : '关键词基线'}。网页不自动驱动圆屏播放。</p>{config?.enabled && <p>记忆库：{config.database}</p>}<p>发送会先保存原始输入，再按当前提取策略生成长期记忆。</p></section>
          </>}</div>
        </aside>}
      </div>
      <form className="chat-composer" onSubmit={event => {event.preventDefault(); void send();}}>
        <label className="chat-message-label" htmlFor="chat-message">消息</label><Input.TextArea id="chat-message" name="message" autoComplete="off" aria-label="消息" value={draft} maxLength={1000} rows={2} disabled={disabled || (chat?.turns.length ?? 0) >= 40} onChange={event => setDraft(event.target.value)}
        onKeyDown={event => {if (shouldSendFromKeyboard({...event, isComposing: event.nativeEvent.isComposing}, sendShortcut)) {event.preventDefault(); void send();}}}
        placeholder="写下想说的话…"/>
        <div className="send-row"><Select size="small" aria-label="发送快捷键" value={sendShortcut}
          options={[{value:'enter',label:'Enter 发送 · Shift+Enter 换行'},{value:'ctrl_enter',label:'Ctrl+Enter 发送 · Enter 换行'}]}
          onChange={value => {setSendShortcut(value); saveSendShortcut(value);}}/><Button type="primary" htmlType="submit" loading={busy && Boolean(chat)} disabled={disabled || !draft.trim() || (chat?.turns.length ?? 0) >= 40}>发送</Button></div>
        <p className="chat-status" role="status">{(chat?.turns.length ?? 0) >= 40 ? '本会话已达 40 轮，请新建聊天；长期记忆保留。' : notice}{config?.model_health?.state === 'unavailable' && ' 模型最近验证失败，可在运行状态中检测连接。'}</p>
        {unknown && <Button disabled={busy} onClick={() => void action(async () => {if (!chat) return; const result = await load(chat.chat_id); if (!result.pending && result.turns.length > chat.turns.length) setDraft(''); setNotice(result.pending ? '后台仍在处理，没有重发。' : '已查询。服务中断时不能据此保证未写入，请检查过程。');})}>只查询结果，不重发</Button>}
      </form>
    </AppShell>
    <Modal title="重命名聊天" open={rename} onCancel={() => setRename(false)} confirmLoading={busy} okText="保存" cancelText="取消" okButtonProps={{disabled: !title.trim() || busy}}
      onOk={() => void action(async () => {await api.request(`/api/chats/${chat?.chat_id}/title`, 'POST', {title}); await list(); if (chat) setChat({...chat,title}); setRename(false);})}><Input aria-label="聊天名称" maxLength={60} value={title} onChange={event => setTitle(event.target.value)}/></Modal>
  </>;
}
