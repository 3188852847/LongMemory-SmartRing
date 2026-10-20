import {DataWorkspace, useWorkspaceParam} from '../features/data-workspace/DataWorkspace';
import {useUnsavedChanges} from '../app/UnsavedChanges';
import {lazy, Suspense, useEffect, useId, useRef, useState} from 'react';
import {Alert, Button, Card, Checkbox, Descriptions, Drawer, Empty, Input, List, Modal, Select, Space, Switch, Tabs, Tag} from 'antd';
import {Link, useSearchParams} from 'react-router-dom';
import {ApiError, ChatApi, type DailyMemoryFeedback, type MemoryFeedbackKind} from '../api';
import {AppShell, ConsoleNav} from '../components/AppShell';
import {PageHeader} from '../components/PageHeader';
import {ManualMemoryAdd} from '../features/memory/ManualMemoryAdd';
import {memoryFailure, type MemoryFailurePhase} from '../features/memory/memoryFailure';
import {ConsolidationOverview} from '../features/memory/ConsolidationStatusCard';
import {useMemoryEngine,canBrowseLegacyMemory} from '../app/MemoryEngineProvider';
import {HyMemoryWorkspace} from '../features/memory/HyMemoryWorkspace';

type MemoryConfig = {
  representation?: 'method_defined';
  method?: string;
  management_capabilities?: Record<string, boolean>;
  configured: boolean;
  database: string | null;
  allow_delete: boolean;
  allow_clear: boolean;
  allow_correction: boolean;
  allow_change: boolean;
  allow_promote_source: boolean;
  allow_l1_quality_review: boolean;
  semantic_relation_preview_available: boolean;
};
type RuntimeMode = {write_enabled: boolean; use_enabled: boolean; scenario_use_enabled: boolean; scenario_available: boolean; persona_use_enabled: boolean; persona_available: boolean; persistent: boolean; l0_archived_when_write_disabled: boolean};
type L1Summary = {id: string; content: string; truncated: boolean; state: 'active' | 'retired'; effective_state?: 'current'|'expired'|'not_started'|'retired'; recorded_at: string; subject_id: string};
type Source = {source_message_id: string; source_type: string; linked_at: string; message: null | {role: string; content: string; created_at: string}};
type L1Detail = L1Summary & {content: string; revision: string; valid_from: string | null; valid_to: string | null; retired_at: string | null; superseded_by_id: string | null; sources: Source[]};
type L0Summary = {id: string; role: 'user' | 'assistant'; content: string; truncated: boolean; created_at: string; linked_memory_count: number};
type DerivedMemory = {id: string; content: string; state: 'active' | 'retired'; source_type: string; linked_at: string};
type L0Detail = L0Summary & {
  content: string;
  revision: string;
  derived_memories: DerivedMemory[];
};
type Page<T> = {items: T[]; total: number; limit: number; offset: number};
type DailyActivity = 'added'|'corrected'|'changed';
type DailyReviewItem = L1Summary & {activity:DailyActivity};
type DailyDeletion = {id:string;memory_id:string;subject_id:string;deleted_at:string};
type DailyReview = {local_date:string;utc_offset_minutes:number;items:DailyReviewItem[];total:number;limited:boolean;activity_counts:Record<DailyActivity|'deleted',number>;message_counts:{user:number;assistant:number;total:number;unlinked_user:number};quality_counts:{owner_confirmed_missed_extraction:number};deletions:DailyDeletion[];deletions_limited:boolean};
type ClearPreview = {l1_total:number;l1_active:number;l1_retired:number;affected_l2_current:number;affected_l3_current:number;l0_preserved:number;revision:string};
type WipePreview = {l0_total:number;l1_total:number;l2_total:number;l3_total:number;l2_current:number;l3_current:number;related_record_total:number;web_chat_archive_preserved:boolean;existing_backups_preserved:boolean;revision:string};
type L1QualityCandidate = {kind:'normalized_duplicate'|'lexical_near_duplicate'|'possible_conflict';similarity:number;reason:string;left:L1Summary;right:L1Summary;review_status:'pending'|'dismissed';review_revision:number;required_remerge_kept_memory_id:string|null};
type L1MergeEvidence = {source_message_id:string;source_type:string;linked_at:string};
type L1MergeHistory = {id:string;kept_memory_id:string;retired_memory_id:string;candidate_kind:'normalized_duplicate'|'lexical_near_duplicate';copied_evidence_count:number;evidence_ledger_count:number;evidence_ledger_complete:boolean;evidence_ledger:L1MergeEvidence[];merged_at:string;kept_content:string;retired_content:string;state:'merged'|'restored';state_revision:number;state_changed_at:string|null;restore_available:boolean};
type L1QualityCandidates = {items:L1QualityCandidate[];total:number;scanned_memory_count:number;memory_scan_limited:boolean;candidate_limit:number;candidate_limit_reached:boolean;lexical_threshold:number;detector_version:string;generated_at:string;merge_history:L1MergeHistory[];merge_history_total:number;merge_history_limited:boolean};
type SemanticRelation = 'equivalent'|'possible_conflict'|'possible_change'|'compatible'|'uncertain';
type SemanticRelationItem = {pair_id:string;cosine_similarity:number;left:{id:string;content:string;recorded_at:string};right:{id:string;content:string;recorded_at:string};relation:SemanticRelation;reason_code:string;left_quote:string;right_quote:string};
type SemanticRelationPreview = {status:'completed'|'insufficient_memories'|'no_same_subject_pairs';items:SemanticRelationItem[];scanned_memory_count:number;memory_scan_limited:boolean;candidate_limit:number;generated_at:string;pairing_version:string;reviewer_version:string;persistent:false;automatic_actions:false;model_request_count:0|1};
type TemporalHistoryItem = L1Summary & {valid_from:string|null;valid_to:string|null;retired_at:string|null;superseded_by_id:string|null};
type TemporalHistory = {selected_memory_id:string;has_explicit_change:boolean;items:TemporalHistoryItem[]};

const api = new ChatApi();
const HyMechanismsWorkspace=lazy(()=>import('../features/memory/HyMechanismsWorkspace').then(module=>({default:module.HyMechanismsWorkspace})));
const displayTime = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '未记录';
const sourceName = (value: string) => value === 'user_stated' ? '用户陈述' : value === 'user_corrected' ? '用户纠正' : value;
const localDateText = (date=new Date()) => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
const feedbackLabel:Record<MemoryFeedbackKind,string> = {
  memory_ok:'记忆使用正常', recall_miss:'没想起已有记忆',
  wrong_memory:'使用了错误记忆', memory_irrelevant:'回答与记忆无关',
};
const semanticRelationLabel:Record<SemanticRelation,string> = {
  equivalent:'可能等价', possible_conflict:'可能冲突', possible_change:'可能发生变化',
  compatible:'可以并存', uncertain:'证据不足',
};
const semanticRelationColor:Record<SemanticRelation,string> = {
  equivalent:'gold', possible_conflict:'red', possible_change:'blue',
  compatible:'green', uncertain:'default',
};

