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
    if (!response.ok) {
      let code = 'voice_operation_failed_recheck';
      try {const body = await response.json() as {error?:unknown}; if (typeof body.error === 'string') code = body.error;} catch { /* 保持安全通用错误。 */ }
      throw new ApiError(code, response.status);
    }
    return response.blob();
  }
  async speech(text: string): Promise<Blob> {
    const response = await fetch('/api/speech', {method:'POST', credentials:'same-origin', cache:'no-store',
      headers:{'Content-Type':'application/json','X-Console-CSRF':this.csrf}, body:JSON.stringify({text})});
    if (!response.ok) {
      let code = 'speech_failed';
      try {const body = await response.json() as {error?:unknown}; if (typeof body.error === 'string') code = body.error;} catch { /* 保持安全通用错误。 */ }
      throw new ApiError(code, response.status);
    }
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
    if (!response.ok) {
      // aiohttp 的框架级 404/400 可能不是 JSON；仍收敛为固定类别，避免把解析异常或 HTML 回显到页面。
      let code = `http_${response.status}`;
      try {
        const data = await response.json() as {error?: unknown};
        if (typeof data.error === 'string') code = data.error;
      } catch { /* 保留按 HTTP 状态生成的安全类别。 */ }
      throw new ApiError(code, response.status);
    }
    return await response.json() as T;
  }
  async uploadRoundWallpaper(file: File, options: RoundWallpaperUploadOptions): Promise<{item:RoundWallpaperItem}> {
    const query = new URLSearchParams(Object.entries(options).map(([key, value]) => [key, String(value)]));
    const form = new FormData();
    form.append('file', file, file.name);
    // 不手动设置 Content-Type：浏览器需要为 multipart 生成 boundary。
    const response = await fetch(`/api/round-wallpapers?${query}`, {
      method:'POST', credentials:'same-origin', cache:'no-store',
      headers:{'X-Console-CSRF':this.csrf}, body:form,
    });
    if (!response.ok) {
      let code = `http_${response.status}`;
      try {const body = await response.json() as {error?:unknown}; if (typeof body.error === 'string') code = body.error;} catch { /* 保持安全错误码。 */ }
      throw new ApiError(code, response.status);
    }
    return await response.json() as {item:RoundWallpaperItem};
  }
}
export interface WriteTrace {operation:string; item_id?:string; source_event_ids?:string[] | null}
export interface RetrievedTrace {item_id:string; content:string; source_event_ids?:string[] | null}
export type MemoryFeedbackKind = 'memory_ok'|'recall_miss'|'wrong_memory'|'memory_irrelevant';
export interface MemoryFeedback {kind:MemoryFeedbackKind; revision:number; occurred_at:string}
export interface Turn {
  request_id?:string; input: string; answer?: string; status: string; writes: WriteTrace[] | null;
  answer_source?: 'model' | 'application_command' | null;
  user_saved: boolean; duration_ms: number; memory_processing?: 'completed' | 'source_only' | null;
  memory_warning?: string | null; retrieval_strategy?: string | null;
  retrieval_warning?: string | null; scenario_use_enabled?: boolean; persona_use_enabled?: boolean;
  persona_retrieved?: Array<{persona_id: string; label: string; statement: string}>;
  scenario_retrieved?: {scenario_id:string; title:string; summary:string; source_memory_ids:string[]; source_message_ids:string[]}[] | null;
  retrieved?: RetrievedTrace[] | null;
  memory_feedback?:MemoryFeedback|null;
  memory_feedback_events?:MemoryFeedback[];
  memory_command?: {kind:string; status:string; notice:string; target_memory_ids?:string[]} | null;
  follow_up_suggestion?: {
    status:'candidate_armed'|'candidate_created_requires_proactive_enabled'|'replayed'|'not_created'; candidate_id:string|null;
    source_memory_id:string|null; prompt_text:string|null; follow_up_at:string|null;
    warning_code:string|null; outreach_id:string|null;
  } | null;
  [key: string]: unknown;
}
export interface DailyMemoryFeedback {
  local_date:string;utc_offset_minutes:number;total:number;limited:boolean;
  action_counts:Record<MemoryFeedbackKind,number>;
  items:Array<{chat_id:string;chat_title:string;request_id:string;kind:MemoryFeedbackKind;revision:number;occurred_at:string;is_current:boolean}>;
  current_total:number;current_limited:boolean;current_counts:Record<MemoryFeedbackKind,number>;
  current_items:Array<{chat_id:string;chat_title:string;request_id:string;kind:MemoryFeedbackKind;revision:number;occurred_at:string}>;
}
export type MemoryFeedbackDiagnosticFocus = 'normal_control'|'negative_control'|'retrieval'|'context_or_answer_use'|'memory_content_freshness_subject_or_ranking'|'short_term_or_answer_model';
export type MemoryFeedbackReviewState = 'open'|'resolved'|'dismissed'|'not_applicable';
export interface MemoryFeedbackReview {
  state:MemoryFeedbackReviewState;reason_code:string|null;review_revision:number;occurred_at:string|null;
}
export interface MemoryFeedbackIndexItem {
  source:'web_chat'|'round_screen';chat_id:string|null;chat_title:string;request_id:string;
  feedback_target_id:string;feedback_event_id?:string;feedback_message_id?:string;assistant_message_id?:string;
  kind:MemoryFeedbackKind;revision:number;occurred_at:string;
  retrieved_counts:{l1:number;l2:number;l3:number};
  retrieval_evidence?:Array<{layer:'l1'|'l2'|'l3';item_id:string;rank:number;content_sha256:string}>;
  retrieval_evidence_recorded?:boolean;diagnostic_focus:MemoryFeedbackDiagnosticFocus;review:MemoryFeedbackReview;
}
export interface MemoryFeedbackIndex {
  kind:'issues'|'all'|'resolved'|'dismissed'|MemoryFeedbackKind;counts:Record<MemoryFeedbackKind,number>;
  review_counts:Record<'open'|'resolved'|'dismissed',number>;
  total:number;offset:number;limit:number;
  items:MemoryFeedbackIndexItem[];
}
export interface RoundScreenFeedbackDetail {
  id:string;event_kind:'recall_miss'|'wrong_memory';evidence_kind:string;interpreter_version:string;occurred_at:string;
  target_user_message_id:string;assistant_message_id:string;feedback_message_id:string;
  question:string;question_at:string;answer:string;answer_at:string;feedback:string;feedback_at:string;
  retrieval_evidence_recorded:boolean;
  retrieval_evidence:Array<{layer:'l1'|'l2'|'l3';item_id:string;rank:number;content_sha256:string;current_content:string|null;current_state:string;matches_receipt:boolean|null}>;
}
export interface Snapshot {chat_id: string; title: string; pending: boolean; turns: Turn[]}
export interface Summary {chat_id: string; title: string; turn_count: number}
export interface ModelHealth {state:'unchecked'|'available'|'unavailable'|'not_applicable'; code:string|null; checked_at:string|null}
export interface Config {enabled: boolean; database: string; model: string; role: string; provider: string; method: string; retrieval: string; model_health?:ModelHealth; model_endpoint?:string|null; insecure_model_transport?:boolean}
export interface DeviceStatus {
  connection_count:number; ready:boolean; read_volume_supported:boolean; set_volume_supported:boolean;
  read_status_supported:boolean; set_brightness_supported:boolean; set_theme_supported:boolean;
  aec_advertised?:boolean; stop_speech_supported?:boolean; allowed_volume?:{minimum:number; maximum:number};
  natural_interruption?:NaturalInterruptionDiagnostic;
  voice_latency?:VoiceLatency;
}
export interface NaturalInterruptionDiagnostic {
  version:1; state:'unavailable'|'blocked'|'trial_ready';
  device_aec_advertised:boolean; server_aec_active:boolean; timestamped_audio_supported:boolean;
  listen_mode:'auto'|'manual'|'realtime'|'unknown';
  reason:'device_offline'|'device_aec_not_advertised'|'timestamp_transport_unavailable'|'server_aec_inactive'|'realtime_listening_inactive'|'ready_for_controlled_trial';
}
export interface VoiceLatency {
  version:1;
  state:'preparing_memory'|'waiting_for_model'|'waiting_for_sentence'|'tts_running'|'audio_ready'|'first_audio_sent';
  started_at:string; tts_backend:'edge'|'voxcpm2'|'other';
  timings_ms:{
    memory_ready_ms:number|null; llm_requested_ms:number|null; llm_first_output_ms:number|null;
    tts_started_ms:number|null; audio_ready_ms:number|null; first_audio_sent_ms:number|null;
    response_completed_ms:number|null;
  };
}
export interface TTSCapabilities {
  contract_version:2; provider_id:string; display_name:string;
  locality:'local'|'remote'|'browser'|'device';
  delivery_modes:Array<'buffered'|'audio_stream'>; output_mime_types:string[];
  controls:Array<'voice_selection'|'reference_voice'|'style_prompt'|'speaking_rate'|'volume'|'emotion'>;
  cancellation:'none'|'cooperative'; max_text_chars:number;
}
export interface TTSBenchmarkCase {
  id:string; label:string; text:string; purpose:string; text_chars:number;
}
export interface TTSBenchmarkIndex {
  schema_version:1; backend:string; capabilities:TTSCapabilities|null; cases:TTSBenchmarkCase[];
  execution:{parallel:false;retries:0;stores_chat_or_memory:false};
}
export interface TTSBenchmarkResult {
  schema_version:1; backend:string; capabilities:TTSCapabilities|null; case:TTSBenchmarkCase;
  started_at:string; adapter_delivery:'buffered'|'audio_stream';
  first_audio_available_ms:number; completed_ms:number; audio_bytes:number; content_type:string;
  wave:{duration_seconds:number;sample_rate_hz:number;channels:number;sample_width_bits:number;rms:number;peak:number;near_silent:boolean}|null;
  limitations:string[];
}
export interface MemoryPageSummary {total:number; limit:number; offset:number; items:unknown[]}
export interface RuntimeStatus {
  enabled:boolean;
  state:'starting'|'ready'|'stopping'|'stopped'|'failed'|'stale'|'launcher_unavailable';
  reason:string|null;
  updated_at?:string;
  age_seconds?:number;
  services:Partial<Record<'console'|'voice'|'voxcpm2','disabled'|'running'|'ready'|'exited'>>;
}
export interface ModelProfile {
  id:'campus'|'official'; label:string; file_exists:boolean; base_url:string; model:string;
  timeout_seconds:number; max_tokens:number; allow_http:boolean; api_key_configured:boolean;
}
export interface ModelProfiles {
  enabled:boolean; current_profile?:'campus'|'official'; next_start_profile?:'campus'|'official';
  voice_next_start_profile?:'campus'|'official'; restart_required?:boolean; profiles?:ModelProfile[];
  voice?:VoiceModelProfileStatus;
}
export interface VoiceModelProfileStatus {
  enabled:boolean; selected_profile:'campus'|'official';
  status:'configured'|'restart_pending'|'configuration_unavailable';
  config_matches?:boolean; provider_name?:string; configured_base_url?:string;
  configured_model?:string; transport?:'http'|'https';
}
export interface VoiceModelHealth extends ModelHealth {profile:'campus'|'official'}
export interface MemoryBackendOption {
  id:'longmemory'|'xiaozhi_local'|'none'; label:string; provider:string;
  description:string; persistent:boolean;
}
export interface MemoryBackends {
  enabled:boolean; current_backend?:MemoryBackendOption['id'];
  next_start_backend?:MemoryBackendOption['id']; restart_required?:boolean;
  backends?:MemoryBackendOption[];
  xiaozhi?:{enabled:boolean; selected_backend:string; status:'configured'|'restart_pending'|'configuration_unavailable'; configured_provider?:string; provider_name?:string};
}
export interface RoundSkin {
  schema_version:1; id:string; name:string; description:string;
  target:{board:'viewe-smartring-plus'; width:360; height:360; color_format:'RGB565'; skin_api:1};
  palette:{background:string; background_edge:string; foreground:string; muted:string; accent:string; listening:string; thinking:string; happy:string; concerned:string; warning:string; error:string; charging:string};
  face:{eye_width:number; eye_height:number; mouth_width:number};
  motion:{blink_seconds:number; speaking_seconds:number}; manifest_sha256:string;
}
export interface RoundSkins {
  enabled:boolean; selected_skin:string; custom_skin_id:string; skins:RoundSkin[];
  delivery:{console_preview:boolean; upstream_assets_ota_detected:boolean; device_apply_supported:boolean; device_delivery_implemented?:boolean; reason:string; known_firmware_baseline:string};
}
export interface RoundDeviceSkin {
  skin_api:1; skin_id:string; manifest_sha256:string;
  background:number; foreground:number; muted:number; accent:number; listening:number;
  thinking:number; happy:number; concerned:number; error:number;
  eye_width:number; eye_height:number; mouth_width:number;
}
export interface RoundSkinApply {
  requested_skin_id:string; requested_manifest_sha256:string; acknowledged:true;
  verified:boolean; device_skin?:RoundDeviceSkin; reason?:string;
}
export interface RoundWallpaperUploadOptions {
  start_seconds:number; duration_seconds:number; frame_rate:number; colors:number;
}
export interface RoundWallpaperItem {
  schema_version:1; id:string; created_at:string; state:'ready';
  source:{display_name:string;size_bytes:number;sha256:string;container:string;video_codec:string;width:number;height:number;duration_seconds:number;frame_rate:number;has_audio:boolean};
  clip:RoundWallpaperUploadOptions;
  preview:{file_name:'preview.gif';size_bytes:number;sha256:string;width:360;height:360;format:'gif';has_audio:false};
  delivery:{device_published:false;reason:'preview_only'};
}
export interface RoundWallpaperLibrary {
  enabled:boolean; tool_state:'ready'|'unavailable'; max_upload_bytes:number; items:RoundWallpaperItem[];
  device_delivery:{enabled:boolean;requires_online_device:true;restart_after_publish:true};
}
export interface RoundWallpaperDeployment {
  wallpaper_api:1; slot:'a'|'b'; wallpaper_id:string; sha256:string; size_bytes:number;
  state:'activated_restarting'|'rollback_restarting'; operation_id:string;
}
export interface RoundWallpaperDeviceStatus {
  wallpaper_api:1; active_valid:boolean; active_slot:''|'a'|'b'; active_wallpaper_id:string;
  active_sha256:string; active_size_bytes:number; rollback_available:boolean;
}
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
  follow_up_source?:null | {
    candidate_id:string; candidate_revision:number; scheduled_for:string;
  };
  strategy_source:null | {
    version_id:string; selection_revision:number; evaluated_local_date:string;
    source_candidate_id:string; source_candidate_revision:number;
    expected_minute:number; grace_minutes:number; utc_offset_minutes:number;
    trigger_policy_version:string;
  };
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
export interface FollowUpCandidate {
  id:string; subject_id:string; source_memory_id:string; prompt_text:string;
  follow_up_at:string; status:'candidate'|'cancelled'; created_at:string;
  updated_at:string; revision:number; due:boolean; ready_for_activation:boolean;
  creation_kind:'owner_created'|'explicit_conversation_request';
  source_message_id:string|null;
  blocked_reason:null|'cancelled'|'already_activated'|'source_changed'|'time_reached';
  source:{layer:'l1'; content:string; state:'active'|'retired'; superseded_by_id:string|null};
  activation:null|{outreach_id:string;state:string;revision:number;expires_at:string};
}
export interface CompanionStrategyCandidate {
  id:string; subject_id:string; status:'candidate'|'dismissed';
  suggested_minute:number; utc_offset_minutes:number;
  evidence_count:number; distinct_local_dates:number;
  rationale_code:'repeated_temporal_followup_near_contact_time';
  generator_version:string; created_at:string; updated_at:string;
  revision:number; active:false;
  sources:Array<{
    interaction_event_id:string; outreach_id:string; queued_at:string;
    observed_at:string; latency_seconds:number;
    local_date:string; local_minute:number;
    delivery_evidence_level:'server_queued'|'transport_sent'|'device_acknowledged'|'played';
  }>;
}
export interface UserInitiatedInteraction {
  id:string; subject_id:string; source_message_id:string; occurred_at:string;
  previous_user_message_at:string|null; silence_gap_seconds:number|null;
  evidence_kind:'silence_gap_without_recent_outreach'; detector_version:string;
  local_date:string; local_minute:number; utc_offset_minutes:number;
}
export interface CompanionRoutineCandidate {
  id:string; subject_id:string; status:'candidate'|'dismissed';
  expected_minute:number; utc_offset_minutes:number;
  observation_window_minutes:30; evidence_count:number;
  distinct_local_dates:number;
  rationale_code:'repeated_user_initiated_activity_near_time';
  generator_version:string; created_at:string; updated_at:string;
  revision:number; active:false;
  sources:Array<{
    user_initiated_event_id:string; occurred_at:string;
    silence_gap_seconds:number|null;
    evidence_kind:'silence_gap_without_recent_outreach';
    local_date:string; local_minute:number;
  }>;
}
export interface CompanionAbsenceStrategyVersion {
  id:string; subject_id:string; source_candidate_id:string;
  source_candidate_revision:number; expected_minute:number; grace_minutes:number;
  utc_offset_minutes:number; allowed_weekdays:number[];
  trigger_policy_version:'routine-absence-trigger-v1';
  replay_protocol:'companion-absence-offline-replay-v1';
  replay_dataset_name:string; replay_dataset_version:string;
  replay_dataset_sha256:string; replay_case_count:number;
  parameter_fingerprint:string;
  replay_matched_count:number; replay_unsafe_allow_count:number;
  replay_gate_passed:boolean; replayed_at:string; created_at:string; active:boolean;
}
export interface CompanionAbsenceStrategySelection {
  current_version_id:string|null; revision:number; updated_at:string|null;
}
export interface CompanionAbsenceStrategySwitchEvent {
  id:string; previous_version_id:string|null; selected_version_id:string|null;
  action:'activate'|'deactivate'|'rollback'; pointer_revision:number; created_at:string;
}
export interface CompanionAbsenceStrategyVersionList {
  items:CompanionAbsenceStrategyVersion[];
  selection:CompanionAbsenceStrategySelection;
  events:CompanionAbsenceStrategySwitchEvent[];
}
