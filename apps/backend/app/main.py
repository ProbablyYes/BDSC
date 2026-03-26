import json
import math
import random
import time
from datetime import datetime
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.schemas import (
    AgentRunPayload,
    AgentRunResponse,
    AnalyzePayload,
    AuthLoginPayload,
    AuthPasswordChangePayload,
    AuthRegisterPayload,
    AuthUserResponse,
    DialogueTurnPayload,
    DialogueTurnResponse,
    HealthResponse,
    ProjectSnapshotResponse,
    SmsLoginPayload,
    SmsSendPayload,
    SmsSendResponse,
    TeamCreatePayload,
    TeamJoinPayload,
    TeamResponse,
    TeacherFeedbackRequest,
    TeacherFeedbackResponse,
    UploadAnalysisResponse,
)
from app.services.agent_router import run_agents
from app.services.case_knowledge import infer_category
from app.services.document_parser import extract_text
from app.services.graph_service import GraphService
from app.services.graph_workflow import init_workflow_services
from app.services.hypergraph_service import HypergraphService
from app.services.llm_client import LlmClient
from app.services.rag_engine import RagEngine
from app.services.storage import ConversationStorage, JsonStorage, TeamStorage, UserStorage
from app.teacher_file_feedback_api import setup_teacher_file_feedback_routes


app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

settings.upload_root.mkdir(parents=True, exist_ok=True)
settings.teacher_examples_root.mkdir(parents=True, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=str(settings.upload_root)), name="uploads")

json_store = JsonStorage(settings.data_root / "project_state")
conv_store = ConversationStorage(settings.data_root / "conversations")
user_store = UserStorage(settings.data_root / "users")
team_store = TeamStorage(settings.data_root / "teams")
graph_service = GraphService(
    uri=settings.neo4j_uri,
    username=settings.neo4j_username,
    password=settings.neo4j_password,
    database=settings.neo4j_database,
)
hypergraph_service = HypergraphService(graph_service=graph_service)
composer_llm = LlmClient()
rag_engine = RagEngine()
rag_engine.initialize()
init_workflow_services(rag_engine=rag_engine, graph_service=graph_service, hypergraph_service=hypergraph_service)

# Setup teacher file feedback routes
setup_teacher_file_feedback_routes(app, json_store, settings)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(timestamp=datetime.utcnow())


# ═══════════════════════════════════════════════════════════════════
#  Auth APIs: register, login, change-password
# ═══════════════════════════════════════════════════════════════════

