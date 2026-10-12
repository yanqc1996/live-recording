const token = new URLSearchParams(location.search).get('token') || '';

export function friendlyError(message: unknown): string {
  const raw = String(message || '').trim();
  if (!raw) return '操作失败，请稍后重试';
  if (/risk control|风控|status code 403|HTTP 403/i.test(raw)) return '抖音暂时限制了本次访问，请稍后重试或登录增强后再试。';
  if (/Failed to fetch|NetworkError|fetch failed|ECONNREFUSED/i.test(raw)) return '本地服务暂时没有响应，请重新打开播录助手。';
  if (/timeout|timed out|超时/i.test(raw)) return '连接超时，请检查网络后重试。';
  return raw;
}

export async function api<T = any>(path: string, body?: unknown, method = body === undefined ? 'GET' : 'POST'): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-LiveRecorder-Token': token },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    throw new Error(friendlyError(error instanceof Error ? error.message : error));
  }
  let data: any;
  try { data = await response.json(); }
  catch { throw new Error('本地服务返回了无法识别的数据，请重新打开播录助手。'); }
  if (!response.ok) throw new Error(friendlyError(data.error || '请求失败'));
  return data as T;
}

export const audioStreamUrl = (id: string) => `/api/interaction/audio-stream?token=${encodeURIComponent(token)}&id=${encodeURIComponent(id)}`;
