"""跨平台集成检查：python -B tests/check_backend.py（只用标准库）。"""
import json
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


def check_server(arguments, check):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-B", *[arg.replace("{port}", str(port)) for arg in arguments]],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
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


def check_api(base):
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
    assert events[0]["type"] == "subgraph"
    assert events[-1]["type"] == "done"
    assert any(e["type"] == "strategy" for e in events)
    for round_number in (1, 2):
        chunks = [e["delta"] for e in events if e.get("id") == f"skill-{round_number}"]
        assert chunks and intent in "".join(chunks)
    final = next(e["content"] for e in events if e["type"] == "final_skill")
    assert final == "".join(e["delta"] for e in events if e.get("id") == "skill-2")
    for skill_id in ("skill-0", "skill-1", "skill-2", "skill-final"):
        skill_end = max(i for i, e in enumerate(events) if e.get("id") == skill_id)
        traces = [(i, e) for i, e in enumerate(events) if e.get("skill_id") == skill_id]
        assert traces and traces[0][0] > skill_end
        assert traces[0][1]["status"] == "running"
        assert traces[-1][1]["status"] == "completed"
        assert len({e["id"] for _, e in traces}) == 1
        assert any(e.get("delta") for _, e in traces)
    for body in ({}, {"intent": ""}, {"intent": "x" * 8001}, {"intent": []}):
        invalid = Request(endpoint, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            urlopen(invalid).close()
        except HTTPError as error:
            assert error.code == 422
            error.close()
        else:
            raise AssertionError(f"Expected 422 for {body}")
    print("PASS: FastAPI SSE, CORS, Chinese text, rounds, deltas and input validation")


if __name__ == "__main__":
    check_server(["-m", "http.server", "{port}", "--bind", "127.0.0.1"], check_static)
    with tempfile.TemporaryDirectory() as directory:
        check_server(backend_args(Path(directory) / "history"), check_api)
