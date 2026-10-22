"""状态机优化流程检查：python -B tests/check_mock.py（只用标准库，零延迟，清空大模型凭证）。"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from net_skill.dcn_opencode import state_machine
from net_skill.dcn_opencode.mock_optimizer import agent, faults
from net_skill.dcn_opencode.pipeline import catalog, edit_records, generate_events, resolve_skill
from net_skill.dcn_opencode.skill_editor import fallback

# 清空大模型环境变量：编辑 agent 第 1 次尝试走演练弱草稿，路径完全确定。
NO_LLM_ENV = {"ARK_API_KEY": "", "SKILL_LLM_MODEL": ""}
BASE_SKILL = "---\nname: network-fault-diag\ndescription: 网络故障诊断与根因定位\n---\n\n单板重启的故障定位，请参考reference/fault_01_board_reset.md的内容\n"

ALL_CASES = [item["id"] for item in faults.samples()] or []


async def collect(round_number, skill, case_ids=None, session_id=""):
    zero = dict.fromkeys(state_machine.DELAYS, 0)
    return [event async for event in state_machine.optimize(
        "网络故障定位", skill, round_number, case_ids=case_ids, session_id=session_id, delays=zero)]


def statuses(events, step):
    return [event["status"] for event in events if isinstance(event, dict) and event.get("step") == step]


def completed(events, step):
    notes = [event["content"] for event in events if isinstance(event, dict)
             and event.get("step") == step and event["status"] == "completed"]
    assert notes, f"step {step} 没有 completed 记录"
    return notes


def check_rounds():
    skill = BASE_SKILL
    for round_number in (1, 2):
        events = asyncio.run(collect(round_number, skill))
        # 契约：1/2/6 各一次 running→completed；回滚重试轮 3/4/5 各两次。
        for step in (1, 2, 6):
            assert statuses(events, step) == ["running", "completed"], (round_number, step)
        for step in (3, 4, 5):
            assert statuses(events, step) == ["running", "completed", "running", "completed"], (round_number, step)
        final = events[-1]
        assert isinstance(final, str), round_number
        # 基线 → 弱草稿回滚 → 真实修订接受：准确率逐步上升。
        if round_number == 1:
            assert "基线准确率 0/2 = 0.00" in completed(events, 2)[0]
        else:
            assert "基线准确率 1/2 = 0.50" in completed(events, 2)[0]
        decisions = completed(events, 5)
        assert "回滚" in decisions[0] and "接受" in decisions[1], (round_number, decisions)
        assert f"第 {round_number} 轮优化 · 接口down故障处理" in final, round_number
        assert final.startswith(skill.rstrip()), round_number
        skill = final

    # 第 3 轮：基线已全对，跳过编辑 / 评测 / 决策，最终返回基线版本。
    events = asyncio.run(collect(3, skill))
    for step in range(1, 7):
        assert statuses(events, step) == ["running", "completed"], (3, step)
    assert "= 1.00" in completed(events, 2)[0]
    for step in (3, 4, 5):
        assert "跳过" in completed(events, step)[0] or "保持" in completed(events, step)[0], step
    assert events[-1] == skill, "跳过轮应原样返回基线版本"

    # 双回滚：正文只覆盖 diag_001，但轮换到的编辑目标也是 diag_001（已覆盖），
    # 两次候选都无法提升 → 全部回滚，保持基线。
    partial = BASE_SKILL + ("\n## 第 9 轮优化 · 接口down故障处理\n\n"
                            f"检查 em5_serverleaf2：{faults.FAULTS[0]['root_cause']}。\n")
    events = asyncio.run(collect(1, partial, case_ids=ALL_CASES))
    assert statuses(events, 5) == ["running", "completed", "running", "completed"]
    assert "保持基线版本" in completed(events, 5)[-1]
    assert events[-1] == partial, "双回滚轮应保持基线版本"
    return skill


def check_evaluator():
    v0 = BASE_SKILL
    fault1, fault2 = faults.FAULTS[0], faults.FAULTS[1]
    # 覆盖判断只看正文：frontmatter description 里的「物理接口down」不算覆盖。
    assert not agent.covered(v0, fault1), "V0 不应被判为已覆盖"
    covered_skill = fallback.revise(v0, 1, agent.analyze(v0, fault1)["trajectory"])
    assert agent.covered(covered_skill, fault1)
    assert not agent.covered(covered_skill, fault2), "覆盖 serverleaf2 不等于覆盖 serverleaf3"
    # 评测器：覆盖用例得出根因（judge 判 correct），未覆盖用例受阻（incorrect）。
    result = agent.evaluate(covered_skill, [fault1, fault2])
    assert result["total"] == 2 and result["covered"] == 1 and abs(result["accuracy"] - 0.5) < 1e-9
    first, second = result["trajectories"]
    assert first["verdict"] == "correct" and first["final_answer"] == fault1["root_cause"]
    assert second["verdict"] == "incorrect" and second["final_answer"] == ""
    assert [item["case"] for item in result["trajectories"]] == [fault1["case"], fault2["case"]]
    assert "准确率 1/2 = 0.50" in result["trace"]
    # 旧 analyze 契约不回归：受阻轨迹、工具序列、判定 incorrect。
    analysis = agent.analyze(covered_skill, fault2)
    assert analysis["trajectory"]["verdict"] == "incorrect"
    assert [a["tool"] for a in analysis["trajectory"]["actions"][:2]] == list(agent.TOOLS[:2])


def check_records():
    # 记录落盘：接受轮（弱草稿回滚 + 真实修订生效）、双回滚轮、跳过轮三种形态。
    skill = BASE_SKILL
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "edit_records.json"
        with patch.object(state_machine, "RECORDS_FILE", target):
            events = asyncio.run(collect(1, skill, session_id="sess-test"))
            accepted = json.loads(target.read_text(encoding="utf-8"))
            assert len(accepted) == 1
            record = accepted[0]
            assert record["session"] == "sess-test" and record["round"] == 1
            assert record["task_ids"] == ALL_CASES and record["edit_count"] == 2
            assert record["baseline_accuracy"] == 0.0 and record["accuracy"] == 0.5
            assert [edit["status"] for edit in record["edits"]] == ["rolled_back", "applied"]
            assert "弱草稿" in record["edits"][0]["summary"] and "回滚" in record["edits"][0]["summary"]
            assert "接受" in record["edits"][1]["summary"]
            assert all({"index", "op", "status", "skill_name", "references", "target", "summary", "content"}
                       <= set(edit) for edit in record["edits"])

            partial = BASE_SKILL + f"\n检查 em5_serverleaf2：{faults.FAULTS[0]['root_cause']}。\n"
            asyncio.run(collect(1, partial, case_ids=ALL_CASES, session_id="sess-test"))
            full = BASE_SKILL + "".join(
                f"\n## 第 {n} 轮优化 · 接口down故障处理\n\n检查 {fault['scope']}：{fault['root_cause']}。\n"
                for n, fault in ((1, faults.FAULTS[0]), (2, faults.FAULTS[1])))
            asyncio.run(collect(3, full, session_id="sess-test"))  # 跳过轮
            records = json.loads(target.read_text(encoding="utf-8"))
            assert [r["edit_count"] for r in records] == [2, 2, 0]
            assert [e["status"] for e in records[1]["edits"]] == ["rolled_back", "rolled_back"]
            assert records[1]["accuracy"] == records[1]["baseline_accuracy"] == 0.5
            assert records[2]["edits"] == [] and records[2]["accuracy"] == 1.0
            # 文件损坏容错：内容非法时按空列表重建。
            target.write_text("not json", encoding="utf-8")
            state_machine.append_record({"session": "x", "round": 9, "edits": []})
            assert [r["round"] for r in json.loads(target.read_text(encoding="utf-8"))] == [9]


def check():
    check_rounds()
    check_evaluator()
    check_records()

    # 没有编号步骤的 Skill 也能完成评测与编辑；受阻轨迹判定 incorrect。
    sparse = "# 只有描述的 Skill\n\n没有步骤。\n"
    analysis = agent.analyze(sparse, faults.FAULTS[0])
    assert "0 个步骤" in analysis["trace"]
    assert analysis["trajectory"]["verdict"] == "incorrect"
    assert sparse in fallback.revise(sparse, 1, analysis["trajectory"])

    # Skill 目录：frontmatter 解析出名称与描述，选择解析支持命中与回退。
    items = catalog()["items"]
    assert items and items[0]["id"], "skills/ 下应至少有一个待优化 Skill"
    first = next(item for item in items if item["id"] == "network-fault-diag")
    assert first["name"] == "network-fault-diag" and "网络故障" in first["description"]
    assert resolve_skill("network-fault-diag") == "network-fault-diag"
    assert resolve_skill("no-such-skill") == items[0]["id"] and resolve_skill("") == items[0]["id"]

    async def first_event():
        async for event in generate_events("意图", "network-fault-diag"):
            return event

    seed = asyncio.run(first_event())
    assert seed["type"] == "skill" and "network-fault-diag" in seed["content"]

    # 用例选择：按样本 id 过滤故障；无效选择回退全部。
    assert ALL_CASES, "data/train_data.json 应至少有一条训练样本"
    assert faults.pick(1, [ALL_CASES[0]]).get("case") == ALL_CASES[0]
    assert faults.pick(1, ["no-such-case"]).get("case") == faults.pick(1).get("case")
    # 编辑记录接口：仓库示例文件可读，字段为契约超集（新记录可多 baseline_accuracy 等键）。
    for record in edit_records()["items"]:
        assert {"session", "round", "task_ids", "accuracy", "generated_at", "edit_count", "edits"} <= set(record)
        assert record["edit_count"] == len(record["edits"])

    print("PASS: state machine evaluates baseline, rolls back weak draft, accepts improvement, "
          "skips at ceiling; evaluator coverage by body; edit records persisted atomically")


if __name__ == "__main__":
    # 清空大模型环境变量再跑：无论机器是否配置过凭证，编辑都走确定性演练路径。
    with patch.dict(os.environ, NO_LLM_ENV):
        check()
