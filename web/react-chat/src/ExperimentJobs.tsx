import {useEffect, useMemo, useRef, useState} from 'react';
import {useMutation, useQuery} from '@tanstack/react-query';
import {Alert, Button, Card, Checkbox, InputNumber, Modal, Progress, Select, Space, Tag} from 'antd';
import {ChatApi} from './api';
import {groupLabel} from '../../assets/experiment-view.mjs';
import {jobStatus, progressText, quoteText} from '../../assets/experiment-jobs.mjs';

type Retrieval = {id:string; dataset:string; started_at:string};
type Options = {enabled:boolean; real_available:boolean; real_model?:string|null; retrievals:Retrieval[]; context_default:number; context_max:number};
type Model = {provider:string; model:string; timeout_seconds:number; max_tokens:number};
type Quote = {quote_id:string; retrieval_id:string; groups:string[]; question_count:number; total:number; context_chars:number; model:Model; network:boolean; endpoint_host?:string|null; insecure_http:boolean; expires_in_seconds:number};
type Job = {id:string; status:string; model:Model; total:number; attempts:number; completed:number; failed:number; report_id?:string|null; error?:string|null};
type Jobs = {items:Job[]};

const active = (job?:Job|null) => Boolean(job && ['queued','running','stopping'].includes(job.status));
const dateText = (value:string) => {const date = new Date(value); return Number.isNaN(date.getTime()) ? '时间未提供' : date.toLocaleString('zh-CN');};

/**
 * 实验作业属于可能联网、计费的写操作：预检和启动故意分成两次请求。
 * 页面只轮询 GET；启动失败后保留同一 requestId，由用户核对后才可能手动重发。
 */
