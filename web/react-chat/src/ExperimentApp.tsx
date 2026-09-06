import {useEffect, useMemo, useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Alert, Button, Card, Descriptions, Empty, Input, List, Select, Space, Table, Tag} from 'antd';
import {ChatApi} from './api';
import {AppShell, ConsoleNav} from './AppShell';
import {evidenceLabel, filterRuns, groupLabel, statusLabel, verdictLabel} from '../../assets/experiment-view.mjs';

type Run = {id:string; kind:string; provider?:string; model?:string; dataset:string; split:string; status:string; completed:number; total:number; started_at:string};
type Group = {id:string; completed:number; total:number; answer_scored:boolean; answer_pass:number; evidence_scored:number; evidence_pass:number};
type ReviewItem = {method:string; question_id:string; verdict:string; rationale?:string};
type Review = {reviewer_kind:string; reviewer:string; summary:Record<string,{pass:number; total:number; pending:number; unscorable:number}>; items:ReviewItem[]};
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

/** 第一切片只读取既有报告；运行与人工复核在契约迁移完成前继续使用原版。 */
export function ExperimentApp() {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState('');
  const [questionId, setQuestionId] = useState('');
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
  const sidebar = <><ConsoleNav active="experiments" legacyPath="/experiments"/><Card size="small" title="迁移状态"><p>当前 React 页只读。启动实验和保存人工复核仍在原版，避免过渡期改变预算与幂等语义。</p><Button href="/experiments">打开完整原版</Button></Card></>;

  return <AppShell subtitle="冻结档案与逐题证据" className="experiment-shell" sidebar={sidebar}>
    <header><div><h1>实验中心</h1><p className="subtle">查看不会调用模型；动态回答和记忆按文本渲染。</p></div><Button loading={runs.isFetching} disabled={!session.isSuccess} onClick={() => void runs.refetch()}>刷新档案</Button></header>
    {(session.isError || runs.isError) && <Alert type="error" showIcon title="实验档案读取失败" description="请确认本机控制台仍在运行；没有自动启动或重试任何模型实验。"/>}
    <div className="experiment-layout">
      <Card title="实验档案">
        <Input.Search aria-label="搜索实验" allowClear value={query} onChange={event => {setQuery(event.target.value); setPage(0);}} placeholder="模型、数据集或编号"/>
        <Select className="wide" aria-label="实验类型" value={filter} onChange={value => {setFilter(value); setPage(0);}} options={[{value:'all',label:'全部'},{value:'real',label:'真实模型回答'},{value:'fake',label:'Fake 工程验证'},{value:'retrieval',label:'仅检索'}]}/>
        <List loading={runs.isLoading} dataSource={filtered.slice(page*10,page*10+10)} locale={{emptyText:<Empty description="没有匹配的实验"/>}} renderItem={run => <List.Item className="memory-item" onClick={() => setSelected(run.id)}><List.Item.Meta title={<Space><Tag>{run.kind === 'retrieval' ? '仅检索' : run.provider === 'fake' ? 'Fake' : '真实回答'}</Tag>{run.model ?? '模型未提供'}</Space>} description={<>{dateText(run.started_at)}<br/>{run.dataset} · {run.split} · {statusLabel(run.status)} {run.completed}/{run.total}<br/>{run.id.slice(-8)}</>}/></List.Item>}/>
        <div className="pagination"><Button disabled={page===0} onClick={() => setPage(page-1)}>上一页</Button><span>{filtered.length} 条 · {filtered.length ? page+1 : 0}/{pages}</span><Button disabled={(page+1)*10>=filtered.length} onClick={() => setPage(page+1)}>下一页</Button></div>
        {runs.data && <small>{runs.data.skipped ? `${runs.data.skipped} 条无法读取，未计为通过。` : ''}{runs.data.limited ? ' 超过 500 条，仅展示限定范围。' : ''}</small>}
      </Card>
      <section>
        {!selected ? <Card><Empty description="选择一条实验查看结果"/></Card> : <>
          <Card loading={detail.isLoading} title={detail.data?.kind === 'retrieval' ? '冻结检索对照' : '逐题回答对照'}>
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
          {detail.data && <Card className="question-select" title="逐题对照"><Select className="wide" aria-label="逐题对照" value={questionId || undefined} options={detail.data.questions.map(item => ({value:item.id,label:item.query}))} onChange={setQuestionId}/><p className="subtle">{question.data?.source_note}</p></Card>}
          <div className="question-grid-react">{question.data?.rows.map(row => <Card key={row.group} title={groupLabel(row.group)} extra={<Tag>{statusLabel(row.status)}</Tag>}><p className="answer-text">{row.answer ?? (detail.data?.kind === 'retrieval' ? '此实验只检索，没有生成回答。' : '没有可用回答。')}</p><p className="subtle">初筛：{row.answer_proxy_pass === null ? '未评分' : row.answer_proxy_pass ? '通过' : '未通过'} · 证据：{evidenceLabel(row.evidence_complete)}</p><EvidenceBlocks row={row}/><details><summary>评分参照（不曾发送给模型）</summary><p>{row.expected_abstention ? '期望承认信息不足，不虚构用户事实。' : row.reference_answer ?? '本报告未记录答案参照。'}</p></details>{detail.data?.reviews.map(review => {const item=review.items.find(value => value.method===row.group && value.question_id===questionId); return item ? <details key={`${review.reviewer_kind}:${review.reviewer}`}><summary>{review.reviewer_kind==='human'?'人工':'助手'} · {review.reviewer} · {verdictLabel(item.verdict)}</summary><p>{item.rationale || '尚未填写理由'}</p></details> : null;})}</Card>)}</div>
        </>}
      </section>
    </div>
  </AppShell>;
}
