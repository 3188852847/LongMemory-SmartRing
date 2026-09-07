// 所有请求复用本机 Cookie/CSRF；不持久缓存正文，不自动重试写请求。
export class ApiError extends Error {
  constructor(public readonly code: string, public readonly status: number) {
    super(`请求未完成（${code}）。不要自动重发消息。`);
    this.name = 'ApiError';
  }
}

export class ChatApi {
  private csrf = '';
  async voicePreview(voice: string): Promise<Blob> {
    const response = await fetch('/api/voice-settings/preview', {method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'X-Console-CSRF': this.csrf}, body: JSON.stringify({voice})});
    if (!response.ok) throw new Error('试听失败，请检查网络与小智环境；未自动重试。');
    return response.blob();
  }
  async bootstrap() {
    const response = await fetch('/api/session', {headers: {'X-Console-Bootstrap': '1'}, cache: 'no-store'});
    if (!response.ok) throw new Error('无法建立本机会话，请刷新页面。');
    this.csrf = (await response.json()).csrf;
  }
  async request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
    const response = await fetch(path, {method, credentials: 'same-origin', cache: 'no-store',
      headers: method === 'GET' ? {} : {'Content-Type': 'application/json', 'X-Console-CSRF': this.csrf},
      body: body === undefined ? undefined : JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new ApiError(String(data.error ?? response.status), response.status);
    return data;
  }
}
export interface Turn {
  input: string; answer?: string; status: string; writes: {operation: string}[] | null;
  user_saved: boolean; duration_ms: number; memory_processing?: 'completed' | 'source_only' | null;
  memory_warning?: string | null; retrieval_strategy?: string | null;
  retrieval_warning?: string | null; scenario_use_enabled?: boolean; persona_use_enabled?: boolean;
  persona_retrieved?: Array<{persona_id: string; label: string; statement: string}>;
  scenario_retrieved?: {scenario_id:string; title:string; summary:string; source_memory_ids:string[]; source_message_ids:string[]}[] | null;
  [key: string]: unknown;
}
export interface Snapshot {chat_id: string; title: string; pending: boolean; turns: Turn[]}
export interface Summary {chat_id: string; title: string; turn_count: number}
export interface Config {enabled: boolean; database: string; model: string; role: string; provider: string; method: string; retrieval: string}
export interface ProactivePolicy {
  subject_id: string; enabled: boolean; utc_offset_minutes: number;
  allowed_weekdays: number[]; allowed_start_minute: number; allowed_end_minute: number;
  daily_limit: number; minimum_interval_seconds: number; maximum_lifetime_seconds: number;
  quiet_until: string | null; policy_version: string; revision: number; updated_at: string | null;
  automatic_enabled: boolean; scheduled_minute: number; greeting_text: string;
  topic_enabled: boolean;
}
export interface ProactiveTestResult {
  outreach_id: string; state: string; revision: number; replayed: boolean;
  policy_action: string | null; policy_reason: string | null; delivery_reason: string | null;
  device: {ready:boolean; user_session_active:boolean; reason:string | null} | null;
}
export interface ProactiveScheduleStatus {
  action:'create'|'skip'|'wait'; reason:string; local_date:string;
  scheduled_for:string | null; user_chatted_today:boolean;
  awaiting_user_response:boolean; already_evaluated_today:boolean;
  development_override: null | ProactiveScheduleOverride;
  latest_development_override: null | ProactiveScheduleOverride;
}
export interface ProactiveScheduleOverride {
    id:string; subject_id:string; local_date:string; scheduled_minute:number;
    policy_revision:number;
    status:'armed'|'consumed'|'cancelled'; created_at:string; updated_at:string;
    consumption_reason:string | null; revision:number;
}
export interface ProactiveOutreachSummary {
  outreach_id:string; trigger:string; content:string; created_at:string; expires_at:string;
  state:string; revision:number; reason:string; event_count:number; failure_reason:string | null;
  topic_seed_id:string | null; topic_seed_revision:number | null;
  outcome_observation_state:'not_applicable'|'delivery_not_established'|'awaiting_subsequent_user_message'|'subsequent_user_message_observed';
  delivery_evidence_level:null|'server_queued'|'transport_sent'|'device_acknowledged'|'played';
  subsequent_user_message:null | {
    occurred_at:string; latency_seconds:number; evidence:'temporal_order';
  };
  explicit_feedback:null | {
    topic_seed_id:string; occurred_at:string; feedback_kind:'reject_topic';
    action_kind:'topic_seed_disabled'; evidence_kind:'user_explicit';
    interpreter_version:string;
  };
}
export interface ProactiveTopicSeed {
  id:string; subject_id:string; scenario_id:string; prompt_text:string;
  status:'active'|'disabled'; created_at:string; updated_at:string;
  revision:number; usable:boolean;
  source:{layer:'l2'; title:string; summary:string; status:string};
}
