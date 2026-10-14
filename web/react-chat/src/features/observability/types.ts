// 此模型只包含安全元数据；HTTP 成功、后台完成和设备播放必须分开呈现。
export type DiagnosticOutcome = 'processing' | 'succeeded' | 'accepted' | 'failed' | 'unknown';

export interface DiagnosticRequest {
  request_id: string;
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
}

export interface DiagnosticReader {
  request<T>(path: string): Promise<T>;
}

export function readDiagnostics(reader: DiagnosticReader): Promise<DiagnosticSnapshot> {
  return reader.request<DiagnosticSnapshot>('/api/observability');
}
