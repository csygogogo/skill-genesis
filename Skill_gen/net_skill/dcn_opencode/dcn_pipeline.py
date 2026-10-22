"""DCN 领域真实优化闭环：上传 Skill → 对接评测平台（Polaris）跑 agent 运维任务 →
解析结果与轨迹 → 分析并编辑 Skill → 准确率严格上升才接受（否则回滚重编辑）→
同步最新 Skill 到 opencode 服务器，循环指定轮数。

外部服务未配置时自动降级，闭环可在本机完整跑通：
- 评测：配置 POLARIS_BASE_URL 走真实平台，否则用 mock_optimizer 的演练评测
  （覆盖判断基于 data/train_data.json 的用例与 gold_answer）。
- 同步：配置 OPENCODE_UPLOAD_URL 走真实上传，否则跳过。
- 编辑：配置 ARK_API_KEY / SKILL_LLM_MODEL 走火山方舟大模型，否则规则编辑。

用法：
    python -m net_skill.dcn_opencode.dcn_pipeline [--rounds 3] [--skill network-fault-diag]
                                                  [--cases diag_001,diag_002] [--session dcn-cli]
"""
import argparse
from datetime import datetime

from . import eval_parse, polaris_client, skill_edit, state_machine, upload_skill_dcn
from .mock_optimizer import agent, faults
from .pipeline import SKILLS_DIR, resolve_skill
from .skill_editor.trajectory import render_trace


def load_skill(skill_id: str = "") -> str:
    """读取 skills/ 下待优化的 Skill 作为起始版本 V0。"""
    chosen = resolve_skill(skill_id)
    if not chosen:
        raise RuntimeError("skills/ 下没有待优化的 Skill")
    return (SKILLS_DIR / chosen / "SKILL.md").read_text(encoding="utf-8")


def evaluate_mock(skill: str, case_ids=None) -> dict:
    """降级评测：mock 演练（覆盖 → correct），结果映射为与平台一致的 items 结构。"""
    pool = faults.pool(case_ids)
    items = []
    for trajectory in agent.evaluate(skill, pool)["trajectories"]:
        correct = trajectory["verdict"] == "correct"
        items.append({
            "case": trajectory["case"],
            "question": (trajectory.get("fault") or {}).get("symptom", ""),
            "answer": trajectory["final_answer"],
            "expected": trajectory["expected"],
            "accuracy": 1.0 if correct else 0.0,
            "trace": render_trace(trajectory),
        })
    return {"accuracy": eval_parse.summarize(items)["accuracy"], "items": items}


def evaluate_polaris(skill: str, case_ids=None) -> dict:
    """真实评测：提交任务 → 拉取 agents 结果 → 容错解析 → 汇总准确率。"""
    task_id = polaris_client.submit_evaluation(skill, resolve_skill(""), case_ids)
    items = eval_parse.parse_agents(polaris_client.fetch_results(task_id))
    if not items:
        raise RuntimeError(f"Polaris 任务 {task_id} 没有返回可解析的 agents 结果")
    return {"accuracy": eval_parse.summarize(items)["accuracy"], "items": items}


def default_evaluator(skill: str, case_ids=None) -> dict:
    """评测入口：优先真实平台，未配置时降级 mock。"""
    if polaris_client.available():
        return evaluate_polaris(skill, case_ids)
    return evaluate_mock(skill, case_ids)


def sync_skill(skill: str) -> str:
    """把最新 Skill 同步到远程 opencode 服务器；未配置 / 失败都不阻断闭环，返回说明。"""
    if not upload_skill_dcn.available():
        return "未配置 OPENCODE_UPLOAD_URL，跳过同步"
    try:
        upload_skill_dcn.upload_skill(skill, resolve_skill(""))
        return "已同步到 opencode 服务器"
    except RuntimeError as error:
        return f"同步失败（闭环继续）：{error}"


