"""跨平台集成检查：python -B tests/check_backend.py（只用标准库）。"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent


def backend_args(directory):
    return ["-c", "import sys; from pathlib import Path; import storage; storage.HISTORY_DIR = Path(sys.argv[1]); import uvicorn; from app import app; uvicorn.run(app, port=int(sys.argv[2]))", str(directory), "{port}"]


def check_server(arguments, check, extra_env=None):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-B", *[arg.replace("{port}", str(port)) for arg in arguments]],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        env={**os.environ, **(extra_env or {})},
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError(process.stderr.read().decode(errors="replace"))
            try:
                with urlopen(base + "/", timeout=1):
                    break
            except HTTPError:
                break  # API-only 服务的根路径返回 404，表示启动完成。
            except URLError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Server startup timed out")
        check(base)
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


def check_static(base):
    for path in ("/", "/styles.css", "/config.js", "/src/app.js", "/src/stream.js", "/src/demo.js"):
        with urlopen(base + path) as response:
            assert response.status == 200, path
            text = response.read().decode("utf-8")
            assert text, path
            if path.endswith(".js"):
                assert "javascript" in response.headers["Content-Type"], path
    print("PASS: Python static server, UTF-8 and JavaScript MIME types")


def wait_for_status(base, session_id, status, timeout=20):
    for _ in range(int(timeout / 0.1)):
        with urlopen(f"{base}/api/skills/sessions/{session_id}") as response:
            session = json.load(response)
        if session["status"] == status:
            return session
        time.sleep(0.1)
    raise AssertionError(f"Session did not reach {status}")


def session_events(base, session_id):
    # 会话结束后事件流会自然终止，可一次读完。
    with urlopen(f"{base}/api/skills/sessions/{session_id}/events", timeout=20) as response:
        return [json.loads(line[6:]) for line in response.read().decode().splitlines() if line.startswith("data: ")]


def check_api(base, records_path):
    check_static(base)
    for path in ("/storage.py", "/history/example/session.json", "/requirements.txt"):
        try:
            urlopen(base + path).close()
        except HTTPError as error:
            assert error.code == 404
            error.close()
        else:
            raise AssertionError(f"Non-frontend file exposed: {path}")
    endpoint = base + "/api/skills/generate"
    intent = "生成一个跨平台的中文 Skill"
    request = Request(endpoint, json.dumps({"intent": intent}).encode(), {
        "Content-Type": "application/json", "Origin": "http://127.0.0.1:5173",
    })
    with urlopen(request, timeout=20) as response:
        assert response.headers["Content-Type"].startswith("text/event-stream")
        assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
        events = [json.loads(line[6:]) for line in response.read().decode().splitlines() if line.startswith("data: ")]
    # V0 来自 net_skill/skills/ 的待优化 Skill（YAML frontmatter 或标题开头），不再由意图拼接。
    assert events[0]["type"] == "skill" and events[0]["content"].lstrip().startswith(("-", "#"))
    assert events[-1]["type"] == "done" and events[-1]["status"] == "generated"
    for body in ({}, {"intent": ""}, {"intent": "x" * 8001}, {"intent": []}):
        invalid = Request(endpoint, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            urlopen(invalid).close()
        except HTTPError as error:
            assert error.code == 422
            error.close()
        else:
            raise AssertionError(f"Expected 422 for {body}")

    # Skill 目录：列出 skills/ 下待优化 Skill；创建会话绑定选中的 Skill，无效选择回退第一个。
    with urlopen(base + "/api/skills/catalog") as response:
        catalog = json.load(response)
    assert any(item["id"] == "network-fault-diag" and "网络故障" in item.get("description", "")
               for item in catalog["items"]), catalog
    fallback = Request(base + "/api/skills/sessions", json.dumps({"intent": intent, "skill": "no-such-skill"}).encode(), {"Content-Type": "application/json"})
    with urlopen(fallback) as response:
        assert json.load(response)["skill"] == "network-fault-diag"
    # 分步流程：生成结束后可反复点击优化，每轮基于上一版本。
    created = Request(base + "/api/skills/sessions", json.dumps({"intent": intent, "skill": "network-fault-diag"}).encode(), {"Content-Type": "application/json"})
    with urlopen(created) as response:
        created_session = json.load(response)
    session_id = created_session["id"]
    assert created_session["skill"] == "network-fault-diag"
    wait_for_status(base, session_id, "generated")
    skill_0 = next(e for e in session_events(base, session_id) if e.get("id") == "skill-0")
    previous = skill_0["content"]
    # 用例目录与定向选择：列出训练样本；优化请求带 cases 只对勾选的用例演练。
    with urlopen(base + "/api/skills/cases") as response:
        cases = json.load(response)
    assert any(item.get("id") == "diag_001" for item in cases["items"]), cases
    for round_number, body in ((1, {"cases": ["diag_001"]}), (2, {})):
        optimize = Request(f"{base}/api/skills/sessions/{session_id}/optimize", json.dumps(body).encode(), {"Content-Type": "application/json"}, "POST")
        with urlopen(optimize) as response:
            session = json.load(response)
        assert session["phase"] == "optimize" and session["round"] == round_number and session["status"] == "queued"
        assert session["cases"] == body.get("cases", [])
        wait_for_status(base, session_id, "generated")
        events = session_events(base, session_id)
        # 每轮推送状态机七个阶段的进度清单；回滚轮 3/4/5 阶段重复 running→completed。
        snapshots = [e for e in events if e["type"] == "optimize_step" and e["round"] == round_number]
        assert snapshots, "missing optimize_step progress events"
        assert all(step["status"] == "pending" for step in snapshots[0]["steps"])
        assert any(step["status"] == "running" for snapshot in snapshots for step in snapshot["steps"])
        final_steps = snapshots[-1]["steps"]
        assert len(final_steps) == 7 and all(step["status"] == "completed" for step in final_steps)
        # 六个执行阶段都带真实耗时（秒）；最后一步是收尾交接，不单独计时。
        assert all(isinstance(step.get("elapsed"), (int, float)) and step["elapsed"] >= 0
                   for step in final_steps[:6]), final_steps
        optimized = next(e for e in events if e.get("id") == f"skill-{round_number}")
        assert optimized["type"] == "optimized_skill" and optimized["round"] == round_number
        assert snapshots[-1]["seq"] < optimized["seq"]
        assert optimized["content"].startswith(previous)
        previous = optimized["content"]
        if round_number == 1:
            # 定向选择生效：本轮快照内容来自 diag_001（接口down 故障）。
            assert any("接口down" in json.dumps(snapshot, ensure_ascii=False) for snapshot in snapshots), "case selection not applied"
        # 状态机每轮把编辑记录写入重定向后的文件：弱草稿回滚 + 真实修订生效，准确率严格上升。
        with urlopen(base + "/api/skills/edit-records") as response:
            records = [r for r in json.load(response)["items"] if r.get("session") == session_id and r.get("round") == round_number]
        assert records, f"missing edit record for round {round_number}"
        record = records[0]
        assert [edit["status"] for edit in record["edits"]] == ["rolled_back", "applied"], record["edits"]
        assert record["accuracy"] > record["baseline_accuracy"], record
        if round_number == 1:
            assert record["task_ids"] == ["diag_001"] and record["baseline_accuracy"] == 0.0
        else:
            assert record["task_ids"] == ["diag_001", "diag_002"] and record["baseline_accuracy"] == 0.5
        assert record["edit_count"] == len(record["edits"])
    with urlopen(f"{base}/api/skills/sessions/{session_id}/versions/skill-2/download") as response:
        assert response.read().decode("utf-8") == previous
    print("PASS: FastAPI SSE, CORS, optimize progress events, step-by-step rounds, downloads and input validation")


if __name__ == "__main__":
    check_server(["-m", "http.server", "--directory", "web", "{port}", "--bind", "127.0.0.1"], check_static)
    with tempfile.TemporaryDirectory() as directory:
        records_path = Path(directory) / "edit_records.json"
        # 记录重定向到临时目录；清空大模型凭证，状态机走确定性演练路径（弱草稿回滚 + 规则修订接受）。
        env = {"SKILL_EDIT_RECORDS": str(records_path), "ARK_API_KEY": "", "SKILL_LLM_MODEL": ""}
        check_server(backend_args(Path(directory) / "history"), lambda base: check_api(base, records_path), extra_env=env)
