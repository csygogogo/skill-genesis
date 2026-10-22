"""Polaris 评测平台 HTTP 客户端：两个接口——启动 agent 评测任务、获取 agent 评测结果与轨迹。

连接配置（环境变量）：
- POLARIS_BASE_URL：平台地址（如 http://polaris.example.com），未配置时客户端不可用。
- POLARIS_API_KEY：可选鉴权，配置后以 Authorization: Bearer 头发送。
- POLARIS_SUBMIT_PATH：启动评测任务路径，默认 /api/eval/tasks。
- POLARIS_RESULT_PATH：结果查询路径模板，默认 /api/eval/tasks/{id}/results。
- POLARIS_TIMEOUT：请求超时秒数，默认 30。

结果接口返回 CSV（含轨迹与准确率），fetch_results 返回 CSV 文本，由 eval_parse 解析。
只用标准库 urllib。接口路径与请求 / 响应字段是按通用 REST 形态的假设实现
（见 TODO 标注），拿到真实接口文档后只需调整本文件，上层流程不用动。
"""
import json
import os
import urllib.error
import urllib.request


def settings() -> dict:
    """读取平台连接配置；base_url 未配置视为不可用。"""
    return {
        "base_url": os.environ.get("POLARIS_BASE_URL", "").strip().rstrip("/"),
        "api_key": os.environ.get("POLARIS_API_KEY", "").strip(),
        "submit_path": os.environ.get("POLARIS_SUBMIT_PATH", "").strip() or "/api/eval/tasks",
        "result_path": os.environ.get("POLARIS_RESULT_PATH", "").strip() or "/api/eval/tasks/{id}/results",
        "timeout": float(os.environ.get("POLARIS_TIMEOUT", "").strip() or 30),
    }


def available() -> bool:
    """是否已配置平台地址。"""
    return bool(settings()["base_url"])


def _request(method: str, url: str, payload=None, api_key: str = "", timeout: float = 30, as_text: bool = False):
    """发起请求；as_text=True 返回原始文本（CSV 结果用），否则解析 JSON。非 2xx 抛 RuntimeError。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Accept", "text/csv" if as_text else "application/json")
    if body:
        request.add_header("Content-Type", "application/json")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8-sig")  # 容错 CSV/JSON 带 BOM 的情况
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Polaris 请求失败（HTTP {error.code}）：{url}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Polaris 连接失败：{url}（{error.reason}）") from error
    if as_text:
        return text
    return json.loads(text) if text.strip() else {}


def submit_evaluation(skill: str, skill_name: str, case_ids=None) -> str:
    """接口一：启动 agent 评测任务（平台用指定 Skill 跑运维任务），返回任务 id。

    TODO: 请求体字段名（skill / skill_name / cases）与响应里的任务 id 字段
    （id / task_id / eval_id）按真实文档调整。
    """
    config = settings()
    payload = {"skill": skill, "skill_name": skill_name}
    if case_ids:
        payload["cases"] = list(case_ids)
    result = _request("POST", config["base_url"] + config["submit_path"], payload,
                      api_key=config["api_key"], timeout=config["timeout"])
    for key in ("id", "task_id", "eval_id"):
        if result.get(key):
            return str(result[key])
    raise RuntimeError(f"Polaris 未返回任务 id：{result}")


def fetch_results(task_id: str) -> str:
    """接口二：获取 agent 评测结果与轨迹（CSV 文本，含准确率），由 eval_parse.parse_csv 解析。

    TODO: 结果可能需要轮询任务状态（running → done）后才有；真实文档到位后
    在这里补轮询（间隔与超时用 POLARIS_TIMEOUT 同款配置）。
    """
    config = settings()
    return _request("GET", config["base_url"] + config["result_path"].format(id=task_id),
                    api_key=config["api_key"], timeout=config["timeout"], as_text=True)
