from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.database import DATA_DIR, init_db
from app.services.agents import AGENT_REGISTRY, frontier_agent, learning_agent, ppt_agent, supervisor_agent
from app.services.notifications import notifications
from app.services.rag import rag_service
from app.services.scheduler import local_scheduler


STATIC_DIR = Path(__file__).resolve().parent / "static"
GENERATED_DIR = DATA_DIR / "generated"


app = FastAPI(title="Personal Steward Agent", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/generated", StaticFiles(directory=GENERATED_DIR), name="generated")


class LearningPlanRequest(BaseModel):
    topic: str
    duration_days: int = Field(default=14, ge=1, le=365)
    daily_minutes: int = Field(default=60, ge=10, le=600)
    target_level: str = "入门到可独立实践"
    use_knowledge: bool = True


class ProgressRequest(BaseModel):
    plan_id: int
    day_index: int
    completion: int = Field(ge=0, le=100)
    mastery: int = Field(ge=0, le=100)
    notes: str = ""


class LearningPlanUpdateRequest(BaseModel):
    duration_days: int = Field(ge=1, le=365)
    daily_minutes: int = Field(ge=10, le=600)


class QueryRequest(BaseModel):
    query: str
    limit: int = Field(default=5, ge=1, le=20)


class PPTRequest(BaseModel):
    topic: str
    audience: str = "通用受众"
    style: str = "清爽专业"
    slides: int = Field(default=6, ge=3, le=30)
    use_knowledge: bool = True


class RouteRequest(BaseModel):
    message: str


class LearningChatRequest(BaseModel):
    plan_id: int
    message: str
    selected_day: Optional[int] = None


@app.on_event("startup")
def startup() -> None:
    init_db()
    local_scheduler.start()


@app.on_event("shutdown")
def shutdown() -> None:
    local_scheduler.shutdown()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status():
    return {"ok": True, "version": "0.1.0", "agents": AGENT_REGISTRY}


@app.get("/api/dashboard")
def dashboard():
    local_scheduler.catch_up()
    plans = learning_agent.list_plans()
    reports = frontier_agent.list_reports()
    return {
        "notifications": notifications.providers["in_app"].list(limit=12),
        "plans": plans[:3],
        "frontier_reports": reports[:3],
        "agents": AGENT_REGISTRY,
        "knowledge_files": rag_service.list_files()[:5],
    }


@app.get("/api/agents")
def agents():
    return AGENT_REGISTRY


@app.post("/api/supervisor/route")
def route(req: RouteRequest):
    return supervisor_agent.route(req.message)


@app.get("/api/notifications")
def list_notifications(unread_only: bool = False):
    return notifications.providers["in_app"].list(unread_only=unread_only)


@app.post("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int):
    notifications.providers["in_app"].mark_read(notification_id)
    return {"ok": True}


@app.post("/api/knowledge/upload")
async def upload_knowledge(file: UploadFile = File(...), tags: Optional[str] = Form(default="")):
    suffix = Path(file.filename or "upload").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        tag_list = [tag.strip() for tag in (tags or "").split(",") if tag.strip()]
        return rag_service.upload_file(tmp_path, file.filename or "upload", tag_list)
    finally:
        tmp_path.unlink(missing_ok=True)


@app.get("/api/knowledge/files")
def list_knowledge_files():
    return rag_service.list_files()


@app.delete("/api/knowledge/files/{file_id}")
def delete_knowledge_file(file_id: int):
    return rag_service.delete_file(file_id)


@app.post("/api/knowledge/query")
def query_knowledge(req: QueryRequest):
    return rag_service.query(req.query, req.limit)


@app.post("/api/learning/plans")
def create_learning_plan(req: LearningPlanRequest):
    return learning_agent.create_plan(req.topic, req.duration_days, req.daily_minutes, req.target_level, req.use_knowledge)


@app.get("/api/learning/plans")
def list_learning_plans():
    return learning_agent.list_plans()


@app.get("/api/learning/plans/{plan_id}")
def get_learning_plan(plan_id: int):
    return learning_agent.get_plan_detail(plan_id)


@app.patch("/api/learning/plans/{plan_id}")
def update_learning_plan(plan_id: int, req: LearningPlanUpdateRequest):
    return learning_agent.update_plan_settings(plan_id, req.duration_days, req.daily_minutes)


@app.delete("/api/learning/plans/{plan_id}")
def delete_learning_plan(plan_id: int):
    return learning_agent.delete_plan(plan_id)


@app.post("/api/learning/progress")
def record_progress(req: ProgressRequest):
    return learning_agent.record_progress(req.plan_id, req.day_index, req.completion, req.mastery, req.notes)


@app.post("/api/learning/chat")
def learning_chat(req: LearningChatRequest):
    return learning_agent.chat(req.plan_id, req.message, req.selected_day)


@app.post("/api/ppt/generate")
def generate_ppt(req: PPTRequest):
    return ppt_agent.generate(req.topic, req.audience, req.style, req.slides, req.use_knowledge)


@app.get("/api/ppt/jobs")
def ppt_jobs():
    return ppt_agent.list_jobs()


@app.post("/api/frontier/run")
def run_frontier():
    return frontier_agent.run_daily()


@app.get("/api/frontier/reports")
def frontier_reports():
    return frontier_agent.list_reports()
