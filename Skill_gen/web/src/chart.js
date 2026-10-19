// 准确率曲线面板：手动输入或从 Excel/CSV 导入「优化轮次 + 准确率」数据点，SVG 折线图展示每轮优化后的准确率变化。
// 单序列折线（dataviz 规范）：紫色 2px 线 + 端点标记（白色描边环）、hairline 网格、
// 十字线 + tooltip 吸附最近轮次、终点数值直接标注；下方数据点列表即表格视图，tooltip 不承载唯一信息。
import { readTable } from './sheet.js';

const STORAGE_KEY = 'skill-studio-accuracy';
const VIEW = { w: 760, h: 300, top: 22, right: 28, bottom: 36, left: 48 };

let points = []; // [{round: 0, value: 62.5}]，按 round 升序。

const fmt = (v) => `${Number(v.toFixed(1))}%`;
const px = (round, domain) => VIEW.left + (round - domain[0]) / (domain[1] - domain[0]) * (VIEW.w - VIEW.left - VIEW.right);
const py = (value) => VIEW.top + (100 - value) / 100 * (VIEW.h - VIEW.top - VIEW.bottom);

function chartSvg() {
  const plotW = VIEW.w - VIEW.left - VIEW.right;
  const baseY = VIEW.h - VIEW.bottom;
  if (!points.length) return '';
  const lo = points[0].round, hi = points.at(-1).round;
  // 单点或同轮次时左右各留一格，点落在画布中部而非边缘。
  const domain = lo === hi ? [lo - 1, hi + 1] : [lo, hi];
  const span = domain[1] - domain[0];
  const x = (round) => px(round, domain);
  // 横轴刻度步长随轮次跨度调整，保持稀疏干净。
  const step = span <= 8 ? 1 : span <= 16 ? 2 : span <= 40 ? 5 : 10;
  const xTicks = [];
  for (let r = Math.ceil(domain[0] / step) * step; r <= domain[1]; r += step) xTicks.push(r);
  const yTicks = [0, 20, 40, 60, 80, 100];
  const grid = yTicks.slice(1).map(t => `<line class="acc-grid" x1="${VIEW.left}" y1="${py(t)}" x2="${VIEW.w - VIEW.right}" y2="${py(t)}"/>`).join('');
  const yText = yTicks.map(t => `<text class="acc-tick" x="${VIEW.left - 9}" y="${py(t) + 3.5}" text-anchor="end">${t}</text>`).join('');
  const xText = xTicks.map(r => `<text class="acc-tick" x="${x(r)}" y="${baseY + 17}" text-anchor="middle">${r}</text>`).join('');
  const dots = points.map(p => `<circle class="acc-dot" data-round="${p.round}" cx="${x(p.round)}" cy="${py(p.value)}" r="4.5"/>`).join('');
  const line = points.length > 1 ? `<polyline class="acc-line" points="${points.map(p => `${x(p.round)},${py(p.value)}`).join(' ')}"/>` : '';
  const area = points.length > 1
    ? `<polygon class="acc-area" points="${VIEW.left},${baseY} ${points.map(p => `${x(p.round)},${py(p.value)}`).join(' ')} ${VIEW.w - VIEW.right},${baseY}"/>` : '';
  // 只标注终点数值（选择性直接标注）；靠近右缘时锚点内收，防止截断。
  const last = points.at(-1);
  const lastX = x(last.round), flip = lastX > VIEW.w - VIEW.right - 46;
  const endLabel = `<text class="acc-value" x="${lastX + (flip ? -10 : 10)}" y="${py(last.value) - 9}" text-anchor="${flip ? 'end' : 'start'}">${fmt(last.value)}</text>`;
  const caption = `<text class="acc-caption" x="${VIEW.w - VIEW.right}" y="${VIEW.top - 8}" text-anchor="end">准确率（%）</text><text class="acc-caption" x="${VIEW.w - VIEW.right}" y="${VIEW.h - 6}" text-anchor="end">优化轮次</text>`;
  const label = `准确率曲线：${points.length} 个数据点，第 ${lo} 轮 ${fmt(points[0].value)} 到第 ${hi} 轮 ${fmt(last.value)}`;
  return `<svg viewBox="0 0 ${VIEW.w} ${VIEW.h}" role="img" aria-label="${label}">
    ${grid}${area}${line}${dots}${endLabel}${yText}${xText}
    <line class="acc-axis" x1="${VIEW.left}" y1="${baseY}" x2="${VIEW.w - VIEW.right}" y2="${baseY}"/>
    <line class="acc-axis" x1="${VIEW.left}" y1="${VIEW.top}" x2="${VIEW.left}" y2="${baseY}"/>
    ${caption}
    <line class="acc-cross" id="acc-cross" x1="0" y1="${VIEW.top}" x2="0" y2="${baseY}" visibility="hidden"/>
    <rect class="acc-hit" x="${VIEW.left - plotW * 0.02}" y="${VIEW.top}" width="${plotW * 1.04}" height="${baseY - VIEW.top}" fill="transparent"/>
  </svg>`;
}

