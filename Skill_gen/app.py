"""运行 python app.py，同时启动前端和后端。"""
import sys
sys.dont_write_bytecode = True

import asyncio
from contextlib import asynccontextmanager, suppress
import json
import logging
from pathlib import Path
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pipeline import generate_events
import storage

tasks = {}


async def run_session(session):
    session_id = session["id"]
    try:
        async for event in generate_events(session["intent"]):
            if event["type"] == "done":
                storage.append(session_id, {**event, "status": "completed"}, "completed")
                return
            if event["type"] == "error":
                storage.append(session_id, event, "failed")
                return
            storage.append(session_id, event)
        raise RuntimeError("Pipeline ended without done")
    except asyncio.CancelledError:
        storage.append(session_id, {"type": "done", "status": "interrupted", "message": "服务停止，已保留当前记录。"}, "interrupted")
        raise
    except Exception:
        logging.exception("Skill session failed: %s", session_id)
        storage.append(session_id, {"type": "error", "message": "生成失败，已保留当前记录。"}, "failed")


async def worker():
    # 单进程队列：任务写入历史文件夹后才执行，与浏览器连接无关。
    while True:
        session = storage.claim()
        if not session:
            await asyncio.sleep(0.25)
            continue
        task = asyncio.create_task(run_session(session))
        tasks[session["id"]] = task
        try:
            await asyncio.gather(task, return_exceptions=True)
        finally:
            tasks.pop(session["id"], None)


@asynccontextmanager
async def lifespan(app):
    storage.initialize()
    job = asyncio.create_task(worker())
    try:
        yield
    finally:
        job.cancel()
        with suppress(asyncio.CancelledError):
            await job


app = FastAPI(lifespan=lifespan)
FRONTEND_DIR = Path(__file__).resolve().parent
# 只开放前端资源，不把 history、源码和配置目录作为静态目录暴露。
app.mount("/src", StaticFiles(directory=FRONTEND_DIR / "src"), name="frontend-src")


@app.get("/", include_in_schema=False)
async def frontend():
    return FileResponse(FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/{asset}", include_in_schema=False)
async def frontend_asset(asset: str):
    if asset not in ("styles.css", "config.js"):
        raise HTTPException(404, "Not found")
    return FileResponse(FRONTEND_DIR / asset, headers={"Cache-Control": "no-store"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type", "Authorization"],
)


def require_session(session_id):
    session = storage.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@app.post("/api/skills/sessions", status_code=201)
async def create_session(intent: str = Body(embed=True, min_length=1, max_length=8000)):
    if not intent.strip():
        raise HTTPException(422, "Intent must not be blank")
    return storage.create(intent.strip())


@app.get("/api/skills/sessions")
async def list_sessions(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    return storage.listing(limit, offset)


@app.get("/api/skills/sessions/{session_id}")
async def get_session(session_id: str):
    return require_session(session_id)


@app.get("/api/skills/sessions/{session_id}/events")
async def stream_session(session_id: str, request: Request, after: int = Query(0, ge=0)):
    require_session(session_id)

    async def stream():
        cursor = after
        while not await request.is_disconnected():
            # 先读状态再读事件，避免终态写入和最后一批事件之间的竞态。
            session = storage.get(session_id)
            if not session:
                yield 'data: {"type":"done","status":"deleted","message":"此记录已被删除。"}\n\n'
                return
            batch = storage.read_events(session_id, cursor)
            for event in batch:
                cursor = event["seq"]
                yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            if not batch and session["status"] not in storage.ACTIVE:
                return
            if not batch:
                yield ": waiting\n\n"
                await asyncio.sleep(0.4)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/skills/sessions/{session_id}/stop")
async def stop_session(session_id: str):
    require_session(session_id)
    storage.append(session_id, {"type": "done", "status": "stopped"}, "stopped")
    if task := tasks.get(session_id):
        task.cancel()
    return require_session(session_id)


@app.get("/api/skills/sessions/{session_id}/versions/{version_id}/download")
async def download_version(session_id: str, version_id: str):
    require_session(session_id)
    content = storage.version_content(session_id, version_id)
    if content is None:
        raise HTTPException(404, "Version not found")
    return Response(content, media_type="text/markdown", headers={"Content-Disposition": 'attachment; filename="SKILL.md"'})


@app.delete("/api/skills/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str):
    # 先标记停止，防止排队任务被取走；等待执行退出后再删除文件。
    await stop_session(session_id)
    if task := tasks.get(session_id):
        await asyncio.gather(task, return_exceptions=True)
    try:
        storage.delete(session_id)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return Response(status_code=204)


# 保留旧 POST SSE 接口；断开此连接同样不会取消任务。
@app.post("/api/skills/generate")
async def generate(request: Request, intent: str = Body(embed=True, min_length=1, max_length=8000)):
    session = await create_session(intent)
    return await stream_session(session["id"], request, 0)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
