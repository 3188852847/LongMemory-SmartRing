import {Alert,Button} from 'antd';
import type {HyLayerPage} from '../../api/hyLayerData';
import type {HySemanticStatus,HySemanticTask} from '../../api/hySemantic';
import {memoryTime} from './HyMemoryWorkspace';
import {hyCapabilityView,type HyCapabilityView,type HyCapabilityState,type HyRuntimeGateSnapshot} from './hyCapabilityView';
import {HySemanticTaskView,semanticReadFailure,semanticTaskStates} from './HySemanticTaskView';

const labels:Record<HyCapabilityState,string>={configured:'已配置',enabled:'已启用',disabled:'未启用',unknown:'未知',unsupported:'不支持',failed:'失败',partial:'部分覆盖',empty:'无条目',present:'有已保存内容',idle:'空闲',pending:'等待认领',paused:'已暂停',running:'运行中',blocked:'受限',isolated:'派生已隔离'};
const axes=[['expected','期望配置'],['instance','实例实际能力'],['coverage','证据与条目覆盖'],['background','后台任务'],['management','管理可用性']] as const;

/** 受控、只读；不采样、不轮询、不启用机制，也不把未知证据投影成成功。 */
export interface HyLayerStatusProps {
  page:HyLayerPage;capabilities?:HyCapabilityView;runtimeSnapshot?:HyRuntimeGateSnapshot;
  semanticSnapshot?:HySemanticStatus;loading?:boolean;error?:unknown;readDisabled?:boolean;onRead?:()=>void;
  taskId?:string;task?:HySemanticTask;taskLoading?:boolean;taskError?:unknown;onTaskRead?:(id:string)=>void;
}
export function HyLayerStatus({page,capabilities,runtimeSnapshot,semanticSnapshot,loading=false,error,readDisabled=false,onRead,taskId='',task,taskLoading=false,taskError,onTaskRead}:HyLayerStatusProps) {
  if(!['l6_schema','l7_intention'].includes(page.layer))return null;
  const view=capabilities??hyCapabilityView(page,semanticSnapshot);
  const gates=semanticSnapshot?{runtime:semanticSnapshot.runtime,observed_at:semanticSnapshot.observed_at,stale:Boolean(error)||loading}:runtimeSnapshot;
  return <details className="hy-layer-capability" aria-label="分层接入与运行证据">
    <summary>接入与运行证据 <span>配置：{labels[view.expected.state]}；内容：{labels[view.coverage.state]}</span></summary>
    {onRead&&<Button aria-label={semanticSnapshot?'刷新实例状态':'读取实例状态'} loading={loading} disabled={readDisabled} onClick={onRead}>{semanticSnapshot?'刷新实例状态':'读取实例状态'}</Button>}
    {Boolean(error)&&<Alert type="warning" title={semanticSnapshot?'未取得新实例状态，以下保留上次快照':'实例能力尚未确认'} description={semanticReadFailure(error)}/>}
    {loading&&<p role="status">正在读取实例证据；已有状态为上次快照。</p>}
    <dl>{axes.map(([axis,title])=><div key={axis}><dt>{title}</dt><dd><strong>{labels[view[axis].state]}</strong><p>{view[axis].description}</p><small>{view[axis].observed_at?`证据读取于 ${memoryTime(view[axis].observed_at)}`:'该项证据时间未提供'}</small></dd></div>)}</dl>
    <p>{gates?<>{gates.stale?'上次':'本次'}运行开关快照：写入{gates.runtime.write_enabled?'开启':'暂停'}，回答使用{gates.runtime.use_enabled?'开启':'暂停'}；读取于 {memoryTime(gates.observed_at)}。</>:'运行开关快照尚未提供。'} 开关开启不等于 L6/L7 生成、管理或注入已成功。</p>
    {semanticSnapshot&&<section aria-label="原生语义状态细节"><p>图式派生状态：{semanticSnapshot.schema_state==='ready'?'同代次可用':semanticSnapshot.schema_state==='isolated'?'已隔离':'未启用'}。图式代次 {semanticSnapshot.epoch??'未提供'}；可用代次 {semanticSnapshot.ready_epoch??'未提供'}。页面内容与实例状态分别读取，不是冻结快照。</p>
      <p>最近任务完成于 {memoryTime(semanticSnapshot.last_task_finished_at)}；这不是条目更新时间或引擎健康结论。</p>
      <dl>{Object.entries(semanticSnapshot.task_counts).map(([state,count])=><div key={state}><dt>{semanticTaskStates[state as keyof typeof semanticTaskStates]}</dt><dd>{count}</dd></div>)}</dl><p>未返回的任务状态计数保持未知，不补零；原生归纳不保证幂等，重启不自动重放。</p>
      <p>{semanticSnapshot.intention_read==='read_only_expiry_filter_and_dedup'?'意图读取使用只读到期过滤与去重。':'当前意图读取关闭。'}{semanticSnapshot.expired_intention_policy==='archive_not_assert_completion'?' 到期维护采用归档，不断言完成。':' 当前到期维护策略关闭。'} 执行与主动联系均未授权。</p>
    </section>}
    <p>{page.items.some(item=>item.semantic_kind)?'逐条原生更新时间见记录；未知值保持未知，存储时间、有效期和本页读取时间分别核对。':'原生最后更新时间尚未提供；存储时间、有效期和本页读取时间分别核对。'}</p>
    {onTaskRead&&<HySemanticTaskView key={taskId} id={taskId} task={task} loading={taskLoading} error={taskError} disabled={readDisabled||loading} onRead={onTaskRead}/>}
    <p aria-label="延迟测量证据状态">本页尚无统一阶段测量证据；任务耗时不能代表用户说完到首个有效回答声音。</p>
  </details>;
}
