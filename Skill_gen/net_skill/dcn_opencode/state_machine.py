"""评测驱动的 skill 优化状态机。

每轮循环：注入故障 → 基线评测（当前 Skill 在全部勾选用例上的准确率与轨迹）→
编辑 Skill（候选）→ 评测候选 → 准确率严格上升才接受；相等或下降回滚候选并重新
编辑（MAX_EDIT_ATTEMPTS 次），仍无提升则保持基线版本。每轮把真实结果追加写入
output/edit_records.json（status 含 applied / rolled_back）。

阶段契约与原 mock_optimizer 相同：逐阶段 yield {"step", "status", "content"}，
编辑 / 评测 / 决策三个阶段在重试时重复 running→completed，最后 yield 最终 Markdown
（接受的候选；无提升时为基线版本）。
"""
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from . import skill_editor
from .mock_optimizer import agent, faults
from .skill_editor.llm import available as llm_available

# 第 1 次草稿 + 第 2 次修正；仍无提升则保持基线版本。
MAX_EDIT_ATTEMPTS = 2

# 状态机的七个阶段，按序实时展示在前端；3/4/5 在重试时重复进入。
STATES = (
    "注入故障",             # 1. 在实际网络环境中注入本轮故障
    "基线评测",             # 2. 当前 Skill 在全部勾选用例上评测：发送现象 + 收集轨迹与准确率
    "编辑 Skill",           # 3. 根据轨迹编辑候选版本（可重入：第 1/2 次尝试）
    "评测候选",             # 4. 候选版本在全部勾选用例上评测（可重入）
    "接受 / 回滚",          # 5. 准确率严格上升 → 接受；否则回滚并重试 / 保持基线（可重入）
    "故障恢复",             # 6. 演练结束，恢复注入的故障，环境回到基线
    "返回优化后的 Skill",   # 7. pipeline 包装层收尾自动标记完成
)

# 各阶段模拟耗时（秒）；测试时可整体传 0。
DELAYS = {"inject": 1.5, "evaluate": 1.2, "revise": 1.5, "decide": 0.3, "recover": 1.0}

# 每轮优化结果落盘位置（项目根 output/，多领域共用一个文件）；环境变量可重定向（测试用）。
RECORDS_FILE = Path(os.environ.get("SKILL_EDIT_RECORDS")
                    or Path(__file__).resolve().parent.parent.parent / "output" / "edit_records.json")


def weak_draft(skill: str, round_number: int) -> str:
    """演练设定（仅未接入大模型时的第 1 次尝试）：追加不含故障名 / 设备 / 根因的泛化章节，
    评测必然无提升，用于演示「回滚 → 重新编辑 → 接受」路径；接入真实大模型后不经过此处。"""
    section = (f"## 第 {round_number} 轮优化 · 通用排查指引\n\n"
               "1. 识别现象：整理告警与日志。\n"
               "2. 缩小范围：检查设备状态与最近变更。\n"
               "3. 根因确认：结合工具结果收敛。\n"
               "4. 处置动作：按根因处置。\n"
               "5. 验证恢复：复核告警清除。\n")
    return f"{skill.rstrip()}\n\n{section}"


def delta_section(baseline: str, candidate: str, round_number: int) -> str:
    """提取候选相对基线新增的章节文本（编辑记录的 content）。"""
    if candidate.startswith(baseline.rstrip()):
        return candidate[len(baseline.rstrip()):].strip()
    marker = f"## 第 {round_number} 轮优化"
    position = candidate.find(marker)
    return candidate[position:].strip() if position >= 0 else candidate.strip()


def _picked_trajectory(evaluation: dict, fault: dict) -> dict:
    """从评测结果里取出本轮编辑目标故障对应的轨迹（优先按用例 id 匹配）。"""
    for item in evaluation["trajectories"]:
        if item["case"] and item["case"] == fault.get("case"):
            return item
    for item in evaluation["trajectories"]:
        if (item.get("fault") or {}).get("name") == fault.get("name"):
            return item
    return evaluation["trajectories"][0]