function DailyFeedbackReview({feedback}:{feedback:DailyMemoryFeedback}) {
  return <section className="daily-feedback-review" aria-label="网页回答记忆复核">
    <h3>网页回答记忆复核</h3>
    <p className="subtle">当天形成 {feedback.current_total} 个当前有效判断，共发生 {feedback.total} 次复核动作。这是内部测试证据，不会自动重答、改写记忆或训练模型。</p>
    <Space wrap>
      <Tag color="green">正常 {feedback.current_counts.memory_ok}</Tag>
      <Tag color="gold">没想起 {feedback.current_counts.recall_miss}</Tag>
      <Tag color="red">错误记忆 {feedback.current_counts.wrong_memory}</Tag>
      <Tag>记忆无关 {feedback.current_counts.memory_irrelevant}</Tag>
    </Space>
    {feedback.current_items.length>0&&<details><summary>回看当前判断（{feedback.current_items.length}）</summary><List size="small" dataSource={feedback.current_items} renderItem={item=><List.Item actions={[<Link key="turn" to={`/chat-react?chat_id=${encodeURIComponent(item.chat_id)}&request_id=${encodeURIComponent(item.request_id)}`}>查看回答与证据</Link>]}><Space direction="vertical" size={0}><span>{feedbackLabel[item.kind]}</span><small className="subtle">{item.chat_title} · {displayTime(item.occurred_at)} · 修订 {item.revision}</small></Space></List.Item>}/>{feedback.current_limited&&<p className="subtle">这一天超过 100 个当前判断，仅显示最近 100 个。</p>}</details>}
    {feedback.total>feedback.current_total&&<details><summary>查看改标历史（{feedback.total-feedback.current_total} 次旧判断）</summary><List size="small" dataSource={feedback.items.filter(item=>!item.is_current)} renderItem={item=><List.Item><Space direction="vertical" size={0}><span>{feedbackLabel[item.kind]}（已被后续标记取代）</span><small className="subtle">{item.chat_title} · {displayTime(item.occurred_at)} · 修订 {item.revision}</small></Space></List.Item>}/>{feedback.limited&&<p className="subtle">复核动作超过 100 次，旧判断可能未完整展开。</p>}</details>}
  </section>;
}

