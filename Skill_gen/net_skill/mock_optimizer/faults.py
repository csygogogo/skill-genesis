"""故障来源：优先加载 net_skill/data/train_data.json 训练集，缺失时回退内置场景。

训练样本字段映射：question→故障现象、inject_device→注入范围、gold_answer→期望根因、
inject_intent→注入操作（其中「注入xxx的故障」的 xxx 作为故障名）。
"""
import json
import re
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "train_data.json"

# 内置回退场景：训练集不存在、格式错误或为空时使用，字段含义与训练样本一致。
BUILTIN = (
    {
        "name": "链路丢包",
        "symptom": "核心交换机到接入交换机的链路丢包 30%，业务侧出现间歇性超时",
        "scope": "core-01 ↔ access-07 互联链路",
        "root_cause": "光模块老化导致误码率升高，触发链路丢包",
        "fix": "切换到备用链路并替换光模块，观察误码率回归正常",
        "gap": "链路质量类故障的定位手段（逐跳丢包统计与光模块误码检查）",
        "inject": "在 core-01 与 access-07 之间注入链路丢包",
    },
    {
        "name": "BGP 邻居中断",
        "symptom": "出口路由器与上游运营商的 BGP 邻居频繁翻动，部分网段路由丢失",
        "scope": "border-02 ↔ 运营商 PE 设备",
        "root_cause": "TCP 会话被中间防火墙空闲超时回收，Keepalive 未及时续接",
        "fix": "调整 BGP keepalive/hold 时间并在防火墙上放行长会话",
        "gap": "邻居状态翻动场景的排查顺序（先查会话再查策略）",
        "inject": "在 border-02 与运营商 PE 之间注入 BGP 邻居中断",
    },
    {
        "name": "端口 Down",
        "symptom": "机房汇聚交换机多个业务端口同时 Down，下联服务器批量失联",
        "scope": "aggre-01 的 ge-0/0/1 至 ge-0/0/8",
        "root_cause": "端口所属 VLAN 在上游被误删除，MAC 表项全部失效",
        "fix": "恢复 VLAN 配置并确认端口重新学习到 MAC 地址",
        "gap": "批量端口异常时先查配置变更再查硬件的判断依据",
        "inject": "在 aggre-01 上注入批量端口 Down",
    },
    {
        "name": "DNS 解析失败",
        "symptom": "办公网访问内部系统域名解析失败，直接用 IP 访问正常",
        "scope": "办公网终端 → 内部 DNS 集群",
        "root_cause": "主 DNS 服务器区域文件损坏，备 DNS 未同步该区域",
        "fix": "回滚区域文件并强制主备同步，验证解析恢复",
        "gap": "域名类故障与链路类故障的区分判断（先做域名/IP 对比验证）",
        "inject": "在内部 DNS 集群注入域名解析失败",
    },
)


def from_sample(sample: dict) -> dict:
    """把一条训练样本转换为演练故障；字段见 data/train_data.json。"""
    intent = str(sample.get("inject_intent", ""))
    named = re.search(r"注入(.+?)的故障", intent)
    answer = str(sample.get("gold_answer", ""))
    return {
        "name": named.group(1) if named else str(sample.get("id", "未知故障")),
        "symptom": str(sample.get("question", "")),
        "scope": str(sample.get("inject_device", "组网环境")),
        "root_cause": answer,
        "fix": str(sample.get("fix", "")),  # 训练集可不带修复动作；缺省在恢复阶段按注入操作撤销
        "gap": f"Skill 未覆盖该故障的定位路径（期望根因：{answer}）" if answer else "Skill 未覆盖该故障的定位路径",
        "inject": intent,
    }


def load():
    """读取训练集构建故障列表；文件缺失、解析失败或为空时回退内置场景。"""
    try:
        samples = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return list(BUILTIN)
    converted = [from_sample(item) for item in samples if isinstance(item, dict)]
    return converted or list(BUILTIN)


FAULTS = tuple(load())


def pick(round_number: int) -> dict:
    """按轮次轮换故障场景：每轮优化演练一种不同的故障。"""
    return FAULTS[(round_number - 1) % len(FAULTS)]


def inject(fault: dict) -> str:
    """第 1 步：在实际网络环境（mock）中注入故障，返回注入说明。"""
    action = f"（{fault['inject']}）" if fault.get("inject") else ""
    return f"已在 {fault['scope']} 注入「{fault['name']}」故障{action}：{fault['symptom']}。"


def recover(fault: dict) -> str:
    """第 4 步：演练结束后恢复注入的故障，环境回到基线。"""
    action = fault["fix"] or (f"撤销注入操作：{fault['inject']}" if fault.get("inject") else "清理注入的故障配置")
    return f"已恢复「{fault['name']}」故障：{action}；{fault['scope']} 回到基线，告警清除。"


def symptoms(fault: dict) -> dict:
    """第 2 步的请求体：把告警现象与拓扑范围整理成发给 Agent 的材料。"""
    return {
        "fault": fault["name"],
        "alarm": fault["symptom"],
        "scope": fault["scope"],
        "materials": ["实时告警列表", "当前拓扑与链路状态", "最近 30 分钟变更记录"],
    }
