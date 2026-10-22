"""mock Agent：演练环境里的执行与评测。

analyze 产出单用例的受阻轨迹（技能缺口场景）；evaluate 是状态机的评测器——
把 Skill 放到一组用例上逐个执行（覆盖 → 得出根因 correct；未覆盖 → 受阻 incorrect），
汇总出准确率与全部轨迹。覆盖判断只看正文（剥掉 frontmatter，避免 description 里的
故障字样误判），规则见 covered。
"""
import json
import re

from ..skill_editor import trajectory as trajectory_module
from ..skill_editor.trajectory import text_contains

# 模拟运维 Agent 可调用的工具池：每个 Skill 步骤轮换调用一个工具。
TOOLS = ("query_alarms", "topology_view", "change_records", "interface_stats", "log_search", "config_check", "probe_ping")


def send(payload: dict) -> str:
    """把故障现象发送给 Agent（mock 一次诊断请求），返回回执。"""
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


def body_of(skill: str) -> str:
    """剥掉顶部 frontmatter，返回正文；覆盖判断只看正文。"""
    lines = skill.splitlines()
    if not lines or lines[0].strip() != "---":
        return skill
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1:])
    return skill


def covered(skill: str, fault: dict) -> bool:
    """Skill 是否覆盖该故障：正文含期望根因（最强信号）；或故障名与注入设备/范围同时出现。

    故障名单独出现不算覆盖——训练集里不同设备的同类故障同名（如都是「接口down」），
    只按名字会把「覆盖了 serverleaf2」误判成「也会处理 serverleaf3」。
    """
    body = body_of(skill)
    if fault.get("root_cause") and text_contains(body, fault["root_cause"]):
        return True
    name, scope = fault.get("name", ""), fault.get("scope", "")
    return bool(name) and text_contains(body, name) and (not scope or text_contains(body, scope))


def _base_actions(skill: str) -> list:
    """编号步骤逐一执行成功的工具调用列表（analyze 与 run_case 共用）。"""
    return [
        {"step": index, "desc": step, "tool": TOOLS[(index - 1) % len(TOOLS)], "ok": True, "detail": "执行成功"}
        for index, step in enumerate(steps_of(skill), start=1)
    ]


def _trajectory(skill: str, fault: dict, resolved: bool) -> dict:
    """构造单用例轨迹：resolved=True 时根因定位成功，否则受阻于技能缺口。"""
    actions = _base_actions(skill)
    if resolved:
        actions.append({"step": 0, "desc": "依据 Skill 步骤定位根因", "tool": "root_cause_check",
                        "ok": True, "detail": fault["root_cause"]})
        final_answer = fault["root_cause"]
    else:
        # step=0 表示 Skill 步骤之外的收尾动作：按步骤收敛根因时被演练设定的缺口挡住。
        actions.append({"step": 0, "desc": "依据 Skill 步骤定位根因", "tool": "root_cause_check",
                        "ok": False, "detail": fault["gap"]})
        final_answer = ""
    return trajectory_module.normalize({
        "case": fault.get("case", ""),
        "fault": fault,
        "skill": {"name": skill_name(skill), "steps": steps_of(skill)},
        "actions": actions,
        "final_answer": final_answer,
        "expected": fault["root_cause"],
        "gap": fault["gap"],
    })


def analyze(skill: str, fault: dict) -> dict:
    """单用例分析：Skill 未覆盖该故障时 Agent 的受阻轨迹（技能缺口场景）。

    演练语义：Skill 的编号步骤全部执行成功（各调用一次工具），但收尾的根因定位
    受阻于技能缺口、未得出根因 —— 轨迹判定 incorrect，成为本轮编辑优化的依据。
    """
    trajectory = _trajectory(skill, fault, resolved=False)
    return {
        "trajectory": trajectory,
        "trace": trajectory_module.render_trace(trajectory),
        "gap": fault["gap"],
        "symptom": fault["symptom"],
    }


def run_case(skill: str, fault: dict) -> dict:
    """在单个用例上执行 Skill：覆盖 → 得出根因（correct）；未覆盖 → 受阻轨迹（incorrect）。"""
    return _trajectory(skill, fault, resolved=covered(skill, fault))


def evaluate(skill: str, fault_list: list) -> dict:
    """状态机的评测器：把 Skill 放到一组用例上逐个执行，返回准确率与全部轨迹。

    返回 {"accuracy": 判对数/总数, "total": 用例数, "covered": 判对数,
    "trajectories": 与 fault_list 同序, "trace": 界面展示的多行文本}。
    """
    trajectories = [run_case(skill, fault) for fault in fault_list]
    passed = sum(1 for item in trajectories if item["verdict"] == "correct")
    total = len(fault_list)
    lines = [f"已把 {total} 个勾选用例的故障现象逐个发送给 Agent（POST /agent/diagnose），"
             f"加载 Skill「{skill_name(skill)}」逐用例执行："]
    for item in trajectories:
        fault = item["fault"]
        head = f"{item['case'] or '未记名'}（{fault.get('name', '未知故障')} · {fault.get('scope', '')}）"
        if item["verdict"] == "correct":
            lines.append(f"{head}：已覆盖，得出根因 —— correct")
        else:
            lines.append(f"{head}：未覆盖 —— 受阻：{item['gap']}")
    lines.append(f"准确率 {passed}/{total} = {passed / total:.2f}（覆盖 {passed} · 未覆盖 {total - passed}）")
    return {"accuracy": passed / total if total else 0.0, "total": total, "covered": passed,
            "trajectories": trajectories, "trace": "\n".join(lines)}
