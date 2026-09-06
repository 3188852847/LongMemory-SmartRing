// 所有请求复用本机 Cookie/CSRF；不持久缓存正文，不自动重试写请求。
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
    if (!response.ok) throw new Error(`请求未完成（${data.error ?? response.status}）。不要自动重发消息。`);
    return data;
  }
}
export interface Turn {
  input: string; answer?: string; status: string; writes: {operation: string}[] | null;
  user_saved: boolean; duration_ms: number; memory_processing?: 'completed' | 'source_only' | null;
  memory_warning?: string | null; [key: string]: unknown;
}
export interface Snapshot {chat_id: string; title: string; pending: boolean; turns: Turn[]}
export interface Summary {chat_id: string; title: string; turn_count: number}
export interface Config {enabled: boolean; database: string; model: string; role: string; provider: string; method: string}
