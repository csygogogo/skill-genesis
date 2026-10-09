# Changelog

记录 Skill Studio 的每次修改，新的在最上面。日期为提交当日。

## 2026-10-09

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
