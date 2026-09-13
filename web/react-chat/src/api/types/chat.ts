import type {MemoryFeedback} from './memory';

export interface WriteTrace {operation:string; item_id?:string; source_event_ids?:string[] | null}
export interface RetrievedTrace {
  item_id:string;
  content:string;
  source_event_ids?:string[] | null;
  temporal_role?:'historical' | null;
  valid_from?:string | null;
  valid_to?:string | null;
}
export interface Turn {
  request_id?:string; input:string; answer?:string; status:string; writes:WriteTrace[] | null;
  answer_source?:'model'|'application_command'|null; user_saved:boolean; duration_ms:number;
  memory_processing?:'completed'|'source_only'|null; memory_warning?:string|null;
  retrieval_strategy?:string|null; retrieval_warning?:string|null;
  scenario_use_enabled?:boolean; persona_use_enabled?:boolean;
  persona_retrieved?:Array<{persona_id:string;label:string;statement:string}>;
  scenario_retrieved?:Array<{scenario_id:string;title:string;summary:string;source_memory_ids:string[];source_message_ids:string[]}>|null;
  retrieved?:RetrievedTrace[]|null; memory_feedback?:MemoryFeedback|null;
  memory_feedback_events?:MemoryFeedback[];
  memory_command?:{kind:string;status:string;notice:string;target_memory_ids?:string[]}|null;
  follow_up_suggestion?:{status:'candidate_armed'|'candidate_created_requires_proactive_enabled'|'replayed'|'not_created';candidate_id:string|null;source_memory_id:string|null;prompt_text:string|null;follow_up_at:string|null;warning_code:string|null;outreach_id:string|null}|null;
  [key:string]:unknown;
}
export interface Snapshot {chat_id:string;title:string;pending:boolean;turns:Turn[]}
export interface Summary {chat_id:string;title:string;turn_count:number}
