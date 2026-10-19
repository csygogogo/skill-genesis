"""skill 优化的 mock 演练流程：故障注入 → 发送请求 → 故障分析 → 故障恢复 → 编辑并返回优化后的 Skill。

每轮从故障库轮换一种故障（faults.py 优先加载 net_skill/data/train_data.json 训练集，
缺失时回退内置场景）：注入后把现象发给 Agent，Agent 加载当前 Skill 产出结构化运维轨迹
（用了哪个 Skill、调了哪些工具、结果对错，见 skill_editor/trajectory.py）；恢复故障让
环境回到基线，再由 skill_editor 编辑 agent（优先火山方舟大模型，失败回退规则编辑）根据
轨迹编辑 Skill，最后返回优化后的完整 Markdown。接入真实环境时，替换本包内各模块的
实现即可，契约保持不变。
"""
import asyncio

from . import agent, faults
from .. import skill_editor

# 各阶段模拟耗时（秒）；测试时可整体传 0。编辑 agent 的大模型调用另有真实耗时。
DELAYS = {"inject": 1.5, "send": 1.0, "analyze": 2.5, "recover": 1.0, "revise": 1.5}


async def optimize(intent: str, skill: str, round_number: int, delays: dict = None, case_ids=None, editor_client=None):
    """逐阶段 yield 进度，最后 yield 优化后的完整 Markdown（与 pipeline 的接入契约一致）。

    case_ids 是界面选择的训练用例 id；为空时在本轮全部用例中轮换。
    editor_client 可注入测试用的大模型假客户端；缺省走环境变量探测。
    """
    pacing = {**DELAYS, **(delays or {})}
    fault = faults.pick(round_number, case_ids)

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

    yield {"step": 4, "status": "running", "content": "正在实际网络环境中恢复故障…"}
    await asyncio.sleep(pacing["recover"])
    yield {"step": 4, "status": "completed", "content": faults.recover(fault)}

    yield {"step": 5, "status": "running", "content": "编辑 agent 正在根据执行轨迹优化 Skill…"}
    await asyncio.sleep(pacing["revise"])
    result = await skill_editor.revise(skill, round_number, analysis["trajectory"], client=editor_client)
    yield {"step": 5, "status": "completed", "content": result["note"]}

    yield result["content"]