def build_record(session_id, round_number, pool, baseline, final_eval, edits) -> dict:
    """构造一轮优化的编辑记录；edits 条目见 output/edit_records.json 契约。"""
    return {
        "session": session_id,
        "round": round_number,
        "task_ids": [fault.get("case", "") for fault in pool if fault.get("case")],
        "accuracy": final_eval["accuracy"],
        "baseline_accuracy": baseline["accuracy"],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "edit_count": len(edits),
        "edits": edits,
    }


def _edit_entry(attempt, candidate, baseline_accuracy, candidate_accuracy, improved, skill, round_number) -> dict:
    """单次编辑尝试的记录条目。"""
    content = delta_section(skill, candidate["content"], round_number)
    heading = next((line for line in content.splitlines() if line.startswith("## ")), "")
    accepted = "严格上升，已接受生效" if improved else "未提升，已回滚"
    note = "，演练设定弱草稿" if candidate.get("draft") else ""
    return {
        "index": attempt,
        "op": "append_section",
        "status": "applied" if improved else "rolled_back",
        "skill_name": agent.skill_name(skill),
        "references": [f"skills/{agent.skill_name(skill)}/SKILL.md"],
        "target": heading or f"第 {round_number} 轮优化",
        "summary": (f"第 {attempt} 次编辑尝试（{candidate.get('engine', 'fallback')}）："
                    f"候选准确率 {baseline_accuracy:.2f} → {candidate_accuracy:.2f}，{accepted}{note}。"),
        "content": content,
    }


def append_record(record: dict) -> None:
    """把一条记录追加进 edit_records.json；文件缺失 / 损坏时从头重建，临时文件原子替换。"""
    try:
        data = json.loads(RECORDS_FILE.read_text(encoding="utf-8"))
        records = data if isinstance(data, list) else []
    except (OSError, ValueError):
        records = []
    records.append(record)
    RECORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = RECORDS_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, RECORDS_FILE)


