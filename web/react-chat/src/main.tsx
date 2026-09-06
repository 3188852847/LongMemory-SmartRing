import {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Button, ConfigProvider, Input, Modal, Select, theme} from 'antd';
import {ChatApi, type Config, type Snapshot, type Summary, type Turn} from './api';
import {KEY, normalize, read, save, apply} from '../../assets/appearance.mjs';
import {turnSummary} from '../../assets/chat-view.mjs';
import './style.css';
import {RoleEditor} from './RoleEditor';
import {VoiceSettings} from './VoiceSettings';

const api = new ChatApi();
const nonce = document.querySelector<HTMLMetaElement>('meta[name="style-nonce"]')?.content;
function memoryWarning(turn: Turn) {
  return turn.memory_warning === 'l1_persistence_failed'
    ? '本轮 L0 原始对话已保存，但 L1 记忆写入失败。'
    : '本轮 L0 原始对话已保存，但 L1 记忆提取失败。';
}
function App() {
  const [config, setConfig] = useState<Config>();
  const [chats, setChats] = useState<Summary[]>([]);
  const [chat, setChat] = useState<Snapshot>();
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(true);
  const [unknown, setUnknown] = useState(false);
  const [notice, setNotice] = useState('正在连接本机服务…');
  const [rename, setRename] = useState(false);
  const [title, setTitle] = useState('');
  const [prefs, setPrefs] = useState(() => {try {return read(localStorage);} catch {return normalize(null);}});
  const [dark, setDark] = useState(matchMedia('(prefers-color-scheme: dark)').matches);
  // ref 在同一事件循环内立即锁定，避免 React 尚未重绘时的双击重复写入。
  const locked = useRef(false);
  const selectionKey = useRef('');
  const turnsEnd = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)');
    const change = () => setDark(media.matches);
    const storage = (event: StorageEvent) => {if (event.key === KEY || event.key === null) {try {setPrefs(read(localStorage));} catch {setPrefs(normalize(null));}}};
    media.addEventListener('change', change); window.addEventListener('storage', storage);
    return () => {media.removeEventListener('change', change); window.removeEventListener('storage', storage);};
  }, []);
  useEffect(() => {apply(document.documentElement, prefs, dark);}, [prefs, dark]);
  useEffect(() => {turnsEnd.current?.scrollIntoView({block: 'nearest'});}, [chat?.turns.length]);
  function appearance(value: typeof prefs) {
    setPrefs(normalize(value));
    try {if (!save(localStorage, value)) throw new Error();}
    catch {setNotice('浏览器无法保存外观设置，本页仍可使用。');}
  }
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
        const rows = await list(); let previous: string | null = null;
        try {previous = localStorage.getItem(selectionKey.current);} catch { /* 默认最近会话。 */ }
        if (rows.length) {const loaded = await load(rows.find(c => c.chat_id === previous)?.chat_id ?? rows[0].chat_id); setNotice(loaded.pending ? '消息仍在处理，请只查询结果。' : '会话已恢复，可以继续聊。');}
        else {await create(); setNotice('新聊天已就绪。');}
      } catch (error) {setNotice(String(error));} finally {setBusy(false);}
    })();
  }, []);
  async function action(work: () => Promise<void>) {
    if (locked.current) return; locked.current = true; setBusy(true);
    try {await work();} catch (error) {setNotice(String(error));} finally {locked.current = false; setBusy(false);}
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
        setNotice(turn.memory_processing === 'source_only'
          ? `回答已完成，但${memoryWarning(turn).replace('本轮 ', '')}不要把它误认为“不该记”。`
          : turn.retrieval_warning === 'dense_retrieval_failed'
            ? '回答已完成，但本地 BGE 检索失败，本轮已明确降级为关键词检索。'
          : turn.status === 'completed' ? '本轮完成，可展开查看记忆证据。' : '本轮未完成；输入可能已保存，请查看过程。');
      } catch (error) {setUnknown(true); setNotice(`${String(error)} 结果未知，请点击查询结果。`);}
    });
  }
  const disabled = busy || unknown || !chat;
  return <ConfigProvider csp={{nonce}} theme={{algorithm: (prefs.theme === 'dark' || (prefs.theme === 'system' && dark)) ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {colorPrimary: '#b62e68', fontSize: prefs.size === 'larger' ? 20 : prefs.size === 'large' ? 18 : 16, borderRadius: 10}}}>
    <div className="shell"><aside><a className="brand" href="/">LongMemory</a><p>你的日常聊天空间</p>
      <Button block disabled={disabled} onClick={() => changeChat()}>新聊天</Button>
      <label htmlFor="conversation">最近会话</label><Select id="conversation" className="wide" aria-label="最近会话" value={chat?.chat_id} disabled={busy || unknown}
        options={chats.map(c => ({value: c.chat_id, label: `${c.title} · ${c.turn_count} 轮`}))} onChange={changeChat}/>
      <Button disabled={disabled} onClick={() => {setTitle(chat?.title ?? ''); setRename(true);}}>重命名</Button>
      <VoiceSettings api={api} disabled={busy || !config?.enabled}/>
      <nav><RoleEditor api={api} disabled={busy || !config?.enabled} onSaved={() => {void api.request<Config>('/api/chat-config').then(setConfig).catch(() => setNotice('角色已保存，但运行配置显示未刷新，请重新读取。'));}}/><a href="/">设备与状态</a><a href="/memories">记忆管理</a><a href="/experiments">实验中心</a><a href="/chat">返回原版聊天</a></nav>
      <details><summary>外观与阅读</summary><label>主题</label><Select className="wide" aria-label="主题" value={prefs.theme} onChange={value => appearance({...prefs, theme: value})} options={[{value:'system',label:'跟随系统'},{value:'light',label:'浅色'},{value:'dark',label:'深色'}]}/>
        <label>字号</label><Select className="wide" aria-label="字号" value={prefs.size} onChange={value => appearance({...prefs,size:value})} options={[{value:'normal',label:'标准'},{value:'large',label:'大'},{value:'larger',label:'更大'}]}/><Button onClick={() => appearance(normalize(null))}>恢复默认</Button></details>
    </aside><main><header><h1>聊聊今天</h1><span>{chat?.turns.length ?? 0} / 40 轮 · React 预览</span></header>
      <section className="messages" aria-label="聊天记录">{!chat?.turns.length && <div className="empty"><h2>今天想聊些什么？</h2><p>可以说说今天的事，也可以继续上次的话题。</p></div>}
        {chat?.turns.map((turn, i) => <article key={i}><div className="bubble user"><strong>你</strong><p>{turn.input}</p></div><div className="bubble assistant"><strong>助手</strong><p>{turn.answer ?? '未获得完整回答。'}</p></div>
          {turn.memory_processing === 'source_only' && <p className="memory-warning">{memoryWarning(turn)} 可继续聊天，之后需要重新整理这条来源。</p>}
          {turn.retrieval_warning === 'dense_retrieval_failed' && <p className="memory-warning">本轮本地 BGE 检索失败，已使用关键词结果继续回答；展开过程可查看实际策略。</p>}
          <details><summary>{turnSummary(turn)}</summary><pre>{JSON.stringify(turn, null, 2)}</pre></details></article>)}<div ref={turnsEnd}/></section>
      <form onSubmit={event => {event.preventDefault(); void send();}}><Input.TextArea aria-label="消息" value={draft} maxLength={1000} rows={3} disabled={disabled || (chat?.turns.length ?? 0) >= 40} onChange={event => setDraft(event.target.value)} placeholder="写下想说的话…"/>
        <div className="send-row"><small>发送会先保存原始输入，再按当前提取策略生成长期记忆。</small><Button type="primary" htmlType="submit" disabled={disabled || !draft.trim() || (chat?.turns.length ?? 0) >= 40}>发送</Button></div></form>
      <p role="status">{notice}</p>{unknown && <Button disabled={busy} onClick={() => void action(async () => {if (!chat) return; const result = await load(chat.chat_id); if (!result.pending && result.turns.length > chat.turns.length) setDraft(''); setNotice(result.pending ? '后台仍在处理，没有重发。' : '已查询。服务中断时不能据此保证未写入，请检查过程。');})}>只查询结果，不重发</Button>}
      <details className="runtime"><summary>运行配置与记忆说明</summary><p>{config?.enabled ? `${config.model} · ${config.role} · ${config.provider}` : '聊天未启用'}</p>{config?.provider === 'fake' && <p>Fake 是离线工程替身，不具备角色和多轮理解能力。</p>}<p>提取：{config?.method === 'longmemory_daily_llm_v2' ? '模型辅助 P3.2（失败保留 L0）' : '规则基线'}；检索：{config?.retrieval === 'keyword_dense_rrf_v1' ? '关键词＋本地 BGE 融合 P3.2' : '关键词基线'}。网页不自动驱动圆屏播放。</p>{config?.enabled && <p>记忆库：{config.database}</p>}</details>
    </main></div>
    <Modal title="重命名聊天" open={rename} onCancel={() => setRename(false)} confirmLoading={busy} okText="保存" cancelText="取消" okButtonProps={{disabled: !title.trim() || busy}}
      onOk={() => void action(async () => {await api.request(`/api/chats/${chat?.chat_id}/title`, 'POST', {title}); await list(); if (chat) setChat({...chat,title}); setRename(false);})}><Input aria-label="聊天名称" maxLength={60} value={title} onChange={event => setTitle(event.target.value)}/></Modal>
  </ConfigProvider>;
}
createRoot(document.getElementById('root')!).render(<App/>);
