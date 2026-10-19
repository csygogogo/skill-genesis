"""运维轨迹的数据契约：规范化、对错判定、渲染成界面文本与 LLM 输入文本。

轨迹记录一次运维演练的全过程：用了哪个 Skill、按步骤调了哪些工具（及成败）、
最终结论与期望根因比对后的对错判定。normalize 后字段固定为：
case（用例 id）、fault（本轮故障快照）、skill（name + steps）、
actions（step/desc/tool/ok/detail 的工具调用列表，step=0 表示 Skill 步骤之外的收尾动作）、
final_answer、expected、verdict（correct/incorrect）、gap（暴露的技能缺口）。
"""
import re

# 判定对错前先把两边文本规范化：去所有空白、转小写、去中英文标点。
_PUNCTS = re.compile(r"[\s，。、；：？！“”‘’（）《》【】,\.;:?!\"'()\[\]<>{}_~`@#$%^&*-+=/\\|]")


def _squash(text: str) -> str:
    return _PUNCTS.sub("", str(text)).lower()


def judge(answer: str, expected: str) -> str:
    """把 Agent 最终结论与期望根因（gold_answer）比对，返回 correct / incorrect。

    双向包含匹配：两边规范化后，任一方包含另一方即视为结论正确；
    结论为空或与期望互不包含视为错误。
    """
    answer, expected = _squash(answer), _squash(expected)
    if not answer or not expected:
        return "incorrect"
    return "correct" if answer in expected or expected in answer else "incorrect"


def _normalize_action(raw) -> dict:
    item = raw if isinstance(raw, dict) else {}
    return {
        "step": int(item.get("step") or 0),
        "desc": str(item.get("desc", "")),
        "tool": str(item.get("tool", "")),
        "ok": bool(item.get("ok")),
        "detail": str(item.get("detail", "")),
    }


def normalize(raw: dict) -> dict:
    """把外部传入的轨迹 dict 规范化为固定键序、固定字段类型的结构。

    缺失键补默认值（skill 未命名 / actions 为空等），verdict 缺失时按
    final_answer 与 expected 现算。真实环境接入时只要喂同样结构的 raw dict。
    """
    item = raw if isinstance(raw, dict) else {}
    skill = item.get("skill") if isinstance(item.get("skill"), dict) else {}
    steps = [str(step) for step in skill.get("steps") or []]
    actions = [_normalize_action(action) for action in item.get("actions") or []]
    expected = str(item.get("expected", ""))
    verdict = str(item.get("verdict", ""))
    if verdict not in ("correct", "incorrect"):
        verdict = judge(str(item.get("final_answer", "")), expected)
    return {
        "case": str(item.get("case", "")),
        "fault": item.get("fault") if isinstance(item.get("fault"), dict) else {},
        "skill": {"name": str(skill.get("name") or "未命名"), "steps": steps},
        "actions": actions,
        "final_answer": str(item.get("final_answer", "")),
        "expected": expected,
        "verdict": verdict,
        "gap": str(item.get("gap", "")),
    }


def render_trace(trajectory: dict) -> str:
    """渲染成界面第 3 步展示的执行轨迹文本（[Agent] 行式，pre-wrap 多行显示）。"""
    skill = trajectory["skill"]
    lines = [f"[Agent] 加载 Skill {skill['name']}（{len(skill['steps'])} 个步骤），开始故障定位"]
    for action in trajectory["actions"]:
        if action["ok"]:
            lines.append(f"[Agent] {action['step']:02d} · {action['desc']} —— 通过 · 工具 {action['tool']}")
        elif action["step"]:
            lines.append(f"[Agent] {action['step']:02d} · {action['desc']} —— 失败 · 工具 {action['tool']}：{action['detail']}")
        else:
            lines.append(f"[Agent] ⚠ 受阻：{action['detail']}，定位中断，转人工补全")
    lines.append(f"[Agent] 期望根因：{trajectory['expected']}")
    answer = trajectory["final_answer"] or "未得出根因"
    if trajectory["verdict"] == "correct":
        lines.append(f"[Agent] 本轮结论：{answer} —— 判定 correct（与期望根因一致）")
    else:
        lines.append(f"[Agent] 本轮结论：{answer} —— 判定 incorrect（与期望根因不符）")
    return "\n".join(lines)


def render_for_llm(trajectory: dict) -> str:
    """渲染成塞进编辑 prompt 的紧凑 Markdown 轨迹段；同输入同输出，便于测试。"""
    skill = trajectory["skill"]
    fault = trajectory.get("fault") or {}
    lines = [f"- 训练用例：{trajectory['case'] or '未记录'}（{fault.get('name', '未知故障')}）"]
    if fault.get("symptom"):
        lines.append(f"- 故障现象：{fault['symptom']}")
    lines.append(f"- 使用的 Skill：{skill['name']}，共 {len(skill['steps'])} 个编号步骤")
    lines.append("- 工具调用与结果：")
    for index, action in enumerate(trajectory["actions"], start=1):
        if action["ok"]:
            lines.append(f"  {index}. {action['tool']}（{action['desc']}）成功")
        else:
            lines.append(f"  - {action['tool']}（{action['desc']}）失败：{action['detail']}")
    answer = trajectory["final_answer"] or "未得出根因"
    lines.append(f"- Agent 最终结论：{answer}")
    lines.append(f"- 期望根因（gold_answer）：{trajectory['expected'] or '未记录'}")
    lines.append(f"- 结果判定：{trajectory['verdict']}")
    if trajectory["gap"]:
        lines.append(f"- 暴露的技能缺口：{trajectory['gap']}")
    return "\n".join(lines)
