const delay = (ms, signal) => new Promise((resolve, reject) => {
  if (signal.aborted) return reject(new DOMException('Stopped', 'AbortError'));
  const stop = () => { clearTimeout(timer); reject(new DOMException('Stopped', 'AbortError')); };
  const timer = setTimeout(() => { signal.removeEventListener('abort', stop); resolve(); }, ms);
  signal.addEventListener('abort', stop, { once: true });
});
async function* executeDemo(skillId, round, signal) {
  const trace = { type: 'execution_trace', id: `trace-${skillId}`, skill_id: skillId, round };
  yield { ...trace, status: 'running', content: '[演示] 开始执行当前 Skill\n' };
  await delay(350, signal);
  yield { ...trace, delta: '01 · 读取示例输入并检查任务约束。\n02 · 执行任务步骤，生成结构化结果。\n' };
  await delay(350, signal);
  yield { ...trace, status: 'completed', delta: '03 · 校验输出完整性。\n[演示] 执行结束，结果用于下一轮评估。' };
}
export async function* generateDemo(intent, signal) {
  const base = `---\nname: intent-driven-skill\ndescription: 基于用户意图执行结构化任务\n---\n\n# 意图驱动 Skill\n\n## 目标\n${intent}\n\n## 输入\n- 用户提供的原始材料\n- 期望的输出格式与约束\n\n## 执行步骤\n1. 识别任务目标与关键约束。\n2. 提取输入中的相关信息。\n3. 按任务目标整理并生成结果。\n\n## 输出\n输出结构清晰、可执行的结果，并说明依据。`;
  await delay(600, signal);
  yield { type: 'subgraph', id: 'graph-1', title: '已构建任务知识子图', content: '围绕当前意图，连接输入规范、执行方法和输出约束。', nodes: [{ id: 'intent', label: '任务意图' }, { id: 'input', label: '输入规范' }, { id: 'method', label: '执行方法' }, { id: 'output', label: '输出约束' }, { id: 'check', label: '质量校验' }], edges: [{ source: 'intent', target: 'input' }, { source: 'intent', target: 'method' }, { source: 'intent', target: 'output' }, { source: 'output', target: 'check' }] };
  await delay(1000, signal);
  yield { type: 'skill', id: 'skill-0', round: 0, content: base };
  yield* executeDemo('skill-0', 0, signal);
  await delay(1100, signal);
  const v1 = base.replace('3. 按任务目标整理并生成结果。', '3. 按任务目标整理并生成结果。\n4. 检查结果是否覆盖全部用户约束。') + '\n\n## 质量标准\n- 每个结论对应明确依据。\n- 缺失信息标记为待补充，不自行编造。';
  yield { type: 'optimized_skill', id: 'skill-1', round: 1, content: v1 };
  yield* executeDemo('skill-1', 1, signal);
  await delay(1100, signal);
  yield { type: 'strategy', id: 'strategy-1', round: 1, content: '第一轮已补充质量标准。下一轮将明确异常输入的处理方式，并加入可验证的交付检查：\n\n① 输入不足时指出缺失项。\n② 将事实与推断分开表达。\n③ 输出前逐项检查目标、依据与可执行性。' };
  await delay(1100, signal);
  const v2 = v1 + '\n\n## 异常处理\n- 输入为空：请求用户提供必要材料。\n- 信息冲突：列出冲突并说明无法确认的部分。\n- 信息不足：提出具体补充问题，保留不确定性。\n\n## 交付检查\n1. 是否完整回应用户意图？\n2. 是否区分事实与推断？\n3. 是否提供明确的下一步行动？';
  yield { type: 'optimized_skill', id: 'skill-2', round: 2, content: v2 };
  yield* executeDemo('skill-2', 2, signal);
  await delay(900, signal);
  yield { type: 'final_skill', id: 'skill-final', round: 2, content: v2 };
  yield* executeDemo('skill-final', 2, signal);
  yield { type: 'done' };
}
