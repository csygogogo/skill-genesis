import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSSE, generateFromAPI } from '../src/stream.js';
const encoder = new TextEncoder();
function stream(bytes, size = 1) { return new ReadableStream({ start(c) { for (let i = 0; i < bytes.length; i += size) c.enqueue(bytes.slice(i, i + size)); c.close(); } }); }
async function collect(body) { const events = []; for await (const e of readSSE(body)) events.push(e); return events; }
test('UTF-8 中文按字节拆分，CRLF、注释心跳和结束帧', async () => {
  const input = ': ping\r\n\r\nevent: skill\r\ndata: {"id":"a","content":"中文内容"}\r\n\r\ndata: [DONE]\r\n\r\n';
  assert.deepEqual(await collect(stream(encoder.encode(input))), [{ type: 'skill', id: 'a', content: '中文内容' }, { type: 'done' }]);
});
test('多行 data、混合事件和没有空行的最后一帧', async () => {
  const input = 'data: {"type":"strategy",\ndata: "content":"调整"}\n\ndata: {"type":"done"}';
  assert.deepEqual(await collect(stream(encoder.encode(input), 7)), [{ type: 'strategy', content: '调整' }, { type: 'done' }]);
});
test('无效 JSON 和非对象事件明确报错', async () => {
  await assert.rejects(collect(stream(encoder.encode('data: bad\n\n'))), /JSON/);
  await assert.rejects(collect(stream(encoder.encode('data: null\n\n'))), /对象/);
});
test('提前结束消费时取消 reader', async () => {
  let canceled = false;
  const body = new ReadableStream({ start(c) { c.enqueue(encoder.encode('data: {"type":"done"}\n\n')); }, cancel() { canceled = true; } });
  for await (const e of readSSE(body)) { assert.equal(e.type, 'done'); break; }
  assert.equal(canceled, true);
});
test('API 发送约定的 POST body 和请求头并读取 SSE', async (t) => {
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    assert.equal(url, '/api/skills/generate'); assert.equal(init.method, 'POST');
    assert.deepEqual(JSON.parse(init.body), { intent: '写文档' });
    assert.equal(init.headers.Accept, 'text/event-stream');
    return new Response('data: {"type":"done"}\n\n', { headers: { 'Content-Type': 'text/event-stream' } });
  });
  const events = []; for await (const e of generateFromAPI('写文档', { endpoint: '/api/skills/generate' }, new AbortController().signal)) events.push(e);
  assert.deepEqual(events, [{ type: 'done' }]);
});
