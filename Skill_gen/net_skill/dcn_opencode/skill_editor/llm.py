"""火山方舟 ARK 大模型接入：环境变量配置、prompt 构造、同步调用与输出校验。

环境变量（每次现读，不缓存）：
- ARK_API_KEY：方舟凭证，缺失则大模型路径不可用。
- SKILL_LLM_MODEL：模型名或接入点 ID（如 doubao-seed-1.6 或 ep-2024xx），缺失则不可用。
- ARK_BASE_URL：覆盖接入地址，默认 https://ark.cn-beijing.volces.com/api/v3。
- SKILL_LLM_TIMEOUT：单次请求超时秒数，默认 60。

openai 只在函数内懒加载：未安装 openai 的环境模块照常导入，available() 返回 False，
上层自动回退规则编辑，python app.py 开箱可跑。
"""
import os

from . import trajectory as trajectory_module

DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

SYSTEM_PROMPT = (
    "你是网络故障诊断 Skill 文档的编辑 agent，根据运维执行轨迹优化 Skill 文档。\n"
    "输出规则（必须严格遵守）：\n"
    "1. 只输出优化后的完整 Markdown 文档本体，不要任何解释、前后缀或对话。\n"
    "2. 不要用 ``` 代码块包裹输出。\n"
    "3. 原样保留文档顶部的 frontmatter（--- 包围的 name/description 等）。\n"
    "4. 不删除原有有效内容，只做必要的修订、补充与排版。"
)

# 按设置元组缓存的客户端；环境变量变化时重建，不会拿到陈旧实例。
_CLIENTS = {}


def settings() -> dict:
    """读取大模型相关环境变量；api_key 与 model 齐备才算可用。"""
    return {
        "api_key": os.environ.get("ARK_API_KEY", "").strip(),
        "model": os.environ.get("SKILL_LLM_MODEL", "").strip(),
        "base_url": os.environ.get("ARK_BASE_URL", "").strip() or DEFAULT_BASE_URL,
        "timeout": float(os.environ.get("SKILL_LLM_TIMEOUT", "").strip() or 60),
    }


def available() -> bool:
    """openai 已安装且凭证、模型名齐备时返回 True。"""
    try:
        import openai  # noqa: F401 懒加载：只探测是否安装
    except ImportError:
        return False
    config = settings()
    return bool(config["api_key"] and config["model"])


def build_client():
    """创建（或复用）指向方舟的 openai 客户端；调用前须先确认 available()。"""
    import openai

    config = settings()
    key = (config["api_key"], config["base_url"], config["timeout"])
    if key not in _CLIENTS:
        _CLIENTS[key] = openai.OpenAI(api_key=config["api_key"], base_url=config["base_url"], timeout=config["timeout"])
    return _CLIENTS[key]


def build_messages(skill: str, round_number: int, trajectory: dict, retry_note: str = "") -> list:
    """构造编辑 prompt：当前 Skill 全文 + 轨迹段 + 本轮编辑要求。

    retry_note 非空时（上一版候选被回滚后的重试），追加针对性要求。
    """
    fault = trajectory.get("fault") or {}
    fault_name = fault.get("name", "未知故障")
    verdict_text = "正确（correct）" if trajectory["verdict"] == "correct" else "错误（incorrect）"
    request = (
        f"这是第 {round_number} 轮优化。轨迹判定结果为{verdict_text}。"
        + (f"演练暴露的技能缺口：{trajectory['gap']}。" if trajectory["gap"] else "")
        + f"请在文档末尾补充一节，标题为「## 第 {round_number} 轮优化 · {fault_name}故障处理」，"
        + "内容覆盖五要素：识别现象、缩小范围、根因确认、处置动作、验证恢复。"
        + f"本轮期望根因：{trajectory['expected'] or '未记录'}。"
        + "若轨迹里有成功的工具调用路径，把它固化进处理步骤；其余章节可润色但不得丢失信息。"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "<current_skill>\n" + skill + "\n</current_skill>\n\n"
            "<trajectory>\n" + trajectory_module.render_for_llm(trajectory) + "\n</trajectory>\n\n"
            + request + (f"\n\n{retry_note}" if retry_note else "")
        )},
    ]


def complete(client, messages: list) -> str:
    """同步调用大模型并返回原始文本；截断（finish_reason=length）按错误处理。"""
    response = client.chat.completions.create(model=settings()["model"], messages=messages)
    choice = response.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        raise ValueError("大模型输出被 max_tokens 截断")
    return str(choice.message.content or "")


def clean_output(raw: str, skill: str, fault_name: str) -> str:
    """校验并清洗大模型输出；不合格 raise ValueError，由上层回退规则编辑。"""
    text = str(raw).strip()
    if not text:
        raise ValueError("大模型返回空输出")
    lines = text.splitlines()
    # 剥掉成对的 ``` 围栏（含 ```markdown 等语言标注）；只有开头围栏视为截断。
    if lines[0].startswith("```"):
        if len(lines) < 2 or not text.rstrip().endswith("```") or lines[-1].strip() != "```":
            raise ValueError("大模型输出只有开头代码围栏，疑似截断")
        lines = lines[1:-1]
        text = "\n".join(lines).strip()
        if not text:
            raise ValueError("大模型返回空输出")
    # 原 Skill 带 frontmatter 时，输出必须原样保留（--- 开头且含 name: 行）。
    if skill.lstrip().startswith("---"):
        name_line = next((line for line in skill.splitlines() if line.strip().startswith("name:")), "")
        if not text.startswith("---") or (name_line and name_line not in text):
            raise ValueError("大模型输出丢失了原 frontmatter")
    if len(text) < max(200, len(skill) * 0.5):
        raise ValueError("大模型输出过短，疑似截断或过度删减")
    if fault_name and fault_name not in text:
        raise ValueError("大模型输出未体现本轮故障")
    return text
