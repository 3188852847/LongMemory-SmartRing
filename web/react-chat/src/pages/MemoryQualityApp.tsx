import {DataWorkspace, useWorkspaceParam} from '../features/data-workspace/DataWorkspace';
import {useUnsavedChanges} from '../app/UnsavedChanges';
import {useEffect, useRef, useState} from 'react';
import {Alert, Button, Card, Checkbox, Descriptions, Drawer, Empty, List, Modal, Select, Space, Statistic, Tag} from 'antd';
import {Link} from 'react-router-dom';
import {ChatApi, type L1ExtractionAuditPage, type L1ExtractionOutcome, type L1SufficiencyPolicyMetrics, type L1SufficiencyShadowDetail, type L1SufficiencyShadowPage, type L2SufficiencyShadowDetail, type L2SufficiencyShadowPage, type L2SufficiencyShadowVerdict, type MemoryFeedbackDiagnosticFocus, type MemoryFeedbackIndex, type MemoryFeedbackIndexItem, type MemoryFeedbackKind, type RoundScreenFeedbackDetail} from '../api';
import {AppShell, ConsoleNav} from '../components/AppShell';
import {PageHeader} from '../components/PageHeader';

const api = new ChatApi();
type Filter = MemoryFeedbackIndex['kind'];

const kindLabel:Record<MemoryFeedbackKind,string> = {
  memory_ok:'记忆使用正常', recall_miss:'没想起已有记忆',
  wrong_memory:'使用了错误记忆', memory_irrelevant:'回答与记忆无关',
};
const focusLabel:Record<MemoryFeedbackDiagnosticFocus,string> = {
  normal_control:'正常对照样本；用于和问题样本比较。',
  negative_control:'不需要记忆的负例；不要计作记忆故障。',
  retrieval:'没有召回 L1/L2/L3，优先核对检索查询和候选覆盖。',
  context_or_answer_use:'已有记忆进入轨迹，优先核对注入预算和回答是否采用证据。',
  memory_content_freshness_subject_or_ranking:'已召回长期记忆，优先核对内容、时效、主体和排序。',
  short_term_or_answer_model:'没有可见长期记忆，先核对短期上下文或回答模型。',
};

function scoreSummary(evidence:{keyword_score?:number|null;dense_score?:number|null;fused_score?:number|null}) {
  const parts:string[]=[];
  if(evidence.keyword_score!=null) parts.push(`关键词 ${evidence.keyword_score}`);
  if(evidence.dense_score!=null) parts.push(`余弦 ${evidence.dense_score.toFixed(3)}`);
  if(evidence.fused_score!=null) parts.push(`融合 ${evidence.fused_score.toFixed(4)}`);
  return parts.join(' · ');
}
const emptyCounts = {memory_ok:0,recall_miss:0,wrong_memory:0,memory_irrelevant:0};
const emptyReviewCounts = {open:0,resolved:0,dismissed:0};
type ReviewAction='resolve'|'dismiss'|'reopen';
const reviewReasonOptions:Record<ReviewAction,Array<{value:string;label:string}>>={
  resolve:[{value:'memory_corrected',label:'相关记忆已经纠正'},{value:'retrieval_fixed',label:'召回问题已经处理'},{value:'answer_behavior_fixed',label:'回答行为已经处理'},{value:'other',label:'其他处理'}],
  dismiss:[{value:'not_memory_issue',label:'核对后不是记忆问题'},{value:'false_positive',label:'反馈被误识别为问题'},{value:'other',label:'其他原因'}],
  reopen:[{value:'needs_follow_up',label:'仍需继续核对'}],
};
const shadowReasonOptions:Record<L2SufficiencyShadowVerdict,Array<{value:string;label:string}>>={
  correct:[{value:'agreement',label:'完整支持集合判断正确'}],
  incorrect:[{value:'missed_support',label:'漏掉了真正支持的候选证据'},{value:'false_support',label:'错误放行了不支持的候选证据'},{value:'stale_content',label:'候选正文后来变化，无法按原状态确认'},{value:'other',label:'其他错误'}],
  uncertain:[{value:'ambiguous_query',label:'问题含义不清，暂时无法判断'},{value:'stale_content',label:'候选正文后来变化'},{value:'other',label:'其他不确定原因'}],
};
const extractionOutcomeLabel:Record<L1ExtractionOutcome|'incomplete',string>={
  noop:'正常不记',added:'新增 L1',reused:'复用已有 L1',
  extraction_failed:'模型提取失败',persistence_failed:'L1 落库失败',
  incomplete:'未完成',
};
const readinessConditionLabel:Record<string,string>={
  answerable_sample_floor:'有证据问题样本',
  unsupported_sample_floor:'无证据问题样本',
  zero_false_blocks:'误拦截',
  zero_unsupported_passes:'无证据误放行',
  zero_incomplete_allows:'支持集漏选',
  all_labeled_context_lengths_measured:'上下文长度覆盖',
  positive_candidate_reduction:'候选缩减收益',
};

/** L1/L2 共享同一证据门槛，但两层样本和结论始终分别展示、分别评审。 */
function SufficiencyReadinessAlert({layer,metrics}:{layer:'L1'|'L2';metrics:L1SufficiencyPolicyMetrics}) {
  const readiness=metrics.readiness;
  const ready=readiness.status==='ready_for_controlled_trial';
  const unmet=readiness.conditions.filter(item=>!item.passed);
  return <Alert showIcon type={ready?'success':'warning'} title={ready?`已具备评审 ${layer} 受控试验的证据`:`正式 ${layer} 门控未就绪`} description={<>
    <p>精确人工标签 {metrics.labeled_cases} 轮：有支持证据 {metrics.answerable_labeled_cases}/{readiness.minimum_cases_per_stratum}，无支持证据 {metrics.unsupported_labeled_cases}/{readiness.minimum_cases_per_stratum}。</p>
    <p>误拦截 {metrics.false_block_cases}；无证据误放行 {metrics.unsupported_pass_cases}；支持集漏选 {metrics.incomplete_allow_cases}；候选减少 {metrics.removed_candidate_count}/{metrics.original_candidate_count}。达标也只允许考虑受控试验，永不自动开启。</p>
    <details><summary>查看 {unmet.length} 项未达条件</summary><ul>{unmet.map(item=><li key={item.code}>{readinessConditionLabel[item.code]??item.code}：当前 {String(item.actual??'无')}，要求 {String(item.required)}</li>)}</ul></details>
  </>}/>;
}

