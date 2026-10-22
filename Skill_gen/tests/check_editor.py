"""skill 编辑 agent 检查：python -B tests/check_editor.py（只用标准库，零延迟零网络）。

覆盖轨迹契约（normalize/judge/渲染）、LLM prompt 构造与输出校验、规则回退，
以及注入假客户端与清空环境变量下的引擎选择；端到端经 state_machine 走 LLM 路径。
不依赖机器上是否安装 openai、是否配置了真实凭证。
"""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from net_skill.dcn_opencode import skill_editor, state_machine
from net_skill.dcn_opencode.mock_optimizer import agent, faults
from net_skill.dcn_opencode.skill_editor import fallback, llm
from net_skill.dcn_opencode.skill_editor import trajectory as trajectory_module

BASE_SKILL = "# 网络故障定位 Skill\n\n## 步骤\n1. 收集告警。\n2. 检查链路。\n3. 输出结论。\n"
FRONT_SKILL = "---\nname: network-fault-diag\ndescription: 网络故障诊断\n---\n\n按 reference 定位故障。\n"
# 清空大模型环境变量：无论机器是否配置过真实凭证，测试都走确定性路径。
NO_LLM_ENV = {"ARK_API_KEY": "", "SKILL_LLM_MODEL": ""}


def fake_client(content=None, error=None):
    """构造只实现 chat.completions.create 的假客户端；返回 (client, calls) 供断言。"""
    calls = []

    def create(model, messages, **kwargs):
        calls.append({"model": model, "messages": messages})
        if error is not None:
            raise error
        choice = SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")
        return SimpleNamespace(choices=[choice])

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), calls


def valid_llm_doc(skill, fault, fenced=True):
    """构造一份能通过输出校验且覆盖该故障（含设备与故障名）的假大模型文档。"""
    body = (f"{skill.rstrip()}\n\n## 第 1 轮优化 · {fault['name']}故障处理\n\n"
            "> 演练发现缺口：Skill 未覆盖该故障的定位路径\n\n"
            "1. 识别现象：按告警与日志确认故障现象。\n"
            f"2. 缩小范围：检查 {fault['scope']} 的状态与最近变更。\n"
            "3. 根因确认：结合工具调用结果收敛根因。\n"
            "4. 处置动作：按确认的根因完成处置。\n"
            "5. 验证恢复：复核告警清除，并记录到故障档案。\n")
    return f"```markdown\n{body}```" if fenced else body


def expect_value_error(bad, skill, fault_name, why):
    try:
        llm.clean_output(bad, skill, fault_name)
        raise AssertionError(f"应当因「{why}」报错")
    except ValueError:
        pass