def _edit_entry(attempt, candidate, baseline_accuracy, candidate_accuracy, improved, skill, round_number) -> dict:
    """单次编辑尝试的记录条目（与 edit_records.json 契约一致）。"""
    content = state_machine.delta_section(skill, candidate["content"], round_number)
    heading = next((line for line in content.splitlines() if line.startswith("## ")), "")
    verdict = "严格上升，已接受生效" if improved else "未提升，已回滚"
    return {
        "index": attempt,
        "op": "append_section",
        "status": "applied" if improved else "rolled_back",
        "skill_name": resolve_skill(""),
        "references": [f"skills/{resolve_skill('')}/SKILL.md"],
        "target": heading or f"第 {round_number} 轮优化",
        "summary": f"第 {attempt} 次编辑尝试（{candidate.get('engine', 'fallback')}）："
                   f"准确率 {baseline_accuracy:.2f} → {candidate_accuracy:.2f}，{verdict}。",
        "content": content,
    }


def run_loop(rounds: int = 3, skill_id: str = "", case_ids=None,
             session_id: str = "", evaluator=None) -> dict:
    """完整优化闭环；返回 {"skill", "accuracy", "rounds": [{round, baseline, accuracy, edits}]}。

    evaluator 可注入测试用评测函数（签名 (skill, case_ids) -> {"accuracy", "items"}）。
    """
    evaluate = evaluator or default_evaluator
    skill = load_skill(skill_id)
    report = {"skill": skill, "rounds": []}
    print(f"起始版本：{len(skill)} 字符 · {sync_skill(skill)}")

    for round_number in range(1, rounds + 1):
        baseline = evaluate(skill, case_ids)
        print(f"\n第 {round_number} 轮 · 基线准确率 {baseline['accuracy']:.2f}（{baseline['items'] and len(baseline['items'])} 个 case）")
        entry = {"round": round_number, "baseline": baseline["accuracy"], "accuracy": baseline["accuracy"], "edits": []}

        if baseline["accuracy"] >= 1:
            print("  基线已全对，本轮跳过编辑。")
        else:
            for attempt in range(1, state_machine.MAX_EDIT_ATTEMPTS + 1):
                retry_note = "" if attempt == 1 else "上一次候选未提升，请确保新增内容明确覆盖目标 case 的设备与期望根因。"
                candidate = skill_edit.edit_skill(skill, round_number, baseline["items"], retry_note=retry_note)
                candidate_accuracy = evaluate(candidate["content"], case_ids)["accuracy"]
                improved = candidate_accuracy > baseline["accuracy"]
                entry["edits"].append(_edit_entry(attempt, candidate, baseline["accuracy"],
                                                  candidate_accuracy, improved, skill, round_number))
                print(f"  第 {attempt} 次编辑（{candidate['engine']}）：{baseline['accuracy']:.2f} → "
                      f"{candidate_accuracy:.2f}，{'接受' if improved else '回滚'} · {candidate['note'][:60]}")
                if improved:
                    skill, entry["accuracy"] = candidate["content"], candidate_accuracy
                    print(f"  {sync_skill(skill)}")
                    break
            else:
                print("  两次编辑均无提升，本轮保持基线版本。")

        report["rounds"].append(entry)
        report["skill"] = skill
        report["accuracy"] = entry["accuracy"]
        if session_id:
            state_machine.append_record({
                "session": session_id, "round": round_number,
                "task_ids": [item["case"] for item in baseline["items"] if item.get("case")],
                "accuracy": entry["accuracy"], "baseline_accuracy": entry["baseline"],
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "edit_count": len(entry["edits"]), "edits": entry["edits"],
            })

    print(f"\n完成 {rounds} 轮 · 最终准确率 {report['accuracy']:.2f} · Skill {len(skill)} 字符")
    return report


def main():
    parser = argparse.ArgumentParser(description="DCN 领域 Skill 优化闭环（对接评测平台与 opencode 服务）")
    parser.add_argument("--rounds", type=int, default=3, help="优化轮数，默认 3")
    parser.add_argument("--skill", default="", help="skills/ 下待优化的 Skill 目录名，默认第一个")
    parser.add_argument("--cases", default="", help="逗号分隔的用例 id，默认全部")
    parser.add_argument("--session", default="", help="会话标识；非空时把编辑记录写入 edit_records.json")
    arguments = parser.parse_args()
    case_ids = [item.strip() for item in arguments.cases.split(",") if item.strip()] or None
    run_loop(rounds=arguments.rounds, skill_id=arguments.skill, case_ids=case_ids, session_id=arguments.session)


if __name__ == "__main__":
    main()
