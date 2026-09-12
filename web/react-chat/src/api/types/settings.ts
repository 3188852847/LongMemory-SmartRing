export interface ModelHealth {state:'unchecked'|'available'|'unavailable'|'not_applicable';code:string|null;checked_at:string|null}
export interface Config {enabled:boolean;database:string;model:string;role:string;provider:string;method:string;retrieval:string;model_health?:ModelHealth;model_endpoint?:string|null;insecure_model_transport?:boolean}
export interface RuntimeStatus {enabled:boolean;state:'starting'|'ready'|'stopping'|'stopped'|'failed'|'stale'|'launcher_unavailable';reason:string|null;updated_at?:string;age_seconds?:number;services:Partial<Record<'console'|'voice'|'voxcpm2'|'sanotts'|'cosyvoice3','disabled'|'running'|'ready'|'exited'>>}
export interface ModelProfile {id:'campus'|'official';label:string;file_exists:boolean;base_url:string;model:string;timeout_seconds:number;max_tokens:number;allow_http:boolean;api_key_configured:boolean}
export interface ModelProfiles {enabled:boolean;current_profile?:'campus'|'official';next_start_profile?:'campus'|'official';voice_next_start_profile?:'campus'|'official';restart_required?:boolean;profiles?:ModelProfile[];voice?:VoiceModelProfileStatus}
export interface VoiceModelProfileStatus {enabled:boolean;selected_profile:'campus'|'official';status:'configured'|'restart_pending'|'configuration_unavailable';config_matches?:boolean;provider_name?:string;configured_base_url?:string;configured_model?:string;transport?:'http'|'https'}
export type TTSBackendId='edge'|'voxcpm2'|'sanotts'|'cosyvoice3';
export interface TTSBackendOption {id:TTSBackendId;label:string;description:string;local_service:boolean}
export interface TTSBackends {enabled:boolean;current_backend?:TTSBackendId;next_start_backend?:TTSBackendId;voice_running?:boolean;restart_required?:boolean;backends?:TTSBackendOption[]}
export interface VoiceModelHealth extends ModelHealth {profile:'campus'|'official'}
