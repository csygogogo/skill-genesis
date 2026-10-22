# Changelog

记录 Skill Studio 的每次修改，新的在最上面。日期为提交当日。

## 2026-10-22 · dcn_opencode 真实优化闭环

### 新增

- `net_skill/dcn_opencode/` 七个模块补齐实现（对接评测平台与 opencode 服务的真实闭环，外部服务未配置时自动降级到本机可跑路径）：
  - `polaris_client.py`：Polaris 评测平台 HTTP 客户端，两个接口——启动 agent 评测任务、获取评测结果与轨迹（结果为 CSV，含准确率；环境变量配置连接，接口字段按通用 REST 假设并标注 TODO）。
  - `eval_parse.py`：agents 结果容错解析——CSV（中文 / 英文表头别名、分隔符嗅探、引号内换行轨迹、BOM）与 JSON 两种输入统一入口（case / question / answer / 准确率 / 轨迹，0–1 / 0–100 / 百分号归一）。
  - `upload_skill_dcn.py`：编辑后的 Skill 经 HTTP 同步到远程 opencode 服务器（未配置或失败不阻断闭环）。
  - `skill_edit.py`：具体编辑——评测结果映射为运维轨迹（带训练集故障快照），选最差 case 交 skill_editor 编辑；渲染 prompts 里的优化分析 prompt。
  - `prompts/skill_optimize_analysis.txt`：逐 case 的归因 / 修改建议 / 影响面分析 prompt。
  - `dcn_pipeline.py`：闭环编排（上传 → 评测 → 解析 → 编辑 → 严格上升才接受，否则回滚重编辑 → 同步，循环），支持 `python -m` 与评测函数注入。
  - `run_dcn_optimize_loop.sh`：命令行启动入口（自动选 venv Python）。
- `tests/check_dcn.py`：解析容错、客户端降级、轨迹映射与分析 prompt、闭环接受 / 回滚 / 跳过与记录落盘。

## 2026-10-22 · 目录按领域分包

### 调整

- `net_skill/` 按领域分包：原外层的 skill 优化代码（pipeline / state_machine / mock_optimizer / skill_editor / data / skills）整体迁入 `net_skill/dcn_opencode/`（DCN 领域）；新增 `net_skill/ci_hummingbrid/` 占位（CI 领域，待接入）。
- `app.py` 与测试的接入路径改为 `net_skill.dcn_opencode.pipeline`；`state_machine` 的编辑记录仍写到项目根 `output/edit_records.json`（多领域共用，路径深度随包层级修正）。

## 2026-10-22

### 新增

- `net_skill/state_machine.py` 评测驱动的 skill 优化状态机：基线评测（当前 Skill 在全部勾选用例上的准确率与轨迹）→ 编辑候选 → 评测候选 → 准确率严格上升才接受；相等或下降回滚候选并重新编辑（上限 2 次尝试），仍无提升则保持基线版本；基线满分时跳过编辑并说明。阶段从 6 个调整为 7 个（注入故障 / 基线评测 / 编辑 Skill / 评测候选 / 接受-回滚 / 故障恢复 / 返回），编辑、评测、决策三个阶段在回滚重试时重复 running→completed，前端零改动适配。
- `mock_optimizer/agent.py` 新增评测器：`covered`（正文含期望根因，或故障名与设备同时出现；剥 frontmatter 防止 description 误判）、`run_case` / `evaluate`（覆盖用例得出根因 correct，未覆盖受阻 incorrect，accuracy = 判对数/总数）。
- 每轮优化把真实结果追加写入 `output/edit_records.json`：新增 `baseline_accuracy` 字段，edits 状态扩展 `rolled_back`（已回滚）；写入为临时文件 + 原子替换，文件损坏时自动重建，可用环境变量 `SKILL_EDIT_RECORDS` 重定向。编辑记录面板新增「已回滚」状态徽章。
- 未接入大模型时第 1 次编辑尝试使用演练弱草稿（不含根因的泛化章节），用于确定性演示「回滚 → 重新编辑 → 接受」路径；接入后由真实大模型输出交评测器裁决，重试时 `retry_note` 提示明确覆盖设备与根因。

### 调整

