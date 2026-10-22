"""每次编辑完 Skill 后同步到远程 opencode 服务器，保证 opencode 服务启动运维任务时
能调用最新编辑后的 Skill（HTTP 接口）。

连接配置（环境变量）：
- OPENCODE_UPLOAD_URL：上传接口完整地址（如 http://opencode-server:9000/api/skills），
  未配置时跳过同步（本机闭环照常运行）。
- OPENCODE_API_KEY：可选鉴权，配置后以 Authorization: Bearer 头发送。
- OPENCODE_TIMEOUT：请求超时秒数，默认 30。

TODO: 请求体字段名（skill_name / content）与响应结构按 opencode 服务的真实接口调整。
"""
import json
import os
import urllib.error
import urllib.request


def settings() -> dict:
    """读取上传配置；upload_url 未配置视为不可用。"""
    return {
        "upload_url": os.environ.get("OPENCODE_UPLOAD_URL", "").strip(),
        "api_key": os.environ.get("OPENCODE_API_KEY", "").strip(),
        "timeout": float(os.environ.get("OPENCODE_TIMEOUT", "").strip() or 30),
    }


def available() -> bool:
    """是否已配置上传地址。"""
    return bool(settings()["upload_url"])


def upload_skill(skill: str, skill_name: str = "network-fault-diag") -> None:
    """把最新 Skill 内容推送到远程 opencode 服务器；失败抛 RuntimeError（由上层决定是否阻断）。"""
    config = settings()
    if not config["upload_url"]:
        return  # 未配置：跳过同步
    payload = {"skill_name": skill_name, "content": skill}
    request = urllib.request.Request(config["upload_url"],
                                      data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST")
    request.add_header("Content-Type", "application/json")
    if config["api_key"]:
        request.add_header("Authorization", f"Bearer {config['api_key']}")
    try:
        with urllib.request.urlopen(request, timeout=config["timeout"]) as response:
            response.read()
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Skill 同步失败（HTTP {error.code}）：{config['upload_url']}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Skill 同步连接失败：{config['upload_url']}（{error.reason}）") from error