def check():
    fault = faults.pick(1)
    analysis = agent.analyze(BASE_SKILL, fault)
    trajectory = analysis["trajectory"]

    # 轨迹契约：用了哪个 Skill、调了哪些工具、结论与期望比对判对错。
    assert trajectory["skill"]["name"] == "未命名" and len(trajectory["skill"]["steps"]) == 3
    assert [action["tool"] for action in trajectory["actions"][:3]] == list(agent.TOOLS[:3])
    assert trajectory["actions"][-1]["ok"] is False and trajectory["actions"][-1]["step"] == 0
    assert trajectory["verdict"] == "incorrect" and trajectory["final_answer"] == ""
    assert trajectory["expected"] == fault["root_cause"] and trajectory["gap"] == fault["gap"]

    # judge：规范化后双向包含才算对；空结论或互不包含为错。
    assert trajectory_module.judge("接口 DOWN！", "接口down") == "correct"
    assert trajectory_module.judge("", "接口down") == "incorrect"
    assert trajectory_module.judge("完全不同的结论", "接口down") == "incorrect"
    assert trajectory_module.judge("结论：serverleaf2由于出现了接口down，导致 vxlan 告警", "serverleaf2由于出现了接口down") == "correct"

    # normalize：缺键补默认、action 五键齐全、verdict 缺失时现算、键序固定。
    normalized = trajectory_module.normalize({"final_answer": "接口down", "expected": "接口 down"})
    assert normalized["verdict"] == "correct" and normalized["case"] == "" and normalized["skill"]["name"] == "未命名"
    assert normalized["actions"] == [] and list(normalized.keys()) == [
        "case", "fault", "skill", "actions", "final_answer", "expected", "verdict", "gap"]

    # 渲染：界面轨迹保留既有标记并新增工具与判定；LLM 轨迹段含工具与判定，且确定性输出。
    trace = analysis["trace"]
    assert "3 个步骤" in trace and "受阻" in trace and fault["gap"] in trace
    assert "工具 query_alarms" in trace and "判定 incorrect" in trace and "期望根因" in trace
    segment = trajectory_module.render_for_llm(trajectory)
    assert segment == trajectory_module.render_for_llm(trajectory)
    for marker in ("query_alarms", "root_cause_check", fault["name"], fault["root_cause"], "结果判定：incorrect"):
        assert marker in segment, marker

    # prompt：system + user 两条，user 含 Skill 全文、轨迹段、轮次与故障名；retry_note 透传。
    messages = llm.build_messages(BASE_SKILL, 2, trajectory)
    assert [item["role"] for item in messages] == ["system", "user"]
    user = messages[1]["content"]
    assert BASE_SKILL in user and segment in user and "第 2 轮" in user and fault["name"] in user
    assert "重试提示" not in user
    retried = llm.build_messages(BASE_SKILL, 2, trajectory, retry_note="重试提示：务必覆盖设备与根因")
    assert "重试提示：务必覆盖设备与根因" in retried[1]["content"] and retried[1]["content"].startswith(user[:60])

    # 输出校验：剥围栏、frontmatter 保留、长度下限、相关性。
    cleaned = llm.clean_output(valid_llm_doc(BASE_SKILL, fault), BASE_SKILL, fault["name"])
    assert cleaned.startswith("# 网络故障定位") and cleaned.endswith("故障档案。")
    assert llm.clean_output(valid_llm_doc(BASE_SKILL, fault, fenced=False), BASE_SKILL, fault["name"]) == cleaned
    expect_value_error("", BASE_SKILL, fault["name"], "空输出")
    expect_value_error("```markdown\n只有开头围栏", BASE_SKILL, fault["name"], "只有开头围栏")
    expect_value_error("太短", BASE_SKILL, fault["name"], "过短")
    expect_value_error("与故障无关的结论，" * 100, BASE_SKILL, fault["name"], "未体现本轮故障")
    # 保留 frontmatter 的合法输出应通过；丢失或篡改则拒绝。
    assert llm.clean_output(valid_llm_doc(FRONT_SKILL, fault, fenced=False), FRONT_SKILL, fault["name"]).startswith("---")
    expect_value_error(f"no-frontmatter\n{fault['name']}，" + "内容" * 200, FRONT_SKILL, fault["name"], "丢失 frontmatter")
    expect_value_error(FRONT_SKILL.replace("name: network-fault-diag", "name: 改名了") + fault["name"] + "，" + "内容" * 200,
                       FRONT_SKILL, fault["name"], "篡改 frontmatter")

    # 规则回退：追加式章节，与轨迹里的故障信息一致。
    revised = fallback.revise(BASE_SKILL, 3, trajectory)
    assert revised.startswith(BASE_SKILL.rstrip()) and f"## 第 3 轮优化 · {fault['name']}故障处理" in revised
    for keyword in ("识别现象", "缩小范围", "根因确认", "处置动作", "验证恢复"):
        assert keyword in revised, keyword

    # 引擎选择：注入假客户端走 LLM；异常 / 空输出 / 未配置凭证都回退。
    with patch.dict(os.environ, {**NO_LLM_ENV, "SKILL_LLM_MODEL": "test-model"}):
        good, calls = fake_client(valid_llm_doc(BASE_SKILL, fault))
        result = asyncio.run(skill_editor.revise(BASE_SKILL, 1, trajectory, client=good))
        assert result["engine"] == "llm" and "大模型" in result["note"] and result["content"].startswith("# 网络故障定位")
        assert calls and calls[0]["model"] == "test-model"

        broken, _ = fake_client(error=RuntimeError("模拟超时"))
        result = asyncio.run(skill_editor.revise(BASE_SKILL, 1, trajectory, client=broken))
        assert result["engine"] == "fallback" and "回退" in result["note"] and "模拟超时" in result["note"]

        garbage, _ = fake_client("")
        result = asyncio.run(skill_editor.revise(BASE_SKILL, 1, trajectory, client=garbage))
        assert result["engine"] == "fallback" and "回退" in result["note"]

    with patch.dict(os.environ, NO_LLM_ENV):
        result = asyncio.run(skill_editor.revise(BASE_SKILL, 1, trajectory))
        assert result["engine"] == "fallback" and "未接入大模型" in result["note"]
        assert result["content"] == fallback.revise(BASE_SKILL, 1, trajectory)

    # 端到端（LLM 路径）：假客户端第 1 次尝试即产出覆盖故障的候选，评测通过后接受。
    async def collect():
        zero = dict.fromkeys(state_machine.DELAYS, 0)
        good, _ = fake_client(valid_llm_doc(BASE_SKILL, fault))
        return [event async for event in state_machine.optimize("网络故障定位", BASE_SKILL, 1,
                                                                delays=zero, editor_client=good)]

    with patch.dict(os.environ, {**NO_LLM_ENV, "SKILL_LLM_MODEL": "test-model"}):
        events = asyncio.run(collect())
    progresses, final = [event for event in events if isinstance(event, dict)], events[-1]
    for step in range(1, 7):  # 状态机汇报 1–6 阶段；LLM 第 1 次尝试即接受，各阶段只进入一次。
        statuses = [event["status"] for event in progresses if event.get("step") == step]
        assert statuses == ["running", "completed"], (step, statuses)
    step3 = next(event for event in progresses if event.get("step") == 3 and event["status"] == "completed")
    step5 = next(event for event in progresses if event.get("step") == 5 and event["status"] == "completed")
    assert "大模型" in step3["content"] and "接受" in step5["content"] and "0.00 → 0.50" in step5["content"]
    assert final == llm.clean_output(valid_llm_doc(BASE_SKILL, fault), BASE_SKILL, fault["name"])

    print("PASS: trajectory contract, judge, renders, prompt, output checks, fallback, engine selection and state-machine e2e (llm path)")


if __name__ == "__main__":
    check()
