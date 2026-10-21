// Skill 编辑记录面板：加载 output/edit_records.json（经 /api/skills/edit-records），
// 按轮次展示每轮优化对 Skill 的具体修改。两级选择：轮次 tab → 单条编辑，右侧看详情。
// 记录字段：session/round/task_ids/accuracy/generated_at/edit_count/edits[]，
// edits[] 含 index/op/status/skill_name/references/target/summary/content。
const OP_LABELS = { append_section: '追加章节', add_reference: '新增参考', update_section: '修订章节', update_description: '更新描述' };
const STATUS_LABELS = { applied: '已生效', failed: '失败', pending: '待应用' };

const accuracyText = (value) => {
  const percent = Number(value);
  if (!Number.isFinite(percent)) return '—';
  return `${Number(((percent <= 1 ? percent * 100 : percent)).toFixed(1))}%`;
};

export function initEditRecords({ toast, load, markdown }) {
  const $ = (id) => document.getElementById(id);
  const panel = $('edit-records-panel'), empty = $('edit-records-empty'), main = $('edit-records-main');
  const tabs = $('record-tabs'), meta = $('record-meta'), list = $('edit-list'), detail = $('edit-detail');
  let records = [], recordIndex = 0, editIndex = 0;

  const pick = (record) => (Array.isArray(record.edits) ? record.edits.filter(e => e && typeof e === 'object') : []);

  function renderTabs() {
    tabs.replaceChildren();
    records.forEach((record, i) => {
      const tab = document.createElement('button');
      tab.type = 'button';
      tab.className = 'record-tab' + (i === recordIndex ? ' active' : '');
      const tasks = Array.isArray(record.task_ids) && record.task_ids.length ? record.task_ids.join(' / ') : '无用例';
      tab.textContent = `第 ${record.round ?? '?'} 轮 · ${tasks} · ${accuracyText(record.accuracy)}`;
      tab.title = `会话 ${record.session || '—'}`;
      tab.addEventListener('click', () => { recordIndex = i; editIndex = 0; renderRecord(); });
      tabs.append(tab);
    });
  }

  function renderMeta() {
    const record = records[recordIndex];
    meta.replaceChildren();
    const fields = [
      ['会话', String(record.session || '—')],
      ['轮次', `第 ${record.round ?? '?'} 轮`],
      ['训练用例', Array.isArray(record.task_ids) ? (record.task_ids.join('、') || '—') : '—'],
      ['准确率', accuracyText(record.accuracy)],
      ['编辑数', String(record.edit_count ?? pick(record).length)],
      ['生成时间', String(record.generated_at || '—')],
    ];
    for (const [label, value] of fields) {
      const item = document.createElement('span');
      item.className = 'meta-item';
      const key = document.createElement('small');
      key.textContent = label;
      const val = document.createElement('b');
      val.textContent = value;
      item.append(key, val);
      meta.append(item);
    }
  }

  function renderEdits() {
    const record = records[recordIndex];
    const edits = pick(record);
    if (editIndex >= edits.length) editIndex = Math.max(0, edits.length - 1);
    list.replaceChildren();
    edits.forEach((edit, i) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'edit-item' + (i === editIndex ? ' active' : '');
      const head = document.createElement('span');
      head.className = 'edit-item-head';
      const index = document.createElement('em');
      index.textContent = `#${edit.index ?? i + 1}`;
      const op = document.createElement('i');
      op.className = `edit-op op-${STATUS_LABELS[edit.status] ? edit.status : 'other'}`;
      op.textContent = OP_LABELS[edit.op] || String(edit.op || '编辑');
      const status = document.createElement('small');
      status.className = `edit-status status-${STATUS_LABELS[edit.status] ? edit.status : 'other'}`;
      status.textContent = STATUS_LABELS[edit.status] || String(edit.status || '—');
      head.append(index, op, status);
      const summary = document.createElement('p');
      summary.textContent = String(edit.summary || '（无说明）');
      item.append(head, summary);
      item.addEventListener('click', () => { editIndex = i; renderEdits(); });
      list.append(item);
    });
    renderDetail(edits[editIndex], record);
  }

  function renderDetail(edit, record) {
    detail.replaceChildren();
    if (!edit) {
      const none = document.createElement('p');
      none.className = 'edit-detail-empty';
      none.textContent = '该轮没有编辑记录。';
      detail.append(none);
      return;
    }
    const title = document.createElement('h3');
    title.textContent = `编辑 #${edit.index ?? editIndex + 1} · ${OP_LABELS[edit.op] || edit.op || '编辑'}`;
    const info = document.createElement('div');
    info.className = 'edit-detail-info';
    const infoRows = [
      ['Skill', String(edit.skill_name || record.skill_name || '—')],
      ['状态', STATUS_LABELS[edit.status] || String(edit.status || '—')],
      ['位置', String(edit.target || '—')],
    ];
    for (const [label, value] of infoRows) {
      const row = document.createElement('p');
      const key = document.createElement('small');
      key.textContent = `${label}：`;
      const val = document.createElement('code');
      val.textContent = value;
      row.append(key, val);
      info.append(row);
    }
    if (Array.isArray(edit.references) && edit.references.length) {
      const row = document.createElement('p');
      const key = document.createElement('small');
      key.textContent = '关联文件：';
      row.append(key);
      edit.references.forEach(ref => {
        const chip = document.createElement('code');
        chip.className = 'ref-chip';
        chip.textContent = String(ref);
        row.append(chip);
      });
      info.append(row);
    }
    const contentTitle = document.createElement('h4');
    contentTitle.textContent = '编辑内容';
    const content = document.createElement('div');
    content.className = 'edit-detail-content';
    content.innerHTML = markdown(String(edit.content || '（无内容）'));
    detail.append(title, info, contentTitle, content);
  }

  function renderRecord() {
    renderTabs(); renderMeta(); renderEdits();
  }

  async function reload() {
    try {
      const result = await load();
      records = Array.isArray(result?.items) ? result.items.filter(r => r && typeof r === 'object') : [];
      $('edit-records-count').textContent = `${records.length} 轮`;
      const has = records.length > 0;
      empty.hidden = has; main.hidden = !has;
      if (has) { recordIndex = Math.min(recordIndex, records.length - 1); renderRecord(); }
    } catch (error) {
      toast(`编辑记录加载失败：${error.message}`);
      empty.hidden = false; main.hidden = true;
      $('edit-records-count').textContent = '—';
    }
  }

  $('edit-records-refresh').addEventListener('click', () => { reload(); toast('编辑记录已刷新'); });
  return { reload };
}