- `mock_optimizer/__init__.py` 移除旧线性流程（由 state_machine 取代）；`pipeline.OPTIMIZE_STEPS` / `EDIT_RECORDS_FILE` 改为引用 state_machine 常量；`optimize_skill` / `optimize_events` 新增 `session_id` 参数（app.py 传入，用于记录落盘）。
- 测试：check_mock 重写为状态机断言（接受轮 / 双回滚轮 / 跳过轮 / 评测器单元 / 记录落盘与容错），check_editor 端到端改经 state_machine（LLM 路径第 1 次尝试即接受），check_backend 断言 7 阶段与编辑记录接口。

## 2026-10-21

### 新增

- `output/edit_records.json` Skill 编辑记录格式（session / round / task_ids / accuracy / generated_at / edit_count / edits[]，每条编辑含 index / op / status / skill_name / references / target / summary / content），并附两轮真实格式的示例记录。
- 界面新增「Skill 编辑记录」面板（`web/src/records.js`）：`GET /api/skills/edit-records` 读取 `output/edit_records.json`，按轮次 tab 展示（用例 / 准确率），点选单条编辑查看详情（操作类型、状态、位置、关联文件、Markdown 渲染的编辑内容）；演示模式下与目录 / 用例面板一同隐藏，支持手动刷新。

## 2026-10-19

### 新增

- 准确率曲线支持从 Excel / CSV 导入（`web/src/sheet.js`）：按钮选择文件或直接把文件拖进面板，解析后自动合并进折线图；列按表头关键字（轮次 / 准确率，支持 round / accuracy）自动识别，无表头时按「前两列数字」回退，单列数值按行序编轮次，0–1 区间数值自动换算为百分比；与已录数据合并时同轮次以导入值为准，无效行忽略并在提示中计数。
- `.xlsx` 解析零第三方依赖：基于浏览器内置 `DecompressionStream`（deflate-raw）与 `DOMParser` 读取 ZIP + XML（含共享字符串表）；CSV 支持引号字段并自动识别逗号 / 分号 / 制表符；旧版 `.xls` 与浏览器缺少所需 API（需 Chrome / Edge 80+ 或 Firefox 113+）时均给出明确的中文提示。
- 界面新增「准确率曲线」面板（`web/src/chart.js`）：横轴为 Skill 优化轮次、纵轴为准确率（0–100%）的原生 SVG 折线图，手动输入「轮次 + 准确率」逐点记录，重复轮次覆盖更新，数据点以 chips 形式列出、可单条删除或清空。
- 折线图交互：十字线随指针吸附最近轮次并联动 tooltip（值为主、标签为辅），终点数值直接标注；数据保存在浏览器 localStorage（`skill-studio-accuracy`），刷新不丢失。

## 2026-10-17

### 新增

- `net_skill/skill_editor/` skill 编辑 agent 模块：输入运维轨迹（用了哪个 Skill、按步骤调了哪些工具及成败、最终结论与期望根因比对的对错判定），优先接火山方舟大模型（openai SDK；环境变量 `ARK_API_KEY`、`SKILL_LLM_MODEL`，可选 `ARK_BASE_URL`、`SKILL_LLM_TIMEOUT`，见模块 docstring）分析轨迹并编辑 Skill；未安装 openai、未配置凭证或调用 / 输出校验失败时自动回退规则编辑，`python app.py` 开箱可跑。
- `tests/check_editor.py`：覆盖轨迹契约、对错判定、两种渲染、prompt 构造、输出校验、规则回退与注入假客户端的引擎选择，零网络零外部依赖。

### 调整

- 第 3 步「定位与分析」升级为产出结构化运维轨迹（含工具调用序列与 correct / incorrect 判定），界面轨迹文本新增工具名与结果判定行。
- 第 5 步「编辑优化 Skill」改由 skill_editor 编辑 agent 完成，完成后说明本次用的编辑引擎（火山方舟大模型 / 回退规则编辑）。
- `mock_optimizer/editor.py` 移除，规则编辑平移至 `skill_editor/fallback.py`（入参从故障字典换成运维轨迹）；`requirements.txt` 新增 `openai>=1.30`；`tests/check_mock.py` 清空大模型环境变量保证确定性，断言同步更新。

## 2026-10-13

### 新增

- 界面支持勾选优化用例：`GET /api/skills/cases` 列出 `data/train_data.json` 训练样本；「优化 Skill」请求携带 `cases`（用例 id 列表），每轮只在勾选的用例中轮换，选择记录在会话里。
- 意图面板新增「优化用例」折叠多选列表（样本 id、现象摘要、期望根因），默认全选并记住上次选择，支持全选 / 清空；未勾选任何用例时阻止优化。

