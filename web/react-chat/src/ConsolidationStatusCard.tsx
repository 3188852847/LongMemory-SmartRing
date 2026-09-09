import {useQuery} from '@tanstack/react-query';
import {Alert, Button, Card, Descriptions, Space, Tag} from 'antd';
import {Link} from 'react-router-dom';
import {ApiError, ChatApi} from './api';

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
  risk_assessment_incomplete:'风险评估尚未完成',
};
const stageName:Record<StageName,string> = {l1_to_l2:'L1 → L2 场景整理',l2_to_l3:'L2 → L3 画像整理'};
const outcomeName:Record<string,string> = {
  scenario_activated:'场景记忆已更新', persona_activated:'用户画像已更新', persona_noop:'画像无需更新',
  no_coherent_group:'没有形成可靠场景', scenario_sensitive_content:'候选包含敏感内容，未写入',
  scenario_proposal_generation_failed:'场景候选生成失败，未写入', risk_review_failed:'风险复核失败，未写入',
  model_request_failed:'模型请求失败，未写入', process_interrupted:'上次进程中断，未完成',
};

function useConsolidationStatus(enabled:boolean) {
  return useQuery({queryKey:['consolidation-status'],enabled,
    queryFn:()=>api.request<StatusResponse>('/api/consolidation-status'),refetchInterval:30_000});
}

function stageItems(item:StageStatus) {
  return [
    {key:'reason',label:'当前判断',children:reasonName[item.trigger_reason]??'状态原因暂未识别'},
    {key:'pending',label:'新来源',children:`${item.pending_new_source_count} / 门槛 ${item.minimum_new_sources}`},
    {key:'budget',label:'今日模型预算',children:`剩余 ${item.remaining_model_calls_today} / ${item.daily_model_call_budget}`},
    {key:'latest',label:'最近结果',children:item.latest_run?.outcome_code ? (outcomeName[item.latest_run.outcome_code]??'整理已结束，结果类别暂未识别') : '尚无运行记录'},
  ];
}

export function consolidationStatusFailure(error: unknown) {
  if (error instanceof ApiError && error.status === 404) return '当前控制台版本没有提供自动整理状态接口。请核对启动服务与页面版本。';
  if (error instanceof ApiError && ['database_missing', 'memory_database_missing'].includes(error.code)) {
    return '当前记忆数据库不存在，自动整理尚未开始。请先核对启动面板中的数据库路径。';
  }
  return '暂时无法读取自动整理状态。请检查控制台服务和记忆数据库；页面会稍后再读取。';
}

/** 只展示持久账本，不提供绕过风险门控的“立即执行”按钮。 */
export function ConsolidationStatusCard({stage,enabled}:{stage:StageName;enabled:boolean}) {
  const query = useConsolidationStatus(enabled);
  if(query.error) return <Alert type="warning" showIcon title="暂时无法读取自动整理状态" description={consolidationStatusFailure(query.error)}/>;
  const item = query.data?.stages.find(value=>value.stage===stage);
  return <Card className="mode-card" size="small" title={stageName[stage]}
    extra={<Tag color={query.data?.background_enabled?'green':'default'}>{query.data?.background_enabled?'后台已启用':'后台尚未启用'}</Tag>}>
    {!item?<p>{query.isFetching?'正在读取整理账本…':'没有该阶段的状态记录。'}</p>:<Descriptions size="small" column={{xs:1,sm:2,md:4}} items={stageItems(item)}/>}
    {!query.data?.background_enabled&&<small>达到门槛只表示“可以评估是否运行”；当前不会自动调用模型或改写记忆。</small>}
  </Card>;
}

/**
 * 把两级低频整理放在日常回顾旁统一解释。
 * 这里仍然只读：真正生成候选与接受候选继续留在各层级页面，避免把“达到门槛”误解成自动写入。
 */
export function ConsolidationOverview({enabled}:{enabled:boolean}) {
  const query=useConsolidationStatus(enabled);
  if(query.error) return <Alert type="warning" showIcon title="暂时无法读取低频整理状态" description={consolidationStatusFailure(query.error)}/>;
  return <Card className="mode-card" title="低频记忆整理"
    extra={<Tag color={query.data?.background_enabled?'green':'default'}>{query.data?.background_enabled?'后台已启用':'后台尚未启用'}</Tag>}>
    <p className="subtle">这里只查看 L1 → L2 → L3 的整理条件与模型调用预算，不会因为打开页面而调用模型或改写记忆。达到门槛只表示具备评估条件，不代表正在运行。</p>
    {query.isFetching&&!query.data&&<p>正在读取整理账本…</p>}
    <div className="consolidation-overview-grid">
      {(['l1_to_l2','l2_to_l3'] as StageName[]).map(stage=>{
        const item=query.data?.stages.find(value=>value.stage===stage);
        return <section key={stage} className="consolidation-stage" aria-label={stageName[stage]}>
          <h3>{stageName[stage]}</h3>
          {item?<Descriptions size="small" column={1} items={stageItems(item)}/>:<p className="subtle">{query.data?'没有该阶段的状态记录。':'等待整理账本。'}</p>}
        </section>;
      })}
    </div>
    <Space wrap>
      <Link to="/scenarios"><Button>查看与复核 L2</Button></Link>
      <Link to="/personas"><Button>查看与复核 L3</Button></Link>
    </Space>
  </Card>;
}
