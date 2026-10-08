import { api, sessionEvents } from './api.js';
import { generateDemo } from './demo.js';
const $ = (id) => document.getElementById(id);
const defaults = window.SKILL_STUDIO_CONFIG || {};
let saved = {};
try { saved = JSON.parse(localStorage.getItem('skill-studio-settings') || '{}') || {}; } catch {}
// 其他设备的 127.0.0.1 指向它自己；清除旧版本保存的本机接口地址。
try {
  if (!['127.0.0.1', 'localhost', '[::1]'].includes(location.hostname)
      && ['127.0.0.1', 'localhost', '[::1]'].includes(new URL(saved.endpoint).hostname)) delete saved.endpoint;
} catch {}
let config = { ...defaults, mode: saved.mode || defaults.mode || 'api', endpoint: saved.endpoint || defaults.endpoint };
let events = [], selectedVersion = '', filter = 'all', running = false, controller;
let toastTimer, currentSession = null, sessionConfig = null, view = 0, historyLimit = 50, historyRequest = 0, pendingDelete = null;
const sessionLabels = { queued: '排队中', running: '生成中', completed: '已完成', failed: '失败', stopped: '已停止', interrupted: '已中断', deleted: '已删除' };
const labels = { subgraph: '子图信息', skill: '初始 Skill', optimized_skill: '优化后的 Skill', strategy: '调整策略', execution_trace: '执行轨迹', final_skill: '最终 Skill' };
const isSkill = (event) => ['skill', 'optimized_skill', 'final_skill'].includes(event.type);
const currentVersion = () => events.find(e => e.id === selectedVersion);
const escape = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const versionLabel = (v) => v.type === 'skill' ? 'V0 · 初始版本' : v.type === 'final_skill' ? `最终版本 · 第 ${v.round ?? '—'} 轮` : `V${v.round ?? '—'} · 第 ${v.round ?? '—'} 轮优化`;
function toast(text) { $('toast').textContent = text; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 2600); }
function connection() { $('connection-label').innerHTML = `${config.mode === 'demo' ? '演示模式' : 'API 模式'}<small>${config.mode === 'demo' ? '仅临时预览，不保存' : 'FastAPI · 后端持久记录'}</small>`; }
function markdown(text) {
  // 仅渲染安全子集；后端 HTML 一律转义，不接受脚本、图片或链接。
  const lines = text.split('\n');
  let output = '', code = false, frontmatter = false, list = '';
  const closeList = () => { if (list) { output += `</${list}>`; list = ''; } };
  const inline = (s) => escape(s).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (i === 0 && line === '---') { frontmatter = true; output += '<pre>'; continue; }
    if (frontmatter) { if (line === '---') { frontmatter = false; output += '</pre>'; } else output += escape(line) + '\n'; continue; }
    if (line.startsWith('```')) { closeList(); output += code ? '</code></pre>' : '<pre><code>'; code = !code; continue; }
    if (code) { output += escape(line) + '\n'; continue; }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    const item = /^(?:([-*])|\d+\.)\s+(.+)$/.exec(line);
    if (item) { const kind = item[1] ? 'ul' : 'ol'; if (list !== kind) { closeList(); list = kind; output += `<${kind}>`; } output += `<li>${inline(item[2])}</li>`; }
    else { closeList(); if (heading) output += `<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`; else if (line.trim()) output += `<p>${inline(line)}</p>`; }
  }
  closeList(); if (code) output += '</code></pre>'; if (frontmatter) output += '</pre>';
  return `<div class="markdown">${output}</div>`;
}
function graph(event) {
  const nodes = Array.isArray(event.nodes) ? event.nodes : [];
  const edges = Array.isArray(event.edges) ? event.edges : [];
  if (!nodes.length) return '';
  const width = 380, height = Math.max(120, Math.ceil((nodes.length - 1) / 2) * 46 + 20);
  const positions = nodes.map((n, i) => i === 0 ? [190, height / 2] : [i % 2 ? 61 : 319, 28 + Math.floor((i - 1) / 2) * 46]);
  const map = new Map(nodes.map((n, i) => [String(n.id), positions[i]]));
  return `<svg class="graph" style="height:${height}px" viewBox="0 0 ${width} ${height}" role="img" aria-label="任务知识子图">${edges.map(e => { const a = map.get(String(e.source)), b = map.get(String(e.target)); return a && b ? `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}"/>` : ''; }).join('')}${nodes.map((n, i) => `<g><title>${escape(n.label || n.id)}</title><rect class="${i === 0 ? 'root-node' : ''}" x="${positions[i][0] - 48}" y="${positions[i][1] - 15}" width="96" height="30" rx="6"/><text x="${positions[i][0]}" y="${positions[i][1] + 4}" text-anchor="middle">${escape(String(n.label || n.id).slice(0, 8))}</text></g>`).join('')}</svg><div class="graph-legend"><span>${nodes.length} 个节点</span><span>${edges.length} 条关联</span></div>`;
}
function traceCard(event) {
  const state = { running: '执行中', completed: '执行完成', failed: '执行失败' };
  const skill = events.find(e => isSkill(e) && e.id === event.skill_id);
  return `<h3>${escape(event.title || 'Skill 执行记录')} <span class="trace-status">${state[event.status] || '执行记录'}</span></h3><p class="event-summary">${escape(event.content || '等待执行输出…')}</p>${skill ? `<button class="event-action" data-version="${escape(skill.id)}">查看执行的 Skill · ${escape(versionLabel(skill))} →</button>` : ''}`;
}
function renderTimeline() {
  const box = $('timeline');
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 75;
  const visible = events.filter(e => filter === 'all' || e.type === filter || (filter === 'optimized_skill' && e.type === 'final_skill'));
  box.innerHTML = visible.length ? visible.map(e => `<article class="event" data-type="${e.type}"><span class="event-icon">${e.type === 'subgraph' ? '⌘' : e.type === 'strategy' ? '↗' : e.type === 'execution_trace' ? '▷' : '✓'}</span><div class="event-header">${labels[e.type]}<span class="event-tag ${e.type === 'final_skill' ? 'final' : ''}">${e.type === 'subgraph' ? 'KNOWLEDGE' : e.type === 'final_skill' ? 'FINAL' : e.round != null ? `第 ${escape(e.round)} 轮` : 'V0'}</span><time>${escape(e.time)}</time></div><div class="event-card ${e.type === 'strategy' ? 'strategy-card' : e.type === 'execution_trace' ? 'trace-card' : ''}">${e.type === 'subgraph' ? `<h3>${escape(e.title || '任务知识子图')}</h3><p class="event-summary">${escape(e.content)}</p>${graph(e)}` : e.type === 'execution_trace' ? traceCard(e) : e.type === 'strategy' ? `<div class="strategy-text">${escape(e.content || '正在接收调整策略…')}</div>` : `<h3>${e.type === 'final_skill' ? '优化完成，可查看并下载' : e.type === 'skill' ? '已生成基础任务结构' : '已更新执行指令与约束'}</h3><p class="event-summary">${escape(e.summary || `${e.content.length} 字符 · ${e.type === 'skill' ? '初始版本' : '保留完整版本内容'}`)}</p><button class="event-action" data-version="${escape(e.id)}">查看此版本 <span>→</span></button>`}</div></article>`).join('') : `<div class="empty-state"><p>${events.length ? '当前标签下还没有输出' : '正在等待服务返回第一条信息…'}</p></div>`;
  $('event-count').textContent = events.length;
  if (nearBottom) box.scrollTop = box.scrollHeight;
}
function renderPreview() {
  const versions = events.filter(isSkill);
  $('version').disabled = !versions.length;
  $('version').innerHTML = versions.length ? versions.map(v => `<option value="${escape(v.id)}">${escape(versionLabel(v))}</option>`).join('') : '<option>暂无版本</option>';
  $('version').value = selectedVersion;
  $('version-count').textContent = `${versions.length} 个版本`;
  const v = currentVersion();
  $('copy').disabled = $('download').disabled = !v?.content;
  $('latest-label').textContent = v && v.id !== versions.at(-1)?.id ? '历史版本' : '最新版本';
  if (v) { $('skill-content').innerHTML = markdown(v.content); $('preview-version').textContent = v.type === 'final_skill' ? 'FINAL' : `V${v.round ?? 0}`; $('preview-subtitle').textContent = versionLabel(v); }
}
function receive(event) {
  if (event.type === 'error') throw new Error(event.message || event.content || '后端生成失败。');
  if (event.type === 'done' || event.type === 'heartbeat') return;
  if (!Object.hasOwn(labels, event.type)) throw new Error(`未识别的事件类型：${event.type}。请按 README 中的协议对接。`);
  if (event.content != null && typeof event.content !== 'string') throw new Error('事件 content 必须为字符串。');
  if (event.delta != null && typeof event.delta !== 'string') throw new Error('事件 delta 必须为字符串。');
  if (event.delta != null && !event.id) throw new Error('增量事件必须提供稳定的 id。');
  const id = String(event.id || `${event.type}-${events.length}`);
  let entry = events.find(e => e.id === id);
  const follow = !selectedVersion || selectedVersion === events.filter(isSkill).at(-1)?.id;
  if (entry && entry.type !== event.type) throw new Error('不同事件类型必须使用不同的 id。');
  if (!entry) { entry = { id, content: '', time: new Date(event.created_at || Date.now()).toLocaleTimeString('zh-CN', { hour12: false }) }; events.push(entry); }
  const previous = entry.content;
  Object.assign(entry, event, { id, time: entry.time, content: event.delta != null ? previous + event.delta : event.content ?? previous });
  if (isSkill(entry)) {
    if (follow) selectedVersion = events.filter(isSkill).at(-1).id;
    renderPreview();
  }
  status(event.type === 'execution_trace' ? '执行中' : '生成中', 'running');
  const stage = event.type === 'strategy' ? 'optimized_skill' : event.type;
  let passed = true;
  document.querySelectorAll('[data-stage]').forEach(el => { el.classList.toggle('current', el.dataset.stage === stage); el.classList.toggle('done', passed && el.dataset.stage !== stage); if (el.dataset.stage === stage) passed = false; });
  renderTimeline();
}
function status(text, className = '') { $('run-status').textContent = text; $('run-status').className = `status ${className}`; }
function busy(value) { running = value; $('generate').hidden = value; $('stop').hidden = !value; $('intent').disabled = value; $('try-demo')?.toggleAttribute('disabled', value); document.querySelectorAll('[data-prompt]').forEach(b => b.disabled = value); }
function resetView() {
  view++;
  controller?.abort(); controller = new AbortController();
  busy(false); currentSession = null; sessionConfig = null;
  events = []; selectedVersion = ''; setFilter('all');
  $('skill-content').innerHTML = '<div class="preview-empty"><h3>等待 Skill 内容</h3><p>生成或选择一条历史记录。</p></div>';
  $('preview-version').textContent = '—'; $('preview-subtitle').textContent = '等待第一个版本';
  $('error-banner').hidden = true; $('elapsed').textContent = '00:00';
  renderTimeline(); renderPreview(); status('准备就绪');
  document.querySelectorAll('[data-stage]').forEach(el => el.classList.remove('current', 'done'));
  return view;
}
function showError(error) {
  $('error-banner').textContent = error instanceof TypeError ? '无法连接后端。已提交的任务仍可能在运行，请刷新记录后查看。' : error.message;
  $('error-banner').hidden = false;
}
async function watch(stream, token, started, persistent) {
  busy(true); $('stop').disabled = false; status('生成中', 'running');
  $('stream-label').textContent = persistent ? '记录已保存 · 关闭页面不会停止任务' : '临时演示 · 刷新后不保留';
  const tick = () => { const seconds = Math.max(0, Math.floor((Date.now() - started) / 1000)); $('elapsed').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`; };
  tick(); const timer = setInterval(tick, 1000);
  try {
    let done;
    for await (const event of stream) {
      if (token !== view) return;
      if (event.type === 'done') { done = event; break; }
      receive(event);
    }
    if (token !== view) return;
    if (!done) throw new Error('查看连接已断开；后端任务不会因此停止。点击刷新记录，再选择当前记录重新连接。');
    const state = done.status || 'completed';
    if (currentSession) { currentSession.status = state; currentSession.updated_at = done.created_at || currentSession.updated_at; }
    status(sessionLabels[state] || '已结束', state === 'completed' ? 'complete' : '');
    $('stream-label').textContent = persistent ? `${sessionLabels[state] || '已结束'} · 所有已接收内容保存在后端` : '演示结束 · 数据不保存';
    if (done.message) { $('error-banner').textContent = done.message; $('error-banner').hidden = false; }
    if (state === 'completed') document.querySelectorAll('[data-stage]').forEach(el => el.classList.add('done'));
  } catch (error) {
    if (token !== view) return;
    if (error.name === 'AbortError') { status('已停止'); $('stream-label').textContent = '临时演示已停止'; }
    else { status('查看异常', 'error'); showError(error); }
  } finally {
    clearInterval(timer);
    if (token === view) {
      busy(false); document.querySelectorAll('[data-stage]').forEach(el => el.classList.remove('current'));
      if (currentSession && !['queued', 'running'].includes(currentSession.status)) {
        const seconds = Math.max(0, Math.floor((Date.parse(currentSession.updated_at) - Date.parse(currentSession.created_at)) / 1000));
        $('elapsed').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
      }
      refreshHistory();
    }
  }
}
async function generate(forceDemo = false) {
  if (running) return;
  const intent = $('intent').value.trim();
  if (!intent) { $('intent').focus(); toast('请先描述你想生成的 Skill'); return; }
  const runConfig = { ...config, mode: forceDemo ? 'demo' : config.mode };
  const token = resetView(); busy(true);
  if (runConfig.mode === 'demo') { await watch(generateDemo(intent, controller.signal), token, Date.now(), false); return; }
  try {
    status('正在保存', 'running'); $('stop').disabled = true;
    const session = await (await api(runConfig, '', { method: 'POST', body: JSON.stringify({ intent }), signal: controller.signal })).json();
    if (token !== view) return;
    currentSession = session; sessionConfig = runConfig; refreshHistory();
    await watch(sessionEvents(runConfig, session.id, controller.signal), token, Date.parse(session.created_at), true);
  } catch (error) {
    if (token === view) { busy(false); status('提交异常', 'error'); showError(error); refreshHistory(); }
  }
}
async function openSession(id) {
  const token = resetView(), runConfig = { ...config };
  try {
    const session = await (await api(runConfig, `/${encodeURIComponent(id)}`, { signal: controller.signal })).json();
    if (token !== view) return;
    currentSession = session; sessionConfig = runConfig; $('intent').value = session.intent; count();
    document.querySelectorAll('[data-session]').forEach(el => { el.classList.toggle('active', el.dataset.session === id); el.setAttribute('aria-current', String(el.dataset.session === id)); });
    await watch(sessionEvents(runConfig, id, controller.signal), token, Date.parse(session.created_at), true);
  } catch (error) { if (token === view) { showError(error); busy(false); } }
}
async function refreshHistory(openLatest = false) {
  const request = ++historyRequest, currentView = view, runConfig = { ...config };
  if (config.mode === 'demo') {
    $('history-list').innerHTML = ''; $('history-count').textContent = '—'; $('more-history').hidden = true;
    $('history-message').textContent = '演示模式不保存记录。切换 API 模式查看后端历史。'; return;
  }
  try {
    const result = await (await api(runConfig, `?limit=${Math.min(historyLimit, 200)}`)).json();
    // 超过 200 条时按页获取，避免截断更早的记录。
    for (let offset = 200; offset < Math.min(historyLimit, result.total); offset += 200) {
      const page = await (await api(runConfig, `?limit=${Math.min(200, historyLimit - offset)}&offset=${offset}`)).json();
      result.items.push(...page.items);
    }
    if (request !== historyRequest) return;
    $('history-count').textContent = result.total;
    $('history-message').textContent = result.total ? '保存在后端历史文件夹 · 切换会话不停止任务' : '暂无记录，输入意图开始生成';
    $('history-list').innerHTML = result.items.map(item => `<div class="history-row"><button type="button" class="history-item ${item.id === currentSession?.id ? 'active' : ''}" data-session="${escape(item.id)}" aria-current="${item.id === currentSession?.id}"><strong>${escape(item.intent)}</strong><small><span>${escape(sessionLabels[item.status] || item.status)}</span><span>${escape(new Date(item.created_at).toLocaleString('zh-CN', { hour12: false }))}</span></small></button><button type="button" class="delete-history" data-delete="${escape(item.id)}" data-intent="${escape(item.intent)}" aria-label="删除记录：${escape(item.intent)}">删除</button></div>`).join('');
    $('more-history').hidden = result.items.length >= result.total;
    if (openLatest && currentView === view && !currentSession && result.items.length) openSession(result.items[0].id);
  } catch (error) {
    if (request === historyRequest) $('history-message').textContent = '暂时无法读取后端记录，请检查服务或点击刷新。';
  }
}
$('new-session').addEventListener('click', () => { resetView(); $('intent').value = ''; count(); $('intent').focus(); $('stream-label').textContent = '新建生成 · 之前的任务仍在后端执行'; refreshHistory(); });
$('refresh-history').addEventListener('click', () => refreshHistory());
$('more-history').addEventListener('click', () => { historyLimit += 50; refreshHistory(); });
$('history-list').addEventListener('click', e => {
  const remove = e.target.closest('[data-delete]');
  if (remove) {
    pendingDelete = { id: remove.dataset.delete, config: { ...config } };
    $('delete-intent').textContent = remove.dataset.intent;
    $('delete-error').hidden = true;
    $('delete-dialog').showModal();
    return;
  }
  const button = e.target.closest('[data-session]'); if (button) openSession(button.dataset.session);
});
$('cancel-delete').addEventListener('click', () => $('delete-dialog').close());
$('delete-dialog').addEventListener('close', () => { pendingDelete = null; });
$('delete-dialog').addEventListener('cancel', e => { if ($('confirm-delete').disabled) e.preventDefault(); });
$('confirm-delete').addEventListener('click', async () => {
  if (!pendingDelete || $('confirm-delete').disabled) return;
  const target = pendingDelete;
  $('confirm-delete').disabled = $('cancel-delete').disabled = true;
  $('confirm-delete').textContent = '正在删除…';
  try {
    await api(target.config, `/${encodeURIComponent(target.id)}`, { method: 'DELETE' });
    if (currentSession?.id === target.id && sessionConfig?.endpoint === target.config.endpoint) {
      resetView(); $('intent').value = ''; count();
      $('stream-label').textContent = '记录已删除，可以新建生成';
    }
    $('delete-dialog').close(); toast('记录及后端文件已删除');
    await refreshHistory();
  } catch (error) {
    $('delete-error').textContent = '删除失败，请检查后端后重试；记录未从界面移除。';
    $('delete-error').hidden = false;
  } finally {
    $('confirm-delete').disabled = $('cancel-delete').disabled = false;
    $('confirm-delete').textContent = '确认删除';
  }
});
$('intent-form').addEventListener('submit', e => { e.preventDefault(); generate(); });
$('intent').addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !e.isComposing) { e.preventDefault(); generate(); } });
const count = () => $('char-count').textContent = `${$('intent').value.length} / 8000`;
$('intent').addEventListener('input', count);
document.querySelectorAll('[data-prompt]').forEach(b => b.addEventListener('click', () => { $('intent').value = b.dataset.prompt; count(); $('intent').focus(); }));
$('try-demo').addEventListener('click', () => { if (!$('intent').value.trim()) $('intent').value = document.querySelector('[data-prompt]').dataset.prompt; count(); generate(true); });
$('stop').addEventListener('click', async () => {
  if (!currentSession) { controller?.abort(); return; }
  try { await api(sessionConfig, `/${encodeURIComponent(currentSession.id)}/stop`, { method: 'POST' }); refreshHistory(); }
  catch (error) { toast('停止请求失败，请重试；任务仍可能在后端运行。'); }
});
function setFilter(value) {
  filter = value;
  document.querySelectorAll('[data-filter]').forEach(el => { const active = el.dataset.filter === value; el.classList.toggle('active', active); el.setAttribute('aria-pressed', String(active)); });
}
$('filters').addEventListener('click', e => { const b = e.target.closest('[data-filter]'); if (b) { setFilter(b.dataset.filter); renderTimeline(); } });
$('timeline').addEventListener('click', e => { const b = e.target.closest('[data-version]'); if (b) { selectedVersion = b.dataset.version; renderPreview(); if (innerWidth < 950) $('preview-title').scrollIntoView({ behavior: 'smooth', block: 'center' }); } });
$('version').addEventListener('change', e => { selectedVersion = e.target.value; renderPreview(); });
$('copy').addEventListener('click', async () => { const v = currentVersion(); if (!v) return; try { await navigator.clipboard.writeText(v.content); toast('Skill 已复制'); } catch { toast('浏览器未允许复制，请下载 Skill 文件'); } });
$('download').addEventListener('click', async () => {
  const version = currentVersion(); if (!version) return;
  try {
    const blob = currentSession
      ? await (await api(sessionConfig, `/${encodeURIComponent(currentSession.id)}/versions/${encodeURIComponent(version.id)}/download`)).blob()
      : new Blob([version.content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = 'SKILL.md'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); toast('已下载当前版本');
  } catch (error) { toast('下载失败，请检查后端连接后重试。'); }
});
function settings() { $('mode').value = config.mode; $('endpoint').value = config.endpoint || ''; $('settings').showModal(); }
$('open-settings').addEventListener('click', settings); $('settings-top').addEventListener('click', settings);
$('close-settings').addEventListener('click', () => $('settings').close());
$('settings-form').addEventListener('submit', e => {
  e.preventDefault(); const endpoint = $('endpoint').value.trim();
  if ($('mode').value === 'api') { try { const url = new URL(endpoint, location.href); if (!['http:', 'https:'].includes(url.protocol) || !endpoint || url.username || url.password) throw new Error(); } catch { toast('请输入有效的 HTTP / HTTPS 地址或相对接口路径'); return; } }
  config = { ...config, mode: $('mode').value, endpoint };
  let stored = true; try { localStorage.setItem('skill-studio-settings', JSON.stringify({ mode: config.mode, endpoint })); } catch { stored = false; }
  connection(); refreshHistory(); $('settings').close(); toast(!stored ? '设置已应用，浏览器不允许持久保存' : running ? '设置已保存，将在下次生成时生效' : '连接设置已保存');
});
connection();
refreshHistory(true);
setInterval(() => { if (!document.hidden) refreshHistory(); }, 5000);