### 调整

- `optimize_skill` / `optimize_events` 增加可选 `case_ids` 参数；`faults.pick` 在选定范围内轮换，无效选择回退全部用例。

## 2026-10-09 · 4344db7

### 新增

- 界面支持选择待优化 Skill：`GET /api/skills/catalog` 列出 `skills/` 目录（frontmatter 的 name/description）；创建会话可带 `skill` 参数并记录在 session 中；意图面板新增下拉选择器，默认选最近生成用过的 Skill，打开历史记录时同步。

### 调整

- `generate_skill(intent, skill_id)` 支持指定 Skill 目录；未指定或不存在时回退第一个。

## 2026-10-09 · 3eb316b

### 新增

- 接入真实数据目录：`net_skill/data/train_data.json` 训练集驱动优化轮次（`question` 现象 / `gold_answer` 期望根因 / `inject_intent`、`inject_device` 注入操作与设备，按轮轮换）；`net_skill/skills/` 下待优化 Skill 作为生成阶段 V0 读入。

### 调整

- 生成阶段不再按意图拼占位 Skill，优先读取 `skills/` 第一个目录的 `SKILL.md`；无待优化 Skill 时回退占位。
- 训练集缺失 / 格式错误 / 为空时，故障库回退内置 4 种场景；样本无 `fix` 字段时恢复阶段按注入操作撤销、编辑阶段使用通用处置动作。
- 测试不再断言「意图出现在 Skill 内容中」，改为校验 V0 结构；新增训练样本字段映射断言。

## 2026-10-09 · d8b632b

### 调整

- 目录重构：UI 界面代码移入 `web/`；新增 `net_skill/` 与 `web/` 同级，存放 Skill 生成与优化逻辑（`pipeline.py`、`mock_optimizer/`）。`app.py` 仍是服务入口，启动命令与页面行为不变。

## 2026-10-09 · 675ac05

### 新增

- 优化流程在「定位与分析」之后新增第 4 阶段「故障恢复」：演练结束恢复注入的故障、环境回到基线；阶段总数从 5 个变为 6 个，前端清单自动适配。
- 新增本 Changelog。

## 2026-10-09 · b9972e0

### 新增

- 优化阶段清单显示每个阶段的真实耗时（`running` 起表、`completed`/`failed` 结算），在 `pipeline.py` 包装层计时，接入真实实现后即为真实耗时。

### 调整

- 主界面去掉 1600px 宽度上限，生成过程与 Skill 预览铺满侧栏以外的整个窗口。

## 2026-10-09 · 6b79f58

### 新增

- `mock_optimizer/`：skill 优化的 mock 演练流程——故障注入（4 种网络故障按轮轮换）→ 发送请求给 Agent → 故障分析（加载当前 Skill 产出执行轨迹与缺口）→ 编辑并返回优化后的 Skill。
- `tests/check_mock.py`：零延迟驱动多轮，校验进度契约、故障轮换与 Skill 逐轮增长。

### 调整

- `pipeline.py` 的 `optimize_skill` 委托 mock 流程；接入契约不变，替换 `mock_optimizer` 内模块即可接真实环境。

## 2026-10-09 · c27ad58

### 新增

- 优化流程阶段化实时进度事件（`optimize_step`）：时间线渲染步骤清单（等待 ○ / 优化中 spinner / 完成 ✓ / 失败 ×），状态栏显示当前阶段与轮次，新增「优化进度」筛选。
- `optimize_skill` 接入契约升级：逐阶段 `yield` 进度、最后 `yield` 优化后的完整 Markdown；兼容旧的直接返回字符串写法。

### 修复

- 前端 `watch` 收到上一轮遗留的 `done` 事件即提前退出，导致点击「优化 Skill」无反应、优化期间重复点击报 409、历史回放只能看到第一轮。

### 调整

- 阶段条显示不再被子图 / 执行轨迹事件误刷。

## 2026-10-08 · 7b0821d

### 调整

- Skill Studio 改为分步交互：先生成初始 Skill，之后每点击一次「优化 Skill」跑一轮；`pipeline.py` 顶部提供生成 / 优化函数接入区。

## 2026-10-08 · 2f5c016

- 初始代码。
