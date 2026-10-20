export type LauncherSettings = {
  voice: boolean; model_profile: string; voice_model_profile: string;
  voice_mode: string; voice_latency_mode: string; memory_extraction: string;
  memory_retrieval: string; memory_backend: string; vad_profile: string;
  start_page: string; lan_ip: string; http_risk_ack: boolean; tts_backend: string;
  voice_ws_port?: number; voice_http_port?: number; network_auto?: boolean;
};
export type LauncherSnapshot = {
  state: 'stopped' | 'starting' | 'ready' | 'stopping' | 'failed'; message: string;
  services: Array<{id: string; label: string; state: string; tone?: 'quiet' | 'good' | 'busy' | 'warning' | 'bad' | 'idle' | 'error'}>;
  shutdown_complete?: boolean;
  console_url: string | null; settings: LauncherSettings; settings_revision: string;
  can_start: boolean; can_stop: boolean;
  network?: {state: string; message: string; address?: string};
};
export type LauncherAction = 'start' | 'stop' | 'open_console' | 'shutdown';

/** 能力令牌只驻留内存，立即从地址栏清除，避免复制链接时带出控制权限。 */
export function consumeLauncherToken(location: Pick<Location, 'hash' | 'pathname' | 'search'>,
  history: Pick<History, 'replaceState'>): string {
  const params = new URLSearchParams(location.hash.slice(1));
  const token = params.get('token') ?? '';
  if (location.hash) history.replaceState(null, '', `${location.pathname}${location.search}`);
  return /^[A-Za-z0-9_-]{24,256}$/.test(token) ? token : '';
}

export class LauncherError extends Error {
  constructor(public status: number, message: string) {super(message);}
}
export class LauncherApi {
  constructor(private readonly token: string) {}
  async request(path: 'status' | 'settings' | 'actions', body?: unknown, signal?: AbortSignal): Promise<LauncherSnapshot> {
    if (!this.token) throw new LauncherError(401, '请重新双击“启动智慧圆屏.cmd”打开面板。');
    const response = await fetch(`/api/launcher/${path}`, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'Authorization': `Bearer ${this.token}`, ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
      ...(body === undefined ? {} : {body: JSON.stringify(body)}),
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(8000)]) : AbortSignal.timeout(8000),
    });
    if (!response.ok) {
      // 固定消息避免把异常响应中的本机路径、令牌或配置内容显示出来。
      const message = response.status === 409 ? '设置已被其他页面修改，请刷新后重新编辑。'
        : response.status === 401 || response.status === 403 ? '控制权限已失效，请重新双击启动入口。'
        : '操作未完成，请检查服务状态后重试。';
      throw new LauncherError(response.status, message);
    }
    return response.json() as Promise<LauncherSnapshot>;
  }
}
