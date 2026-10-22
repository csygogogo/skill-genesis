"""DCN 真实闭环模块检查：python -B tests/check_dcn.py（只用标准库，零网络）。

覆盖 eval_parse 容错解析、polaris_client / upload_skill_dcn 的配置与降级、
skill_edit 的轨迹映射与分析 prompt、dcn_pipeline 闭环（注入评测函数，
验证接受 / 回滚 / 跳过路径与编辑记录落盘）。
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from net_skill.dcn_opencode import dcn_pipeline, eval_parse, polaris_client, skill_edit, upload_skill_dcn
from net_skill.dcn_opencode import state_machine
from net_skill.dcn_opencode.mock_optimizer import faults

NO_LLM_ENV = {"ARK_API_KEY": "", "SKILL_LLM_MODEL": "", "POLARIS_BASE_URL": "", "OPENCODE_UPLOAD_URL": ""}
ALL_CASES = [item["id"] for item in faults.samples()] or []


def check_parse():
    raw = {"results": [
        {"case_name": "diag_001", "question": "vxlan 告警", "agent_answer": "接口 down",
         "gold_answer": "接口down", "score": 0, "steps": ["查告警", "查接口"]},
        {"id": "diag_002", "q": "serverleaf3 告警", "response": "接口 down", "expected": "接口 down",
         "pass_rate": "100%", "trajectory": "查告警\n查日志"},
    ]}
    items = eval_parse.parse_agents(raw)
    assert len(items) == 2
    first, second = items
    assert first["case"] == "diag_001" and first["question"] == "vxlan 告警"
    assert first["answer"] == "接口 down" and first["expected"] == "接口down"
    assert first["accuracy"] == 0.0 and first["trace"] == "查告警\n查接口"
    assert second["accuracy"] == 1.0 and second["trace"] == "查告警\n查日志"
    # 准确率规格归一：0–100 / 百分号 / 非法值。
    assert eval_parse.normalize_accuracy(85) == 0.85
    assert eval_parse.normalize_accuracy("85%") == 0.85
    assert eval_parse.normalize_accuracy("0.85") == 0.85
    assert eval_parse.normalize_accuracy(None) == 0.0
    assert eval_parse.summarize(items)["accuracy"] == 0.5 and eval_parse.summarize([])["accuracy"] == 0.0
    # 列表直接输入与非 dict 条目跳过。
    assert len(eval_parse.parse_agents([{"case": "x"}, "junk", 5])) == 1


def check_parse_csv():
    # 评测平台结果为 CSV：中文表头 + 引号内换行轨迹 + 百分号准确率 + BOM。
    csv_text = (
        "用例名,问题,答案,期望根因,准确率,执行轨迹\r\n"
        'diag_001,"serverleaf2 vxlan 告警，请分析原因","接口 down","serverleaf2由于出现了接口down",50%,'
        '"[Agent] 加载 Skill（0 个步骤）\n[Agent] 查询告警\n[Agent] 未得出根因"\r\n'
        'diag_002,"serverleaf3 告警","接口 down","serverleaf3由于出现了接口down",1,"查告警\n查日志"\r\n'
        "\r\n"
    )
    items = eval_parse.parse_agents(chr(0xFEFF) + csv_text)
    assert len(items) == 2, "空行应被跳过"
    first, second = items
    assert first["case"] == "diag_001" and first["question"].startswith("serverleaf2")
    assert first["expected"] == "serverleaf2由于出现了接口down" and first["accuracy"] == 0.5
    assert first["trace"].count("\n") == 2 and "未得出根因" in first["trace"]
    assert second["accuracy"] == 1.0 and second["trace"] == "查告警\n查日志"
    # 分号分隔 + 英文表头；未知列被忽略。
    semicolon = "case;answer;score;trajectory\n" "diag_003;链路丢包;0.85;查告警\n"
    item = eval_parse.parse_csv(semicolon)[0]
    assert item["case"] == "diag_003" and item["accuracy"] == 0.85 and item["trace"] == "查告警"
    assert eval_parse.parse_csv("") == []


def check_clients():
    with patch.dict("os.environ", NO_LLM_ENV, clear=False):
        assert polaris_client.available() is False and upload_skill_dcn.available() is False
        assert polaris_client.settings()["submit_path"] == "/api/eval/tasks"
        assert upload_skill_dcn.settings()["timeout"] == 30.0
    # 未配置上传地址时 upload_skill 是安全空操作；降级说明正确。
    with patch.dict("os.environ", NO_LLM_ENV, clear=False):
        upload_skill_dcn.upload_skill("# skill", "network-fault-diag")
        assert "跳过" in dcn_pipeline.sync_skill("# skill")


def check_skill_edit():
    items = [
        {"case": "diag_001", "question": "serverleaf2 vxlan 告警", "answer": "",
         "expected": "emulation5组网中serverleaf2由于出现了接口down", "accuracy": 0.0, "trace": "查告警\n查日志"},
        {"case": "diag_002", "question": "serverleaf3 告警", "answer": "接口 down",
         "expected": "接口 down", "accuracy": 1.0, "trace": "查告警"},
    ]
    # 编辑目标选准确率最低的 case；轨迹映射出受阻收尾动作与缺口。
    target = skill_edit.pick_target(items)
    assert target["case"] == "diag_001"
    trajectory = skill_edit.build_trajectory(target)
    assert trajectory["case"] == "diag_001" and trajectory["verdict"] == "incorrect"
    assert trajectory["actions"][0]["desc"] == "查告警" and trajectory["actions"][-1]["ok"] is False
    assert "serverleaf2由于出现了接口down" in trajectory["gap"]
    # 期望根因缺失时回退训练集 gold_answer。
    bare = skill_edit.build_trajectory({"case": "diag_002", "answer": "", "accuracy": 0.0, "trace": "查告警"})
    assert "serverleaf3" in bare["expected"]
    # 分析 prompt：模板渲染进每个 case 的关键信息。
    prompt = skill_edit.analysis_prompt(items)
    for marker in ("diag_001", "归因", "serverleaf2", "准确率：0%", "执行轨迹"):
        assert marker in prompt, marker
    # 规则回退编辑产出追加式候选。
    with patch.dict("os.environ", NO_LLM_ENV, clear=False):
        result = skill_edit.edit_skill("# 基线\n\n1. 步骤。\n", 1, items)
    assert result["engine"] == "fallback" and result["content"].startswith("# 基线")


def check_loop():
    # 注入评测函数：基线全错 → 编辑后第一个 case 变对（接受），再编辑第二个 case 变对（接受），随后全对（跳过）。
    state = {"passing": set()}

    def fake_evaluator(skill, case_ids=None):
        items = []
        for sample in faults.samples():
            case = sample["id"]
            correct = case in state["passing"] or sample.get("gold_answer", "") in skill
            items.append({"case": case, "question": sample.get("question", ""), "answer": sample.get("gold_answer", "") if correct else "",
                          "expected": sample.get("gold_answer", ""), "accuracy": 1.0 if correct else 0.0, "trace": "查告警"})
        accuracy = sum(item["accuracy"] for item in items) / len(items)
        return {"accuracy": accuracy, "items": items}

    # 触发接受路径：fallback 编辑会写入目标 case 的 gold_answer（coverage 判断同款字段）。
    with tempfile.TemporaryDirectory() as directory, \
            patch.dict("os.environ", NO_LLM_ENV, clear=False), \
            patch.object(state_machine, "RECORDS_FILE", Path(directory) / "edit_records.json"):
        report = dcn_pipeline.run_loop(rounds=3, session_id="dcn-test", evaluator=fake_evaluator)
        rounds = report["rounds"]
        assert [r["accuracy"] for r in rounds] == [0.5, 1.0, 1.0]
        assert [r["baseline"] for r in rounds] == [0.0, 0.5, 1.0]
        assert rounds[0]["edits"] and rounds[0]["edits"][-1]["status"] == "applied"
        assert rounds[2]["edits"] == [], "全对轮应跳过编辑"
        records = json.loads((Path(directory) / "edit_records.json").read_text(encoding="utf-8"))
        assert [r["round"] for r in records] == [1, 2, 3]
        assert records[0]["session"] == "dcn-test" and records[0]["task_ids"] == ALL_CASES
        assert records[0]["accuracy"] > records[0]["baseline_accuracy"]

    # 回滚路径：评测恒定全错（常量基准，候选再好也不算数）→ 两次尝试均无提升 → 保持基线。
    def flat_evaluator(skill, case_ids=None):
        return fake_evaluator("# 无法覆盖任何用例的内容", case_ids)

    with patch.dict("os.environ", NO_LLM_ENV, clear=False):
        report = dcn_pipeline.run_loop(rounds=1, evaluator=flat_evaluator)
        entry = report["rounds"][0]
        assert len(entry["edits"]) == state_machine.MAX_EDIT_ATTEMPTS
        assert all(edit["status"] == "rolled_back" for edit in entry["edits"])
        assert entry["accuracy"] == entry["baseline"] == 0.0


def check():
    check_parse()
    check_parse_csv()
    check_clients()
    check_skill_edit()
    check_loop()
    print("PASS: eval parser tolerates aliases and accuracy formats; clients degrade without config; "
          "skill edit maps results to trajectories; loop accepts/rolls back/skips and persists records")


if __name__ == "__main__":
    check()
