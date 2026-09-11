import type {RoundWallpaperItem, RoundWallpaperUploadOptions} from './types/device';

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
    const response = await fetch('/api/voice-settings/preview', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'X-Console-CSRF': this.csrf},
      body: JSON.stringify({voice}),
    });
    if (!response.ok) throw await this.apiError(response, 'voice_operation_failed_recheck');
    return response.blob();
  }

  async speech(text: string): Promise<Blob> {
    const response = await fetch('/api/speech', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'X-Console-CSRF': this.csrf},
      body: JSON.stringify({text}),
    });
    if (!response.ok) throw await this.apiError(response, 'speech_failed');
    return response.blob();
  }

  async bootstrap() {
    const response = await fetch('/api/session', {
      headers: {'X-Console-Bootstrap': '1'}, cache: 'no-store',
    });
    if (!response.ok) throw new Error('无法建立本机会话，请刷新页面。');
    this.csrf = (await response.json()).csrf;
  }

  async request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
    const response = await fetch(path, {
      method, credentials: 'same-origin', cache: 'no-store',
      headers: method === 'GET' ? {} : {
        'Content-Type': 'application/json', 'X-Console-CSRF': this.csrf,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) throw await this.apiError(response, `http_${response.status}`);
    return await response.json() as T;
  }

  async uploadRoundWallpaper(file: File, options: RoundWallpaperUploadOptions): Promise<{item: RoundWallpaperItem}> {
    const query = new URLSearchParams(Object.entries(options).map(([key, value]) => [key, String(value)]));
    const form = new FormData();
    form.append('file', file, file.name);
    // 不手动设置 Content-Type：浏览器需要为 multipart 生成 boundary。
    const response = await fetch(`/api/round-wallpapers?${query}`, {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'X-Console-CSRF': this.csrf}, body: form,
    });
    if (!response.ok) throw await this.apiError(response, `http_${response.status}`);
    return await response.json() as {item: RoundWallpaperItem};
  }

  private async apiError(response: Response, fallback: string): Promise<ApiError> {
    // 框架级错误可能不是 JSON；绝不把 HTML 或解析异常回显到页面。
    let code = fallback;
    try {
      const data = await response.json() as {error?: unknown};
      if (typeof data.error === 'string') code = data.error;
    } catch { /* 保留安全错误类别。 */ }
    return new ApiError(code, response.status);
  }
}