@app.post("/api/auth/register", response_model=AuthUserResponse)
def auth_register(payload: AuthRegisterPayload) -> AuthUserResponse:
    try:
        user = user_store.create_user(payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AuthUserResponse(status="ok", user=user)


@app.post("/api/auth/login", response_model=AuthUserResponse)
def auth_login(payload: AuthLoginPayload) -> AuthUserResponse:
    user = user_store.authenticate(payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    return AuthUserResponse(status="ok", user=user)


@app.post("/api/auth/change-password", response_model=AuthUserResponse)
def auth_change_password(payload: AuthPasswordChangePayload) -> AuthUserResponse:
    user = user_store.change_password(payload.email, payload.current_password, payload.new_password)
    if not user:
        raise HTTPException(status_code=400, detail="原密码错误或账号不存在")
    return AuthUserResponse(status="ok", user=user)


# ── SMS verification (dev mode: code returned in response) ──

_sms_codes: dict[str, tuple[str, float]] = {}

SMS_CODE_TTL = 300  # 5 min

@app.post("/api/auth/sms/send", response_model=SmsSendResponse)
def sms_send(payload: SmsSendPayload) -> SmsSendResponse:
    phone = payload.phone.strip()
    code = f"{random.randint(0, 999999):06d}"
    _sms_codes[phone] = (code, time.time())
    return SmsSendResponse(status="ok", expires_in=SMS_CODE_TTL, code_hint=code)


@app.post("/api/auth/sms/login", response_model=AuthUserResponse)
def sms_login(payload: SmsLoginPayload) -> AuthUserResponse:
    phone = payload.phone.strip()
    record = _sms_codes.get(phone)
    if not record:
        raise HTTPException(status_code=400, detail="请先获取验证码")
    stored_code, ts = record
    if time.time() - ts > SMS_CODE_TTL:
        _sms_codes.pop(phone, None)
        raise HTTPException(status_code=400, detail="验证码已过期，请重新获取")
    if payload.code.strip() != stored_code:
        raise HTTPException(status_code=400, detail="验证码不正确")
    _sms_codes.pop(phone, None)
    user = user_store.get_or_create_by_phone(phone)
    return AuthUserResponse(status="ok", user=user)


# ── Team Management CRUD ──────────────────────────────────────────────

@app.post("/api/teams")
def create_team(payload: TeamCreatePayload) -> TeamResponse:
    user = user_store.get_by_id(payload.teacher_id)
    if not user or user.get("role") != "teacher":
        raise HTTPException(status_code=403, detail="仅教师可创建团队")
    team = team_store.create_team(
        teacher_id=payload.teacher_id,
        teacher_name=payload.teacher_name or user.get("display_name", ""),
        team_name=payload.team_name,
    )
    return TeamResponse(team=team)


@app.get("/api/teams")
def list_teams(role: str = "", user_id: str = "") -> dict:
    if role == "teacher" and user_id:
        teams = team_store.list_by_teacher(user_id)
    elif role == "student" and user_id:
        teams = team_store.list_by_member(user_id)
    else:
        teams = team_store.list_all()
    for t in teams:
        t["member_count"] = len(t.get("members", []))
    return {"teams": teams}


@app.post("/api/teams/join")
def join_team(payload: TeamJoinPayload) -> TeamResponse:
    team = team_store.find_by_invite_code(payload.invite_code)
    if not team:
        raise HTTPException(status_code=404, detail="邀请码无效或团队不存在")
    updated = team_store.add_member(team["team_id"], payload.user_id)
    return TeamResponse(team=updated or team)


@app.delete("/api/teams/{team_id}")
def delete_team(team_id: str, teacher_id: str = "") -> dict:
    if not teacher_id:
        raise HTTPException(status_code=400, detail="需提供 teacher_id")
    ok = team_store.delete_team(team_id, teacher_id)
    if not ok:
        raise HTTPException(status_code=404, detail="团队不存在或无权删除")
    return {"status": "ok"}


@app.delete("/api/teams/{team_id}/members/{user_id}")
def remove_team_member(team_id: str, user_id: str, teacher_id: str = "") -> TeamResponse:
    team = team_store.get_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="团队不存在")
    if team.get("teacher_id") != teacher_id:
        raise HTTPException(status_code=403, detail="仅团队创建教师可移除成员")
    updated = team_store.remove_member(team_id, user_id)
    return TeamResponse(team=updated or team)


def _aggregate_student_data(user_id: str, include_detail: bool = False) -> dict:
    """Read real submissions from JsonStorage and compute metrics for one student."""
    project_id = f"project-{user_id}"
    project = json_store.load_project(project_id)
    subs = project.get("submissions", [])
    scores = []
    risk_count = 0
    projects_map: dict[str, list] = {}
    for s in subs:
        sc = 0.0
        diag = s.get("diagnosis", {})
        if isinstance(diag, dict):
            sc = float(diag.get("overall_score", 0) or 0)
        if not sc:
            sc = float(s.get("overall_score", 0) or 0)
        if sc > 0:
            scores.append(sc)
        triggered = s.get("triggered_rules") or s.get("diagnosis", {}).get("triggered_rules") or []
        if triggered:
            risk_count += 1
        pid = s.get("project_id", project_id)
        projects_map.setdefault(pid, []).append({**s, "_score": sc})

    avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0
    trend = 0.0
    if len(scores) >= 4:
        mid = len(scores) // 2
        trend = round(sum(scores[mid:]) / (len(scores) - mid) - sum(scores[:mid]) / mid, 1)

    result: dict = {
        "total_submissions": len(subs),
        "project_count": max(1, len(projects_map)),
        "avg_score": avg_score,
        "trend": trend,
        "risk_count": risk_count,
        "last_active": subs[-1].get("created_at", "") if subs else "",
    }

    if include_detail:
        proj_list = []
        for pid, psubs in projects_map.items():
            p_scores = [s["_score"] for s in psubs if s["_score"] > 0]
            proj_list.append({
                "project_id": pid,
                "project_name": pid.replace("project-", "项目·"),
                "submission_count": len(psubs),
                "avg_score": round(sum(p_scores) / len(p_scores), 1) if p_scores else 0,
                "first_score": p_scores[0] if p_scores else 0,
                "latest_score": p_scores[-1] if p_scores else 0,
                "improvement": round(p_scores[-1] - p_scores[0], 1) if len(p_scores) >= 2 else 0,
                "submissions": [
                    {
                        "created_at": s.get("created_at", ""),
                        "overall_score": s["_score"],
                        "source_type": s.get("source_type", "text"),
                        "filename": s.get("filename"),
                        "bottleneck": s.get("diagnosis", {}).get("bottleneck") or s.get("next_task", {}).get("bottleneck", ""),
                        "next_task": s.get("next_task", {}).get("description", "") if isinstance(s.get("next_task"), dict) else str(s.get("next_task", "")),
                        "triggered_rules": s.get("triggered_rules") or s.get("diagnosis", {}).get("triggered_rules", []),
                        "text_preview": (s.get("raw_text") or "")[:80],
                    }
                    for s in psubs
                ],
            })
        result["projects"] = proj_list

    return result


@app.get("/api/teacher/teams")
def teacher_teams(teacher_id: str = "") -> dict:
    """Aggregate real student data per team from TeamStorage + JsonStorage."""
    all_teams_raw = team_store.list_all()
    my_teams = []
    other_teams = []

    for t in all_teams_raw:
        is_mine = t.get("teacher_id") == teacher_id if teacher_id else False
        members = t.get("members", [])
        team_scores: list[float] = []
        team_sub_count = 0
        team_risk = 0
        students = []

        for m in members:
            uid = m.get("user_id", "")
            user_info = user_store.get_by_id(uid)
            display_name = (user_info or {}).get("display_name", uid[:8])
            stats = _aggregate_student_data(uid, include_detail=is_mine)
            stu = {
                "student_id": uid,
                "display_name": display_name,
                "avg_score": stats["avg_score"],
                "total_submissions": stats["total_submissions"],
                "project_count": stats["project_count"],
                "trend": stats["trend"],
                "risk_count": stats["risk_count"],
                "last_active": stats["last_active"],
            }
            if is_mine and "projects" in stats:
                stu["projects"] = stats["projects"]
            students.append(stu)
            team_sub_count += stats["total_submissions"]
            team_risk += stats["risk_count"]
            if stats["avg_score"] > 0:
                team_scores.append(stats["avg_score"])

        team_avg = round(sum(team_scores) / len(team_scores), 1) if team_scores else 0.0
        risk_rate = round(team_risk / max(team_sub_count, 1) * 100, 1)
        team_trend = 0.0
        if len(team_scores) >= 2:
            mid = len(team_scores) // 2
            team_trend = round(
                sum(team_scores[mid:]) / max(1, len(team_scores) - mid)
                - sum(team_scores[:mid]) / max(1, mid), 1
            )

        team_out = {
            "team_id": t["team_id"],
            "team_name": t["team_name"],
            "teacher_name": t.get("teacher_name", ""),
            "invite_code": t.get("invite_code", "") if is_mine else "",
            "is_mine": is_mine,
            "student_count": len(members),
            "avg_score": team_avg,
            "total_submissions": team_sub_count,
            "risk_rate": risk_rate,
            "trend": team_trend,
        }
        if is_mine:
            team_out["students"] = students
        else:
            team_out["students_summary"] = [
                {"student_id": s["student_id"], "display_name": s["display_name"],
                 "avg_score": s["avg_score"], "total_submissions": s["total_submissions"],
                 "trend": s["trend"]}
                for s in students
            ]

        if is_mine:
            my_teams.append(team_out)
        else:
            other_teams.append(team_out)

    return {"my_teams": my_teams, "other_teams": other_teams}


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
        f"## Critic反驳\n反事实追问: {challenge[:6]}\n"
        f"## Planner建议\n执行计划: {plan[:5]}\n"
        f"## 苏格拉底追问\n{socratic[:5]}\n"
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
                "2. 将诊断中发现的所有重要风险都展开讨论，用通俗语言解释为什么这是问题\n"
                "3. 给出唯一的下一步任务，说清楚要做什么、怎么做\n"
                "4. 用苏格拉底式追问收尾——提2-3个让学生深入思考的问题\n"
                "5. 语气像导师跟学生聊天，不要说'根据诊断结果'\n"
                "6. 回复长度600-1200字，宁可长一些也不要丢掉有价值的分析洞察\n"
                "7. 回复末尾附上：⚠ AI生成，仅供参考\n"
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
    agents_called = result.get("agents_called", [])

    hyper_insight = result.get("hypergraph_insight", {})
    hyper_student = result.get("hypergraph_student", {})
    rag_cases = result.get("rag_cases", [])
    web_search = result.get("web_search_result", {})
    import logging as _log
    _log.getLogger("main").info("API response: hyper_student.ok=%s, kg_entities=%d", hyper_student.get("ok"), len(kg_analysis.get("entities", [])))

    agent_trace = {
        "orchestration": {
            "mode": payload.mode,
            "llm_enabled": composer_llm.enabled,
            "intent": result.get("intent", ""),
            "confidence": result.get("intent_confidence", 0),
            "engine": result.get("intent_engine", ""),
            "pipeline": result.get("intent_pipeline", []),
            "nodes_visited": nodes_visited,
            "agents_called": agents_called,
            "strategy": "langgraph_v4_parallel",
        },
        "role_agents": {
            "coach": result.get("coach_output", {}),
            "analyst": result.get("analyst_output", {}),
            "advisor": result.get("advisor_output", {}),
            "tutor": result.get("tutor_output", {}),
            "grader": result.get("grader_output", {}),
            "planner": result.get("planner_output", {}),
        },
        "kg_analysis": kg_analysis,
        "rag_cases": rag_cases,
        "web_search": web_search,
        "hypergraph_student": hyper_student,
        "critic": result.get("critic"),
        "challenge_strategies": result.get("challenge_strategies"),
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
        "agent_trace": {
            **agent_trace,
            "diagnosis": diagnosis,
            "next_task": next_task,
            "kg_analysis": kg_analysis,
            "hypergraph_insight": hyper_insight,
        },
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
        hypergraph_student=hyper_student,
        rag_cases=rag_cases,
        agent_trace=agent_trace,
    )


@app.post("/api/dialogue/turn-stream")
async def dialogue_turn_stream(request: Request):
    """SSE streaming endpoint: runs workflow, then streams orchestrator reply."""
    from app.services.graph_workflow import run_workflow_pre_orchestrate, stream_orchestrator

    payload = await request.json()
    msg = payload.get("message", "")
    project_id = payload.get("project_id", "demo")
    student_id = payload.get("student_id", "student")
    conv_id = payload.get("conversation_id", "")
    mode_val = payload.get("mode", "coursework")

    conv_messages: list[dict] = []
    if conv_id:
        conv = conv_store.get(project_id, conv_id)
        if conv:
            conv_messages = conv.get("messages", [])
    else:
        new_conv = conv_store.create(project_id, student_id)
        conv_id = new_conv["conversation_id"]

    project_state = json_store.load_project(project_id)
    history_context = ""
    for row in (project_state.get("submissions", []) or [])[-4:]:
        snippet = (row.get("raw_text") or "")[:200]
        task = (row.get("next_task") or {}).get("title", "")
        if snippet:
            history_context += f"- {snippet}… → {task}\n"

    teacher_fb = project_state.get("teacher_feedback", [])
    tfb_ctx = ""
    if teacher_fb:
        latest = teacher_fb[-1]
        tfb_ctx = f"{latest.get('comment','')}"

    pre = run_workflow_pre_orchestrate(
        message=msg, mode=mode_val,
        project_state=project_state,
        history_context=history_context,
        conversation_messages=conv_messages,
        teacher_feedback_context=tfb_ctx,
    )

    side_data = {
        "conversation_id": conv_id,
        "diagnosis": pre.get("diagnosis", {}),
        "next_task": pre.get("next_task", {}),
        "kg_analysis": pre.get("kg_analysis", {}),
        "hypergraph_student": pre.get("hypergraph_student", {}),
        "hypergraph_insight": pre.get("hypergraph_insight", {}),
        "rag_cases": pre.get("rag_cases", []),
        "agent_trace": {
            "orchestration": {
                "mode": mode_val,
                "intent": pre.get("intent", ""),
                "confidence": pre.get("intent_confidence", 0),
                "engine": pre.get("intent_engine", ""),
                "agents_called": pre.get("agents_called", []),
            },
            "kg_analysis": pre.get("kg_analysis", {}),
            "rag_cases": pre.get("rag_cases", []),
            "web_search": pre.get("web_search_result", {}),
            "hypergraph_student": pre.get("hypergraph_student", {}),
        },
    }

    def event_stream():
        yield f"data: {json.dumps({'type': 'meta', 'data': side_data}, ensure_ascii=False)}\n\n"

        full_text = ""
        for chunk in stream_orchestrator(pre):
            full_text += chunk
            yield f"data: {json.dumps({'type': 'token', 'data': chunk}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'data': full_text}, ensure_ascii=False)}\n\n"

        conv_store.append_message(project_id, conv_id, {"role": "user", "content": msg})
        conv_store.append_message(project_id, conv_id, {
            "role": "assistant", "content": full_text,
            "agent_trace": side_data.get("agent_trace", {}),
        })

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _build_doc_sections(parsed_doc) -> list[dict]:
    """Merge small segments into logical sections for document review."""
    sections: list[dict] = []
    buf_text = ""
    buf_source = ""
    for seg in parsed_doc.segments:
        text = seg.text.strip()
        if not text:
            continue
        is_heading = (
            text.startswith("#")
            or (len(text) < 80 and text.isupper())
            or (len(text) < 60 and seg.source_unit.startswith("slide"))
        )
        if is_heading and buf_text:
            sections.append({"id": len(sections), "source": buf_source, "text": buf_text.strip()})
            buf_text = ""
            buf_source = ""
        buf_text += text + "\n"
        if not buf_source:
            buf_source = seg.source_unit
        if len(buf_text) > 800:
            sections.append({"id": len(sections), "source": buf_source, "text": buf_text.strip()})
            buf_text = ""
            buf_source = ""
    if buf_text.strip():
        sections.append({"id": len(sections), "source": buf_source, "text": buf_text.strip()})
    return sections[:40]


@app.post("/api/dialogue/turn-upload")
async def dialogue_turn_upload(
    project_id: str = Form(...),
    student_id: str = Form(...),
    class_id: str = Form(""),
    cohort_id: str = Form(""),
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

    from app.services.document_parser import parse_document
    parsed_doc = parse_document(target_path)
    extracted = parsed_doc.full_text
    if not extracted.strip():
        raise HTTPException(status_code=400, detail="无法解析该文件。")

    doc_sections = _build_doc_sections(parsed_doc)

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
    # 如果没有指定class_id，从project_state的最新提交中获取
    if not class_id and project_state.get("submissions"):
        class_id = project_state["submissions"][-1].get("class_id", "")
    if not cohort_id and project_state.get("submissions"):
        cohort_id = project_state["submissions"][-1].get("cohort_id", "")
    
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
    hyper_insight = result.get("hypergraph_insight", {})
    hyper_student = result.get("hypergraph_student", {})
    agents_called = result.get("agents_called", [])

    agent_trace = {
        "orchestration": {
            "mode": mode,
            "intent": result.get("intent", ""),
            "confidence": result.get("intent_confidence", 0),
            "engine": result.get("intent_engine", "file_detect"),
            "pipeline": result.get("intent_pipeline", []),
            "nodes_visited": result.get("nodes_visited", []),
            "agents_called": agents_called,
            "strategy": "langgraph_v4_parallel",
        },
        "role_agents": {
            "coach": result.get("coach_output", {}),
            "analyst": result.get("analyst_output", {}),
            "advisor": result.get("advisor_output", {}),
            "tutor": result.get("tutor_output", {}),
            "grader": result.get("grader_output", {}),
            "planner": result.get("planner_output", {}),
        },
        "kg_analysis": kg_analysis,
        "rag_cases": result.get("rag_cases", []),
        "web_search": result.get("web_search_result", {}),
        "hypergraph_student": hyper_student,
        "critic": result.get("critic"),
        "competition": result.get("competition"),
        "learning": result.get("learning"),
        "category": result.get("category", ""),
    }

    json_store.append_submission(project_id, {
        "student_id": student_id,
        "class_id": class_id or None,
        "cohort_id": cohort_id or None,
        "source_type": "file_in_chat",
        "mode": mode,
        "filename": file.filename,
        "raw_text": extracted[:6000],
        "diagnosis": diagnosis,
        "next_task": next_task,
        "kg_analysis": kg_analysis,
        "hypergraph_insight": hyper_insight,
        "agent_outputs": agent_trace,
    })

    file_url = f"/uploads/{project_id}/{file.filename}"

    # Generate annotations synchronously so they persist in the conversation
    doc_annotations: list[dict] = []
    if doc_sections and composer_llm.enabled:
        batch_text = ""
        for s in doc_sections[:20]:
            batch_text += f"\n[Section {s['id']}]\n{s['text'][:500]}\n"
        ann_result = composer_llm.chat_json(
            system_prompt=(
                "你是一位资深创业导师，正在逐段审阅学生的商业计划书。\n"
                "针对每个Section，给出简短但有针对性的批注（1-3句话）。\n"
                "批注类型: praise(亮点)、issue(问题)、suggestion(建议)、question(追问)\n"
                "如果某个段落没什么好批注的，可以跳过。\n\n"
                '输出JSON: {"annotations": [\n'
                '  {"section_id": 0, "type": "issue", "comment": "..."},\n'
                '  {"section_id": 1, "type": "praise", "comment": "..."},\n'
                "  ...\n]}"
            ),
            user_prompt=f"模式: {mode}\n以下是学生文档的各个段落:\n{batch_text}",
            temperature=0.3,
        )
        doc_annotations = (ann_result or {}).get("annotations", [])

    conv_store.append_message(project_id, conv_id, {
        "role": "user", "content": f"[上传文件: {file.filename}] {message}",
    })
    conv_store.append_message(project_id, conv_id, {
        "role": "assistant", "content": assistant_message,
        "agent_trace": {
            **agent_trace,
            "diagnosis": diagnosis,
            "next_task": next_task,
            "kg_analysis": kg_analysis,
            "hypergraph_insight": hyper_insight,
            "doc_sections": doc_sections,
            "doc_annotations": doc_annotations,
            "file_url": file_url,
            "filename": file.filename,
        },
    })

    return {
        "conversation_id": conv_id,
        "assistant_message": assistant_message,
        "filename": file.filename,
        "file_url": file_url,
        "extracted_length": len(extracted),
        "diagnosis": diagnosis,
        "next_task": next_task,
        "kg_analysis": kg_analysis,
        "hypergraph_insight": hyper_insight,
        "hypergraph_student": hyper_student,
        "rag_cases": result.get("rag_cases", []),
        "agent_trace": agent_trace,
        "doc_sections": doc_sections,
        "doc_annotations": doc_annotations,
    }


@app.post("/api/document-review")
def document_review(payload: dict):
    """LLM-based section-by-section document annotation."""
    from app.services.llm_client import LlmClient
    llm = LlmClient()
    sections = payload.get("sections", [])
    mode = payload.get("mode", "coursework")
    context = payload.get("context", "")

    if not sections or not llm.enabled:
        return {"annotations": []}

    batch_text = ""
    for s in sections[:20]:
        batch_text += f"\n[Section {s['id']}]\n{s['text'][:500]}\n"

    result = llm.chat_json(
        system_prompt=(
            "你是一位资深创业导师，正在逐段审阅学生的商业计划书。\n"
            "针对每个Section，给出简短但有针对性的批注（1-3句话）。\n"
            "批注类型: praise(亮点)、issue(问题)、suggestion(建议)、question(追问)\n"
            "如果某个段落没什么好批注的，可以跳过(不必为每段都批注)。\n\n"
            '输出JSON: {"annotations": [\n'
            '  {"section_id": 0, "type": "issue", "comment": "..."},\n'
            '  {"section_id": 1, "type": "praise", "comment": "..."},\n'
            '  ...\n'
            "]}"
        ),
        user_prompt=(
            f"模式: {mode}\n"
            + (f"对话背景: {context[:300]}\n\n" if context else "")
            + f"以下是学生文档的各个段落:\n{batch_text}"
        ),
        temperature=0.3,
    )

    annotations = (result or {}).get("annotations", [])
    return {"annotations": annotations}


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
                "full_text": (sub.get("raw_text") or "")[:4000],
                "kg_analysis": sub.get("kg_analysis"),
                "bottleneck": diagnosis.get("bottleneck", ""),
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

    enriched = _enrich_docs_in_conversation(conv, project_id)
    if enriched:
        _save_conv(project_id, conversation_id, conv)

    return conv


def _enrich_docs_in_conversation(conv: dict, project_id: str) -> bool:
    """Lazy migration: retroactively add doc_sections to old conversations.

    Scans messages for file uploads that lack doc_sections in their
    corresponding assistant agent_trace.  Parses the file from disk and
    patches the trace.  Returns True if anything was enriched (caller
    should persist).
    """
    import re
    from app.services.document_parser import parse_document

    _UPLOAD_RE = re.compile(r"\[上传文件:\s*(.+?)\]")
    messages = conv.get("messages", [])
    changed = False

    for i, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        m = _UPLOAD_RE.search(msg.get("content", ""))
        if not m:
            continue
        filename = m.group(1).strip()

        # Find the next assistant message
        assist = None
        for j in range(i + 1, min(i + 3, len(messages))):
            if messages[j].get("role") == "assistant":
                assist = messages[j]
                break
        if assist is None:
            continue

        trace = assist.get("agent_trace")
        if not isinstance(trace, dict):
            trace = {}
            assist["agent_trace"] = trace

        if trace.get("doc_sections"):
            continue

        file_path = settings.upload_root / project_id / filename
        if not file_path.exists():
            continue

        try:
            parsed = parse_document(file_path)
            sections = _build_doc_sections(parsed)
        except Exception:
            continue

        if not sections:
            continue

        file_url = f"/uploads/{project_id}/{filename}"
        trace["doc_sections"] = sections
        trace["doc_annotations"] = []
        trace["file_url"] = file_url
        trace["filename"] = filename
        changed = True

    return changed


def _save_conv(project_id: str, conversation_id: str, conv: dict) -> None:
    """Persist enriched conversation data back to disk."""
    import json as _json

    path = conv_store._conv_dir(project_id) / f"{conversation_id}.json"
    if path.exists():
        path.write_text(
            _json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8"
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
    # Helper function to generate summary from filename and diagnosis
    def generate_file_summary(filename: str, diagnosis: dict, raw_text: str) -> str:
        """生成文件摘要，显示项目核心信息"""
        summary_parts = []
        
        # Extract project name from filename (remove pdf extension and hash)
        project_name = filename.rsplit("-", 1)[0] if "-" in filename else filename
        project_name = project_name.replace(".pdf", "").replace(".docx", "").strip()
        summary_parts.append(f"项目：{project_name}")
        
        # Add diagnosis bottleneck if available
        if diagnosis and diagnosis.get("bottleneck"):
            bottleneck = diagnosis["bottleneck"]
            # Limit bottleneck length to ~100 chars
            if len(bottleneck) > 100:
                bottleneck = bottleneck[:100] + "..."
            summary_parts.append(f"瓶颈：{bottleneck}")
        
        # Add overall score if available
        if diagnosis and diagnosis.get("overall_score") is not None:
            score = diagnosis["overall_score"]
            summary_parts.append(f"评分：{score:.2f}")
        
        return " | ".join(summary_parts)
    
    # Get Neo4j evidence data
    neo4j_data = graph_service.project_evidence(project_id=project_id)
    
    # Get student file submissions from JSON
    project_state = json_store.load_project(project_id)
    
    file_submissions = []
    
    if project_state and "submissions" in project_state:
        for idx, submission in enumerate(project_state["submissions"]):
            source_type = submission.get("source_type")
            
            # Only include file submissions
            if source_type not in ["file", "file_in_chat"]:
                continue
            
            # Build file evidence entry
            raw_text = submission.get("raw_text", "")
            diagnosis = submission.get("diagnosis", {})
            filename = submission.get("filename", "unknown")
            
            # Generate summary instead of full preview
            summary = generate_file_summary(filename, diagnosis, raw_text)
            
            file_evidence = {
                "type": "student_submission",
                "filename": filename,
                "student_id": submission.get("student_id", ""),
                "submission_id": submission.get("submission_id", ""),
                "created_at": submission.get("created_at", ""),
                "summary": summary,  # Key summary instead of long preview
                "diagnosis": diagnosis,
            }
            file_submissions.append(file_evidence)
    
    # Build response: always include file_submissions even if Neo4j fails
    # Create a base response structure that works with or without Neo4j data
    if neo4j_data and "error" not in neo4j_data:
        # Neo4j data is valid, use it as base
        merged_data = neo4j_data.copy()
    else:
        # Neo4j failed or no data, create minimal structure
        merged_data = {
            "project": {
                "project_id": project_id,
                "project_name": project_state.get("project_id", project_id) if project_state else project_id,
                "category": "unknown",
                "confidence": 0
            },
            "evidence": [],
            "rubric_coverage": [],
            "risk_rules": []
        }
    
    # Always add file submissions
    merged_data["file_submissions"] = file_submissions
    
    return {
        "project_id": project_id,
        "data": merged_data,
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
            # 复合规则ID？
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


# ═══════════════════════════════════════════════════════════════════
#  Enhanced Teacher APIs (V2: Capability Map, Rubric, Rule Coverage)
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/teacher/capability-map/{class_id}")
def teacher_capability_map(class_id: str, cohort_id: str | None = None) -> dict:
    """班级能力映射雷达图：5维度（基于学生提交的文件数据）"""
    # 从JSON数据源获取班级的所有文件提交
    projects = json_store.list_projects()
    submissions = []
    for project in projects:
        for sub in project.get("submissions", []):
            # 只统计文件提交（file 或 file_in_chat）
            source_type = sub.get("source_type", "")
            if source_type not in ["file", "file_in_chat"]:
                continue
            if sub.get("class_id") != class_id:
                continue
            if cohort_id and sub.get("cohort_id") != cohort_id:
                continue
            submissions.append(sub)
    
    if not submissions:
        return {
            "class_id": class_id,
            "submission_count": 0,
            "data_source": "json_file_only",
            "dimensions": [
                {"name": "痛点发现 (Empathy)", "score": 0, "max": 10},
                {"name": "方案策划 (Ideation)", "score": 0, "max": 10},
                {"name": "商业建模 (Business)", "score": 0, "max": 10},
                {"name": "资源杠杆 (Execution)", "score": 0, "max": 10},
                {"name": "路演表达 (Pitching)", "score": 0, "max": 10},
            ],
            "radar_avg": [0] * 5,
        }
    
    dimension_scores = {"empathy": [], "ideation": [], "business": [], "execution": [], "pitching": []}
    diagnosis_keywords = {
        "empathy": ["痛点", "需求", "用户", "验证"],
        "ideation": ["方案", "设计", "创新", "功能"],
        "business": ["盈利", "商业模式", "定价", "收入"],
        "execution": ["资源", "团队", "执行", "里程碑"],
        "pitching": ["路演", "表达", "叙事", "数据"],
    }
    
    for sub in submissions:
        diagnosis = sub.get("diagnosis", {}) if isinstance(sub.get("diagnosis"), dict) else {}
        overall_score = _safe_float(diagnosis.get("overall_score", 0))
        
        # 根据诊断中的关键词计算各维度评分
        raw_text = str(sub.get("raw_text") or "").lower()
        
        for dim_name, keywords in diagnosis_keywords.items():
            keyword_hit_count = sum(1 for kw in keywords if kw in raw_text)
            score = min(10, overall_score * 0.7 + keyword_hit_count * 0.3)
            dimension_scores[dim_name].append(score)
    
    # 计算平均分
    dimension_names = ["痛点发现 (Empathy)", "方案策划 (Ideation)", "商业建模 (Business)", 
                       "资源杠杆 (Execution)", "路演表达 (Pitching)"]
    dimension_keys = list(dimension_scores.keys())
    radar_avg = []
    dimensions = []
    
    for i, (name, key) in enumerate(zip(dimension_names, dimension_keys)):
        scores = dimension_scores[key]
        avg_score = round(sum(scores) / len(scores), 2) if scores else 0
        dimensions.append({"name": name, "score": avg_score, "max": 10})
        radar_avg.append(avg_score)
    
    return {
        "class_id": class_id,
        "submission_count": len(submissions),
        "data_source": "json_file_only",
        "dimensions": dimensions,
        "radar_avg": radar_avg,
        "student_count": len(set(s.get("student_id") for s in submissions)),
    }


@app.get("/api/teacher/rule-coverage/{class_id}")
def teacher_rule_coverage(class_id: str, cohort_id: str | None = None) -> dict:
    """规则检查覆盖率：H1-H15规则在班级中的触发情况（基于学生提交的文件数据）"""
    # 规则定义（H1-H15）
    rules = {
        "H1": "客户--价值主张错位",
        "H2": "渠道不可达",
        "H3": "定价无支付意愿证据",
        "H4": "TAM/SAM/SOM 口径混乱",
        "H5": "需求证据不足",
        "H6": "竞品对比不可比",
        "H7": "创新点不可验证",
        "H8": "单位经济不成立",
        "H9": "增长逻辑跳跃",
        "H10": "里程碑不可交付",
        "H11": "合规/伦理缺口",
        "H12": "技术路线与资源不匹配",
        "H13": "实验设计不合格",
        "H14": "路演叙事断裂",
        "H15": "评分项证据覆盖不足",
    }
    
    # 从JSON数据源查询班级的规则覆盖率数据（只统计文件提交）
    projects = json_store.list_projects()
    rule_coverage = {}
    total_submissions = 0
    
    for rule_id in rules:
        rule_coverage[rule_id] = {"name": rules[rule_id], "hit_count": 0, "projects": []}
    
    for project in projects:
        for sub in project.get("submissions", []):
            # 只统计文件提交（file 或 file_in_chat）
            source_type = sub.get("source_type", "")
            if source_type not in ["file", "file_in_chat"]:
                continue
            if sub.get("class_id") != class_id:
                continue
            if cohort_id and sub.get("cohort_id") != cohort_id:
                continue
            total_submissions += 1
            diagnosis = sub.get("diagnosis", {}) if isinstance(sub.get("diagnosis"), dict) else {}
            triggered_rules = diagnosis.get("triggered_rules", []) or []
            
            for rule in triggered_rules:
                if isinstance(rule, dict):
                    rule_id = str(rule.get("id", "")).upper()
                    if rule_id in rule_coverage:
                        rule_coverage[rule_id]["hit_count"] += 1
                        rule_coverage[rule_id]["projects"].append(sub.get("project_id", ""))
    
    # 生成热力图数据
    heatmap_data = []
    for rule_id in sorted(rules.keys()):
        hit_count = rule_coverage[rule_id]["hit_count"]
        coverage_ratio = round(hit_count / total_submissions, 3) if total_submissions > 0 else 0
        severity = "high" if coverage_ratio > 0.4 else "medium" if coverage_ratio > 0.2 else "low"
        
        heatmap_data.append({
            "rule_id": rule_id,
            "rule_name": rules[rule_id],
            "hit_count": hit_count,
            "coverage_ratio": coverage_ratio,
            "severity": severity,
        })
    
    return {
        "class_id": class_id,
        "total_submissions": total_submissions,
        "data_source": "json_file_only",
        "rule_coverage": heatmap_data,
        "high_risk_count": sum(1 for r in heatmap_data if r["severity"] == "high"),
    }


@app.get("/api/teacher/project/{project_id}/deep-diagnosis")
def teacher_project_deep_diagnosis(project_id: str) -> dict:
    """项目深度诊断：瓶颈、影响、修复建议"""
    project_state = json_store.load_project(project_id)
    submissions = project_state.get("submissions", []) or []
    
    if not submissions:
        return {
            "project_id": project_id,
            "error": "该项目还没有提交记录",
        }
    
    # 取最新提交
    latest_sub = submissions[-1]
    diagnosis = latest_sub.get("diagnosis", {}) if isinstance(latest_sub.get("diagnosis"), dict) else {}
    next_task = latest_sub.get("next_task", {}) or {}
    triggered_rules = diagnosis.get("triggered_rules", []) or []
    
    # 构建修复方案
    fix_strategies = []
    for rule in triggered_rules[:3]:
        if isinstance(rule, dict):
            rule_id = str(rule.get("id", ""))
            rule_name = str(rule.get("name", ""))
            severity = str(rule.get("severity", "medium"))
            
            # 根据规则ID生成修复建议
            fix_map = {
                "H1": "重新定义目标客户群体，验证他们对该价值主张的需求程度",
                "H2": "分析客户获取路径，确保渠道能够有效触达目标用户",
                "H3": "通过用户访谈/调查收集支付意愿的直接证据",
                "H4": "清晰定义TAM/SAM/SOM，确保口径统一",
                "H5": "补充真实用户访谈记录、行为数据或第三方报告",
                "H6": "选择可比的竞品，说明差异点的商业意义",
                "H7": "通过实验/原型验证创新点的技术可行性",
                "H8": "重新计算单位经济：CAC、LTV、毛利率等指标",
                "H9": "补充增长逻辑的中间步骤，确保因果关系合理",
                "H10": "细化里程碑，确保每个里程碑都有明确的交付物与时间表",
                "H11": "咨询行业专家，评估合规/伦理风险，给出缓解方案",
                "H12": "调整技术路线或补充资源计划，确保匹配度",
                "H13": "设计受控的A/B实验或前后对比研究",
                "H14": "重新组织路演逻辑，确保故事有起承转合",
                "H15": "对标Rubric，逐项补齐缺失的证据",
            }
            
            fix_strategy = fix_map.get(rule_id, f"针对规则{rule_id}进行改进")
            fix_strategies.append({
                "rule_id": rule_id,
                "rule_name": rule_name,
                "severity": severity,
                "fix_strategy": fix_strategy,
            })
    
    bottleneck = str(diagnosis.get("bottleneck", "暂无诊断"))
    overall_score = _safe_float(diagnosis.get("overall_score", 0))
    
    return {
        "project_id": project_id,
        "student_id": latest_sub.get("student_id", ""),
        "submission_count": len(submissions),
        "latest_submission_time": latest_sub.get("created_at", ""),
        "overall_score": overall_score,
        "bottleneck": bottleneck,
        "bottleneck_impact": f"该瓶颈可能导致项目在以下方面受阻：评分降低、融资难度增加、用户获取成本上升",
        "triggered_rules": triggered_rules[:5],
        "fix_strategies": fix_strategies,
        "next_task": next_task,
        "socratic_questions": diagnosis.get("socratic_questions", [])[:3],
    }


@app.get("/api/teacher/project/{project_id}/rubric-assessment")
def teacher_rubric_assessment(project_id: str) -> dict:
    """形成性评价：Rubric评分表（9个维度R1-R9）"""
    project_state = json_store.load_project(project_id)
    submissions = project_state.get("submissions", []) or []
    
    if not submissions:
        return {
            "project_id": project_id,
            "error": "该项目还没有提交记录",
        }
    
    latest_sub = submissions[-1]
    diagnosis = latest_sub.get("diagnosis", {}) if isinstance(latest_sub.get("diagnosis"), dict) else {}
    raw_text = str(latest_sub.get("raw_text", "") or "")
    
    # Rubric定义
    rubric_items = [
        {"id": "R1", "name": "问题定义", "description": "问题清晰、具体，基于真实用户痛点", "weight": 0.1},
        {"id": "R2", "name": "用户证据强度", "description": "声明由充分且相关的证据支持", "weight": 0.15},
        {"id": "R3", "name": "方案可行性", "description": "方案在技术和运营上都可行", "weight": 0.1},
        {"id": "R4", "name": "商业模式一致性", "description": "客户、价值、渠道、收入、成本之间逻辑一致", "weight": 0.15},
        {"id": "R5", "name": "市场与竞争", "description": "市场规模估算和竞争分析合理", "weight": 0.1},
        {"id": "R6", "name": "财务逻辑", "description": "单位经济和财务假设合理", "weight": 0.1},
        {"id": "R7", "name": "创新与差异化", "description": "有清晰的差异化优势和可验证的优点", "weight": 0.1},
        {"id": "R8", "name": "团队与执行", "description": "团队能力与项目雄心相匹配", "weight": 0.05},
        {"id": "R9", "name": "展示与材料质量", "description": "材料清晰、逻辑连贯、有说服力", "weight": 0.05},
    ]
    
    # 根据诊断数据估算评分（0-5分制）
    rubric_scores = []
    overall_weighted_score = 0
    
    for item in rubric_items:
        item_id = item["id"]
        
        # 基于历史数据和规则触发情况进行评分
        score = 3  # 默认中等
        
        # 根据关键词和规则调整
        if item_id == "R1":
            score = 3 if "痛点" in raw_text or "需求" in raw_text else 2
        elif item_id == "R2":
            score = 4 if len(diagnosis.get("triggered_rules", [])) < 3 else 2
        elif item_id == "R3":
            score = 3 if "技术" in raw_text else 2
        elif item_id == "R4":
            score = 2 if "H1" in str(diagnosis.get("triggered_rules", [])) else 4
        elif item_id == "R5":
            score = 3 if "市场" in raw_text or "竞争" in raw_text else 2
        elif item_id == "R6":
            score = 2 if "H8" in str(diagnosis.get("triggered_rules", [])) else 3
        elif item_id == "R7":
            score = 3 if "创新" in raw_text else 2
        elif item_id == "R8":
            score = 3 if "团队" in raw_text else 2
        elif item_id == "R9":
            score = _safe_float(diagnosis.get("overall_score", 3)) / 2
        
        score = max(0, min(5, round(score, 1)))
        overall_weighted_score += score * item["weight"]
        
        # 生成修改建议
        revision_suggestions = {
            "R1": "补充至少2名真实用户的访谈记录，说明他们的具体痛点和频率",
            "R2": "提供量化的用户验证数据（如调查样本数、转化率）",
            "R3": "明确技术实现路线，细化MVP设计与资源需求",
            "R4": "绘制商业模式画布，确保5个要素相互支持",
            "R5": "用TAM/SAM/SOM三层法估算市场规模，列出主要竞品表",
            "R6": "详细计算CAC、LTV、毛利率等核心单位经济指标",
            "R7": "准备竞品对比表，说明该方案相比竞品的3个核心优势",
            "R8": "列出团队成员背景，说明各自在项目中的关键角色",
            "R9": "重新组织Pitch大纲，确保有明确的开头、3个主体论点、结尾",
        }
        
        rubric_scores.append({
            "item_id": item_id,
            "item_name": item["name"],
            "description": item["description"],
            "score": score,
            "max_score": 5,
            "weight": item["weight"],
            "revision_suggestion": revision_suggestions.get(item_id, ""),
            "evidence_quotes": raw_text[:100],  # 简化的证据引用
        })
    
    return {
        "project_id": project_id,
        "student_id": latest_sub.get("student_id", ""),
        "evaluation_time": datetime.utcnow().isoformat(),
        "rubric_items": rubric_scores,
        "overall_weighted_score": round(overall_weighted_score, 2),
        "max_weighted_score": 5.0,
        "missing_evidence": ["用户验证数据", "竞品对比", "财务模型"],
    }


@app.get("/api/teacher/project/{project_id}/competition-score")
def teacher_competition_score_predict(project_id: str) -> dict:
    """竞赛评分预测与快速修复清单"""
    project_state = json_store.load_project(project_id)
    submissions = project_state.get("submissions", []) or []
    
    if not submissions:
        return {
            "project_id": project_id,
            "error": "该项目还没有提交记录",
        }
    
    latest_sub = submissions[-1]
    diagnosis = latest_sub.get("diagnosis", {}) if isinstance(latest_sub.get("diagnosis"), dict) else {}
    overall_score = _safe_float(diagnosis.get("overall_score", 0))
    triggered_rules = diagnosis.get("triggered_rules", []) or []
    
    # 竞赛预测评分（模拟）
    competition_score = min(100, max(0, overall_score * 10 + 20 - len(triggered_rules) * 5))
    
    # 计算评分范围，并进行精确的四舍五入
    score_lower = max(0, competition_score - 10)
    score_upper = min(100, competition_score + 10)
    
    # 四舍五入到1位小数
    predicted_score = round(competition_score, 1)
    # 调整范围为十的整倍数
    score_lower_rounded = int(round(score_lower / 10) * 10)
    score_upper_rounded = int(round(score_upper / 10) * 10)
    
    return {
        "project_id": project_id,
        "student_id": latest_sub.get("student_id", ""),
        "predicted_competition_score": predicted_score,
        "score_range": f"{score_lower_rounded}-{score_upper_rounded}",  # 格式化为字符串
        "score_range_min": score_lower_rounded,
        "score_range_max": score_upper_rounded,
        "quick_fixes_24h": [
            "完成高风险规则（H1-H5）的证据补充",
            "制作1页对标用户验证的数据总结",
            "更新Pitch开场和结尾逻辑",
        ],
        "quick_fixes_72h": [
            "完成商业模式画布的全部9个要素",
            "补齐竞品对比表和市场规模估算",
            "制作完整的财务模型（CAC、LTV、BEP）",
            "进行班级内部模拟路演，录制视频",
        ],
        "high_risk_rules_for_competition": [
            {"rule": r.get("id"), "name": r.get("name"), "priority": "高"}
            for r in triggered_rules[:3]
        ] if triggered_rules else [],
    }


@app.get("/api/teacher/teaching-interventions/{class_id}")
def teacher_teaching_interventions(class_id: str, cohort_id: str | None = None) -> dict:
    """教学干预建议：班级共性问题识别与优先级排序"""
    projects = json_store.list_projects()
    rule_frequency = {}
    common_mistakes = {}
    student_count = 0
    
    for project in projects:
        for sub in project.get("submissions", []):
            if sub.get("class_id") != class_id:
                continue
            if cohort_id and sub.get("cohort_id") != cohort_id:
                continue
            
            student_count += 1
            diagnosis = sub.get("diagnosis", {}) if isinstance(sub.get("diagnosis"), dict) else {}
            triggered_rules = diagnosis.get("triggered_rules", []) or []
            
            for rule in triggered_rules:
                if isinstance(rule, dict):
                    rule_id = str(rule.get("id", ""))
                    rule_frequency[rule_id] = rule_frequency.get(rule_id, 0) + 1
    
    if student_count == 0:
        return {
            "class_id": class_id,
            "student_count": 0,
            "error": "班级还没有学生提交记录",
        }
    
    # 识别共性问题（出现在>40%的学生提交中）
    shared_problems = []
    for rule_id, count in sorted(rule_frequency.items(), key=lambda x: x[1], reverse=True):
        ratio = count / student_count
        if ratio > 0.4:
            # 生成教学建议
            teaching_tips = {
                "H1": "组织课堂讨论'客户是谁？他们的痛点是什么？'，用案例引导学生定义清晰的目标用户",
                "H4": "讲授TAM/SAM/SOM三层市场估算法，布置一个市场规模计算作业",
                "H5": "强调'Validation is King'，布置用户访谈作业，要求每人20min访谈至少3个用户",
                "H8": "讲授单位经济学基础，用失败案例展示不健康的CAC/LTV比例有多危险",
                "H14": "组织Pitch工作坊，邀请创业导师进行实时反馈，录制优秀案例供学生学习",
            }
            
            shared_problems.append({
                "rule_id": rule_id,
                "problem_description": f"规则{rule_id}：{count}名学生触发，占比{round(ratio*100)}%",
                "teaching_suggestion": teaching_tips.get(rule_id, f"针对{rule_id}进行专项讲解"),
                "priority": "高" if ratio > 0.6 else "中",
                "estimated_teaching_time": "45分钟 / 1个课时",
            })
    
    return {
        "class_id": class_id,
        "student_count": student_count,
        "total_shared_problems": len(shared_problems),
        "shared_problems": shared_problems[:5],  # Top 5问题
        "recommended_next_class_focus": "针对Top 2-3的共性问题设计专项讲解与练习",
    }
