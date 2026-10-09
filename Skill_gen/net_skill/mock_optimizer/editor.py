"""根据 Agent 执行轨迹编辑优化 Skill：把演练暴露的缺口补成可执行的处理指引。"""


def revise(skill: str, round_number: int, fault: dict, analysis: dict) -> str:
    """第 5 步：根据执行轨迹与缺口编辑优化 Skill，返回新的完整 Markdown。"""
    action = fault["fix"] or "按确认的根因完成处置，并验证告警清除"
    section = (
        f"## 第 {round_number} 轮优化 · {fault['name']}故障处理\n\n"
        f"> 演练发现缺口：{analysis['gap']}\n\n"
        f"1. 识别现象：{fault['symptom']}\n"
        f"2. 缩小范围：检查 {fault['scope']} 的状态与最近变更。\n"
        f"3. 根因确认：{fault['root_cause']}\n"
        f"4. 处置动作：{action}\n"
        f"5. 验证恢复：复核告警清除，并把本次处理记录到故障档案。\n"
    )
    return f"{skill.rstrip()}\n\n{section}"
