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

## 文件

- `pipeline.py`：接入你的 Skill 生成、优化和执行逻辑。
- `history/`：每次生成一个文件夹，保存意图、执行轨迹和各轮 `.md`。
- 页面可以查看历史、下载 Skill，以及确认后删除记录。

关闭页面不会停止后台任务；关闭后端会停止执行，但已保存的记录仍保留。