function evidencePath(layer:'l1'|'l2'|'l3',itemId:string) {
  const key=layer==='l1'?'memory_id':layer==='l2'?'scenario_id':'persona_id';
  const page=layer==='l1'?'/memories':layer==='l2'?'/scenarios':'/personas';
  return `${page}?${key}=${encodeURIComponent(itemId)}`;
}

/** 所有者跨日查看网页复核与圆屏明确反馈；列表不接收对话正文。 */
export function MemoryQualityApp() {
  const [workspace,setWorkspace] = useWorkspaceParam('view','issues',['issues','extraction','l1-shadow','l2-shadow']);
  const [filterValue,setFilter] = useWorkspaceParam('kind','issues',['issues','recall_miss','wrong_memory','memory_ok','memory_irrelevant','resolved','dismissed','all']);
  const filter = filterValue as Filter;
  const [record,setRecord] = useWorkspaceParam('record','');
  const [recordType,setRecordType] = useWorkspaceParam('record_type','round',['round','l1','l2']);
  const inspectedRecord = useRef('');
  const [offsetText,setOffset] = useWorkspaceParam('offset','0');
  const offset = /^\d{1,7}$/.test(offsetText) ? Math.floor(Number(offsetText)/25)*25 : 0;
  const [ready,setReady] = useState(false);
  const [samplesLoaded,setSamplesLoaded] = useState(false);
  const [readFailures,setReadFailures] = useState({extraction:false,l1:false,l2:false});
  const [page,setPage] = useState<MemoryFeedbackIndex>({kind:'issues',counts:emptyCounts,review_counts:emptyReviewCounts,total:0,offset:0,limit:25,items:[]});
  const [busy,setBusy] = useState(true);
  const [notice,setNotice] = useState('正在读取当前有效判断…');
  const [detail,setDetail] = useState<RoundScreenFeedbackDetail|null>(null);
  const [detailOpen,setDetailOpen] = useState(false);
  const [detailBusy,setDetailBusy] = useState(false);
  const [reviewTarget,setReviewTarget] = useState<{item:MemoryFeedbackIndexItem;action:ReviewAction}|null>(null);
  const [reviewReason,setReviewReason] = useState('');
  const [reviewBusy,setReviewBusy] = useState(false);
  const [l1Shadow,setL1Shadow] = useState<L1SufficiencyShadowPage|null>(null);
  const [l1ShadowDetail,setL1ShadowDetail] = useState<L1SufficiencyShadowDetail|null>(null);
  const [l1ShadowOpen,setL1ShadowOpen] = useState(false);
  const [l1ShadowBusy,setL1ShadowBusy] = useState(false);
  const [l1ShadowReview,setL1ShadowReview] = useState<L2SufficiencyShadowVerdict|null>(null);
  const [l1ShadowReviewReason,setL1ShadowReviewReason] = useState('');
  const [l1ShadowExpectedIds,setL1ShadowExpectedIds] = useState<string[]>([]);
  const [l1ShadowReviewBusy,setL1ShadowReviewBusy] = useState(false);
  const [shadow,setShadow] = useState<L2SufficiencyShadowPage|null>(null);
  const [shadowDetail,setShadowDetail] = useState<L2SufficiencyShadowDetail|null>(null);
  const [shadowOpen,setShadowOpen] = useState(false);
  const [shadowBusy,setShadowBusy] = useState(false);
  const [shadowReview,setShadowReview] = useState<L2SufficiencyShadowVerdict|null>(null);
  const [shadowReviewReason,setShadowReviewReason] = useState('');
  const [shadowExpectedIds,setShadowExpectedIds] = useState<string[]>([]);
  const [shadowReviewBusy,setShadowReviewBusy] = useState(false);
  const [extractionAudit,setExtractionAudit] = useState<L1ExtractionAuditPage|null>(null);
  const [retryingAttempt,setRetryingAttempt] = useState<string|null>(null);
  useUnsavedChanges(Boolean(reviewTarget || l1ShadowReview || shadowReview), '有尚未提交的质量复核。');

  async function load(nextFilter=filter,offset=0) {
    setBusy(true);
    try {
      const params = new URLSearchParams({kind:nextFilter,offset:String(offset),limit:'25'});
      setPage(await api.request<MemoryFeedbackIndex>(`/api/chat-memory-feedback?${params}`));setSamplesLoaded(true);
      setNotice('质量样本已更新；列表没有复制聊天正文。');
    } catch {
      setNotice('无法读取质量样本。请确认控制台仍在运行，然后刷新；没有自动重试。');
    } finally {setBusy(false);}
  }

  async function loadShadow() {
    try {
      const value=await api.request<L2SufficiencyShadowPage>('/api/l2-sufficiency-shadow?limit=20');
      setReadFailures(current=>({...current,l2:false}));
      setShadow(value&&Array.isArray(value.items)&&value.runtime&&typeof value.runtime.enabled==='boolean'?value:null);
    } catch {
      setShadow(null);setReadFailures(current=>({...current,l2:true}));
    }
  }

  async function loadL1Shadow() {
    try {
      const value=await api.request<L1SufficiencyShadowPage>('/api/l1-sufficiency-shadow?limit=20');
      setReadFailures(current=>({...current,l1:false}));
      setL1Shadow(value&&Array.isArray(value.items)&&value.runtime&&typeof value.runtime.enabled==='boolean'?value:null);
    } catch {setL1Shadow(null);setReadFailures(current=>({...current,l1:true}));}
  }

  async function loadExtractionAudit() {
    try {
      const value=await api.request<L1ExtractionAuditPage>('/api/l1-extraction-audit?limit=30');
      setReadFailures(current=>({...current,extraction:false}));
      setExtractionAudit(value&&Array.isArray(value.items)?value:null);
    } catch {
      setExtractionAudit(null);setReadFailures(current=>({...current,extraction:true}));
    }
  }

  async function retryExtraction(sourceMessageId:string,attemptId:string) {
    setRetryingAttempt(attemptId);
    try {
      await api.request(
        `/api/l1-extraction-audit/${encodeURIComponent(sourceMessageId)}/retry`,
        'POST',{expected_attempt_id:attemptId},
      );
      setNotice('已排队重新提取一次；复用原 L0，不会复制对话。稍后刷新可查看新尝试结果。');
      await loadExtractionAudit();
    } catch {
      setNotice('没有发起重新提取。该来源可能已在处理，或列表状态已经过期；请刷新后核对。');
      await loadExtractionAudit();
    } finally {setRetryingAttempt(null);}
  }

  useEffect(()=>{void (async()=>{
    try {await api.bootstrap();await Promise.all([loadL1Shadow(),loadShadow(),loadExtractionAudit()]);setReady(true);}
    catch {setNotice('无法建立本机控制台会话，请刷新页面。');setBusy(false);}
  })();},[]);

  useEffect(()=>{if(ready) void load(filter,offset);},[ready,filter,offset]);

  useEffect(()=>{
    if(!ready)return;
    if(!record){inspectedRecord.current='';setDetailOpen(false);setL1ShadowOpen(false);setShadowOpen(false);return;}
    if(record.length>128 || inspectedRecord.current===`${recordType}:${record}`)return;
    if(recordType==='l1')void inspectL1Shadow(record);
    else if(recordType==='l2')void inspectShadow(record);
    else void inspectRoundScreen(record);
  },[ready,record,recordType]);

  function selectRecord(type:'round'|'l1'|'l2',id:string) {
    inspectedRecord.current=`${type}:${id}`;setRecordType(type);setRecord(id);
    setDetailOpen(type==='round');setL1ShadowOpen(type==='l1');setShadowOpen(type==='l2');
  }
  async function inspectShadow(messageId:string) {
    selectRecord('l2',messageId);
    setShadowOpen(true);setShadowBusy(true);setShadowDetail(null);
    try {const value=await api.request<L2SufficiencyShadowDetail>(`/api/l2-sufficiency-shadow/${encodeURIComponent(messageId)}`);if(inspectedRecord.current===`l2:${messageId}`)setShadowDetail(value);}
    catch {if(inspectedRecord.current===`l2:${messageId}`)setNotice('无法读取这条 L2 影子记录。请确认控制台仍在运行后重试。');}
    finally {if(inspectedRecord.current===`l2:${messageId}`)setShadowBusy(false);}
  }

  async function inspectL1Shadow(messageId:string) {
    selectRecord('l1',messageId);
    setL1ShadowOpen(true);setL1ShadowBusy(true);setL1ShadowDetail(null);
    try {const value=await api.request<L1SufficiencyShadowDetail>(`/api/l1-sufficiency-shadow/${encodeURIComponent(messageId)}`);if(inspectedRecord.current===`l1:${messageId}`)setL1ShadowDetail(value);}
    catch {if(inspectedRecord.current===`l1:${messageId}`)setNotice('无法读取这条 L1 影子记录。请确认控制台仍在运行后重试。');}
    finally {if(inspectedRecord.current===`l1:${messageId}`)setL1ShadowBusy(false);}
  }

  function beginL1ShadowReview(verdict:L2SufficiencyShadowVerdict) {
    setL1ShadowReview(verdict);
    setL1ShadowReviewReason(shadowReasonOptions[verdict][0].value);
    setL1ShadowExpectedIds(
      verdict==='uncertain' ? [] : (l1ShadowDetail?.candidates
        .filter(candidate=>candidate.supports_answer===1)
        .map(candidate=>candidate.memory_id)??[]),
    );
  }

  async function saveL1ShadowReview() {
    if(!l1ShadowDetail||!l1ShadowReview||!l1ShadowReviewReason)return;
    setL1ShadowReviewBusy(true);
    try {
      await api.request(`/api/l1-sufficiency-shadow/${encodeURIComponent(l1ShadowDetail.user_message_id)}/reviews`,'POST',{
        verdict:l1ShadowReview,reason_code:l1ShadowReviewReason,
        expected_review_revision:l1ShadowDetail.review.review_revision,
        expected_supported_memory_ids:l1ShadowReview==='uncertain'?null:l1ShadowExpectedIds,
      });
      setL1ShadowReview(null);
      setNotice('L1 人工复核已追加；模型原判、正式回答和长期记忆均未修改。');
      await Promise.all([inspectL1Shadow(l1ShadowDetail.user_message_id),loadL1Shadow()]);
    } catch {setNotice('L1 人工复核没有保存。记录可能已在其他页面更新，请重新打开详情核对。');}
    finally {setL1ShadowReviewBusy(false);}
  }

  function beginShadowReview(verdict:L2SufficiencyShadowVerdict) {
    setShadowReview(verdict);
    setShadowReviewReason(shadowReasonOptions[verdict][0].value);
    setShadowExpectedIds(verdict==='uncertain'?[]:(shadowDetail?.candidates
      .filter(candidate=>candidate.supports_answer===1)
      .map(candidate=>candidate.scenario_id)??[]));
  }

  async function saveShadowReview() {
    if(!shadowDetail||!shadowReview||!shadowReviewReason)return;
    setShadowReviewBusy(true);
    try {
      await api.request(`/api/l2-sufficiency-shadow/${encodeURIComponent(shadowDetail.user_message_id)}/reviews`,'POST',{
        verdict:shadowReview,reason_code:shadowReviewReason,
        expected_review_revision:shadowDetail.review.review_revision,
        expected_supported_scenario_ids:shadowReview==='uncertain'?null:shadowExpectedIds,
      });
      setShadowReview(null);
      setNotice('人工复核已追加；机器原判、正式回答和长期记忆均未修改。');
      await Promise.all([inspectShadow(shadowDetail.user_message_id),loadShadow()]);
    } catch {setNotice('人工复核没有保存。记录可能已在其他页面更新，请重新打开详情核对。');}
    finally {setShadowReviewBusy(false);}
  }

  async function inspectRoundScreen(eventId:string) {
    selectRecord('round',eventId);
    setDetailOpen(true);setDetailBusy(true);setDetail(null);
    try {const value=await api.request<RoundScreenFeedbackDetail>(`/api/round-screen-memory-feedback/${encodeURIComponent(eventId)}`);if(inspectedRecord.current===`round:${eventId}`)setDetail(value);}
    catch {if(inspectedRecord.current===`round:${eventId}`)setNotice('无法读取这条圆屏诊断详情。请确认控制台仍在运行后重试。');}
    finally {if(inspectedRecord.current===`round:${eventId}`)setDetailBusy(false);}
  }

  function beginReview(item:MemoryFeedbackIndexItem,action:ReviewAction) {
    setReviewTarget({item,action});
    setReviewReason(reviewReasonOptions[action][0].value);
  }

  async function saveReview() {
    if(!reviewTarget||!reviewReason)return;
    setReviewBusy(true);
    try {
      const {item,action}=reviewTarget;
      await api.request('/api/chat-memory-feedback/reviews','POST',{
        source:item.source,target_id:item.feedback_target_id,feedback_revision:item.revision,
        action,reason_code:reviewReason,expected_review_revision:item.review.review_revision,
      });
      setReviewTarget(null);
      setNotice(action==='reopen'?'样本已重新放回待处理队列。':'复核状态已保存；没有自动修改长期记忆。');
      await load(filter,page.offset);
    } catch {setNotice('复核状态没有保存。样本可能已在其他页面更新，请刷新后核对；没有自动重试。');}
    finally {setReviewBusy(false);}
  }

  const sidebar = <ConsoleNav active="quality" legacyPath="/memories"/>;
  const machineL1SupportIds=(l1ShadowDetail?.candidates??[])
    .filter(candidate=>candidate.supports_answer===1).map(candidate=>candidate.memory_id);
  const l1SelectionMatchesMachine=machineL1SupportIds.length===l1ShadowExpectedIds.length
    && machineL1SupportIds.every(id=>l1ShadowExpectedIds.includes(id));
  const l1ReviewSelectionValid=l1ShadowReview==='uncertain'
    || l1ShadowReview==='correct'&&l1SelectionMatchesMachine
    || l1ShadowReview==='incorrect'&&!l1SelectionMatchesMachine;
  const machineL2SupportIds=(shadowDetail?.candidates??[])
    .filter(candidate=>candidate.supports_answer===1).map(candidate=>candidate.scenario_id);
  const l2SelectionMatchesMachine=machineL2SupportIds.length===shadowExpectedIds.length
    && machineL2SupportIds.every(id=>shadowExpectedIds.includes(id));
  const l2ReviewSelectionValid=shadowReview==='uncertain'
    || shadowReview==='correct'&&l2SelectionMatchesMachine
    || shadowReview==='incorrect'&&!l2SelectionMatchesMachine;

  return <AppShell subtitle="跨日期的记忆诊断样本" className="quality-shell" sidebar={sidebar}>
    <PageHeader eyebrow="长期记忆" title="记忆质量样本" description="集中查看日常 L1 提取、网页人工复核、圆屏明确反馈和只观察不生效的 L1/L2 影子判断。" action={<Button loading={busy} onClick={()=>void Promise.all([load(filter,page.offset),loadL1Shadow(),loadShadow(),loadExtractionAudit()])}>刷新</Button>}/>
    <DataWorkspace label="记忆质量工作区" activeKey={workspace} onChange={setWorkspace} items={[
      {key:'issues',label:'问题队列',children:<>    <Alert showIcon type="info" title="这是人工诊断队列，不是准确率报告" description="默认只显示‘没想起’和‘错误记忆’。排查方向由可见轨迹生成，不代表系统已经确认根因，也不会触发模型、重答或记忆修改。"/>
    <section className="quality-counts" aria-label="当前有效判断总览">
      <Card><Statistic title="待处理" value={samplesLoaded?page.review_counts.open:'—'}/></Card>
      <Card><Statistic title="已处理" value={samplesLoaded?page.review_counts.resolved:'—'}/></Card>
      <Card><Statistic title="非记忆问题" value={samplesLoaded?page.review_counts.dismissed:'—'}/></Card>
      <Card><Statistic title="没想起 / 错误" value={samplesLoaded?`${page.counts.recall_miss} / ${page.counts.wrong_memory}`:'—'}/></Card>
    </section>
    <Card className="quality-list-card" title="当前有效判断" extra={<Select aria-label="质量样本筛选" value={filter} disabled={busy} style={{width:190}} options={[
      {value:'issues',label:'需要核对的问题'}, {value:'recall_miss',label:'只看没想起'},
      {value:'wrong_memory',label:'只看错误记忆'}, {value:'memory_ok',label:'正常对照'},
      {value:'memory_irrelevant',label:'记忆无关负例'}, {value:'resolved',label:'已处理问题'},
      {value:'dismissed',label:'不是记忆问题'}, {value:'all',label:'全部当前判断'},
    ]} onChange={(value:Filter)=>{setFilter(value);setOffset('0');}}/>}>
      <List loading={busy} dataSource={page.items} locale={{emptyText:<Empty description={filter==='issues'?'目前没有待核对问题':'没有符合筛选的当前判断'}/>}} renderItem={item=><List.Item actions={[
        ...(item.source==='round_screen' ? [
        item.feedback_event_id&&<Button key="detail" type="link" onClick={()=>void inspectRoundScreen(item.feedback_event_id!)}>在此核对</Button>,
        <Link key="question" to={`/memories?l0_message_id=${encodeURIComponent(item.request_id)}`}>问题 L0</Link>,
        item.assistant_message_id&&<Link key="answer" to={`/memories?l0_message_id=${encodeURIComponent(item.assistant_message_id)}`}>回答 L0</Link>,
        item.feedback_message_id&&<Link key="feedback" to={`/memories?l0_message_id=${encodeURIComponent(item.feedback_message_id)}`}>反馈 L0</Link>,
      ].filter(Boolean) : [<Link key="inspect" to={`/chat-react?chat_id=${encodeURIComponent(item.chat_id ?? '')}&request_id=${encodeURIComponent(item.request_id)}`}>核对回答与证据</Link>]),
        ...(item.review.state==='open'?[<Button key="resolve" type="link" onClick={()=>beginReview(item,'resolve')}>标为已处理</Button>,<Button key="dismiss" type="link" onClick={()=>beginReview(item,'dismiss')}>不是记忆问题</Button>]:item.review.state==='resolved'||item.review.state==='dismissed'?[<Button key="reopen" type="link" onClick={()=>beginReview(item,'reopen')}>重新打开</Button>]:[]),
      ]}>
        <List.Item.Meta title={<Space wrap><Tag color={item.kind==='wrong_memory'?'red':item.kind==='recall_miss'?'gold':item.kind==='memory_ok'?'green':'default'}>{kindLabel[item.kind]}</Tag><Tag>{item.source==='round_screen'?'圆屏语音':'网页聊天'}</Tag>{item.review.state==='resolved'&&<Tag color="green">已处理</Tag>}{item.review.state==='dismissed'&&<Tag>不是记忆问题</Tag>}<span>{item.chat_title}</span></Space>} description={<div className="quality-sample-description"><p>{focusLabel[item.diagnostic_focus]}</p><Space wrap><span>{new Date(item.occurred_at).toLocaleString('zh-CN')}</span><code>反馈修订 {item.revision}</code>{item.review.review_revision>0&&<code>复核修订 {item.review.review_revision}</code>}<span>L1 {item.retrieved_counts.l1} · L2 {item.retrieved_counts.l2} · L3 {item.retrieved_counts.l3}</span></Space>{item.source==='round_screen'&&<div><small className="subtle">{item.retrieval_evidence?.length?'当轮实际召回：':item.retrieval_evidence_recorded?'当轮确认没有召回 L1/L2/L3。':'旧回执只保存数量，没有可伪造回填的条目 ID。'}</small><Space wrap>{item.retrieval_evidence?.map(evidence=><Link key={`${evidence.layer}-${evidence.rank}`} to={evidencePath(evidence.layer,evidence.item_id)}>{evidence.layer.toUpperCase()} #{evidence.rank}</Link>)}</Space></div>}</div>}/>
      </List.Item>}/>
      <div className="pagination"><Button disabled={busy||page.offset===0} onClick={()=>setOffset(String(Math.max(0,page.offset-page.limit)))}>上一页</Button><span>{page.total?`${page.offset+1}–${Math.min(page.offset+page.limit,page.total)} / ${page.total}`:'0 条'}</span><Button disabled={busy||page.offset+page.limit>=page.total} onClick={()=>setOffset(String(page.offset+page.limit))}>下一页</Button></div>
    </Card>
</>},
      {key:'extraction',label:'日常提取',children:<>    <Card className="quality-list-card" title="L1 日常提取运行" extra={<Tag color={extractionAudit?.counts.incomplete?'gold':'green'}>{!extractionAudit?'状态未知':extractionAudit.counts.incomplete?`未完成 ${extractionAudit.counts.incomplete}`:'最近尝试均有终态'}</Tag>}>
      <Alert showIcon type="info" title="这里回答‘为什么这一句没有变成 L1’" description="正常不记和故障会明确区分。只有最新的失败或中断项可手动重试一次；不会重跑正常不记，也不会复制 L0。旧对话没有历史回填。"/>
      {extractionAudit&&<Space wrap className="quality-shadow-counts">
        <Tag color="green">新增 {extractionAudit.counts.added}</Tag>
        <Tag color="cyan">复用 {extractionAudit.counts.reused}</Tag>
        <Tag>正常不记 {extractionAudit.counts.noop}</Tag>
        <Tag color="red">提取失败 {extractionAudit.counts.extraction_failed}</Tag>
        <Tag color="red">落库失败 {extractionAudit.counts.persistence_failed}</Tag>
      </Space>}
      {readFailures.extraction?<Alert showIcon type="error" title="日常提取记录读取失败" description="可刷新后核对；读取失败不等于正常不记。"/>:!extractionAudit?<Empty description="当前数据库尚未迁移到 V44，或聊天入口未启用"/>:<List dataSource={extractionAudit.items} locale={{emptyText:<Empty description="还没有新的 L1 提取尝试；旧对话不会伪造回填"/>}} renderItem={item=>{
        const outcome=item.outcome_code??'incomplete';
        const color=outcome==='added'?'green':outcome==='reused'?'cyan':outcome==='noop'?'default':outcome==='incomplete'?'gold':'red';
        const actions=[<Link key="source" to={`/memories?l0_message_id=${encodeURIComponent(item.source_message_id)}`}>打开来源 L0</Link>];
        if(item.retryable) actions.push(<Button key="retry" type="link" danger loading={retryingAttempt===item.attempt_id} disabled={retryingAttempt!==null&&retryingAttempt!==item.attempt_id} onClick={()=>void retryExtraction(item.source_message_id,item.attempt_id)}>重新提取一次</Button>);
        return <List.Item actions={actions}>
          <List.Item.Meta title={<Space wrap><Tag color={color}>{extractionOutcomeLabel[outcome]}</Tag><code>{item.source_message_id}</code></Space>} description={<Space wrap><span>{new Date(item.started_at).toLocaleString('zh-CN')}</span><span>候选 {item.candidate_count??'—'} · 新增 {item.added_count??'—'}</span><span>{item.duration_ms==null?'耗时未记录':`${Math.round(item.duration_ms)} ms`}</span><code>{item.provider} / {item.model}</code><code>{item.preprocessor_version}</code></Space>}/>
        </List.Item>;
      }}/>} {null}
    </Card>
</>},
      {key:'l1-shadow',label:'L1 影子判断',children:<>    <Card className="quality-list-card" title="L1 证据充分性影子记录" extra={<Tag color={l1Shadow?.runtime?.enabled?'cyan':'default'}>{!l1Shadow?'状态未知':l1Shadow.runtime.enabled?'本次已启用':'本次未启用'}</Tag>}>
      <Alert showIcon type="info" title="语义相关不等于足以回答" description="影子判断只记录如果增加证据门控会发生什么；它不过滤当轮 L1，不修改回答或记忆。"/>
      {l1Shadow&&<Space wrap className="quality-shadow-counts"><Tag>已完成 {l1Shadow.review_counts.completed}</Tag><Tag color="blue">待复核 {l1Shadow.review_counts.unreviewed}</Tag><Tag color="green">正确 {l1Shadow.review_counts.correct}</Tag><Tag color="red">错误 {l1Shadow.review_counts.incorrect}</Tag><Tag color="gold">不确定 {l1Shadow.review_counts.uncertain}</Tag></Space>}
      {l1Shadow&&<SufficiencyReadinessAlert layer="L1" metrics={l1Shadow.policy_metrics}/>}
      {readFailures.l1?<Alert showIcon type="error" title="L1 影子记录读取失败" description="可刷新后核对；失败不能作为未启用或判断通过的证据。"/>:!l1Shadow?<Empty description="当前数据库没有可读取的 V46 L1 影子记录，或聊天入口未启用"/>:<List dataSource={l1Shadow.items} locale={{emptyText:<Empty description="还没有 L1 影子样本"/>}} renderItem={item=><List.Item actions={[<Button key="detail" type="link" onClick={()=>void inspectL1Shadow(item.user_message_id)}>查看 L1 候选判断</Button>,<Link key="source" to={`/memories?l0_message_id=${encodeURIComponent(item.user_message_id)}`}>问题 L0</Link>]}>
        <List.Item.Meta title={<Space wrap><Tag color={item.status==='completed'?'green':item.status==='failed'?'red':'gold'}>{item.status==='completed'?'已完成':item.status==='failed'?'失败':'处理中'}</Tag>{item.review_verdict&&<Tag color={item.review_verdict==='correct'?'green':item.review_verdict==='incorrect'?'red':'gold'}>{item.review_verdict==='correct'?'人工确认正确':item.review_verdict==='incorrect'?'人工确认错误':'人工暂不确定'}</Tag>}<span>{item.query}</span></Space>} description={<Space wrap><span>{new Date(item.requested_at).toLocaleString('zh-CN')}</span><span>候选 {item.candidate_count} · 判定支持 {item.supported_count}</span><code>{item.retrieval_strategy}</code><code>{item.model}</code>{item.error_code&&<code>{item.error_code}</code>}</Space>}/>
      </List.Item>}/>}
    </Card>
</>},
      {key:'l2-shadow',label:'L2 影子判断',children:<>    <Card className="quality-list-card" title="L2 证据充分性影子记录" extra={<Tag color={shadow?.runtime?.enabled?'cyan':'default'}>{!shadow?'状态未知':shadow.runtime.enabled?'本次已启用':'本次未启用'}</Tag>}>
      <Alert showIcon type="info" title="这里只显示‘如果门控生效会怎样’" description="影子判断不会过滤本轮 L2、不会修改回答或记忆。默认关闭；历史记录即使当前未启用也会保留。"/>
      {shadow&&<Space wrap className="quality-shadow-counts"><Tag>已完成 {shadow.review_counts.completed}</Tag><Tag color="blue">待复核 {shadow.review_counts.unreviewed}</Tag><Tag color="green">正确 {shadow.review_counts.correct}</Tag><Tag color="red">错误 {shadow.review_counts.incorrect}</Tag><Tag color="gold">不确定 {shadow.review_counts.uncertain}</Tag></Space>}
      {shadow&&<SufficiencyReadinessAlert layer="L2" metrics={shadow.policy_metrics}/>}
      {readFailures.l2?<Alert showIcon type="error" title="L2 影子记录读取失败" description="可刷新后核对；失败不能作为未启用或判断通过的证据。"/>:!shadow?<Empty description="当前数据库没有可读取的 V42 影子记录，或聊天入口未启用"/>:<List dataSource={shadow.items} locale={{emptyText:<Empty description="还没有影子样本"/>}} renderItem={item=><List.Item actions={[<Button key="detail" type="link" onClick={()=>void inspectShadow(item.user_message_id)}>查看候选判断</Button>,<Link key="source" to={`/memories?l0_message_id=${encodeURIComponent(item.user_message_id)}`}>问题 L0</Link>]}>
        <List.Item.Meta title={<Space wrap><Tag color={item.status==='completed'?'green':item.status==='failed'?'red':'gold'}>{item.status==='completed'?'已完成':item.status==='failed'?'失败':'处理中'}</Tag>{item.review_verdict&&<Tag color={item.review_verdict==='correct'?'green':item.review_verdict==='incorrect'?'red':'gold'}>{item.review_verdict==='correct'?'人工确认正确':item.review_verdict==='incorrect'?'人工确认错误':'人工暂不确定'}</Tag>}<span>{item.query}</span></Space>} description={<Space wrap><span>{new Date(item.requested_at).toLocaleString('zh-CN')}</span><span>候选 {item.candidate_count} · 判定支持 {item.supported_count}</span><code>{item.model}</code>{item.error_code&&<code>{item.error_code}</code>}</Space>}/>
      </List.Item>}/>}
    </Card>
</>},
    ]}/>
    <Drawer width={640} title="圆屏记忆质量详情" open={detailOpen} onClose={()=>setRecord('')}>
      {detailBusy?<p>正在读取原始证据…</p>:detail?<>
        <Alert showIcon type="info" title="正文只在打开详情后读取" description="这里只比较回答当时的召回指纹和条目当前内容；内容变化不自动等于错误根因。"/>
        <Descriptions column={1} bordered size="small" items={[
          {key:'question',label:'用户问题',children:detail.question},
          {key:'answer',label:'助手回答',children:detail.answer},
          {key:'feedback',label:'用户反馈',children:detail.feedback},
        ]}/>
        <Card title="回答当时的召回证据" size="small">
          <p className="subtle">策略：<code>{detail.retrieval_strategy??'历史未记录'}</code>。关键词分是重合词项数，余弦分是语义相似度，融合分用于排序；它们都不是事实可信度。</p>
          {!detail.retrieval_evidence_recorded
            ? <Alert type="warning" showIcon title="旧回执没有保存条目索引"/>
            : detail.retrieval_evidence.length===0
              ? <Empty description="当轮确认没有召回 L1/L2/L3"/>
              : <List dataSource={detail.retrieval_evidence} renderItem={evidence=><List.Item actions={[<Link key="open" to={evidencePath(evidence.layer,evidence.item_id)}>打开当前条目</Link>]}><List.Item.Meta title={<Space><Tag>{evidence.layer.toUpperCase()} #{evidence.rank}</Tag>{evidence.temporal_role==='historical'&&<Tag color="gold">回答时作为历史事实</Tag>}<Tag color={evidence.matches_receipt===true?'green':evidence.matches_receipt===false?'gold':'default'}>{evidence.matches_receipt===true?'与回答时一致':evidence.matches_receipt===false?'内容后来变化':'当前已缺失'}</Tag></Space>} description={<><p>{evidence.current_content??'当前数据库中找不到该条目正文。'}</p><code>{evidence.item_id}</code><small className="subtle"> · 当前状态 {evidence.current_state}{evidence.temporal_role==='historical'&&` · 回答时区间 ${evidence.valid_from??'未记录'} → ${evidence.valid_to??'未记录'}`}{scoreSummary(evidence)&&` · ${scoreSummary(evidence)}`}</small></>}/></List.Item>}/>
          }
        </Card>
      </>:<Empty description="没有可显示的诊断详情"/>}
    </Drawer>
    <Drawer width={680} title="L1 影子门控详情" open={l1ShadowOpen} onClose={()=>setRecord('')}>
      {l1ShadowBusy?<p>正在读取 L1 候选审计…</p>:l1ShadowDetail?<>
        <Alert showIcon type="warning" title="判定尚未参与正式回答" description="正文来自当前 L1；指纹用于核对它是否仍与影子运行时一致。支持只表示该候选包含被问信息。"/>
        <Descriptions column={1} bordered size="small" items={[
          {key:'query',label:'当轮问题',children:l1ShadowDetail.query},
          {key:'status',label:'运行状态',children:l1ShadowDetail.status},
          {key:'strategy',label:'召回策略',children:l1ShadowDetail.retrieval_strategy},
          {key:'reviewer',label:'门控版本',children:l1ShadowDetail.reviewer_version},
          {key:'model',label:'复核模型',children:`${l1ShadowDetail.provider} / ${l1ShadowDetail.model}`},
          {key:'owner-review',label:'人工复核',children:l1ShadowDetail.review.verdict==='correct'?'判断正确':l1ShadowDetail.review.verdict==='incorrect'?'判断错误':l1ShadowDetail.review.verdict==='uncertain'?'暂不确定':'尚未复核'},
        ]}/>
        <List dataSource={l1ShadowDetail.candidates} locale={{emptyText:<Empty description="该轮没有 L1 候选，因此没有调用复核模型"/>}} renderItem={candidate=><List.Item actions={[<Link key="memory" to={`/memories?memory_id=${encodeURIComponent(candidate.memory_id)}`}>打开 L1</Link>]}><List.Item.Meta title={<Space wrap><Tag>#{candidate.rank}</Tag><Tag color={candidate.supports_answer===1?'green':candidate.supports_answer===0?'default':'gold'}>{candidate.supports_answer===1?'足以支持':candidate.supports_answer===0?'证据不足':'尚未判定'}</Tag><code>{candidate.memory_id}</code></Space>} description={<><p>{candidate.current_content??'当前数据库中没有这条 L1 正文。'}</p><Space wrap><code>{candidate.reason_code??'pending'}</code>{scoreSummary(candidate)&&<span>{scoreSummary(candidate)}</span>}<span>{candidate.content_matches_snapshot===true?'与运行时指纹一致':candidate.content_matches_snapshot===false?'正文后来变化':'无法核对历史正文'}</span></Space></>}/></List.Item>}/>
        {l1ShadowDetail.status==='completed'&&<Space wrap><Button onClick={()=>beginL1ShadowReview('correct')}>L1 判断正确</Button><Button danger onClick={()=>beginL1ShadowReview('incorrect')}>L1 判断错误</Button><Button onClick={()=>beginL1ShadowReview('uncertain')}>L1 暂不确定</Button></Space>}
      </>:<Empty description="没有可显示的 L1 影子详情"/>}
    </Drawer>
    <Drawer width={680} title="L2 影子门控详情" open={shadowOpen} onClose={()=>setRecord('')}>
      {shadowBusy?<p>正在读取候选审计…</p>:shadowDetail?<>
        <Alert showIcon type="warning" title="判定尚未参与正式回答" description="场景正文来自当前 L2；指纹可核对它是否仍与影子运行时一致。支持只表示候选包含被问信息，不表示最终答案一定正确。"/>
        <Descriptions column={1} bordered size="small" items={[
          {key:'query',label:'当轮问题',children:shadowDetail.query},
          {key:'status',label:'运行状态',children:shadowDetail.status},
          {key:'strategy',label:'候选策略',children:shadowDetail.retrieval_strategy},
          {key:'reviewer',label:'门控版本',children:shadowDetail.reviewer_version},
          {key:'model',label:'复核模型',children:`${shadowDetail.provider} / ${shadowDetail.model}`},
          {key:'owner-review',label:'人工复核',children:shadowDetail.review.verdict==='correct'?'判断正确':shadowDetail.review.verdict==='incorrect'?'判断错误':shadowDetail.review.verdict==='uncertain'?'暂不确定':'尚未复核'},
        ]}/>
        <List dataSource={shadowDetail.candidates} locale={{emptyText:<Empty description="该轮没有 L2 候选，因此没有调用复核模型"/>}} renderItem={candidate=><List.Item actions={[<Link key="scenario" to={`/scenarios?scenario_id=${encodeURIComponent(candidate.scenario_id)}`}>打开 L2</Link>]}><List.Item.Meta title={<Space wrap><Tag>#{candidate.rank}</Tag><Tag color={candidate.supports_answer===1?'green':candidate.supports_answer===0?'default':'gold'}>{candidate.supports_answer===1?'足以支持':candidate.supports_answer===0?'证据不足':'尚未判定'}</Tag><span>{candidate.current_title??'当前场景已缺失'}</span></Space>} description={<><p>{candidate.current_summary??'当前数据库中没有这条 L2 正文。'}</p><Space wrap><code>{candidate.reason_code??'pending'}</code>{candidate.keyword_score!=null&&<span>关键词 {candidate.keyword_score}</span>}<span>{candidate.content_matches_snapshot===true?'与运行时指纹一致':candidate.content_matches_snapshot===false?'正文后来变化':'无法核对历史正文'}</span></Space></>}/></List.Item>}/>
        {shadowDetail.status==='completed'&&<Space wrap><Button onClick={()=>beginShadowReview('correct')}>判断正确</Button><Button danger onClick={()=>beginShadowReview('incorrect')}>判断错误</Button><Button onClick={()=>beginShadowReview('uncertain')}>暂不确定</Button></Space>}
      </>:<Empty description="没有可显示的影子详情"/>}
    </Drawer>
    <Modal title="复核 L2 影子判断" open={shadowReview!==null} confirmLoading={shadowReviewBusy} okText="保存人工复核" cancelText="取消" okButtonProps={{disabled:!l2ReviewSelectionValid}} onOk={()=>void saveShadowReview()} onCancel={()=>!shadowReviewBusy&&setShadowReview(null)}>
      <p>复核的是这一轮完整的支持集合；只追加审计事件，不会改变回答或记忆。</p>
      {shadowReview!=='uncertain'&&<>
        <p className="subtle">勾选你认为真正包含问题答案的 L2 场景。全部不选表示候选都不足以回答。</p>
        <Checkbox.Group aria-label="L2 人工支持集合" value={shadowExpectedIds} onChange={values=>setShadowExpectedIds(values.map(String))}>
          <Space direction="vertical">{(shadowDetail?.candidates??[]).map(candidate=><Checkbox key={candidate.scenario_id} value={candidate.scenario_id}>#{candidate.rank} {candidate.current_title??candidate.scenario_id}</Checkbox>)}</Space>
        </Checkbox.Group>
      </>}
      <Select aria-label="L2 影子复核原因" value={shadowReviewReason} style={{width:'100%'}} options={shadowReview?shadowReasonOptions[shadowReview]:[]} onChange={setShadowReviewReason}/>
    </Modal>
    <Modal title="复核 L1 影子判断" open={l1ShadowReview!==null} confirmLoading={l1ShadowReviewBusy} okText="保存 L1 复核" cancelText="取消" okButtonProps={{disabled:!l1ReviewSelectionValid}} onOk={()=>void saveL1ShadowReview()} onCancel={()=>!l1ShadowReviewBusy&&setL1ShadowReview(null)}>
      <p>复核的是这一轮完整 L1 支持集合；只追加审计事件，不会改变回答或记忆。</p>
      {l1ShadowReview!=='uncertain'&&<>
        <p className="subtle">勾选你认为真正包含问题答案的候选。可以全部不选，表示这些候选都不足以回答。</p>
        <Checkbox.Group aria-label="人工支持集合" value={l1ShadowExpectedIds} onChange={values=>setL1ShadowExpectedIds(values.map(String))}>
          <Space direction="vertical">{(l1ShadowDetail?.candidates??[]).map(candidate=><Checkbox key={candidate.memory_id} value={candidate.memory_id}>#{candidate.rank} {candidate.current_content??candidate.memory_id}</Checkbox>)}</Space>
        </Checkbox.Group>
      </>}
      <Select aria-label="L1 影子复核原因" value={l1ShadowReviewReason} style={{width:'100%'}} options={l1ShadowReview?shadowReasonOptions[l1ShadowReview]:[]} onChange={setL1ShadowReviewReason}/>
    </Modal>
    <Modal title={reviewTarget?.action==='resolve'?'标记为已处理':reviewTarget?.action==='dismiss'?'标记为不是记忆问题':'重新打开样本'} open={reviewTarget!==null} confirmLoading={reviewBusy} okText="保存复核状态" cancelText="取消" onOk={()=>void saveReview()} onCancel={()=>!reviewBusy&&setReviewTarget(null)}>
      <p>这只管理诊断队列，不会自动修改、删除或重新生成长期记忆。</p>
      <Select aria-label="复核原因" value={reviewReason} style={{width:'100%'}} options={reviewTarget?reviewReasonOptions[reviewTarget.action]:[]} onChange={setReviewReason}/>
    </Modal>
    <p className="memory-status" role="status">{notice}</p>
  </AppShell>;
}
