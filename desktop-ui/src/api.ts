const token = new URLSearchParams(location.search).get('token') || '';

export type ApiDebugEntry = {
  id: number; startedAt: number; durationMs: number; method: string; path: string;
  status?: number; ok: boolean; request?: unknown; response?: unknown; error?: string;
};

const DEBUG_KEY = 'liveRecorderApiDebug';
const debugListeners = new Set<(entry: ApiDebugEntry) => void>();
let debugSequence = 0;

export const isApiDebugEnabled = () => localStorage.getItem(DEBUG_KEY) === '1';
export const setApiDebugEnabled = (enabled: boolean) => localStorage.setItem(DEBUG_KEY, enabled ? '1' : '0');
export const subscribeApiDebug = (listener: (entry: ApiDebugEntry) => void) => {
  debugListeners.add(listener);
  return () => { debugListeners.delete(listener); };
};

const secretKey = /(^|_)(cookie|token|authorization|password|secret|private_?key|ticket|ts_sign|session(id)?|csrf|auth_code|authorization_code)($|_)/i;
function sanitize(value: unknown, key = '', depth = 0): unknown {
  if (secretKey.test(key)) return '[已隐藏]';
  if (depth > 8) return '[内容层级过深]';
  if (Array.isArray(value)) return value.slice(0, 200).map(item => sanitize(item, '', depth + 1));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([name, item]) => [name, sanitize(item, name, depth + 1)]));
  if (typeof value === 'string' && value.length > 20000) return `${value.slice(0, 20000)}…[已截断 ${value.length - 20000} 字符]`;
  return value;
}

function safePath(path: string) {
  try {
    const url = new URL(path, location.origin);
    for (const name of [...url.searchParams.keys()]) if (secretKey.test(name)) url.searchParams.set(name, '[已隐藏]');
    return `${url.pathname}${url.search}`;
  } catch { return path; }
}

const backgroundEndpoint = (path: string) => /^\/api\/(state|logs|interaction\/events|work-pull\/logs|baidupan\/logs)(\?|$)/.test(path);
function emitDebug(entry: ApiDebugEntry) {
  if (!isApiDebugEnabled() || (backgroundEndpoint(entry.path) && entry.ok)) return;
  debugListeners.forEach(listener => listener(entry));
}

export function friendlyError(message: unknown): string {
  const raw = String(message || '').trim();
  if (!raw) return '操作失败，请稍后重试';
  if (/risk control|风控|status code 403|HTTP 403/i.test(raw)) return '抖音暂时限制了本次访问，请稍后重试或登录增强后再试。';
  if (/Failed to fetch|NetworkError|fetch failed|ECONNREFUSED/i.test(raw)) return '本地服务暂时没有响应，请重新打开播录助手。';
  if (/timeout|timed out|超时/i.test(raw)) return '连接超时，请检查网络后重试。';
  return raw;
}

export async function api<T = any>(path: string, body?: unknown, method = body === undefined ? 'GET' : 'POST'): Promise<T> {
  const startedAt = Date.now();
  const trace = (values: Partial<ApiDebugEntry>) => emitDebug({
    id: ++debugSequence, startedAt, durationMs: Date.now() - startedAt, method, path: safePath(path),
    ok: false, request: body === undefined ? undefined : sanitize(body), ...values,
  });
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-LiveRecorder-Token': token },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    const message = friendlyError(error instanceof Error ? error.message : error);
    trace({ error: message });
    throw new Error(message);
  }
  let data: any;
  try { data = await response.json(); }
  catch {
    const message = '本地服务返回了无法识别的数据，请重新打开播录助手。';
    trace({ status: response.status, error: message });
    throw new Error(message);
  }
  trace({ status: response.status, ok: response.ok, response: sanitize(data), error: response.ok ? undefined : friendlyError(data.error || '请求失败') });
  if (!response.ok) throw new Error(friendlyError(data.error || '请求失败'));
  return data as T;
}

export const audioStreamUrl = (id: string) => `/api/interaction/audio-stream?token=${encodeURIComponent(token)}&id=${encodeURIComponent(id)}`;
export const mediaPreviewUrl = (path: string) => `/api/media/preview?token=${encodeURIComponent(token)}&path=${encodeURIComponent(path)}`;
export const mediaAudioPreviewUrl = (path: string) => `/api/media/audio-preview?token=${encodeURIComponent(token)}&path=${encodeURIComponent(path)}`;
