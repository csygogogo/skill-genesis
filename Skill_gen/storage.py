"""历史记录就是普通文件夹：session.json、events.jsonl、skills/*.md。"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import quote
from uuid import uuid4

HISTORY_DIR = Path(__file__).resolve().parent / "history"
ACTIVE = ("queued", "running")


def now():
    return datetime.now(timezone.utc).isoformat()


def folder(session_id):
    # URL 中的会话 id 只能访问历史根目录下的生成目录。
    if not re.fullmatch(r"[a-f0-9]{32}", session_id):
        return None
    return HISTORY_DIR / session_id


def save_session(session):
    path = folder(session["id"]) / "session.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def get(session_id):
    directory = folder(session_id)
    if directory is None or not (directory / "session.json").is_file():
        return None
    return json.loads((directory / "session.json").read_text(encoding="utf-8"))


def listing(limit=50, offset=0):
    sessions = []
    for path in HISTORY_DIR.glob("*/session.json"):
        try:
            sessions.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue  # 一个手工改坏的文件不影响其他记录。
    sessions.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
    return {"items": sessions[offset:offset + limit], "total": len(sessions)}


def create(intent):
    session = {
        "id": uuid4().hex, "intent": intent, "status": "queued",
        "phase": "generate", "round": 0, "created_at": now(), "updated_at": now(),
    }
    (folder(session["id"]) / "skills").mkdir(parents=True)
    save_session(session)
    return session


def read_events(session_id, after=0, limit=500):
    path = folder(session_id) / "events.jsonl"
    if not path.exists():
        return []
    events = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            try:
                event = json.loads(line)
            except ValueError:
                continue  # 保留原文件；未写完整或手工改坏的行不参与回放。
            if event["seq"] > after:
                events.append(event)
                if len(events) >= limit:
                    break
    return events


def version_content(session_id, version_id):
    content, found, cursor = "", False, 0
    while batch := read_events(session_id, cursor):
        for event in batch:
            cursor = event["seq"]
            if event.get("id") == version_id and event["type"] in ("skill", "optimized_skill", "final_skill"):
                found = True
                content = content + event["delta"] if "delta" in event else event.get("content", content)
    return content if found else None


def latest_skill(session_id):
    """返回事件流中最后一个 Skill 版本 {"id", "round", "content"}；没有版本时返回 None。"""
    contents, order, cursor = {}, [], 0
    while batch := read_events(session_id, cursor):
        for event in batch:
            cursor = event["seq"]
            if event["type"] in ("skill", "optimized_skill", "final_skill"):
                if event["id"] not in contents:
                    order.append(event)
                previous = contents.get(event["id"], "")
                contents[event["id"]] = (
                    previous + event["delta"] if "delta" in event
                    else event.get("content", previous)
                )
    if not order:
        return None
    last = order[-1]
    return {"id": last["id"], "round": last.get("round", 0), "content": contents[last["id"]]}


def requeue_optimize(session_id):
    """把会话重新排队进入下一轮优化；由 worker 像生成任务一样领取执行。"""
    session = get(session_id)
    session.update(phase="optimize", round=session.get("round", 0) + 1, status="queued", updated_at=now())
    save_session(session)
    return session


def write_skill(session_id, version_id):
    content = version_content(session_id, version_id)
    if content is not None:
        path = folder(session_id) / "skills" / (quote(str(version_id), safe="") + ".md")
        path.write_text(content, encoding="utf-8")


def append(session_id, event, status=None):
    session = get(session_id)
    if not session or session["status"] not in ACTIVE:
        return
    event = {**event, "created_at": now(), "seq": session.get("event_count", 0) + 1}
    # 事件是原始记录；Markdown 文件是方便直接使用的副本。
    with (folder(session_id) / "events.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False) + "\n")
        file.flush()
        os.fsync(file.fileno())
    session.update(status=status or session["status"], updated_at=event["created_at"], event_count=event["seq"])
    save_session(session)
    if event["type"] in ("skill", "optimized_skill", "final_skill"):
        write_skill(session_id, event["id"])


def initialize():
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    for session in listing(limit=10**9)["items"]:
        # 补齐意外退出时尚未更新的状态和 Markdown 副本。
        path = folder(session["id"]) / "events.jsonl"
        events = read_events(session["id"], limit=10**9)
        if path.exists():
            # 不删除原始日志；为断电后的不完整尾行补换行，允许继续追加。
            with path.open("rb+") as file:
                if file.seek(0, 2):
                    file.seek(-1, 2)
                    if file.read(1) != b"\n":
                        file.write(b"\n")
        if events:
            last = events[-1]
            session.update(event_count=last["seq"], updated_at=last["created_at"])
            if last["type"] == "done":
                session["status"] = last.get("status", "completed")
            elif last["type"] == "error":
                session["status"] = "failed"
            save_session(session)
            for version_id in {e["id"] for e in events if e["type"] in ("skill", "optimized_skill", "final_skill")}:
                write_skill(session["id"], version_id)
        if session["status"] == "running":
            append(session["id"], {"type": "done", "status": "interrupted", "message": "服务重启中断了执行，已保留此前记录。"}, "interrupted")


def claim():
    for session in reversed(listing(limit=10**9)["items"]):
        if session["status"] == "queued":
            session.update(status="running", updated_at=now())
            save_session(session)
            return session
    return None


def delete(session_id):
    directory = folder(session_id)
    root = HISTORY_DIR.resolve()
    if directory is None or directory.resolve() != root / session_id:
        raise ValueError("Refusing to delete a path outside this session folder")
    if directory.exists():
        shutil.rmtree(directory)
