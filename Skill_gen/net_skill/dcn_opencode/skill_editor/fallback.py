"""规则回退编辑：大模型不可用（未配置 / 未安装 / 调用失败）时的确定性编辑。

逻辑与原 mock_optimizer/editor.revise 等价：在 Skill 末尾追加一轮「故障处理」
章节，取值来源从 fault dict 换成运维轨迹（fault 快照 + gap）。
"""


def revise(skill: str, round_number: int, trajectory: dict) -> str:
    """根据轨迹追加处理指引章节，返回新的完整 Markdown；追加式，不改动原有内容。"""
    fault = trajectory.get("fault") or {}
    action = fault.get("fix") or "按确认的根因完成处置，并验证告警清除"
    section = (
        f"## 第 {round_number} 轮优化 · {fault.get('name', '未知故障')}故障处理\n\n"
        f"> 演练发现缺口：{trajectory.get('gap') or 'Skill 未覆盖该故障的定位路径'}\n\n"
        f"1. 识别现象：{fault.get('symptom') or trajectory.get('expected') or '本轮演练的故障现象'}\n"
        f"2. 缩小范围：检查 {fault.get('scope', '组网环境')} 的状态与最近变更。\n"
        f"3. 根因确认：{fault.get('root_cause') or trajectory.get('expected') or '按告警与日志逐步收敛'}\n"
        f"4. 处置动作：{action}\n"
        f"5. 验证恢复：复核告警清除，并把本次处理记录到故障档案。\n"
    )
    return f"{skill.rstrip()}\n\n{section}"
