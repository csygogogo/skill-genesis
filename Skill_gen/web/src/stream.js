// POST + SSE: 支持 UTF-8 分片、多行 data、LF/CRLF、心跳与未以空行结束的最后一帧。
export async function* readSSE(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  function parse(frame) {
    let name = 'message';
    const data = [];
    for (const line of frame.split(/\r\n|\n|\r/)) {
      if (line.startsWith(':')) continue;
      const colon = line.indexOf(':');
      const field = colon < 0 ? line : line.slice(0, colon);
      let value = colon < 0 ? '' : line.slice(colon + 1);
      if (value.startsWith(' ')) value = value.slice(1);
      if (field === 'event') name = value;
      if (field === 'data') data.push(value);
    }
    if (!data.length) return null;
    const payload = data.join('\n');
    if (payload === '[DONE]') return { type: 'done' };
    let result;
    try { result = JSON.parse(payload); } catch { throw new Error('服务返回了无效的 SSE JSON 数据。'); }
    if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('SSE data 必须是 JSON 对象。');
    return { ...result, type: result.type || name };
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let match;
      while ((match = /\r\n\r\n|\n\n|\r\r/.exec(buffer))) {
        const frame = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        const event = parse(frame);
        if (event) yield event;
      }
      if (buffer.length > 2_000_000) throw new Error('单条流式消息过大，请拆分为增量事件。');
      if (done) { if (buffer.trim()) { const event = parse(buffer); if (event) yield event; } break; }
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

export async function* generateFromAPI(intent, config, signal) {
  // 后端对接入口：请求体、鉴权和自定义 header 均在此调整。
  const response = await fetch(config.endpoint, {
    method: 'POST', signal,
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...config.headers },
    body: JSON.stringify({ intent }),
  });
  if (!response.ok) throw new Error(`生成服务请求失败（HTTP ${response.status}）。请检查服务地址及后端日志。`);
  if (!response.headers.get('content-type')?.includes('text/event-stream')) throw new Error('接口需要返回 text/event-stream 格式。');
  if (!response.body) throw new Error('浏览器未获取到可读取的响应流。');
  yield* readSSE(response.body);
}
