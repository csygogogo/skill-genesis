"""skill 优化的 mock 演练流程：故障注入 → 发送请求 → 故障分析 → 编辑并返回优化后的 Skill。

每轮从 faults.FAULTS 轮换一种故障：注入后把现象发给 Agent，Agent 加载当前 Skill
做定位分析并暴露缺口，再由 editor 把缺口补成处理指引，最后返回优化后的完整 Markdown。
接入真实环境时，替换本包内各模块的实现即可，pipeline.py 的进度契约保持不变。
"""
import asyncio

from . import agent, editor, faults

# 各阶段模拟耗时（秒）；测试时可整体传 0。
DELAYS = {"inject": 1.5, "send": 1.0, "analyze": 2.5, "revise": 1.5}


async def optimize(intent: str, skill: str, round_number: int, delays: dict = None):
    """逐阶段 yield 进度，最后 yield 优化后的完整 Markdown（与 pipeline 的接入契约一致）。"""
    pacing = {**DELAYS, **(delays or {})}
    fault = faults.pick(round_number)

    yield {"step": 1, "status": "running", "content": "正在实际网络环境中注入故障…"}
    await asyncio.sleep(pacing["inject"])
    yield {"step": 1, "status": "completed", "content": faults.inject(fault)}

    yield {"step": 2, "status": "running", "content": "正在把故障现象发送给 Agent…"}
    await asyncio.sleep(pacing["send"])
    yield {"step": 2, "status": "completed", "content": agent.send(faults.symptoms(fault))}

    yield {"step": 3, "status": "running", "content": "Agent 正在加载 Skill 做故障定位与分析…"}
    await asyncio.sleep(pacing["analyze"])
    analysis = agent.analyze(skill, fault)
    yield {"step": 3, "status": "completed", "content": analysis["trace"]}

    yield {"step": 4, "status": "running", "content": "正在根据执行轨迹编辑优化 Skill…"}
    await asyncio.sleep(pacing["revise"])
    optimized = editor.revise(skill, round_number, fault, analysis)
    yield {"step": 4, "status": "completed"}

    yield optimized
