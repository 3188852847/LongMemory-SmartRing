import {useQuery} from '@tanstack/react-query';
import {Alert, Card, Descriptions, Tag} from 'antd';
import {ChatApi} from './api';

type StageName = 'l1_to_l2' | 'l2_to_l3';
type StageStatus = {
  stage: StageName; pending_new_source_count: number; trigger_action: 'run'|'hold'|'block';
  trigger_reason: string; minimum_new_sources: number; maximum_sources_per_run: number;
  cooldown_seconds: number; daily_model_call_budget: number; model_calls_today: number;
  remaining_model_calls_today: number; cursor: {recorded_at:string;source_id:string}|null;
  latest_run: {status:string;outcome_code:string|null;finished_at:string|null;source_count:number;model_call_count:number}|null;
};
type StatusResponse = {background_enabled:boolean;stages:StageStatus[]};

const api = new ChatApi();
const reasonName:Record<string,string> = {
  ready:'已达到触发门槛', no_pending_evidence:'没有新的可整理来源',
  below_source_threshold:'新来源尚未达到门槛', cooldown_active:'仍在冷却时间内',
  daily_budget_exhausted:'今天的模型调用预算已用完', run_already_active:'已有一次整理正在运行',
};
const stageName:Record<StageName,string> = {l1_to_l2:'L1 → L2 场景整理',l2_to_l3:'L2 → L3 画像整理'};

/** 只展示持久账本，不提供绕过风险门控的“立即执行”按钮。 */
export function ConsolidationStatusCard({stage,enabled}:{stage:StageName;enabled:boolean}) {
  const query = useQuery({queryKey:['consolidation-status'],enabled,
    queryFn:()=>api.request<StatusResponse>('/api/consolidation-status'),refetchInterval:30_000});
  if(query.error) return <Alert type="warning" showIcon title="暂时无法读取自动整理状态" description={String(query.error)}/>;
  const item = query.data?.stages.find(value=>value.stage===stage);
  return <Card className="mode-card" size="small" title={stageName[stage]}
    extra={<Tag color={query.data?.background_enabled?'green':'default'}>{query.data?.background_enabled?'后台已启用':'后台尚未启用'}</Tag>}>
    {!item?<p>{query.isFetching?'正在读取整理账本…':'没有该阶段的状态记录。'}</p>:<Descriptions size="small" column={{xs:1,sm:2,md:4}} items={[
      {key:'reason',label:'当前判断',children:reasonName[item.trigger_reason]??item.trigger_reason},
      {key:'pending',label:'新来源',children:`${item.pending_new_source_count} / 门槛 ${item.minimum_new_sources}`},
      {key:'budget',label:'今日模型预算',children:`剩余 ${item.remaining_model_calls_today} / ${item.daily_model_call_budget}`},
      {key:'latest',label:'最近结果',children:item.latest_run?.outcome_code??'尚无运行记录'},
    ]}/>}
    {!query.data?.background_enabled&&<small>达到门槛只表示“可以评估是否运行”；当前不会自动调用模型或改写记忆。</small>}
  </Card>;
}
