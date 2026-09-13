import {useEffect, useRef, useState} from 'react';
import {useMutation, useQuery} from '@tanstack/react-query';
import {Alert, Button, Card, Descriptions, Empty, Select, Space, Tag} from 'antd';
import {ChatApi} from './api';

type Source = {id:string;created_at?:string|null;protocol:string;dataset?:string|null;total:number;report_sha256:string};
type Summary = {total_cases:number;completed_cases:number;false_block_cases:number;unsupported_pass_cases:number;original_candidate_count:number;kept_candidate_count:number;removed_candidate_count:number;candidate_reduction_rate:number|null;context_character_reduction_rate:number|null};
type Replay = {id:string;created_at?:string|null;status:string;source_report_sha256:string;report_sha256:string;summary:Summary};
type Options = {sources:Source[];replays:Replay[];skipped:number};

const percent=(value:number|null|undefined)=>value==null?'不适用':`${(value*100).toFixed(1)}%`;

/** 零模型请求的策略回放独立于可能联网的实验作业，不要求风险确认。 */
export function L1PolicyReplayCard({api,ready}:{api:ChatApi;ready:boolean}) {
  const [source,setSource]=useState('');
  const [notice,setNotice]=useState('正在读取冻结 L1 充分性档案…');
  const requestId=useRef('');
  const options=useQuery({queryKey:['l1-policy-replay'],queryFn:()=>api.request<Options>('/api/l1-policy-replay'),enabled:ready});
  useEffect(()=>{
    if(!options.data)return;
    setSource(value=>options.data!.sources.some(item=>item.id===value)?value:(options.data!.sources[0]?.id??''));
    setNotice(options.data.sources.length?'选择冻结来源后可在本机离线回放；不会调用模型或修改日常召回。':'尚无可回放的已完成 L1 充分性报告。');
  },[options.data]);
  const run=useMutation({mutationFn:()=>{
    if(!requestId.current)requestId.current=crypto.randomUUID();
    return api.request<{id:string;replayed:boolean;status:string;summary:Summary}>('/api/l1-policy-replay','POST',{source_id:source,request_id:requestId.current});
  },onMutate:()=>setNotice('正在核对冻结来源并计算策略代理；没有模型请求。'),onSuccess:async result=>{
    requestId.current='';
    setNotice(result.replayed?'已找到同一请求的既有结果，没有重复生成。':'离线回放完成；日常 L1 仍未启用门控。');
    await options.refetch();
  },onError:()=>setNotice('离线回放未完成。请刷新档案并核对来源是否仍完整；没有自动重试。')});
  const selectedSource=options.data?.sources.find(item=>item.id===source);
  const latest=options.data?.replays.find(item=>item.source_report_sha256===selectedSource?.report_sha256);
  return <Card className="experiment-detail-card" title="L1 证据门控离线回放" extra={<Tag color="cyan">0 次模型请求</Tag>}>
    <Alert showIcon type="info" title="先看策略影响，不直接上线" description="把已有模型判定当作假设门控，统计误拦截、无证据误放行和上下文缩减。合成结果不是端到端回答质量。"/>
    <Space wrap>
      <Select aria-label="L1 回放来源" value={source||undefined} style={{minWidth:360}} placeholder="选择冻结充分性报告" options={(options.data?.sources??[]).map(item=>({value:item.id,label:`${item.dataset??'未知数据集'} · ${item.total} 题 · ${item.id.slice(-8)}`}))} onChange={value=>{requestId.current='';setSource(value);}}/>
      <Button loading={run.isPending} disabled={!source||run.isPending} onClick={()=>run.mutate()}>运行本地回放</Button>
    </Space>
    <p className="subtle" role="status">{notice}{options.data?.skipped?` ${options.data.skipped} 条损坏或不兼容档案已跳过。`:''}</p>
    {!latest?<Empty description="还没有 L1 策略回放结果"/>:<>
      <Descriptions size="small" bordered column={{xs:1,sm:2,md:4}} items={[
        {key:'completed',label:'完成题数',children:`${latest.summary.completed_cases}/${latest.summary.total_cases}`},
        {key:'false-block',label:'误拦截代理',children:latest.summary.false_block_cases},
        {key:'unsafe-pass',label:'无证据误放行',children:latest.summary.unsupported_pass_cases},
        {key:'reduction',label:'候选缩减',children:`${latest.summary.removed_candidate_count}/${latest.summary.original_candidate_count}（${percent(latest.summary.candidate_reduction_rate)}）`},
        {key:'characters',label:'上下文字符缩减',children:percent(latest.summary.context_character_reduction_rate)},
        {key:'run',label:'最新档案',children:<code>{latest.id}</code>},
      ]}/>
    </>}
  </Card>;
}
