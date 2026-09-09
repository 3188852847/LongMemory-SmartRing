import {useEffect, useRef, useState} from 'react';
import {Button, Card, Checkbox, Descriptions, Drawer, Empty, Input, List, Modal, Select, Space, Switch, Tabs, Tag} from 'antd';
import {useSearchParams} from 'react-router-dom';
import {ChatApi} from './api';
import {AppShell, ConsoleNav} from './AppShell';
import {PageHeader} from './PageHeader';
import {ManualMemoryAdd} from './ManualMemoryAdd';
import {memoryFailure, type MemoryFailurePhase} from './memoryFailure';

type MemoryConfig = {configured: boolean; database: string | null; allow_delete: boolean; allow_correction: boolean; allow_change: boolean};
type RuntimeMode = {write_enabled: boolean; use_enabled: boolean; scenario_use_enabled: boolean; scenario_available: boolean; persona_use_enabled: boolean; persona_available: boolean; persistent: boolean; l0_archived_when_write_disabled: boolean};
type L1Summary = {id: string; content: string; truncated: boolean; state: 'active' | 'retired'; recorded_at: string; subject_id: string};
type Source = {source_message_id: string; source_type: string; linked_at: string; message: null | {role: string; content: string; created_at: string}};
type L1Detail = L1Summary & {content: string; revision: string; valid_from: string | null; valid_to: string | null; retired_at: string | null; superseded_by_id: string | null; sources: Source[]};
type L0Summary = {id: string; role: 'user' | 'assistant'; content: string; truncated: boolean; created_at: string; linked_memory_count: number};
type DerivedMemory = {id: string; content: string; state: 'active' | 'retired'; source_type: string; linked_at: string};
type L0Detail = {id: string; role: 'user' | 'assistant'; content: string; created_at: string; derived_memories: DerivedMemory[]};
type Page<T> = {items: T[]; total: number; limit: number; offset: number};
type DailyActivity = 'added'|'corrected'|'changed';
type DailyReviewItem = L1Summary & {activity:DailyActivity};
type DailyDeletion = {id:string;memory_id:string;subject_id:string;deleted_at:string};
type DailyReview = {local_date:string;utc_offset_minutes:number;items:DailyReviewItem[];total:number;limited:boolean;activity_counts:Record<DailyActivity|'deleted',number>;message_counts:{user:number;assistant:number;total:number};deletions:DailyDeletion[];deletions_limited:boolean};

const api = new ChatApi();
const displayTime = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '未记录';
const sourceName = (value: string) => value === 'user_stated' ? '用户陈述' : value === 'user_corrected' ? '用户纠正' : value;
const localDateText = (date=new Date()) => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;

