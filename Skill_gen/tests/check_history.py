"""真实 HTTP + 历史文件夹回归：断连、20 条记录、下载、停止与服务重启。"""
import json
from pathlib import Path
import tempfile
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from check_backend import check_server, backend_args


def request(base, path="", body=None, method=None):
    req = Request(base + "/api/skills/sessions" + path,
                  None if body is None else json.dumps(body).encode(),
                  {"Content-Type": "application/json"}, method=method)
    with urlopen(req, timeout=15) as response:
        return None if response.status == 204 else json.load(response)


def wait_for(base, session_id, statuses):
    for _ in range(150):
        session = request(base, "/" + session_id)
        if session["status"] in statuses:
            return session
        time.sleep(0.1)
    raise AssertionError(f"Session did not reach {statuses}")


def download(base, session_id):
    with urlopen(f"{base}/api/skills/sessions/{session_id}/versions/skill-0/download") as response:
        assert "attachment" in response.headers["Content-Disposition"]
        return response.read().decode("utf-8")


def check_persistence():
    saved = {}

    def before_restart(base):
        session = request(base, body={"intent": "保存中文 Skill，关闭页面后继续执行"})
        saved["id"] = session["id"]
        # 收到第一条消息后主动断开查看连接。
        with urlopen(f"{base}/api/skills/sessions/{session['id']}/events", timeout=10) as response:
            while not response.readline().startswith(b"data: "):
                pass
        wait_for(base, session["id"], {"generated"})
        saved["content"] = download(base, session["id"])
        assert "关闭页面后继续执行" in saved["content"]
        # 创建另外 19 条独立记录并停止，确认不会覆盖、不会删除部分结果。
        for index in range(19):
            item = request(base, body={"intent": f"历史意图 {index}"})
            stopped = request(base, f"/{item['id']}/stop", {})
            assert stopped["status"] == "stopped"
        page = request(base, "?limit=10&offset=0")
        page2 = request(base, "?limit=10&offset=10")
        assert page["total"] == 20
        assert len({s["id"] for s in page["items"] + page2["items"]}) == 20
        with urlopen(f"{base}/api/skills/sessions/{session['id']}/events") as response:
            saved["events"] = response.read()
        assert b'"type": "skill"' in saved["events"]
        saved["active"] = request(base, body={"intent": "服务重启时中断的任务"})["id"]
        wait_for(base, saved["active"], {"running"})
        saved["queued"] = request(base, body={"intent": "重启后继续排队的任务"})["id"]
        assert request(base, "/" + saved["queued"])["status"] == "queued"
        print("PASS: disconnected task completed; 20 independent records; pagination; stop; download")

    def after_restart(base):
        assert request(base)["total"] == 22
        assert download(base, saved["id"]) == saved["content"]
        with urlopen(f"{base}/api/skills/sessions/{saved['id']}/events") as response:
            assert response.read() == saved["events"]
        assert request(base, "/" + saved["active"])["status"] == "interrupted"
        wait_for(base, saved["queued"], {"generated"})
        assert "重启后继续排队" in download(base, saved["queued"])
        print("PASS: history, events and downloads survive restart; interrupted status; queued task resumes")
        # 只删除临时测试记录：覆盖完成、执行中、排队三种状态。
        running = request(base, body={"intent": "待删除的执行中测试任务"})["id"]
        wait_for(base, running, {"running"})
        queued = request(base, body={"intent": "待删除的排队测试任务"})["id"]
        for session_id in (queued, running, saved["id"]):
            request(base, "/" + session_id, method="DELETE")
            assert not (history / session_id).exists()
            for suffix in ("", "/events", "/versions/skill-0/download"):
                try:
                    request(base, "/" + session_id + suffix)
                except HTTPError as error:
                    assert error.code == 404
                    error.close()
                else:
                    raise AssertionError("Deleted record is still accessible")
        time.sleep(0.5)
        assert not (history / running).exists()
        assert request(base)["total"] == 21
        assert "重启后继续排队" in download(base, saved["queued"])
        print("PASS: delete completed/running/queued records and files; other records preserved")

    with tempfile.TemporaryDirectory() as directory:
        history = Path(directory) / "history"
        args = backend_args(history)
        check_server(args, before_restart)
        check_server(args, after_restart)


if __name__ == "__main__":
    check_persistence()
