"""接入你的 Skill 生成与优化函数；界面分两步调用：生成 → 逐轮优化。"""
import asyncio
import inspect


# ====== 接入区：把你的两个函数放在这里 ======

async def generate_skill(intent: str) -> str:
    """点击「生成 Skill」时调用：根据意图生成初始 Skill，返回完整 Markdown 字符串。"""
    await asyncio.sleep(1.5)  # 示例延迟，接入时可删除
    return f"# 自生成 Skill\n\n## 目标\n{intent}\n\n## 步骤\n1. 分析输入。\n2. 执行任务。\n3. 输出结果。"


async def optimize_skill(intent: str, skill: str, round_number: int) -> str:
    """点击「优化 Skill」时调用：基于当前版本优化，返回优化后的完整 Markdown 字符串。

    skill 是当前最新版本的内容；round_number 从 1 开始，每次点击递增。
    """
    await asyncio.sleep(1.0)  # 示例延迟，接入时可删除
    return skill + f"\n\n## 第 {round_number} 轮优化\n补充失败场景与交付要求。"

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


async def optimize_events(intent: str, skill: str, round_number: int):
    optimized = await call(optimize_skill, intent, skill, round_number)
    yield {"type": "optimized_skill", "id": f"skill-{round_number}", "round": round_number, "content": optimized}