async def optimize(intent: str, skill: str, round_number: int, case_ids=None,
                   editor_client=None, session_id: str = "", delays: dict = None):
    """状态机主流程：契约与 pipeline 对接（进度 dict + 最终 Markdown 字符串）。

    case_ids 是界面勾选的训练用例（评测与轮换范围）；session_id 非空时落盘编辑记录；
    editor_client 可注入测试用的大模型假客户端。
    """
    pacing = {**DELAYS, **(delays or {})}
    pool = faults.pool(case_ids)                 # 评测范围：全部勾选用例
    fault = faults.pick(round_number, case_ids)  # 编辑目标：本轮轮换到的故障
    use_llm = editor_client is not None or llm_available()

    yield {"step": 1, "status": "running", "content": "正在实际网络环境中注入故障…"}
    await asyncio.sleep(pacing["inject"])
    yield {"step": 1, "status": "completed", "content": faults.inject(fault)}

    # 基线评测：把 N 个勾选用例的现象逐个发给 Agent，收集轨迹与准确率。
    yield {"step": 2, "status": "running",
           "content": f"正在把 {len(pool)} 个勾选用例的故障现象逐个发送给 Agent，评测当前 Skill 的基线准确率…"}
    await asyncio.sleep(pacing["evaluate"])
    baseline = agent.evaluate(skill, pool)
    yield {"step": 2, "status": "completed",
           "content": baseline["trace"] + f"\n基线准确率 {baseline['covered']}/{baseline['total']} = {baseline['accuracy']:.2f}"}

    edits, final, final_eval = [], skill, baseline

    if baseline["accuracy"] >= 1:
        # 无提升空间：跳过编辑 / 评测 / 决策，保持每阶段 running→completed 契约。
        for step, title, note in ((3, "编辑 Skill", "基线已全部答对，本轮跳过编辑。"),
                                  (4, "评测候选", "无编辑产生，跳过候选评测。"),
                                  (5, "接受 / 回滚", "基线已是最高准确率，本轮保持当前版本。")):
            yield {"step": step, "status": "running", "content": f"{title}：{note}"}
            yield {"step": step, "status": "completed", "content": note}
    else:
        trajectory = _picked_trajectory(baseline, fault)
        for attempt in range(1, MAX_EDIT_ATTEMPTS + 1):
            # 编辑候选：未接入大模型时第 1 次尝试用弱草稿（演练设定，演示回滚路径）。
            yield {"step": 3, "status": "running",
                   "content": f"第 {attempt}/{MAX_EDIT_ATTEMPTS} 次编辑尝试：编辑 agent 正在根据执行轨迹优化 Skill…"}
            await asyncio.sleep(pacing["revise"])
            if not use_llm and attempt == 1:
                candidate = {"content": weak_draft(skill, round_number), "engine": "fallback", "draft": True,
                             "note": "演练设定：第 1 次尝试使用不含根因的弱草稿，演示回滚路径。"}
            else:
                retry_note = "" if attempt == 1 else (
                    "上一次候选未带来准确率提升，请确保新增内容明确覆盖故障设备 "
                    f"{fault.get('scope', '')} 与期望根因：{trajectory['expected']}。")
                candidate = await skill_editor.revise(skill, round_number, trajectory,
                                                      client=editor_client, retry_note=retry_note)
            yield {"step": 3, "status": "completed",
                   "content": f"第 {attempt}/{MAX_EDIT_ATTEMPTS} 次尝试 · {candidate['note']}"}

            # 评测候选：仍在全部勾选用例上评测，与基线同口径。
            yield {"step": 4, "status": "running",
                   "content": f"正在全部 {len(pool)} 个勾选用例上评测第 {attempt} 次编辑候选…"}
            await asyncio.sleep(pacing["evaluate"])
            candidate_eval = agent.evaluate(candidate["content"], pool)
            yield {"step": 4, "status": "completed",
                   "content": candidate_eval["trace"]
                   + f"\n候选准确率 {candidate_eval['covered']}/{candidate_eval['total']} = {candidate_eval['accuracy']:.2f}"}

            # 接受 / 回滚：准确率严格上升才接受。
            yield {"step": 5, "status": "running", "content": "正在比对基线与候选准确率，做出接受 / 回滚决策…"}
            await asyncio.sleep(pacing["decide"])
            improved = candidate_eval["accuracy"] > baseline["accuracy"]
            edits.append(_edit_entry(attempt, candidate, baseline["accuracy"],
                                     candidate_eval["accuracy"], improved, skill, round_number))
            comparison = (f"准确率 {baseline['accuracy']:.2f} → {candidate_eval['accuracy']:.2f}")
            if improved:
                final, final_eval = candidate["content"], candidate_eval
                yield {"step": 5, "status": "completed",
                       "content": f"{comparison}（严格上升）：接受候选，本轮优化生效。"}
                break
            verdict = (f"进入第 {attempt + 1}/{MAX_EDIT_ATTEMPTS} 次编辑尝试。"
                       if attempt < MAX_EDIT_ATTEMPTS
                       else f"{MAX_EDIT_ATTEMPTS} 次编辑尝试均无提升，本轮保持基线版本。")
            yield {"step": 5, "status": "completed",
                   "content": f"{comparison}（未严格上升）：回滚候选，{verdict}"}

    yield {"step": 6, "status": "running", "content": "正在实际网络环境中恢复故障…"}
    await asyncio.sleep(pacing["recover"])
    yield {"step": 6, "status": "completed", "content": faults.recover(fault)}

    if session_id:
        try:
            append_record(build_record(session_id, round_number, pool, baseline, final_eval, edits))
        except Exception as error:  # 落盘失败不阻断优化流程。
            print(f"警告：编辑记录写入失败（{error}）")

    yield final
