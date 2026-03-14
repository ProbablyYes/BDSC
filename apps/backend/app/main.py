from datetime import datetime
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.schemas import (
    AgentRunPayload,
    AgentRunResponse,
    AnalyzePayload,
    DialogueTurnPayload,
    DialogueTurnResponse,
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
from app.services.hypergraph_service import HypergraphService
from app.services.llm_client import LlmClient
from app.services.storage import ConversationStorage, JsonStorage

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
conv_store = ConversationStorage(settings.data_root / "conversations")
graph_service = GraphService(
    uri=settings.neo4j_uri,
    username=settings.neo4j_username,
    password=settings.neo4j_password,
    database=settings.neo4j_database,
)
hypergraph_service = HypergraphService(graph_service=graph_service)
composer_llm = LlmClient()


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
    inferred_category = infer_category(payload.input_text)
    rule_ids = [str(x.get("id")) for x in (coach.get("diagnosis", {}).get("triggered_rules", []) or []) if isinstance(x, dict)]
    hyper_insight = hypergraph_service.insight(category=inferred_category, rule_ids=rule_ids, limit=3)
    json_store.append_submission(
        payload.project_id,
        {
            "student_id": payload.student_id,
            "class_id": payload.class_id,
            "cohort_id": payload.cohort_id,
            "source_type": "text",
            "mode": payload.mode,
            "raw_text": payload.input_text[:6000],
            "diagnosis": coach["diagnosis"],
            "next_task": coach["next_task"],
            "hypergraph_insight": hyper_insight,
            "agent_outputs": multi_agent_result,
        },
    )
    return {
        "project_id": payload.project_id,
        "student_id": payload.student_id,
        "diagnosis": coach["diagnosis"],
        "next_task": coach["next_task"],
        "hypergraph_insight": hyper_insight,
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
    inferred_category = infer_category(extracted_text)
    rule_ids = [str(x.get("id")) for x in (coach.get("diagnosis", {}).get("triggered_rules", []) or []) if isinstance(x, dict)]
    hyper_insight = hypergraph_service.insight(category=inferred_category, rule_ids=rule_ids, limit=3)
    json_store.append_submission(
        project_id,
        {
            "student_id": student_id,
            "class_id": class_id or None,
            "cohort_id": cohort_id or None,
            "source_type": "file",
            "mode": mode,
            "filename": file.filename,
            "raw_text": extracted_text[:6000],
            "diagnosis": coach["diagnosis"],
            "next_task": coach["next_task"],
            "hypergraph_insight": hyper_insight,
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
        hypergraph_insight=hyper_insight,
    )


def _compose_assistant_message(
    user_message: str,
    coach: dict,
    critic: dict,
    planner: dict,
    grader: dict | None = None,
    hyper_insight: dict | None = None,
) -> str:
    diagnosis = coach.get("diagnosis", {}) if isinstance(coach, dict) else {}
    next_task = coach.get("next_task", {}) if isinstance(coach, dict) else {}
    bottleneck = str(diagnosis.get("bottleneck") or "暂无")
    rules = diagnosis.get("triggered_rules", []) or []
    rule_text = "；".join(f"{r.get('id')}:{r.get('name')}" for r in rules[:5] if isinstance(r, dict)) or "暂无"
    task_title = str(next_task.get("title") or "暂无")
    task_desc = str(next_task.get("description") or "")
    accept = next_task.get("acceptance_criteria", []) or []
    challenge = (critic.get("counterfactual_questions") or critic.get("challenge_points") or []) if isinstance(critic, dict) else []
    plan = planner.get("execution_plan", []) if isinstance(planner, dict) else []
    socratic = diagnosis.get("socratic_questions", []) or []
    score = (grader or {}).get("overall_score", diagnosis.get("overall_score", ""))
    hyper_edges = (hyper_insight or {}).get("edges", []) or []
    hyper_note = hyper_edges[0].get("teaching_note", "") if hyper_edges else ""

    context_block = (
        f"## 诊断结果\n瓶颈: {bottleneck}\n触发风险: {rule_text}\n综合评分: {score}\n"
        f"## 下一步任务\n标题: {task_title}\n描述: {task_desc}\n验收标准: {accept}\n"
        f"## Critic反驳\n反事实追问: {challenge[:3]}\n"
        f"## Planner建议\n执行计划: {plan[:3]}\n"
        f"## 苏格拉底追问\n{socratic[:3]}\n"
    )
    if hyper_note:
        context_block += f"## 超图洞察\n{hyper_note}\n"

    if composer_llm.enabled:
        reply = composer_llm.chat_text(
            system_prompt=(
                "你是一位经验丰富、温和但严格的双创项目教练。\n"
                "请基于以下多Agent诊断结果，用自然流畅的中文给学生写一段回复。\n"
                "要求：\n"
                "1. 先简要回应学生说的话，体现你在认真倾听\n"
                "2. 指出最关键的1-2个风险，用通俗语言解释为什么这是问题\n"
                "3. 给出唯一的下一步任务，说清楚要做什么、怎么做\n"
                "4. 用苏格拉底式追问收尾——提一个让学生深入思考的问题\n"
                "5. 语气像导师跟学生聊天，不要用表格或列表标记符号，不要说'根据诊断结果'\n"
                "6. 控制在200-400字\n"
            ),
            user_prompt=f"学生说：{user_message}\n\n诊断上下文：\n{context_block}",
            model=settings.llm_reason_model,
            temperature=0.35,
        )
        if reply and len(reply.strip()) > 30:
            return reply.strip()

    msg = f"{bottleneck}\n\n触发风险：{rule_text}\n\n下一步任务：{task_title}\n{task_desc}"
    if accept:
        msg += "\n验收标准：" + "；".join(str(a) for a in accept[:3])
    if challenge:
        msg += f"\n\n追问：{challenge[0]}"
    if plan:
        msg += f"\n执行建议：{plan[0]}"
    return msg


@app.post("/api/dialogue/turn", response_model=DialogueTurnResponse)
def dialogue_turn(payload: DialogueTurnPayload) -> DialogueTurnResponse:
    from app.services.graph_workflow import run_workflow

    project_state = json_store.load_project(payload.project_id)

    # ── conversation management ──
    conv_id = payload.conversation_id
    conv_messages: list[dict] = []
    if conv_id:
        conv = conv_store.get(payload.project_id, conv_id)
        if conv:
            conv_messages = conv.get("messages", [])
    else:
        new_conv = conv_store.create(payload.project_id, payload.student_id)
        conv_id = new_conv["conversation_id"]

    # ── history from past submissions ──
    submissions = project_state.get("submissions", []) or []
    history_context = ""
    for row in submissions[-4:]:
        snippet = (row.get("raw_text") or "")[:200]
        task = (row.get("next_task") or {}).get("title", "")
        if snippet:
            history_context += f"- 学生曾说：{snippet}… → 建议任务：{task}\n"

    # ── teacher feedback context ──
    teacher_fb = project_state.get("teacher_feedback", [])
    tfb_ctx = ""
    if teacher_fb:
        latest = teacher_fb[-1]
        tfb_ctx = f"{latest.get('comment','')}\n关注点: {latest.get('focus_tags',[])}"

    # ── run LangGraph workflow ──
    result = run_workflow(
        message=payload.message,
        mode=payload.mode,
        project_state=project_state,
        history_context=history_context,
        conversation_messages=conv_messages,
        teacher_feedback_context=tfb_ctx,
    )

    diagnosis = result.get("diagnosis", {})
    next_task = result.get("next_task", {})
    category = result.get("category", "")
    kg_analysis = result.get("kg_analysis", {})
    assistant_message = result.get("assistant_message", "")
    nodes_visited = result.get("nodes_visited", [])

    # ── hypergraph insight (service lives in main, not in workflow) ──
    rule_ids = [str(r.get("id")) for r in (diagnosis.get("triggered_rules", []) or []) if isinstance(r, dict)]
    hyper_insight = hypergraph_service.insight(category=category, rule_ids=rule_ids, limit=3)

    agent_trace = {
        "orchestration": {
            "mode": payload.mode,
            "llm_enabled": composer_llm.enabled,
            "intent": result.get("intent", ""),
            "confidence": result.get("intent_confidence", 0),
            "pipeline": result.get("intent_pipeline", []),
            "nodes_visited": nodes_visited,
            "strategy": "langgraph",
        },
        "kg_analysis": kg_analysis,
        "critic": result.get("critic"),
        "competition": result.get("competition"),
        "learning": result.get("learning"),
        "category": category,
    }

    # ── persist to project state ──
    json_store.append_submission(
        payload.project_id,
        {
            "student_id": payload.student_id,
            "class_id": payload.class_id,
            "cohort_id": payload.cohort_id,
            "source_type": "dialogue_turn",
            "mode": payload.mode,
            "raw_text": payload.message[:6000],
            "diagnosis": diagnosis,
            "next_task": next_task,
            "kg_analysis": kg_analysis,
            "hypergraph_insight": hyper_insight,
            "agent_outputs": agent_trace,
        },
    )

    # ── persist to conversation ──
    conv_store.append_message(payload.project_id, conv_id, {
        "role": "user", "content": payload.message,
    })
    conv_store.append_message(payload.project_id, conv_id, {
        "role": "assistant", "content": assistant_message,
        "agent_trace": agent_trace,
    })

    return DialogueTurnResponse(
        project_id=payload.project_id,
        student_id=payload.student_id,
        conversation_id=conv_id,
        assistant_message=assistant_message.strip(),
        diagnosis=diagnosis,
        next_task=next_task,
        kg_analysis=kg_analysis,
        hypergraph_insight=hyper_insight,
        agent_trace=agent_trace,
    )


@app.post("/api/dialogue/turn-upload")
async def dialogue_turn_upload(
    project_id: str = Form(...),
    student_id: str = Form(...),
    message: str = Form(""),
    conversation_id: str = Form(""),
    mode: str = Form("coursework"),
    file: UploadFile = File(...),
) -> dict:
    """Handle file upload within a conversation context."""
    from app.services.graph_workflow import run_workflow

    upload_target = settings.upload_root / project_id
    upload_target.mkdir(parents=True, exist_ok=True)
    target_path = upload_target / file.filename
    content = await file.read()
    target_path.write_bytes(content)

    extracted = extract_text(target_path)
    if not extracted.strip():
        raise HTTPException(status_code=400, detail="无法解析该文件。")

    combined_msg = f"{message}\n\n[上传文件: {file.filename}]\n{extracted[:3000]}" if message.strip() else f"[上传文件: {file.filename}]\n{extracted[:3000]}"

    # conversation
    conv_id = conversation_id
    conv_messages: list[dict] = []
    if conv_id:
        conv = conv_store.get(project_id, conv_id)
        if conv:
            conv_messages = conv.get("messages", [])
    else:
        new_conv = conv_store.create(project_id, student_id)
        conv_id = new_conv["conversation_id"]

    project_state = json_store.load_project(project_id)
    result = run_workflow(
        message=combined_msg,
        mode=mode,
        project_state=project_state,
        conversation_messages=conv_messages,
    )

    diagnosis = result.get("diagnosis", {})
    next_task = result.get("next_task", {})
    kg_analysis = result.get("kg_analysis", {})
    assistant_message = result.get("assistant_message", "")

    category = result.get("category", "")
    rule_ids = [str(r.get("id")) for r in (diagnosis.get("triggered_rules", []) or []) if isinstance(r, dict)]
    hyper_insight = hypergraph_service.insight(category=category, rule_ids=rule_ids, limit=3)

    json_store.append_submission(project_id, {
        "student_id": student_id,
        "source_type": "file_in_chat",
        "mode": mode,
        "filename": file.filename,
        "raw_text": extracted[:6000],
        "diagnosis": diagnosis,
        "next_task": next_task,
        "kg_analysis": kg_analysis,
        "hypergraph_insight": hyper_insight,
    })

    conv_store.append_message(project_id, conv_id, {
        "role": "user", "content": f"[上传文件: {file.filename}] {message}",
    })
    conv_store.append_message(project_id, conv_id, {
        "role": "assistant", "content": assistant_message,
    })

    return {
        "conversation_id": conv_id,
        "assistant_message": assistant_message,
        "filename": file.filename,
        "extracted_length": len(extracted),
        "diagnosis": diagnosis,
        "next_task": next_task,
        "kg_analysis": kg_analysis,
        "hypergraph_insight": hyper_insight,
        "agent_trace": {
            "intent": result.get("intent", ""),
            "nodes_visited": result.get("nodes_visited", []),
        },
    }


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


@app.get("/api/project/{project_id}/feedback")
def get_project_feedback(project_id: str) -> dict:
    data = json_store.load_project(project_id)
    return {
        "project_id": project_id,
        "feedback": data.get("teacher_feedback", []),
    }


@app.get("/api/teacher/submissions")
def teacher_list_submissions(class_id: str | None = None, cohort_id: str | None = None, limit: int = 50) -> dict:
    projects = json_store.list_projects()
    rows: list[dict[str, Any]] = []
    for project in projects:
        pid = project.get("project_id", "")
        for sub in project.get("submissions", []):
            if class_id and sub.get("class_id") != class_id:
                continue
            if cohort_id and sub.get("cohort_id") != cohort_id:
                continue
            diagnosis = sub.get("diagnosis", {}) if isinstance(sub.get("diagnosis"), dict) else {}
            rows.append({
                "project_id": pid,
                "student_id": sub.get("student_id", ""),
                "class_id": sub.get("class_id"),
                "created_at": sub.get("created_at", ""),
                "source_type": sub.get("source_type", ""),
                "filename": sub.get("filename"),
                "overall_score": diagnosis.get("overall_score", 0),
                "triggered_rules": [r.get("id") for r in diagnosis.get("triggered_rules", []) if isinstance(r, dict)],
                "next_task": (sub.get("next_task") or {}).get("title", ""),
                "text_preview": (sub.get("raw_text") or "")[:120],
            })
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"count": len(rows), "submissions": rows[:limit]}


@app.post("/api/teacher/generate-report")
def teacher_generate_report(class_id: str | None = None, cohort_id: str | None = None) -> dict:
    snapshot = _build_class_snapshot(class_id=class_id, cohort_id=cohort_id)
    if not composer_llm.enabled:
        return {"report": "LLM未启用，无法生成报告。", "snapshot": snapshot}

    report = composer_llm.chat_text(
        system_prompt=(
            "你是教学辅助决策智能体。请基于班级数据生成一份简洁的班级项目潜力评估报告。\n"
            "要求：\n"
            "1. 先给出班级整体概况（提交数、风险分布）\n"
            "2. 列出Top 3高频风险和对应教学建议\n"
            "3. 给出下周重点教学建议（具体可执行）\n"
            "4. 列出需要优先干预的项目特征\n"
            "5. 用自然段落，不超过500字\n"
        ),
        user_prompt=f"班级数据：\n{snapshot}",
        model=settings.llm_reason_model,
        temperature=0.3,
    )
    return {"report": report.strip() if report else "报告生成失败", "snapshot": snapshot}


# ═══════════════════════════════════════════════════════════════════
#  Conversation management APIs
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/conversations")
def list_conversations(project_id: str) -> dict:
    convs = conv_store.list_conversations(project_id)
    return {"project_id": project_id, "conversations": convs}


@app.post("/api/conversations")
def create_conversation(project_id: str, student_id: str) -> dict:
    conv = conv_store.create(project_id, student_id)
    return conv


@app.get("/api/conversations/{conversation_id}")
def get_conversation(project_id: str, conversation_id: str) -> dict:
    conv = conv_store.get(project_id, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


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


@app.post("/api/hypergraph/rebuild")
def rebuild_hypergraph(min_pattern_support: int = 2, max_edges: int = 30) -> dict:
    data = hypergraph_service.rebuild(min_pattern_support=min_pattern_support, max_edges=max_edges)
    return {
        "min_pattern_support": min_pattern_support,
        "max_edges": max_edges,
        "data": data,
    }


@app.get("/api/hypergraph/insight")
def hypergraph_insight(category: str | None = None, rule_ids: str = "", limit: int = 5) -> dict:
    parsed_rule_ids = [x.strip() for x in rule_ids.split(",") if x.strip()]
    data = hypergraph_service.insight(category=category, rule_ids=parsed_rule_ids, limit=limit)
    return {
        "category": category,
        "rule_ids": parsed_rule_ids,
        "limit": limit,
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