export function ExperimentJobs({api, ready, onOpen}: {api:ChatApi; ready:boolean; onOpen:(reportId:string)=>void}) {
  const [source, setSource] = useState('');
  const [provider, setProvider] = useState('fake');
  const [budget, setBudget] = useState(4000);
  const [quote, setQuote] = useState<Quote|null>(null);
  const [consent, setConsent] = useState(false);
  const [notice, setNotice] = useState('正在读取运行配置…');
  const [startUnknown, setStartUnknown] = useState(false);
  const requestId = useRef('');

  const options = useQuery({queryKey:['experiment-job-options'], queryFn:() => api.request<Options>('/api/experiment-jobs/options'), enabled:ready});
  const jobs = useQuery({queryKey:['experiment-jobs'], queryFn:() => api.request<Jobs>('/api/experiment-jobs'), enabled:ready,
    refetchInterval: query => active((query.state.data as Jobs|undefined)?.items[0]) ? 2000 : false});
  const current = jobs.data?.items[0];
  useEffect(() => {
    if (!options.data) return;
    setBudget(options.data.context_default);
    setSource(value => options.data!.retrievals.some(item => item.id === value) ? value : (options.data!.retrievals[0]?.id ?? ''));
    setNotice(!options.data.enabled ? '当前服务仅查看档案。需从启动面板启用实验运行，才可预检和启动。'
      : !options.data.retrievals.length ? '尚无已完成的开发集冻结检索档案。'
      : '先核对预算，再确认启动。刷新或关闭网页不会取消已经启动的任务。');
  }, [options.data]);

  const prepare = useMutation({mutationFn:() => api.request<Quote>('/api/experiment-jobs/prepare','POST',{retrieval_id:source,provider,context_chars:budget}),
    onMutate:() => setNotice('正在本机校验来源与预算；这一步不调用模型。'),
    onSuccess:value => {setQuote(value); setConsent(false); setStartUnknown(false); requestId.current=crypto.randomUUID(); setNotice('预检完成，尚未启动；报价 10 分钟后失效。');},
    onError:error => setNotice(`${String(error)} 未启动实验。`)});
  const start = useMutation({mutationFn:() => api.request<Job>('/api/experiment-jobs/start','POST',{
      quote_id:quote!.quote_id, request_id:requestId.current, confirm:true,
      allow_network:quote!.network, allow_http:quote!.insecure_http,
    }),
    onSuccess:async value => {setQuote(null); setConsent(false); setStartUnknown(false); setNotice('实验已启动；页面只读刷新进度，不会重放启动请求。'); await jobs.refetch(); if (!active(value) && value.report_id) onOpen(value.report_id);},
    onError:async error => {setStartUnknown(true); setNotice(`${String(error)} 启动结果可能未知；未自动重发。请先刷新任务核对。`); await jobs.refetch();}});
  const stop = useMutation({mutationFn:(id:string) => api.request(`/api/experiment-jobs/${id}/stop`,'POST',{}),
    onSuccess:async () => {setNotice('已请求停止后续题目；当前已经发出的一次请求仍可能完成或计费。'); await jobs.refetch();},
    onError:error => setNotice(`${String(error)} 未自动重复停止请求。`)});

  const busy = prepare.isPending || start.isPending || stop.isPending;
  const progress = current?.total ? Math.round(100*(current.completed+current.failed)/current.total) : 0;
  const risk = useMemo(() => !quote ? '' : !quote.network
    ? 'Fake 不联网，只验证工程流程，不能评价记忆质量。'
    : quote.insecure_http
      ? '将通过明文 HTTP 发送凭据、合成问题和记忆。只应在已确认风险的校园网运行。'
      : '将向配置的模型服务发送凭据、合成问题和记忆，可能产生费用。', [quote]);

  async function refreshAfterUnknown() {
    const result = await jobs.refetch();
    const expected = requestId.current.replaceAll('-','');
    const found = result.data?.items.find(item => item.id === expected);
    if (found) {setQuote(null); setStartUnknown(false); setNotice('已找到同一请求对应的任务，没有重复启动。');}
    else if (!result.error) {setStartUnknown(false); setNotice('任务台账中未找到同一请求；如需继续，可用同一请求编号再次确认，后端会做幂等检查。');}
  }

  return <Card className="experiment-jobs" title="运行回答对照" extra={<Tag color={active(current)?'processing':'default'}>{current ? jobStatus(current.status) : '没有任务'}</Tag>}>
    <p className="subtle">复用冻结记忆和检索，只重新生成回答；固定开发集，不提取、不编码、不写个人记忆。</p>
    {(options.isError || jobs.isError) && <Alert type="error" showIcon title="任务配置读取失败" description="没有自动启动、停止或重试实验。"/>}
    <div className="job-controls">
      <label>冻结检索档案</label><Select aria-label="冻结检索档案" value={source || undefined} disabled={busy || active(current)} options={(options.data?.retrievals ?? []).map(item => ({value:item.id,label:`${item.id.slice(-8)} · ${item.dataset} · ${dateText(item.started_at)}`}))} onChange={setSource}/>
      <label>回答模型</label><Select aria-label="回答模型" value={provider} disabled={busy || active(current)} options={[{value:'fake',label:'Fake（只验证流程）'},{value:'openai_compatible',label:options.data?.real_available ? `${options.data.real_model}（真实模型）` : '兼容模型（未配置）',disabled:!options.data?.real_available}]} onChange={setProvider}/>
      <label>记忆上限（字符）</label><InputNumber aria-label="记忆上限" min={1} max={options.data?.context_max ?? 16000} value={budget} disabled={busy || active(current)} onChange={value => setBudget(value ?? 4000)}/>
      <Button type="primary" loading={prepare.isPending} disabled={!options.data?.enabled || !source || busy || active(current)} onClick={() => prepare.mutate()}>预检与核对预算</Button>
    </div>
    <p role="status" className="subtle">{notice}</p>
    {current && <div className="job-current"><h3>{jobStatus(current.status)} · {current.model.model} · {current.id.slice(-8)}</h3><Progress percent={progress}/><p className="subtle">{progressText(current)}{current.error ? ` 状态说明：${current.error}；不会自动重试。` : ''}</p><Space wrap>
      <Button loading={jobs.isFetching} onClick={() => void jobs.refetch()}>刷新任务</Button>
      <Button danger disabled={!active(current) || current.status==='stopping' || stop.isPending} onClick={() => {if(confirm('停止尚未开始的题目？已发出的一次请求可能完成或计费，结果会保留。')) stop.mutate(current.id);}}>停止后续请求</Button>
      <Button type="primary" disabled={!current.report_id || active(current)} onClick={() => current.report_id && onOpen(current.report_id)}>打开结果</Button>
    </Space></div>}
    <Modal title="核对这一次实验" open={Boolean(quote)} closable={!start.isPending} mask={{closable:!start.isPending}} keyboard={!start.isPending} onCancel={() => {if(!start.isPending){setQuote(null);setConsent(false);setStartUnknown(false);}}}
      footer={<Space><Button disabled={start.isPending} onClick={() => {setQuote(null);setConsent(false);setStartUnknown(false);}}>返回修改</Button>{startUnknown && <Button loading={jobs.isFetching} onClick={() => void refreshAfterUnknown()}>只刷新任务并核对</Button>}<Button type="primary" loading={start.isPending} disabled={!consent || startUnknown} onClick={() => start.mutate()}>确认启动</Button></Space>}>
      {quote && <><p>{quoteText(quote)}</p><p className="subtle">输入档案：{quote.retrieval_id}。{quote.groups.map(groupLabel).join('；')}</p><Alert type={quote.network?'warning':'info'} showIcon title={risk}/><p className="subtle">预算是请求次数上限，不是费用报价；字符不等于 token。失败不重试，真实模型结果仍需逐题复核。</p><Checkbox checked={consent} disabled={start.isPending || startUnknown} onChange={event => setConsent(event.target.checked)}>我已核对模型、预算与网络风险，启动这一次实验。</Checkbox></>}
    </Modal>
  </Card>;
}
