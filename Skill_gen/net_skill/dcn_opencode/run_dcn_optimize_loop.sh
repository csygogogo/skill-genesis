#!/bin/sh
# 启动 agent 运维任务对接评测平台迭代优化 skill。
# 外部服务用环境变量配置（见各模块 docstring）：
#   POLARIS_BASE_URL / POLARIS_API_KEY   评测平台（未配置走本机 mock 演练评测）
#   OPENCODE_UPLOAD_URL / OPENCODE_API_KEY  Skill 同步（未配置跳过）
#   ARK_API_KEY / SKILL_LLM_MODEL        大模型编辑（未配置走规则编辑）
# 用法：./run_dcn_optimize_loop.sh [--rounds 3] [--cases diag_001] [--session dcn-cli]
cd "$(dirname "$0")/../.." || exit 1
if [ -n "$PYTHON" ]; then :
elif [ -x ".venv/Scripts/python.exe" ]; then PYTHON=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then PYTHON=".venv/bin/python"
else PYTHON="python"; fi
PYTHONUTF8=1 "$PYTHON" -m net_skill.dcn_opencode.dcn_pipeline "$@"
