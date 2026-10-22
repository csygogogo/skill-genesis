"""skill 编辑 agent：输入运维轨迹（用了哪些 Skill、调了哪些工具、结果对错），编辑优化 Skill 文档。

入口 revise(skill, round_number, trajectory, client=None)：
- 优先走火山方舟大模型（llm.py，环境变量见该模块 docstring），分析轨迹后输出优化文档；
- 未配置凭证 / 未安装 openai / 调用或校验失败时，自动回退 fallback.py 的规则编辑；
- 返回 {"content": 新 Markdown, "engine": "llm"|"fallback", "note": 给界面看的引擎说明}。
client 可注入测试用的假客户端（只需实现 chat.completions.create）。
"""
import asyncio

from . import fallback, llm, trajectory as trajectory_module


async def revise(skill: str, round_number: int, trajectory: dict, client=None, retry_note: str = "") -> dict:
    """根据一条运维轨迹编辑 Skill；LLM 路径失败或不可用时回退规则编辑。

    retry_note 是上一版候选被回滚后的重试提示，仅 LLM 路径使用（规则回退忽略）。
    """
    trajectory = trajectory_module.normalize(trajectory)
    fault_name = (trajectory.get("fault") or {}).get("name", "未知故障")

    if client is not None or llm.available():
        try:
            use_client = client or llm.build_client()
            messages = llm.build_messages(skill, round_number, trajectory, retry_note=retry_note)
            raw = await asyncio.to_thread(llm.complete, use_client, messages)
            content = llm.clean_output(raw, skill, fault_name)
            model = llm.settings()["model"] or "注入客户端"
            return {"content": content, "engine": "llm",
                    "note": f"已由火山方舟大模型（{model}）根据执行轨迹完成编辑。"}
        except Exception as error:  # 超时、网络、SDK 错误、输出校验不过：统一回退。
            reason = str(error).strip() or error.__class__.__name__
            return {"content": fallback.revise(skill, round_number, trajectory), "engine": "fallback",
                    "note": f"大模型编辑未成功（{reason[:80]}），已回退规则编辑。"}

    return {"content": fallback.revise(skill, round_number, trajectory), "engine": "fallback",
            "note": (f"未接入大模型（未安装 openai 或未配置 ARK_API_KEY / SKILL_LLM_MODEL），"
                     f"已回退规则编辑：追加「{fault_name}故障处理」章节。")}
