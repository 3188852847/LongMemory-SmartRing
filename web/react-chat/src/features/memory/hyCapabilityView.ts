import type {HyLayerPage} from '../../api/hyLayerData';
import type {HyMechanismsSnapshot} from '../../api/hyMechanisms';
import type {HySemanticStatus} from '../../api/hySemantic';

/** 页面内投影，不是新的HTTP/SDK协议；独立消费层内容和已冻结的实例状态。 */
export type HyCapabilityState='configured'|'enabled'|'disabled'|'unknown'|'unsupported'|'failed'|'partial'|'empty'|'present'|'idle'|'pending'|'paused'|'running'|'blocked'|'isolated';
export interface HyCapabilityFact {state:HyCapabilityState;description:string;observed_at:string|null}
export interface HyCapabilityView {
  expected:HyCapabilityFact;instance:HyCapabilityFact;coverage:HyCapabilityFact;
  background:HyCapabilityFact;management:HyCapabilityFact;
}
export interface HyRuntimeGateSnapshot {
  runtime:Pick<HyMechanismsSnapshot['runtime'],'write_enabled'|'use_enabled'>;
  observed_at:string;stale:boolean;
}

/** 缺少实例状态时只投影声明与读覆盖；有状态也不混同配置、后台任务和管理能力。 */
export function hyCapabilityView(page:HyLayerPage,status?:HySemanticStatus):HyCapabilityView {
  const observed_at=page.observed_at;
  const expected:HyCapabilityFact={state:page.generation_state==='configured'?'configured':page.generation_state==='disabled'?'disabled':'unknown',
    description:page.generation_state==='configured'?'生成配置已接入；尚不能证明本实例执行过生成。':page.generation_state==='disabled'?'返回的生成声明为关闭；历史内容仍可能存在。':'生成配置尚不能确认。',observed_at};
  const unavailable=()=>({state:'unknown' as const,description:'当前逐层端点未提供该项实例证据。',observed_at:null});
  const complete=['vdb_complete','graph_complete'].includes(page.coverage);
  const isolated=page.reason_code==='schema_injection_isolated'||page.items.some(item=>item.derivation_state==='isolated');
  const view:HyCapabilityView={expected,instance:unavailable(),background:unavailable(),management:{state:'unknown',description:'逐层只读成功不能证明纠正、删除或后台写入已获准。',observed_at:null},
    coverage:{state:page.read_status==='unavailable'?'blocked':isolated?'isolated':!complete?'partial':page.data_state==='empty'?(page.coverage==='graph_complete'?'unknown':'empty'):page.data_state==='present'?'present':'unknown',
      description:page.read_status==='unavailable'?'本次未取得可安全展示的内容。':isolated?'本页包含已隔离派生；隔离不表示无条目或已关闭。':page.coverage==='graph_only_legacy_vdb_present'?'本页读取原生图库，旧向量 L6 未包含；整体覆盖不完整。':!complete?'本次只读向量范围，图中内容与派生关系尚未确认。':page.data_state==='empty'?'所选读取页未返回条目；不推断派生隔离、其他状态或页。':page.data_state==='present'?'已返回本页保存内容；不证明当前生成或后台任务已成功。':'当前读取范围的内容尚不能确认。',observed_at}};
  if(!status)return view;
  const at=status.observed_at;
  view.expected={state:status.desired_enabled?'configured':'disabled',description:status.desired_enabled?'已请求语义能力；实际初始化与配置分别核对。':'配置未请求语义能力。',observed_at:at};
  view.instance={state:status.enabled?'enabled':status.desired_enabled?'blocked':'disabled',description:status.enabled?`实例已初始化 ${status.mode} 语义能力；原生图库${status.graph_available?'可用':'不可用'}。`:'实例能力未启用；期望配置不能代替实际能力。',observed_at:at};
  const running=status.task_counts.running, pending=status.task_counts.pending;
  view.background={state:running!==undefined&&running>0?'running':status.paused?'paused':pending!==undefined&&pending>0?'pending':running===0&&pending===0?'idle':'unknown',
    description:status.paused?'未认领任务暂停；已认领任务不假称回滚。':running!==undefined&&running>0?'已有任务被认领；是否完成须核对单任务回执。':pending!==undefined&&pending>0?'有等待认领任务，不等于已执行。':'按已返回计数核对，缺键保持未知；历史 partial/uncertain 不自动重放。',observed_at:at};
  view.management={state:status.management_available?'enabled':'blocked',description:status.management_available?'实例报告管理可用；本页仍只读，不产生执行或主动联系授权。':'当前实例未提供管理可用性；不能复用旧证明开启图或后台写入。',observed_at:at};
  if(page.layer==='l6_schema'&&status.schema_state==='isolated')view.coverage={state:'isolated',description:'实例报告图式派生已隔离；不是空层或已关闭，旧派生不能据此获得注入资格。',observed_at:at};
  return view;
}