// 把表格行解析为数据点：优先按表头关键字（轮次 / 准确率，支持英文）定位列；
// 无表头时回退「前两列数字」；只有一列数值时按行序从 1 编轮次；
// 全部数值 ≤ 1 时视为 0–1 比例自动换算成百分比。无效行忽略并计数。
function tableToPoints(rows) {
  rows = rows.filter(row => row.some(cell => String(cell ?? '').trim()));
  if (!rows.length) return { points: [], ignored: 0, note: '' };
  let roundCol = -1, accCol = -1;
  (rows[0] || []).forEach((cell, i) => {
    if (roundCol < 0 && /轮次|轮数|round/i.test(cell)) roundCol = i;
    if (accCol < 0 && /准确率|正确率|accuracy|acc\b/i.test(cell)) accCol = i;
  });
  let sequential = false, start = 0;
  if (accCol >= 0 && roundCol < 0) { sequential = true; start = 1; }       // 只有准确率列：按行序编轮次
  else if (roundCol >= 0 && accCol >= 0) start = 1;                        // 两列表头齐备
  else {                                                                    // 无表头：前两列数字，或单列数值
    const numeric = rows[0].filter(cell => cell !== '' && Number.isFinite(Number(cell))).length;
    sequential = numeric < 2;
    roundCol = sequential ? -1 : 0;
    accCol = sequential ? 0 : 1;
  }
  let items = [], ignored = 0, order = 0;
  for (let r = start; r < rows.length; r++) {
    const row = rows[r];
    const round = sequential ? ++order : Number(row[roundCol]);
    const acc = Number(String(row[accCol] ?? '').replace('%', ''));
    if (!Number.isFinite(acc) || (!sequential && (!Number.isInteger(round) || round < 0 || round > 100000))
        || acc < 0 || acc > 100) { ignored++; continue; }
    items.push({ round: sequential ? order : round, value: acc });
  }
  let note = '';
  if (items.length && items.every(p => p.value <= 1) && items.some(p => p.value > 0)) {
    items = items.map(p => ({ round: p.round, value: Math.round(p.value * 1000) / 10 }));
    note = '数值均在 0–1 区间，已按百分比换算';
  }
  return { points: items, ignored, note };
}