export function MemoryApp() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [config, setConfig] = useState<MemoryConfig>();
  const [mode, setMode] = useState<RuntimeMode>();
  const [modeDraft, setModeDraft] = useState({write_enabled: true, use_enabled: true, scenario_use_enabled: false, persona_use_enabled: false});
  const [tab, setTab] = useState<'l1' | 'l0'>('l1');
  const [l1, setL1] = useState<Page<L1Summary>>({items: [], total: 0, limit: 25, offset: 0});
  const [l0, setL0] = useState<Page<L0Summary>>({items: [], total: 0, limit: 25, offset: 0});
  const [daily,setDaily] = useState<DailyReview>();
  const [reviewDate,setReviewDate] = useState(localDateText());
  const [dailyNotice,setDailyNotice] = useState('');
  const [query, setQuery] = useState('');
  const [l1State, setL1State] = useState('active');
  const [role, setRole] = useState('all');
  const [linkState, setLinkState] = useState('all');
  const [selectedL1, setSelectedL1] = useState<L1Detail>();
  const [selectedL0, setSelectedL0] = useState<L0Detail>();
  const [busy, setBusy] = useState(true);
  const [notice, setNotice] = useState('正在连接本机记忆服务…');
  const [correcting, setCorrecting] = useState(false);
  const [correction, setCorrection] = useState('');
  const [changing, setChanging] = useState(false);
  const [changedContent, setChangedContent] = useState('');
  const [effectiveLocal, setEffectiveLocal] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [deleteUnderstood, setDeleteUnderstood] = useState(false);
  const locked = useRef(false);

  async function fetchL1(offset = 0, search = query, stateFilter = l1State) {
    const params = new URLSearchParams({q: search, state: stateFilter, offset: String(offset), limit: '25'});
    const data = await api.request<Page<L1Summary>>(`/api/memories?${params}`);
    setL1(data); setSelectedL1(undefined);
  }
  async function fetchL0(offset = 0, search = query, roleFilter = role, linkFilter = linkState) {
    const params = new URLSearchParams({q: search, role: roleFilter, link_state: linkFilter, offset: String(offset), limit: '25'});
    const data = await api.request<Page<L0Summary>>(`/api/source-messages?${params}`);
    setL0(data); setSelectedL0(undefined);
  }
  async function fetchDaily(date=reviewDate) {
    const params=new URLSearchParams({local_date:date,utc_offset_minutes:String(-new Date().getTimezoneOffset())});
    try {
      setDaily(await api.request<DailyReview>(`/api/memories/daily-review?${params}`));
      setDailyNotice('');
    } catch {
      setDaily(undefined);
      setDailyNotice('暂时无法读取这一天的回顾；完整 L1 列表仍可正常使用。');
    }
  }
  async function refresh(offset = 0, search = query) {
    setBusy(true);
    try {
      if (tab === 'l1') {await fetchL1(offset, search); await fetchDaily();} else await fetchL0(offset, search);
      setNotice('列表已更新。');
    } catch (error) {setNotice(memoryFailure(error, 'read'));}
    finally {setBusy(false);}
  }
  useEffect(() => {
    void (async () => {
      try {
        await api.bootstrap();
        const current = await api.request<MemoryConfig>('/api/memory-config');
        setConfig(current);
        if (!current.configured) {setNotice('启动时没有指定记忆库；页面不会自动创建数据库。'); return;}
        try {
          const runtime = await api.request<RuntimeMode>('/api/memory-mode');
          setMode(runtime); setModeDraft({write_enabled: runtime.write_enabled, use_enabled: runtime.use_enabled, scenario_use_enabled: runtime.scenario_use_enabled, persona_use_enabled: runtime.persona_use_enabled});
        } catch {setNotice('记忆库可浏览，但聊天 Runtime 未启用，运行期开关不可用。');}
        const params = new URLSearchParams({q: '', state: 'active', offset: '0', limit: '25'});
        setL1(await api.request<Page<L1Summary>>(`/api/memories?${params}`));
        await fetchDaily();
        const linkedMemoryId = searchParams.get('memory_id')?.trim();
        if (linkedMemoryId && linkedMemoryId.length <= 128 && !/[\u0000-\u001f\u007f]/.test(linkedMemoryId)) {
          try {
            setSelectedL1(await api.request<L1Detail>(`/api/memories/${encodeURIComponent(linkedMemoryId)}`));
            setNotice('已从聊天证据打开对应 L1；下方可核对 L0 原始来源。');
          } catch {
            setNotice('链接指向的 L1 不存在或已不可用；记忆列表仍可正常浏览。');
          }
        } else {
          setNotice(linkedMemoryId ? '记忆链接格式无效；未自动打开详情。' : 'L1 原子记忆已加载；可切换到 L0 检查原始记录。');
        }
      } catch (error) {setNotice(memoryFailure(error, 'read'));}
      finally {setBusy(false);}
    })();
  }, []);

  function closeL1() {
    setSelectedL1(undefined);
    if (searchParams.has('memory_id')) {
      const next = new URLSearchParams(searchParams);
      next.delete('memory_id');
      setSearchParams(next, {replace: true});
    }
  }

  async function guarded(work: () => Promise<void>, phase: MemoryFailurePhase = 'read') {
    if (locked.current) return;
    locked.current = true; setBusy(true);
    try {await work();} catch (error) {setNotice(memoryFailure(error, phase));}
    finally {locked.current = false; setBusy(false);}
  }
  async function openL1(id: string) {
    await guarded(async () => {setSelectedL1(await api.request<L1Detail>(`/api/memories/${encodeURIComponent(id)}`));});
  }
  async function openCorrection(id:string) {
    await guarded(async()=>{
      const detail=await api.request<L1Detail>(`/api/memories/${encodeURIComponent(id)}`);
      setSelectedL1(detail); setCorrection(''); setCorrecting(true);
    });
  }
  function changeReviewDate(value:string) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value>localDateText()) return;
    setReviewDate(value); void fetchDaily(value);
  }
  function previousReviewDate() {
    const date=new Date(`${reviewDate}T12:00:00`); date.setDate(date.getDate()-1);
    changeReviewDate(localDateText(date));
  }
  async function openL0(id: string) {
    await guarded(async () => {setSelectedL0(await api.request<L0Detail>(`/api/source-messages/${encodeURIComponent(id)}`));});
  }
  function switchTab(key: string) {
    const next = key as 'l1' | 'l0'; setTab(next); setQuery(''); setSelectedL1(undefined); setSelectedL0(undefined);
    void guarded(async () => {
      if (next === 'l1') await fetchL1(0, ''); else await fetchL0(0, '');
      setNotice(next === 'l1' ? '这里显示系统派生的 L1 原子记忆。' : '这里显示完整 L0 原始记录，包括没有形成 L1 的话语。');
    });
  }
  async function saveMode() {
    await guarded(async () => {
      const saved = await api.request<RuntimeMode>('/api/memory-mode', 'PUT', modeDraft);
      setMode(saved); setNotice(`已应用到网页与圆屏：L1 写入${saved.write_enabled ? '开启' : '暂停'}，L1 使用${saved.use_enabled ? '开启' : '暂停'}，L2 场景${saved.scenario_use_enabled ? '参与回答' : '不参与回答'}，L3 画像${saved.persona_use_enabled ? '参与回答' : '不参与回答'}。`);
    }, 'write');
  }
  async function saveCorrection() {
    if (!selectedL1 || !correction.trim()) return;
    await guarded(async () => {
      const result = await api.request<{new_memory_id: string}>(`/api/memories/${encodeURIComponent(selectedL1.id)}/corrections`, 'POST', {
        revision: selectedL1.revision, corrected_content: correction.trim(), correction_kind: 'error', confirm_correction: true,
      });
      setCorrecting(false); setCorrection(''); await fetchL1(0, query); await fetchDaily();
      setSelectedL1(await api.request<L1Detail>(`/api/memories/${encodeURIComponent(result.new_memory_id)}`));
      setNotice('纠正已保存：新 L1 生效，旧 L1 保留为已取代历史。');
    }, 'write');
  }
  function openChange() {
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    setEffectiveLocal(now.toISOString().slice(0, 16));
    setChangedContent('');
    setChanging(true);
  }
  async function saveChange() {
    if (!selectedL1 || !changedContent.trim() || !effectiveLocal) return;
    await guarded(async () => {
      const result = await api.request<{new_memory_id: string}>(`/api/memories/${encodeURIComponent(selectedL1.id)}/changes`, 'POST', {
        revision: selectedL1.revision,
        new_content: changedContent.trim(),
        effective_at: new Date(effectiveLocal).toISOString(),
        change_kind: 'fact_changed',
        confirm_change: true,
      });
      setChanging(false); setChangedContent(''); setEffectiveLocal(''); await fetchL1(0, query); await fetchDaily();
      setSelectedL1(await api.request<L1Detail>(`/api/memories/${encodeURIComponent(result.new_memory_id)}`));
      setNotice('变化已保存：旧事实保留历史有效期，新事实从指定时间开始生效。');
    }, 'write');
  }
  async function removeMemory() {
    if (!selectedL1) return;
    await guarded(async () => {
      await api.request(`/api/memories/${encodeURIComponent(selectedL1.id)}`, 'DELETE', {revision: selectedL1.revision, confirm_delete: true});
      setDeleting(false); setDeleteUnderstood(false); setSelectedL1(undefined);
      await fetchL1(0, query); await fetchDaily(); setNotice('L1 已删除；L0 原始对话仍保留。');
    }, 'write');
  }

  const page = tab === 'l1' ? l1 : l0;
  const sidebar = <>
      <ConsoleNav active="memories" legacyPath="/memories-legacy"/>
      <Card size="small" className="memory-layer-guide" title="层级说明"><p><Tag color="magenta">L1</Tag><span>规范化、可召回的派生事实</span></p><p><Tag color="blue">L0</Tag><span>用户或助手当时说过的原文</span></p></Card>
    </>;
  return <><AppShell subtitle="可追溯的个人记忆" className="memory-shell" sidebar={sidebar}><PageHeader eyebrow="长期记忆" title="原始与原子记忆" description="查看系统保存的原话和从中提取的可召回事实，并核对两者之间的来源关系。" meta={config?.database ?? '未指定记忆库'} action={<Space><ManualMemoryAdd api={api} disabled={!config?.configured || !mode} onSaved={async memoryId => {await fetchL1(0, ''); setTab('l1'); setQuery(''); setNotice('明确事实已处理，列表已更新。'); if (memoryId) await openL1(memoryId);}}/><Button loading={busy} disabled={!config?.configured} onClick={() => void refresh(page.offset)}>刷新</Button></Space>}/>
      <section className="memory-overview" aria-label="记忆概览"><div><small>当前视图</small><strong>{tab === 'l1' ? 'L1 原子记忆' : 'L0 原始记录'}</strong></div><div><small>记录数</small><strong>{page.total}</strong></div><div><small>回答时召回</small><strong className={mode?.use_enabled ? 'is-positive' : ''}>{mode?.use_enabled ? '已开启' : '已关闭'}</strong></div></section>
      <Card className="mode-card" title={`每日记忆回顾 · ${reviewDate}`} extra={<Space wrap><Button size="small" onClick={previousReviewDate}>前一天</Button><Input aria-label="回顾日期" type="date" max={localDateText()} value={reviewDate} onChange={event=>changeReviewDate(event.target.value)} style={{width:145}}/><Button size="small" disabled={reviewDate===localDateText()} onClick={()=>changeReviewDate(localDateText())}>今天</Button>{daily&&<Tag color={daily.total?'processing':'default'}>{daily.total} 条写入</Tag>}</Space>}>
        <p className="subtle">这里按你的本地自然日显示当天形成的 L1，包括后来被纠正或取代的记录；它不是“当前有效记忆”总表，也不会触发模型整理。</p>
        {dailyNotice&&<p role="status" className="subtle">{dailyNotice}</p>}
        {daily&&<>
        <p className="subtle">当天归档 L0：用户 {daily.message_counts.user} 条，助手 {daily.message_counts.assistant} 条。这里只是原始记录计数，不代表会话轮数或内容总结。</p>
        <Space wrap><Tag>新增 {daily.activity_counts.added}</Tag><Tag color="gold">纠正 {daily.activity_counts.corrected}</Tag><Tag color="blue">事实变化 {daily.activity_counts.changed}</Tag><Tag color="red">删除 {daily.activity_counts.deleted}</Tag></Space>
        {daily.items.length?<List size="small" dataSource={daily.items.slice(0,5)} renderItem={item=><List.Item actions={[<Button type="link" key="review" onClick={()=>void openL1(item.id)}>核对来源</Button>]}>
          <List.Item.Meta title={item.content} description={<Space wrap><Tag color={item.activity==='corrected'?'gold':item.activity==='changed'?'blue':'default'}>{item.activity==='corrected'?'纠正':item.activity==='changed'?'事实变化':'新增'}</Tag><Tag color={item.state==='active'?'green':'default'}>{item.state==='active'?'当前':'已退役'}</Tag><span>{displayTime(item.recorded_at)}</span>{item.state==='active'&&config?.allow_correction&&<Button type="link" size="small" onClick={event=>{event.stopPropagation();void openCorrection(item.id);}}>直接纠正</Button>}</Space>}/>
        </List.Item>}/>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="这一天没有形成 L1"/>}
        {daily.total>5&&<p className="subtle">这里只展开最近 5 条；下方 L1 列表可查看全部。{daily.limited?'今日记录达到 100 条读取上限。':''}</p>}
        {daily.deletions.length>0&&<details><summary>查看删除审计（{daily.deletions.length}）</summary><List size="small" dataSource={daily.deletions} renderItem={event=><List.Item><Space direction="vertical" size={0}><span>已删除 L1：<code>{event.memory_id}</code></span><small className="subtle">{displayTime(event.deleted_at)} · 不保留被删正文</small></Space></List.Item>}/>{daily.deletions_limited&&<p className="subtle">删除审计超过 100 条，这里只显示最近记录。</p>}</details>}
        </>}
      </Card>
      {mode && <Card className="mode-card" title={<span>本次运行的记忆模式 <Tag>临时设置</Tag></span>} extra={<Button type="primary" disabled={busy || (mode.write_enabled === modeDraft.write_enabled && mode.use_enabled === modeDraft.use_enabled && mode.scenario_use_enabled === modeDraft.scenario_use_enabled && mode.persona_use_enabled === modeDraft.persona_use_enabled)} onClick={() => void saveMode()}>应用到网页与圆屏</Button>}>
        <div className="memory-mode-grid">
          <label><Switch checked={modeDraft.write_enabled} disabled={busy} onChange={value => setModeDraft({...modeDraft, write_enabled: value})}/><span><strong>生成 L1</strong><small>从新对话提取原子记忆</small></span></label>
          <label><Switch checked={modeDraft.use_enabled} disabled={busy} onChange={value => setModeDraft({...modeDraft, use_enabled: value})}/><span><strong>使用 L1</strong><small>回答时召回已有事实</small></span></label>
          <label><Switch checked={modeDraft.scenario_use_enabled} disabled={busy || !mode.scenario_available} onChange={value => setModeDraft({...modeDraft, scenario_use_enabled: value})}/><span><strong>使用 L2</strong><small>注入已接受生活场景</small></span></label>
          <label><Switch checked={modeDraft.persona_use_enabled} disabled={busy || !mode.persona_available} onChange={value => setModeDraft({...modeDraft, persona_use_enabled: value})}/><span><strong>使用 L3</strong><small>注入已接受用户画像</small></span></label>
        </div><p className="subtle">关闭 L1 写入仍保留 L0。L2/L3 只使用当前有效且与问题相关的内容，设置在服务重启后恢复默认。</p></Card>}
      <section className="memory-browser"><Tabs activeKey={tab} onChange={switchTab} items={[{key: 'l1', label: `L1 原子记忆 · ${l1.total}`}, {key: 'l0', label: `L0 原始记录 · ${l0.total}`}]}/>
      <div className="memory-toolbar"><Input.Search aria-label="搜索当前层级" value={query} maxLength={200} allowClear disabled={busy || !config?.configured} placeholder={tab === 'l1' ? '搜索原子事实' : '搜索原始对话'} onChange={e => setQuery(e.target.value)} onSearch={value => void refresh(0, value.trim())}/>
        {tab === 'l1' ? <Select aria-label="L1 状态" value={l1State} disabled={busy || !config?.configured} onChange={value => {setL1State(value); void guarded(async () => {await fetchL1(0, query, value); setNotice('L1 状态筛选已应用。');});}} options={[{value:'active',label:'当前记忆'},{value:'retired',label:'已退役'},{value:'all',label:'全部 L1'}]}/>
          : <><Select aria-label="L0 角色" value={role} disabled={busy || !config?.configured} onChange={value => {setRole(value); void guarded(async () => {await fetchL0(0, query, value, linkState); setNotice('L0 角色筛选已应用。');});}} options={[{value:'all',label:'全部角色'},{value:'user',label:'用户原话'},{value:'assistant',label:'助手原话'}]}/>
            <Select aria-label="L1 关联" value={linkState} disabled={busy || !config?.configured} onChange={value => {setLinkState(value); void guarded(async () => {await fetchL0(0, query, role, value); setNotice('L0 关联筛选已应用。');});}} options={[{value:'all',label:'全部关联状态'},{value:'linked',label:'已形成 L1'},{value:'unlinked',label:'未形成 L1'}]}/></>}
      </div>
      {tab === 'l1' ? <List loading={busy} dataSource={l1.items} locale={{emptyText: <Empty description="没有符合条件的 L1"/>}} renderItem={item => <List.Item className="memory-item" onClick={() => void openL1(item.id)} actions={[<Button key="open" type="link">查看来源</Button>]}>
        <List.Item.Meta title={<span className="memory-title"><Tag color="magenta">L1</Tag><span>{item.content}{item.truncated ? '…' : ''}</span></span>} description={<span className="memory-meta"><Tag color={item.state === 'active' ? 'green' : 'default'}>{item.state === 'active' ? '当前' : '已退役'}</Tag><span>{displayTime(item.recorded_at)}</span><code>{item.id}</code></span>}/></List.Item>}/>
        : <List loading={busy} dataSource={l0.items} locale={{emptyText: <Empty description="没有符合条件的 L0"/>}} renderItem={item => <List.Item className="memory-item" onClick={() => void openL0(item.id)} actions={[<Button key="open" type="link">查看派生</Button>]}>
          <List.Item.Meta title={<span className="memory-title"><Tag color="blue">L0</Tag><span>{item.content}{item.truncated ? '…' : ''}</span></span>} description={<span className="memory-meta"><Tag>{item.role === 'user' ? '用户' : '助手'}</Tag><Tag color={item.linked_memory_count ? 'green' : 'default'}>{item.linked_memory_count ? `已关联 ${item.linked_memory_count} 条 L1` : '未形成 L1'}</Tag><span>{displayTime(item.created_at)}</span><code>{item.id}</code></span>}/></List.Item>}/>}
      <div className="pagination"><Button disabled={busy || page.offset === 0} onClick={() => void refresh(Math.max(0, page.offset - page.limit))}>上一页</Button><span>{page.total ? `${page.offset + 1}–${Math.min(page.offset + page.limit, page.total)} / ${page.total}` : '0 条'}</span><Button disabled={busy || page.offset + page.limit >= page.total} onClick={() => void refresh(page.offset + page.limit)}>下一页</Button></div>
      </section><p className="memory-status" role="status">{notice}</p>
    </AppShell>
    <Drawer width={620} title="L1 原子记忆" open={Boolean(selectedL1)} onClose={closeL1} extra={<Space><Button disabled={!config?.allow_correction || selectedL1?.state !== 'active'} onClick={() => setCorrecting(true)}>纠正错误</Button><Button disabled={!config?.allow_change || selectedL1?.state !== 'active'} onClick={openChange}>记录变化</Button><Button danger disabled={!config?.allow_delete} onClick={() => setDeleting(true)}>删除</Button></Space>}>
      {selectedL1 && <><p className="detail-content">{selectedL1.content}</p><Descriptions column={1} size="small" items={[{key:'state',label:'层级与状态',children:<Space><Tag color="magenta">L1</Tag><Tag>{selectedL1.state === 'active' ? '当前' : '已退役'}</Tag></Space>},{key:'id',label:'记忆 ID',children:selectedL1.id},{key:'time',label:'系统记录时间',children:displayTime(selectedL1.recorded_at)},{key:'validFrom',label:'事实开始生效',children:displayTime(selectedL1.valid_from)},{key:'validTo',label:'事实结束生效',children:displayTime(selectedL1.valid_to)},{key:'superseded',label:'取代它的记忆',children:selectedL1.superseded_by_id ?? '无'}]}/>
        <h3>L0 原始来源</h3>{selectedL1.sources.length ? selectedL1.sources.map(source => <Card size="small" className="source-card" key={`${source.source_message_id}:${source.source_type}`} title={<Space><Tag color="blue">L0</Tag><span>{sourceName(source.source_type)}</span></Space>}><p>{source.message?.content ?? '原始来源缺失，无法核对原文。'}</p><small>{source.message ? `${source.message.role === 'user' ? '用户' : '助手'} · ${displayTime(source.message.created_at)}` : source.source_message_id}</small></Card>) : <Empty description="这条 L1 没有可用来源，需要核查"/>}</>}
    </Drawer>
    <Drawer width={620} title="L0 原始记录" open={Boolean(selectedL0)} onClose={() => setSelectedL0(undefined)}>
      {selectedL0 && <><p className="detail-content">{selectedL0.content}</p><Descriptions column={1} size="small" items={[{key:'layer',label:'层级',children:<Tag color="blue">L0</Tag>},{key:'role',label:'说话角色',children:selectedL0.role === 'user' ? '用户' : '助手'},{key:'id',label:'消息 ID',children:selectedL0.id},{key:'time',label:'记录时间',children:displayTime(selectedL0.created_at)}]}/>
        <h3>由此派生的 L1</h3>{selectedL0.derived_memories.length ? selectedL0.derived_memories.map(memory => <Card size="small" className="source-card" key={memory.id} title={<Space><Tag color="magenta">L1</Tag><Tag>{memory.state === 'active' ? '当前' : '已退役'}</Tag></Space>}><p>{memory.content}</p><small>{sourceName(memory.source_type)} · {displayTime(memory.linked_at)}</small></Card>) : <Empty description="这条原始记录没有形成 L1"/>}</>}
    </Drawer>
    <Modal title="纠正 L1" open={correcting} okText="确认旧事实有误并保存" cancelText="取消" confirmLoading={busy} okButtonProps={{disabled: !correction.trim()}} onCancel={() => {setCorrecting(false); setCorrection('');}} onOk={() => void saveCorrection()}>
      <p>纠正会新建 L1，并保留旧记录为已取代历史。只用于旧事实本来就错了，不用于后来发生的变化。</p><Input.TextArea aria-label="纠正后的完整事实" rows={4} maxLength={1000} value={correction} onChange={e => setCorrection(e.target.value)} placeholder="输入可独立理解的完整事实"/>
    </Modal>
    <Modal title="记录事实变化" open={changing} okText="确认事实已经变化" cancelText="取消" confirmLoading={busy} okButtonProps={{disabled: !changedContent.trim() || !effectiveLocal}} onCancel={() => {setChanging(false); setChangedContent(''); setEffectiveLocal('');}} onOk={() => void saveChange()}>
      <p>用于“旧事实过去成立，但后来发生了变化”。旧事实会保留到生效时间，新事实从该时间开始生效；不要用它纠正从一开始就错误的记录。</p>
      <Input.TextArea aria-label="变化后的完整事实" rows={4} maxLength={1000} value={changedContent} onChange={e => setChangedContent(e.target.value)} placeholder="输入变化后可独立理解的完整事实"/>
      <label className="field-label" htmlFor="effective-at">变化生效时间</label>
      <Input id="effective-at" aria-label="变化生效时间" type="datetime-local" value={effectiveLocal} onChange={e => setEffectiveLocal(e.target.value)}/>
    </Modal>
    <Modal title="删除这条 L1 记忆？" open={deleting} okText="确认删除 L1" cancelText="取消" confirmLoading={busy} okButtonProps={{danger: true, disabled: !deleteUnderstood}} onCancel={() => {setDeleting(false); setDeleteUnderstood(false);}} onOk={() => void removeMemory()}>
      <p>只删除 L1 及来源关联；L0 原始对话和备份仍然保留，目前没有一键恢复。</p><Checkbox checked={deleteUnderstood} onChange={event => setDeleteUnderstood(event.target.checked)}>我理解以上影响，只删除这一条 L1。</Checkbox>
    </Modal>
  </>;
}
