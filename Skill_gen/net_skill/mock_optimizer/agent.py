"""mock Agent：接收故障现象，加载当前 Skill 按步骤执行，产出执行轨迹与技能缺口。"""
import json
import re


def send(payload: dict) -> str:
    """第 2 步：把故障现象发送给 Agent（mock 一次诊断请求），返回回执。"""
    body = json.dumps(payload, ensure_ascii=False)
    return (f"已发送故障现象给 Agent（POST /agent/diagnose，{len(body.encode('utf-8'))} 字节）："
            f"告警={payload['alarm']}；材料={'、'.join(payload['materials'])}。")


def steps_of(skill: str) -> list:
    """从 Skill Markdown 中提取编号步骤（形如“1. xxx”的行）。"""
    return [match.group(1).strip() for match in re.finditer(r"^\s*\d+\.\s+(.+)$", skill, re.MULTILINE)]


def analyze(skill: str, fault: dict) -> dict:
    """第 3 步：Agent 加载 Skill 执行故障定位与分析，返回执行轨迹和暴露的缺口。"""
    steps = steps_of(skill)
    trace = [f"[Agent] 加载 Skill（{len(steps)} 个步骤），开始故障定位"]
    for index, step in enumerate(steps, start=1):
        trace.append(f"[Agent] {index:02d} · {step} —— 通过")
    # 演练设定的受阻点：真实技能缺口让定位在这里中断，成为本轮优化的依据。
    trace.append(f"[Agent] ⚠ 受阻：{fault['gap']}，定位中断，转人工补全")
    trace.append(f"[Agent] 期望根因：{fault['root_cause']}")
    return {
        "trace": "\n".join(trace),
        "gap": fault["gap"],
        "symptom": fault["symptom"],
    }
