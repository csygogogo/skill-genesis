"""故障库与注入：每轮按序号轮换一种网络故障，模拟实际网络环境中的故障注入。"""


# 每种故障：现象（发给 Agent 的材料）、范围、根因、处置动作、当前 Skill 暴露的缺口。
FAULTS = (
    {
        "name": "链路丢包",
        "symptom": "核心交换机到接入交换机的链路丢包 30%，业务侧出现间歇性超时",
        "scope": "core-01 ↔ access-07 互联链路",
        "root_cause": "光模块老化导致误码率升高，触发链路丢包",
        "fix": "切换到备用链路并替换光模块，观察误码率回归正常",
        "gap": "链路质量类故障的定位手段（逐跳丢包统计与光模块误码检查）",
    },
    {
        "name": "BGP 邻居中断",
        "symptom": "出口路由器与上游运营商的 BGP 邻居频繁翻动，部分网段路由丢失",
        "scope": "border-02 ↔ 运营商 PE 设备",
        "root_cause": "TCP 会话被中间防火墙空闲超时回收，Keepalive 未及时续接",
        "fix": "调整 BGP keepalive/hold 时间并在防火墙上放行长会话",
        "gap": "邻居状态翻动场景的排查顺序（先查会话再查策略）",
    },
    {
        "name": "端口 Down",
        "symptom": "机房汇聚交换机多个业务端口同时 Down，下联服务器批量失联",
        "scope": "aggre-01 的 ge-0/0/1 至 ge-0/0/8",
        "root_cause": "端口所属 VLAN 在上游被误删除，MAC 表项全部失效",
        "fix": "恢复 VLAN 配置并确认端口重新学习到 MAC 地址",
        "gap": "批量端口异常时先查配置变更再查硬件的判断依据",
    },
    {
        "name": "DNS 解析失败",
        "symptom": "办公网访问内部系统域名解析失败，直接用 IP 访问正常",
        "scope": "办公网终端 → 内部 DNS 集群",
        "root_cause": "主 DNS 服务器区域文件损坏，备 DNS 未同步该区域",
        "fix": "回滚区域文件并强制主备同步，验证解析恢复",
        "gap": "域名类故障与链路类故障的区分判断（先做域名/IP 对比验证）",
    },
)


def pick(round_number: int) -> dict:
    """按轮次轮换故障场景：每轮优化演练一种不同的故障。"""
    return FAULTS[(round_number - 1) % len(FAULTS)]


def inject(fault: dict) -> str:
    """第 1 步：在实际网络环境（mock）中注入故障，返回注入说明。"""
    return f"已在 {fault['scope']} 注入「{fault['name']}」故障：{fault['symptom']}。"


def recover(fault: dict) -> str:
    """第 4 步：演练结束后恢复注入的故障，环境回到基线。"""
    return f"已恢复「{fault['name']}」故障：{fault['fix']}；{fault['scope']} 回到基线，告警清除。"


def symptoms(fault: dict) -> dict:
    """第 2 步的请求体：把告警现象与拓扑范围整理成发给 Agent 的材料。"""
    return {
        "fault": fault["name"],
        "alarm": fault["symptom"],
        "scope": fault["scope"],
        "materials": ["实时告警列表", "当前拓扑与链路状态", "最近 30 分钟变更记录"],
    }
