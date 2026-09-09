import {useEffect, useState} from 'react';
import {Alert, Button, Card, Empty, List, Select, Space, Statistic, Tag} from 'antd';
import {Link} from 'react-router-dom';
import {ChatApi, type MemoryFeedbackDiagnosticFocus, type MemoryFeedbackIndex, type MemoryFeedbackKind} from './api';
import {AppShell, ConsoleNav} from './AppShell';
import {PageHeader} from './PageHeader';

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
const emptyCounts = {memory_ok:0,recall_miss:0,wrong_memory:0,memory_irrelevant:0};

/** 所有者跨日查看人工标注；列表只接收定位元数据，正文仍留在原聊天轨迹。 */
export function MemoryQualityApp() {
  const [filter,setFilter] = useState<Filter>('issues');
  const [page,setPage] = useState<MemoryFeedbackIndex>({kind:'issues',counts:emptyCounts,total:0,offset:0,limit:25,items:[]});
  const [busy,setBusy] = useState(true);
  const [notice,setNotice] = useState('正在读取当前有效判断…');

  async function load(nextFilter=filter,offset=0) {
    setBusy(true);
    try {
      const params = new URLSearchParams({kind:nextFilter,offset:String(offset),limit:'25'});
      setPage(await api.request<MemoryFeedbackIndex>(`/api/chat-memory-feedback?${params}`));
      setNotice('质量样本已更新；列表没有复制聊天正文。');
    } catch {
      setNotice('无法读取质量样本。请确认控制台仍在运行，然后刷新；没有自动重试。');
    } finally {setBusy(false);}
  }

  useEffect(()=>{void (async()=>{
    try {await api.bootstrap();await load('issues',0);}
    catch {setNotice('无法建立本机控制台会话，请刷新页面。');setBusy(false);}
  })();},[]);

  const sidebar = <ConsoleNav active="quality" legacyPath="/memories"/>;
  return <AppShell subtitle="跨日期的记忆诊断样本" className="quality-shell" sidebar={sidebar}>
    <PageHeader eyebrow="长期记忆" title="记忆质量样本" description="集中查看你已经确认的记忆问题，并回到原回答核对实际召回与注入证据。" action={<Button loading={busy} onClick={()=>void load(filter,page.offset)}>刷新</Button>}/>
    <Alert showIcon type="info" title="这是人工诊断队列，不是准确率报告" description="默认只显示‘没想起’和‘错误记忆’。排查方向由可见轨迹生成，不代表系统已经确认根因，也不会触发模型、重答或记忆修改。"/>
    <section className="quality-counts" aria-label="当前有效判断总览">
      <Card><Statistic title="没想起" value={page.counts.recall_miss}/></Card>
      <Card><Statistic title="错误记忆" value={page.counts.wrong_memory}/></Card>
      <Card><Statistic title="正常对照" value={page.counts.memory_ok}/></Card>
      <Card><Statistic title="记忆无关" value={page.counts.memory_irrelevant}/></Card>
    </section>
    <Card className="quality-list-card" title="当前有效判断" extra={<Select aria-label="质量样本筛选" value={filter} disabled={busy} style={{width:190}} options={[
      {value:'issues',label:'需要核对的问题'}, {value:'recall_miss',label:'只看没想起'},
      {value:'wrong_memory',label:'只看错误记忆'}, {value:'memory_ok',label:'正常对照'},
      {value:'memory_irrelevant',label:'记忆无关负例'}, {value:'all',label:'全部当前判断'},
    ]} onChange={(value:Filter)=>{setFilter(value);void load(value,0);}}/>}>
      <List loading={busy} dataSource={page.items} locale={{emptyText:<Empty description={filter==='issues'?'目前没有待核对问题':'没有符合筛选的当前判断'}/>}} renderItem={item=><List.Item actions={[<Link key="inspect" to={`/chat-react?chat_id=${encodeURIComponent(item.chat_id)}&request_id=${encodeURIComponent(item.request_id)}`}>核对回答与证据</Link>]}>
        <List.Item.Meta title={<Space wrap><Tag color={item.kind==='wrong_memory'?'red':item.kind==='recall_miss'?'gold':item.kind==='memory_ok'?'green':'default'}>{kindLabel[item.kind]}</Tag><span>{item.chat_title}</span></Space>} description={<div className="quality-sample-description"><p>{focusLabel[item.diagnostic_focus]}</p><Space wrap><span>{new Date(item.occurred_at).toLocaleString('zh-CN')}</span><code>修订 {item.revision}</code><span>L1 {item.retrieved_counts.l1} · L2 {item.retrieved_counts.l2} · L3 {item.retrieved_counts.l3}</span></Space></div>}/>
      </List.Item>}/>
      <div className="pagination"><Button disabled={busy||page.offset===0} onClick={()=>void load(filter,Math.max(0,page.offset-page.limit))}>上一页</Button><span>{page.total?`${page.offset+1}–${Math.min(page.offset+page.limit,page.total)} / ${page.total}`:'0 条'}</span><Button disabled={busy||page.offset+page.limit>=page.total} onClick={()=>void load(filter,page.offset+page.limit)}>下一页</Button></div>
    </Card>
    <p className="memory-status" role="status">{notice}</p>
  </AppShell>;
}
