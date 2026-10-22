"""mock 故障环境与演练 Agent：faults 提供故障库与注入 / 恢复，agent 提供执行与评测。

优化流程（基线评测 → 编辑 → 评测 → 接受 / 回滚）见 net_skill/state_machine.py；
接入真实环境时替换本包内各模块的实现即可，状态机契约保持不变。
"""
