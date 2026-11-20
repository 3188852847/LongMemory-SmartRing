export type MemoryFeedbackKind = 'memory_ok'|'recall_miss'|'wrong_memory'|'memory_irrelevant';
export interface MemoryFeedback {kind:MemoryFeedbackKind;revision:number;occurred_at:string}
export interface EngineItem {item_id:string;content:string;revision:string;kind:string;source_event_ids:string[]|null;recorded_at:string|null;valid_from:string|null;valid_to:string|null;state:string|null}
export interface EnginePage<T> {items:T[];total:number;limit:number;offset:number}
export interface EngineStatus {method:string;write_enabled:boolean;use_enabled:boolean;management_capabilities:Record<string,boolean>;deferred_observation?:{supported:boolean;awaiting_completion:number;running_or_queued:number;last_result:{state:string;warning_code:string|null}}}
export interface EngineSource {event_id:string;role:string;content:string;occurred_at:string|null;session_id:string|null;state:string;attempt_id:string|null}
export interface HyWorkspace {protocol:1;profile:boolean;history:boolean;operations:boolean;correction:boolean;deletion:boolean;write_enabled:boolean;use_enabled:boolean;revision_check:string;native_atomic_revision:false;full_text_search:false;platform_sources_preserved:true}
export interface HyHistory {items:Array<{event:string|null;old_memory:string|null;new_memory:string|null;created_at:string|number|null}>;limited:boolean;recording_complete:false}
export interface HyOperation {request_id:string;action:'correct'|'delete';item_id:string;source_event_id:string;revision:string;state:'running'|'completed'|'uncertain';occurred_at:string;error_code:string|null}
export interface HyMutationResult {request_id:string;state:'completed';replayed:boolean;platform_sources_preserved:true}
