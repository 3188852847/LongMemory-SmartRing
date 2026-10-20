export const HY_SEMANTIC_TASK_STATES=['pending','running','completed','partial','uncertain','cancelled'] as const;
export type HySemanticTaskState=typeof HY_SEMANTIC_TASK_STATES[number];
export interface HySemanticStatus {
  protocol:2;enabled:boolean;desired_enabled:boolean;mode:'ultra'|'pro';graph_available:boolean;
  task_counts:Partial<Record<HySemanticTaskState,number>>;paused:boolean;last_task_finished_at:string|null;
  management_available:boolean;schema_state:'ready'|'isolated'|'disabled';epoch:number|null;ready_epoch:number|null;
  native_evolve_idempotent:false;automatic_restart_replay:false;
  intention_read:'read_only_expiry_filter_and_dedup'|'disabled';
  expired_intention_policy:'archive_not_assert_completion'|'disabled';
  execution_authorized:false;proactive_contact_enabled:false;
  observed_at:string;runtime:{write_enabled:boolean;use_enabled:boolean};
}
export interface HySemanticTask {
  task_id:string;kind:'evolve'|'intention_maintenance';state:HySemanticTaskState;
  created_at:string;finished_at:string|null;elapsed_ms:number|null;reason_code:string|null;observed_at:string;
}
export class HySemanticContractError extends Error {}
/** 与AI application/semantic_tasks.py的已提交白名单一致。 */
export const hySemanticTaskIdentifier=(value:unknown):value is string=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,96}$/.test(value);
const object=(v:unknown):v is Record<string,unknown>=>Boolean(v)&&typeof v==='object'&&!Array.isArray(v);
const utc=(v:unknown):v is string=>typeof v==='string'&&/(Z|\+00:00)$/.test(v)&&!Number.isNaN(Date.parse(v));
const nullableUtc=(v:unknown)=>v===null||utc(v);
const epoch=(v:unknown)=>v===null||Number.isSafeInteger(v);
const invalid=()=>new HySemanticContractError('语义运行响应与固定协议不一致，未作为能力或任务成功证据。');

/** AI冻结的扁平HTTP导出；不接收任何启用、执行或主动联系授权。 */
export function parseHySemanticStatus(value:unknown):HySemanticStatus {
  if(!object(value)||value.protocol!==2||!utc(value.observed_at)||
    ['enabled','desired_enabled','graph_available','paused','management_available'].some(key=>typeof value[key]!=='boolean')||
    !['ultra','pro'].includes(String(value.mode))||!['ready','isolated','disabled'].includes(String(value.schema_state))||
    !epoch(value.epoch)||!epoch(value.ready_epoch)||!nullableUtc(value.last_task_finished_at)||
    value.native_evolve_idempotent!==false||value.automatic_restart_replay!==false||
    !['read_only_expiry_filter_and_dedup','disabled'].includes(String(value.intention_read))||
    !['archive_not_assert_completion','disabled'].includes(String(value.expired_intention_policy))||
    value.execution_authorized!==false||value.proactive_contact_enabled!==false||
    !object(value.runtime)||typeof value.runtime.write_enabled!=='boolean'||typeof value.runtime.use_enabled!=='boolean'||
    !object(value.task_counts)||Object.entries(value.task_counts).some(([state,count])=>!HY_SEMANTIC_TASK_STATES.includes(state as HySemanticTaskState)||!Number.isSafeInteger(count)||Number(count)<0))throw invalid();
  return value as unknown as HySemanticStatus;
}
export function parseHySemanticTask(value:unknown,id:string):HySemanticTask {
  if(!object(value)||!hySemanticTaskIdentifier(value.task_id)||value.task_id!==id||!['evolve','intention_maintenance'].includes(String(value.kind))||
    !HY_SEMANTIC_TASK_STATES.includes(value.state as HySemanticTaskState)||!utc(value.created_at)||!nullableUtc(value.finished_at)||!utc(value.observed_at)||
    !(value.elapsed_ms===null||typeof value.elapsed_ms==='number'&&Number.isFinite(value.elapsed_ms)&&value.elapsed_ms>=0)||
    !(value.reason_code===null||typeof value.reason_code==='string'&&/^[a-z0-9_-]{1,128}$/i.test(value.reason_code)))throw invalid();
  return value as unknown as HySemanticTask;
}
