import type {HySemanticStatus,HySemanticTask} from '../../api/hySemantic';

/** AB候选 + AI扁平HTTP导出的纯合成样例，不是真实实例证明。 */
export function semanticStatusFixture(patch:Partial<HySemanticStatus>={}):HySemanticStatus {
  return {protocol:2,enabled:true,desired_enabled:true,mode:'ultra',graph_available:true,
    task_counts:{pending:0,running:0,completed:1},paused:false,last_task_finished_at:'2026-10-21T04:00:00Z',
    management_available:true,schema_state:'ready',epoch:1,ready_epoch:1,native_evolve_idempotent:false,automatic_restart_replay:false,
    intention_read:'read_only_expiry_filter_and_dedup',expired_intention_policy:'archive_not_assert_completion',
    execution_authorized:false,proactive_contact_enabled:false,observed_at:'2026-10-21T04:20:00Z',runtime:{write_enabled:true,use_enabled:true},...patch};
}
export function disabledSemanticStatus():HySemanticStatus {
  return semanticStatusFixture({enabled:false,desired_enabled:false,mode:'pro',graph_available:false,task_counts:{},paused:true,
    management_available:false,last_task_finished_at:null,schema_state:'disabled',epoch:null,ready_epoch:null,
    intention_read:'disabled',expired_intention_policy:'disabled'});
}
export function semanticTaskFixture(patch:Partial<HySemanticTask>={}):HySemanticTask {
  return {task_id:'synthetic-evolve-task',kind:'evolve',state:'completed',created_at:'2026-10-21T03:00:00Z',finished_at:'2026-10-21T04:00:00Z',
    elapsed_ms:12.5,reason_code:null,observed_at:'2026-10-21T04:20:00Z',...patch};
}
