/** 仅供合成验收：固定样例不读取个人库，不提供任何设备或模型写入口。 */
export function syntheticResponse(path:string, populated:boolean):unknown {
  const url=new URL(path,'http://synthetic.invalid');
  const now='2026-10-14T01:00:00Z';
  const l1={id:'synthetic-l1',content:'合成事实：用户喜欢茶。',state:'active',recorded_at:now,subject_id:'user:self',truncated:false};
  const scenario={id:'synthetic-scenario',title:'合成场景',summary:'合成生活场景内容',status:'active',generated_at:now,revision:1,subject_id:'user:self'};
  const persona={id:'synthetic-persona',label:'合成画像',statement:'合成画像内容',kind:'preference',basis:'user_declared',status:'active',generated_at:now,revision:1,subject_id:'user:self'};
  const page=(items:unknown[])=>({items,total:items.length,offset:0,limit:25});
  switch(url.pathname) {
    case '/api/session':return {csrf:'synthetic-only'};
    case '/api/memory-engine/identity':return {schema_version:1,configured:true,method:'longmemory_v1',representation:'atomic_fact',legacy_sqlite:true,state:'available'};
    case '/api/observability':return {schema_version:1,scope:'current_process',capacity:100,persistence:'disabled',
      requests:[],device_playback:'unconfirmed',coverage:['http_request'],uncovered:['asr','tts','device_playback','background_completion'],logs:[]};
    case '/api/memory-config':return {configured:true,database:'synthetic.db',allow_delete:false,allow_clear:false,allow_correction:false,allow_change:false,allow_promote_source:false,allow_scenario_management:false,allow_persona_management:false};
    case '/api/memory-mode':return {write_enabled:true,use_enabled:true,scenario_use_enabled:false,persona_use_enabled:false,scenario_available:false,persona_available:false,persistent:false,l0_archived_when_write_disabled:true};
    case '/api/memories':return page(populated?[l1]:[]);
    case '/api/source-messages':return page([]);
    case '/api/memories/synthetic-l1':return {...l1,revision:'synthetic',sources:[],valid_from:null,valid_to:null};
    case '/api/memories/daily-review':return {local_date:'2026-10-14',items:[],total:0,activity_counts:{added:0,corrected:0,changed:0,deleted:0},message_counts:{user:0,assistant:0,total:0,unlinked_user:0},quality_counts:{owner_confirmed_missed_extraction:0},deletions:[]};
    case '/api/chat-memory-feedback/daily':return {current_total:0,total:0,current_counts:{memory_ok:0,recall_miss:0,wrong_memory:0,memory_irrelevant:0},current_items:[],items:[]};
    case '/api/consolidation-status':return {background_enabled:false,stages:[]};
    case '/api/scenarios':return page(populated?[scenario]:[]);
    case '/api/scenarios/synthetic-scenario':return {...scenario,sources:[],lifecycle_events:[]};
    case '/api/scenario-source-inbox':return {items:[],total:0,limited:false,selection_is_semantic:false};
    case '/api/personas':return page(populated?[persona]:[]);
    case '/api/personas/synthetic-persona':return {...persona,sources:[],lifecycle_events:[],audit:null};
    case '/api/persona-profile':return {active_assertion_count:populated?1:0,sections:populated?[{kind:'preference',items:[persona]}]:[],updated_at:now};
    case '/api/persona-source-options':return {l1:[],l2:[]};
    case '/api/chat-memory-feedback':return {...page(populated?[{source:'web_chat',kind:'recall_miss',chat_id:'synthetic-chat',chat_title:'合成问题样本',request_id:'synthetic-request',diagnostic_focus:'retrieval',occurred_at:now,revision:1,retrieved_counts:{l1:0,l2:0,l3:0},review:{state:'open',review_revision:0}}]:[]),kind:'issues',counts:{memory_ok:0,recall_miss:populated?1:0,wrong_memory:0,memory_irrelevant:0},review_counts:{open:populated?1:0,resolved:0,dismissed:0}};
    case '/api/l1-extraction-audit':return {items:[],counts:{noop:0,added:0,reused:0,extraction_failed:0,persistence_failed:0,incomplete:0}};
    case '/api/l1-sufficiency-shadow':case '/api/l2-sufficiency-shadow':return null;
    case '/api/device':return {ready:populated,connection_count:populated?1:0,reason:populated?null:'device_offline',read_volume_supported:populated,set_volume_supported:populated,read_status_supported:false,set_brightness_supported:false,set_theme_supported:false,stop_speech_supported:false,allowed_volume:{minimum:5,maximum:100}};
    case '/api/experiments':return {items:populated?[{id:'synthetic-run',kind:'answers',provider:'fake',model:'合成模型',dataset:'synthetic',split:'dev',status:'completed',completed:1,total:1,started_at:now}]:[],skipped:0,limited:false};
    case '/api/experiments/synthetic-run':return {kind:'answers',started_at:now,split:'dev',status:'completed',groups:[],reviews:[],questions:[{id:'synthetic-question',query:'合成比较题'}],report_sha256:'a'.repeat(64),review_enabled:false};
    case '/api/experiments/synthetic-run/question':return {source_note:'合成验收',rows:['no_memory','longmemory_v1'].map(group=>({group,status:'completed',answer:`合成回答 ${group}`,injected_context:'合成证据',context:'合成检索上下文',retrieved:[],sources:[],answer_proxy_pass:null,evidence_complete:null}))};
    case '/api/experiment-jobs/options':return {enabled:false,real_available:false,retrievals:[],context_default:4000,context_max:16000};
    case '/api/experiment-jobs':return {items:[]};
    case '/api/l1-policy-replay':return {sources:[],replays:[],skipped:0};
    default:throw new Error(`Unmapped synthetic endpoint: ${url.pathname}`);
  }
}