export function MemoryApp() {
  const sourceHeading = useId();
  const [searchParams, setSearchParams] = useSearchParams();
  const mechanismsView=searchParams.get('view')==='mechanisms';
  const [workspace,setWorkspace] = useWorkspaceParam('view','browse',['browse','daily','consolidation','quality','runtime']);
  const engine=useMemoryEngine();
  const legacyManagement=canBrowseLegacyMemory(engine);
  const [config,setConfig]=useState<MemoryConfig>();
  const [mode, setMode] = useState<RuntimeMode>();
  const [modeDraft, setModeDraft] = useState({write_enabled: true, use_enabled: true, scenario_use_enabled: false, persona_use_enabled: false});
  const [tab,setTab] = useWorkspaceParam('layer','l1',['l1','l0']);
  const [appliedQuery,setAppliedQuery] = useWorkspaceParam('q','');
  const [offsetText,setOffset] = useWorkspaceParam('offset','0');
  const browseOffset = /^\d{1,7}$/.test(offsetText)?Math.floor(Number(offsetText)/25)*25:0;
  const [initialized,setInitialized] = useState(false);
  const loadedCoordinate = useRef('');
  const [l1, setL1] = useState<Page<L1Summary>>({items: [], total: 0, limit: 25, offset: 0});
  const [l0, setL0] = useState<Page<L0Summary>>({items: [], total: 0, limit: 25, offset: 0});
  const [l0Loaded, setL0Loaded] = useState(false);
  const [daily,setDaily] = useState<DailyReview>();
  const [dailyFeedback,setDailyFeedback] = useState<DailyMemoryFeedback>();
  const [reviewDate,setReviewDate] = useState(localDateText());
  const [dailyNotice,setDailyNotice] = useState('');
  const [query, setQuery] = useState(appliedQuery);
  useEffect(()=>setQuery(appliedQuery),[appliedQuery]);
  const [l1State, setL1State] = useWorkspaceParam('state','active',['active','retired','all']);
  const [role, setRole] = useWorkspaceParam('role','all',['all','user','assistant']);
  const [linkState, setLinkState] = useWorkspaceParam('link_state','all',['all','linked','unlinked']);
  const [l0Date, setL0Date] = useWorkspaceParam('local_date','');
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
  const [clearing, setClearing] = useState(false);
  const [clearPreview, setClearPreview] = useState<ClearPreview>();
  const [clearPhrase, setClearPhrase] = useState('');
  const [wiping, setWiping] = useState(false);
  const [wipePreview, setWipePreview] = useState<WipePreview>();
  const [wipePhrase, setWipePhrase] = useState('');
  const [wipeNotice, setWipeNotice] = useState('');
  const [promoting, setPromoting] = useState(false);
  const [promotedContent, setPromotedContent] = useState('');
  useUnsavedChanges(Boolean((correcting && correction) || (changing && (changedContent || effectiveLocal))
    || (promoting && promotedContent)
    || (mode && Object.entries(modeDraft).some(([key, value]) => mode[key as keyof typeof modeDraft] !== value))), '有未保存的记忆编辑或运行开关。');
  const [qualityCandidates, setQualityCandidates] = useState<L1QualityCandidates>();
  const [qualityScanning, setQualityScanning] = useState(false);
  const [semanticPreview, setSemanticPreview] = useState<SemanticRelationPreview>();
  const [semanticPreviewing, setSemanticPreviewing] = useState(false);
  const [temporalHistory, setTemporalHistory] = useState<TemporalHistory>();
  const [temporalHistoryOpen, setTemporalHistoryOpen] = useState(false);
  const [mergeChoice, setMergeChoice] = useState<{item:L1QualityCandidate;kept:'left'|'right'}>();
  const [restoreChoice, setRestoreChoice] = useState<L1MergeHistory>();
  const locked = useRef(false);

  async function fetchL1(offset = 0, search = query, stateFilter = l1State) {
    const params = new URLSearchParams({q: search, state: stateFilter, offset: String(offset), limit: '25'});
    const data = await api.request<Page<L1Summary>>(`/api/memories?${params}`);
    setL1(data);
  }
  async function fetchL0(offset = 0, search = query, roleFilter = role, linkFilter = linkState, dateFilter = l0Date) {
    const params = new URLSearchParams({q: search, role: roleFilter, link_state: linkFilter, offset: String(offset), limit: '25'});
    if(dateFilter) {
      params.set('local_date',dateFilter);
      params.set('utc_offset_minutes',String(-new Date().getTimezoneOffset()));
    }
    const data = await api.request<Page<L0Summary>>(`/api/source-messages?${params}`);
    setL0(data); setL0Loaded(true);
  }
  async function fetchDaily(date=reviewDate) {
    const params=new URLSearchParams({local_date:date,utc_offset_minutes:String(-new Date().getTimezoneOffset())});
    try {
      setDaily(await api.request<DailyReview>(`/api/memories/daily-review?${params}`));
      try {
        setDailyFeedback(await api.request<DailyMemoryFeedback>(`/api/chat-memory-feedback/daily?${params}`));
        setDailyNotice('');
      } catch {
        setDailyFeedback(undefined);
        setDailyNotice('当天记忆写入已读取，但网页回答复核暂时无法读取。');
      }
    } catch {
      setDaily(undefined); setDailyFeedback(undefined);
      setDailyNotice('暂时无法读取这一天的回顾；完整 L1 列表仍可正常使用。');
    }
  }
  async function refresh(offset = browseOffset, search = appliedQuery) {
    setBusy(true);
    try {
      if (tab === 'l1') {await fetchL1(offset, search); await fetchDaily();} else await fetchL0(offset, search);
      setNotice('列表已更新。');
    } catch (error) {setNotice(memoryFailure(error, 'read'));}
    finally {setBusy(false);}
  }
  useEffect(() => {
    if(engine.phase!=='ready'||(engine.identity?.state!=='available'&&!legacyManagement)||mechanismsView)return;
    let cancelled=false;
    setConfig(undefined);setInitialized(false);setBusy(true);
    void (async () => {
      try {
        await api.bootstrap();
        const current=await api.request<MemoryConfig>('/api/memory-config');
        if(cancelled)return;
        const agrees=legacyManagement?current.representation!=='method_defined'&&(!current.method||current.method===engine.identity?.method):current.representation==='method_defined'&&current.method===engine.identity?.method;
        if(!agrees){setNotice('管理能力与当前引擎身份不一致，请重新核对后再浏览。');return;}
        setConfig(current);
        if (current.representation === 'method_defined') return;
        if (!current.configured) {setNotice('启动时没有指定记忆库；页面不会自动创建数据库。'); return;}
        // 已指定的旧库可独立浏览；未初始化时不为运行开关懒建聊天Runtime。
        if(engine.identity?.state==='available') try {
          const runtime = await api.request<RuntimeMode>('/api/memory-mode');
          setMode(runtime); setModeDraft({write_enabled: runtime.write_enabled, use_enabled: runtime.use_enabled, scenario_use_enabled: runtime.scenario_use_enabled, persona_use_enabled: runtime.persona_use_enabled});
        } catch {setNotice('记忆库可浏览，但聊天 Runtime 未启用，运行期开关不可用。');}
        else setMode(undefined);
        const params = new URLSearchParams({q: appliedQuery, state: l1State, offset: String(tab==='l1'?browseOffset:0), limit: '25'});
        setL1(await api.request<Page<L1Summary>>(`/api/memories?${params}`));
        // 页签标题必须来自真实查询。L0 尚未读取时不能用初始 state 的 0
        // 冒充数据库统计；同时预载第一页也让首次切换无需再等待空白列表。
        await Promise.all([
          fetchL0(0, '', 'all', 'all', '').catch(() => undefined),
          fetchDaily(),
        ]);
        // L1 已按当前坐标读取，不再立即重复刷新并覆盖深链接的来源提示。
        if (tab === 'l1') loadedCoordinate.current = browseCoordinate;
        setInitialized(true);
        setNotice('记忆已加载；可核对来源或切换任务。');
      } catch (error) {if(!cancelled)setNotice(memoryFailure(error, 'read'));}
      finally {if(!cancelled)setBusy(false);}
    })();
    return ()=>{cancelled=true;};
  }, [engine.identity,engine.phase,mechanismsView,legacyManagement]);


  const browseCoordinate = `${tab}:${appliedQuery}:${l1State}:${role}:${linkState}:${l0Date}:${browseOffset}`;
  useEffect(()=>{
    if(!initialized || engine.phase!=='ready'||!legacyManagement||loadedCoordinate.current===browseCoordinate)return;
    loadedCoordinate.current=browseCoordinate;
    void refresh(browseOffset,appliedQuery);
  },[initialized,browseCoordinate,engine.phase,legacyManagement]);
  useEffect(()=>{
    if(!initialized||engine.phase!=='ready'||!legacyManagement)return;
    const memoryId=searchParams.get('memory_id');
    const sourceId=searchParams.get('l0_message_id');
    if(!memoryId && !sourceId){setSelectedL1(undefined);setSelectedL0(undefined);return;}
    const id=sourceId||memoryId!;
    if(id.length>128 || /[\u0000-\u001f\u007f]/.test(id)){setNotice('记忆链接格式无效；未自动打开详情。');return;}
    let current=true;
    if(sourceId){
      if(selectedL0?.id===sourceId)return;
      setSelectedL1(undefined);
      void api.request<L0Detail>(`/api/source-messages/${encodeURIComponent(id)}`).then(value=>{if(current){setSelectedL0(value);setNotice('已从圆屏质量反馈打开对应用户 L0；可核对原话和派生记忆。');}}).catch(()=>{if(current){setSelectedL0(undefined);setNotice('链接指向的 L0 不存在或已不可用。');}});
    }else{
      if(selectedL1?.id===memoryId)return;
      setSelectedL0(undefined);
      void api.request<L1Detail>(`/api/memories/${encodeURIComponent(id)}`).then(value=>{if(current)setSelectedL1(value);}).catch(()=>{if(current){setSelectedL1(undefined);setNotice('链接指向的 L1 不存在或已不可用。');}});
    }
    return()=>{current=false;};
  },[initialized,searchParams.get('memory_id'),searchParams.get('l0_message_id')]);

  function linkDetail(key:'memory_id'|'l0_message_id',id:string) {
    const next=new URLSearchParams(searchParams);next.delete('memory_id');next.delete('l0_message_id');next.set(key,id);
    setSearchParams(next,{replace:true});
  }
  function closeL1() {
    setSelectedL1(undefined);
    setTemporalHistoryOpen(false);
    setTemporalHistory(undefined);
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
    await guarded(async () => {setSelectedL1(await api.request<L1Detail>(`/api/memories/${encodeURIComponent(id)}`));linkDetail('memory_id',id);});
  }
  async function openTemporalHistory() {
    if (!selectedL1) return;
    await guarded(async()=>{
      const history=await api.request<TemporalHistory>(`/api/memories/${encodeURIComponent(selectedL1.id)}/temporal-history`);
      setTemporalHistory(history);setTemporalHistoryOpen(true);
      setNotice(history.has_explicit_change?'已读取明确事实变化时间线；没有修改记忆。':'这条 L1 没有可证明的事实变化链；纠错和重复合并不会冒充历史。');
    });
  }
  async function scanL1Quality() {
    if (qualityScanning) return;
    setQualityScanning(true);
    try {
      const result = await api.request<L1QualityCandidates>('/api/memories/quality-candidates');
      setQualityCandidates(result);
      setNotice(result.total
        ? `发现 ${result.total} 组需要人工复核的 L1；系统没有自动修改记忆。`
        : '没有发现满足当前保守规则的 L1 重复或显式矛盾。');
    } catch (error) {setNotice(memoryFailure(error, 'read'));}
    finally {setQualityScanning(false);}
  }
  async function reviewL1Quality(item:L1QualityCandidate, action:'dismiss'|'reopen') {
    await guarded(async()=>{
      const result=await api.request<{review_status:'pending'|'dismissed';review_revision:number}>(
        '/api/memories/quality-candidates/reviews','POST',{
          left_memory_id:item.left.id,right_memory_id:item.right.id,
          candidate_kind:item.kind,action,expected_revision:item.review_revision,
        },
      );
      setQualityCandidates(current=>current ? {...current,items:current.items.map(candidate=>
        candidate.left.id===item.left.id&&candidate.right.id===item.right.id&&candidate.kind===item.kind
          ? {...candidate,review_status:result.review_status,review_revision:result.review_revision}
          : candidate)} : current);
      setNotice(action==='dismiss'?'已把这组候选标为误报；两条 L1 均未修改。':'已恢复这组候选，等待再次复核。');
    },'write');
  }
  async function previewSemanticRelations() {
    if (semanticPreviewing) return;
    setSemanticPreviewing(true);
    try {
      const result = await api.request<SemanticRelationPreview>(
        '/api/memories/semantic-relations/preview', 'POST',
      );
      setSemanticPreview(result);
      setNotice(result.status === 'completed'
        ? `语义预览完成：复核了 ${result.items.length} 组候选；没有修改或保存任何记忆。`
        : result.status === 'insufficient_memories'
          ? '当前有效 L1 少于两条，未运行本地编码或模型复核。'
          : '当前 L1 没有同一主体的可配对项，未调用模型。');
    } catch (error) {setNotice(memoryFailure(error, 'read'));}
    finally {setSemanticPreviewing(false);}
  }
  async function mergeL1Quality() {
    if (!mergeChoice) return;
    const {item,kept}=mergeChoice;
    await guarded(async()=>{
      const keptMemory=kept==='left'?item.left:item.right;
      const result=await api.request<{merge_event_id:string;copied_evidence_count:number;reapplied:boolean}>(
        '/api/memories/quality-candidates/merge','POST',{
          left_memory_id:item.left.id,right_memory_id:item.right.id,
          candidate_kind:item.kind,kept_memory_id:keptMemory.id,
          expected_review_revision:item.review_revision,confirm_merge:true,
        },
      );
      setMergeChoice(undefined);
      await fetchL1(0,'','active');
      await scanL1Quality();
      setNotice(`${result.reapplied?'重复 L1 已重新合并':'重复 L1 已合并'}：保留所选事实，另一条已退役；汇入 ${result.copied_evidence_count} 条此前未关联的 L0 来源。`);
      setSelectedL1(await api.request<L1Detail>(`/api/memories/${encodeURIComponent(keptMemory.id)}`));
    },'write');
  }
  async function restoreL1Merge() {
    if (!restoreChoice) return;
    const event=restoreChoice;
    await guarded(async()=>{
      const result=await api.request<{copied_evidence_preserved:number}>(
        '/api/memories/quality-candidates/merges/restore','POST',{
          merge_event_id:event.id,expected_state_revision:event.state_revision,confirm_restore:true,
        },
      );
      setRestoreChoice(undefined);
      await fetchL1(0,'','active');
      await scanL1Quality();
      setNotice(`被合并的 L1 已恢复为当前记忆；保留项上的 ${result.copied_evidence_preserved} 条来源副本继续保留，L2/L3 没有被自动复活。`);
    },'write');
  }
  async function openCorrection(id:string) {
    await guarded(async()=>{
      const detail=await api.request<L1Detail>(`/api/memories/${encodeURIComponent(id)}`);
      setSelectedL1(detail); linkDetail('memory_id',id); setCorrection(''); setCorrecting(true);
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
    await guarded(async () => {setSelectedL0(await api.request<L0Detail>(`/api/source-messages/${encodeURIComponent(id)}`));linkDetail('l0_message_id',id);});
  }
  function closeL0() {
    setSelectedL0(undefined);
    if (searchParams.has('l0_message_id')) {
      const next = new URLSearchParams(searchParams);
      next.delete('l0_message_id');
      setSearchParams(next, {replace: true});
    }
  }
  function switchTab(key:string) {setTab(key);setOffset('0');}
  async function inspectDailyUnlinked() {
    setWorkspace('browse'); setTab('l0'); setQuery(''); setAppliedQuery(''); setOffset('0'); setRole('user'); setLinkState('unlinked'); setL0Date(reviewDate);
    await guarded(async()=>{
      await fetchL0(0,'','user','unlinked',reviewDate);
      setNotice(`${reviewDate} 的未关联用户原话已加载；未形成 L1 不等于一定漏记，请逐条核对。`);
    });
  }
  async function promoteSelectedSource() {
    if (!selectedL0 || !promotedContent.trim()) return;
    await guarded(async () => {
      const result = await api.request<{memory_id: string; created_new_memory: boolean}>(
        `/api/source-messages/${encodeURIComponent(selectedL0.id)}/promote`, 'POST',
        {
          content: promotedContent.trim(),
          revision: selectedL0.revision,
          confirm_promote: true,
        },
      );
      setPromoting(false);
      setPromotedContent('');
      setSelectedL0(undefined);
      await fetchDaily();
      setTab('l1');
      setQuery('');
      setL0Date('');
      await fetchL1(0, '');
      setSelectedL1(await api.request<L1Detail>(`/api/memories/${encodeURIComponent(result.memory_id)}`));
      setNotice(result.created_new_memory
        ? '已从原 L0 补成 L1，并保留原话来源。'
        : '已有相同 L1；已把原 L0 补为额外来源。');
    }, 'write');
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
      setSelectedL1(await api.request<L1Detail>(`/api/memories/${encodeURIComponent(result.new_memory_id)}`));linkDetail('memory_id',result.new_memory_id);
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
      setSelectedL1(await api.request<L1Detail>(`/api/memories/${encodeURIComponent(result.new_memory_id)}`));linkDetail('memory_id',result.new_memory_id);
      setNotice('变化已保存：旧事实保留历史有效期，新事实从指定时间开始生效。');
    }, 'write');
  }
  async function removeMemory() {
    if (!selectedL1) return;
    await guarded(async () => {
      await api.request(`/api/memories/${encodeURIComponent(selectedL1.id)}`, 'DELETE', {revision: selectedL1.revision, confirm_delete: true});
      setDeleting(false); setDeleteUnderstood(false); closeL1();
      await fetchL1(0, query); await fetchDaily(); setNotice('L1 已删除；L0 原始对话仍保留。');
    }, 'write');
  }
  async function openClearMemories() {
    await guarded(async () => {
      const preview = await api.request<ClearPreview>('/api/memories/clear-preview');
      setClearPreview(preview); setClearPhrase(''); setClearing(true);
      setNotice(preview.l1_total
        ? `已核对清空范围：共 ${preview.l1_total} 条 L1。`
        : '当前没有可清空的 L1，L0 原始对话仍然保留。');
    });
  }
  async function clearMemories() {
    if (!clearPreview || clearPhrase !== '清空我的记忆') return;
    await guarded(async () => {
      const result = await api.request<{deleted_l1:number;l0_preserved:number;affected_l2_current:number;affected_l3_current:number}>(
        '/api/memories/clear', 'POST', {revision: clearPreview.revision, confirm_clear: true},
      );
      setClearing(false); setClearPreview(undefined); setClearPhrase('');
      setSelectedL1(undefined); setSelectedL0(undefined); setTab('l1'); setQuery(''); setAppliedQuery(''); setOffset('0'); setL1State('active');
      await fetchL1(0, '', 'active'); await fetchDaily();
      setNotice(`已清空 ${result.deleted_l1} 条 L1；${result.l0_preserved} 条 L0 原始对话仍保留，关联的当前 L2/L3 已停止召回。`);
    }, 'write');
  }
  async function openWipeMemories() {
    await guarded(async () => {
      const preview = await api.request<WipePreview>('/api/memories/wipe-preview');
      setWipePreview(preview); setWipePhrase(''); setWipeNotice(''); setWiping(true);
      setNotice(`已核对当前库：L0 ${preview.l0_total} 条，L1 ${preview.l1_total} 条。尚未删除。`);
    });
  }
  async function wipeMemories() {
    if (!wipePreview || wipePhrase !== '彻底清除当前记忆库' || locked.current) return;
    locked.current = true; setBusy(true); setWipeNotice('正在创建恢复点并清除，请稍候…');
    try {
      const result = await api.request<{l0_total:number;l1_total:number;l2_total:number;l3_total:number;backup:{path:string;sha256:string}}>(
        '/api/memories/wipe', 'POST', {revision: wipePreview.revision, confirm_wipe: true},
      );
      setWiping(false); setWipePreview(undefined); setWipePhrase(''); setWipeNotice('');
      setSelectedL1(undefined); setSelectedL0(undefined); setTab('l1'); setQuery(''); setAppliedQuery(''); setOffset('0'); setL1State('active');
      setL0({items:[], total:0, limit:25, offset:0}); setL0Loaded(true);
      await fetchL1(0, '', 'active'); await fetchDaily();
      setNotice(`已清除当前库的 L0 ${result.l0_total}、L1 ${result.l1_total}、L2 ${result.l2_total}、L3 ${result.l3_total} 条；操作前恢复点已保存。网页会话档案和既有备份未删除。`);
    } catch (error) {
      const message = memoryFailure(error, 'write');
      if (error instanceof ApiError && error.code === 'memory_wipe_changed') {
        try {
          setWipePreview(await api.request<WipePreview>('/api/memories/wipe-preview'));
          setWipePhrase('');
          setWipeNotice('确认期间记忆库新增或改变了记录，本次没有删除。已重新核对数量，请再次输入确认短语。');
        } catch {
          setWipeNotice(message);
        }
      } else {
        setWipeNotice(message);
      }
      setNotice(message);
    } finally {
      locked.current = false; setBusy(false);
    }
  }

  const page = tab === 'l1' ? l1 : l0;
  const configMatches=Boolean(config&&(legacyManagement?config.representation!=='method_defined'&&(!config.method||config.method===engine.identity?.method):config.representation==='method_defined'&&config.method===engine.identity?.method));
  if (mechanismsView) return <Suspense fallback={<p className="page-loading" role="status">正在加载机制视图…</p>}><HyMechanismsWorkspace/></Suspense>;
  if (engine.phase!=='ready'||!config||!configMatches) return <AppShell subtitle="核对当前记忆引擎" className="memory-shell" sidebar={<ConsoleNav active="memories" legacyPath="/memories-legacy"/>}><PageHeader eyebrow="长期记忆" title="我的记忆" description={engine.phase==='ready'?'此页面不会为浏览而初始化引擎或打开未指定的库。':'正在确认当前引擎与管理能力。'}/><Alert type={busy?'info':'error'} showIcon title={engine.phase==='error'?'无法核对当前记忆引擎':engine.kind==='uninitialized'?'记忆已配置，尚未初始化':engine.kind==='unconfigured'?'尚未配置记忆引擎':notice} action={engine.phase==='error'?<Button onClick={engine.refresh} loading={engine.refreshing}>重新核对引擎</Button>:undefined}/></AppShell>;
  if (config.representation === 'method_defined') return <HyMemoryWorkspace api={api} method={config.method} capabilities={config.management_capabilities}/>;
  const sidebar = <>
      <ConsoleNav active="memories" legacyPath="/memories-legacy"/>
      <Card size="small" className="memory-layer-guide" title="层级说明"><p><Tag color="magenta">L1</Tag><span>规范化、可召回的派生事实</span></p><p><Tag color="blue">L0</Tag><span>用户或助手当时说过的原文</span></p></Card>
    </>;
  return <><AppShell subtitle="可追溯的个人记忆" className="memory-shell" sidebar={sidebar}><PageHeader eyebrow="长期记忆" title="原话与事实" description="查看系统保存的原话和从中提取的可召回事实，并核对两者之间的来源关系。" meta={config?.database ?? '未指定记忆库'} action={<Space wrap><ManualMemoryAdd api={api} disabled={!config?.configured || !mode} onSaved={async memoryId => {await fetchL1(0, ''); setTab('l1'); setQuery(''); setAppliedQuery(''); setOffset('0'); setWorkspace('browse'); setNotice('明确事实已处理，列表已更新。'); if (memoryId) await openL1(memoryId);}}/><Button danger disabled={busy || !config?.allow_clear} onClick={() => void openClearMemories()}>重置长期记忆</Button><Button danger disabled={busy || !config?.allow_clear} onClick={() => void openWipeMemories()}>清除 L0–L3</Button><Button loading={busy} disabled={!config?.configured} onClick={() => void refresh(page.offset)}>刷新</Button></Space>}/>
    <DataWorkspace label="记忆工作区" activeKey={workspace} onChange={setWorkspace} items={[
      {key:'browse',label:'浏览记忆',children:<>      <section className="memory-overview" aria-label="记忆概览"><div><small>当前视图</small><strong>{tab === 'l1' ? '事实记忆（L1）' : '对话原话（L0）'}</strong></div><div><small>记录数</small><strong>{page.total}</strong></div><div><small>回答时召回</small><strong className={mode?.use_enabled ? 'is-positive' : ''}>{mode?.use_enabled ? '已开启' : '已关闭'}</strong></div></section>
      <section className="memory-browser"><Tabs activeKey={tab} onChange={switchTab} items={[{key: 'l1', label: `事实记忆（L1） · ${l1.total}`}, {key: 'l0', label: `对话原话（L0） · ${l0Loaded ? l0.total : '—'}`}]}/>
      <div className="memory-toolbar"><Input.Search aria-label="搜索当前层级" value={query} maxLength={200} allowClear disabled={busy || !config?.configured} placeholder={tab === 'l1' ? '搜索原子事实' : '搜索原始对话'} onChange={e => setQuery(e.target.value)} onSearch={value=>{setAppliedQuery(value.trim());setOffset('0');if(value.trim()===appliedQuery && browseOffset===0)void refresh(0,value.trim());}}/>
        {tab === 'l1' ? <Select aria-label="L1 状态" value={l1State} disabled={busy || !config?.configured} onChange={value => {setL1State(value);setOffset('0');}} options={[{value:'active',label:'当前记忆'},{value:'retired',label:'已退役'},{value:'all',label:'全部 L1'}]}/>
          : <><Select aria-label="L0 角色" value={role} disabled={busy || !config?.configured} onChange={value => {setRole(value);setOffset('0');}} options={[{value:'all',label:'全部角色'},{value:'user',label:'用户原话'},{value:'assistant',label:'助手原话'}]}/>
            <Select aria-label="L1 关联" value={linkState} disabled={busy || !config?.configured} onChange={value => {setLinkState(value);setOffset('0');}} options={[{value:'all',label:'全部关联状态'},{value:'linked',label:'已形成 L1'},{value:'unlinked',label:'未形成 L1'}]}/>
            <Input aria-label="L0 日期" type="date" value={l0Date} disabled={busy || !config?.configured} onChange={event=>{const value=event.target.value;setL0Date(value);setOffset('0');}}/></>}
      </div>
      {tab === 'l1' ? <List loading={busy} dataSource={l1.items} locale={{emptyText: <Empty description="没有符合条件的 L1"/>}} renderItem={item => <List.Item className="memory-item" onClick={() => void openL1(item.id)} actions={[<Button key="open" type="link" onClick={event=>{event.stopPropagation();void openL1(item.id);}}>查看来源</Button>]}>
        <List.Item.Meta title={<span className="memory-title"><Tag color="magenta">L1</Tag><span>{item.content}{item.truncated ? '…' : ''}</span></span>} description={<span className="memory-meta"><Tag color={item.effective_state === 'expired' ? 'gold' : item.effective_state === 'not_started' ? 'blue' : item.state === 'active' ? 'green' : 'default'}>{item.effective_state === 'expired' ? '已到期' : item.effective_state === 'not_started' ? '未生效' : item.state === 'active' ? '当前' : '已退役'}</Tag><span>{displayTime(item.recorded_at)}</span><code>{item.id}</code></span>}/></List.Item>}/>
        : <List loading={busy} dataSource={l0.items} locale={{emptyText: <Empty description="没有符合条件的 L0"/>}} renderItem={item => <List.Item className="memory-item" onClick={() => void openL0(item.id)} actions={[<Button key="open" type="link" onClick={event=>{event.stopPropagation();void openL0(item.id);}}>查看派生</Button>]}>
          <List.Item.Meta title={<span className="memory-title"><Tag color="blue">L0</Tag><span>{item.content}{item.truncated ? '…' : ''}</span></span>} description={<span className="memory-meta"><Tag>{item.role === 'user' ? '用户' : '助手'}</Tag><Tag color={item.linked_memory_count ? 'green' : 'default'}>{item.linked_memory_count ? `已关联 ${item.linked_memory_count} 条 L1` : '未形成 L1'}</Tag><span>{displayTime(item.created_at)}</span><code>{item.id}</code></span>}/></List.Item>}/>}
      <div className="pagination"><Button disabled={busy || page.offset === 0} onClick={()=>setOffset(String(Math.max(0,page.offset-page.limit)))}>上一页</Button><span>{page.total ? `${page.offset + 1}–${Math.min(page.offset + page.limit, page.total)} / ${page.total}` : '0 条'}</span><Button disabled={busy || page.offset + page.limit >= page.total} onClick={()=>setOffset(String(page.offset+page.limit))}>下一页</Button></div>
      </section>
</>},
      {key:'daily',label:'每日回顾',children:<>      <Card className="mode-card" title={`每日记忆回顾 · ${reviewDate}`} extra={<Space wrap><Button size="small" onClick={previousReviewDate}>前一天</Button><Input aria-label="回顾日期" type="date" max={localDateText()} value={reviewDate} onChange={event=>changeReviewDate(event.target.value)} style={{width:145}}/><Button size="small" disabled={reviewDate===localDateText()} onClick={()=>changeReviewDate(localDateText())}>今天</Button>{daily&&<Tag color={daily.total?'processing':'default'}>{daily.total} 条写入</Tag>}</Space>}>
        <p className="subtle">这里按你的本地自然日显示当天形成的 L1，包括后来被纠正或取代的记录；它不是“当前有效记忆”总表，也不会触发模型整理。</p>
        {dailyNotice&&<p role="status" className="subtle">{dailyNotice}</p>}
        {daily&&<>
        <p className="subtle">当天归档 L0：用户 {daily.message_counts.user} 条，助手 {daily.message_counts.assistant} 条；其中 {daily.message_counts.unlinked_user} 条用户原话没有形成 L1。这里只是原始记录计数，不代表会话轮数、内容总结或漏记结论。</p>
        <p className="subtle">当天所有者确认漏记 {daily.quality_counts.owner_confirmed_missed_extraction} 条。该数字来自显式“补成 L1”操作，不是模型自评或对未关联原话的推测。</p>
        {dailyFeedback&&<DailyFeedbackReview feedback={dailyFeedback}/>}
        {daily.message_counts.unlinked_user>0&&<Button size="small" onClick={()=>void inspectDailyUnlinked()}>核对当天未形成 L1 的原话</Button>}
        <Space wrap><Tag>新增 {daily.activity_counts.added}</Tag><Tag color="gold">纠正 {daily.activity_counts.corrected}</Tag><Tag color="blue">事实变化 {daily.activity_counts.changed}</Tag><Tag color="red">删除 {daily.activity_counts.deleted}</Tag></Space>
        {daily.items.length?<List size="small" dataSource={daily.items.slice(0,5)} renderItem={item=><List.Item actions={[<Button type="link" key="review" onClick={()=>void openL1(item.id)}>核对来源</Button>]}>
          <List.Item.Meta title={item.content} description={<Space wrap><Tag color={item.activity==='corrected'?'gold':item.activity==='changed'?'blue':'default'}>{item.activity==='corrected'?'纠正':item.activity==='changed'?'事实变化':'新增'}</Tag><Tag color={item.state==='active'?'green':'default'}>{item.state==='active'?'当前':'已退役'}</Tag><span>{displayTime(item.recorded_at)}</span>{item.state==='active'&&config?.allow_correction&&<Button type="link" size="small" onClick={event=>{event.stopPropagation();void openCorrection(item.id);}}>直接纠正</Button>}</Space>}/>
        </List.Item>}/>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="这一天没有形成 L1"/>}
        {daily.total>5&&<p className="subtle">这里只展开最近 5 条；下方 L1 列表可查看全部。{daily.limited?'今日记录达到 100 条读取上限。':''}</p>}
        {daily.deletions.length>0&&<details><summary>查看删除审计（{daily.deletions.length}）</summary><List size="small" dataSource={daily.deletions} renderItem={event=><List.Item><Space direction="vertical" size={0}><span>已删除 L1：<code>{event.memory_id}</code></span><small className="subtle">{displayTime(event.deleted_at)} · 不保留被删正文</small></Space></List.Item>}/>{daily.deletions_limited&&<p className="subtle">删除审计超过 100 条，这里只显示最近记录。</p>}</details>}
        </>}
      </Card>
</>},
      {key:'consolidation',label:'整理状态',children:<>      <ConsolidationOverview enabled={config?.configured === true}/>
</>},
      {key:'quality',label:'重复与关系复核',children:<>      <Card className="mode-card l1-quality-card" title="L1 质量候选" extra={<Button size="small" loading={qualityScanning} disabled={!config?.configured} onClick={() => void scanL1Quality()}>{qualityCandidates ? '重新扫描' : '扫描当前 L1'}</Button>}>
        <p className="subtle">本地只读检查当前有效 L1，寻找规范化重复、高字面重合和明确肯定/否定冲突。相似度是字符片段重合，不是事实置信度；扫描不会调用模型或修改记忆。</p>
        {!qualityCandidates ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未扫描"/> : qualityCandidates.items.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={`已检查 ${qualityCandidates.scanned_memory_count} 条当前 L1，未发现候选`}/> : <>
          <Space wrap><Tag color="gold">待复核 {qualityCandidates.total} 组</Tag><Tag>已检查 {qualityCandidates.scanned_memory_count} 条</Tag>{qualityCandidates.memory_scan_limited&&<Tag color="red">只检查前 500 条</Tag>}{qualityCandidates.candidate_limit_reached&&<Tag color="red">候选达到 {qualityCandidates.candidate_limit} 组上限</Tag>}</Space>
          <List size="small" dataSource={qualityCandidates.items} renderItem={item => <List.Item className="quality-candidate-item">
            <Space direction="vertical" size={6} className="quality-candidate-body">
              <Space wrap><Tag color={item.kind==='possible_conflict'?'red':item.kind==='normalized_duplicate'?'gold':'blue'}>{item.kind==='possible_conflict'?'可能矛盾':item.kind==='normalized_duplicate'?'规范化重复':'高字面重合'}</Tag><span>{item.reason}</span><code>重合 {Math.round(item.similarity*100)}%</code></Space>
              <div className="quality-candidate-pair"><Button type="text" onClick={()=>void openL1(item.left.id)}><Tag color="magenta">A</Tag>{item.left.content}</Button><Button type="text" onClick={()=>void openL1(item.right.id)}><Tag color="magenta">B</Tag>{item.right.content}</Button></div>
              <Space wrap><small className="subtle">请分别核对原始来源；矛盾候选应使用“纠正错误”或“记录变化”，不能当成重复合并。</small><Button size="small" disabled={!config?.allow_l1_quality_review||busy} onClick={()=>void reviewL1Quality(item,item.review_status==='dismissed'?'reopen':'dismiss')}>{item.review_status==='dismissed'?'恢复候选':'标为误报'}</Button>{item.kind!=='possible_conflict'&&item.review_status==='pending'&&<><Button size="small" disabled={Boolean(item.required_remerge_kept_memory_id&&item.required_remerge_kept_memory_id!==item.left.id)} onClick={()=>setMergeChoice({item,kept:'left'})}>{item.required_remerge_kept_memory_id===item.left.id?'重新保留 A，合并 B':'保留 A，合并 B'}</Button><Button size="small" disabled={Boolean(item.required_remerge_kept_memory_id&&item.required_remerge_kept_memory_id!==item.right.id)} onClick={()=>setMergeChoice({item,kept:'right'})}>{item.required_remerge_kept_memory_id===item.right.id?'重新保留 B，合并 A':'保留 B，合并 A'}</Button></>}{item.required_remerge_kept_memory_id&&<Tag color="blue">恢复后的候选只能按原方向重新合并</Tag>}{item.review_status==='dismissed'&&<Tag>已忽略</Tag>}</Space>
            </Space>
          </List.Item>}/>
        </>}
        {qualityCandidates&&qualityCandidates.merge_history.length>0&&<details className="quality-merge-history"><summary>查看重复合并历史（{qualityCandidates.merge_history_total}）</summary><List size="small" dataSource={qualityCandidates.merge_history} renderItem={event=><List.Item actions={event.restore_available?[<Button key="restore" size="small" onClick={()=>setRestoreChoice(event)}>恢复被合并项</Button>]:undefined}><Space direction="vertical" size={2}><Space wrap><Tag color={event.state==='merged'?'green':'blue'}>{event.state==='merged'?'合并生效中':'已恢复'}</Tag><span><Button type="link" size="small" onClick={()=>void openL1(event.kept_memory_id)}>保留：{event.kept_content}</Button></span></Space><span className="subtle">{event.state==='merged'?'已取代':'曾取代'}：{event.retired_content}</span><small className="subtle">首次合并 {displayTime(event.merged_at)} · 当前状态修订 {event.state_revision}{event.state_changed_at?` · 状态更新 ${displayTime(event.state_changed_at)}`:''} · 汇入 {event.copied_evidence_count} 条来源 · {event.evidence_ledger_complete?`账本完整 ${event.evidence_ledger_count}/${event.copied_evidence_count}`:'旧合并无逐条账本'}</small>{event.evidence_ledger.length>0&&<Space wrap size={4}>{event.evidence_ledger.map(source=><Button key={`${source.source_message_id}:${source.source_type}`} type="link" size="small" onClick={()=>void openL0(source.source_message_id)}>L0 {source.source_message_id.slice(0,8)} · {sourceName(source.source_type)} · {displayTime(source.linked_at)}</Button>)}</Space>}</Space></List.Item>}/>{qualityCandidates.merge_history_limited&&<p className="subtle">这里只显示最近 25 次合并。</p>}</details>}
      </Card>
      <Card className="mode-card l1-quality-card" title={<span>语义关系实验预览 <Tag>不保存</Tag></span>} extra={<Button size="small" loading={semanticPreviewing} disabled={!config?.semantic_relation_preview_available} onClick={() => void previewSemanticRelations()}>{semanticPreview ? '重新运行' : '运行一次预览'}</Button>}>
        <p className="subtle">仅在点击后读取最多 500 条当前有效 L1：本地 BGE 选出最多 20 对，再用当前兼容模型单次复核。分数只代表语义接近程度；模型结果不会写入数据库，也不会自动纠正、合并、取代或删除。</p>
        {!config?.semantic_relation_preview_available&&<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="需要以兼容模型 + 本地 BGE 混合召回模式启动控制台"/>}
        {config?.semantic_relation_preview_available&&!semanticPreview&&<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未运行；打开页面不会自动调用模型"/>}
        {semanticPreview&&semanticPreview.status!=='completed'&&<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={semanticPreview.status==='insufficient_memories'?'当前有效 L1 少于两条':'没有同一主体的可配对记忆'}/>}
        {semanticPreview?.status==='completed'&&<>
          <Space wrap><Tag color="blue">临时复核 {semanticPreview.items.length} 组</Tag><Tag>扫描 {semanticPreview.scanned_memory_count} 条 L1</Tag><Tag>模型请求 {semanticPreview.model_request_count} 次</Tag>{semanticPreview.memory_scan_limited&&<Tag color="red">只读取前 500 条</Tag>}</Space>
          <List size="small" dataSource={semanticPreview.items} renderItem={item=><List.Item className="quality-candidate-item"><Space direction="vertical" size={6} className="quality-candidate-body">
            <Space wrap><Tag color={semanticRelationColor[item.relation]}>{semanticRelationLabel[item.relation]}</Tag><code>语义接近 {Math.round(item.cosine_similarity*100)}%</code><small className="subtle">{item.reason_code}</small></Space>
            <div className="quality-candidate-pair"><Button type="text" onClick={()=>void openL1(item.left.id)}><Tag color="magenta">A</Tag>{item.left.content}</Button><Button type="text" onClick={()=>void openL1(item.right.id)}><Tag color="magenta">B</Tag>{item.right.content}</Button></div>
            <small className="subtle">模型引用：A「{item.left_quote}」 · B「{item.right_quote}」</small>
          </Space></List.Item>}/>
          <p className="subtle">生成于 {displayTime(semanticPreview.generated_at)}；刷新页面后结果消失。若要处理候选，请另行核对 L0 来源后使用现有人工操作。</p>
        </>}
      </Card>
</>},
      {key:'runtime',label:'记忆开关',children:<>      {mode && <Card className="mode-card" title={<span>本次运行的记忆模式 <Tag>临时设置</Tag></span>} extra={<Button type="primary" disabled={busy || (mode.write_enabled === modeDraft.write_enabled && mode.use_enabled === modeDraft.use_enabled && mode.scenario_use_enabled === modeDraft.scenario_use_enabled && mode.persona_use_enabled === modeDraft.persona_use_enabled)} onClick={() => void saveMode()}>应用到网页与圆屏</Button>}>
        <div className="memory-mode-grid">
          <label><Switch checked={modeDraft.write_enabled} disabled={busy} onChange={value => setModeDraft({...modeDraft, write_enabled: value})}/><span><strong>生成 L1</strong><small>从新对话提取原子记忆</small></span></label>
          <label><Switch checked={modeDraft.use_enabled} disabled={busy} onChange={value => setModeDraft({...modeDraft, use_enabled: value})}/><span><strong>使用 L1</strong><small>回答时召回已有事实</small></span></label>
          <label><Switch checked={modeDraft.scenario_use_enabled} disabled={busy || !mode.scenario_available} onChange={value => setModeDraft({...modeDraft, scenario_use_enabled: value})}/><span><strong>使用 L2</strong><small>注入已接受生活场景</small></span></label>
          <label><Switch checked={modeDraft.persona_use_enabled} disabled={busy || !mode.persona_available} onChange={value => setModeDraft({...modeDraft, persona_use_enabled: value})}/><span><strong>使用 L3</strong><small>注入已接受用户画像</small></span></label>
        </div><p className="subtle">关闭 L1 写入仍保留 L0。L2/L3 只使用当前有效且与问题相关的内容，设置在服务重启后恢复默认。</p></Card>}

</>},
    ]}/>
    <p className="memory-status" role="status">{notice}</p>
    </AppShell>
    <Drawer aria-labelledby={sourceHeading} className="memory-source-drawer" width={620} title={<span id={sourceHeading}>事实记忆（L1）</span>} open={Boolean(selectedL1)} onClose={closeL1} extra={<Space wrap><Button onClick={()=>void openTemporalHistory()}>事实时间线</Button><Button disabled={!config?.allow_correction || selectedL1?.state !== 'active'} onClick={() => setCorrecting(true)}>纠正错误</Button><Button disabled={!config?.allow_change || selectedL1?.state !== 'active'} onClick={openChange}>记录变化</Button><Button danger disabled={!config?.allow_delete} onClick={() => setDeleting(true)}>删除</Button></Space>}>
      {selectedL1 && <><p className="detail-content">{selectedL1.content}</p><Descriptions column={1} size="small" items={[{key:'state',label:'层级与状态',children:<Space><Tag color="magenta">L1</Tag><Tag>{selectedL1.effective_state === 'expired' ? '已到期' : selectedL1.effective_state === 'not_started' ? '未生效' : selectedL1.state === 'active' ? '当前' : '已退役'}</Tag></Space>},{key:'id',label:'记忆 ID',children:selectedL1.id},{key:'time',label:'系统记录时间',children:displayTime(selectedL1.recorded_at)},{key:'validFrom',label:'事实开始生效',children:displayTime(selectedL1.valid_from)},{key:'validTo',label:'事实结束生效',children:displayTime(selectedL1.valid_to)},{key:'superseded',label:'取代它的记忆',children:selectedL1.superseded_by_id ?? '无'}]}/>
        <h3>L0 原始来源</h3>{selectedL1.sources.length ? selectedL1.sources.map(source => <Card size="small" className="source-card" key={`${source.source_message_id}:${source.source_type}`} title={<Space><Tag color="blue">L0</Tag><span>{sourceName(source.source_type)}</span></Space>}><p>{source.message?.content ?? '原始来源缺失，无法核对原文。'}</p><small>{source.message ? `${source.message.role === 'user' ? '用户' : '助手'} · ${displayTime(source.message.created_at)}` : source.source_message_id}</small></Card>) : <Empty description="这条 L1 没有可用来源，需要核查"/>}</>}
    </Drawer>
    <Modal title="事实变化时间线" open={temporalHistoryOpen} footer={null} onCancel={()=>setTemporalHistoryOpen(false)}>
      {temporalHistory&&!temporalHistory.has_explicit_change?<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有明确的事实变化链；这可能是独立事实、纠错或重复合并"/>:temporalHistory&&<>
        <p className="subtle">只展示由“记录变化”形成且时间边界精确衔接的历史，不按系统记录先后猜测现实顺序。</p>
        <List dataSource={temporalHistory.items} renderItem={(item,index)=><List.Item><Space direction="vertical" size={2}>
          <Space wrap><Tag color={item.id===temporalHistory.selected_memory_id?'blue':'default'}>{item.id===temporalHistory.selected_memory_id?'当前查看':'链上记录'}</Tag><strong>{item.content}</strong></Space>
          <small className="subtle">{item.valid_from?`从 ${displayTime(item.valid_from)} 生效`:'开始时间未记录'} · {item.valid_to?`到 ${displayTime(item.valid_to)} 结束`:'目前仍有效'} · 第 {index+1}/{temporalHistory.items.length} 段</small>
        </Space></List.Item>}/>
      </>}
    </Modal>
    <Drawer
      width={620}
      title="对话原话（L0）"
      open={Boolean(selectedL0)}
      onClose={closeL0}
      extra={<Button
        disabled={!config?.allow_promote_source || selectedL0?.role !== 'user' || Boolean(selectedL0?.derived_memories.length)}
        onClick={() => {setPromotedContent(''); setPromoting(true);}}
      >补成 L1</Button>}
    >
      {selectedL0 && <><p className="detail-content">{selectedL0.content}</p><Descriptions column={1} size="small" items={[{key:'layer',label:'层级',children:<Tag color="blue">L0</Tag>},{key:'role',label:'说话角色',children:selectedL0.role === 'user' ? '用户' : '助手'},{key:'id',label:'消息 ID',children:selectedL0.id},{key:'time',label:'记录时间',children:displayTime(selectedL0.created_at)}]}/>
        <h3>由此派生的 L1</h3>{selectedL0.derived_memories.length ? selectedL0.derived_memories.map(memory => <Card size="small" className="source-card" key={memory.id} title={<Space><Tag color="magenta">L1</Tag><Tag>{memory.state === 'active' ? '当前' : '已退役'}</Tag></Space>}><p>{memory.content}</p><small>{sourceName(memory.source_type)} · {displayTime(memory.linked_at)}</small></Card>) : <Empty description="这条原始记录没有形成 L1"/>}</>}
    </Drawer>
    <Modal title="把这条原话补成 L1？" open={promoting} okText="确认补成 L1" cancelText="取消" confirmLoading={busy} okButtonProps={{disabled: !promotedContent.trim()}} onCancel={() => {if (!busy) {setPromoting(false); setPromotedContent('');}}} onOk={() => void promoteSelectedSource()}>
      <p>系统会继续引用当前 L0 原话，不会复制对话，也不会调用模型。若已有内容完全相同的当前 L1，只增加这条来源。</p>
      <p className="subtle">请把原话整理为一条可独立理解、以“用户”作主体的完整事实；不要把问题、寒暄或助手推测补成用户事实。</p>
      <Input.TextArea aria-label="补记后的完整 L1" rows={4} maxLength={1000} showCount value={promotedContent} onChange={event => setPromotedContent(event.target.value)} placeholder="例如：用户最近开始每天晨跑。"/>
    </Modal>
    <Modal title="纠正 L1" open={correcting} okText="确认旧事实有误并保存" cancelText="取消" confirmLoading={busy} okButtonProps={{disabled: !correction.trim()}} onCancel={() => {setCorrecting(false); setCorrection('');}} onOk={() => void saveCorrection()}>
      <p>纠正会新建 L1，并保留旧记录为已取代历史。只用于旧事实本来就错了，不用于后来发生的变化。</p><Input.TextArea aria-label="纠正后的完整事实" rows={4} maxLength={1000} value={correction} onChange={e => setCorrection(e.target.value)} placeholder="输入可独立理解的完整事实"/>
    </Modal>
    <Modal title="确认合并这两条重复 L1？" open={Boolean(mergeChoice)} okText="确认合并" cancelText="取消" confirmLoading={busy} okButtonProps={{danger:true}} onCancel={()=>{if(!busy)setMergeChoice(undefined);}} onOk={()=>void mergeL1Quality()}>
      {mergeChoice&&<><p>将保留：<strong>{mergeChoice.kept==='left'?mergeChoice.item.left.content:mergeChoice.item.right.content}</strong></p><p>另一条不会物理删除，而是标记为“已由保留项取代”；它的 L0 来源会同时关联到保留项。</p><p className="subtle">依赖被合并项的当前 L2/L3 会按既有来源规则变为失效，等待以后重新整理。合并历史会留下审计记录，可以从历史中恢复。</p></>}
    </Modal>
    <Modal title="恢复这条被合并的 L1？" open={Boolean(restoreChoice)} okText="确认恢复" cancelText="取消" confirmLoading={busy} onCancel={()=>{if(!busy)setRestoreChoice(undefined);}} onOk={()=>void restoreL1Merge()}>
      {restoreChoice&&<><p>将重新启用：<strong>{restoreChoice.retired_content}</strong></p><p>恢复不会删除已经汇入“{restoreChoice.kept_content}”的 L0 来源副本，避免破坏之后形成的溯源关系。</p><p className="subtle">此前因合并而失效的 L2/L3 不会自动复活；恢复后若确认仍属重复，只能按原来的保留方向再次合并。</p></>}
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
    <Modal title="重置长期记忆并保留原话？" open={clearing} okText="删除全部 L1" cancelText="取消" confirmLoading={busy}
      okButtonProps={{danger:true,disabled:!clearPreview?.l1_total || clearPhrase !== '清空我的记忆'}}
      onCancel={() => {if (!busy) {setClearing(false); setClearPreview(undefined); setClearPhrase('');}}}
      onOk={() => void clearMemories()}>
      <p>这是一项开发期重置操作，会删除当前和已退役的全部 事实记忆（L1）。依赖这些事实的当前 L2 场景和 L3 用户画像会变为失效，不再参与回答。</p>
      {clearPreview&&<Descriptions column={1} size="small" items={[
        {key:'l1',label:'将删除的 L1',children:`${clearPreview.l1_total} 条（当前 ${clearPreview.l1_active}，已退役 ${clearPreview.l1_retired}）`},
        {key:'l2',label:'将失效的当前 L2',children:`${clearPreview.affected_l2_current} 条`},
        {key:'l3',label:'将失效的当前 L3',children:`${clearPreview.affected_l3_current} 条`},
        {key:'l0',label:'保留的 L0 原话',children:`${clearPreview.l0_preserved} 条`},
      ]}/>}
      <p className="subtle">L0 原始对话和删除审计会保留，因此这不是“清除所有隐私数据”。控制台目前不提供一键恢复。</p>
      <label className="field-label" htmlFor="clear-memory-phrase">请输入“清空我的记忆”确认</label>
      <Input id="clear-memory-phrase" aria-label="清空确认短语" autoComplete="off" value={clearPhrase} onChange={event=>setClearPhrase(event.target.value)}/>
    </Modal>
    <Modal title="清除当前记忆库中的 L0–L3？" open={wiping} okText="清除当前库" cancelText="取消" confirmLoading={busy}
      okButtonProps={{danger:true,disabled:!wipePreview || wipePhrase !== '彻底清除当前记忆库'}}
      onCancel={() => {if (!busy) {setWiping(false); setWipePreview(undefined); setWipePhrase(''); setWipeNotice('');}}}
      onOk={() => void wipeMemories()}>
      <p>这会清除当前 SQLite 记忆库中的原始对话、原子记忆、场景、用户画像，以及依赖它们的圆屏回答证据和陪伴学习记录。清除后系统不能再从当前库的 L0 重新提取这些内容。</p>
      {wipePreview&&<Descriptions column={1} size="small" items={[
        {key:'l0',label:'将删除的 L0',children:`${wipePreview.l0_total} 条`},
        {key:'l1',label:'将删除的 L1',children:`${wipePreview.l1_total} 条`},
        {key:'l2',label:'将删除的 L2',children:`${wipePreview.l2_total} 条（当前 ${wipePreview.l2_current}）`},
        {key:'l3',label:'将删除的 L3',children:`${wipePreview.l3_total} 条（当前 ${wipePreview.l3_current}）`},
        {key:'related',label:'相关派生与审计记录',children:`${wipePreview.related_record_total} 条`},
      ]}/>}
      <p className="subtle">模型、声音和主动交流规则等产品设置会保留。系统会先创建一致性恢复点；网页聊天会话旁库和所有既有备份不会删除，所以这不是磁盘级隐私擦除。</p>
      {wipeNotice&&<Alert showIcon type={wipeNotice.startsWith('正在')?'info':'error'} message={wipeNotice}/>}
      <label className="field-label" htmlFor="wipe-memory-phrase">请输入“彻底清除当前记忆库”确认</label>
      <Input id="wipe-memory-phrase" aria-label="彻底清除确认短语" autoComplete="off" value={wipePhrase} onChange={event=>setWipePhrase(event.target.value)}/>
    </Modal>
  </>;
}
