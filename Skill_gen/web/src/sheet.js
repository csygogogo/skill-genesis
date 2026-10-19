// Excel / CSV 表格读取：零第三方依赖。
// .xlsx 是 ZIP + XML，用浏览器内置的 DecompressionStream（deflate-raw）与 DOMParser 解析；
// CSV 按引号规则切分并自动识别分隔符。输出二维文本表 rows[row][col]，列按 Excel 实际列位对齐。
// 仅支持 Excel 2007+ 的 .xlsx；旧版 .xls 是二进制格式，提示用户另存为 .xlsx 或 CSV。

const text = (bytes) => new TextDecoder().decode(bytes);

export async function readTable(file) {
  const name = (file.name || '').toLowerCase();
  if (name.endsWith('.csv') || file.type === 'text/csv') return parseCsv(await file.text());
  if (name.endsWith('.xlsx')) {
    if (typeof DecompressionStream === 'undefined' || typeof DOMParser === 'undefined')
      throw new Error('当前浏览器缺少解析 .xlsx 所需的能力，请换用新版 Chrome / Edge，或把文件另存为 CSV 再导入');
    return parseXlsx(await file.arrayBuffer());
  }
  throw new Error('暂只支持 .xlsx 与 .csv；旧版 .xls 请先在 Excel 里另存为 .xlsx 或 CSV');
}

// ---- CSV ----

function splitCsvLine(line, delimiter) {
  const cells = [];
  let cell = '', quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === delimiter) { cells.push(cell); cell = ''; }
    else cell += ch;
  }
  cells.push(cell);
  return cells.map(c => c.trim());
}

function parseCsv(raw) {
  const lines = raw.replace(/^\uFEFF/, '').split(/\r\n|\n|\r/).filter(line => line.trim());
  if (!lines.length) return [];
  // 分隔符取能把首行切出最多列的那一个（逗号 / 分号 / 制表符）。
  const delimiter = [',', ';', '\t']
    .map(d => ({ d, n: splitCsvLine(lines[0], d).length }))
    .sort((a, b) => b.n - a.n)[0].d;
  return lines.map(line => splitCsvLine(line, delimiter));
}

// ---- .xlsx ----

function zipEntries(buffer) {
  // 解析 ZIP 中央目录：从尾部定位 EOCD，逐条读出文件名、压缩方式与本地头偏移。
  const view = new DataView(buffer);
  let eocd = -1;
  for (let i = view.byteLength - 22; i >= 0 && i > view.byteLength - 65558; i--) {
    if (view.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error('不是有效的 .xlsx 文件（缺少 ZIP 目录）');
  const count = view.getUint16(eocd + 10, true);
  let offset = view.getUint32(eocd + 16, true);
  const files = new Map();
  for (let i = 0; i < count; i++) {
    if (view.getUint32(offset, true) !== 0x02014b50) break;
    const entry = {
      method: view.getUint16(offset + 10, true),
      size: view.getUint32(offset + 20, true),
      local: view.getUint32(offset + 42, true),
    };
    const nameLength = view.getUint16(offset + 28, true);
    const extraLength = view.getUint16(offset + 30, true);
    const commentLength = view.getUint16(offset + 32, true);
    entry.name = text(new Uint8Array(buffer, offset + 46, nameLength)).toLowerCase();
    files.set(entry.name, entry);
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return files;
}

async function readEntry(buffer, entry) {
  const header = new DataView(buffer, entry.local, 30);
  if (header.getUint32(0, true) !== 0x04034b50) throw new Error('xlsx 内部结构异常');
  const nameLength = header.getUint16(26, true), extraLength = header.getUint16(28, true);
  const start = entry.local + 30 + nameLength + extraLength;
  const data = new Uint8Array(buffer, start, entry.size);
  if (entry.method === 0) return data; // stored：未压缩
  const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function columnIndex(letters) {
  let n = 0;
  for (const ch of letters.toUpperCase()) n = n * 26 + (ch.codePointAt(0) - 64);
  return n - 1; // 'A' -> 0
}

function xml(textContent) {
  const doc = new DOMParser().parseFromString(textContent, 'application/xml');
  if (doc.getElementsByTagName('parsererror').length) throw new Error('xlsx 内部 XML 解析失败');
  return doc;
}

async function parseXlsx(buffer) {
  const files = zipEntries(buffer);
  const sheetName = [...files.keys()].filter(n => n.match(/^xl\/worksheets\/sheet\d+\.xml$/)).sort()[0];
  if (!sheetName) throw new Error('xlsx 里没有找到工作表');
  const sharedDoc = files.has('xl/sharedstrings.xml') ? xml(text(await readEntry(buffer, files.get('xl/sharedstrings.xml')))) : null;
  // 共享字符串表：<si> 内可能有多段富文本 <t>，拼接为一个单元格文本。
  const shared = sharedDoc ? [...sharedDoc.getElementsByTagName('si')]
    .map(si => [...si.getElementsByTagName('t')].map(t => t.textContent).join('')) : [];
  const doc = xml(text(await readEntry(buffer, files.get(sheetName))));
  const rows = [];
  for (const row of doc.getElementsByTagName('row')) {
    const cells = [];
    for (const cell of row.getElementsByTagName('c')) {
      const col = columnIndex((cell.getAttribute('r') || 'A').replace(/\d+/g, ''));
      const type = cell.getAttribute('t');
      const v = cell.getElementsByTagName('v')[0]?.textContent ?? '';
      // t="s" 共享字符串按下标取；t="inlineStr" 内联文本；否则为数值/公式结果。
      cells[col] = type === 's' ? (shared[Number(v)] ?? '') : type === 'inlineStr'
        ? (cell.getElementsByTagName('t')[0]?.textContent ?? '') : v;
    }
    rows.push(Array.from(cells, c => c ?? ''));
  }
  return rows;
}
