"""替换此文件中的模拟生成与执行逻辑；只需 yield 事件字典。"""
import asyncio


async def execution_trace(skill_id: str, round_number: int):
    # 替换为真实 Skill 执行器的日志；同一个 id 持续追加轨迹。
    trace = {"type": "execution_trace", "id": f"trace-{skill_id}", "skill_id": skill_id, "round": round_number}
    yield {**trace, "status": "running", "content": "[示例] 开始执行 Skill\n"}
    for step in ("01 · 检查输入与约束。\n", "02 · 执行任务，生成结果。\n", "03 · 校验输出完整性。\n"):
        await asyncio.sleep(0.1)
        yield {**trace, "delta": step}
    yield {**trace, "status": "completed", "delta": "[示例] 执行完成。"}


async def generate_events(intent: str):
    # 在此替换为真实子图检索 / 模型 / 优化循环。
    yield {"type": "subgraph", "id": "graph-1", "content": "根据意图构建知识子图", "nodes": [
        {"id": "intent", "label": "用户意图"}, {"id": "output", "label": "输出约束"}
    ], "edges": [{"source": "intent", "target": "output"}]}
    skill = f"# 自生成 Skill\n\n## 目标\n{intent}\n\n## 步骤\n1. 分析输入。\n2. 执行任务。\n3. 输出结果。"
    yield {"type": "skill", "id": "skill-0", "round": 0, "content": skill}
    async for event in execution_trace("skill-0", 0):
        yield event
    for round_number in range(1, 3):
        await asyncio.sleep(0.6)
        skill += f"\n\n## 第 {round_number} 轮校验\n检查输入约束与结果完整性。"
        # 每轮使用不同 id；同一轮的 delta 使用同一个 id。
        for index in range(0, len(skill), 24):
            yield {"type": "optimized_skill", "id": f"skill-{round_number}", "round": round_number, "delta": skill[index:index + 24]}
            await asyncio.sleep(0.03)
        async for event in execution_trace(f"skill-{round_number}", round_number):
            yield event
        if round_number < 2:
            yield {"type": "strategy", "id": f"strategy-{round_number}", "round": round_number, "content": "下一轮补充结果校验，明确失败场景和交付要求。"}
    yield {"type": "final_skill", "id": "skill-final", "round": 2, "content": skill}
    async for event in execution_trace("skill-final", 2):
        yield event
    yield {"type": "done"}
