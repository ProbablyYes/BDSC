from datetime import datetime

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.schemas import (
    AgentRunPayload,
    AgentRunResponse,
    AnalyzePayload,
    HealthResponse,
    ProjectSnapshotResponse,
    TeacherFeedbackRequest,
    TeacherFeedbackResponse,
    UploadAnalysisResponse,
)
from app.services.agent_router import run_agents
from app.services.document_parser import extract_text
from app.services.graph_service import GraphService
from app.services.storage import JsonStorage

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

settings.upload_root.mkdir(parents=True, exist_ok=True)
settings.teacher_examples_root.mkdir(parents=True, exist_ok=True)

json_store = JsonStorage(settings.data_root / "project_state")
graph_service = GraphService(
    uri=settings.neo4j_uri,
    username=settings.neo4j_username,
    password=settings.neo4j_password,
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(timestamp=datetime.utcnow())


@app.post("/api/analyze-text")
def analyze_text(payload: AnalyzePayload) -> dict:
    project_state = json_store.load_project(payload.project_id)
    multi_agent_result = run_agents(
        agent_type="all",
        input_text=payload.input_text,
        mode=payload.mode,
        project_state=project_state,
    )
    coach = multi_agent_result["project_coach"]
    json_store.append_submission(
        payload.project_id,
        {
            "student_id": payload.student_id,
            "source_type": "text",
            "raw_text": payload.input_text[:6000],
            "diagnosis": coach["diagnosis"],
            "next_task": coach["next_task"],
            "agent_outputs": multi_agent_result,
        },
    )
    return {
        "project_id": payload.project_id,
        "student_id": payload.student_id,
        "diagnosis": coach["diagnosis"],
        "next_task": coach["next_task"],
        "agent_outputs": multi_agent_result,
    }


@app.post("/api/upload", response_model=UploadAnalysisResponse)
async def upload_and_analyze(
    project_id: str = Form(...),
    student_id: str = Form(...),
    mode: str = Form("coursework"),
    file: UploadFile = File(...),
) -> UploadAnalysisResponse:
    upload_target = settings.upload_root / project_id
    upload_target.mkdir(parents=True, exist_ok=True)
    target_path = upload_target / file.filename

    content = await file.read()
    target_path.write_bytes(content)

    extracted_text = extract_text(target_path)
    if not extracted_text.strip():
        raise HTTPException(status_code=400, detail="无法解析该文件，请尝试 docx/pdf/pptx/txt。")

    project_state = json_store.load_project(project_id)
    multi_agent_result = run_agents(
        agent_type="all",
        input_text=extracted_text,
        mode=mode,
        project_state=project_state,
    )
    coach = multi_agent_result["project_coach"]
    json_store.append_submission(
        project_id,
        {
            "student_id": student_id,
            "source_type": "file",
            "filename": file.filename,
            "raw_text": extracted_text[:6000],
            "diagnosis": coach["diagnosis"],
            "next_task": coach["next_task"],
            "agent_outputs": multi_agent_result,
        },
    )

    return UploadAnalysisResponse(
        project_id=project_id,
        student_id=student_id,
        filename=file.filename,
        extracted_length=len(extracted_text),
        diagnosis=coach["diagnosis"],
        next_task=coach["next_task"],
    )


@app.post("/api/teacher-feedback", response_model=TeacherFeedbackResponse)
def add_teacher_feedback(payload: TeacherFeedbackRequest) -> TeacherFeedbackResponse:
    feedback_id = json_store.append_teacher_feedback(
        payload.project_id,
        {
            "teacher_id": payload.teacher_id,
            "comment": payload.comment,
            "focus_tags": payload.focus_tags,
        },
    )
    return TeacherFeedbackResponse(
        project_id=payload.project_id,
        status="saved",
        feedback_id=feedback_id,
    )


@app.get("/api/project/{project_id}", response_model=ProjectSnapshotResponse)
def project_snapshot(project_id: str) -> ProjectSnapshotResponse:
    data = json_store.load_project(project_id)
    latest_submission = data["submissions"][-1] if data["submissions"] else None
    graph = graph_service.health()
    return ProjectSnapshotResponse(
        project_id=project_id,
        latest_student_submission=latest_submission,
        teacher_feedback=data["teacher_feedback"],
        graph_signals={"connected": graph.connected, "detail": graph.detail},
    )


@app.get("/api/teacher-examples")
def list_teacher_examples() -> dict:
    categories = []
    for category_dir in sorted(settings.teacher_examples_root.glob("*")):
        if not category_dir.is_dir():
            continue
        items = [
            {"name": p.name, "size": p.stat().st_size}
            for p in sorted(category_dir.glob("*"))
            if p.is_file()
        ]
        categories.append(
            {
                "category": category_dir.name,
                "count": len(items),
                "files": items,
            }
        )
    root_files = [
        {"name": p.name, "size": p.stat().st_size}
        for p in sorted(settings.teacher_examples_root.glob("*"))
        if p.is_file()
    ]
    return {
        "path": str(settings.teacher_examples_root),
        "root_file_count": len(root_files),
        "root_files": root_files,
        "categories": categories,
    }


@app.post("/api/agent/run", response_model=AgentRunResponse)
def run_agent(payload: AgentRunPayload) -> AgentRunResponse:
    project_state = json_store.load_project(payload.project_id)
    input_text = payload.prompt or ""
    if not input_text:
        latest_submission = project_state["submissions"][-1] if project_state["submissions"] else {}
        input_text = latest_submission.get("raw_text", "") or latest_submission.get("diagnosis", {}).get("summary", "")
    result = run_agents(
        agent_type=payload.agent_type,
        input_text=input_text,
        mode=payload.mode,
        project_state=project_state,
    )
    return AgentRunResponse(
        project_id=payload.project_id,
        agent_type=payload.agent_type,
        result=result,
    )
