"""mock 优化流程检查：python -B tests/check_mock.py（只用标准库，零延迟跑四轮）。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from net_skill import mock_optimizer
from net_skill.mock_optimizer import agent, editor, faults
from net_skill.pipeline import catalog, generate_events, resolve_skill

BASE_SKILL = "# 网络故障定位 Skill\n\n## 步骤\n1. 收集告警。\n2. 检查链路。\n3. 输出结论。\n"


async def collect(round_number, skill):
    zero = dict.fromkeys(mock_optimizer.DELAYS, 0)
    return [event async for event in mock_optimizer.optimize("网络故障定位", skill, round_number, delays=zero)]


def check():
    skill = BASE_SKILL
    for round_number in range(1, 5):
        events = asyncio.run(collect(round_number, skill))
        progresses, final = [e for e in events if isinstance(e, dict)], events[-1]
        # 契约：五个阶段各先 running 后 completed，最后一项是优化后的完整 Markdown。
        for step in range(1, 6):
            statuses = [e["status"] for e in progresses if e.get("step") == step]
            assert statuses == ["running", "completed"], (round_number, step, statuses)
        assert isinstance(final, str) and final.startswith(skill.rstrip()), round_number
        # 注入说明、轨迹内容与恢复说明来自本轮轮换到的故障。
        fault = faults.pick(round_number)
        assert fault["name"] in progresses[1]["content"], round_number
        trace = progresses[5]["content"]
        assert "受阻" in trace and fault["gap"] in trace, round_number
        assert "恢复" in progresses[7]["content"], round_number
        # 每轮把缺口补成处理指引，Skill 只增不减。
        assert f"第 {round_number} 轮优化 · {fault['name']}故障处理" in final, round_number
        skill = final
    # 故障按轮次轮换，走完一圈回到第一种。
    assert faults.pick(len(faults.FAULTS) + 1)["name"] == faults.pick(1)["name"]
    # 训练样本字段映射：注入意图取名、设备为范围、gold_answer 为期望根因。
    sample = {"id": "t1", "question": "叶子交换机 vxlan 告警", "gold_answer": "接口 down",
              "inject_intent": "在组网中注入接口down的故障", "inject_device": "em5_serverleaf2"}
    converted = faults.from_sample(sample)
    assert converted["name"] == "接口down" and converted["scope"] == "em5_serverleaf2"
    assert converted["root_cause"] == "接口 down" and "接口 down" in converted["gap"]
    # 没有编号步骤的 Skill 也能完成分析并编辑。
    sparse = "# 只有描述的 Skill\n\n没有步骤。\n"
    analysis = agent.analyze(sparse, faults.FAULTS[0])
    assert "0 个步骤" in analysis["trace"]
    assert sparse in editor.revise(sparse, 1, faults.FAULTS[0], analysis)
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
    print("PASS: mock optimizer rotates faults, per-step progress, trace exposes gap, skill grows each round; skill catalog resolves")


if __name__ == "__main__":
    check()
