import {useEffect, useMemo, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Button, Card, Empty, Input, Select, Space, Table, Tag} from 'antd';
import {ChatApi} from './api';
import {AppShell, ConsoleNav} from './AppShell';
import {PageHeader} from './PageHeader';
import {ExperimentJobs} from './ExperimentJobs';
import {evidenceLabel, filterRuns, groupLabel, statusLabel, verdictLabel} from '../../assets/experiment-view.mjs';

type Run = {id:string; kind:string; provider?:string; model?:string; dataset:string; split:string; status:string; completed:number; total:number; started_at:string};
type Group = {id:string; completed:number; total:number; answer_scored:boolean; answer_pass:number; evidence_scored:number; evidence_pass:number};
type ReviewItem = {method:string; question_id:string; verdict:string; rationale?:string};
type Review = {reviewer_kind:string; reviewer:string; revision:number; summary:Record<string,{pass:number; total:number; pending:number; unscorable:number}>; items:ReviewItem[]};
type Question = {id:string; query:string};
type Detail = {kind:string; started_at:string; dataset?:{name:string}; split:string; status:string; groups:Group[]; reviews:Review[]; questions:Question[]; ignored_reviews:number; report_sha256:string; code_commit?:string; code_dirty?:boolean; review_enabled:boolean};
type Evidence = {content:string; source_event_ids?:string[]};
type Source = {event_id:string; role:string; content:string};
type Row = {group:string; status:string; answer?:string; answer_proxy_pass:boolean|null; evidence_complete:boolean|null; state_unchanged:boolean|null; error?:string; injected_context:string; context:string; retrieved:Evidence[]; sources:Source[]; expected_abstention?:boolean; reference_answer?:string};
type QuestionDetail = {report_sha256:string; source_note:string; rows:Row[]};

const api = new ChatApi();
const dateText = (value:string) => {const date = new Date(value); return Number.isNaN(date.getTime()) ? '时间未提供' : date.toLocaleString('zh-CN');};

function EvidenceBlocks({row}: {row:Row}) {
  return <>
    <details><summary>实际注入上下文</summary><pre>{row.injected_context || '空：没有注入记忆'}</pre></details>
    <details><summary>完整检索上下文</summary><pre>{row.context || '空：没有召回记忆'}</pre></details>
    <details><summary>召回条目与来源 ID（{row.retrieved.length}）</summary>{row.retrieved.map((item,index) => <pre key={index}>{index+1}. {item.content}{'\n'}来源：{item.source_event_ids?.join('、') ?? '未提供'}</pre>)}</details>
    <details><summary>原始来源（含说话角色）</summary>{row.sources.length ? row.sources.map(source => <pre key={source.event_id}>{source.event_id} · {source.role}{'\n'}{source.content}</pre>) : <p>没有可展示的来源。</p>}</details>
  </>;
}

function ReviewForm({runId, questionId, row, detail, reviewer, onDirty}: {runId:string; questionId:string; row:Row; detail:Detail; reviewer:string; onDirty:(dirty:boolean)=>void}) {
  const client = useQueryClient();
  const current = detail.reviews.find(review => review.reviewer_kind === 'human' && review.reviewer === reviewer);
  const saved = current?.items.find(item => item.method === row.group && item.question_id === questionId);
  const [verdict, setVerdict] = useState(saved?.verdict ?? 'pending');
  const [rationale, setRationale] = useState(saved?.rationale ?? '');
  const [unknown, setUnknown] = useState(false);
  const [notice, setNotice] = useState('');
  useEffect(() => {setVerdict(saved?.verdict ?? 'pending'); setRationale(saved?.rationale ?? ''); setUnknown(false); onDirty(false);}, [saved?.verdict, saved?.rationale, reviewer, questionId, row.group]);
  const mutation = useMutation({mutationFn:() => api.request(`/api/experiments/${runId}/reviews`, 'POST', {
    report_sha256:detail.report_sha256, reviewer:reviewer.trim(), revision:current?.revision ?? null,
    method:row.group, question_id:questionId, verdict, rationale:rationale.trim(), request_id:crypto.randomUUID(),
  }), onSuccess:async () => {onDirty(false); setNotice('已另存人工复核版本；原报告与自动初筛未改。'); await client.invalidateQueries({queryKey:['experiment',runId]});},
    onError:error => {setUnknown(true); setNotice(`${String(error)} 结果可能已保存；请刷新档案核对，不自动重发。`);}});
  const changed = verdict !== (saved?.verdict ?? 'pending') || rationale !== (saved?.rationale ?? '');
  function changedValue(nextVerdict:string, nextRationale:string) {onDirty(nextVerdict !== (saved?.verdict ?? 'pending') || nextRationale !== (saved?.rationale ?? ''));}
  return <div className="review-form"><h4>我的判断</h4><Select aria-label={`${row.group}复核结论`} value={verdict} disabled={mutation.isPending || unknown} options={['pending','pass','fail','unscorable'].map(value => ({value,label:verdictLabel(value)}))} onChange={value => {setVerdict(value); changedValue(value,rationale);}}/>
    <Input.TextArea aria-label={`${row.group}复核理由`} rows={3} maxLength={1000} value={rationale} disabled={mutation.isPending || unknown} placeholder="非待判断时，说明依据哪些来源或回答。" onChange={event => {setRationale(event.target.value); changedValue(verdict,event.target.value);}}/>
    <Button loading={mutation.isPending} disabled={!changed || unknown || !reviewer.trim() || (verdict !== 'pending' && !rationale.trim())} onClick={() => mutation.mutate()}>保存此题复核</Button>
    {unknown && <Button onClick={() => {setUnknown(false); void client.invalidateQueries({queryKey:['experiment',runId]});}}>只刷新核对，不重发</Button>}<p className="subtle" role="status">{notice}</p></div>;
}

