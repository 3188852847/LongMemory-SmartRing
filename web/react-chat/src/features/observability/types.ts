// 此模型只包含安全元数据；HTTP 成功、后台完成和设备播放必须分开呈现。
export type DiagnosticOutcome = 'processing' | 'succeeded' | 'accepted' | 'failed' | 'unknown';

export interface DiagnosticRequest {
  request_id: string;
  voice_round_id?: string;
  time: string;
  operation: string;
  stage: string;
  outcome: DiagnosticOutcome;
  code: string;
  status?: number;
  duration_ms: number;
  stages: {stage: string; event: string; at_ms: number}[];
}

export interface DiagnosticSnapshot {
  schema_version: 1;
  scope: 'current_process';
  capacity: number;
  persistence: 'enabled' | 'disabled' | 'unavailable';
  requests: DiagnosticRequest[];
  device_playback: 'unconfirmed';
  coverage: string[];
  uncovered: string[];
  logs: {id: string; owner: string; retention: string; state: string; bytes: number | null}[];
  voice?: {
    scope: string;
    delivery: 'best_effort_no_retry';
    device_playback: 'unconfirmed';
    rounds: {round_id: string; source: string; state: string; missing: string[]; sequence_gaps: number[];
      source_gaps?: {source: string; http_request_id: string | null; missing: number[]}[]; truncated?: boolean;
      events: {sequence: number; event: string; source?: string; http_request_id?: string}[]; device_playback: 'unconfirmed'}[];
  };
  log_retention?: {
    mode: 'dry_run'; budget_bytes: number; min_age_days: number; total_bytes: number;
    managed_bytes: number; vendor_bytes: number; candidate_bytes: number; over_budget_bytes?: number;
    unresolved_bytes?: number; complete: boolean; state: string; deletion_available: false;
    candidate_streams: string[];
    owners: Record<string, number>;
  };
}

export interface DiagnosticReader {
  request<T>(path: string): Promise<T>;
}

export function readDiagnostics(reader: DiagnosticReader): Promise<DiagnosticSnapshot> {
  return reader.request<DiagnosticSnapshot>('/api/observability');
}
