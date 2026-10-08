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

在 `pipeline.py` 顶部的接入区替换两个函数（同步或 `async` 均可，返回完整 Markdown 字符串）：

- `generate_skill(intent)` — 点击「生成 Skill」时调用，产出初始版本 V0。
- `optimize_skill(intent, skill, round_number)` — 点击「优化 Skill」时调用；`skill` 是当前最新版本内容，`round_number` 从 1 开始，每点击一次加一。

## 文件

- `pipeline.py`：接入你的 Skill 生成和优化逻辑。
- `history/`：每次生成一个文件夹，保存意图、事件流和各版本 `.md`。
- 页面可以查看历史、切换版本、下载 Skill，以及确认后删除记录。

关闭页面不会停止后台任务；关闭后端会停止执行，但已保存的记录仍保留。