/** 实验运行、档案阅读和人工复核共用后端契约；运行与阅读状态彼此隔离。 */
export function ExperimentApp() {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState('');
  const [questionId, setQuestionId] = useState('');
  const [reviewer, setReviewer] = useState('我');
  const [reviewDirty, setReviewDirty] = useState(false);
  const session = useQuery({queryKey:['experiments-session'], queryFn:async () => {await api.bootstrap(); return true;}, staleTime:Infinity});
  const runs = useQuery({queryKey:['experiments'], queryFn:() => api.request<{items:Run[]; skipped:number; limited:boolean}>('/api/experiments'), enabled:session.isSuccess});
  const filtered = useMemo(() => filterRuns(runs.data?.items ?? [], query, filter) as Run[], [runs.data, query, filter]);
  const pages = Math.ceil(filtered.length / 10);
  useEffect(() => {setPage(current => Math.min(current, Math.max(0, pages - 1)));}, [pages]);
  useEffect(() => {
    if (!selected && runs.data?.items.length) setSelected((runs.data.items.find(item => item.kind === 'answers' && item.provider === 'openai_compatible') ?? runs.data.items[0]).id);
  }, [runs.data, selected]);
  const detail = useQuery({queryKey:['experiment', selected], queryFn:() => api.request<Detail>(`/api/experiments/${selected}`), enabled:Boolean(selected) && session.isSuccess});
  useEffect(() => {setQuestionId(detail.data?.questions[0]?.id ?? '');}, [detail.data?.report_sha256]);
  const question = useQuery({queryKey:['experiment-question', selected, questionId], queryFn:() => api.request<QuestionDetail>(`/api/experiments/${selected}/question?id=${encodeURIComponent(questionId)}`), enabled:Boolean(selected && questionId)});
  async function openResult(reportId:string) {setSelected(reportId); await runs.refetch();}
  const selectedRun = runs.data?.items.find(item => item.id === selected);
  const sidebar = <><ConsoleNav active="experiments" legacyPath="/experiments"/><Card size="small" className="experiment-guide" title="页面说明"><p>运行、档案、证据和人工复核均已迁移。</p><p>原版仅作为迁移期回退入口。</p></Card></>;

  return <AppShell subtitle="冻结档案与逐题证据" className="experiment-shell" sidebar={sidebar}>
    <PageHeader eyebrow="控制与观察" title="实验中心" description="运行可控的对照实验，查看冻结结果并逐题核对回答与证据。" meta="浏览已有档案不会调用模型；启动新实验前会单独展示预算与网络风险。" action={<Button loading={runs.isFetching} disabled={!session.isSuccess} onClick={() => void runs.refetch()}>刷新档案</Button>}/>
    {(session.isError || runs.isError) && <Alert type="error" showIcon title="实验档案读取失败" description="请确认本机控制台仍在运行；没有自动启动或重试任何模型实验。"/>}
    <section className="experiment-overview" aria-label="实验中心概览">
      <div><small>可读档案</small><strong>{runs.data?.items.length ?? 0}</strong></div>
      <div><small>当前筛选</small><strong>{filtered.length}</strong></div>
      <div><small>当前档案</small><strong>{selectedRun ? statusLabel(selectedRun.status) : '未选择'}</strong></div>
      <div><small>逐题人工复核</small><strong className={detail.data?.review_enabled ? 'is-positive' : ''}>{detail.data?.review_enabled ? '可用' : '未开放'}</strong></div>
    </section>
    <ExperimentJobs api={api} ready={session.isSuccess} onOpen={reportId => void openResult(reportId)}/>
    <div className="experiment-layout">
      <Card className="experiment-archive-card" title="实验档案">
        <Input.Search aria-label="搜索实验" allowClear value={query} onChange={event => {setQuery(event.target.value); setPage(0);}} placeholder="模型、数据集或编号"/>
        <Select className="wide" aria-label="实验类型" value={filter} onChange={value => {setFilter(value); setPage(0);}} options={[{value:'all',label:'全部'},{value:'real',label:'真实模型回答'},{value:'fake',label:'Fake 工程验证'},{value:'retrieval',label:'仅检索'}]}/>
        <div className="experiment-run-list" aria-busy={runs.isLoading}>{filtered.slice(page*10,page*10+10).map(run => <button type="button" className="experiment-run" aria-pressed={selected===run.id} key={run.id} onClick={() => setSelected(run.id)}><Space><Tag>{run.kind === 'retrieval' ? '仅检索' : run.provider === 'fake' ? 'Fake' : '真实回答'}</Tag><strong>{run.model ?? '模型未提供'}</strong></Space><span>{dateText(run.started_at)}<br/>{run.dataset} · {run.split} · {statusLabel(run.status)} {run.completed}/{run.total}<br/>{run.id.slice(-8)}</span></button>)}{!runs.isLoading && !filtered.length && <Empty description="没有匹配的实验"/>}</div>
        <div className="pagination"><Button disabled={page===0} onClick={() => setPage(page-1)}>上一页</Button><span>{filtered.length} 条 · {filtered.length ? page+1 : 0}/{pages}</span><Button disabled={(page+1)*10>=filtered.length} onClick={() => setPage(page+1)}>下一页</Button></div>
        {runs.data && <small>{runs.data.skipped ? `${runs.data.skipped} 条无法读取，未计为通过。` : ''}{runs.data.limited ? ' 超过 500 条，仅展示限定范围。' : ''}</small>}
      </Card>
      <section>
        {!selected ? <Card><Empty description="选择一条实验查看结果"/></Card> : <>
          <Card className="experiment-detail-card" loading={detail.isLoading} title={detail.data?.kind === 'retrieval' ? '冻结检索对照' : '逐题回答对照'}>
            {detail.data && <><p>{dateText(detail.data.started_at)} · {detail.data.dataset?.name ?? '未知数据集'} · {detail.data.split} · {statusLabel(detail.data.status)}</p>
              <Table pagination={false} rowKey="id" dataSource={detail.data.groups} columns={[
                {title:'实验组',dataIndex:'id',render:groupLabel},
                {title:'完成 / 总题',render:(_,g) => `${g.completed}/${g.total}`},
                {title:'词面初筛 / 总题',render:(_,g) => g.answer_scored ? `${g.answer_pass}/${g.total}` : '未评分'},
                {title:'充分证据 / 可评题',render:(_,g) => g.evidence_scored ? `${g.evidence_pass}/${g.evidence_scored}` : '不适用 / 未评分'},
              ]}/>
              {detail.data.reviews.map(review => <p className="subtle" key={`${review.reviewer_kind}:${review.reviewer}`}>{review.reviewer_kind === 'human' ? '人工复核' : '助手复核'} · {review.reviewer}：{Object.entries(review.summary).map(([group,count]) => `${groupLabel(group)} ${count.pass}/${count.total}（待判断 ${count.pending}，不可评分 ${count.unscorable}）`).join('；')}</p>)}
              <details><summary>来源与可比性</summary><pre>报告 {selected}{'\n'}SHA256 {detail.data.report_sha256}{'\n'}代码 {detail.data.code_commit ?? '未记录'}{detail.data.code_dirty ? '（运行时工作区非干净）' : ''}</pre></details></>}
          </Card>
          {detail.data && <Card className="question-select" title="逐题对照"><Select className="wide" aria-label="逐题对照" value={questionId || undefined} options={detail.data.questions.map(item => ({value:item.id,label:item.query}))} onChange={value => {if (!reviewDirty || confirm('有未保存的复核，切换会丢弃编辑。继续吗？')) {setReviewDirty(false); setQuestionId(value);}}}/><label>我的复核署名</label><Input aria-label="我的复核署名" maxLength={60} value={reviewer} onChange={event => {if (!reviewDirty || confirm('有未保存的复核，更换署名会丢弃编辑。继续吗？')) {setReviewDirty(false); setReviewer(event.target.value);}}}/><p className="subtle">自报署名，不是身份认证；同一署名继续原复核。{question.data?.source_note}</p></Card>}
          <div className="question-grid-react">{question.data?.rows.map(row => <Card key={row.group} title={groupLabel(row.group)} extra={<Tag>{statusLabel(row.status)}</Tag>}><p className="answer-text">{row.answer ?? (detail.data?.kind === 'retrieval' ? '此实验只检索，没有生成回答。' : '没有可用回答。')}</p><p className="subtle">初筛：{row.answer_proxy_pass === null ? '未评分' : row.answer_proxy_pass ? '通过' : '未通过'} · 证据：{evidenceLabel(row.evidence_complete)}</p><EvidenceBlocks row={row}/><details><summary>评分参照（不曾发送给模型）</summary><p>{row.expected_abstention ? '期望承认信息不足，不虚构用户事实。' : row.reference_answer ?? '本报告未记录答案参照。'}</p></details>{detail.data?.reviews.map(review => {const item=review.items.find(value => value.method===row.group && value.question_id===questionId); return item ? <details key={`${review.reviewer_kind}:${review.reviewer}`}><summary>{review.reviewer_kind==='human'?'人工':'助手'} · {review.reviewer} · {verdictLabel(item.verdict)}</summary><p>{item.rationale || '尚未填写理由'}</p></details> : null;})}{detail.data?.review_enabled && <ReviewForm runId={selected} questionId={questionId} row={row} detail={detail.data} reviewer={reviewer} onDirty={setReviewDirty}/>}</Card>)}</div>
        </>}
      </section>
    </div>
  </AppShell>;
}
