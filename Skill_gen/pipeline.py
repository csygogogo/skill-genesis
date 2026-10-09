"""接入你的 Skill 生成与优化函数；界面分两步调用：生成 → 逐轮优化。"""
import asyncio
import inspect


# ====== 接入区：把你的两个函数放在这里 ======

async def generate_skill(intent: str) -> str:
    """点击「生成 Skill」时调用：根据意图生成初始 Skill，返回完整 Markdown 字符串。"""
    await asyncio.sleep(1.5)  # 示例延迟，接入时可删除
    return f"# 自生成 Skill\n\n## 目标\n{intent}\n\n## 步骤\n1. 分析输入。\n2. 执行任务。\n3. 输出结果。"


# 优化流程的五个阶段，按顺序实时展示在前端；optimize_skill 按序号汇报进度。
OPTIMIZE_STEPS = (
    "注入故障",           # 1. 在实际网络环境中注入故障
    "发送故障现象",       # 2. 把故障现象发送给 Agent
    "定位与分析",         # 3. Agent 加载 Skill 做故障定位与分析
    "编辑优化 Skill",     # 4. 根据 Agent 执行轨迹编辑优化 Skill
    "返回优化后的 Skill", # 5. 包装代码拿到优化结果时自动标记完成
)


async def optimize_skill(intent: str, skill: str, round_number: int):
    """点击「优化 Skill」时调用：逐阶段 yield 进度，最后 yield 优化后的完整 Markdown。

    进度格式：{"step": 1, "status": "running" 或 "completed", "content": "可选说明文本"}
    step 对应 OPTIMIZE_STEPS 的序号；每个阶段开始时 yield running，结束时再 yield completed。
    全部阶段结束后，再 yield 优化后的完整 Markdown 字符串（字符串，不是字典）。
    也兼容旧式接入：不 yield 进度，直接返回完整 Markdown 字符串的普通函数 / 协程。
    """
    yield {"step": 1, "status": "running", "content": "正在实际网络环境中注入故障…"}
    await asyncio.sleep(2.0)  # 示例延迟：接入真实的故障注入
    fault = "已注入故障：核心交换机到接入交换机的链路丢包 30%。"
    yield {"step": 1, "status": "completed", "content": fault}

    yield {"step": 2, "status": "running", "content": "正在把故障现象发送给 Agent…"}
    await asyncio.sleep(1.5)  # 示例延迟：接入真实的告警发送
    yield {"step": 2, "status": "completed", "content": "已发送告警现象与网络拓扑信息。"}

    yield {"step": 3, "status": "running", "content": "Agent 正在加载 Skill 做故障定位与分析…"}
    await asyncio.sleep(3.0)  # 示例延迟：接入真实的 Agent 执行
    trace = "执行轨迹：读取告警 → 检查链路状态 → 定位丢包端口 ge-0/0/1。"
    yield {"step": 3, "status": "completed", "content": trace}

    yield {"step": 4, "status": "running", "content": "正在根据执行轨迹编辑优化 Skill…"}
    await asyncio.sleep(1.5)  # 示例延迟：接入真实的 Skill 编辑
    yield {"step": 4, "status": "completed"}

    yield skill + f"\n\n## 第 {round_number} 轮优化\n- 验证故障：{fault}\n- {trace}\n- 根据执行轨迹补充失败场景与交付要求。"


# ====== 以下是接入界面的包装代码，一般无需修改 ======


async def call(function, *args):
    # 同步函数、async 函数和返回协程的调用方式都支持。
    result = function(*args)
    while inspect.isawaitable(result):
        result = await result
    return result


async def generate_events(intent: str):
    skill = await call(generate_skill, intent)
    yield {"type": "skill", "id": "skill-0", "round": 0, "content": skill}


def apply_progress(states, progress):
    # progress：{"step": 序号, "status": running/completed, "content": 可选说明}。
    if not isinstance(progress, dict) or not isinstance(progress.get("step"), int):
        raise RuntimeError("optimize_skill yield 的进度必须是包含 step 序号的字典")
    for state in states:
        if state["step"] == progress["step"]:
            state["status"] = progress["status"] if progress.get("status") in ("running", "completed") else "running"
            if progress.get("content"):
                state["content"] = str(progress["content"])


async def optimize_events(intent: str, skill: str, round_number: int):
    generator = optimize_skill(intent, skill, round_number)
    if not (inspect.isasyncgen(generator) or inspect.isgenerator(generator)):
        # 旧式接入：optimize_skill 是普通函数 / 协程，等返回后直接发最终版本。
        optimized = generator
        while inspect.isawaitable(optimized):
            optimized = await optimized
        yield {"type": "optimized_skill", "id": f"skill-{round_number}", "round": round_number, "content": optimized}
        return

    # 五个阶段的实时状态：pending / running / completed / failed，前端渲染成进度清单。
    states = [{"step": index, "title": title, "status": "pending", "content": ""}
              for index, title in enumerate(OPTIMIZE_STEPS, start=1)]

    def snapshot():
        return {"type": "optimize_step", "id": f"optimize-{round_number}", "round": round_number, "steps": states}

    yield snapshot()
    optimized = None
    try:
        while True:
            try:
                progress = await generator.__anext__() if inspect.isasyncgen(generator) else next(generator)
            except (StopAsyncIteration, StopIteration):
                break
            if isinstance(progress, str):
                optimized = progress  # 收尾：yield 字符串即优化后的完整 Markdown。
                break
            apply_progress(states, progress)
            yield snapshot()
    except Exception:
        # 中途失败：把执行中的阶段标记为 failed，再交给上层记录 error 事件。
        for state in states:
            if state["status"] == "running":
                state["status"] = "failed"
        yield snapshot()
        raise
    if not isinstance(optimized, str) or not optimized.strip():
        raise RuntimeError("optimize_skill 必须以 yield 优化后的完整 Markdown 字符串结束")
    for state in states[:-1]:
        state["status"] = "completed"
    states[-1].update(status="completed", content="优化完成，已生成新版本。")
    yield snapshot()
    yield {"type": "optimized_skill", "id": f"skill-{round_number}", "round": round_number, "content": optimized}
