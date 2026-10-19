"""mock Agent：接收故障现象，加载当前 Skill 按步骤执行，产出结构化运维轨迹与界面轨迹文本。"""
import json
import re

from ..skill_editor import trajectory as trajectory_module

# 模拟运维 Agent 可调用的工具池：每个 Skill 步骤轮换调用一个工具。
TOOLS = ("query_alarms", "topology_view", "change_records", "interface_stats", "log_search", "config_check", "probe_ping")


def send(payload: dict) -> str:
    """第 2 步：把故障现象发送给 Agent（mock 一次诊断请求），返回回执。"""
    body = json.dumps(payload, ensure_ascii=False)
    return (f"已发送故障现象给 Agent（POST /agent/diagnose，{len(body.encode('utf-8'))} 字节）："
            f"告警={payload['alarm']}；材料={'、'.join(payload['materials'])}。")


def steps_of(skill: str) -> list:
    """从 Skill Markdown 中提取编号步骤（形如“1. xxx”的行）。"""
    return [match.group(1).strip() for match in re.finditer(r"^\s*\d+\.\s+(.+)$", skill, re.MULTILINE)]


def skill_name(skill: str) -> str:
    """从 Skill 顶部的 frontmatter 读 name；本地简化解析（不引 pipeline，避免循环导入）。"""
    lines = skill.splitlines()
    if not lines or lines[0].strip() != "---":
        return "未命名"
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, separator, value = line.partition(":")
        if separator and key.strip() == "name" and value.strip():
            return value.strip()
    return "未命名"


def analyze(skill: str, fault: dict) -> dict:
    """第 3 步：Agent 加载 Skill 执行故障定位与分析，返回结构化轨迹与界面轨迹文本。

    演练语义：Skill 的编号步骤全部执行成功（各调用一次工具），但收尾的根因定位
    受阻于技能缺口、未得出根因 —— 轨迹判定 incorrect，成为本轮编辑优化的依据。
    """
    steps = steps_of(skill)
    actions = [
        {"step": index, "desc": step, "tool": TOOLS[(index - 1) % len(TOOLS)], "ok": True, "detail": "执行成功"}
        for index, step in enumerate(steps, start=1)
    ]
    # step=0 表示 Skill 步骤之外的收尾动作：按步骤收敛根因时被演练设定的缺口挡住。
    actions.append({"step": 0, "desc": "依据 Skill 步骤定位根因", "tool": "root_cause_check",
                    "ok": False, "detail": fault["gap"]})
    trajectory = trajectory_module.normalize({
        "case": fault.get("case", ""),
        "fault": fault,
        "skill": {"name": skill_name(skill), "steps": steps},
        "actions": actions,
        "final_answer": "",  # 受阻，未得出根因
        "expected": fault["root_cause"],
        "gap": fault["gap"],
    })
    return {
        "trajectory": trajectory,
        "trace": trajectory_module.render_trace(trajectory),
        "gap": fault["gap"],
        "symptom": fault["symptom"],
    }
