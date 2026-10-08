import { readSSE } from './stream.js';

// 兼容已有的 /generate 配置；也可直接配置 /sessions。
export function sessionsURL(config) {
  return config.endpoint.replace(/\/$/, '').replace(/\/generate$/, '/sessions');
}

export async function api(config, path = '', options = {}) {
  const response = await fetch(sessionsURL(config) + path, {
    ...options, headers: { 'Content-Type': 'application/json', ...config.headers, ...options.headers },
  });
  if (!response.ok) throw new Error(`记录服务请求失败（HTTP ${response.status}），请检查后端和接口地址。`);
  return response;
}

export async function* sessionEvents(config, sessionId, signal, after = 0) {
  const response = await api(config, `/${encodeURIComponent(sessionId)}/events?after=${after}`, {
    signal, headers: { Accept: 'text/event-stream' },
  });
  if (!response.body || !response.headers.get('content-type')?.includes('text/event-stream')) throw new Error('记录接口未返回 SSE 事件流。');
  yield* readSSE(response.body);
}
