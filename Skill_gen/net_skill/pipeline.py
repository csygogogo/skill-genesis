"""接入你的 Skill 生成与优化函数；界面分两步调用：生成 → 逐轮优化。"""
import asyncio
import inspect
import time
from pathlib import Path

from .mock_optimizer import optimize as run_mock_optimize

# skills/ 下放待优化的 Skill；data/ 下放训练集，见 mock_optimizer/faults.py。
SKILLS_DIR = Path(__file__).resolve().parent / "skills"


def parse_frontmatter(text: str) -> dict:
    """读取 SKILL.md 顶部 frontmatter 的 name / description（简单 key: value 子集）。"""
    meta, lines = {}, text.splitlines()
    if not lines or lines[0].strip() != "---":
        return meta
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, separator, value = line.partition(":")
        if separator:
            meta[key.strip()] = value.strip()
    return meta


def catalog() -> dict:
    """列出 skills/ 下可用的待优化 Skill，供界面选择。"""
    items = []
    for path in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        if not path.is_file():
            continue
        meta = parse_frontmatter(path.read_text(encoding="utf-8"))
        items.append({
            "id": path.parent.name,
            "name": meta.get("name") or path.parent.name,
            "description": meta.get("description", ""),
        })
    return {"items": items}


def resolve_skill(skill_id: str = "") -> str:
    """把界面选择的 Skill 目录名解析为实际使用的目录名；无效回退第一个，无 Skill 返回空串。"""
    paths = sorted(path for path in SKILLS_DIR.glob("*/SKILL.md") if path.is_file())
    for path in paths:
        if path.parent.name == skill_id:
            return skill_id
    return paths[0].parent.name if paths else ""


# ====== 接入区：把你的两个函数放在这里 ======

async def generate_skill(intent: str, skill_id: str = "") -> str:
    """点击「生成 Skill」时调用：读取 skills/ 下指定的待优化 Skill 作为初始版本 V0。

    skill_id 是界面选择的 Skill 目录名；为空或不存在时取第一个，skills/ 为空时
    回退为按意图生成的占位版本。
    """
    # 模拟准备 V0 的耗时，保证生成阶段有可见的运行窗口；接入真实实现时随逻辑自然产生。
    await asyncio.sleep(1.5)
    chosen = resolve_skill(skill_id)
    if chosen:
        return (SKILLS_DIR / chosen / "SKILL.md").read_text(encoding="utf-8")
    return f"# 自生成 Skill\n\n## 目标\n{intent}\n\n## 步骤\n1. 分析输入。\n2. 执行任务。\n3. 输出结果。"


# 优化流程的六个阶段，按顺序实时展示在前端；optimize_skill 按序号汇报进度。
OPTIMIZE_STEPS = (
    "注入故障",           # 1. 在实际网络环境中注入故障
    "发送故障现象",       # 2. 把故障现象发送给 Agent
    "定位与分析",         # 3. Agent 加载 Skill 做故障定位与分析
    "故障恢复",           # 4. 演练结束，恢复注入的故障，环境回到基线
    "编辑优化 Skill",     # 5. 根据 Agent 执行轨迹编辑优化 Skill
    "返回优化后的 Skill", # 6. 包装代码拿到优化结果时自动标记完成
)


async def optimize_skill(intent: str, skill: str, round_number: int):
    """点击「优化 Skill」时调用：当前接入 mock_optimizer 的演练流程，逐阶段 yield 进度。

    mock 流程（mock_optimizer/ 文件夹）：故障注入 → 发送请求给 Agent →
    故障分析（Agent 加载 Skill 产出执行轨迹与缺口）→ 故障恢复 → 编辑并返回优化后的 Skill。
    接入真实环境时，替换 mock_optimizer 内各模块的实现，或把下面的委托换成真实调用。
    进度契约不变：yield {"step", "status", "content"}，最后 yield 优化后的完整 Markdown 字符串。
    也兼容旧式接入：不 yield 进度，直接返回完整 Markdown 字符串的普通函数 / 协程。
    """
    async for progress in run_mock_optimize(intent, skill, round_number):
        yield progress


# ====== 以下是接入界面的包装代码，一般无需修改 ======


async def call(function, *args):
    # 同步函数、async 函数和返回协程的调用方式都支持。
    result = function(*args)
    while inspect.isawaitable(result):
        result = await result
    return result


async def generate_events(intent: str, skill_id: str = ""):
    skill = await call(generate_skill, intent, skill_id)
    yield {"type": "skill", "id": "skill-0", "round": 0, "content": skill}


def apply_progress(states, progress, started):
    # progress：{"step": 序号, "status": running/completed, "content": 可选说明}。
    if not isinstance(progress, dict) or not isinstance(progress.get("step"), int):
        raise RuntimeError("optimize_skill yield 的进度必须是包含 step 序号的字典")
    for state in states:
        if state["step"] != progress["step"]:
            continue
        state["status"] = progress["status"] if progress.get("status") in ("running", "completed") else "running"
        if progress.get("content"):
            state["content"] = str(progress["content"])
        # 阶段真实耗时：running 起表，completed 时结算写入 elapsed（秒）。
        if state["status"] == "running" and state["step"] not in started:
            started[state["step"]] = time.monotonic()
        elif state["status"] == "completed" and state["step"] in started:
            state["elapsed"] = round(time.monotonic() - started.pop(state["step"]), 1)


def settle_elapsed(states, started, status):
    # 中断收尾：把还挂着计时的阶段结算出已耗时间。
    for state in states:
        if state["status"] == status and state["step"] in started:
            state["elapsed"] = round(time.monotonic() - started.pop(state["step"]), 1)


async def optimize_events(intent: str, skill: str, round_number: int):
    generator = optimize_skill(intent, skill, round_number)
    if not (inspect.isasyncgen(generator) or inspect.isgenerator(generator)):
        # 旧式接入：optimize_skill 是普通函数 / 协程，等返回后直接发最终版本。
        optimized = generator
        while inspect.isawaitable(optimized):
            optimized = await optimized
        yield {"type": "optimized_skill", "id": f"skill-{round_number}", "round": round_number, "content": optimized}
        return

    # 五个阶段的实时状态：pending / running / completed / failed（完成后附耗时 elapsed），前端渲染成进度清单。
    states = [{"step": index, "title": title, "status": "pending", "content": ""}
              for index, title in enumerate(OPTIMIZE_STEPS, start=1)]
    started = {}

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
            apply_progress(states, progress, started)
            yield snapshot()
    except Exception:
        # 中途失败：结算耗时并把执行中的阶段标记为 failed，再交给上层记录 error 事件。
        settle_elapsed(states, started, "running")
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
