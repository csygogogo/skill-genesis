# Skill Studio

## 启动

在已安装依赖的 Python 环境中运行：

```sh
python app.py
```

页面和后端一起启动。本机打开 http://127.0.0.1:8000 ，同一局域网的设备打开 `http://这台电脑的IP:8000`。

第一次使用、尚未安装依赖时：

```sh
pip install --no-compile -r requirements.txt
```

## 接入你的生成 / 优化函数

在 `net_skill/pipeline.py` 顶部的接入区替换两个函数（同步或 `async` 均可，返回完整 Markdown 字符串）：

- `generate_skill(intent, skill_id)` — 点击「生成 Skill」时调用：读取 `net_skill/skills/` 下界面选中的待优化 Skill 的 `SKILL.md` 作为初始版本 V0；未指定或不存在时取第一个，没有待优化 Skill 时按意图生成占位版本。
- `optimize_skill(intent, skill, round_number)` — 点击「优化 Skill」时调用；`skill` 是当前最新版本内容，`round_number` 从 1 开始，每点击一次加一。
  - 逐阶段写法（推荐）：改成生成器，按 `OPTIMIZE_STEPS` 的序号逐阶段 `yield {"step": 1, "status": "running", "content": "可选说明"}`，每个阶段先 running、结束时再 completed；界面会实时显示各阶段进度（优化中…），全部结束后再 `yield` 优化后的完整 Markdown 字符串。
  - 整体写法：普通函数 / 协程直接返回完整 Markdown，界面只显示「优化中」，完成后展示新版本。

## 文件

- `web/`：UI 界面代码（`index.html`、`styles.css`、`config.js`、`src/`）。
- `net_skill/`：Skill 生成与优化逻辑，与 `web/` 同级；`pipeline.py` 是接入入口，`mock_optimizer/` 是当前接入的演练流程（故障注入 → 发送请求 → 故障分析 → 故障恢复 → 编辑并返回）。`data/train_data.json` 是训练集（`question` 故障现象、`gold_answer` 期望根因、`inject_intent` / `inject_device` 注入操作与设备），优化轮次按轮换使用；`skills/` 下放待优化的 Skill（生成阶段作为 V0 读入）。
- `app.py`：FastAPI 服务入口，托管 `web/` 界面并调用 `net_skill/` 的逻辑；`storage.py` 是历史记录存储。
- `CHANGELOG.md`：每次修改的更新日志。
- `history/`：每次生成一个文件夹，保存意图、事件流和各版本 `.md`。
- 页面可以选择待优化 Skill（`GET /api/skills/catalog` 列出，默认选最近生成用过的），查看历史、切换版本、下载 Skill，以及确认后删除记录。

关闭页面不会停止后台任务；关闭后端会停止执行，但已保存的记录仍保留。