export function initAccuracyChart(notify) {
  const $ = (id) => document.getElementById(id);
  const form = $('accuracy-form'), chips = $('accuracy-chips'), plot = $('accuracy-plot');
  const stage = $('accuracy-stage'), empty = $('accuracy-empty'), tooltip = $('accuracy-tooltip');
  const panel = document.querySelector('.chart-panel'), fileInput = $('accuracy-file');
  try { const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); if (Array.isArray(saved)) points = saved.filter(p => Number.isFinite(p?.round) && Number.isFinite(p?.value)).map(p => ({ round: Math.round(p.round), value: Math.min(100, Math.max(0, p.value)) })); } catch {}
  points.sort((a, b) => a.round - b.round);
  const save = () => { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(points)); } catch {} };

  function renderChips() {
    chips.replaceChildren();
    for (const p of points) {
      const chip = document.createElement('span');
      chip.className = 'acc-chip';
      const text = document.createElement('span');
      text.textContent = `第 ${p.round} 轮 · ${fmt(p.value)}`;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = '×';
      remove.setAttribute('aria-label', `删除第 ${p.round} 轮的数据点`);
      remove.addEventListener('click', () => {
        points = points.filter(item => item.round !== p.round);
        save(); render(); notify(`已删除第 ${p.round} 轮的数据点`);
      });
      chip.append(text, remove);
      chips.append(chip);
    }
  }

  function renderChart() {
    $('accuracy-count').textContent = `${points.length} 个数据点`;
    const has = points.length > 0;
    stage.hidden = !has; empty.hidden = has;
    if (!has) { tooltip.hidden = true; return; }
    plot.innerHTML = chartSvg();
    wireHover();
  }

  const spanDomain = () => {
    const lo = points[0].round, hi = points.at(-1).round;
    return lo === hi ? [lo - 1, hi + 1] : [lo, hi];
  };

  // 十字线跟随指针并吸附最近的数据轮次：值为主、标签为辅，随点放大端点。
  function wireHover() {
    const svg = plot.querySelector('svg'), cross = svg.querySelector('#acc-cross');
    const hit = svg.querySelector('.acc-hit');
    const dots = [...svg.querySelectorAll('.acc-dot')];
    const focus = (point) => {
      const scale = plot.clientWidth / VIEW.w;
      const cx = px(point.round, spanDomain()), dot = dots.find(d => Number(d.dataset.round) === point.round);
      cross.setAttribute('x1', cx); cross.setAttribute('x2', cx); cross.setAttribute('visibility', 'visible');
      dots.forEach(d => d.setAttribute('r', 4.5));
      if (dot) dot.setAttribute('r', 6);
      tooltip.replaceChildren();
      const value = document.createElement('strong'); value.textContent = fmt(point.value);
      const label = document.createElement('span'); label.textContent = `第 ${point.round} 轮`;
      tooltip.append(value, label);
      tooltip.hidden = false;
      const left = Math.min(Math.max(cx * scale + 12, 6), plot.clientWidth - tooltip.offsetWidth - 6);
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${Math.max(py(point.value) * scale - tooltip.offsetHeight - 10, 4)}px`;
    };
    const clear = () => { cross.setAttribute('visibility', 'hidden'); dots.forEach(d => d.setAttribute('r', 4.5)); tooltip.hidden = true; };
    hit.addEventListener('pointermove', (event) => {
      const rect = svg.getBoundingClientRect();
      const scale = rect.width / VIEW.w;
      const sx = (event.clientX - rect.left) / scale; // 指针在 viewBox 坐标系中的 x
      let best = points[0];
      for (const p of points) if (Math.abs(px(p.round, spanDomain()) - sx) < Math.abs(px(best.round, spanDomain()) - sx)) best = p;
      focus(best);
    });
    hit.addEventListener('pointerleave', clear);
  }

  function render() { renderChips(); renderChart(); }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const round = Number($('accuracy-round').value), value = Number($('accuracy-value').value);
    if (!Number.isInteger(round) || round < 0) { notify('轮次需为不小于 0 的整数'); return; }
    if (!Number.isFinite(value) || value < 0 || value > 100) { notify('准确率需在 0–100% 之间'); return; }
    const exists = points.some(p => p.round === round);
    points = points.filter(p => p.round !== round).concat({ round, value }).sort((a, b) => a.round - b.round);
    save(); render();
    notify(exists ? `已更新第 ${round} 轮的准确率为 ${fmt(value)}` : `已记录第 ${round} 轮 · ${fmt(value)}`);
    $('accuracy-round').value = ''; $('accuracy-value').value = ''; $('accuracy-round').focus();
  });

  $('accuracy-clear').addEventListener('click', () => {
    if (!points.length) return;
    points = []; save(); render(); notify('已清空全部数据点');
  });

  // Excel / CSV 导入：与已有数据合并，同轮次以导入值为准；解析失败的行忽略并计数。
  async function importFile(file) {
    if (!file) return;
    try {
      const { points: imported, ignored, note } = tableToPoints(await readTable(file));
      if (!imported.length) throw new Error('未识别到「轮次 + 准确率」数据；请确认表格含这两列（或两列数字）');
      const merged = new Map(points.map(p => [p.round, p.value]));
      for (const p of imported) merged.set(p.round, p.value);
      points = [...merged].map(([round, value]) => ({ round, value })).sort((a, b) => a.round - b.round);
      save(); render();
      notify(`已从 ${file.name} 导入 ${imported.length} 个数据点`
        + (merged.size > imported.length ? `，合并后共 ${merged.size} 个` : '')
        + (ignored ? `，忽略 ${ignored} 行无效数据` : '') + (note ? `（${note}）` : ''));
    } catch (error) {
      notify(`导入失败：${error.message}`);
    }
  }

  $('accuracy-import').addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => { importFile(fileInput.files[0]); fileInput.value = ''; });
  // 面板支持直接拖入 .xlsx / .csv 文件。
  panel.addEventListener('dragover', (event) => { event.preventDefault(); panel.classList.add('dragging'); });
  panel.addEventListener('dragleave', () => panel.classList.remove('dragging'));
  panel.addEventListener('drop', (event) => {
    event.preventDefault(); panel.classList.remove('dragging');
    importFile(event.dataTransfer?.files?.[0]);
  });

  render();
}
