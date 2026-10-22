"""具体的 skill 编辑：把评测结果（eval_parse 解析后的 agents 结果）映射为运维轨迹，
调用 skill_editor（优先火山方舟大模型，失败回退规则编辑）产出候选 Skill；
并用 prompts/skill_optimize_analysis.txt 的分析 prompt 支撑「是否值得编辑」的判断。
"""
import asyncio
from pathlib import Path

from .mock_optimizer import faults
from .skill_editor import revise
from .skill_editor import trajectory as trajectory_module

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def fault_of(case: str) -> dict:
    """按用例 id 在训练集故障库里找故障快照（现象 / 设备 / 根因），找不到返回空。"""
    return next((fault for fault in faults.FAULTS if fault.get("case") == case), {})


def expected_of(item: dict) -> str:
    """该 case 的期望根因：优先评测结果自带的 expected，缺失时回退训练集 gold_answer。"""
    if item.get("expected"):
        return item["expected"]
    fault = fault_of(item.get("case", ""))
    if fault:
        return fault.get("root_cause", "")
    return ""


def build_trajectory(item: dict) -> dict:
    """把一条评测结果映射为 skill_editor 认识的运维轨迹（工具调用取自轨迹文本切行）。"""
    expected = expected_of(item)
    answer = item.get("answer", "")
    steps = [line.strip() for line in (item.get("trace") or "").splitlines() if line.strip()]
    actions = [
        {"step": index, "desc": step[:80], "tool": "agent_action", "ok": True, "detail": "执行成功"}
        for index, step in enumerate(steps, start=1)
    ]
    correct = item.get("accuracy", 0) >= 1
    actions.append({"step": 0, "desc": "给出最终根因", "tool": "final_answer",
                    "ok": correct, "detail": answer if correct else f"与期望不符：{answer or '未作答'}"})
    return trajectory_module.normalize({
        "case": item.get("case", ""),
        "fault": fault_of(item.get("case", "")),  # 训练集故障快照：让编辑产出现象/设备/根因俱全的章节
        "skill": {"name": "评测执行", "steps": steps[:5]},
        "actions": actions,
        "final_answer": answer,
        "expected": expected,
        "gap": "" if correct else (f"Skill 未覆盖该 case（期望根因：{expected}）" if expected else "Skill 未覆盖该 case"),
    })


def pick_target(items: list) -> dict:
    """选本轮编辑目标：准确率最低的 case（并列取第一个；全对时取第一条）。"""
    if not items:
        raise ValueError("本轮没有评测结果，无法选择编辑目标")
    return min(items, key=lambda item: item.get("accuracy", 0))


def analysis_prompt(items: list) -> str:
    """渲染优化分析 prompt：把本轮 case 结果填进 prompts/skill_optimize_analysis.txt。"""
    template = (PROMPTS_DIR / "skill_optimize_analysis.txt").read_text(encoding="utf-8")
    blocks = []
    for item in items:
        blocks.append(
            f"[{item['case'] or '未记名'}]\n"
            f"问题：{item['question'] or '（未提供）'}\n"
            f"Agent 答案：{item['answer'] or '（未作答）'}\n"
            f"期望根因：{item['expected'] or expected_of(item) or '（未提供）'}\n"
            f"准确率：{item['accuracy']:.0%}\n"
            f"执行轨迹：\n{item['trace'] or '（无轨迹）'}")
    return template.replace("{cases}", "\n\n".join(blocks))


def edit_skill(skill: str, round_number: int, items: list, retry_note: str = "") -> dict:
    """根据评测结果编辑 Skill：选最差的 case 构造轨迹，交 skill_editor 产出候选。

    返回 skill_editor.revise 的结果：{"content": 新 Markdown, "engine": "llm"|"fallback", "note": 说明}。
    """
    target = pick_target(items)
    trajectory = build_trajectory(target)
    return asyncio.run(revise(skill, round_number, trajectory, retry_note=retry_note))
