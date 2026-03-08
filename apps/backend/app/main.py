from datetime import datetime
from typing import Any

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
from app.services.case_knowledge import infer_category
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
    database=settings.neo4j_database,
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
            "class_id": payload.class_id,
            "cohort_id": payload.cohort_id,
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
    class_id: str = Form(""),
    cohort_id: str = Form(""),
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
            "class_id": class_id or None,
            "cohort_id": cohort_id or None,
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


@app.get("/api/teacher/dashboard")
def teacher_dashboard(category: str | None = None, limit: int = 8) -> dict:
    limit = max(1, min(limit, 30))
    data = graph_service.teacher_dashboard(category=category, limit=limit)
    return {
        "category_filter": category,
        "limit": limit,
        "data": data,
    }


@app.get("/api/teacher/project/{project_id}/evidence")
def teacher_project_evidence(project_id: str) -> dict:
    data = graph_service.project_evidence(project_id=project_id)
    return {
        "project_id": project_id,
        "data": data,
    }


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return 0.0


def _build_class_snapshot(class_id: str | None = None, cohort_id: str | None = None, limit: int = 8) -> dict[str, Any]:
    projects = json_store.list_projects()
    submissions: list[dict[str, Any]] = []
    for project in projects:
        for sub in project.get("submissions", []):
            if class_id and sub.get("class_id") != class_id:
                continue
            if cohort_id and sub.get("cohort_id") != cohort_id:
                continue
            submissions.append(sub)

    if not submissions:
        return {
            "submission_count": 0,
            "avg_rule_hits_per_submission": 0.0,
            "high_risk_ratio": 0.0,
            "avg_rubric_score": 0.0,
            "category_distribution": [],
            "top_risk_rules": [],
            "risk_levels": {"high": 0, "medium": 0, "low": 0},
        }

    total_rule_hits = 0
    high_risk_count = 0
    rubric_score_sum = 0.0
    rubric_score_count = 0
    category_counter: dict[str, int] = {}
    risk_rule_counter: dict[str, int] = {}
    risk_levels = {"high": 0, "medium": 0, "low": 0}

    for sub in submissions:
        diagnosis = sub.get("diagnosis", {}) if isinstance(sub.get("diagnosis"), dict) else {}
        triggered = diagnosis.get("triggered_rules", [])
        triggered = triggered if isinstance(triggered, list) else []
        total_rule_hits += len(triggered)
        if len(triggered) >= 2:
            high_risk_count += 1
        for item in triggered:
            if not isinstance(item, dict):
                continue
            rule_id = str(item.get("id") or "UNKNOWN")
            risk_rule_counter[rule_id] = risk_rule_counter.get(rule_id, 0) + 1
            sev = str(item.get("severity") or "low").lower()
            if sev in risk_levels:
                risk_levels[sev] += 1
            else:
                risk_levels["low"] += 1

        rubric = diagnosis.get("rubric", [])
        rubric = rubric if isinstance(rubric, list) else []
        for r in rubric:
            if not isinstance(r, dict):
                continue
            rubric_score_sum += _safe_float(r.get("score"))
            rubric_score_count += 1

        raw_text = str(sub.get("raw_text") or "")
        category = infer_category(raw_text) if raw_text else "未分类"
        category_counter[category] = category_counter.get(category, 0) + 1

    submission_count = len(submissions)
    top_risk_rules = sorted(risk_rule_counter.items(), key=lambda x: x[1], reverse=True)[:limit]
    category_distribution = sorted(category_counter.items(), key=lambda x: x[1], reverse=True)

    return {
        "submission_count": submission_count,
        "avg_rule_hits_per_submission": round(total_rule_hits / submission_count, 3),
        "high_risk_ratio": round(high_risk_count / submission_count, 3),
        "avg_rubric_score": round((rubric_score_sum / rubric_score_count) if rubric_score_count else 0.0, 3),
        "category_distribution": [
            {"category": k, "project_count": v, "ratio": round(v / submission_count, 3)}
            for k, v in category_distribution
        ],
        "top_risk_rules": [
            {"rule": k, "project_count": v, "ratio": round(v / submission_count, 3)}
            for k, v in top_risk_rules
        ],
        "risk_levels": risk_levels,
    }


def _build_compare_recommendations(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> list[str]:
    if int(current.get("submission_count", 0) or 0) == 0:
        return ["当前筛选范围内还没有学生提交记录，先完成至少1轮班级提交后再看基线对比。"]

    recs: list[str] = []
    risk_delta = current.get("avg_rule_hits_per_submission", 0.0) - baseline.get("avg_rule_hits_per_project", 0.0)
    high_risk_delta = current.get("high_risk_ratio", 0.0) - baseline.get("high_risk_ratio", 0.0)
    rubric_score = current.get("avg_rubric_score", 0.0)

    if risk_delta > 0.4:
        recs.append("本班规则命中强度高于历史基线，优先开展高频风险规则的集中讲解与案例反例对照。")
    if high_risk_delta > 0.12:
        recs.append("本班高风险项目占比偏高，建议分层干预：先处理风险规则>=2的项目，再推进一般项目。")
    if rubric_score and rubric_score < 6.2:
        recs.append("本班 rubric 平均分偏低，建议将下一次作业要求改为“证据链补齐任务”，并设24小时与72小时两级验收。")
    if not recs:
        recs.append("本班整体接近历史基线，可把重心放在优秀样例复盘和跨组互评，提升天花板。")
    return recs


@app.get("/api/teacher/compare")
def teacher_compare(
    class_id: str | None = None,
    cohort_id: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    limit = max(1, min(limit, 30))
    baseline = graph_service.baseline_snapshot(limit=limit)
    current = _build_class_snapshot(class_id=class_id, cohort_id=cohort_id, limit=limit)
    comparison = {
        "risk_intensity_delta": round(
            current.get("avg_rule_hits_per_submission", 0.0) - baseline.get("avg_rule_hits_per_project", 0.0),
            3,
        ),
        "high_risk_ratio_delta": round(current.get("high_risk_ratio", 0.0) - baseline.get("high_risk_ratio", 0.0), 3),
    }
    recommendations = _build_compare_recommendations(baseline=baseline, current=current)
    return {
        "filters": {"class_id": class_id, "cohort_id": cohort_id, "limit": limit},
        "baseline": baseline,
        "current_class": current,
        "comparison": comparison,
        "recommendations": recommendations,
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
