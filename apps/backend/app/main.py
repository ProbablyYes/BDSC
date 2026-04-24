import json
import logging
import math
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.schemas import (
    AdminBatchCreateUsersPayload,
    AdminChangePasswordPayload,
    AdminUserCreatePayload,
    AdminUserUpdatePayload,
    AgentRunPayload,
    AgentRunResponse,
    AnalyzePayload,
    AuthLoginPayload,
    AuthPasswordChangePayload,
    AuthRegisterPayload,
    AuthUserResponse,
    BusinessPlanExpandPayload,
    BusinessPlanExportPayload,
    BusinessPlanGeneratePayload,
    BusinessPlanQuestionsResponse,
    BusinessPlanResponse,
    BusinessPlanSectionUpdatePayload,
    BusinessPlanSuggestionsResponse,
    BusinessPlanUpgradePayload,
    BusinessPlanForkCompetitionPayload,
    BusinessPlanGradingPayload,
    BusinessPlanGradingResponse,
    BusinessPlanComparePayload,
    BusinessPlanCompareResponse,
    BusinessPlanCoachingModePayload,
    BusinessPlanAgendaApplyPayload,
    BusinessPlanAgendaPatchPayload,
    BusinessPlanAgendaReviewPayload,
    BudgetAIChatPayload,
    BudgetAISuggestPayload,
    BudgetCreatePayload,
    BudgetSavePayload,
    ChatMessageSendPayload,
    ChatReactionPayload,
    ChatRoomAddMemberPayload,
    ChatRoomCreatePayload,
    DialogueTurnPayload,
    DialogueTurnResponse,
    HealthResponse,
    PosterGeneratePayload,
    PosterGenerateResponse,
    ProjectSnapshotResponse,
    ProjectCognitionResponse,
    ProjectCognitionUpdatePayload,
    SmsLoginPayload,
    SmsSendPayload,
    SmsSendResponse,
    SetStudentIdPayload,
    StudentInterventionViewPayload,
    TeamCreatePayload,
    TeamJoinPayload,
    TeamResponse,
    TeacherAssistantAssessmentReviewPayload,
    TeacherAssistantInterventionPayload,
    TeacherAssistantInterventionSendPayload,
    TeacherAssistantSmartSelectFilter,
    TeacherFeedbackRequest,
    TeacherFeedbackResponse,
    TeamUpdatePayload,
    UploadAnalysisResponse,
    VideoAnalysisResponse,
    PosterImageGeneratePayload,
    PosterImageGenerateResponse,
    FinanceReportGeneratePayload,
    FinanceReportResponse,
    FinanceReportStatusResponse,
)
from app.services.diagnosis_engine import RULE_FALLACY_MAP, RULE_EDGE_MAP
from app.services.agent_router import run_agents
from app.services.case_knowledge import infer_category
from app.services.document_parser import extract_text
from app.services.graph_service import GraphService
from app.services.graph_workflow import init_workflow_services
from app.services.hypergraph_service import HypergraphService
from app.services.llm_client import LlmClient
from app.services.image_client import ImageClient
from app.services.video_pitch_analyzer import VideoPitchAnalyzer
from app.services.rag_engine import RagEngine
from app.services.business_plan_service import BusinessPlanService, BusinessPlanStorage
from app.services.budget_storage import BudgetStorage
from app.services.finance_report_service import FinanceReportService
from app.services.finance_guard import scan_message as finance_guard_scan
from app.services.finance_signal_extractor import (
    extract_finance_signals as finance_signal_extract,
    apply_signals_to_budget as finance_signal_apply,
)
from app.services import finance_baseline_service
from app.services.chat_storage import ChatStorage
from app.services.project_cognition import describe_track_vector, ensure_project_cognition
from app.services.storage import ConversationStorage, JsonStorage, TeamStorage, UserStorage
from app.services.track_inference import infer_project_stage_v2, infer_track_vector, merge_track_vector
from app.teacher_file_feedback_api import setup_teacher_file_feedback_routes


logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RuntimeError)
async def _runtime_error_handler(request: Request, exc: RuntimeError):
    """
    存储层 _safe_read_json 在 JSON 损坏时会抛 RuntimeError（带详细原因 + 备份文件名）。
    这里统一转成 500，避免前端看到空响应或 "邮箱或密码错误" 这类迷惑性文案。
    """
    from fastapi.responses import JSONResponse
    logger.error("RuntimeError on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"status": "server_error", "detail": str(exc)},
    )

settings.upload_root.mkdir(parents=True, exist_ok=True)
settings.video_upload_root.mkdir(parents=True, exist_ok=True)
settings.teacher_examples_root.mkdir(parents=True, exist_ok=True)

# 学生文档上传（计划书等）
app.mount("/uploads", StaticFiles(directory=str(settings.upload_root)), name="uploads")

# 路演视频上传，可按需用于日后预览
app.mount("/video_uploads", StaticFiles(directory=str(settings.video_upload_root)), name="video_uploads")

json_store = JsonStorage(settings.data_root / "project_state")
conv_store = ConversationStorage(settings.data_root / "conversations")
user_store = UserStorage(settings.data_root / "users")
team_store = TeamStorage(settings.data_root / "teams")
chat_store = ChatStorage(settings.data_root / "chat")
budget_store = BudgetStorage(settings.data_root / "budgets")
business_plan_store = BusinessPlanStorage(settings.data_root / "business_plans")
business_plan_exports_root = settings.data_root / "exports"
business_plan_exports_root.mkdir(parents=True, exist_ok=True)

# ── 教师订正层 + 证据回定 ──
from app.services.ai_override_store import AiOverrideStore, walk_and_apply as _ov_walk_apply  # noqa: E402
from app.services.evidence_link import EvidenceLinker, set_default_linker  # noqa: E402

ai_override_store = AiOverrideStore(settings.data_root / "ai_overrides")
evidence_linker = EvidenceLinker(conv_store)
set_default_linker(evidence_linker)

chat_files_root = settings.data_root / "chat_files"
chat_files_root.mkdir(parents=True, exist_ok=True)
app.mount("/chat_files", StaticFiles(directory=str(chat_files_root)), name="chat_files")

# WebSocket connection manager for chat
_ws_rooms: dict[str, dict[str, WebSocket]] = {}
_main_loop = None  # captured on first WebSocket connect

graph_service = GraphService(
    uri=settings.neo4j_uri,
    username=settings.neo4j_username,
    password=settings.neo4j_password,
    database=settings.neo4j_database,
)
hypergraph_service = HypergraphService(graph_service=graph_service)
composer_llm = LlmClient()
image_client = ImageClient()
rag_engine = RagEngine()
rag_engine.initialize()

# 启动时探活 Neo4j。若实例被暂停（Aura Free 常见）或不可达，则降级为无图谱模式，
# 避免每次 gather_context 被 55s 超时拖累，并在日志中提示如何恢复。
_neo4j_disable_env = os.getenv("DISABLE_NEO4J", "").strip().lower() in ("1", "true", "yes", "on")
_graph_service_for_workflow = graph_service
if _neo4j_disable_env:
    logger.warning("Neo4j disabled via DISABLE_NEO4J env; running in graph-less mode.")
    _graph_service_for_workflow = None
else:
    try:
        _probe = graph_service.health()
        if not _probe.connected:
            logger.warning(
                "Neo4j probe failed (%s). Falling back to graph-less mode. "
                "Wake the Aura instance at console.neo4j.io or set DISABLE_NEO4J=1 to silence this.",
                _probe.detail,
            )
            _graph_service_for_workflow = None
        else:
            logger.info("Neo4j probe ok: %s", _probe.detail)
    except Exception as _probe_exc:  # noqa: BLE001
        logger.warning("Neo4j probe exception, falling back to graph-less mode: %s", _probe_exc)
        _graph_service_for_workflow = None

init_workflow_services(
    rag_engine=rag_engine,
    graph_service=_graph_service_for_workflow,
    hypergraph_service=hypergraph_service if _graph_service_for_workflow else None,
)
business_plan_service = BusinessPlanService(
    storage=business_plan_store,
    json_store=json_store,
    conv_store=conv_store,
    llm=composer_llm,
    rag_engine=rag_engine,
    graph_service=graph_service,
)
finance_report_service = FinanceReportService(
    data_root=settings.data_root / "finance_reports",
    budget_store=budget_store,
    conv_store=conv_store,
    json_store=json_store,
    llm=composer_llm,
)

def _background_hyper_rebuild():
    """Run hypergraph rebuild in background so it doesn't block server startup."""
    import threading
    def _do():
        try:
            result = hypergraph_service.rebuild(min_pattern_support=1, max_edges=400)
            logger.info("Hypergraph background rebuild done: %s edges, %s nodes",
                        result.get("total_edges"), result.get("total_nodes"))
        except Exception as exc:
            logger.warning("Hypergraph background rebuild failed (non-fatal): %s", exc)
    t = threading.Thread(target=_do, daemon=True)
    t.start()

_background_hyper_rebuild()


@app.on_event("startup")
async def _capture_event_loop():
    """Capture the main asyncio loop so background threads can broadcast via WebSocket."""
    import asyncio as _aio
    global _main_loop
    _main_loop = _aio.get_running_loop()


@app.on_event("shutdown")
async def _cleanup_neo4j():
    graph_service.close()


# Setup teacher file feedback routes
setup_teacher_file_feedback_routes(app, json_store, settings)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(timestamp=datetime.utcnow())


@app.get("/api/kb-stats")
def kb_stats() -> dict:
    """Return real-time knowledge base statistics from Neo4j + RAG + Hypergraph."""
    neo4j_stats = graph_service.get_kb_stats()
    rag_count = rag_engine.case_count
    rag_embed_ready = rag_engine.embed_ready
    hyper_summary = hypergraph_service.summary()
    return {
        "neo4j": neo4j_stats,
        "rag": {
            "corpus_count": rag_count,
            "embed_ready": rag_embed_ready,
        },
        "hypergraph_local": hyper_summary,
    }


@app.get("/api/kb-insights")
def kb_insights() -> dict:
    """Return high-frequency entities across dimensions + sample cases for teacher overview."""
    return graph_service.get_kb_insights(limit=8)


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
        # 登录失败也写入访问日志（不记录密码）
        existing = user_store.get_by_email(payload.email) or {}
        role = str(existing.get("role", "")) if existing else ""
        role_label = {"student": "学生", "teacher": "教师", "admin": "管理员"}.get(role, "用户")
        display_name = str(
            (existing.get("display_name") if existing else "")
            or (existing.get("email") if existing else "")
            or payload.email
        )
        user_id = existing.get("user_id") if existing else None
        user_label = f"{role_label}:{display_name}" if display_name else role_label or payload.email
        _append_access_log(
            {
                "time": datetime.utcnow().isoformat() + "Z",
                "user": user_label,
                "user_id": user_id,
                "role": role,
                "display_name": existing.get("display_name") if existing else None,
                "action": "LOGIN_FAILED",
                "detail": "邮箱或密码错误",
                "status": "FAILED",
                "method": "POST",
                "path": "/api/auth/login",
                "status_code": 401,
                "duration_ms": 0,
            }
        )
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    # 记录登录成功到访问日志，包含 user_id 与角色信息
    role = str(user.get("role", ""))
    role_label = {"student": "学生", "teacher": "教师", "admin": "管理员"}.get(role, "用户")
    display_name = str(user.get("display_name") or user.get("email") or user.get("user_id") or "")
    user_label = f"{role_label}:{display_name}" if display_name else role_label
    _append_access_log(
        {
            "time": datetime.utcnow().isoformat() + "Z",
            "user": user_label,
            "user_id": user.get("user_id"),
            "role": role,
            "display_name": user.get("display_name"),
            "action": "LOGIN",
            "detail": "用户密码登录成功",
            "status": "OK",
            "method": "POST",
            "path": "/api/auth/login",
            "status_code": 200,
            "duration_ms": 0,
        }
    )
    return AuthUserResponse(status="ok", user=user)


@app.post("/api/auth/change-password", response_model=AuthUserResponse)
def auth_change_password(payload: AuthPasswordChangePayload) -> AuthUserResponse:
    user = user_store.change_password(payload.email, payload.current_password, payload.new_password)
    if not user:
        raise HTTPException(status_code=400, detail="原密码错误或账号不存在")
    return AuthUserResponse(status="ok", user=user)


@app.patch("/api/auth/me/student-id", response_model=AuthUserResponse)
def auth_set_student_id(payload: SetStudentIdPayload) -> AuthUserResponse:
    """学生在个人中心填入/修改学号（选填，全局唯一）。"""
    try:
        updated = user_store.set_student_id(payload.user_id, payload.student_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not updated:
        raise HTTPException(status_code=404, detail="用户不存在")
    return AuthUserResponse(status="ok", user=updated)


@app.get("/api/project/by-display-id/{display_id}")
def project_by_display_id(display_id: str) -> dict:
    """根据项目编号 P-学号-NN 反查 project_id / conversation_id，便于老师按编号跳转。"""
    target = (display_id or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="项目编号不能为空")
    for project in json_store.list_projects():
        pid = str(project.get("project_id") or "")
        for row in reversed(project.get("submissions", []) or []):
            if str(row.get("logical_project_id", "")) == target:
                return {
                    "status": "ok",
                    "display_id": target,
                    "project_id": pid,
                    "conversation_id": row.get("conversation_id"),
                    "user_id": pid[len("project-"):] if pid.startswith("project-") else None,
                    "submitted_at": row.get("submitted_at"),
                }
    raise HTTPException(status_code=404, detail=f"未找到项目编号 {target}")


# ═══════════════════════════════════════════════════════════════════
#  Admin user management APIs (CRUD, password, class binding)
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/admin/users")
def admin_list_users(role: str = "", class_id: str = "", keyword: str = "") -> dict:
    users = user_store.list_users(role=role or None, class_id=class_id or None, keyword=keyword or None)

    # Build a mapping from user_id -> team names based on TeamStorage/teams.json
    all_teams = team_store.list_all()
    user_team_names: dict[str, list[str]] = {}
    for team in all_teams:
        team_name = _safe_str(team.get("team_name", ""))
        if not team_name:
            continue
        # teacher as team owner
        teacher_uid = _safe_str(team.get("teacher_id", ""))
        if teacher_uid:
            user_team_names.setdefault(teacher_uid, []).append(team_name)
        # student members
        for member in team.get("members", []) or []:
            uid = _safe_str(member.get("user_id", ""))
            if not uid:
                continue
            user_team_names.setdefault(uid, []).append(team_name)

    enriched: list[dict[str, Any]] = []
    for u in users:
        uid = str(u.get("user_id", ""))
        stats = _aggregate_student_data(uid, include_detail=False) if uid else {
            "project_count": 0,
            "last_active": "",
        }
        team_names = user_team_names.get(uid, [])
        enriched.append(
            {
                **u,
                "status": u.get("status", "active"),
                "last_login": u.get("last_login") or stats.get("last_active", ""),
                "project_count": stats.get("project_count", 0),
                "team_names": team_names,
            }
        )
    return {"count": len(enriched), "users": enriched}


@app.post("/api/admin/users")
def admin_create_user(payload: AdminUserCreatePayload) -> dict:
    try:
        user, temp_password = user_store.admin_create_user(payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    uid = str(user.get("user_id", ""))
    stats = _aggregate_student_data(uid, include_detail=False) if uid else {
        "project_count": 0,
        "last_active": "",
    }
    teams = []
    if uid:
        teams.extend(team_store.list_by_member(uid))
        teams.extend(team_store.list_by_teacher(uid))
    team_names = [_safe_str(t.get("team_name", "")) for t in teams if _safe_str(t.get("team_name", ""))]
    user_out = {
        **user,
        "project_count": stats.get("project_count", 0),
        "last_login": stats.get("last_active", ""),
        "team_names": team_names,
    }
    return {"user": user_out, "temp_password": temp_password}


@app.post("/api/admin/users/batch")
def admin_batch_create_users(payload: AdminBatchCreateUsersPayload) -> dict:
    """Batch creation of student/teacher accounts for admin console.

    Business rules (aligned with admin UI requirements):
    - account (登录账号) uses pattern: prefix + zero-padded sequence
    - default password: account + (password_suffix or "123")
    - for students: optional invite_code to join an existing team
    - for teachers: optional team_name / team_invite_code to create teams
    """

    role = payload.role
    prefix = payload.prefix.strip()
    if not prefix:
        raise HTTPException(status_code=400, detail="账号前缀不能为空")

    start_index = int(payload.start_index or 1)
    count = int(payload.count or 1)
    if count <= 0:
        raise HTTPException(status_code=400, detail="创建数量必须大于 0")

    password_suffix = str(payload.password_suffix or "123")
    invite_code = (payload.invite_code or "").strip().upper()
    team_name = (payload.team_name or "").strip()
    team_invite_code = (payload.team_invite_code or "").strip().upper() or None

    # If student invite_code is provided, validate it once up-front.
    target_team: dict[str, Any] | None = None
    if role == "student" and invite_code:
        target_team = team_store.find_by_invite_code(invite_code)  # type: ignore[assignment]
        if not target_team:
            raise HTTPException(status_code=400, detail="邀请码无效或团队不存在")

    created_users: list[dict[str, Any]] = []
    password_list: list[dict[str, str]] = []
    duplicate_accounts: list[str] = []
    duplicate_names: list[str] = []

    for i in range(count):
        seq = start_index + i
        account = f"{prefix}{seq:03d}"
        email = account  # 现有系统以 email 字段作为登录账号

        if user_store.get_by_email(email):
            duplicate_accounts.append(account)
            continue
        # 检查昵称唯一
        display_name = account
        users = user_store._load()
        if display_name and any(str(u.get("display_name", "")).strip() == display_name for u in users):
            duplicate_names.append(display_name)
            continue

        raw_password = f"{account}{password_suffix or '123'}"
        payload_single = {
            "role": role,
            "display_name": account,
            "email": email,
            "student_id": None,
            "password": raw_password,
        }

        try:
            user, _temp_password = user_store.admin_create_user(payload_single)
        except ValueError as e:  # pragma: no cover - defensive
            msg = str(e)
            if "用户名已存在" in msg:
                duplicate_names.append(display_name)
            else:
                duplicate_accounts.append(account)
            continue

        uid = str(user.get("user_id", ""))
        if role == "student" and uid:
            stats = _aggregate_student_data(uid, include_detail=False)
        else:
            stats = {"project_count": 0, "last_active": ""}

        teams = []
        if uid:
            teams.extend(team_store.list_by_member(uid))
            teams.extend(team_store.list_by_teacher(uid))
        team_names = [_safe_str(t.get("team_name", "")) for t in teams if _safe_str(t.get("team_name", ""))]

        user_out = {
            **user,
            "project_count": stats.get("project_count", 0),
            "last_login": user.get("last_login") or stats.get("last_active", ""),
            "team_names": team_names,
        }
        created_users.append(user_out)
        password_list.append({
            "user_id": uid,
            "email": email,
            "password": raw_password,
        })

        # For students, add them to the target team if invite_code provided.
        if role == "student" and target_team and uid:
            team_store.add_member(target_team["team_id"], uid)

        # For teachers, create teams when requested.
        if role == "teacher" and team_name and uid:
            # 多个教师时自动在团队名称后追加序号，避免完全重复
            final_team_name = team_name
            if count > 1:
                final_team_name = f"{team_name}-{i + 1}"
            try:
                team_store.create_team_with_custom_code(
                    teacher_id=uid,
                    teacher_name=user.get("display_name") or user.get("email") or uid,
                    team_name=final_team_name,
                    invite_code=team_invite_code if i == 0 else None,
                )
            except ValueError as e:  # pragma: no cover - validation
                pass  # skip team creation error for batch

    return {
        "status": "ok",
        "count": len(created_users),
        "users": created_users,
        "passwords": password_list,
        "duplicates": duplicate_accounts,
        "duplicate_names": duplicate_names,
        "duplicate_message": (
            ("该账号名已存在" if duplicate_accounts else "") +
            ("，" if duplicate_accounts and duplicate_names else "") +
            ("用户名已存在" if duplicate_names else "")
        ),
    }


@app.patch("/api/admin/users/{user_id}")
def admin_update_user(user_id: str, payload: AdminUserUpdatePayload) -> dict:
    try:
        user = user_store.update_user(user_id, payload.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    uid = str(user.get("user_id", ""))
    stats = _aggregate_student_data(uid, include_detail=False) if uid else {
        "project_count": 0,
        "last_active": "",
    }
    teams = []
    if uid:
        teams.extend(team_store.list_by_member(uid))
        teams.extend(team_store.list_by_teacher(uid))
    team_names = [_safe_str(t.get("team_name", "")) for t in teams if _safe_str(t.get("team_name", ""))]
    user_out = {
        **user,
        "project_count": stats.get("project_count", 0),
        "last_login": user.get("last_login") or stats.get("last_active", ""),
        "team_names": team_names,
    }
    return {"user": user_out}


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: str) -> dict:
    # 先查找该用户是否为教师，若是则删除其所有团队
    user = user_store.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.get("role") == "teacher":
        # 删除该教师所有团队
        teams = team_store.list_by_teacher(user_id)
        for t in teams:
            team_store.delete_team(t.get("team_id"), user_id)
    ok = user_store.delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"status": "ok"}


@app.post("/api/admin/users/{user_id}/password")
def admin_change_user_password(user_id: str, payload: AdminChangePasswordPayload) -> dict:
    user = user_store.admin_change_password(user_id, payload.new_password)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"status": "ok", "user_id": user_id}


@app.get("/api/admin/teachers")
def admin_list_teachers() -> dict:
    """Aggregate per-teacher performance metrics for admin ranking view."""
    teachers = user_store.list_users(role="teacher")

    # Map teacher_id -> owned teams
    all_teams = team_store.list_all()
    teacher_teams: dict[str, list[dict]] = {}
    for team in all_teams:
        tid = _safe_str(team.get("teacher_id", ""))
        if not tid:
            continue
        teacher_teams.setdefault(tid, []).append(team)

    rows: list[dict[str, Any]] = []
    for t in teachers:
        teacher_id = _safe_str(t.get("user_id", ""))
        if not teacher_id:
            continue
        teams = teacher_teams.get(teacher_id, [])
        student_ids: set[str] = set()
        for team in teams:
            for m in team.get("members", []) or []:
                sid = _safe_str(m.get("user_id", ""))
                if sid:
                    student_ids.add(sid)

        team_count = len(teams)
        student_count = len(student_ids)
        total_submissions = 0
        total_risks = 0
        active_students = 0
        students_with_interventions = 0
        student_scores: list[float] = []
        last_active_overall = ""

        for sid in student_ids:
            stats = _aggregate_student_data(sid, include_detail=False)
            subs = int(stats.get("total_submissions", 0) or 0)
            risks = int(stats.get("risk_count", 0) or 0)
            avg_sc = float(stats.get("avg_score", 0) or 0)
            last_act = _safe_str(stats.get("last_active", ""))
            total_submissions += subs
            total_risks += risks
            if subs > 0:
                active_students += 1
            if avg_sc > 0:
                student_scores.append(avg_sc)
            if last_act and last_act > last_active_overall:
                last_active_overall = last_act

            # Check if this teacher has ever created an intervention for this student
            project_id = f"project-{sid}"
            project_state = json_store.load_project(project_id)
            interventions = project_state.get("teacher_interventions", []) or []
            for item in interventions:
                if isinstance(item, dict) and _safe_str(item.get("teacher_id", "")) == teacher_id:
                    students_with_interventions += 1
                    break

        avg_score = round(sum(student_scores) / len(student_scores), 1) if student_scores else 0.0
        risk_rate = round((total_risks / max(1, total_submissions)) * 100, 1) if total_submissions else 0.0
        intervention_coverage = round((students_with_interventions / max(1, active_students)) * 100, 1) if active_students else 0.0

        rows.append({
            "teacher_id": teacher_id,
            "display_name": t.get("display_name") or t.get("email") or teacher_id,
            "email": t.get("email", ""),
            "team_count": team_count,
            "student_count": student_count,
            "active_students": active_students,
            "avg_score": avg_score,
            "risk_rate": risk_rate,
            "intervention_coverage": intervention_coverage,
            "last_active": last_active_overall,
        })

    # Sort by avg_score then active_students for a simple ranking
    rows.sort(key=lambda r: (r["avg_score"], r["active_students"]), reverse=True)
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx

    return {"count": len(rows), "teachers": rows}


@app.get("/api/admin/projects")
def admin_projects_overview(limit: int = 500) -> dict:
    """Admin overview of projects based on conversations + project_state.

    This scans data/conversations for all project_ids and then joins with
    JsonStorage project_state to retrieve the latest scoring / risk info.
    Each project_id appears至多一次，按最新时间排序返回。
    """
    conv_root = conv_store.root
    if not conv_root.exists():  # type: ignore[attr-defined]
        return {"count": 0, "projects": []}

    projects: list[dict[str, Any]] = []

    for project_dir in sorted(conv_root.iterdir()):  # type: ignore[attr-defined]
        if not project_dir.is_dir():
            continue
        project_id = project_dir.name

        latest_conv: dict[str, Any] | None = None
        latest_ts = ""
        for path in sorted(project_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(data, dict):
                continue
            ts = _safe_str(data.get("created_at", ""))
            msgs = data.get("messages") or []
            if isinstance(msgs, list) and msgs:
                last_msg_ts = _safe_str(msgs[-1].get("timestamp", "")) or ts
            else:
                last_msg_ts = ts
            if last_msg_ts > latest_ts:
                latest_ts = last_msg_ts
                latest_conv = data

        if not latest_conv:
            continue

        pid = _safe_str(latest_conv.get("project_id") or project_id)
        student_id = _safe_str(latest_conv.get("student_id", ""))

        # Join with JsonStorage to get scoring / risk information
        project_state = json_store.load_project(pid)
        submissions = list(project_state.get("submissions", []) or [])
        latest_sub: dict[str, Any] | None = None
        if submissions:
            submissions.sort(key=lambda row: _safe_str(row.get("created_at", "")))
            latest_sub = submissions[-1]

        diagnosis = (
            latest_sub.get("diagnosis", {})
            if isinstance(latest_sub, dict) and isinstance(latest_sub.get("diagnosis"), dict)
            else {}
        )
        overall_score = diagnosis.get("overall_score", 0)
        triggered_rules = [
            r.get("id")
            for r in diagnosis.get("triggered_rules", []) or []
            if isinstance(r, dict)
        ]
        created_at = _safe_str(
            (latest_sub or {}).get("created_at") or latest_ts
        )
        class_id = _safe_str((latest_sub or {}).get("class_id", "")) or None
        logical_project_id = _safe_str((latest_sub or {}).get("logical_project_id", ""))
        source_type = _safe_str((latest_sub or {}).get("source_type", ""))
        filename = (latest_sub or {}).get("filename")

        projects.append(
            {
                "project_id": pid,
                "logical_project_id": logical_project_id,
                "student_id": student_id,
                "class_id": class_id,
                "created_at": created_at,
                "source_type": source_type,
                "filename": filename,
                "overall_score": overall_score,
                "triggered_rules": triggered_rules,
            }
        )

    projects.sort(key=lambda row: _safe_str(row.get("created_at", "")), reverse=True)
    if limit and limit > 0:
        projects = projects[:limit]
    return {"count": len(projects), "projects": projects}


def _append_access_log(entry: dict[str, Any]) -> None:
    """Append a single access-log entry to data/logs/access_logs.json.

    This is a lightweight JSON-based logger used by the admin console.
    Failures in logging must never break the main business logic, so
    all errors are swallowed after writing a warning.
    """
    log_file = settings.data_root / "logs" / "access_logs.json"
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            raw = json.loads(log_file.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                logs: list[dict[str, Any]] = []
            else:
                logs = [item for item in raw if isinstance(item, dict)]
        except Exception:  # noqa: BLE001
            logs = []

        record = dict(entry)
        if "time" not in record or not record["time"]:
            record["time"] = datetime.utcnow().isoformat() + "Z"

        logs.append(record)
        log_file.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.warning("Failed to append access log entry", exc_info=True)


def _load_access_logs() -> dict[str, Any]:
    """Load raw access logs from JSON and compute aggregate statistics.

    The log file is stored under data/logs/access_logs.json and contains
    a list of entries with fields such as time, user, method, path,
    status, status_code and duration_ms.
    """
    log_file = settings.data_root / "logs" / "access_logs.json"
    if not log_file.exists():
        return {
            "logs": [],
            "stats": {
                "total_requests": 0,
                "success_count": 0,
                "error_count": 0,
                "blocked_count": 0,
                "avg_duration_ms": 0.0,
                "p95_duration_ms": 0.0,
                "top_paths": [],
            },
        }

    try:
        data = json.loads(log_file.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        data = []

    if not isinstance(data, list):
        data = []

    logs: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict):
            logs.append(item)

    # Sort by time descending if possible
    def _parse_time(value: Any) -> float:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except Exception:  # noqa: BLE001
            return 0.0

    logs.sort(key=lambda row: _parse_time(row.get("time")), reverse=True)

    total = len(logs)
    success_count = 0
    error_count = 0
    blocked_count = 0
    durations: list[float] = []
    path_stats: dict[str, dict[str, Any]] = {}

    for row in logs:
        status_str = str(row.get("status", "")).upper()
        code = int(row.get("status_code", 0) or 0)
        duration = float(row.get("duration_ms", 0) or 0)
        if duration > 0:
            durations.append(duration)

        if status_str == "BLOCKED" or code == 403:
            blocked_count += 1
            status_bucket = "blocked_count"
        elif 200 <= code < 400 and status_str == "OK":
            success_count += 1
            status_bucket = "success_count"
        else:
            error_count += 1
            status_bucket = "error_count"

        path = str(row.get("path") or "").strip()
        if path:
            stat = path_stats.setdefault(
                path,
                {
                    "path": path,
                    "count": 0,
                    "total_duration_ms": 0.0,
                    "success_count": 0,
                    "error_count": 0,
                    "blocked_count": 0,
                },
            )
            stat["count"] += 1
            stat["total_duration_ms"] += max(duration, 0.0)
            stat[status_bucket] += 1

    avg_duration = round(sum(durations) / len(durations), 2) if durations else 0.0
    p95_duration = 0.0
    if durations:
        sorted_durations = sorted(durations)
        idx = max(0, int(math.ceil(0.95 * len(sorted_durations))) - 1)
        p95_duration = round(sorted_durations[idx], 2)

    top_paths: list[dict[str, Any]] = []
    for stat in path_stats.values():
        count = max(1, int(stat.get("count", 0) or 0))
        avg = stat["total_duration_ms"] / count
        top_paths.append(
            {
                "path": stat["path"],
                "count": count,
                "avg_duration_ms": round(avg, 2),
                "success_count": int(stat.get("success_count", 0) or 0),
                "error_count": int(stat.get("error_count", 0) or 0),
                "blocked_count": int(stat.get("blocked_count", 0) or 0),
            }
        )

    top_paths.sort(key=lambda row: row["count"], reverse=True)

    stats = {
        "total_requests": total,
        "success_count": success_count,
        "error_count": error_count,
        "blocked_count": blocked_count,
        "avg_duration_ms": avg_duration,
        "p95_duration_ms": p95_duration,
        "top_paths": top_paths[:12],
    }

    return {"logs": logs, "stats": stats}


@app.get("/api/admin/interventions")
def admin_interventions() -> dict:
    """Aggregate teaching interventions across all teachers for admin view.

    This scans JsonStorage for teacher_interventions and groups them by
    teacher and student so that the admin can monitor intervention
    workload and coverage.
    """
    projects = json_store.list_projects()
    all_items: list[dict[str, Any]] = []
    teacher_ids: set[str] = set()
    student_ids: set[str] = set()
    status_totals: dict[str, int] = {}

    def _student_id_from_project(project_id: str) -> str:
        if project_id.startswith("project-") and len(project_id) > len("project-"):
            return project_id[len("project-") :]
        return ""

    for project in projects:
        project_id = _safe_str(project.get("project_id", ""))
        root_student_id = _student_id_from_project(project_id)
        interventions = project.get("teacher_interventions", []) or []
        if not isinstance(interventions, list):
            continue
        for item in interventions:
            if not isinstance(item, dict):
                continue
            teacher_id = _safe_str(item.get("teacher_id", ""))
            if not teacher_id:
                continue
            teacher_ids.add(teacher_id)
            target_student_id = _safe_str(item.get("target_student_id") or root_student_id)
            if target_student_id:
                student_ids.add(target_student_id)
            status = _safe_str(item.get("status", "draft")).lower() or "draft"
            status_totals[status] = status_totals.get(status, 0) + 1

            teacher_info = user_store.get_by_id(teacher_id) or {}
            student_info = user_store.get_by_id(target_student_id) or {}

            all_items.append(
                {
                    "intervention_id": _safe_str(item.get("intervention_id", "")),
                    "project_id": project_id,
                    "logical_project_id": _safe_str(item.get("logical_project_id", "")),
                    "teacher_id": teacher_id,
                    "teacher_name": teacher_info.get("display_name") or teacher_info.get("email") or teacher_id,
                    "student_id": target_student_id,
                    "student_name": student_info.get("display_name") or target_student_id,
                    "title": _safe_str(item.get("title", "")),
                    "reason_summary": _safe_str(item.get("reason_summary", "")),
                    "status": status,
                    "scope_type": _safe_str(item.get("scope_type", "")),
                    "scope_id": _safe_str(item.get("scope_id", "")),
                    "priority": _safe_str(item.get("priority", "")),
                    "created_at": _safe_str(item.get("created_at", "")),
                    "updated_at": _safe_str(item.get("updated_at", "")),
                }
            )

    # Build teacher-level aggregates
    teacher_stats: dict[str, dict[str, Any]] = {}
    teacher_students: dict[str, set[str]] = {}
    for row in all_items:
        teacher_id = row["teacher_id"]
        target_student_id = row.get("student_id", "") or ""
        status = row.get("status", "draft") or "draft"
        if teacher_id not in teacher_stats:
            info = user_store.get_by_id(teacher_id) or {}
            teacher_stats[teacher_id] = {
                "teacher_id": teacher_id,
                "name": info.get("display_name") or info.get("email") or teacher_id,
                "email": info.get("email", ""),
                "total_interventions": 0,
                "draft": 0,
                "approved": 0,
                "sent": 0,
                "viewed": 0,
                "completed": 0,
                "archived": 0,
                "student_count": 0,
            }
            teacher_students[teacher_id] = set()
        stat = teacher_stats[teacher_id]
        stat["total_interventions"] += 1
        if status in stat:
            stat[status] += 1
        if target_student_id:
            teacher_students[teacher_id].add(target_student_id)

    for teacher_id, students in teacher_students.items():
        teacher_stats[teacher_id]["student_count"] = len(students)

    teachers_out = sorted(
        teacher_stats.values(),
        key=lambda r: (r["total_interventions"], r["student_count"]),
        reverse=True,
    )

    completed_count = status_totals.get("completed", 0)

    # Normalize status buckets for summary
    all_status_keys = [
        "draft",
        "approved",
        "sent",
        "viewed",
        "completed",
        "archived",
    ]
    status_summary = {key: int(status_totals.get(key, 0) or 0) for key in all_status_keys}

    # Recent interventions sorted by updated_at/created_at desc
    def _parse_ts(row: dict) -> str:
        return _safe_str(row.get("updated_at") or row.get("created_at") or "")

    all_items.sort(key=_parse_ts, reverse=True)

    return {
        "summary": {
            "total_interventions": len(all_items),
            "teacher_count": len(teacher_ids),
            "student_count": len(student_ids),
            "completed_count": completed_count,
            "status_counts": status_summary,
        },
        "teachers": teachers_out,
        "recent": all_items[:120],
    }


def _build_teacher_intervention_impact(teacher_id: str) -> dict[str, Any]:
    """Aggregate intervention effect for one teacher across all projects.

    This looks at teacher_interventions in JsonStorage, pairs them with
    before/after submissions around the sent_at timestamp, and computes
    simple score / risk deltas for an "effect dashboard" view.
    """
    projects = json_store.list_projects()

    def _student_id_from_project(project_id: str) -> str:
        if project_id.startswith("project-") and len(project_id) > len("project-"):
            return project_id[len("project-") :]
        return ""

    def _extract_score(sub: dict) -> float | None:
        if not sub:
            return None
        diag = sub.get("diagnosis", {}) if isinstance(sub.get("diagnosis"), dict) else {}
        raw_score = diag.get("overall_score", sub.get("overall_score", 0))
        score = _safe_float(raw_score)
        return score if score > 0 else None

    def _extract_triggered_rules(sub: dict) -> list[Any]:
        if not sub:
            return []
        return sub.get("triggered_rules") or (
            (sub.get("diagnosis") or {}).get("triggered_rules", [])
            if isinstance(sub.get("diagnosis"), dict)
            else []
        )

    def _risk_score_from_label(label: str) -> int:
        if label == "高":
            return 2
        if label == "中":
            return 1
        return 0

    records: list[dict[str, Any]] = []
    status_totals: dict[str, int] = {}
    effect_totals: dict[str, int] = {"positive": 0, "neutral": 0, "negative": 0, "no_followup": 0}
    priority_accum: dict[str, dict[str, Any]] = {}
    timeline_accum: dict[str, dict[str, int]] = {}

    score_gain_total = 0.0
    risk_delta_total = 0.0
    effective_count = 0

    for project in projects:
        project_id = _safe_str(project.get("project_id", ""))
        submissions = list(project.get("submissions", []) or [])
        if submissions:
            submissions.sort(key=lambda row: row.get("created_at", ""))
        interventions = project.get("teacher_interventions", []) or []
        if not isinstance(interventions, list):
            continue
        for item in interventions:
            if not isinstance(item, dict):
                continue
            t_id = _safe_str(item.get("teacher_id", ""))
            if teacher_id and t_id != teacher_id:
                continue
            status = _safe_str(item.get("status", "draft")).lower() or "draft"
            status_totals[status] = status_totals.get(status, 0) + 1

            sent_ts = _safe_str(item.get("sent_at") or item.get("updated_at") or item.get("created_at") or "")
            before_sub = None
            after_sub = None
            if submissions and sent_ts:
                before_subs = [s for s in submissions if _safe_str(s.get("created_at", "")) < sent_ts]
                after_subs = [s for s in submissions if _safe_str(s.get("created_at", "")) >= sent_ts]
                before_sub = before_subs[-1] if before_subs else None
                after_sub = after_subs[-1] if after_subs else None

            score_before = _extract_score(before_sub)
            score_after = _extract_score(after_sub)
            triggered_before = _extract_triggered_rules(before_sub)
            triggered_after = _extract_triggered_rules(after_sub)
            risk_label_before = _risk_level(score_before or 0.0, triggered_before) if score_before is not None else ""
            risk_label_after = _risk_level(score_after or 0.0, triggered_after) if score_after is not None else ""

            if after_sub is None or score_before is None or score_after is None:
                effect_label = "no_followup"
                score_delta = 0.0
                risk_delta = 0.0
            else:
                score_delta = round(score_after - score_before, 2)
                risk_before_v = _risk_score_from_label(risk_label_before)
                risk_after_v = _risk_score_from_label(risk_label_after)
                risk_delta = risk_after_v - risk_before_v
                if score_delta >= 0.8 and risk_after_v <= risk_before_v:
                    effect_label = "positive"
                elif score_delta <= -0.5 and risk_after_v >= risk_before_v:
                    effect_label = "negative"
                else:
                    effect_label = "neutral"
                score_gain_total += score_delta
                risk_delta_total += risk_delta
                effective_count += 1

            effect_totals[effect_label] = effect_totals.get(effect_label, 0) + 1

            priority = _safe_str(item.get("priority", "medium")) or "medium"
            bucket = priority_accum.setdefault(priority, {"priority": priority, "count": 0, "score_gain_total": 0.0, "risk_delta_total": 0.0})
            bucket["count"] += 1
            bucket["score_gain_total"] += score_delta
            bucket["risk_delta_total"] += risk_delta

            day_key = _safe_str(sent_ts or item.get("created_at") or "")[:10]
            if day_key:
                t_bucket = timeline_accum.setdefault(day_key, {"date": day_key, "total": 0, "effective": 0, "positive": 0, "negative": 0, "neutral": 0})
                t_bucket["total"] += 1
                if effect_label != "no_followup":
                    t_bucket["effective"] += 1
                if effect_label in {"positive", "negative", "neutral"}:
                    t_bucket[effect_label] += 1

            student_id = _safe_str(item.get("target_student_id") or _student_id_from_project(project_id))
            base_sub = after_sub or before_sub or {}

            records.append({
                "intervention_id": _safe_str(item.get("intervention_id", "")),
                "project_id": project_id,
                "logical_project_id": _safe_str(item.get("logical_project_id", "")),
                "teacher_id": t_id,
                "student_id": student_id,
                "class_id": _safe_str(base_sub.get("class_id", project.get("class_id", ""))),
                "cohort_id": _safe_str(base_sub.get("cohort_id", project.get("cohort_id", ""))),
                "title": _safe_str(item.get("title", "")),
                "reason_summary": _safe_str(item.get("reason_summary", "")),
                "priority": priority,
                "status": status,
                "sent_at": _safe_str(item.get("sent_at", "")),
                "viewed_at": _safe_str(item.get("viewed_at", "")),
                "score_before": score_before,
                "score_after": score_after,
                "score_delta": score_delta,
                "risk_level_before": risk_label_before,
                "risk_level_after": risk_label_after,
                "risk_delta": risk_delta,
                "effect": effect_label,
                "latest_submission_at": _safe_str(base_sub.get("created_at", "")),
            })

    by_priority = []
    for priority, bucket in priority_accum.items():
        count = max(1, int(bucket.get("count", 0) or 0))
        by_priority.append({
            "priority": priority,
            "count": int(bucket.get("count", 0) or 0),
            "avg_score_gain": round(float(bucket.get("score_gain_total", 0.0)) / count, 2),
            "avg_risk_delta": round(float(bucket.get("risk_delta_total", 0.0)) / count, 3),
        })
    by_priority.sort(key=lambda r: {"high": 0, "medium": 1, "low": 2}.get(r["priority"], 3))

    timeline = sorted(timeline_accum.values(), key=lambda r: r["date"])

    status_summary = {key: int(status_totals.get(key, 0) or 0) for key in ["draft", "approved", "sent", "viewed", "completed", "archived"]}

    avg_score_gain = round(score_gain_total / max(effective_count, 1), 2) if effective_count else 0.0
    avg_risk_delta = round(risk_delta_total / max(effective_count, 1), 3) if effective_count else 0.0

    return {
        "teacher_id": teacher_id,
        "summary": {
            "total_interventions": len(records),
            "effective_interventions": effective_count,
            "status_counts": status_summary,
            "effect_counts": effect_totals,
            "avg_score_gain": avg_score_gain,
            "avg_risk_delta": avg_risk_delta,
        },
        "by_priority": by_priority,
        "timeline": timeline,
        "items": sorted(records, key=lambda r: r.get("latest_submission_at", ""), reverse=True)[:200],
    }


@app.get("/api/teacher/assistant/intervention-impact")
def teacher_intervention_impact(teacher_id: str) -> dict[str, Any]:
    if not teacher_id:
        raise HTTPException(status_code=400, detail="teacher_id is required")
    return _build_teacher_intervention_impact(teacher_id)


def _compute_system_health() -> dict[str, Any]:
    """Compute multi-dimensional system health scores for admin dashboard.

    This aggregates project quality, risk control, system stability and
    teaching engagement into a single health score in [0, 100]. The
    formulas are aligned with apps/web/app/admin/health.md.
    """

    # ── 1) Project quality Q (based on /api/admin/projects) ──
    projects_data = admin_projects_overview(limit=0)
    projects = list((projects_data or {}).get("projects", []) or [])
    project_count = len(projects)

    scores: list[float] = []
    low_count = 0
    for proj in projects:
        sc = _safe_float(proj.get("overall_score", 0))
        scores.append(sc)
        if sc < 6.0:
            low_count += 1

    avg_score = sum(scores) / project_count if project_count else 0.0
    low_ratio = (low_count / project_count) if project_count else 0.0

    Q_neutral = 60.0

    def _quality_base(mean_score: float) -> float:
        if mean_score <= 0:
            return 40.0
        if mean_score <= 6.0:
            return 40.0 + 20.0 * (mean_score / 6.0)
        if mean_score <= 8.5:
            return 60.0 + 25.0 * ((mean_score - 6.0) / 2.5)
        top = min(mean_score, 10.0)
        return 85.0 + 10.0 * ((top - 8.5) / 1.5)

    if project_count:
        q_base = _quality_base(avg_score)
        q_penalty = min(20.0, 40.0 * low_ratio)
        q_raw = q_base - q_penalty
        k_q = min(1.0, project_count / 50.0)
        q_score = (1.0 - k_q) * Q_neutral + k_q * q_raw
    else:
        q_base = Q_neutral
        q_penalty = 0.0
        q_raw = Q_neutral
        q_score = Q_neutral

    # ── 2) Risk control R (high-risk project ratio + weighted rules) ──
    R_neutral = 60.0
    high_risk_count = 0
    weighted_rule_hits = 0.0

    if project_count:
        for proj in projects:
            pid = _safe_str(proj.get("project_id", ""))
            if not pid:
                continue
            project_state = json_store.load_project(pid)
            submissions = list(project_state.get("submissions", []) or [])
            latest_sub: dict[str, Any] | None = submissions[-1] if submissions else None
            diag = (
                latest_sub.get("diagnosis", {})
                if isinstance(latest_sub, dict) and isinstance(latest_sub.get("diagnosis"), dict)
                else {}
            )
            overall_score = _safe_float(diag.get("overall_score", proj.get("overall_score", 0)))
            triggered_rules = diag.get("triggered_rules", []) or []

            level = _risk_level(overall_score, triggered_rules)
            if level == "高":
                high_risk_count += 1

            for rule in triggered_rules:
                if isinstance(rule, dict):
                    sev = str(rule.get("severity") or "").lower()
                    if sev == "high":
                        weight = 3.0
                    elif sev == "medium":
                        weight = 2.0
                    else:
                        weight = 1.0
                else:
                    weight = 1.0
                weighted_rule_hits += weight

        p_hr = high_risk_count / max(project_count, 1)
        r_avg = weighted_rule_hits / max(project_count, 1)

        if p_hr <= 0.3:
            r_hr = 100.0 - 60.0 * (p_hr / 0.3 if p_hr > 0 else 0.0)
        else:
            r_hr = 40.0 - 20.0 * ((p_hr - 0.3) / 0.7)

        r_penalty_avg = min(25.0, max(0.0, r_avg - 1.0) * 5.0)
        r_raw = r_hr - r_penalty_avg
        k_r = min(1.0, project_count / 50.0)
        r_score = (1.0 - k_r) * R_neutral + k_r * r_raw
    else:
        p_hr = 0.0
        r_avg = 0.0
        r_hr = 100.0
        r_penalty_avg = 0.0
        r_raw = R_neutral
        r_score = R_neutral

    # ── 3) System stability S (from access logs) ──
    logs_data = _load_access_logs()
    stats = (logs_data or {}).get("stats", {}) or {}
    total_requests = int(stats.get("total_requests", 0) or 0)
    success_count = int(stats.get("success_count", 0) or 0)
    error_count = int(stats.get("error_count", 0) or 0)
    blocked_count = int(stats.get("blocked_count", 0) or 0)
    avg_duration_ms = float(stats.get("avg_duration_ms", 0.0) or 0.0)
    p95_duration_ms = float(stats.get("p95_duration_ms", 0.0) or 0.0)

    denom = max(total_requests, 1)
    p_succ = success_count / denom
    p_err = error_count / denom
    p_blk = blocked_count / denom

    # Stability dimension: score equals success rate plus blocked rate (converted to percentage)
    s_raw = (p_succ + p_blk) * 100.0
    s_score = s_raw

    # ── 4) Teaching engagement E (from interventions + users) ──
    interventions_data = admin_interventions()
    summary = (interventions_data or {}).get("summary", {}) or {}
    total_interventions = int(summary.get("total_interventions", 0) or 0)
    teachers_with_interventions = int(summary.get("teacher_count", 0) or 0)
    students_with_interventions = int(summary.get("student_count", 0) or 0)

    all_teachers = user_store.list_users(role="teacher")
    all_students = user_store.list_users(role="student")
    total_teachers = len(all_teachers)
    total_students = len(all_students)

    c_teacher = teachers_with_interventions / max(total_teachers, 1) if total_teachers else 0.0
    c_student = students_with_interventions / max(total_students, 1) if total_students else 0.0

    status_counts = summary.get("status_counts", {}) or {}
    completed_count = int(status_counts.get("completed", 0) or 0) if isinstance(status_counts, dict) else 0
    c_done = completed_count / max(total_interventions, 1) if total_interventions else 0.0

    def _engagement_subscore(c: float) -> float:
        c = max(0.0, min(1.0, c))
        if c <= 0.8:
            return 40.0 + 55.0 * (c / 0.8 if c > 0 else 0.0)
        return 95.0 + 5.0 * ((c - 0.8) / 0.2)

    if total_interventions:
        e_teacher = _engagement_subscore(c_teacher)
        e_student = _engagement_subscore(c_student)
        e_done = _engagement_subscore(c_done)
        e_raw = 0.3 * e_teacher + 0.4 * e_student + 0.3 * e_done
        k_e = min(1.0, total_interventions / 50.0)
        e_score = (1.0 - k_e) * 60.0 + k_e * e_raw
    else:
        e_teacher = _engagement_subscore(0.0)
        e_student = _engagement_subscore(0.0)
        e_done = _engagement_subscore(0.0)
        e_raw = 60.0
        e_score = 60.0

    # ── 5) Final health score H ──
    # Weights: quality (Q), risk (R), stability (S), engagement (E)
    # Sum to 1.0: 0.20 + 0.15 + 0.55 + 0.10 = 1.0
    w_q = 0.20
    w_r = 0.15
    w_s = 0.55
    w_e = 0.10

    def _clamp_score(v: float) -> float:
        return max(0.0, min(100.0, v))

    q_score = _clamp_score(q_score)
    r_score = _clamp_score(r_score)
    s_score = _clamp_score(s_score)
    e_score = _clamp_score(e_score)

    h_score = w_q * q_score + w_r * r_score + w_s * s_score + w_e * e_score
    h_score = _clamp_score(h_score)

    def _round1(v: float) -> float:
        return round(v * 10.0) / 10.0

    return {
        "health_score": _round1(h_score),
        "quality_score": _round1(q_score),
        "risk_score": _round1(r_score),
        "stability_score": _round1(s_score),
        "engagement_score": _round1(e_score),
        "weights": {
            "quality": w_q,
            "risk": w_r,
            "stability": w_s,
            "engagement": w_e,
        },
        "quality_detail": {
            "project_count": project_count,
            "avg_score": round(avg_score, 2) if project_count else 0.0,
            "low_score_ratio": round(low_ratio, 3) if project_count else 0.0,
            "base_score": round(q_base, 2),
            "penalty_low_ratio": round(q_penalty, 2),
        },
        "risk_detail": {
            "project_count": project_count,
            "high_risk_project_ratio": round(p_hr, 3) if project_count else 0.0,
            "high_risk_project_count": high_risk_count,
            "avg_weighted_rule_hits": round(r_avg, 3) if project_count else 0.0,
        },
        "stability_detail": {
            "total_requests": total_requests,
            "success_rate": round(p_succ, 3) if total_requests else 0.0,
            "error_rate": round(p_err, 3) if total_requests else 0.0,
            "blocked_rate": round(p_blk, 3) if total_requests else 0.0,
            "avg_duration_ms": avg_duration_ms,
            "p95_duration_ms": p95_duration_ms,
        },
        "engagement_detail": {
            "total_interventions": total_interventions,
            "teacher_coverage": round(c_teacher, 3) if total_teachers else 0.0,
            "student_coverage": round(c_student, 3) if total_students else 0.0,
            "done_ratio": round(c_done, 3) if total_interventions else 0.0,
            "teacher_with_interventions": teachers_with_interventions,
            "student_with_interventions": students_with_interventions,
            "total_teachers": total_teachers,
            "total_students": total_students,
        },
    }


@app.get("/api/admin/logs")
def admin_logs() -> dict:
    """Admin view of access logs + aggregate statistics."""
    return _load_access_logs()


@app.get("/api/admin/health")
def admin_health() -> dict[str, Any]:
    """Return overall system health scores for admin dashboard."""
    return _compute_system_health()


@app.post("/api/admin/logs/unauthorized")
async def admin_log_unauthorized(request: Request) -> dict[str, Any]:
    """Record an unauthorized access attempt and return 403.

    This endpoint is intended to be called by the frontend when a user
    without sufficient privileges attempts to access an admin-only
    view. It appends a structured entry into access_logs.json so that
    the admin console can display and aggregate these security events.
    """
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    role = str(payload.get("role") or "")
    display_name = str(payload.get("display_name") or "")
    user_id = payload.get("user_id")
    reason = str(payload.get("reason") or "")

    role_label = {"student": "学生", "teacher": "教师", "admin": "管理员"}.get(role, "用户")
    user_label = display_name or str(payload.get("user")) or ""
    if user_label:
        user_label = f"{role_label}:{user_label}"
    else:
        user_label = role_label or "anonymous"

    path = str(payload.get("path") or request.headers.get("X-Original-Path") or request.url.path)

    detail = "Unauthorized Access Attempt"
    if reason:
        detail = f"{detail}: {reason}"

    _append_access_log(
        {
            "time": datetime.utcnow().isoformat() + "Z",
            "user": user_label,
            "user_id": user_id,
            "role": role,
            "display_name": display_name or None,
            "action": "UNAUTHORIZED",
            "detail": detail,
            "status": "BLOCKED",
            "method": request.method,
            "path": path,
            "status_code": 403,
            "duration_ms": 0,
        }
    )

    # Always respond with 403 so that security tests see a hard block.
    raise HTTPException(status_code=403, detail="Forbidden")


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
        _append_access_log(
            {
                "time": datetime.utcnow().isoformat() + "Z",
                "user": f"phone:{phone}",
                "action": "LOGIN_SMS_FAILED",
                "detail": "未发送验证码",
                "status": "FAILED",
                "method": "POST",
                "path": "/api/auth/sms/login",
                "status_code": 400,
                "duration_ms": 0,
            }
        )
        raise HTTPException(status_code=400, detail="请先获取验证码")
    stored_code, ts = record
    if time.time() - ts > SMS_CODE_TTL:
        _sms_codes.pop(phone, None)
        _append_access_log(
            {
                "time": datetime.utcnow().isoformat() + "Z",
                "user": f"phone:{phone}",
                "action": "LOGIN_SMS_FAILED",
                "detail": "验证码已过期",
                "status": "FAILED",
                "method": "POST",
                "path": "/api/auth/sms/login",
                "status_code": 400,
                "duration_ms": 0,
            }
        )
        raise HTTPException(status_code=400, detail="验证码已过期，请重新获取")
    if payload.code.strip() != stored_code:
        _append_access_log(
            {
                "time": datetime.utcnow().isoformat() + "Z",
                "user": f"phone:{phone}",
                "action": "LOGIN_SMS_FAILED",
                "detail": "验证码不正确",
                "status": "FAILED",
                "method": "POST",
                "path": "/api/auth/sms/login",
                "status_code": 400,
                "duration_ms": 0,
            }
        )
        raise HTTPException(status_code=400, detail="验证码不正确")
    _sms_codes.pop(phone, None)
    user = user_store.get_or_create_by_phone(phone)
    # 记录短信登录成功到访问日志
    role = str(user.get("role", ""))
    role_label = {"student": "学生", "teacher": "教师", "admin": "管理员"}.get(role, "用户")
    display_name = str(user.get("display_name") or user.get("phone") or user.get("email") or user.get("user_id") or "")
    user_label = f"{role_label}:{display_name}" if display_name else role_label
    _append_access_log(
        {
            "time": datetime.utcnow().isoformat() + "Z",
            "user": user_label,
            "user_id": user.get("user_id"),
            "role": role,
            "display_name": user.get("display_name"),
            "action": "LOGIN_SMS",
            "detail": "用户短信登录成功",
            "status": "OK",
            "method": "POST",
            "path": "/api/auth/sms/login",
            "status_code": 200,
            "duration_ms": 0,
        }
    )
    return AuthUserResponse(status="ok", user=user)


# ── Team Management CRUD ──────────────────────────────────────────────

@app.post("/api/teams")
def create_team(payload: TeamCreatePayload) -> TeamResponse:
    user = user_store.get_by_id(payload.teacher_id)
    if not user or user.get("role") != "teacher":
        raise HTTPException(status_code=403, detail="仅教师可创建团队")
    team = team_store.create_team_with_custom_code(
        teacher_id=payload.teacher_id,
        teacher_name=payload.teacher_name or user.get("display_name", ""),
        team_name=payload.team_name,
        invite_code=payload.invite_code,
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


@app.patch("/api/teams/{team_id}")
def update_team(team_id: str, payload: TeamUpdatePayload) -> TeamResponse:
    if not payload.teacher_id:
        raise HTTPException(status_code=400, detail="需提供 teacher_id")
    team = team_store.rename_team(team_id, payload.teacher_id, payload.team_name)
    if not team:
        raise HTTPException(status_code=404, detail="团队不存在或无权修改")
    return TeamResponse(team=team)


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


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, dict):
        return v.get("description") or v.get("title") or v.get("text") or str(v)
    return str(v)


def _normalize_rules(rules: Any) -> list[str]:
    if not rules or not isinstance(rules, list):
        return []
    result = []
    for r in rules:
        if isinstance(r, str):
            result.append(r)
        elif isinstance(r, dict):
            result.append(r.get("id") or r.get("name") or str(r))
    return result


def _safe_diagnosis(diag: Any) -> dict:
    if not isinstance(diag, dict):
        return {}
    return {
        "overall_score": float(diag.get("overall_score", 0) or 0),
        "bottleneck": _safe_str(diag.get("bottleneck", "")),
        "triggered_rules": _normalize_rules(diag.get("triggered_rules", [])),
        "strengths": [_safe_str(s) for s in (diag.get("strengths") or [])[:5]],
        "weaknesses": [_safe_str(w) for w in (diag.get("weaknesses") or [])[:5]],
    }


def _rich_triggered_rules(rules: Any) -> list[dict]:
    """Preserve the full rule objects (quote / explanation / inference_chain / …)
    needed by the teacher-side student-analysis panel. Unlike ``_normalize_rules``
    which reduces each rule to its id string, this returns ready-to-render dicts.
    Strings are wrapped into a minimal dict so the frontend never receives raw
    primitives in the same array as dicts."""
    if not rules or not isinstance(rules, list):
        return []
    out: list[dict] = []
    for r in rules:
        if isinstance(r, str):
            out.append({"id": r, "rule_id": r})
            continue
        if not isinstance(r, dict):
            continue
        item: dict[str, Any] = {}
        for key in (
            "id", "rule_id", "name", "rule_name", "severity",
            "quote", "explanation", "impact", "fix_hint",
            "matched_keywords", "missing_requires",
            "competition_context", "source_message_id",
            "agent_name", "score_impact",
        ):
            if key in r:
                item[key] = r.get(key)
        chain = r.get("inference_chain")
        if isinstance(chain, list):
            item["inference_chain"] = [
                step if isinstance(step, (str, dict)) else str(step)
                for step in chain[:12]
            ]
        linked = r.get("linked_task")
        if isinstance(linked, dict):
            item["linked_task"] = {
                "title": _safe_str(linked.get("title", "")),
                "description": _safe_str(linked.get("description", "")),
                "acceptance_criteria": [
                    _safe_str(x) for x in (linked.get("acceptance_criteria") or [])[:6]
                ],
            }
        if not item.get("id") and item.get("rule_id"):
            item["id"] = item["rule_id"]
        if not item.get("rule_id") and item.get("id"):
            item["rule_id"] = item["id"]
        out.append(item)
    return out


def _rich_diagnosis(diag: Any) -> dict:
    """Extend ``_safe_diagnosis`` with the rich fields the teacher-side analysis
    panel needs to render (rubric / rationale / triggered rules with full
    context / hypergraph / next_task / etc.). Keeps scalar defaults from the
    original helper so callers can rely on them."""
    base = _safe_diagnosis(diag)
    if not isinstance(diag, dict):
        return base

    def _pass_list(value: Any, limit: int | None = None) -> list[Any]:
        if not isinstance(value, list):
            return []
        return value[:limit] if limit else list(value)

    base["triggered_rules"] = _rich_triggered_rules(diag.get("triggered_rules", []))
    rubric_list = _pass_list(diag.get("rubric"))
    rubric_items = _pass_list(diag.get("rubric_items"))
    if rubric_list:
        base["rubric"] = rubric_list
    if rubric_items:
        base["rubric_items"] = rubric_items
    rubric_assess = diag.get("rubric_assessment")
    if isinstance(rubric_assess, dict):
        base["rubric_assessment"] = rubric_assess
    for key in (
        "overall_weighted_score", "overall_score_10",
        "overall_rationale", "project_phase_rationale",
        "bottleneck_rationale", "current_summary_rationale",
        "next_task_rationale", "maturity_rationale",
        "project_phase", "current_summary", "score_band",
        "next_task", "kg", "pattern_warnings",
        "passed_dimensions", "failed_dimensions",
    ):
        if key in diag:
            base[key] = diag.get(key)
    if "bottleneck" in diag and isinstance(diag.get("bottleneck"), dict):
        base["bottleneck"] = diag.get("bottleneck")
    return base


def _safe_kg_analysis(kg: Any) -> dict:
    if not isinstance(kg, dict):
        return {}
    entities = []
    for e in (kg.get("entities") or [])[:12]:
        if not isinstance(e, dict):
            continue
        entities.append({
            "id": _safe_str(e.get("id", "")),
            "label": _safe_str(e.get("label", "")),
            "type": _safe_str(e.get("type", "")),
        })
    relationships = []
    for r in (kg.get("relationships") or [])[:16]:
        if not isinstance(r, dict):
            continue
        relationships.append({
            "source": _safe_str(r.get("source", "")),
            "target": _safe_str(r.get("target", "")),
            "relation": _safe_str(r.get("relation", "")),
        })
    return {
        "entities": entities,
        "relationships": relationships,
        "structural_gaps": [_safe_str(x) for x in (kg.get("structural_gaps") or [])[:6]],
        "content_strengths": [_safe_str(x) for x in (kg.get("content_strengths") or [])[:6]],
        "insight": _safe_str(kg.get("insight", "")),
        "completeness_score": float(kg.get("completeness_score", 0) or 0),
        "section_scores": kg.get("section_scores", {}) if isinstance(kg.get("section_scores"), dict) else {},
        "kg_quality": kg.get("kg_quality", {}),
    }


def _safe_hypergraph_insight(hg: Any) -> dict:
    if not isinstance(hg, dict):
        return {}
    edges = []
    for e in (hg.get("edges") or [])[:30]:
        if not isinstance(e, dict):
            continue
        edges.append({
            "hyperedge_id": _safe_str(e.get("hyperedge_id", "")),
            "type": _safe_str(e.get("type", "")),
            "family_label": _safe_str(e.get("family_label", "")),
            "support": int(e.get("support", 0) or 0),
            "teaching_note": _safe_str(e.get("teaching_note", "")),
            "rules": [_safe_str(x) for x in (e.get("rules") or [])[:6]],
            "rubrics": [_safe_str(x) for x in (e.get("rubrics") or [])[:6]],
            "nodes": [_safe_str(x) for x in (e.get("nodes") or [])[:12]],
            "evidence_quotes": [_safe_str(x) for x in (e.get("evidence_quotes") or [])[:3]],
            "retrieval_reason": _safe_str(e.get("retrieval_reason", "")),
            "source_project_ids": [_safe_str(x) for x in (e.get("source_project_ids") or [])[:6]],
            "confidence": float(e.get("confidence", 0) or 0),
            "severity": _safe_str(e.get("severity", "")),
            "score_impact": float(e.get("score_impact", 0) or 0),
            "stage_scope": _safe_str(e.get("stage_scope", "")),
            "match_score": float(e.get("match_score", 0) or 0),
        })
    return {
        "summary": _safe_str(hg.get("summary", "")),
        "top_signals": [_safe_str(x) for x in (hg.get("top_signals") or [])[:10]],
        "key_dimensions": [_safe_str(x) for x in (hg.get("key_dimensions") or [])[:10]],
        "edges": edges,
        "matched_by": hg.get("matched_by", {}) if isinstance(hg.get("matched_by"), dict) else {},
        "meta": hg.get("meta", {}) if isinstance(hg.get("meta"), dict) else {},
        "topology": hg.get("topology", {}) if isinstance(hg.get("topology"), dict) else {},
    }


def _safe_hypergraph_student(hs: Any) -> dict:
    if not isinstance(hs, dict):
        return {}
    hub_entities = []
    for h in (hs.get("hub_entities") or [])[:6]:
        if not isinstance(h, dict):
            continue
        hub_entities.append({
            "entity": _safe_str(h.get("entity", "")),
            "connections": int(h.get("connections", 0) or 0),
            "note": _safe_str(h.get("note", "")),
        })
    cross_links = []
    for c in (hs.get("cross_links") or [])[:8]:
        if not isinstance(c, dict):
            continue
        cross_links.append({
            "from_dim": _safe_str(c.get("from_dim", "")),
            "to_dim": _safe_str(c.get("to_dim", "")),
            "relation": _safe_str(c.get("relation", "")),
        })
    pattern_warnings = []
    for item in (hs.get("pattern_warnings") or [])[:5]:
        if isinstance(item, dict):
            pattern_warnings.append({
                "pattern_id": _safe_str(item.get("pattern_id", "")),
                "warning": _safe_str(item.get("warning", "")),
                "matched_rules": [_safe_str(x) for x in (item.get("matched_rules") or [])[:5]],
                "support": int(item.get("support", 0) or 0),
                "edge_type": _safe_str(item.get("edge_type", "")),
            })
        else:
            pattern_warnings.append({"warning": _safe_str(item)})
    pattern_strengths = []
    for item in (hs.get("pattern_strengths") or [])[:5]:
        if isinstance(item, dict):
            pattern_strengths.append({
                "pattern_id": _safe_str(item.get("pattern_id", "")),
                "note": _safe_str(item.get("note", "")),
                "support": int(item.get("support", 0) or 0),
                "edge_type": _safe_str(item.get("edge_type", "")),
            })
        else:
            pattern_strengths.append({"note": _safe_str(item)})
    dimensions = {}
    raw_dimensions = hs.get("dimensions") or {}
    if isinstance(raw_dimensions, dict):
        for key, value in list(raw_dimensions.items())[:16]:
            if not isinstance(value, dict):
                continue
            dimensions[_safe_str(key)] = {
                "name": _safe_str(value.get("name", "")),
                "covered": bool(value.get("covered")),
                "entities": [_safe_str(x) for x in (value.get("entities") or [])[:5]],
                "count": int(value.get("count", 0) or 0),
            }
    missing_dimensions = []
    for item in (hs.get("missing_dimensions") or [])[:8]:
        if not isinstance(item, dict):
            continue
        missing_dimensions.append({
            "dimension": _safe_str(item.get("dimension", "")),
            "importance": _safe_str(item.get("importance", "")),
            "recommendation": _safe_str(item.get("recommendation", "")),
        })
    return {
        "ok": bool(hs.get("ok")),
        "coverage_score": float(hs.get("coverage_score", 0) or 0),
        "covered_count": int(hs.get("covered_count", 0) or 0),
        "total_dimensions": int(hs.get("total_dimensions", 0) or 0),
        "dimensions": dimensions,
        "hub_entities": hub_entities,
        "cross_links": cross_links,
        "pattern_warnings": pattern_warnings,
        "pattern_strengths": pattern_strengths,
        "missing_dimensions": missing_dimensions,
        "projected_edge_types": [_safe_str(x) for x in (hs.get("projected_edge_types") or [])[:8]],
        "student_graph_stats": hs.get("student_graph_stats", {}) if isinstance(hs.get("student_graph_stats"), dict) else {},
        "quality_metrics": hs.get("quality_metrics", {}),
        "template_matches": hs.get("template_matches", []),
        "consistency_issues": hs.get("consistency_issues", []),
    }


def _normalize_intent(raw_intent: Any, message: str = "") -> str:
    intent = _safe_str(raw_intent).strip().lower()
    text = message.lower()
    if not intent:
        intent = text
    if any(k in intent for k in ["learn", "学习", "原理", "概念", "不会", "理解", "怎么学"]):
        return "学习理解"
    if any(k in intent for k in ["business", "商业", "盈利", "市场", "竞品", "商业模式", "用户"]):
        return "商业诊断"
    if any(k in intent for k in ["方案", "设计", "技术", "功能", "架构", "实现", "产品"]):
        return "方案设计"
    if any(k in intent for k in ["材料", "文档", "润色", "修改", "优化表达", "计划书", "ppt"]):
        return "材料润色"
    if any(k in intent for k in ["路演", "答辩", "演讲", "展示", "pitch"]):
        return "路演表达"
    return "综合咨询"


def _submission_intent_shape(row: dict) -> str:
    ao = row.get("agent_outputs", {}) if isinstance(row.get("agent_outputs"), dict) else {}
    orchestration = ao.get("orchestration", {}) if isinstance(ao.get("orchestration"), dict) else {}
    shape = _safe_str(row.get("intent_shape") or orchestration.get("intent_shape", "")).lower()
    return shape if shape in {"single", "mixed"} else "single"


def _infer_project_phase(text: str, next_task: dict | None = None, kg_analysis: dict | None = None) -> str:
    blob = " ".join([
        _safe_str(text),
        _safe_str((next_task or {}).get("title", "")),
        _safe_str((next_task or {}).get("description", "")),
        _safe_str((kg_analysis or {}).get("insight", "")),
    ]).lower()
    if any(k in blob for k in ["用户", "痛点", "访谈", "需求", "场景", "问题定义"]):
        return "问题定义"
    if any(k in blob for k in ["方案", "功能", "原型", "技术", "架构", "实现"]):
        return "方案设计"
    if any(k in blob for k in ["商业", "市场", "竞品", "盈利", "商业模式", "资源"]):
        return "商业论证"
    if any(k in blob for k in ["文档", "计划书", "材料", "润色", "修改", "补充"]):
        return "材料打磨"
    if any(k in blob for k in ["路演", "答辩", "演讲", "展示", "pitch"]):
        return "路演准备"
    return "持续迭代"


def _derive_logical_project_id(project_state: dict, conversation_id: str | None, message: str, project_id: str) -> str:
    subs = project_state.get("submissions", []) or []
    # 1) 同一会话已有提交 → 沿用原 logical_project_id（老/新都走这一条，保证不回溯历史编号）
    if conversation_id:
        for row in reversed(subs):
            if row.get("conversation_id") == conversation_id and row.get("logical_project_id"):
                return str(row.get("logical_project_id"))
    # 2) 主题相似聚合（保留老逻辑）
    terms = _topic_terms(message)
    if conversation_id and terms:
        for row in reversed(subs[-12:]):
            row_terms = _topic_terms(" ".join([
                _safe_str(row.get("raw_text", "")),
                _safe_str((row.get("next_task") or {}).get("title", "")),
                _safe_str((row.get("diagnosis") or {}).get("bottleneck", "")),
            ]))
            overlap = terms.intersection(row_terms)
            overlap_ratio = len(overlap) / len(terms) if terms else 0
            if len(overlap) >= 5 and overlap_ratio >= 0.4 and row.get("logical_project_id"):
                return str(row.get("logical_project_id"))
    # 3) 新会话 + 用户已填学号 → 生成 P-{学号}-{NN}
    #    project_id 约定为 `project-{user_id}`，据此查用户是否已配置学号
    try:
        owner_uid = ""
        if isinstance(project_id, str) and project_id.startswith("project-"):
            owner_uid = project_id[len("project-"):]
        if owner_uid:
            owner = user_store.get_by_id(owner_uid) or {}
            sid = str(owner.get("student_id") or "").strip()
            if sid:
                serial = user_store.allocate_project_serial(owner_uid)
                return f"P-{sid}-{serial:02d}"
    except Exception:
        pass  # 任何异常都回退到下面的兜底，保证主链路不受影响
    # 4) 兜底：沿用老逻辑 = conversation_id 或 project_id
    return conversation_id or project_id


def _extract_evidence_quotes(raw_text: str, diagnosis: dict | None = None, filename: str | None = None) -> list[dict]:
    text = _safe_str(raw_text)
    if not text:
        return []
    diag = diagnosis if isinstance(diagnosis, dict) else {}
    rules = diag.get("triggered_rules", []) or []
    quotes: list[dict] = []

    def _snippet(keyword: str) -> str:
        idx = text.lower().find(keyword.lower())
        if idx < 0:
            return ""
        start = max(0, idx - 26)
        end = min(len(text), idx + len(keyword) + 34)
        return text[start:end].replace("\n", " ").strip()

    for rule in rules[:5]:
        if not isinstance(rule, dict):
            continue
        keywords = [str(k) for k in (rule.get("matched_keywords") or []) if str(k).strip()]
        snippet = ""
        for kw in keywords[:3]:
            snippet = _snippet(kw)
            if snippet:
                break
        if not snippet:
            snippet = text[:90].replace("\n", " ").strip()
        quotes.append({
            "risk_id": _safe_str(rule.get("id", "")),
            "risk_name": _safe_str(rule.get("name", "")),
            "quote": snippet,
            "source": "document" if filename else "text",
            "filename": filename or "",
        })

    if not quotes:
        quotes.append({
            "risk_id": "",
            "risk_name": "",
            "quote": text[:90].replace("\n", " ").strip(),
            "source": "document" if filename else "text",
            "filename": filename or "",
        })
    return quotes[:5]


def _generate_conversation_title(
    user_message: str,
    assistant_message: str,
    category: str = "",
) -> str:
    """Use LLM to generate a concise 6-12 character conversation title."""
    try:
        if not composer_llm.enabled:
            return ""
        snippet_user = user_message.strip()[:300]
        snippet_ai = assistant_message.strip()[:300]
        raw = composer_llm.chat_text(
            system_prompt=(
                "你是标题生成器。根据学生与AI助教的对话生成一个6-12字的中文标题，"
                "概括对话核心主题。只输出标题文字，不要引号、标点或解释。"
            ),
            user_prompt=f"类别: {category or '无'}\n学生: {snippet_user}\nAI: {snippet_ai}",
            temperature=0.3,
        )
        title = str(raw or "").strip().replace('"', "").replace("'", "")[:20]
        return title if len(title) >= 2 else ""
    except Exception:
        return ""


def _build_agent_trace(
    result: dict,
    *,
    mode: str,
    llm_enabled: bool,
    matched_interventions: list[dict] | None = None,
) -> dict:
    return {
        "orchestration": {
            "mode": mode,
            "llm_enabled": llm_enabled,
            "intent": result.get("intent", ""),
            "intent_shape": _safe_str(result.get("intent_shape", "")) or "single",
            "intent_reason": _safe_str(result.get("intent_reason", "")),
            "confidence": result.get("intent_confidence", 0),
            "engine": result.get("intent_engine", ""),
            "pipeline": result.get("intent_pipeline", []),
            "nodes_visited": result.get("nodes_visited", []),
            "agents_called": result.get("agents_called", []),
            "resolved_agents": result.get("resolved_agents", []),
            "agent_reasoning": _safe_str(result.get("agent_reasoning", "")),
            "score_request_detected": bool(result.get("score_request_detected", False)),
            "eval_followup_detected": bool(result.get("eval_followup_detected", False)),
            "conversation_continuation_mode": _safe_str(result.get("conversation_continuation_mode", "")) or "new_analysis",
            "conversation_state_summary": _safe_str(result.get("conversation_state_summary", "")),
            "rag_hits": len(result.get("rag_cases", []) or []),
            "rag_case_ids": [
                _safe_str(item.get("case_id") or item.get("project_name") or "")
                for item in (result.get("rag_cases", []) or [])[:5]
                if isinstance(item, dict)
            ],
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
        "kg_analysis": result.get("kg_analysis", {}),
        "hypergraph_insight": result.get("hypergraph_insight", {}),
        "rag_cases": result.get("rag_cases", []),
        "web_search": result.get("web_search_result", {}),
        "hypergraph_student": result.get("hypergraph_student", {}),
        "hyper_consistency_issues": result.get("hyper_consistency_issues", []),
        "critic": result.get("critic"),
        "challenge_strategies": result.get("challenge_strategies"),
        "pressure_test_trace": result.get("pressure_test_trace"),
        "competition": result.get("competition"),
        "learning": result.get("learning"),
        "category": result.get("category", ""),
        "track_vector": result.get("track_vector", {}),
        "project_stage_v2": result.get("project_stage_v2", ""),
        "track_inference_meta": result.get("track_inference_meta", {}),
        "track_labels": describe_track_vector(result.get("track_vector")),
        "matched_teacher_interventions": matched_interventions or [],
        "kb_utilization": result.get("kb_utilization", {}),
        "rag_enrichment_insight": result.get("rag_enrichment_insight", ""),
        "neo4j_graph_hits": result.get("neo4j_graph_hits", []),
        "incremental_stats": result.get("incremental_stats", {}),
        "dim_results": result.get("dim_results", {}),
        "agent_hyper_details": result.get("agent_hyper_details", []),
        # 多轮稳定性：哪些重型组件是本轮新跑、哪些是 carry-forward。前端据此做轻提示。
        "analysis_refresh": result.get("analysis_refresh", {}),
        # 本轮命中的能力子图（创新评估 / 商业模式 / 模拟路演 等）。
        "ability_subgraphs": result.get("ability_subgraphs", []),
        # 运行时本体接入：本轮“覆盖 / 缺失 / 证据 / 任务 / 误区”摘要，前端可视化。
        "ontology_grounding": result.get("ontology_grounding", {}),
    }


def _safe_agent_summary(sub: dict) -> dict:
    ao = sub.get("agent_outputs") or {}
    if not isinstance(ao, dict):
        return {}
    summary: dict = {}
    for agent_name, agent_data in ao.items():
        if not isinstance(agent_data, dict):
            continue
        summary[agent_name] = _safe_str(agent_data.get("summary") or agent_data.get("description") or agent_data.get("text") or "")
    nt = sub.get("next_task", {})
    if isinstance(nt, dict):
        summary["_next_task"] = {
            "title": _safe_str(nt.get("title", "")),
            "description": _safe_str(nt.get("description", "")),
            "acceptance_criteria": [_safe_str(c) for c in (nt.get("acceptance_criteria") or [])[:5]],
        }
    orchestration = ao.get("orchestration", {}) if isinstance(ao.get("orchestration"), dict) else {}
    meta = ao.get("meta", {}) if isinstance(ao.get("meta"), dict) else {}
    summary["_meta"] = {
        "category": _safe_str(ao.get("category", "") or meta.get("category", "")),
        "strategy": _safe_str(meta.get("strategy", "") or orchestration.get("strategy", "")),
        "agents_called": [_safe_str(x) for x in ((meta.get("agents_called") or orchestration.get("agents_called") or [])[:8])],
        "resolved_agents": [_safe_str(x) for x in ((meta.get("resolved_agents") or orchestration.get("resolved_agents") or [])[:8])],
        "pipeline": [_safe_str(x) for x in ((meta.get("pipeline") or orchestration.get("pipeline") or [])[:6])],
        "intent": _normalize_intent(orchestration.get("intent", "") or ao.get("intent", ""), _safe_str(sub.get("raw_text", ""))),
        "intent_shape": _safe_str(orchestration.get("intent_shape", "") or ao.get("intent_shape", "")) or "single",
        "intent_reason": _safe_str(orchestration.get("intent_reason", "") or ao.get("intent_reason", "")),
        "intent_confidence": float(orchestration.get("confidence", 0) or ao.get("intent_confidence", 0) or 0),
        "agent_reasoning": _safe_str(orchestration.get("agent_reasoning", "") or ao.get("agent_reasoning", "")),
        "score_request_detected": bool(orchestration.get("score_request_detected", False)),
        "eval_followup_detected": bool(orchestration.get("eval_followup_detected", False)),
        "conversation_continuation_mode": _safe_str(orchestration.get("conversation_continuation_mode", "")) or "new_analysis",
        "rag_hits": int(orchestration.get("rag_hits", 0) or 0),
        "rag_case_ids": [_safe_str(x) for x in (orchestration.get("rag_case_ids", []) or [])[:5]],
    }
    return summary


def _safe_evidence_quotes(quotes: Any) -> list[dict]:
    safe_quotes: list[dict] = []
    if not isinstance(quotes, list):
        return safe_quotes
    for item in quotes[:8]:
        if not isinstance(item, dict):
            continue
        quote = _safe_str(item.get("quote", ""))
        if not quote:
            continue
        safe_quotes.append({
            "risk_id": _safe_str(item.get("risk_id", "")),
            "risk_name": _safe_str(item.get("risk_name", "")),
            "quote": quote,
            "source": _safe_str(item.get("source", "")),
            "filename": _safe_str(item.get("filename", "")),
        })
    return safe_quotes


def _project_label(pid: str, psubs: list[dict]) -> str:
    latest = psubs[-1] if psubs else {}
    # Priority 1: AI-generated conversation title
    conv_id = ""
    for sub in reversed(psubs):
        conv_id = _safe_str(sub.get("conversation_id", ""))
        if conv_id:
            break
    if conv_id:
        try:
            proj_id = _safe_str(latest.get("project_id", "")) or pid
            conv = conv_store.get(proj_id, conv_id)
            title = _safe_str(conv.get("title", "")) if conv else ""
            if title and title != "新对话" and len(title) >= 2:
                return title[:24]
        except Exception:
            pass
    # Priority 2: AI summary or bottleneck from diagnosis
    for sub in reversed(psubs):
        diag = sub.get("diagnosis") or sub.get("latest_diagnosis") or {}
        if isinstance(diag, dict):
            summary = _safe_str(diag.get("bottleneck", "")) or _safe_str(diag.get("ai_summary", ""))
            if summary and len(summary) >= 4:
                return summary[:24]
    # Priority 3: filename
    filename = _safe_str(latest.get("filename", ""))
    if filename:
        stem = Path(filename).stem.strip()
        if stem:
            return stem[:24]
    # Priority 4: raw_text keywords
    raw = _safe_str(latest.get("raw_text", "")).replace("\n", " ").strip()
    if raw:
        words = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{4,}", raw)
        if words:
            return "".join(words[:3])[:24]
    return f"项目 {pid[-4:]}" if len(pid) >= 4 else "项目病例"


def _teacher_intervention_hint(intent_mix: dict[str, int], latest_phase: str, risks: list[str]) -> str:
    top_intent = max(intent_mix.items(), key=lambda kv: kv[1])[0] if intent_mix else ""
    if top_intent == "学习理解":
        return "适合补基础概念和方法论，先统一理解再推进任务。"
    if top_intent == "商业诊断":
        return "建议老师做一次市场/用户/商业模式的系统诊断。"
    if top_intent == "方案设计":
        return "更适合一对一讨论方案结构、功能边界和技术可行性。"
    if top_intent == "材料润色":
        return "可以集中辅导材料结构、表达逻辑和论证完整度。"
    if top_intent == "路演表达":
        return "建议做一次路演模拟，重点纠正表达与答辩节奏。"
    if latest_phase == "问题定义":
        return "目前仍在问题定义阶段，适合先补用户与场景分析。"
    if risks:
        return f"优先围绕“{risks[0]}”做针对性干预。"
    return "建议先看最新任务与证据链，再决定是补课还是个别诊断。"


def _submission_intent_shape(row: dict) -> str:
    if not isinstance(row, dict):
        return "single"
    direct = _safe_str(row.get("intent_shape", ""))
    if direct in {"single", "mixed"}:
        return direct
    ao = row.get("agent_outputs", {}) if isinstance(row.get("agent_outputs"), dict) else {}
    orch = ao.get("orchestration", {}) if isinstance(ao.get("orchestration"), dict) else {}
    shape = _safe_str(orch.get("intent_shape", ""))
    return shape if shape in {"single", "mixed"} else "single"


def _aggregate_student_data(user_id: str, include_detail: bool = False) -> dict:
    """Read real submissions from JsonStorage and compute metrics for one student."""
    project_id = f"project-{user_id}"
    project = json_store.load_project(project_id)
    subs = list(project.get("submissions", []) or [])
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
        triggered = s.get("triggered_rules") or ((s.get("diagnosis") or {}).get("triggered_rules") if isinstance(s.get("diagnosis"), dict) else []) or []
        if triggered:
            risk_count += 1
        pid = _safe_str(s.get("logical_project_id") or s.get("project_id") or s.get("conversation_id") or project_id)
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
        student_intent_mix: dict[str, int] = {}
        student_shape_mix: dict[str, int] = {}
        latest_project_phase = ""
        latest_summary = ""
        project_snapshot_cards = []
        for pid, psubs in projects_map.items():
            psubs.sort(key=lambda row: row.get("created_at", ""))
            p_scores = [s["_score"] for s in psubs if s["_score"] > 0]
            latest = psubs[-1] if psubs else {}
            latest_diag = _rich_diagnosis(latest.get("diagnosis", {}))
            latest_kg = _safe_kg_analysis(latest.get("kg_analysis", {}))
            latest_hyper = _safe_hypergraph_insight(latest.get("hypergraph_insight", {}))
            latest_hyper_student = _safe_hypergraph_student(
                latest.get("hypergraph_student")
                or (latest.get("agent_outputs", {}) if isinstance(latest.get("agent_outputs"), dict) else {}).get("hypergraph_student", {})
            )
            latest_hyper_project_view = (
                latest.get("hypergraph_project_view")
                if isinstance(latest.get("hypergraph_project_view"), dict)
                else {}
            )
            latest_task = latest.get("next_task", {}) if isinstance(latest.get("next_task"), dict) else {}
            latest_phase = _safe_str(latest.get("project_phase", "")) or "持续迭代"
            intent_mix: dict[str, int] = {}
            shape_mix: dict[str, int] = {}
            phase_history: list[dict] = []
            risk_evidence: list[dict] = []
            latest_quotes: list[dict] = []
            for s in psubs:
                intent = _normalize_intent(
                    s.get("intent")
                    or ((s.get("agent_outputs", {}) if isinstance(s.get("agent_outputs"), dict) else {}).get("orchestration", {}) or {}).get("intent", ""),
                    _safe_str(s.get("raw_text", "")),
                )
                intent_mix[intent] = intent_mix.get(intent, 0) + 1
                student_intent_mix[intent] = student_intent_mix.get(intent, 0) + 1
                shape = _submission_intent_shape(s)
                shape_mix[shape] = shape_mix.get(shape, 0) + 1
                student_shape_mix[shape] = student_shape_mix.get(shape, 0) + 1
                phase_history.append({
                    "created_at": s.get("created_at", ""),
                    "phase": _safe_str(s.get("project_phase", "")) or latest_phase,
                    "intent": intent,
                    "intent_shape": shape,
                    "score": s["_score"],
                })
                for q in _safe_evidence_quotes(s.get("evidence_quotes", [])):
                    risk_evidence.append({
                        **q,
                        "created_at": s.get("created_at", ""),
                    })
                if s is latest:
                    latest_quotes = _safe_evidence_quotes(s.get("evidence_quotes", []))
            top_risks = []
            for _r in (latest_diag.get("triggered_rules") or [])[:4]:
                rid = _r if isinstance(_r, str) else (_r.get("id") or _r.get("rule_id") or _r.get("name") or "")
                if rid:
                    top_risks.append(rid)
            project_name = _project_label(pid, psubs)
            project_summary = (
                latest_hyper.get("summary")
                or latest_kg.get("insight")
                or latest_diag.get("bottleneck")
                or _safe_str(latest_task.get("description", ""))
                or "该项目还在持续迭代中。"
            )
            card = {
                "project_id": pid,
                "project_name": project_name,
                "project_phase": latest_phase,
                "submission_count": len(psubs),
                "avg_score": round(sum(p_scores) / len(p_scores), 1) if p_scores else 0,
                "first_score": p_scores[0] if p_scores else 0,
                "latest_score": p_scores[-1] if p_scores else 0,
                "improvement": round(p_scores[-1] - p_scores[0], 1) if len(p_scores) >= 2 else 0,
                "current_summary": project_summary,
                "intent_distribution": intent_mix,
                "intent_shape_distribution": shape_mix,
                "top_risks": top_risks,
                "latest_task": {
                    "title": _safe_str(latest_task.get("title", "")),
                    "description": _safe_str(latest_task.get("description", "")),
                    "acceptance_criteria": [_safe_str(x) for x in (latest_task.get("acceptance_criteria") or [])[:4]],
                },
                "teacher_intervention": _teacher_intervention_hint(intent_mix, latest_phase, top_risks),
                "latest_diagnosis": latest_diag,
                "latest_kg": latest_kg,
                "latest_hypergraph": latest_hyper,
                "latest_hypergraph_student": latest_hyper_student,
                "latest_hypergraph_project_view": latest_hyper_project_view,
                "risk_evidence": risk_evidence[-10:],
                "evidence_quotes": latest_quotes,
                "phase_history": phase_history,
                "submissions": [
                    {
                        "submission_id": s.get("submission_id", ""),
                        "created_at": s.get("created_at", ""),
                        "project_phase": _safe_str(s.get("project_phase", "")) or latest_phase,
                        "logical_project_id": pid,
                        "overall_score": s["_score"],
                        "intent": _normalize_intent(
                            s.get("intent")
                            or ((s.get("agent_outputs", {}) if isinstance(s.get("agent_outputs"), dict) else {}).get("orchestration", {}) or {}).get("intent", ""),
                            _safe_str(s.get("raw_text", "")),
                        ),
                        "intent_confidence": float(s.get("intent_confidence", 0) or 0),
                        "intent_shape": _submission_intent_shape(s),
                        "source_type": s.get("source_type", "text"),
                        "filename": s.get("filename"),
                        "bottleneck": _safe_str(s.get("diagnosis", {}).get("bottleneck") or s.get("next_task", {}).get("bottleneck", "")),
                        "next_task": (
                            s.get("next_task")
                            if isinstance(s.get("next_task"), dict)
                            else {"description": _safe_str(s.get("next_task", ""))}
                        ),
                        "triggered_rules": _rich_triggered_rules(
                            s.get("triggered_rules") or s.get("diagnosis", {}).get("triggered_rules", [])
                        ),
                        "text_preview": (s.get("raw_text") or "")[:80],
                        "evidence_quotes": _safe_evidence_quotes(s.get("evidence_quotes", [])),
                        "diagnosis": _rich_diagnosis(s.get("diagnosis", {})),
                        "agent_outputs": _safe_agent_summary(s),
                        "kg_analysis": _safe_kg_analysis(s.get("kg_analysis", {})),
                        "hypergraph_insight": _safe_hypergraph_insight(s.get("hypergraph_insight", {})),
                        "hypergraph_student": _safe_hypergraph_student(
                            s.get("hypergraph_student")
                            or (s.get("agent_outputs", {}) if isinstance(s.get("agent_outputs"), dict) else {}).get("hypergraph_student", {})
                        ),
                        "hypergraph_project_view": (
                            s.get("hypergraph_project_view")
                            if isinstance(s.get("hypergraph_project_view"), dict)
                            else {}
                        ),
                        "hyper_consistency_issues": (
                            s.get("hyper_consistency_issues")
                            if isinstance(s.get("hyper_consistency_issues"), list)
                            else []
                        ),
                    }
                    for s in psubs
                ],
            }
            proj_list.append(card)
            project_snapshot_cards.append({
                "project_id": pid,
                "project_name": project_name,
                "project_phase": latest_phase,
                "latest_score": card["latest_score"],
                "top_risks": top_risks,
                "intent_distribution": intent_mix,
                "current_summary": project_summary,
            })
            latest_project_phase = latest_phase or latest_project_phase
            if not latest_summary:
                latest_summary = project_summary
        result["projects"] = proj_list
        result["intent_distribution"] = student_intent_mix
        result["intent_shape_distribution"] = student_shape_mix
        result["latest_phase"] = latest_project_phase or "持续迭代"
        result["student_case_summary"] = latest_summary or "该学生已有可追踪的多轮项目记录。"
        result["teacher_intervention"] = _teacher_intervention_hint(student_intent_mix, result["latest_phase"], [])
        result["project_snapshots"] = project_snapshot_cards

        # ── Student portrait enrichment (read from raw subs to avoid _safe_diagnosis stripping rubric) ──
        rubric_scores_all: dict[str, list[float]] = {}
        growth_points: list[dict] = []
        submission_dates: list[str] = []
        for _pid, raw_psubs in projects_map.items():
            for sub in raw_psubs:
                diag = sub.get("diagnosis", {})
                if isinstance(diag, dict):
                    for r_item in (diag.get("rubric_scores") or diag.get("rubric") or []):
                        if isinstance(r_item, dict) and r_item.get("item"):
                            rubric_scores_all.setdefault(r_item["item"], []).append(float(r_item.get("score", 0) or 0))
                created = sub.get("created_at", "")
                sc = float(sub.get("_score", 0) or sub.get("overall_score", 0) or 0)
                if created:
                    submission_dates.append(created)
                if sc > 0 and created:
                    growth_points.append({"date": created, "score": sc})

        rubric_heatmap = []
        strength_dims: list[str] = []
        weakness_dims: list[str] = []
        for rname, rscores in rubric_scores_all.items():
            avg_rs = round(sum(rscores) / len(rscores), 1) if rscores else 0
            dim_rationale = {
                "field": f"rubric_heatmap:{rname}",
                "value": avg_rs,
                "formula": "avg(submission_dim_scores)",
                "formula_display": (
                    f"{rname} 均分 = Σ({len(rscores)} 次提交的该维度分) ÷ {len(rscores)}\n"
                    f"= ({' + '.join(f'{s:.1f}' for s in rscores[:6])}"
                    + (" + …" if len(rscores) > 6 else "")
                    + f") ÷ {len(rscores)}\n"
                    f"= {avg_rs}"
                ),
                "inputs": [
                    {"label": f"提交 {i+1}", "value": round(float(s), 2)}
                    for i, s in enumerate(rscores[:12])
                ],
                "note": f"近期 {len(rscores)} 次 · 均值 {avg_rs}",
            }
            rubric_heatmap.append({
                "item": rname,
                "avg_score": avg_rs,
                "count": len(rscores),
                "rationale": dim_rationale,
            })
            if avg_rs >= 7:
                strength_dims.append(rname)
            elif avg_rs < 5:
                weakness_dims.append(rname)

        submission_dates.sort()
        submit_interval_days = 0.0
        if len(submission_dates) >= 2:
            try:
                from datetime import datetime as _dt
                first_d = _dt.fromisoformat(submission_dates[0].replace("Z", "+00:00"))
                last_d = _dt.fromisoformat(submission_dates[-1].replace("Z", "+00:00"))
                span = (last_d - first_d).total_seconds() / 86400
                submit_interval_days = round(span / max(len(submission_dates) - 1, 1), 1)
            except Exception:
                pass

        improvement_rate = 0.0
        if growth_points and len(growth_points) >= 2:
            improvement_rate = round(growth_points[-1]["score"] - growth_points[0]["score"], 1)

        strength_rationale = {
            "field": "portrait:strength_dimensions",
            "value": ", ".join(strength_dims) or "—",
            "formula": "filter(rubric_heatmap where avg >= 7)",
            "formula_display": (
                "优势维度 = 所有 rubric 维度中均分 ≥ 7 的维度集合。\n"
                + "\n".join(
                    f"- {h['item']}：{h['avg_score']}（{h['count']} 次）"
                    for h in rubric_heatmap if h["avg_score"] >= 7
                )
                or "当前无均分 ≥ 7 的维度，需继续夯实。"
            ),
            "inputs": [
                {"label": h["item"], "value": h["avg_score"], "impact": f"{h['count']} 次提交"}
                for h in rubric_heatmap if h["avg_score"] >= 7
            ],
            "note": "优势阈值：7/10",
        }
        weakness_rationale = {
            "field": "portrait:weakness_dimensions",
            "value": ", ".join(weakness_dims) or "—",
            "formula": "filter(rubric_heatmap where avg < 5)",
            "formula_display": (
                "待加强维度 = 所有 rubric 维度中均分 < 5 的维度集合。\n"
                + "\n".join(
                    f"- {h['item']}：{h['avg_score']}（{h['count']} 次）"
                    for h in rubric_heatmap if h["avg_score"] < 5
                )
                or "暂无明显短板。"
            ),
            "inputs": [
                {"label": h["item"], "value": h["avg_score"], "impact": f"{h['count']} 次提交"}
                for h in rubric_heatmap if h["avg_score"] < 5
            ],
            "note": "短板阈值：5/10",
        }
        growth_rationale = {
            "field": "portrait:growth_trajectory",
            "value": f"首末差 {improvement_rate:+.1f}",
            "formula": "last_score − first_score",
            "formula_display": (
                f"成长轨迹：共 {len(growth_points)} 个打分点。\n"
                f"首次 {growth_points[0]['score'] if growth_points else '—'} →"
                f" 最新 {growth_points[-1]['score'] if growth_points else '—'}\n"
                f"提升幅度 = {improvement_rate:+.1f}"
            ),
            "inputs": [
                {"label": p.get("date", "")[:10], "value": p.get("score", 0)}
                for p in growth_points[-6:]
            ],
            "note": f"平均提交间隔 {submit_interval_days} 天",
        }
        result["portrait"] = {
            "strength_dimensions": strength_dims,
            "strength_rationale": strength_rationale,
            "weakness_dimensions": weakness_dims,
            "weakness_rationale": weakness_rationale,
            "growth_trajectory": growth_points[-20:],
            "growth_rationale": growth_rationale,
            "rubric_heatmap": rubric_heatmap,
            "behavioral_pattern": {
                "total_submissions": len(subs),
                "avg_submit_interval_days": submit_interval_days,
                "improvement_rate": improvement_rate,
                "active_days_span": submit_interval_days * max(len(submission_dates) - 1, 1),
            },
        }

    return result


def _topic_terms(text: str) -> set[str]:
    if not text:
        return set()
    parts = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}", text.lower())
    return {p.strip() for p in parts if len(p.strip()) >= 2}


def _build_scoped_project_state(project_state: dict, conversation_id: str, message: str) -> tuple[dict, str]:
    submissions = list(project_state.get("submissions", []) or [])
    if not submissions:
        return project_state, ""

    msg_terms = _topic_terms(message)
    recent = submissions[-10:]
    same_conv = [row for row in recent if conversation_id and row.get("conversation_id") == conversation_id]

    def _row_score(row: dict) -> int:
        score = 0
        if conversation_id and row.get("conversation_id") == conversation_id:
            score += 100
        hay = " ".join([
            str(row.get("raw_text", "") or ""),
            str((row.get("next_task") or {}).get("title", "") if isinstance(row.get("next_task"), dict) else ""),
            str((row.get("diagnosis") or {}).get("bottleneck", "") if isinstance(row.get("diagnosis"), dict) else ""),
            str((row.get("kg_analysis") or {}).get("insight", "") if isinstance(row.get("kg_analysis"), dict) else ""),
        ])
        row_terms = _topic_terms(hay)
        score += len(msg_terms.intersection(row_terms)) * 8
        if row.get("created_at"):
            score += 1
        return score

    # Only pull from other conversations if they belong to the same logical_project_id
    cur_logical_id = None
    for sc in reversed(same_conv):
        if sc.get("logical_project_id"):
            cur_logical_id = sc["logical_project_id"]
            break

    relevant_other = []
    for row in recent:
        if row in same_conv:
            continue
        if cur_logical_id and row.get("logical_project_id") == cur_logical_id:
            relevant_other.append(row)
    relevant_other.sort(key=_row_score, reverse=True)

    selected: list[dict] = []
    selected.extend(same_conv[-6:])
    selected.extend([row for row in relevant_other[:2] if _row_score(row) > 0])
    if not selected:
        selected = recent[-2:]

    seen_ids = set()
    normalized = []
    for row in selected:
        sid = row.get("submission_id") or id(row)
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        normalized.append(row)

    history_context = ""
    for row in normalized[-4:]:
        snippet = (row.get("raw_text") or "")[:180]
        task = (row.get("next_task") or {}).get("title", "") if isinstance(row.get("next_task"), dict) else ""
        insight = (row.get("kg_analysis") or {}).get("insight", "") if isinstance(row.get("kg_analysis"), dict) else ""
        if snippet:
            history_context += f"- 历史相关内容：{snippet}…"
            if task:
                history_context += f" → 任务：{task}"
            if insight:
                history_context += f" → 洞察：{insight[:40]}"
            history_context += "\n"

    scoped = {**project_state, "submissions": normalized}

    # For brand-new conversations (no same_conv history), only expose
    # public profile fields to avoid cross-conversation memory bleed.
    if not same_conv:
        full_profile = scoped.get("student_profile")
        if isinstance(full_profile, dict):
            _public_keys = {"interest_domains", "name", "grade", "major", "school", "team_name"}
            scoped["student_profile"] = {
                k: v for k, v in full_profile.items() if k in _public_keys
            }

    return scoped, history_context


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
        team_intent_mix: dict[str, int] = {}
        team_phase_mix: dict[str, int] = {}
        team_risk_mix: dict[str, int] = {}
        project_cards: list[dict] = []

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
                "latest_phase": stats.get("latest_phase", ""),
                "intent_distribution": stats.get("intent_distribution", {}),
                "student_case_summary": stats.get("student_case_summary", ""),
                "teacher_intervention": stats.get("teacher_intervention", ""),
                "project_snapshots": stats.get("project_snapshots", []),
            }
            if is_mine and "projects" in stats:
                stu["projects"] = stats["projects"]
            students.append(stu)
            team_sub_count += stats["total_submissions"]
            team_risk += stats["risk_count"]
            if stats["avg_score"] > 0:
                team_scores.append(stats["avg_score"])
            phase = _safe_str(stats.get("latest_phase", ""))
            if phase:
                team_phase_mix[phase] = team_phase_mix.get(phase, 0) + 1
            for intent, count in (stats.get("intent_distribution", {}) or {}).items():
                team_intent_mix[intent] = team_intent_mix.get(intent, 0) + int(count or 0)
            for snap in (stats.get("project_snapshots", []) or [])[:6]:
                if isinstance(snap, dict):
                    project_cards.append({
                        **snap,
                        "student_id": uid,
                        "display_name": display_name,
                    })
                    for risk in (snap.get("top_risks") or [])[:4]:
                        r = _safe_str(risk)
                        if r:
                            team_risk_mix[r] = team_risk_mix.get(r, 0) + 1

        team_avg = round(sum(team_scores) / len(team_scores), 1) if team_scores else 0.0
        risk_rate = round(team_risk / max(team_sub_count, 1) * 100, 1)
        team_trend = 0.0
        if len(team_scores) >= 2:
            mid = len(team_scores) // 2
            team_trend = round(
                sum(team_scores[mid:]) / max(1, len(team_scores) - mid)
                - sum(team_scores[:mid]) / max(1, mid), 1
            )
        active_students = len([s for s in students if s.get("total_submissions", 0) > 0])
        submission_density = round(team_sub_count / max(len(members), 1), 1)
        project_cards.sort(key=lambda p: float(p.get("latest_score", 0) or 0), reverse=True)
        dominant_intent = max(team_intent_mix.items(), key=lambda kv: kv[1])[0] if team_intent_mix else ""
        top_risks = [k for k, _ in sorted(team_risk_mix.items(), key=lambda kv: kv[1], reverse=True)[:4]]
        care_points = []
        if dominant_intent:
            care_points.append(f"团队当前求助最多的是“{dominant_intent}”。")
        if top_risks:
            care_points.append(f"高频风险集中在 {', '.join(top_risks[:2])}。")
        if submission_density:
            care_points.append(f"人均提交 {submission_density} 次，可用于判断迭代活跃度。")

        team_out = {
            "team_id": t["team_id"],
            "team_name": t["team_name"],
            "teacher_name": t.get("teacher_name", ""),
            "invite_code": t.get("invite_code", "") if is_mine else "",
            "is_mine": is_mine,
            "student_count": len(members),
            "active_students": active_students,
            "submission_density": submission_density,
            "avg_score": team_avg,
            "total_submissions": team_sub_count,
            "risk_rate": risk_rate,
            "trend": team_trend,
            "intent_distribution": team_intent_mix,
            "phase_distribution": team_phase_mix,
            "top_risks": top_risks,
            "care_points": care_points,
            "project_highlights": project_cards[:8],
            "team_insight": _build_team_insight_payload(t["team_id"]),
        }
        if is_mine:
            team_out["students"] = students
        else:
            team_out["students_summary"] = [
                {"student_id": s["student_id"], "display_name": s["display_name"],
                 "avg_score": s["avg_score"], "total_submissions": s["total_submissions"],
                 "trend": s["trend"], "latest_phase": s.get("latest_phase", ""),
                 "intent_distribution": s.get("intent_distribution", {}),
                 "student_case_summary": s.get("student_case_summary", "")}
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
    logical_project_id = _derive_logical_project_id(project_state, None, payload.input_text, payload.project_id)
    project_phase = _infer_project_phase(payload.input_text, coach.get("next_task", {}), {})
    intent = _normalize_intent(inferred_category, payload.input_text)
    json_store.append_submission(
        payload.project_id,
        {
            "student_id": payload.student_id,
            "class_id": payload.class_id,
            "cohort_id": payload.cohort_id,
            "logical_project_id": logical_project_id,
            "project_phase": project_phase,
            "intent": intent,
            "intent_confidence": 0.45,
            "source_type": "text",
            "mode": payload.mode,
            "raw_text": payload.input_text[:6000],
            "diagnosis": coach["diagnosis"],
            "next_task": coach["next_task"],
            "hypergraph_insight": hyper_insight,
            "evidence_quotes": _extract_evidence_quotes(payload.input_text, coach.get("diagnosis", {})),
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
    logical_project_id = _derive_logical_project_id(project_state, None, extracted_text[:800], project_id)
    project_phase = _infer_project_phase(extracted_text, coach.get("next_task", {}), {})
    intent = _normalize_intent(inferred_category, extracted_text)
    json_store.append_submission(
        project_id,
        {
            "student_id": student_id,
            "class_id": class_id or None,
            "cohort_id": cohort_id or None,
            "logical_project_id": logical_project_id,
            "project_phase": project_phase,
            "intent": intent,
            "intent_confidence": 0.45,
            "source_type": "file",
            "mode": mode,
            "filename": file.filename,
            "raw_text": extracted_text[:6000],
            "diagnosis": coach["diagnosis"],
            "next_task": coach["next_task"],
            "hypergraph_insight": hyper_insight,
            "evidence_quotes": _extract_evidence_quotes(extracted_text, coach.get("diagnosis", {}), file.filename),
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


@app.post("/api/student/video-analysis", response_model=VideoAnalysisResponse)
async def student_video_analysis(
    project_id: str = Form(...),
    student_id: str = Form(...),
    class_id: str = Form(""),
    cohort_id: str = Form(""),
    mode: str = Form("competition"),
    competition_type: str = Form(""),
    conversation_id: str = Form(""),
    file: UploadFile = File(...),
) -> VideoAnalysisResponse:
    """学生端路演视频同步分析接口。

    特点：
    - 与多智能体对话工作流解耦，不写入 agent_trace；
    - 使用语音转写 + 诊断引擎 Rubric 打分；
    - 结果持久化到 project_state.video_analyses，便于教师和学生事后回看。
    """

    if not file.filename:
        raise HTTPException(status_code=400, detail="请上传有效的视频文件。")

    analyzer = VideoPitchAnalyzer()
    safe_mode = (mode or "competition").strip() or "competition"
    safe_comp = (competition_type or "").strip()

    # 构造与当前对话相关的精简上下文，帮助模型理解项目背景
    project_state = json_store.load_project(project_id)
    ctx_summary = ""
    latest_user_msg = ""
    conv_id_val = (conversation_id or "").strip() or None
    try:
        ctx_summary, _latest_sub = _summarize_latest_diagnosis_for_poster(
            project_state,
            student_id=student_id or None,
            conversation_id=conv_id_val,
        )
    except Exception:  # noqa: BLE001
        ctx_summary = ""
    try:
        latest_user_msg = _get_latest_user_message(
            project_id,
            conversation_id=conv_id_val,
            student_id=student_id or None,
        )
    except Exception:  # noqa: BLE001
        latest_user_msg = ""

    ctx_parts: list[str] = []
    if ctx_summary:
        ctx_parts.append("【诊断概要】" + str(ctx_summary)[:800])
    if latest_user_msg:
        ctx_parts.append("【最近学生说明】" + str(latest_user_msg)[:800])
    context_text = "\n\n".join(ctx_parts)

    upload_target = settings.video_upload_root / project_id
    upload_target.mkdir(parents=True, exist_ok=True)
    target_path = upload_target / file.filename

    content = await file.read()
    try:
        target_path.write_bytes(content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to save uploaded video for %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail="保存视频文件失败，请稍后重试。") from exc

    try:
        analysis = analyzer.analyze(
            video_path=target_path,
            mode=safe_mode,
            competition_type=safe_comp,
            filename=file.filename,
            context_text=context_text,
        )
    except ValueError as exc:
        # 用户输入问题（文件过大/格式不支持/内容过短等）
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # 环境或模型未配置好
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Video analysis failed for %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail="视频分析失败，请稍后重试。") from exc

    created_at = datetime.utcnow()

    # 持久化到 project_state.video_analyses（不影响 submissions/agent_trace）
    records = project_state.get("video_analyses") or []
    if not isinstance(records, list):
        records = []
    record = {
        "project_id": project_id,
        "student_id": student_id,
        "class_id": class_id or None,
        "cohort_id": cohort_id or None,
        "mode": safe_mode,
        "competition_type": safe_comp,
        "filename": file.filename,
        "created_at": created_at.isoformat() + "Z",
        "analysis": analysis,
    }
    records.append(record)
    project_state["video_analyses"] = records
    json_store.save_project(project_id, project_state)

    return VideoAnalysisResponse(
        project_id=project_id,
        student_id=student_id,
        filename=file.filename,
        created_at=created_at,
        analysis=analysis,
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
            model=settings.llm_synthesis_model,
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

    scoped_project_state, history_context = _build_scoped_project_state(project_state, conv_id, payload.message)

    # ── teacher feedback context ──
    tfb_ctx, matched_interventions = _build_teacher_runtime_context(project_state, payload.message)

    # ── 财务结构化证据（给本轮诊断加分）──
    # 来源：① 本学生最新 finance_report 的 merged_evidence
    #       ② 最近一条 assistant 消息里的 finance_advisory.evidence_for_diagnosis
    structured_signals: dict[str, float] = {}
    try:
        _user_key = (payload.student_id or "").strip().lower()
        if _user_key and _user_key != "none":
            _latest_report = finance_report_service.load_latest(_user_key)
            if _latest_report:
                for _k, _v in (_latest_report.get("merged_evidence") or {}).items():
                    structured_signals[_k] = max(structured_signals.get(_k, 0.0), float(_v))
    except Exception:
        pass
    try:
        for _prev in reversed(conv_messages[-8:]):
            if not isinstance(_prev, dict):
                continue
            _trace = _prev.get("agent_trace") or {}
            _adv = _trace.get("finance_advisory") or {}
            for _k, _v in (_adv.get("evidence_for_diagnosis") or {}).items():
                structured_signals[_k] = max(structured_signals.get(_k, 0.0), float(_v))
            if _adv:
                break
    except Exception:
        pass

    # ── run LangGraph workflow ──
    result = run_workflow(
        message=payload.message,
        mode=payload.mode,
        project_state=scoped_project_state,
        history_context=history_context,
        conversation_messages=conv_messages,
        teacher_feedback_context=tfb_ctx,
        competition_type=getattr(payload, "competition_type", "") or "",
        structured_signals=structured_signals,
    )

    # ── 对话旁路：财务守望 guard（不调 LLM，<500ms）──
    finance_advisory: dict = {}
    try:
        _user_key = (payload.student_id or "").strip().lower()
        _budget_snap = None
        if _user_key and _user_key != "none":
            try:
                _plans = budget_store.list_plans(_user_key)
                if _plans:
                    _budget_snap = budget_store.load(_user_key, _plans[0].get("plan_id", ""))
            except Exception:
                _budget_snap = None
        _industry_hint = result.get("category", "") or ""
        finance_advisory = finance_guard_scan(
            text=payload.message,
            history=conv_messages,
            budget_snapshot=_budget_snap,
            user_id=_user_key,
            industry_hint=_industry_hint,
        )
    except Exception as _fg_err:
        logger.warning("finance_guard failed silently: %s", _fg_err)
        finance_advisory = {}

    # ── 对话→预算自动回写（finance_signal_extractor）──
    finance_auto_apply: dict = {}
    try:
        if _user_key and _user_key != "none":
            # fallback pattern 取项目当前 dominant pattern（若有）
            _fallback_pattern = None
            try:
                if _budget_snap:
                    _biz = _budget_snap.get("business_finance") or {}
                    _streams = _biz.get("revenue_streams") or []
                    if _streams:
                        _fallback_pattern = (_streams[0] or {}).get("pattern_key")
            except Exception:
                _fallback_pattern = None
            _signals = finance_signal_extract(
                payload.message,
                history=conv_messages,
                fallback_pattern=_fallback_pattern,
            )
            if _signals.get("triggered") and _signals.get("pattern_inputs"):
                # 选当前 plan_id（若没有就用第一个）
                _plan_id_for_apply = ""
                try:
                    _plan_id_for_apply = (_plans[0].get("plan_id") if _plans else "") or ""
                except Exception:
                    _plan_id_for_apply = ""
                if _plan_id_for_apply:
                    _msg_id_for_apply = f"{conv_id}#{len((conv_store.get(payload.project_id, conv_id) or {}).get('messages') or [])}"
                    _apply_res = finance_signal_apply(
                        user_id=_user_key,
                        plan_id=_plan_id_for_apply,
                        signals=_signals,
                        source_message_id=_msg_id_for_apply,
                        confidence_threshold=0.6,
                        overwrite=False,  # 已有人工值时不覆盖, 仅写入 _ai_meta.suggestions
                    )
                    finance_auto_apply = {
                        "signals": {
                            "primary_pattern": _signals.get("primary_pattern"),
                            "primary_pattern_label": _signals.get("primary_pattern_label"),
                            "summary": _signals.get("summary"),
                            "candidate_patterns": _signals.get("candidate_patterns"),
                            "pattern_inputs": _signals.get("pattern_inputs"),
                            "kind": _signals.get("kind"),
                        },
                        "applied": _apply_res.get("applied") or [],
                        "skipped": _apply_res.get("skipped") or [],
                        "stream_added": _apply_res.get("stream_added"),
                        "plan_id": _plan_id_for_apply,
                    }
    except Exception as _fa_err:
        logger.warning("finance_signal auto-apply failed silently: %s", _fa_err)
        finance_auto_apply = {}

    diagnosis = result.get("diagnosis", {})
    next_task = result.get("next_task", {})
    category = result.get("category", "")
    kg_analysis = result.get("kg_analysis", {})
    assistant_message = result.get("assistant_message", "")
    nodes_visited = result.get("nodes_visited", [])
    agents_called = result.get("agents_called", [])

    # ── 给 KG 实体/关系补 source_message_id（{conv_id}#{turn_index}），
    #     配合 graph_workflow 里写入的 source_span，可以点实体跳回原消息 ──
    try:
        _conv_obj_for_msgid = conv_store.get(payload.project_id, conv_id) or {}
        _msgs_for_id = list(_conv_obj_for_msgid.get("messages") or [])
        _next_user_turn = len(_msgs_for_id)  # 这一条 user 消息即将被追加
        _user_msg_id = f"{conv_id}#{_next_user_turn}"
        if isinstance(kg_analysis, dict):
            for _ent in kg_analysis.get("entities", []) or []:
                if isinstance(_ent, dict) and not _ent.get("source_message_id"):
                    _ent["source_message_id"] = _user_msg_id
            for _rel in kg_analysis.get("relationships", []) or []:
                if isinstance(_rel, dict) and not _rel.get("source_message_id"):
                    _rel["source_message_id"] = _user_msg_id
    except Exception as _tx:
        logger.info("kg source_message_id enrich failed: %s", _tx)

    hyper_insight = result.get("hypergraph_insight", {})
    hyper_student = result.get("hypergraph_student", {})
    rag_cases = result.get("rag_cases", [])
    web_search = result.get("web_search_result", {})
    logical_project_id = _derive_logical_project_id(project_state, conv_id, payload.message, payload.project_id)
    project_phase = _infer_project_phase(payload.message, next_task, kg_analysis)
    intent = _normalize_intent(result.get("intent", ""), payload.message)
    intent_confidence = float(result.get("intent_confidence", 0) or 0)
    intent_shape = _safe_str(result.get("intent_shape", "")) or "single"
    evidence_quotes = _extract_evidence_quotes(payload.message, diagnosis)
    import logging as _log
    _log.getLogger("main").info("API response: hyper_student.ok=%s, kg_entities=%d", hyper_student.get("ok"), len(kg_analysis.get("entities", [])))

    # Enrich rubric entries with trend (delta from previous turn)
    _cur_rubric = diagnosis.get("rubric") if isinstance(diagnosis, dict) else []
    if _cur_rubric and conv_messages:
        _prev_rubric_map: dict[str, float] = {}
        for _hm in reversed(conv_messages):
            _hm_trace = _hm.get("agent_trace") if isinstance(_hm, dict) else None
            if isinstance(_hm_trace, dict):
                _hm_diag = _hm_trace.get("diagnosis") or {}
                if isinstance(_hm_diag, dict) and _hm_diag.get("rubric"):
                    for _pr in _hm_diag["rubric"]:
                        if isinstance(_pr, dict) and _pr.get("item"):
                            _prev_rubric_map[_pr["item"]] = float(_pr.get("score", 0))
                    break
        if _prev_rubric_map:
            for _cr in _cur_rubric:
                if isinstance(_cr, dict) and _cr.get("item"):
                    _prev_s = _prev_rubric_map.get(_cr["item"])
                    if _prev_s is not None:
                        _diff = round(float(_cr.get("score", 0)) - _prev_s, 2)
                        _cr["trend"] = "up" if _diff > 0.1 else "down" if _diff < -0.1 else "stable"
                        _cr["prev_score"] = _prev_s

    # ── persist project cognition state (track vector / stage / history) ──
    # 注意：必须在 _build_agent_trace 之前完成融合，并把“真正落库的平滑后向量”
    # 回写到 result，前端 agent_trace 才会和持久化状态保持一致。
    project_state = ensure_project_cognition(project_state)
    _raw_track_meta = result.get("track_inference_meta") if isinstance(result.get("track_inference_meta"), dict) else {}
    project_state, _track_snapshot = merge_track_vector(
        project_state,
        {
            "track_vector": result.get("track_vector", {}),
            "confidence": _raw_track_meta.get("confidence", 0),
            "source_mix": _raw_track_meta.get("source_mix", {}),
            "reason": _raw_track_meta.get("last_reason", ""),
            "evidence": _raw_track_meta.get("last_evidence", []),
        },
        source=str((result.get("track_vector") or {}).get("source") or "inferred"),
    )
    project_state["project_stage_v2"] = infer_project_stage_v2(diagnosis, project_state)
    json_store.save_project(payload.project_id, project_state)
    # 用平滑后的值回写 result，后续 agent_trace / 前端 / KB 都看到同一份数据。
    result["track_vector"] = dict(project_state.get("track_vector") or {})
    result["project_stage_v2"] = project_state.get("project_stage_v2", "")
    result["track_inference_meta"] = dict(project_state.get("track_inference_meta") or {})
    result["track_history"] = list(project_state.get("track_history") or [])

    agent_trace = _build_agent_trace(
        result,
        mode=payload.mode,
        llm_enabled=composer_llm.enabled,
        matched_interventions=matched_interventions,
    )
    if finance_advisory.get("triggered"):
        agent_trace["finance_advisory"] = finance_advisory
    if finance_auto_apply:
        agent_trace["finance_auto_apply"] = finance_auto_apply

    # ── persist to project state ──
    _sync_sid = payload.student_id.strip() if payload.student_id and payload.student_id.lower() != "none" else (
        payload.project_id.replace("project-", "", 1) if payload.project_id.startswith("project-") else "student"
    )
    json_store.append_submission(
        payload.project_id,
        {
            "student_id": _sync_sid,
            "conversation_id": conv_id,
            "class_id": payload.class_id,
            "cohort_id": payload.cohort_id,
            "logical_project_id": logical_project_id,
            "project_phase": project_phase,
            "intent": intent,
            "intent_confidence": intent_confidence,
            "intent_shape": intent_shape,
            "source_type": "dialogue_turn",
            "mode": payload.mode,
            "raw_text": payload.message[:6000],
            "track_vector": project_state.get("track_vector", {}),
            "project_stage_v2": project_state.get("project_stage_v2", ""),
            "diagnosis": diagnosis,
            "next_task": next_task,
            "kg_analysis": kg_analysis,
            "hypergraph_insight": hyper_insight,
            "hypergraph_student": hyper_student,
            "evidence_quotes": evidence_quotes,
            "matched_teacher_interventions": matched_interventions,
            "agent_outputs": agent_trace,
        },
    )

    # ── merge student identity into project profile (cross-session memory) ──
    _sid = result.get("_student_identity")
    if isinstance(_sid, dict) and _sid:
        try:
            _proj = json_store.load_project(payload.project_id) or {}
            _existing_profile = _proj.get("student_profile") or {}
            _merged_profile = {**_existing_profile}
            for _pk, _pv in _sid.items():
                if _pv and str(_pv).strip():
                    _merged_profile[_pk] = str(_pv).strip()
            if _merged_profile != _existing_profile:
                _proj["student_profile"] = _merged_profile
                json_store.save_project(payload.project_id, _proj)
        except Exception:
            pass

    # ── persist to conversation ──
    conv_store.append_message(payload.project_id, conv_id, {
        "role": "user", "content": payload.message,
    })
    llm_title = _generate_conversation_title(payload.message, assistant_message, category)
    conv_store.append_message(payload.project_id, conv_id, {
        "role": "assistant", "content": assistant_message,
        "agent_trace": {
            **agent_trace,
            "diagnosis": diagnosis,
            "next_task": next_task,
            "kg_analysis": kg_analysis,
            "hypergraph_insight": hyper_insight,
            "pressure_test_trace": result.get("pressure_test_trace"),
            "matched_teacher_interventions": matched_interventions,
            "execution_trace": result.get("execution_trace", {}),
            "exploration_state": result.get("exploration_state", {}),
        },
    }, generated_title=llm_title or None)

    # ── 竞赛教练议题板：若该会话关联的计划书处于 competition 教练模式，
    #     对本轮 assistant 回复做一次轻量议题抽取并入库 ────────────────
    try:
        latest_plan = business_plan_service.get_latest(payload.project_id, conv_id)
        if latest_plan and str(latest_plan.get("coaching_mode") or "project") == "competition":
            conv_obj = conv_store.get(payload.project_id, conv_id) or {}
            turn_index_latest = max(len(list(conv_obj.get("messages") or [])) - 1, 0)
            source_message_id = f"{conv_id}#{turn_index_latest}"
            business_plan_service.note_agenda_signal(
                str(latest_plan.get("plan_id") or ""),
                assistant_text=assistant_message,
                source_message_id=source_message_id,
            )
    except Exception as _agenda_exc:  # noqa: BLE001
        logger.info("competition agenda extract failed: %s", _agenda_exc)

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
        pressure_test_trace=result.get("pressure_test_trace", {}),
        agent_trace=agent_trace,
        insight_sources={
            "case_transfer_insight": result.get("case_transfer_insight", ""),
            "hyper_narrative": result.get("hyper_narrative", ""),
            "web_facts": result.get("web_facts", []),
            "gather_layers": {
                "data_maturity": result.get("_data_maturity", "unknown"),
                "l1_ran": any([
                    result.get("_l1_hyper_teaching_ran"),
                    result.get("_l1_hyper_student_ran"),
                    result.get("_l1_neo4j_graph_ran"),
                ]),
            },
        },
        logical_project_id=logical_project_id or "",
        track_vector=dict(project_state.get("track_vector") or {}),
        project_stage_v2=project_state.get("project_stage_v2", "") or "",
        track_history=list(project_state.get("track_history") or [])[-20:],
        track_inference_meta=dict(project_state.get("track_inference_meta") or {}),
    )


@app.post("/api/dialogue/turn-stream")
async def dialogue_turn_stream(request: Request):
    """SSE streaming endpoint: runs workflow, then streams orchestrator reply."""
    from app.services.graph_workflow import run_workflow_pre_orchestrate, stream_orchestrator

    payload = await request.json()
    msg = payload.get("message", "")
    project_id = payload.get("project_id", "demo")
    _raw_sid = str(payload.get("student_id") or "").strip()
    student_id = _raw_sid if _raw_sid and _raw_sid.lower() != "none" else (
        project_id.replace("project-", "", 1) if project_id.startswith("project-") else "student"
    )
    initial_conv_id = payload.get("conversation_id", "")
    mode_val = payload.get("mode", "coursework")
    comp_type_val = payload.get("competition_type", "")

    def event_stream():
        conv_id = initial_conv_id
        try:
            if conv_id:
                conv = conv_store.get(project_id, conv_id)
                conv_messages = conv.get("messages", []) if conv else []
            else:
                new_conv = conv_store.create(project_id, student_id)
                conv_id = new_conv["conversation_id"]
                conv_messages = []

            yield f"data: {json.dumps({'type': 'preparing', 'data': {'conversation_id': conv_id, 'status': 'preparing'}}, ensure_ascii=False)}\n\n"

            project_state = json_store.load_project(project_id)
            scoped_project_state, history_context = _build_scoped_project_state(project_state, conv_id, msg)
            tfb_ctx, matched_interventions = _build_teacher_runtime_context(project_state, msg)

            pre = run_workflow_pre_orchestrate(
                message=msg,
                mode=mode_val,
                project_state=scoped_project_state,
                history_context=history_context,
                conversation_messages=conv_messages,
                teacher_feedback_context=tfb_ctx,
                competition_type=comp_type_val,
            )
            logical_project_id = _derive_logical_project_id(project_state, conv_id, msg, project_id)
            project_phase = _infer_project_phase(msg, pre.get("next_task", {}), pre.get("kg_analysis", {}))
            intent = _normalize_intent(pre.get("intent", ""), msg)
            intent_confidence = float(pre.get("intent_confidence", 0) or 0)
            intent_shape = _safe_str(pre.get("intent_shape", "")) or "single"
            evidence_quotes = _extract_evidence_quotes(msg, pre.get("diagnosis", {}))

            # Enrich rubric with trend
            _s_diag = pre.get("diagnosis") if isinstance(pre.get("diagnosis"), dict) else {}
            _s_rubric = _s_diag.get("rubric") if isinstance(_s_diag, dict) else []
            if _s_rubric and conv_messages:
                _s_prev_map: dict[str, float] = {}
                for _shm in reversed(conv_messages):
                    _shm_t = _shm.get("agent_trace") if isinstance(_shm, dict) else None
                    if isinstance(_shm_t, dict):
                        _shm_d = _shm_t.get("diagnosis") or {}
                        if isinstance(_shm_d, dict) and _shm_d.get("rubric"):
                            for _spr in _shm_d["rubric"]:
                                if isinstance(_spr, dict) and _spr.get("item"):
                                    _s_prev_map[_spr["item"]] = float(_spr.get("score", 0))
                            break
                if _s_prev_map:
                    for _scr in _s_rubric:
                        if isinstance(_scr, dict) and _scr.get("item"):
                            _sp = _s_prev_map.get(_scr["item"])
                            if _sp is not None:
                                _sd = round(float(_scr.get("score", 0)) - _sp, 2)
                                _scr["trend"] = "up" if _sd > 0.1 else "down" if _sd < -0.1 else "stable"
                                _scr["prev_score"] = _sp

            agent_trace = _build_agent_trace(
                pre,
                mode=mode_val,
                llm_enabled=composer_llm.enabled,
                matched_interventions=matched_interventions,
            )

            side_data = {
                "conversation_id": conv_id,
                "logical_project_id": logical_project_id,
                "project_phase": project_phase,
                "diagnosis": pre.get("diagnosis", {}),
                "next_task": pre.get("next_task", {}),
                "kg_analysis": pre.get("kg_analysis", {}),
                "hypergraph_student": pre.get("hypergraph_student", {}),
                "hypergraph_insight": pre.get("hypergraph_insight", {}),
                "rag_cases": pre.get("rag_cases", []),
                "agent_trace": agent_trace,
                "execution_trace": pre.get("execution_trace", {}),
                "exploration_state": pre.get("exploration_state", {}),
                "insight_sources": {
                    "case_transfer_insight": pre.get("case_transfer_insight", ""),
                    "hyper_narrative": pre.get("hyper_narrative", ""),
                    "web_facts": pre.get("web_facts", []),
                    "gather_layers": {
                        "l0_tasks": ["rag", "kg"],
                        "l1_tasks_run": [k for k in ["hyper_teaching", "hyper_student", "neo4j_graph"]
                                         if pre.get(f"_l1_{k}_ran")],
                        "data_maturity": pre.get("_data_maturity", "unknown"),
                    },
                },
            }
            yield f"data: {json.dumps({'type': 'meta', 'data': side_data}, ensure_ascii=False)}\n\n"

            full_text = ""
            for chunk in stream_orchestrator(pre):
                full_text += chunk
                yield f"data: {json.dumps({'type': 'token', 'data': chunk}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'data': full_text}, ensure_ascii=False)}\n\n"

            # ── merge student identity (stream path) ──
            _sid_s = pre.get("_student_identity")
            if isinstance(_sid_s, dict) and _sid_s:
                try:
                    _proj_s = json_store.load_project(project_id) or {}
                    _ep = _proj_s.get("student_profile") or {}
                    _mp = {**_ep}
                    for _k, _v in _sid_s.items():
                        if _v and str(_v).strip():
                            _mp[_k] = str(_v).strip()
                    if _mp != _ep:
                        _proj_s["student_profile"] = _mp
                        json_store.save_project(project_id, _proj_s)
                except Exception:
                    pass

            json_store.append_submission(project_id, {
                "student_id": student_id,
                "conversation_id": conv_id,
                "logical_project_id": logical_project_id,
                "project_phase": project_phase,
                "intent": intent,
                "intent_confidence": intent_confidence,
                "intent_shape": intent_shape,
                "class_id": payload.get("class_id"),
                "cohort_id": payload.get("cohort_id"),
                "source_type": "dialogue_turn_stream",
                "mode": mode_val,
                "raw_text": msg[:6000],
                "diagnosis": pre.get("diagnosis", {}),
                "next_task": pre.get("next_task", {}),
                "kg_analysis": pre.get("kg_analysis", {}),
                "hypergraph_insight": pre.get("hypergraph_insight", {}),
                "hypergraph_student": pre.get("hypergraph_student", {}),
                "evidence_quotes": evidence_quotes,
                "matched_teacher_interventions": matched_interventions,
                "agent_outputs": agent_trace,
            })
            conv_store.append_message(project_id, conv_id, {"role": "user", "content": msg})
            stream_title = _generate_conversation_title(msg, full_text, pre.get("category", ""))
            conv_store.append_message(project_id, conv_id, {
                "role": "assistant",
                "content": full_text,
                "agent_trace": {
                    **agent_trace,
                    "diagnosis": pre.get("diagnosis", {}),
                    "next_task": pre.get("next_task", {}),
                    "kg_analysis": pre.get("kg_analysis", {}),
                    "hypergraph_insight": pre.get("hypergraph_insight", {}),
                    "pressure_test_trace": pre.get("pressure_test_trace"),
                    "matched_teacher_interventions": matched_interventions,
                    "execution_trace": pre.get("execution_trace", {}),
                    "exploration_state": pre.get("exploration_state", {}),
                },
            }, generated_title=stream_title or None)
        except Exception as exc:
            logger.warning("dialogue_turn_stream failed: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'data': {'conversation_id': conv_id, 'message': '流式生成失败，请稍后重试。', 'detail': str(exc)[:200]}}, ensure_ascii=False)}\n\n"

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
    
    scoped_project_state, history_context = _build_scoped_project_state(project_state, conv_id, combined_msg)

    result = run_workflow(
        message=combined_msg,
        mode=mode,
        project_state=scoped_project_state,
        history_context=history_context,
        conversation_messages=conv_messages,
    )

    diagnosis = result.get("diagnosis", {})
    next_task = result.get("next_task", {})
    kg_analysis = result.get("kg_analysis", {})
    assistant_message = result.get("assistant_message", "")
    hyper_insight = result.get("hypergraph_insight", {})
    hyper_student = result.get("hypergraph_student", {})
    agents_called = result.get("agents_called", [])
    logical_project_id = _derive_logical_project_id(project_state, conv_id, combined_msg, project_id)
    project_phase = _infer_project_phase(combined_msg, next_task, kg_analysis)
    intent = _normalize_intent(result.get("intent", ""), combined_msg)
    intent_confidence = float(result.get("intent_confidence", 0) or 0)
    evidence_quotes = _extract_evidence_quotes(extracted, diagnosis, file.filename)

    agent_trace = _build_agent_trace(
        result,
        mode=mode,
        llm_enabled=composer_llm.enabled,
        matched_interventions=[],
    )

    json_store.append_submission(project_id, {
        "student_id": student_id,
        "conversation_id": conv_id,
        "class_id": class_id or None,
        "cohort_id": cohort_id or None,
        "logical_project_id": logical_project_id,
        "project_phase": project_phase,
        "intent": intent,
        "intent_confidence": intent_confidence,
        "source_type": "file_in_chat",
        "mode": mode,
        "filename": file.filename,
        "raw_text": extracted[:6000],
        "diagnosis": diagnosis,
        "next_task": next_task,
        "kg_analysis": kg_analysis,
        "hypergraph_insight": hyper_insight,
        "hypergraph_student": hyper_student,
        "evidence_quotes": evidence_quotes,
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
                "每条批注都要给一个 anchor_quote，必须直接摘自该 Section 原文，长度控制在 12-60 字，作为老师划线定位。\n"
                "如果某个段落没什么好批注的，可以跳过。\n\n"
                '输出JSON: {"annotations": [\n'
                '  {"section_id": 0, "type": "issue", "comment": "...", "anchor_quote": "..."},\n'
                '  {"section_id": 1, "type": "praise", "comment": "...", "anchor_quote": "..."},\n'
                "  ...\n]}"
            ),
            user_prompt=f"模式: {mode}\n以下是学生文档的各个段落:\n{batch_text}",
            temperature=0.3,
        )
        doc_annotations = (ann_result or {}).get("annotations", [])

    conv_store.append_message(project_id, conv_id, {
        "role": "user", "content": f"[上传文件: {file.filename}] {message}",
    })
    category = result.get("category", "")
    file_title = _generate_conversation_title(message, assistant_message, category)
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
    }, generated_title=file_title or None)

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
            "每条批注都要给一个 anchor_quote，必须直接摘自该 Section 原文，长度控制在 12-60 字，作为划线定位。\n"
            "如果某个段落没什么好批注的，可以跳过(不必为每段都批注)。\n\n"
            '输出JSON: {"annotations": [\n'
            '  {"section_id": 0, "type": "issue", "comment": "...", "anchor_quote": "..."},\n'
            '  {"section_id": 1, "type": "praise", "comment": "...", "anchor_quote": "..."},\n'
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


def _summarize_latest_diagnosis_for_poster(
    project_state: dict,
    student_id: str | None = None,
    conversation_id: str | None = None,
) -> tuple[str, dict]:
    """Build a compact text summary of the latest diagnosis context for poster generation.

    Returns (summary_text, latest_submission_dict).

    If conversation_id is provided, only submissions from that conversation
    are considered. Otherwise, if student_id is provided, submissions are
    limited to that student.
    """

    submissions = list(project_state.get("submissions", []) or [])

    scoped: list[dict] = submissions
    if conversation_id:
        scoped = [s for s in submissions if str(s.get("conversation_id") or "") == conversation_id]
    elif student_id:
        sid_norm = student_id.strip()
        scoped = [s for s in submissions if str(s.get("student_id") or "").strip() == sid_norm]

    latest: dict[str, Any] | None = scoped[-1] if scoped else None
    if not latest:
        return "", {}

    diagnosis = latest.get("diagnosis", {}) if isinstance(latest.get("diagnosis"), dict) else {}
    kg = latest.get("kg_analysis", {}) if isinstance(latest.get("kg_analysis"), dict) else {}
    hyper = latest.get("hypergraph_insight", {}) if isinstance(latest.get("hypergraph_insight"), dict) else {}

    lines: list[str] = []
    overall = diagnosis.get("overall_score")
    if overall is not None:
        lines.append(f"总体评分: {overall}/10")
    bottleneck = diagnosis.get("bottleneck")
    if bottleneck:
        lines.append(f"主要瓶颈: {bottleneck}")
    rubric = diagnosis.get("rubric") or []
    if isinstance(rubric, list) and rubric:
        top_dims: list[str] = []
        for row in rubric[:8]:
            try:
                item = str(row.get("item") or "")
                score = row.get("score")
                if item and score is not None:
                    top_dims.append(f"{item}:{score}")
            except Exception:
                continue
        if top_dims:
            lines.append("Rubric 维度: " + "；".join(top_dims))
    rules = diagnosis.get("triggered_rules") or []
    if isinstance(rules, list) and rules:
        rule_texts: list[str] = []
        for r in rules[:8]:
            try:
                rid = str(r.get("id") or "")
                name = str(r.get("name") or "")
                if rid or name:
                    rule_texts.append(f"{rid}:{name}")
            except Exception:
                continue
        if rule_texts:
            lines.append("风险规则: " + "；".join(rule_texts))

    if isinstance(kg, dict):
        insight = str(kg.get("insight") or "").strip()
        gaps = kg.get("structural_gaps") or []
        strengths = kg.get("content_strengths") or []
        if insight:
            lines.append("知识图谱洞察: " + insight[:280])
        if isinstance(gaps, list) and gaps:
            lines.append("结构缺口: " + "；".join(str(x) for x in gaps[:5]))
        if isinstance(strengths, list) and strengths:
            lines.append("内容亮点: " + "；".join(str(x) for x in strengths[:5]))

    if isinstance(hyper, dict):
        h_sum = str(hyper.get("summary") or "").strip()
        if h_sum:
            lines.append("超图总结: " + h_sum[:280])
        top_signals = hyper.get("top_signals") or []
        if isinstance(top_signals, list) and top_signals:
            lines.append("关键信号: " + "；".join(str(x) for x in top_signals[:6]))

    return "\n".join(lines), latest


def _get_latest_user_message(
    project_id: str,
    conversation_id: str | None = None,
    student_id: str | None = None,
) -> str:
    """Fetch the latest user message content from ConversationStorage.

    If conversation_id is provided, messages are taken strictly from that
    conversation so that poster generation only反映当前这一条对话记录。
    """

    try:
        # If we know the exact conversation, only use its messages.
        if conversation_id:
            conv = conv_store.get(project_id, conversation_id)
            if not conv:
                return ""
            msgs = conv.get("messages") or []
            for m in reversed(msgs):
                if isinstance(m, dict) and m.get("role") == "user":
                    text = str(m.get("content") or "").strip()
                    if text:
                        return text
            return ""

        # Fallback to previous behaviour (best-effort) when no conversation
        # is provided — primarily for legacy callers.
        convs = conv_store.list_conversations(project_id)
        if not convs:
            return ""

        # Optionally narrow to the same student if that metadata is present.
        if student_id:
            sid_norm = student_id.strip()
            scoped_convs = [c for c in convs if str(c.get("student_id") or "").strip() == sid_norm]
            if scoped_convs:
                convs = scoped_convs

        latest_conv_id = str(convs[0].get("conversation_id"))
        conv = conv_store.get(project_id, latest_conv_id)
        if not conv:
            return ""
        msgs = conv.get("messages") or []
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("role") == "user":
                text = str(m.get("content") or "").strip()
                if text:
                    return text
    except Exception:
        return ""
    return ""


@app.post("/api/poster/generate", response_model=PosterGenerateResponse)
def generate_poster(payload: PosterGeneratePayload) -> PosterGenerateResponse:
    """Generate a structured poster design plan from project text + latest diagnosis.

    This endpoint is intentionally *single-shot* and does **not** run the
    multi-agent workflow. It reuses the latest project_state / conversation
    context and asks LLM to return a PosterDesign JSON object.
    """

    llm = LlmClient()
    if not llm.enabled:
        raise HTTPException(status_code=503, detail="LLM 未启用，无法生成海报设计方案")

    project_id = payload.project_id.strip()
    student_id = payload.student_id.strip()
    if not project_id or not student_id:
        raise HTTPException(status_code=400, detail="project_id 和 student_id 不能为空")

    conv_id = (getattr(payload, "conversation_id", "") or "").strip() or None

    # Try to read the current conversation's title / summary so that the
    # poster generation can stay strictly aligned with "this" dialogue,
    # instead of hallucinating一个完全不同的项目名称。
    conv_title = ""
    conv_summary = ""
    if conv_id:
        try:
            conv_meta = conv_store.get(project_id, conv_id) or {}
            conv_title = str(conv_meta.get("title") or "").strip()
            conv_summary = str(conv_meta.get("summary") or "").strip()
        except Exception:
            conv_title = ""
            conv_summary = ""

    project_state = json_store.load_project(project_id)

    # ── collect text sources ──
    base_text = (payload.source_text or "").strip()
    diag_summary, latest_sub = _summarize_latest_diagnosis_for_poster(
        project_state,
        student_id=student_id,
        conversation_id=conv_id,
    )
    latest_raw = str(latest_sub.get("raw_text") or "").strip() if latest_sub else ""

    if payload.use_latest_context and not base_text and latest_raw:
        base_text = latest_raw

    latest_user_msg = _get_latest_user_message(project_id, conversation_id=conv_id, student_id=student_id)

    if not base_text and not diag_summary and not latest_user_msg:
        raise HTTPException(status_code=400, detail="暂无可用项目上下文，请先在对话中描述一下你的项目或完成一次诊断")

    # ── build LLM prompts ──
    mode_label = {"coursework": "课程辅导", "competition": "竞赛冲刺", "learning": "项目教练"}.get(payload.mode, payload.mode)
    comp_label = {
        "": "不限",
        "internet_plus": "互联网+",
        "challenge_cup": "挑战杯",
        "dachuang": "大创",
    }.get(payload.competition_type or "", payload.competition_type or "")

    system_prompt = (
        "你是一名资深的创业路演海报设计师，擅长为学生项目做一页式中文项目海报设计。\n"
        "你的目标：让路人或评委在【3 秒内】看懂这个项目——第一眼被画面和痛点吸引，第二眼知道你做什么，第三眼看到关键数据和护城河。\n\n"
        "现在需要你根据项目文本和最近一次诊断结果，给出一份 *结构化* 的海报设计方案 PosterDesign，用于线下/线上路演宣传海报。\n\n"
        "必须严格输出一个 JSON 对象，字段如下（不要额外增加顶层字段）：\n"
        "{\n"
        '  "title": 项目名称或品牌名（不超过 16 字，用于海报顶部或左上角，品牌辨识度要强）,\n'
        '  "subtitle": Slogan / 一句话定位（不超过 40 字，用“为谁 + 做什么 + 带来什么价值”讲清楚）,\n'
        '  "sections": [\n'
        '    { "id": "hero" | "problem" | "solution" | "advantages" | "data" | "cta" | "team" | 自定义ID, "title": 分区标题, "bullets": [精炼要点...], "highlight": true/false },\n'
        '    ...\n'
        '  ],\n'
        '  "layout": {\n'
        '    "orientation": "portrait" | "landscape",  // 竖版或横版\n'
        '    "grid": 如 "3x4"、"2x4"，表示大致分区网格结构,\n'
        '    "accent_area": 建议突出区域，例如 "top_left"、"center"、"right_column" 等\n'
        '  },\n'
        '  "theme": 配色/风格标签，如 "tech_blue"、"youthful_gradient"、"minimal_black"、"warm_orange"、"deep_navy"、"green_growth",\n'
        '  "image_prompts": [\n'
        '    // 至少 3 条，用于一次性生成多张插图：\n'
        '    // image_prompts[0]: 第一眼抓人眼球的主视觉（项目场景或核心痛点/成果），\n'
        '    // image_prompts[1]: 使用场景或“传统方案 vs 我们方案”的对比画面，\n'
        '    // image_prompts[2]: 数据/奖项/里程碑相关的可视化画面。\n'
        '    // 每条需描述画面主体、场景、风格和光影，例如\n'
        '    // "futuristic isometric illustration of campus startup pitch, neon blue, high contrast"\n'
        '  ],\n'
        '  "export_hint": 推荐纸张/分辨率，例如 "A3 纵向，适合现场展板" 或 "1080x1920 竖屏海报"\n'
        "}\n\n"
        "要求（严格遵守）：\n"
        "1. 遵循“三秒原则”：\n"
        "   - 第 1 秒（第一眼）：hero 分区 + 主视觉插图，要用一句话或 1-2 个亮点钩住读者，文案可以偏情绪/冲击。\n"
        "   - 第 2 秒（第二眼）：title + subtitle 让人一眼知道你是“为谁解决什么问题”。\n"
        "   - 第 3 秒（第三眼）：通过 data / advantages 分区里的数字和优势，让人觉得项目靠谱、有护城河。\n"
        "2. 分区设计建议：\n"
        "   - hero：放在视觉最显眼区域，包含一句 Slogan 或亮点摘要（可与 subtitle 呼应），highlight=true。\n"
        "   - problem：目标用户 + 当前痛点/市场现状，2-3 条要点。\n"
        "   - solution：产品形态 / 核心功能 / 商业模式，用 2-4 条 bullet 讲清。\n"
        "   - advantages：用数据化语言描述核心优势和护城河（如 成本降低 40%、准确率提升 30%、专利/算法壁垒 等）。\n"
        "   - data：关键 KPI、里程碑或比赛获奖信息，建议每条中都出现醒目的数字（百分比、倍数、数量）。\n"
        "   - cta：路演/展位信息，如时间、地点、展位号、报名或联系方式。\n"
        "   - team：团队/导师亮点（可选），只保留最打动人的 2-3 点。\n"
        "   分区总数建议控制在 4-7 个，每个分区 bullets 不超过 4 条。\n"
        "3. 文案长度与可读性（避免“说明书式”堆字）：\n"
        "   - 整张海报的中文总字数控制在约 200 字以内，不写大段长段落。\n"
        "   - 小标题 3-6 字，bullet 每条不超过 30 字，尽量一句话说清。\n"
        "   - 多用动词+结果，少用抽象名词堆砌（如“显著提升用户体验”要具体成“决策时间缩短 50%+”）。\n"
        "4. 审美与风格：\n"
        "   - 科技/AI 类：推荐 theme=\"tech_blue\" 或 \"deep_navy\"，image_prompts 中多用深蓝、紫色、线性光效、科技感 UI 元素。\n"
        "   - 社会创新/文创类：推荐 theme=\"warm_orange\" 或 \"youthful_gradient\"，采用暖色调、插画或手绘风格。\n"
        "   - B 端/工业类：推荐 theme=\"minimal_black\" 或偏工程蓝的搭配，布局更克制、逻辑感强。\n"
        "   - 无法判断类型时，默认使用 \"tech_blue\"。\n"
        "5. 视觉避雷（需在文案结构上规避）：\n"
        "   - 不要引导生成超长段落：每个 bullet 不超过 1-2 行。\n"
        "   - 不要在 sections 里塞太多概念性词语，而是尽量加入可见的数字、场景和对比。\n"
        "   - 保留足够“留白”空间：可以通过减少 bullet 数量来实现，而不是塞满所有空间。\n"
        "6. image_prompts：\n"
        "   - 至少给出 3 条，用于一次性生成多张插图，分别服务于“第一眼主视觉”、“使用场景/对比”、“数据或奖项可视化”。\n"
        "   - 每条需要说明主体（谁/什么）、场景（在哪里）、风格（插画/写实/3D/等距）、色彩氛围（冷暖、明暗对比）。\n"
        "7. 如果诊断里有评分/风险/知识图谱/超图洞察，请把【优势】转成 hero/advantages/data 等分区的亮点，把【风险和缺口】转成温和的 TODO/改进建议（可放在单独分区），语气保持积极建设性。\n"
        "8. 标题命名规则：如果上下文中已经给出了清晰的项目名称或对话标题（例如“非遗木雕盲盒海外营销策略探讨”），请在 title 中优先沿用或轻度优化该名称，禁止凭空创造与上下文无关的新项目标题。\n"
        "9. 输出要求：禁止在 JSON 外输出任何说明文字、注释或 markdown，只能返回上述结构的 JSON。\n"
    )

    parts: list[str] = []
    if conv_title:
        parts.append("【当前对话的项目标题】\n" + conv_title[:120])
    if conv_summary:
        parts.append("【本对话的项目小结】\n" + conv_summary[:800])
    if base_text:
        parts.append("【项目原始描述或材料节选】\n" + base_text[:1500])
    if diag_summary:
        parts.append("【最近一次诊断 / 评分摘要】\n" + diag_summary)
    if latest_user_msg:
        parts.append("【学生在最近一轮对话中的自述/问题】\n" + latest_user_msg[:800])
    if latest_sub:
        stage = str(latest_sub.get("project_phase") or "")
        intent = str(latest_sub.get("intent") or "")
        if stage or intent:
            meta_line = "【项目阶段与意图】" + (f" 阶段={stage}" if stage else "") + (f"；意图={intent}" if intent else "")
            parts.append(meta_line)

    user_prompt = (
        f"教学模式: {mode_label}\n"  # e.g. 课程辅导/竞赛冲刺
        f"参赛类型: {comp_label}\n"
        f"project_id: {project_id} / student_id: {student_id}\n\n"
        + "\n\n".join(parts)
        + "\n\n请基于以上信息，生成一份适合中文路演现场的一页式海报设计 PosterDesign(JSON)。"
    )

    raw = llm.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=settings.llm_structured_model or settings.llm_reason_model or None,
        temperature=0.25,
    )

    # The model might either return the design directly or wrap it under a
    # top-level "poster" key; support both forms.
    from app.schemas import PosterDesign as _PosterDesign  # local import to avoid circular hints

    data = raw or {}
    if not isinstance(data, dict):
        data = {}
    poster_raw = data.get("poster") if isinstance(data.get("poster"), dict) else data

    try:
        poster = _PosterDesign.model_validate(poster_raw)
    except Exception:
        # Fallback: build a minimal PosterDesign from available text so the
        # frontend always has something usable.
        fallback_title = conv_title or "项目海报草稿"
        if not fallback_title and base_text:
            first_line = base_text.strip().splitlines()[0][:30]
            if first_line:
                fallback_title = first_line
        poster = _PosterDesign(
            title=fallback_title,
            subtitle=f"模式：{mode_label}；类型：{comp_label or '普通项目'}",
            sections=[
                {
                    "id": "hero",
                    "title": "项目亮点",
                    "bullets": [
                        "请在这里补充一句话项目 Slogan",
                        "写出 1-2 个最打动评委的亮点",
                    ],
                    "highlight": True,
                },
                {
                    "id": "problem",
                    "title": "痛点与机会",
                    "bullets": [
                        "用一两句话说明目标用户是谁、遇到什么问题",
                        "可以补充一条最关键的机会点或市场空白",
                    ],
                    "highlight": False,
                },
                {
                    "id": "cta",
                    "title": "路演信息",
                    "bullets": [
                        "时间：请写明路演或展示时间",
                        "地点：填写教室/会场/展位号等信息",
                        "欢迎评委和同学现场交流，可备注二维码/联系方式说明",
                    ],
                    "highlight": False,
                },
            ],
            layout={"orientation": "portrait", "grid": "3x4", "accent_area": "top_left"},
            theme="tech_blue",
            image_prompts=[],
            export_hint="A3 纵向，适合课堂或路演展板",
        )

    return PosterGenerateResponse(poster=poster)


@app.post("/api/poster/generate-image", response_model=PosterImageGenerateResponse)
def generate_poster_image(payload: PosterImageGeneratePayload) -> PosterImageGenerateResponse:
    """Generate an illustration image for the poster using a visual model.

    Frontend is expected to pass a prompt derived from PosterDesign.image_prompts
    or from the poster title/subtitle. The generated image is stored under
    upload_root/poster_images and served via the existing /uploads mount.
    """

    if not image_client.enabled:
        raise HTTPException(status_code=503, detail="图像生成未启用，请联系管理员在 .env 中配置 LLM_IMAGE_MODEL 和 LLM_API_KEY")

    project_id = payload.project_id.strip()
    student_id = payload.student_id.strip()
    if not project_id or not student_id:
        raise HTTPException(status_code=400, detail="project_id 和 student_id 不能为空")

    prompt = (payload.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")

    # Use orientation/size hints if provided, otherwise choose a sensible default.
    if payload.size:
        size = payload.size.strip() or "1024x576"
    else:
        if payload.orientation == "landscape":
            size = "1280x720"
        else:
            size = "1024x576"

    try:
        image_url = image_client.generate_poster_image(
            prompt=prompt,
            project_id=project_id,
            size=size,
            out_root=settings.upload_root / "poster_images",
        )
    except RuntimeError as exc:
        # Configuration issue, surface as 503 for frontend
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        logger.warning(
            "poster image generation failed (project_id=%s, student_id=%s)",
            project_id,
            student_id,
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail="生成海报插图失败，请稍后重试")

    return PosterImageGenerateResponse(image_url=image_url)


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
    data = ensure_project_cognition(json_store.load_project(project_id))
    latest_submission = data["submissions"][-1] if data["submissions"] else None
    video_analyses = list(data.get("video_analyses", []) or [])
    graph = graph_service.health()
    return ProjectSnapshotResponse(
        project_id=project_id,
        latest_student_submission=latest_submission,
        teacher_feedback=data["teacher_feedback"],
        video_analyses=video_analyses,
        graph_signals={"connected": graph.connected, "detail": graph.detail},
        track_vector=data.get("track_vector", {}),
        project_stage_v2=str(data.get("project_stage_v2") or ""),
        track_history=list(data.get("track_history", []) or []),
        track_inference_meta=data.get("track_inference_meta", {}) if isinstance(data.get("track_inference_meta"), dict) else {},
    )


@app.get("/api/project/{project_id}/cognition", response_model=ProjectCognitionResponse)
def project_cognition_get(project_id: str) -> ProjectCognitionResponse:
    data = ensure_project_cognition(json_store.load_project(project_id))
    return ProjectCognitionResponse(
        project_id=project_id,
        track_vector=data.get("track_vector", {}),
        project_stage_v2=str(data.get("project_stage_v2") or ""),
        track_history=list(data.get("track_history", []) or []),
        track_inference_meta=data.get("track_inference_meta", {}) if isinstance(data.get("track_inference_meta"), dict) else {},
        labels=describe_track_vector(data.get("track_vector")),
    )


@app.patch("/api/project/{project_id}/cognition", response_model=ProjectCognitionResponse)
def project_cognition_update(project_id: str, payload: ProjectCognitionUpdatePayload) -> ProjectCognitionResponse:
    data = ensure_project_cognition(json_store.load_project(project_id))
    source = str(payload.source or "student")
    if isinstance(payload.track_vector, dict):
        incoming = {
            "track_vector": payload.track_vector,
            "confidence": 1.0 if source == "student" else 0.8,
            "source_mix": {source: 1.0},
            "reason": payload.reason or "用户手动更新双光谱定位。",
            "evidence": ["manual_override"],
        }
        data, _ = merge_track_vector(data, incoming, source=source)
    if payload.project_stage_v2:
        data["project_stage_v2"] = payload.project_stage_v2
    json_store.save_project(project_id, data)
    return ProjectCognitionResponse(
        project_id=project_id,
        track_vector=data.get("track_vector", {}),
        project_stage_v2=str(data.get("project_stage_v2") or ""),
        track_history=list(data.get("track_history", []) or []),
        track_inference_meta=data.get("track_inference_meta", {}) if isinstance(data.get("track_inference_meta"), dict) else {},
        labels=describe_track_vector(data.get("track_vector")),
    )


@app.post("/api/project/{project_id}/cognition/infer", response_model=ProjectCognitionResponse)
def project_cognition_infer(project_id: str, payload: dict | None = None) -> ProjectCognitionResponse:
    payload = payload or {}
    data = ensure_project_cognition(json_store.load_project(project_id))
    diagnosis = data.get("submissions", [])[-1].get("diagnosis", {}) if data.get("submissions") else {}
    latest_text = str(payload.get("message") or "")
    if not latest_text and data.get("submissions"):
        latest_text = str(data["submissions"][-1].get("raw_text") or "")
    inferred = infer_track_vector(
        latest_text,
        diagnosis=diagnosis if isinstance(diagnosis, dict) else {},
        category=str(payload.get("category") or ""),
        competition_type=str(payload.get("competition_type") or ""),
        structured_signals=payload.get("structured_signals") if isinstance(payload.get("structured_signals"), dict) else {},
    )
    data, _ = merge_track_vector(data, inferred, source="inferred")
    if diagnosis:
        data["project_stage_v2"] = infer_project_stage_v2(diagnosis, data)
    json_store.save_project(project_id, data)
    return ProjectCognitionResponse(
        project_id=project_id,
        track_vector=data.get("track_vector", {}),
        project_stage_v2=str(data.get("project_stage_v2") or ""),
        track_history=list(data.get("track_history", []) or []),
        track_inference_meta=data.get("track_inference_meta", {}) if isinstance(data.get("track_inference_meta"), dict) else {},
        labels=describe_track_vector(data.get("track_vector")),
    )


@app.get("/api/project/{project_id}/submissions")
def get_project_submissions(project_id: str) -> dict:
    data = json_store.load_project(project_id)
    submissions = list(data.get("submissions", []) or [])
    grouped: dict[str, list[dict]] = {}
    for row in submissions:
        logical_id = _safe_str(row.get("logical_project_id") or row.get("project_id") or row.get("conversation_id") or project_id)
        grouped.setdefault(logical_id, []).append(row)
    project_meta: dict[str, dict] = {}
    submission_order: dict[str, int] = {}
    for project_order, (logical_id, rows) in enumerate(
        sorted(
            grouped.items(),
            key=lambda item: max(_safe_str(x.get("created_at", "")) for x in item[1]) if item[1] else "",
            reverse=True,
        ),
        start=1,
    ):
        rows.sort(key=lambda item: _safe_str(item.get("created_at", "")))
        project_meta[logical_id] = {
            "project_order": project_order,
            "project_display_name": _project_label(logical_id, rows),
        }
        for idx, row in enumerate(rows, start=1):
            sid = _safe_str(row.get("submission_id", ""))
            if sid:
                submission_order[sid] = idx
    normalized = []
    for s in reversed(submissions):
        diag = s.get("diagnosis", {}) if isinstance(s.get("diagnosis"), dict) else {}
        logical_project_id = _safe_str(s.get("logical_project_id") or s.get("project_id") or s.get("conversation_id") or project_id)
        meta = project_meta.get(logical_project_id, {})
        summary = (
            _safe_str((s.get("kg_analysis") or {}).get("insight", ""))
            or _safe_str((s.get("hypergraph_insight") or {}).get("summary", ""))
            or _safe_str(diag.get("bottleneck", ""))
            or _safe_str(((s.get("next_task") or {}) if isinstance(s.get("next_task"), dict) else {}).get("description", ""))
        )
        normalized.append({
            "submission_id": s.get("submission_id", ""),
            "created_at": s.get("created_at", ""),
            "logical_project_id": logical_project_id,
            "project_order": meta.get("project_order", 0),
            "project_display_name": meta.get("project_display_name", logical_project_id),
            "submission_order": submission_order.get(_safe_str(s.get("submission_id", "")), 0),
            "project_phase": s.get("project_phase", ""),
            "intent": _normalize_intent(
                s.get("intent")
                or ((s.get("agent_outputs", {}) if isinstance(s.get("agent_outputs"), dict) else {}).get("orchestration", {}) or {}).get("intent", ""),
                _safe_str(s.get("raw_text", "")),
            ),
            "intent_shape": _submission_intent_shape(s),
            "source_type": s.get("source_type", ""),
            "filename": s.get("filename"),
            "text_preview": (s.get("raw_text") or "")[:120],
            "full_text": (s.get("raw_text") or "")[:8000],
            "overall_score": diag.get("overall_score", s.get("overall_score", 0)),
            "bottleneck": _safe_str(diag.get("bottleneck", "")),
            "ai_summary": summary,
            "next_task": _safe_str(((s.get("next_task") or {}) if isinstance(s.get("next_task"), dict) else {}).get("title", "")),
            "triggered_rules": _normalize_rules(diag.get("triggered_rules", s.get("triggered_rules", []))),
            "agent_trace_meta": _safe_agent_summary(s).get("_meta", {}),
            "matched_teacher_interventions": [
                {
                    "title": _safe_str(item.get("title", "")),
                    "reason_summary": _safe_str(item.get("reason_summary", "")),
                }
                for item in (s.get("matched_teacher_interventions", []) or [])[:3]
                if isinstance(item, dict)
            ],
        })
    return {"project_id": project_id, "submissions": normalized}


@app.get("/api/teacher/project/{project_id}/workbench-summary")
def get_project_workbench_summary(project_id: str) -> dict:
    project_state = json_store.load_project(project_id)
    submissions = list(project_state.get("submissions", []) or [])
    grouped: dict[str, list[dict]] = {}
    for row in submissions:
        logical_id = _safe_str(row.get("logical_project_id") or row.get("project_id") or row.get("conversation_id") or project_id)
        grouped.setdefault(logical_id, []).append(row)

    logical_projects: list[dict] = []
    root_scores: list[float] = []
    for project_order, (logical_id, rows) in enumerate(
        sorted(
            grouped.items(),
            key=lambda item: max(_safe_str(x.get("created_at", "")) for x in item[1]) if item[1] else "",
            reverse=True,
        ),
        start=1,
    ):
        rows.sort(key=lambda item: _safe_str(item.get("created_at", "")))
        latest = rows[-1] if rows else {}
        latest_diag = _safe_diagnosis(latest.get("diagnosis", {}))
        latest_task = latest.get("next_task", {}) if isinstance(latest.get("next_task"), dict) else {}
        scores = [
            _safe_float(
                (row.get("diagnosis", {}) if isinstance(row.get("diagnosis"), dict) else {}).get("overall_score", row.get("overall_score", 0))
            )
            for row in rows
        ]
        positive_scores = [score for score in scores if score > 0]
        root_scores.extend(positive_scores)
        intent_mix: dict[str, int] = {}
        source_mix: dict[str, int] = {}
        rule_hits: dict[str, int] = {}
        material_count = 0
        for row in rows:
            intent = _normalize_intent(
                row.get("intent")
                or ((row.get("agent_outputs", {}) if isinstance(row.get("agent_outputs"), dict) else {}).get("orchestration", {}) or {}).get("intent", ""),
                _safe_str(row.get("raw_text", "")),
            )
            intent_mix[intent] = intent_mix.get(intent, 0) + 1
            source_type = _safe_str(row.get("source_type", "")) or "text"
            source_mix[source_type] = source_mix.get(source_type, 0) + 1
            if source_type in {"file", "file_in_chat"}:
                material_count += 1
            for rid in _normalize_rules((row.get("diagnosis", {}) if isinstance(row.get("diagnosis"), dict) else {}).get("triggered_rules", []) or row.get("triggered_rules", [])):
                rule_hits[rid] = rule_hits.get(rid, 0) + 1
        dominant_intent = max(intent_mix.items(), key=lambda kv: kv[1])[0] if intent_mix else "综合咨询"
        top_risks = [rid for rid, _ in sorted(rule_hits.items(), key=lambda kv: kv[1], reverse=True)[:3]]
        logical_projects.append({
            "logical_project_id": logical_id,
            "project_order": project_order,
            "project_name": _project_label(logical_id, rows),
            "project_phase": _safe_str(latest.get("project_phase", "")) or "持续迭代",
            "submission_count": len(rows),
            "material_count": material_count,
            "avg_score": round(sum(positive_scores) / len(positive_scores), 1) if positive_scores else 0,
            "latest_score": positive_scores[-1] if positive_scores else 0,
            "improvement": round(positive_scores[-1] - positive_scores[0], 1) if len(positive_scores) >= 2 else 0,
            "latest_created_at": latest.get("created_at", ""),
            "dominant_intent": dominant_intent,
            "intent_distribution": intent_mix,
            "top_risks": top_risks,
            "summary": _safe_str((latest.get("kg_analysis") or {}).get("insight", "")) or latest_diag.get("bottleneck") or _safe_str(latest_task.get("description", "")) or "该项目仍在持续迭代。",
            "source_mix": source_mix,
        })

    return {
        "project_id": project_id,
        "logical_project_count": len(logical_projects),
        "avg_score": round(sum(root_scores) / len(root_scores), 1) if root_scores else 0,
        "material_count": sum(item.get("material_count", 0) for item in logical_projects),
        "submission_count": sum(item.get("submission_count", 0) for item in logical_projects),
        "logical_projects": logical_projects,
    }


@app.get("/api/project/{project_id}/feedback")
def get_project_feedback(project_id: str) -> dict:
    data = json_store.load_project(project_id)
    return {
        "project_id": project_id,
        "feedback": data.get("teacher_feedback", []),
    }


@app.get("/api/teacher/assistant/dashboard")
def teacher_assistant_dashboard(teacher_id: str = "") -> dict:
    if not teacher_id:
        return {"teacher_id": "", "team_count": 0, "pending_assessments": [], "pending_interventions": [], "followups": [], "shared_focus": []}
    return _build_teacher_assistant_dashboard(teacher_id)


@app.get("/api/teacher/assistant/project/{project_id}/assessment")
def teacher_assistant_project_assessment(project_id: str, logical_project_id: str = "") -> dict:
    return _build_assessment_payload(project_id, logical_project_id)


@app.post("/api/teacher/assistant/project/{project_id}/assessment/review")
def teacher_assistant_save_review(project_id: str, payload: TeacherAssistantAssessmentReviewPayload) -> dict:
    saved = json_store.upsert_teacher_assistant_review(
        project_id,
        {
            "teacher_id": payload.teacher_id,
            "logical_project_id": payload.logical_project_id or "",
            "title": payload.title,
            "summary": payload.summary,
            "strengths": payload.strengths,
            "weaknesses": payload.weaknesses,
            "action_items": payload.action_items,
            "focus_tags": payload.focus_tags,
            "score_band": payload.score_band,
            "status": "sent" if payload.send_to_student else "approved",
        },
    )
    feedback_id = ""
    if payload.send_to_student:
        feedback_id = json_store.append_teacher_feedback(
            project_id,
            {
                "teacher_id": payload.teacher_id,
                "comment": payload.summary,
                "focus_tags": payload.focus_tags,
                "source": "teacher_assistant_assessment",
                "logical_project_id": payload.logical_project_id or "",
                "action_items": payload.action_items,
                "score_band": payload.score_band,
            },
        )
    return {
        "status": "ok",
        "project_id": project_id,
        "review": saved,
        "feedback_id": feedback_id,
    }


@app.get("/api/teacher/assistant/class/{team_or_class_id}/interventions")
def teacher_assistant_team_interventions(team_or_class_id: str, teacher_id: str = "") -> dict:
    return _build_team_intervention_payload(team_or_class_id, teacher_id)


@app.get("/api/teacher/assistant/class/{team_or_class_id}/insights")
def teacher_assistant_team_insights(team_or_class_id: str) -> dict:
    return _build_team_insight_payload(team_or_class_id)


@app.post("/api/teacher/assistant/interventions")
def teacher_assistant_create_intervention(payload: TeacherAssistantInterventionPayload) -> dict:
    targets = _target_projects_for_intervention(payload)
    if not targets:
        raise HTTPException(status_code=404, detail="未找到可下发的目标学生或项目")
    shared_id = ""
    saved_targets = []
    for target in targets:
        saved = json_store.upsert_teacher_intervention(
            target["project_id"],
            {
                "teacher_id": payload.teacher_id,
                "scope_type": payload.scope_type,
                "scope_id": payload.scope_id,
                "source_type": payload.source_type,
                "target_student_id": target.get("student_id") or payload.target_student_id or "",
                "project_id": payload.project_id or target["project_id"],
                "logical_project_id": payload.logical_project_id or "",
                "title": payload.title,
                "reason_summary": payload.reason_summary,
                "action_items": payload.action_items,
                "acceptance_criteria": payload.acceptance_criteria,
                "priority": payload.priority,
                "status": payload.status,
            },
            intervention_id=shared_id or None,
        )
        shared_id = saved["intervention_id"]
        saved_targets.append({
            "project_id": target["project_id"],
            "student_id": target.get("student_id", ""),
        })
    return {
        "status": "ok",
        "intervention_id": shared_id,
        "targets": saved_targets,
    }


@app.post("/api/teacher/assistant/smart-select")
def teacher_assistant_smart_select(filter: TeacherAssistantSmartSelectFilter) -> dict:
    """根据筛选条件，帮助教师批量选择适合干预的项目列表。

    该接口不会直接创建干预任务，只返回候选项目/学生，
    前端可据此填充 TeacherAssistantInterventionPayload 并复用原有创建逻辑。
    """
    projects = json_store.list_projects()
    rows: list[dict[str, Any]] = []
    class_id = _safe_str(filter.class_id or "") or None
    cohort_id = _safe_str(filter.cohort_id or "") or None

    for project in projects:
        pid = _safe_str(project.get("project_id", ""))
        submissions = list(project.get("submissions", []) or [])
        if not submissions:
            continue
        latest = submissions[-1]
        if class_id and latest.get("class_id") != class_id:
            continue
        if cohort_id and latest.get("cohort_id") != cohort_id:
            continue
        diagnosis = _safe_diagnosis(latest.get("diagnosis", {}))
        overall_score = _safe_float(diagnosis.get("overall_score", latest.get("overall_score", 0)))
        triggered_raw = diagnosis.get("triggered_rules", []) or latest.get("triggered_rules", []) or []
        rule_ids = _normalize_rules(triggered_raw)
        high_risk_rules = [
            _safe_str(r.get("id"))
            for r in triggered_raw
            if isinstance(r, dict) and _safe_str(r.get("severity", "")) == "high"
        ]
        risk_count = len(rule_ids)
        phase = _safe_str(diagnosis.get("project_stage", latest.get("project_phase", ""))) or "持续迭代"

        # 基础数值过滤
        if filter.min_overall_score is not None and overall_score < filter.min_overall_score:
            continue
        if filter.max_overall_score is not None and overall_score > filter.max_overall_score:
            continue
        if filter.min_risk_count is not None and risk_count < filter.min_risk_count:
            continue
        if filter.max_risk_count is not None and risk_count > filter.max_risk_count:
            continue

        # 规则包含/排除
        norm_required = {(_safe_str(rid).upper()) for rid in (filter.require_high_risk_rules or []) if _safe_str(rid)}
        norm_exclude = {(_safe_str(rid).upper()) for rid in (filter.exclude_rules or []) if _safe_str(rid)}
        pid_rules = {(_safe_str(r).upper()) for r in rule_ids if _safe_str(r)}
        if norm_required and not norm_required.issubset(pid_rules.union({(_safe_str(r).upper()) for r in high_risk_rules if _safe_str(r)})):
            continue
        if norm_exclude and pid_rules.intersection(norm_exclude):
            continue

        # 项目阶段过滤
        phase_in = [p for p in (filter.project_phase_in or []) if _safe_str(p)]
        if phase_in and phase not in phase_in:
            continue

        rows.append(
            {
                "project_id": pid,
                "student_id": _safe_str(latest.get("student_id", "")),
                "class_id": latest.get("class_id"),
                "cohort_id": latest.get("cohort_id"),
                "overall_score": overall_score,
                "risk_count": risk_count,
                "high_risk_rules": high_risk_rules,
                "project_stage": phase,
                "latest_bottleneck": _safe_str(diagnosis.get("bottleneck", "")),
            }
        )

    # 进度排序：默认按整体得分升序 + 风险数降序，让“落后&高风险”靠前
    rows.sort(key=lambda r: (_safe_float(r.get("overall_score", 0)), -int(r.get("risk_count", 0) or 0)))

    # 进度名次区间过滤（基于排序后的 index）
    total = len(rows)
    if total and (filter.min_progress_rank is not None or filter.max_progress_rank is not None):
        start = max(0, int((filter.min_progress_rank or 1) - 1))
        end = int((filter.max_progress_rank or total))
        rows = rows[start:end]

    limit = max(1, min(int(filter.limit or 30), 200))
    selected = rows[:limit]
    return {
        "total_candidates": total,
        "selected_count": len(selected),
        "items": selected,
    }


@app.post("/api/teacher/assistant/interventions/{intervention_id}/send")
def teacher_assistant_send_intervention(intervention_id: str, payload: TeacherAssistantInterventionSendPayload) -> dict:
    sent_count = 0
    for project in json_store.list_projects():
        pid = project.get("project_id", "")
        saved = json_store.update_teacher_intervention(
            pid,
            intervention_id,
            {
                "status": "sent",
                "sent_at": datetime.now().isoformat(),
                "teacher_id": payload.teacher_id,
            },
        )
        if saved:
            sent_count += 1
    if sent_count == 0:
        raise HTTPException(status_code=404, detail="未找到对应的干预任务")
    return {"status": "ok", "intervention_id": intervention_id, "sent_count": sent_count}


@app.get("/api/student/interventions")
def student_interventions(project_id: str) -> dict:
    data = json_store.load_project(project_id)
    interventions = list(data.get("teacher_interventions", []) or [])
    interventions.sort(key=lambda row: row.get("updated_at", row.get("created_at", "")), reverse=True)
    visible = [row for row in interventions if row.get("status") in {"sent", "viewed", "completed", "approved"}]
    return {
        "project_id": project_id,
        "interventions": visible,
    }


@app.post("/api/student/interventions/{intervention_id}/view")
def student_view_intervention(intervention_id: str, payload: StudentInterventionViewPayload) -> dict:
    saved = json_store.update_teacher_intervention(
        payload.project_id,
        intervention_id,
        {
            "status": "viewed",
            "viewed_at": datetime.now().isoformat(),
            "student_id": payload.student_id or "",
        },
    )
    if not saved:
        raise HTTPException(status_code=404, detail="未找到该教师干预任务")
    return {"status": "ok", "intervention": saved}


@app.get("/api/teacher/assistant/project/{project_id}/conversation-eval")
def teacher_assistant_project_conversation_eval(project_id: str, logical_project_id: str = "") -> dict:
    return _build_conversation_eval_payload(project_id, logical_project_id)


@app.get("/api/teacher/conversation-analytics")
def teacher_conversation_analytics(class_id: str | None = None, cohort_id: str | None = None) -> dict[str, Any]:
    """Aggregate dialogue-based conversation quality metrics at class/cohort level.

    This endpoint only looks at submissions whose source_type starts with
    "dialogue_turn" and aggregates per-student conversation behaviour such as
    turn count, question density and evidence-awareness trend.
    """
    return _build_conversation_analytics(class_id=class_id, cohort_id=cohort_id)


@app.get("/api/teacher/case-benchmark")
def teacher_case_benchmark(class_id: str | None = None, cohort_id: str | None = None) -> dict[str, Any]:
    """Class-level overview: benchmark student projects against retrieved cases.

    Aggregates per (project, logical_project_id) using dialogue history rag_cases
    and latest diagnosis rubric / triggered_rules.
    """
    return _build_case_benchmark_overview(class_id=class_id, cohort_id=cohort_id)


@app.get("/api/teacher/project/{project_id}/case-benchmark")
def teacher_project_case_benchmark(project_id: str, logical_project_id: str = "") -> dict[str, Any]:
    """Per-project case benchmarking payload for teacher project workbench.

    Compares a student project with its most frequently retrieved cases across
    dialogue history, exposing rubric and risk contrasts for visualization.
    """
    return _build_case_benchmark_for_project(project_id, logical_project_id)


@app.get("/api/teacher/submissions")
def teacher_list_submissions(class_id: str | None = None, cohort_id: str | None = None, limit: int = 50) -> dict:
    projects = json_store.list_projects()
    rows: list[dict[str, Any]] = []
    _user_name_cache: dict[str, str] = {}
    def _resolve_student(sid: str, pid: str) -> tuple[str, str]:
        real_sid = sid if sid and sid.lower() != "none" else (
            pid.replace("project-", "", 1) if pid.startswith("project-") else ""
        )
        if real_sid and real_sid not in _user_name_cache:
            u = user_store.get_by_id(real_sid)
            _user_name_cache[real_sid] = (u or {}).get("display_name", "") if u else ""
        return real_sid, _user_name_cache.get(real_sid, "")
    for project in projects:
        pid = project.get("project_id", "")
        for sub in project.get("submissions", []):
            if class_id and sub.get("class_id") != class_id:
                continue
            if cohort_id and sub.get("cohort_id") != cohort_id:
                continue
            diagnosis = sub.get("diagnosis", {}) if isinstance(sub.get("diagnosis"), dict) else {}
            _sid, _sname = _resolve_student(sub.get("student_id", ""), pid)
            rows.append({
                "project_id": pid,
                "logical_project_id": _safe_str(sub.get("logical_project_id") or sub.get("project_id") or sub.get("conversation_id", "")),
                "student_id": _sid,
                "student_name": _sname,
                "class_id": sub.get("class_id"),
                "created_at": sub.get("created_at", ""),
                "source_type": sub.get("source_type", ""),
                "filename": sub.get("filename"),
                "project_phase": _safe_str(sub.get("project_phase", "")),
                "overall_score": diagnosis.get("overall_score", 0),
                "triggered_rules": [r.get("id") for r in diagnosis.get("triggered_rules", []) if isinstance(r, dict)],
                "next_task": (sub.get("next_task") or {}).get("title", ""),
                "text_preview": (sub.get("raw_text") or "")[:120],
                "full_text": (sub.get("raw_text") or "")[:4000],
                "kg_analysis": sub.get("kg_analysis"),
                "bottleneck": diagnosis.get("bottleneck", ""),
                "intent": sub.get("intent", ""),
                "mode": sub.get("mode", ""),
                "reply_strategy": (sub.get("agent_outputs") or {}).get("reply_strategy", "") if isinstance(sub.get("agent_outputs"), dict) else "",
                "agents_called": (sub.get("agent_outputs") or {}).get("agents_called", []) if isinstance(sub.get("agent_outputs"), dict) else [],
                "matched_teacher_interventions": [
                    {
                        "title": _safe_str(item.get("title", "")),
                        "reason_summary": _safe_str(item.get("reason_summary", "")),
                    }
                    for item in (sub.get("matched_teacher_interventions", []) or [])[:2]
                    if isinstance(item, dict)
                ],
                "agent_trace_meta": _safe_agent_summary(sub).get("_meta", {}),
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
        model=settings.llm_fast_model,
        temperature=0.3,
    )
    return {"report": report.strip() if report else "报告生成失败", "snapshot": snapshot}


@app.post("/api/teacher/project-insight-report")
def teacher_project_insight_report(payload: dict) -> dict:
    rows = list(payload.get("rows") or [])
    category = _safe_str(payload.get("category", "")) or "全部项目"
    if not rows:
        return {
            "headline": "暂无可分析项目",
            "overview": "当前分类下还没有可用于生成结构化报告的项目。",
            "executive_brief": "",
            "category_diagnosis": [],
            "strengths": [],
            "issues": [],
            "priority_projects": [],
            "comparison_axes": [],
            "sample_comparison": [],
            "sample_cards": [],
            "risk_watchlist": [],
            "intent_profile": [],
            "cohort_snapshot": {},
            "teaching_sequence": [],
            "teaching_modules": [],
            "evidence_citations": [],
            "teaching_focus": "",
            "teaching_action": "",
        }

    sorted_by_score = sorted(rows, key=lambda item: float(item.get("latest_score", 0) or 0), reverse=True)
    sorted_by_risk = sorted(rows, key=lambda item: len(item.get("top_risks") or []), reverse=True)
    sorted_by_improvement = sorted(rows, key=lambda item: float(item.get("improvement", 0) or 0), reverse=True)
    risk_counter: dict[str, int] = {}
    intent_counter: dict[str, int] = {}
    for row in rows:
        for risk in (row.get("top_risks") or [])[:4]:
            risk_key = _safe_str(risk)
            if risk_key:
                risk_counter[risk_key] = risk_counter.get(risk_key, 0) + 1
        intent = _safe_str(row.get("dominant_intent", "综合咨询")) or "综合咨询"
        intent_counter[intent] = intent_counter.get(intent, 0) + 1

    avg_score = round(sum(float(row.get("latest_score", 0) or 0) for row in rows) / max(1, len(rows)), 1)
    avg_improvement = round(sum(float(row.get("improvement", 0) or 0) for row in rows) / max(1, len(rows)), 1)
    avg_risk_count = round(sum(len(row.get("top_risks") or []) for row in rows) / max(1, len(rows)), 1)
    avg_submission_count = round(sum(float(row.get("submission_count", 0) or 0) for row in rows) / max(1, len(rows)), 1)
    high_score_count = sum(1 for row in rows if float(row.get("latest_score", 0) or 0) >= 8)
    low_score_count = sum(1 for row in rows if float(row.get("latest_score", 0) or 0) < 6)
    top_risks = sorted(risk_counter.items(), key=lambda item: item[1], reverse=True)[:3]
    intent_profile = [
        {"intent": intent, "count": count}
        for intent, count in sorted(intent_counter.items(), key=lambda item: item[1], reverse=True)[:4]
    ]
    dominant_intent = sorted(intent_counter.items(), key=lambda item: item[1], reverse=True)[0][0] if intent_counter else "综合咨询"
    sample_cards: list[dict[str, Any]] = []

    def _append_sample_card(label: str, row: dict[str, Any] | None, metric: str, takeaway: str) -> None:
        if not row:
            return
        project_name = _safe_str(row.get("project_name", "未命名项目"))
        if any(card.get("project_name") == project_name and card.get("label") == label for card in sample_cards):
            return
        sample_cards.append({
            "label": label,
            "project_name": project_name,
            "metric": metric,
            "takeaway": takeaway,
        })

    _append_sample_card(
        "高分样本",
        sorted_by_score[0] if sorted_by_score else None,
        f"{float(sorted_by_score[0].get('latest_score', 0) or 0):.1f} 分" if sorted_by_score else "",
        "适合作为正向样本，优先拆解其结构完整度与表达方式。",
    )
    _append_sample_card(
        "进步最快",
        sorted_by_improvement[0] if sorted_by_improvement else None,
        f"{float(sorted_by_improvement[0].get('improvement', 0) or 0):+.1f} 分" if sorted_by_improvement else "",
        "适合拿来复盘其迭代路径，提炼成可迁移的方法。",
    )
    _append_sample_card(
        "高风险样本",
        sorted_by_risk[0] if sorted_by_risk else None,
        f"{len((sorted_by_risk[0].get('top_risks') or []))} 个风险" if sorted_by_risk else "",
        "建议优先精读，确认是结构性短板还是单次提交失误。",
    )
    cohort_snapshot = {
        "avg_score": avg_score,
        "avg_improvement": avg_improvement,
        "avg_risk_count": avg_risk_count,
        "avg_submission_count": avg_submission_count,
        "high_score_share": round(high_score_count / max(1, len(rows)) * 100),
        "low_score_share": round(low_score_count / max(1, len(rows)) * 100),
        "dominant_intent": dominant_intent,
    }
    risk_watchlist = [
        {
            "risk": risk,
            "count": count,
            "advice": f"当前分类中出现 {count} 次，建议把它放进下一次统一讲评的固定检查项。",
        }
        for risk, count in top_risks
    ]
    teaching_sequence = [
        {
            "step": "先定标",
            "action": f"先展示 {sample_cards[0]['project_name']} 的可取结构或表达亮点。" if sample_cards else "先展示一个高分样本。",
            "goal": "让学生先看到这类项目的完成标准。",
        },
        {
            "step": "再对照",
            "action": (
                f"对照说明 {top_risks[0][0]} 等高频问题如何拖低项目质量。"
                if top_risks else
                "对照一个高风险样本，说明为什么会失分。"
            ),
            "goal": "把共性问题讲透，而不是逐个零散点评。",
        },
        {
            "step": "后布置",
            "action": "统一布置下一轮修改要求，并明确必须补充的证据或结构。",
            "goal": "让同类项目在下一轮提交中出现可观察的整体改善。",
        },
    ]
    snapshot = {
        "category": category,
        "project_count": len(rows),
        "avg_score": avg_score,
        "avg_improvement": avg_improvement,
        "avg_risk_count": avg_risk_count,
        "avg_submission_count": avg_submission_count,
        "dominant_intent": dominant_intent,
        "intent_profile": intent_profile,
        "top_sample": sorted_by_score[:5],
        "improving_sample": sorted_by_improvement[:5],
        "priority_sample": sorted_by_risk[:5],
        "top_risks": [{"risk": risk, "count": count} for risk, count in top_risks],
        "rows": rows[:24],
    }

    fallback = {
        "headline": f"{category}共有 {len(rows)} 个项目，平均最新分 {avg_score}。",
        "overview": (
            f"当前这一组项目更集中暴露在“{dominant_intent}”相关问题上。"
            + (f" 高频风险包括 {', '.join(risk for risk, _ in top_risks)}。" if top_risks else " 当前风险分布还不算集中，适合抽样精读。")
        ),
        "executive_brief": f"这一类项目当前最值得老师关注的是共性问题是否已经开始重复出现，以及高分样本的方法是否可以迁移到低分项目上。",
        "category_diagnosis": [
            {
                "theme": "整体完成度",
                "detail": f"当前分类共有 {len(rows)} 个项目，平均最新分 {avg_score}，说明整体仍处在需要教师筛选重点样本的阶段。"
            },
            {
                "theme": "主导工作重心",
                "detail": f"项目主要集中在“{dominant_intent}”相关任务，老师可以按这一维度组织讲评。"
            },
        ],
        "strengths": [
            f"高分样本 {sorted_by_score[0].get('project_name', '未命名项目')} 可以作为同类参考。"
        ] if sorted_by_score else [],
        "issues": [
            {
                "title": risk,
                "detail": f"该问题在当前分类中出现 {count} 次，建议老师统一提醒。"
            }
            for risk, count in top_risks
        ],
        "priority_projects": [
            {
                "project_name": _safe_str(item.get("project_name", "未命名项目")),
                "reason": f"当前分 {float(item.get('latest_score', 0) or 0):.1f}，且风险项较多，建议优先精读。"
            }
            for item in sorted_by_risk[:2]
        ],
        "comparison_axes": [
            {"dimension": "论证完整度", "insight": "横向对比时优先看问题定义、证据和方案闭环是否连上。"},
            {"dimension": "迭代质量", "insight": "结合提交次数与分数变化，判断是稳步改进还是反复返工。"},
        ],
        "sample_comparison": [
            {
                "role": "高分样本",
                "project_name": _safe_str(sorted_by_score[0].get("project_name", "未命名项目")) if sorted_by_score else "",
                "takeaway": "适合作为这一类项目的参考样本，重点看其论证闭环与表达方式。"
            },
            {
                "role": "高风险样本",
                "project_name": _safe_str(sorted_by_risk[0].get("project_name", "未命名项目")) if sorted_by_risk else "",
                "takeaway": "适合作为反例样本，帮助老师判断共性问题到底出在哪里。"
            },
        ],
        "sample_cards": sample_cards,
        "risk_watchlist": risk_watchlist,
        "intent_profile": intent_profile,
        "cohort_snapshot": cohort_snapshot,
        "teaching_sequence": teaching_sequence,
        "teaching_modules": [
            "先展示一个高分样本的结构优势。",
            "再对照一个高风险样本，指出最关键的断点。",
            "最后统一布置下一轮修改要求与证据补充任务。",
        ],
        "evidence_citations": [
            {
                "claim": f"当前分类里需要优先处理 {_safe_str(sorted_by_risk[0].get('project_name', '未命名项目'))}。",
                "project_name": _safe_str(sorted_by_risk[0].get("project_name", "未命名项目")) if sorted_by_risk else "",
                "evidence": _safe_str(sorted_by_risk[0].get("summary", "")) if sorted_by_risk else "",
            },
            {
                "claim": f"{_safe_str(sorted_by_score[0].get('project_name', '未命名项目'))} 可以作为正向样本参考。",
                "project_name": _safe_str(sorted_by_score[0].get("project_name", "未命名项目")) if sorted_by_score else "",
                "evidence": _safe_str(sorted_by_score[0].get("summary", "")) if sorted_by_score else "",
            },
        ] if sorted_by_score and sorted_by_risk else [],
        "teaching_focus": top_risks[0][0] if top_risks else dominant_intent,
        "teaching_action": "先抽一份高分样本和一份高风险样本做对照讲评，再给这一类项目统一布置下一轮修订要求。",
    }

    if not composer_llm.enabled:
        return {**fallback, "snapshot": snapshot}

    result = composer_llm.chat_json(
        system_prompt=(
            "你是教师端的项目洞察智能体，需要把一批同类项目压缩成老师可直接使用的结构化报告。\n"
            "请只输出 JSON，字段必须包含：\n"
            'headline: string, overview: string,\n'
            'executive_brief: string,\n'
            'category_diagnosis: [{"theme": string, "detail": string}],\n'
            'strengths: string[],\n'
            'issues: [{"title": string, "detail": string}],\n'
            'priority_projects: [{"project_name": string, "reason": string}],\n'
            'comparison_axes: [{"dimension": string, "insight": string}],\n'
            'sample_comparison: [{"role": string, "project_name": string, "takeaway": string}],\n'
            'sample_cards: [{"label": string, "project_name": string, "metric": string, "takeaway": string}],\n'
            'risk_watchlist: [{"risk": string, "count": number, "advice": string}],\n'
            'intent_profile: [{"intent": string, "count": number}],\n'
            'cohort_snapshot: {"avg_score": number, "avg_improvement": number, "avg_risk_count": number, "avg_submission_count": number, "high_score_share": number, "low_score_share": number, "dominant_intent": string},\n'
            'teaching_sequence: [{"step": string, "action": string, "goal": string}],\n'
            'teaching_modules: string[],\n'
            'evidence_citations: [{"claim": string, "project_name": string, "evidence": string}],\n'
            'teaching_focus: string, teaching_action: string。\n'
            "要求：\n"
            "1. 聚焦老师接下来该先看什么、为什么。\n"
            "2. 不要泛泛而谈，尽量结合风险、分数、迭代、项目名称给出判断。\n"
            "3. 必须体现至少一个高分样本和一个高风险样本之间的对照分析。\n"
            "4. 每个数组控制在 2-4 条。\n"
            "5. 结论要适合前端做卡片和图表展示，不要只写成长段文字。\n"
            "6. 中文输出，简洁但信息密度高，像老师真正会看的教学分析报告。"
        ),
        user_prompt=f"当前分类项目数据：\n{json.dumps(snapshot, ensure_ascii=False)}",
        temperature=0.25,
        model=settings.llm_structured_model,
    ) or {}
    if not isinstance(result, dict):
        return {**fallback, "snapshot": snapshot}
    return {
        "headline": _safe_str(result.get("headline", fallback["headline"])),
        "overview": _safe_str(result.get("overview", fallback["overview"])),
        "executive_brief": _safe_str(result.get("executive_brief", fallback["executive_brief"])),
        "category_diagnosis": result.get("category_diagnosis") or fallback["category_diagnosis"],
        "strengths": result.get("strengths") or fallback["strengths"],
        "issues": result.get("issues") or fallback["issues"],
        "priority_projects": result.get("priority_projects") or fallback["priority_projects"],
        "comparison_axes": result.get("comparison_axes") or fallback["comparison_axes"],
        "sample_comparison": result.get("sample_comparison") or fallback["sample_comparison"],
        "sample_cards": result.get("sample_cards") or fallback["sample_cards"],
        "risk_watchlist": result.get("risk_watchlist") or fallback["risk_watchlist"],
        "intent_profile": result.get("intent_profile") or fallback["intent_profile"],
        "cohort_snapshot": result.get("cohort_snapshot") or fallback["cohort_snapshot"],
        "teaching_sequence": result.get("teaching_sequence") or fallback["teaching_sequence"],
        "teaching_modules": result.get("teaching_modules") or fallback["teaching_modules"],
        "evidence_citations": result.get("evidence_citations") or fallback["evidence_citations"],
        "teaching_focus": _safe_str(result.get("teaching_focus", fallback["teaching_focus"])),
        "teaching_action": _safe_str(result.get("teaching_action", fallback["teaching_action"])),
        "snapshot": snapshot,
    }


@app.post("/api/teacher/project-compare-report")
def teacher_project_compare_report(payload: dict) -> dict:
    left = dict(payload.get("left") or {})
    right = dict(payload.get("right") or {})
    if not left or not right:
        return {
            "headline": "请选择两个项目进行对比",
            "overall_judgement": "",
            "winning_project": "",
            "winning_reason": "",
            "dimension_cards": [],
            "risk_overlap": [],
            "teaching_actions": [],
            "focus_questions": [],
            "evidence_citations": [],
            "snapshot": {},
        }

    def _metric(item: dict[str, Any], key: str) -> float:
        return float(item.get(key, 0) or 0)

    def _risk_list(item: dict[str, Any]) -> list[str]:
        return [_safe_str(risk) for risk in list(item.get("top_risks") or []) if _safe_str(risk)]

    left_name = _safe_str(left.get("project_name", "项目A")) or "项目A"
    right_name = _safe_str(right.get("project_name", "项目B")) or "项目B"
    left_score = _metric(left, "latest_score")
    right_score = _metric(right, "latest_score")
    left_improvement = _metric(left, "improvement")
    right_improvement = _metric(right, "improvement")
    left_iterations = _metric(left, "submission_count")
    right_iterations = _metric(right, "submission_count")
    left_risks = _risk_list(left)
    right_risks = _risk_list(right)
    shared_risks = sorted(set(left_risks) & set(right_risks))
    left_only_risks = [risk for risk in left_risks if risk not in shared_risks]
    right_only_risks = [risk for risk in right_risks if risk not in shared_risks]

    left_strength_score = left_score * 0.55 + left_improvement * 0.2 + left_iterations * 0.05 - len(left_risks) * 0.7
    right_strength_score = right_score * 0.55 + right_improvement * 0.2 + right_iterations * 0.05 - len(right_risks) * 0.7
    stronger = left if left_strength_score >= right_strength_score else right
    weaker = right if stronger is left else left
    stronger_name = _safe_str(stronger.get("project_name", "更优项目")) or "更优项目"
    weaker_name = _safe_str(weaker.get("project_name", "另一项目")) or "另一项目"

    dimension_cards = [
        {
            "dimension": "当前分",
            "winner": left_name if left_score >= right_score else right_name,
            "delta": f"{abs(left_score - right_score):.1f} 分",
            "insight": f"{left_name} {left_score:.1f} 分，{right_name} {right_score:.1f} 分，当前完成度差异已经比较明显。",
        },
        {
            "dimension": "迭代成效",
            "winner": left_name if left_improvement >= right_improvement else right_name,
            "delta": f"{abs(left_improvement - right_improvement):.1f} 分",
            "insight": f"最近提分更明显的一项更值得复盘其修改路径，看是否能迁移到另一项。",
        },
        {
            "dimension": "迭代投入",
            "winner": left_name if left_iterations >= right_iterations else right_name,
            "delta": f"{abs(left_iterations - right_iterations):.0f} 次",
            "insight": "提交次数能帮助判断项目是稳步迭代，还是投入不足导致诊断停滞。",
        },
        {
            "dimension": "风险暴露",
            "winner": left_name if len(left_risks) <= len(right_risks) else right_name,
            "delta": f"{abs(len(left_risks) - len(right_risks))} 个风险",
            "insight": "风险更少的一方通常结构更稳，风险更多的一方更需要老师介入拆解。",
        },
    ]
    risk_overlap = [
        {
            "risk": risk,
            "status": "shared",
            "detail": "这是两项项目共同卡住的风险，适合做一次共性讲评。",
        }
        for risk in shared_risks[:3]
    ] + [
        {
            "risk": risk,
            "status": left_name,
            "detail": f"{left_name} 独有风险，说明它的短板更偏向个体性问题。",
        }
        for risk in left_only_risks[:2]
    ] + [
        {
            "risk": risk,
            "status": right_name,
            "detail": f"{right_name} 独有风险，建议单独追踪其修正质量。",
        }
        for risk in right_only_risks[:2]
    ]
    snapshot = {
        "left": left,
        "right": right,
        "shared_risks": shared_risks,
        "left_only_risks": left_only_risks,
        "right_only_risks": right_only_risks,
        "dimension_cards": dimension_cards,
    }
    fallback = {
        "headline": f"{stronger_name} 当前整体更稳，{weaker_name} 更需要教师介入。",
        "overall_judgement": (
            f"{stronger_name} 在当前分、风险控制或近期迭代上占优，更适合作为本轮示范样本；"
            f"{weaker_name} 则更适合作为反例，帮助老师快速定位这一类项目最容易断掉的环节。"
        ),
        "winning_project": stronger_name,
        "winning_reason": (
            f"{stronger_name} 的综合表现更好：当前分更高或风险更少，同时具备更清晰的可迁移经验。"
        ),
        "dimension_cards": dimension_cards,
        "risk_overlap": risk_overlap,
        "teaching_actions": [
            f"先讲 {stronger_name} 的亮点结构，再对照 {weaker_name} 的断点做一次示范讲评。",
            f"围绕 {(_safe_str(shared_risks[0]) if shared_risks else '核心风险')} 设计统一修改要求，减少共性返工。",
            f"优先复查 {weaker_name} 的下一轮提交，确认问题是否真正被修正。",
        ],
        "focus_questions": [
            f"{weaker_name} 的问题主要出在论证闭环、证据支撑，还是表达组织？",
            f"{stronger_name} 的成功经验里，哪些步骤可以要求另一项直接照做？",
            "两项项目的共同风险，是否已经到了需要全班统一讲评的程度？",
        ],
        "evidence_citations": [
            {
                "project_name": left_name,
                "claim": f"{left_name} 当前状态摘要",
                "evidence": _safe_str(left.get("summary", "")),
            },
            {
                "project_name": right_name,
                "claim": f"{right_name} 当前状态摘要",
                "evidence": _safe_str(right.get("summary", "")),
            },
        ],
    }
    if not composer_llm.enabled:
        return {**fallback, "snapshot": snapshot}

    result = composer_llm.chat_json(
        system_prompt=(
            "你是教师端的项目对比智能体，需要比较两个学生项目，并输出老师可直接拿来决策的结构化 JSON。\n"
            "请只输出 JSON，字段必须包含：\n"
            'headline: string,\n'
            'overall_judgement: string,\n'
            'winning_project: string,\n'
            'winning_reason: string,\n'
            'dimension_cards: [{"dimension": string, "winner": string, "delta": string, "insight": string}],\n'
            'risk_overlap: [{"risk": string, "status": string, "detail": string}],\n'
            'teaching_actions: string[],\n'
            'focus_questions: string[],\n'
            'evidence_citations: [{"project_name": string, "claim": string, "evidence": string}]。\n'
            "要求：\n"
            "1. 不要空泛夸奖，必须指出两项项目到底差在哪里。\n"
            "2. 既要比较当前结果，也要比较迭代势头与风险分布。\n"
            "3. 至少给出 3 个可以指导老师下一步动作的结论。\n"
            "4. 语言简洁、信息密度高，适合前端卡片展示。"
        ),
        user_prompt=f"两个项目的对比数据：\n{json.dumps(snapshot, ensure_ascii=False)}",
        temperature=0.2,
        model=settings.llm_structured_model,
    ) or {}
    if not isinstance(result, dict):
        return {**fallback, "snapshot": snapshot}
    return {
        "headline": _safe_str(result.get("headline", fallback["headline"])),
        "overall_judgement": _safe_str(result.get("overall_judgement", fallback["overall_judgement"])),
        "winning_project": _safe_str(result.get("winning_project", fallback["winning_project"])),
        "winning_reason": _safe_str(result.get("winning_reason", fallback["winning_reason"])),
        "dimension_cards": result.get("dimension_cards") or fallback["dimension_cards"],
        "risk_overlap": result.get("risk_overlap") or fallback["risk_overlap"],
        "teaching_actions": result.get("teaching_actions") or fallback["teaching_actions"],
        "focus_questions": result.get("focus_questions") or fallback["focus_questions"],
        "evidence_citations": result.get("evidence_citations") or fallback["evidence_citations"],
        "snapshot": snapshot,
    }



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


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(project_id: str, conversation_id: str) -> dict:
    ok = conv_store.delete(project_id, conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "ok", "conversation_id": conversation_id}


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
    neo4j_data = graph_service.teacher_dashboard(category=category, limit=limit)

    projects = json_store.list_projects()
    all_subs: list[dict] = []
    unique_projects: set[str] = set()
    unique_students: set[str] = set()
    intent_counter: dict[str, int] = {}
    rule_counter: dict[str, int] = {}
    scores: list[float] = []
    total_dims = 0
    recent_activity: list[dict] = []

    for proj in projects:
        pid = proj.get("project_id", "")
        subs = proj.get("submissions", [])
        if not subs:
            continue
        unique_projects.add(pid)
        for sub in subs:
            sid = str(sub.get("student_id") or "").strip()
            if sid and sid.lower() != "none":
                unique_students.add(sid)
            elif pid.startswith("project-"):
                unique_students.add(pid.replace("project-", "", 1))
            all_subs.append(sub)

            intent = sub.get("intent", "")
            if intent:
                _label = {
                    "project_diagnosis": "项目诊断",
                    "idea_brainstorm": "想法探索",
                    "business_model": "商业模式",
                    "competition_prep": "竞赛准备",
                    "learning_concept": "概念学习",
                    "general_chat": "一般咨询",
                    "pressure_test": "压力测试",
                    "evidence_check": "证据核查",
                    "market_competitor": "市场竞品",
                }.get(intent, intent)
                intent_counter[_label] = intent_counter.get(_label, 0) + 1

            diag = sub.get("diagnosis", {}) if isinstance(sub.get("diagnosis"), dict) else {}
            sc = diag.get("overall_score")
            if sc and float(sc) > 0:
                scores.append(float(sc))

            for r in (diag.get("triggered_rules", []) or []):
                rid = r.get("id", "") if isinstance(r, dict) else str(r)
                if rid:
                    rule_counter[rid] = rule_counter.get(rid, 0) + 1

            kg = sub.get("kg_analysis", {}) if isinstance(sub.get("kg_analysis"), dict) else {}
            total_dims += len(kg.get("entities", []))

            created = sub.get("created_at", "")
            if created:
                recent_activity.append({"project_id": pid, "student_id": sid, "created_at": created, "intent": intent})

    recent_activity.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    avg_score = round(sum(scores) / len(scores), 2) if scores else 0
    intent_dist = sorted(intent_counter.items(), key=lambda x: x[1], reverse=True)
    rule_dist = sorted(rule_counter.items(), key=lambda x: x[1], reverse=True)[:limit]

    student_overview = {
        "total_student_projects": len(unique_projects),
        "total_students": len(unique_students),
        "total_submissions": len(all_subs),
        "avg_score": avg_score,
        "total_dimensions_extracted": total_dims,
        "intent_distribution": [{"intent": k, "count": v} for k, v in intent_dist],
        "student_risk_rules": [{"rule": k, "count": v} for k, v in rule_dist],
        "recent_activity": recent_activity[:20],
    }

    return {
        "category_filter": category,
        "limit": limit,
        "data": neo4j_data,
        "student_overview": student_overview,
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
def rebuild_hypergraph(min_pattern_support: int = 1, max_edges: int = 400) -> dict:
    data = hypergraph_service.rebuild(min_pattern_support=min_pattern_support, max_edges=max_edges)
    return {
        "min_pattern_support": min_pattern_support,
        "max_edges": max_edges,
        "data": data,
    }


@app.get("/api/hypergraph/insight")
def hypergraph_insight(category: str | None = None, rule_ids: str = "", limit: int = 8) -> dict:
    parsed_rule_ids = [x.strip() for x in rule_ids.split(",") if x.strip()]
    data = hypergraph_service.insight(category=category, rule_ids=parsed_rule_ids, limit=limit)
    return {
        "category": category,
        "rule_ids": parsed_rule_ids,
        "limit": limit,
        "data": data,
    }


@app.get("/api/hypergraph/library")
def hypergraph_library(limit: int = 24) -> dict:
    data = hypergraph_service.library_snapshot(limit=limit)
    return {"limit": limit, "data": data}


@app.get("/api/hypergraph/catalog")
def hypergraph_catalog() -> dict:
    return hypergraph_service.catalog()


@app.post("/api/hypergraph/project-view")
def hypergraph_project_view(payload: dict[str, Any]) -> dict:
    data = hypergraph_service.project_match_view(
        hypergraph_insight=payload.get("hypergraph_insight", {}) if isinstance(payload, dict) else {},
        hypergraph_student=payload.get("hypergraph_student", {}) if isinstance(payload, dict) else {},
        pressure_trace=payload.get("pressure_test_trace", {}) if isinstance(payload, dict) else {},
    )
    return {"data": data}


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


def _build_conversation_analytics(class_id: str | None = None, cohort_id: str | None = None) -> dict[str, Any]:
    """Compute class-level conversation quality metrics from dialogue_turn submissions.

    Metrics are aggregated per student and derived only from submissions whose
    source_type starts with "dialogue_turn".
    """
    projects = json_store.list_projects()
    students: dict[str, dict[str, Any]] = {}
    topics: dict[str, dict[str, Any]] = {}
    fallacies: dict[str, dict[str, Any]] = {}

    for project in projects:
        pid = _safe_str(project.get("project_id", ""))
        for sub in project.get("submissions", []) or []:
            source_type = str(sub.get("source_type", ""))
            if not source_type.startswith("dialogue_turn"):
                continue
            if class_id and sub.get("class_id") != class_id:
                continue
            if cohort_id and sub.get("cohort_id") != cohort_id:
                continue

            sid = _safe_str(sub.get("student_id", ""))
            if not sid:
                continue

            student = students.setdefault(
                sid,
                {
                    "student_id": sid,
                    "project_ids": set(),
                    "conversation_ids": set(),
                    "turns": [],
                    "turn_count": 0,
                    "effective_turn_count": 0,
                    "challenge_questions_total": 0,
                    "missing_evidence_total": 0,
                    "intent_counts": {},
                    "high_intent_turns": 0,
                    "intent_turns": 0,
                    "score_sum": 0.0,
                    "score_count": 0,
                    "latest_bottleneck": "",
                },
            )

            student["project_ids"].add(pid)
            conv_id = _safe_str(sub.get("conversation_id", ""))
            if conv_id:
                student["conversation_ids"].add(conv_id)
            student["turn_count"] += 1
            student["effective_turn_count"] += 1

            ao = sub.get("agent_outputs", {}) if isinstance(sub.get("agent_outputs"), dict) else {}
            critic = ao.get("critic", {}) if isinstance(ao.get("critic"), dict) else {}
            cq_list = critic.get("counterfactual_questions") or critic.get("challenge_points") or []
            if isinstance(cq_list, list):
                cq_count = len(cq_list)
            else:
                cq_count = 0
            me_list = critic.get("missing_evidence") or []
            if isinstance(me_list, list):
                me_count = len(me_list)
            else:
                me_count = 0
            student["challenge_questions_total"] += cq_count
            student["missing_evidence_total"] += me_count

            diagnosis = sub.get("diagnosis", {}) if isinstance(sub.get("diagnosis"), dict) else {}
            score = _safe_float(diagnosis.get("overall_score", sub.get("overall_score", 0)))
            if score > 0:
                student["score_sum"] += score
                student["score_count"] += 1

            orch = ao.get("orchestration", {}) if isinstance(ao.get("orchestration"), dict) else {}
            raw_text = _safe_str(sub.get("raw_text", ""))
            intent = _normalize_intent(
                orch.get("intent", "") or sub.get("intent", ""),
                raw_text,
            )
            intent_counts: dict[str, int] = student["intent_counts"]
            intent_counts[intent] = intent_counts.get(intent, 0) + 1
            student["intent_turns"] += 1
            is_high_intent = intent in {"学习理解", "商业诊断", "方案设计", "路演表达"}
            if is_high_intent:
                student["high_intent_turns"] += 1

            created_at = _safe_str(sub.get("created_at", ""))
            student["turns"].append(
                {
                    "created_at": created_at,
                    "missing_evidence": me_count,
                    "is_high_intent": is_high_intent,
                }
            )

            # 话题热点与共性谬误聚合（基于意图 + 触发规则）
            topic_key = intent or "综合咨询"
            t_bucket = topics.setdefault(
                topic_key,
                {
                    "topic": topic_key,
                    "turn_count": 0,
                    "student_ids": set(),
                    "rule_hits": {},
                },
            )
            t_bucket["turn_count"] += 1
            t_bucket["student_ids"].add(sid)

            triggered_raw = diagnosis.get("triggered_rules", []) or sub.get("triggered_rules", []) or []
            rule_ids = _normalize_rules(triggered_raw)
            for rid in rule_ids:
                rid_u = _safe_str(rid).upper()
                if not rid_u:
                    continue
                # 话题-规则共现
                rh = t_bucket["rule_hits"]
                rh[rid_u] = rh.get(rid_u, 0) + 1
                # 班级层面的对话谬误统计
                f_bucket = fallacies.setdefault(
                    rid_u,
                    {
                        "rule_id": rid_u,
                        "rule_name": get_rule_name(rid_u),
                        "fallacy": RULE_FALLACY_MAP.get(rid_u, ""),
                        "edge_families": RULE_EDGE_MAP.get(rid_u, []),
                        "hit_count": 0,
                        "student_ids": set(),
                    },
                )
                f_bucket["hit_count"] += 1
                f_bucket["student_ids"].add(sid)

            if diagnosis.get("bottleneck"):
                student["latest_bottleneck"] = _safe_str(diagnosis.get("bottleneck"))

    if not students:
        empty_box = {"min": 0.0, "q1": 0.0, "median": 0.0, "q3": 0.0, "max": 0.0, "avg": 0.0}
        return {
            "class_id": class_id,
            "cohort_id": cohort_id,
            "summary": {
                "student_count": 0,
                "conversation_count": 0,
                "avg_turn_count": 0.0,
                "avg_question_density": 0.0,
                "avg_evidence_awareness_trend": 0.0,
                "avg_high_order_ratio": 0.0,
            },
            "scatter": [],
            "high_order_ratio_box": empty_box,
            "students": [],
            "topics": [],
            "fallacies": [],
        }

    scatter_rows: list[dict[str, Any]] = []
    hor_values: list[float] = []  # 班级箱线图与均值仅统计样本充足的学生
    students_out: list[dict[str, Any]] = []
    total_turns = 0

    # 高阶对话占比计算参数：
    # - 时间加权仍按整段对话前后两半划分
    # - 为保证班级分布稳定，仅纳入轮数较充足的学生（例如 8 轮及以上）
    T_MIN_HIGH_ORDER_TURNS = 8
    W1, W2 = 1.0, 1.5  # 前半段/后半段权重

    for sid, sdata in students.items():
        turns = sorted(sdata["turns"], key=lambda r: r.get("created_at", ""))
        missing_counts = [int(t.get("missing_evidence", 0) or 0) for t in turns]
        high_flags = [bool(t.get("is_high_intent", False)) for t in turns]

        # 证据意识趋势（保持原有定义）
        evidence_trend = 0.0
        if len(missing_counts) >= 2:
            evidence_trend = (missing_counts[0] - missing_counts[-1]) / max(len(missing_counts) - 1, 1)

        # 提问密度（保持原有定义）
        question_density = (
            float(sdata["challenge_questions_total"]) / max(int(sdata["effective_turn_count"] or 0), 1)
        )

        # 高阶对话占比：基础占比 + 时间加权占比
        T = len(turns)
        T_high = int(sdata.get("high_intent_turns", 0) or 0)
        R_base = float(T_high) / max(T, 1)

        if T >= 2:
            mid = T // 2
            h1 = high_flags[:mid]
            h2 = high_flags[mid:]
            T1, T2 = len(h1), len(h2)
            Th1 = sum(1 for f in h1 if f)
            Th2 = sum(1 for f in h2 if f)
            denom = W1 * T1 + W2 * T2
            R_time = (W1 * Th1 + W2 * Th2) / denom if denom > 0 else R_base
        else:
            R_time = R_base

        # 最终指标：样本不足用 R_base，仅用于个人视图；样本充足用时间加权，并进入班级统计
        sample_sufficient = T >= T_MIN_HIGH_ORDER_TURNS
        high_order_ratio = R_time if sample_sufficient else R_base

        if sample_sufficient:
            hor_values.append(high_order_ratio)

        # 评分均值（保持原有定义）
        avg_score = (
            float(sdata["score_sum"]) / max(int(sdata["score_count"] or 0), 1)
            if sdata["score_count"]
            else 0.0
        )
        intent_counts = sdata["intent_counts"]
        dominant_intent = (
            max(intent_counts.items(), key=lambda kv: kv[1])[0] if intent_counts else "综合咨询"
        )

        # Persona: coarse clustering based on density and trend
        persona = "直觉表达型"
        if question_density >= 0.7 and evidence_trend > 0:
            persona = "证据敏感型"
        elif question_density < 0.35 and high_order_ratio < 0.4:
            persona = "被动应答型"

        students_out.append(
            {
                "student_id": sid,
                "project_count": len(sdata["project_ids"]),
                "conversation_count": len(sdata["conversation_ids"]),
                "turn_count": int(sdata["turn_count"] or 0),
                "effective_turn_count": int(sdata["effective_turn_count"] or 0),
                "question_density": round(question_density, 3),
                "evidence_awareness_trend": round(evidence_trend, 3),
                "high_order_ratio": round(high_order_ratio, 3),
                "avg_score": round(avg_score, 2),
                "dominant_intent": dominant_intent,
                "total_challenge_questions": int(sdata["challenge_questions_total"] or 0),
                "total_missing_evidence": int(sdata["missing_evidence_total"] or 0),
                "latest_risk_summary": sdata["latest_bottleneck"],
                "persona": persona,
                "high_order_sample_sufficient": sample_sufficient,
            }
        )

        scatter_rows.append(
            {
                "student_id": sid,
                "turn_count": int(sdata["turn_count"] or 0),
                "question_density": round(question_density, 3),
                "evidence_awareness_trend": round(evidence_trend, 3),
                "avg_score": round(avg_score, 2),
            }
        )

        total_turns += int(sdata.get("turn_count", 0) or 0)

    def _pct(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        vals = sorted(values)
        idx = (p / 100.0) * (len(vals) - 1)
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if lo == hi:
            return vals[lo]
        frac = idx - lo
        return vals[lo] + (vals[hi] - vals[lo]) * frac

    high_order_box = {
        "min": min(hor_values) if hor_values else 0.0,
        "q1": _pct(hor_values, 25.0),
        "median": _pct(hor_values, 50.0),
        "q3": _pct(hor_values, 75.0),
        "max": max(hor_values) if hor_values else 0.0,
        "avg": (sum(hor_values) / len(hor_values)) if hor_values else 0.0,
    }

    summary = {
        "student_count": len(students_out),
        "conversation_count": sum(len(s.get("conversation_ids", [])) for s in students.values()),
        "avg_turn_count": round(
            sum(int(s.get("turn_count", 0) or 0) for s in students.values()) / max(len(students), 1), 2
        ),
        "avg_question_density": round(
            sum(row["question_density"] for row in students_out) / max(len(students_out), 1), 3
        ),
        "avg_evidence_awareness_trend": round(
            sum(row["evidence_awareness_trend"] for row in students_out) / max(len(students_out), 1), 3
        ),
        # 仅统计样本充足的学生（T >= T_MIN_HIGH_ORDER_TURNS）
        "avg_high_order_ratio": round(
            (sum(hor_values) / max(len(hor_values), 1)) if hor_values else 0.0,
            3,
        ),
    }

    # 话题热点（Top N，带规则与学生覆盖率）
    topics_out: list[dict[str, Any]] = []
    total_students = max(len(students_out), 1)
    total_turns = max(total_turns, 1)
    for topic_key, bucket in topics.items():
        rule_hits = bucket.get("rule_hits", {}) or {}
        related_rules: list[dict[str, Any]] = []
        for rid, cnt in sorted(rule_hits.items(), key=lambda kv: kv[1], reverse=True)[:6]:
            rid_u = _safe_str(rid).upper()
            related_rules.append(
                {
                    "rule_id": rid_u,
                    "rule_name": get_rule_name(rid_u),
                    "fallacy": RULE_FALLACY_MAP.get(rid_u, ""),
                    "edge_families": RULE_EDGE_MAP.get(rid_u, []),
                    "hit_count": int(cnt),
                }
            )
        topics_out.append(
            {
                "topic": topic_key,
                "turn_count": int(bucket.get("turn_count", 0) or 0),
                "students_ratio": round(len(bucket.get("student_ids", set())) / total_students, 3),
                "turn_ratio": round((bucket.get("turn_count", 0) or 0) / total_turns, 3),
                "related_rules": related_rules,
            }
        )
    topics_out.sort(key=lambda row: row["turn_count"], reverse=True)
    topics_out = topics_out[:8]

    # 班级共性谬误（按触发频次排序）
    fallacies_out: list[dict[str, Any]] = []
    for rid, fb in fallacies.items():
        fallacies_out.append(
            {
                "rule_id": fb.get("rule_id", rid),
                "rule_name": fb.get("rule_name", get_rule_name(rid)),
                "fallacy": fb.get("fallacy", RULE_FALLACY_MAP.get(rid, "")),
                "edge_families": fb.get("edge_families", RULE_EDGE_MAP.get(rid, [])),
                "hit_count": int(fb.get("hit_count", 0) or 0),
                "students_ratio": round(len(fb.get("student_ids", set())) / total_students, 3),
            }
        )
    fallacies_out.sort(key=lambda row: row["hit_count"], reverse=True)

    return {
        "class_id": class_id,
        "cohort_id": cohort_id,
        "summary": summary,
        "scatter": scatter_rows,
        "high_order_ratio_box": high_order_box,
        "students": students_out,
        "topics": topics_out,
        "fallacies": fallacies_out,
    }


@app.get("/api/teacher/student/{student_id}/capability")
def teacher_student_capability(student_id: str, class_id: str | None = None, cohort_id: str | None = None) -> dict:
    """单个学生的五维能力画像 + 最近提交趋势。

    该接口复用班级能力映射的维度定义，基于该学生的文件提交
    （source_type in ["file", "file_in_chat"]）聚合 Empathy/Ideation/Business/Execution/Pitching
    五个维度的平均能力值，并给出最近 3 次提交的整体能力走势。
    """
    student_id = _safe_str(student_id)
    if not student_id:
        return {
            "student_id": "",
            "class_id": class_id,
            "submission_count": 0,
            "dimensions": [],
            "radar": [],
            "trend": [],
        }

    projects = json_store.list_projects()
    submissions: list[dict] = []
    for project in projects:
        for sub in project.get("submissions", []) or []:
            source_type = sub.get("source_type", "")
            if source_type not in ["file", "file_in_chat"]:
                continue
            if _safe_str(sub.get("student_id", "")) != student_id:
                continue
            if class_id and sub.get("class_id") != class_id:
                continue
            if cohort_id and sub.get("cohort_id") != cohort_id:
                continue
            submissions.append(sub)

    if not submissions:
        return {
            "student_id": student_id,
            "class_id": class_id,
            "submission_count": 0,
            "dimensions": [
                {"name": "痛点发现 (Empathy)", "score": 0.0, "max": 5.0},
                {"name": "方案策划 (Ideation)", "score": 0.0, "max": 5.0},
                {"name": "商业建模 (Business)", "score": 0.0, "max": 5.0},
                {"name": "资源杠杆 (Execution)", "score": 0.0, "max": 5.0},
                {"name": "路演表达 (Pitching)", "score": 0.0, "max": 5.0},
            ],
            "radar": [0.0] * 5,
            "trend": [],
        }

    diagnosis_keywords = {
        "empathy": ["痛点", "需求", "用户", "验证"],
        "ideation": ["方案", "设计", "创新", "功能"],
        "business": ["盈利", "商业模式", "定价", "收入"],
        "execution": ["资源", "团队", "执行", "里程碑"],
        "pitching": ["路演", "表达", "叙事", "数据"],
    }

    dim_acc: dict[str, list[float]] = {k: [] for k in diagnosis_keywords.keys()}
    # 为趋势图按时间记录每次提交的整体能力均值
    timeline_points: list[dict[str, Any]] = []

    for sub in sorted(submissions, key=lambda r: _safe_str(r.get("created_at", ""))):
        diagnosis = sub.get("diagnosis", {}) if isinstance(sub.get("diagnosis"), dict) else {}
        overall_score = _safe_float(diagnosis.get("overall_score", 0))
        raw_text = _safe_str(sub.get("raw_text") or "").lower()
        per_dim_scores: list[float] = []
        for dim, keywords in diagnosis_keywords.items():
            keyword_hit_count = sum(1 for kw in keywords if kw in raw_text)
            base = 1.2 + min(keyword_hit_count, 4) * 0.8
            if overall_score >= 7:
                base += 0.5
            elif overall_score <= 5.5:
                base -= 0.3
            score = max(0.0, min(5.0, round(base, 1)))
            dim_acc[dim].append(score)
            per_dim_scores.append(score)
        if per_dim_scores:
            capability_index = round(sum(per_dim_scores) / len(per_dim_scores), 2)
            timeline_points.append(
                {
                    "created_at": _safe_str(sub.get("created_at", "")),
                    "capability_index": capability_index,
                    "overall_score": overall_score,
                }
            )

    dim_order = [
        ("痛点发现 (Empathy)", "empathy"),
        ("方案策划 (Ideation)", "ideation"),
        ("商业建模 (Business)", "business"),
        ("资源杠杆 (Execution)", "execution"),
        ("路演表达 (Pitching)", "pitching"),
    ]
    dimensions: list[dict[str, Any]] = []
    radar: list[float] = []
    for name, key in dim_order:
        scores = dim_acc.get(key, [])
        avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0
        dimensions.append({"name": name, "score": avg_score, "max": 5.0})
        radar.append(avg_score)

    # 仅返回最近 3 次提交的能力走势，供前端绘制 sparkline
    timeline_points.sort(key=lambda r: r.get("created_at", ""))
    recent_trend = timeline_points[-3:]

    return {
        "student_id": student_id,
        "class_id": class_id,
        "submission_count": len(submissions),
        "dimensions": dimensions,
        "radar": radar,
        "trend": recent_trend,
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


def _project_submissions_by_logical_id(project_state: dict, logical_project_id: str = "") -> list[dict]:
    submissions = list(project_state.get("submissions", []) or [])
    if not logical_project_id:
        return submissions
    return [
        s for s in submissions
        if _safe_str(s.get("logical_project_id") or s.get("project_id") or s.get("conversation_id", "")) == logical_project_id
    ]


def _extract_rag_cases(sub: dict) -> list[dict[str, Any]]:
    """Safely extract rag_cases list from a submission.

    rag_cases are stored inside agent_outputs.rag_cases for dialogue_turn
    submissions; fall back to top-level rag_cases if present.
    """
    if not isinstance(sub, dict):
        return []
    ao = sub.get("agent_outputs", {}) if isinstance(sub.get("agent_outputs"), dict) else {}
    rag = ao.get("rag_cases") or sub.get("rag_cases") or []
    if not isinstance(rag, list):
        return []
    return [item for item in rag if isinstance(item, dict)]


def _build_case_benchmark_from_submissions(
    project_id: str,
    logical_project_id: str,
    submissions: list[dict],
) -> dict[str, Any]:
    """Core aggregator: build case-benchmark payload from a list of submissions.

    This function is shared by both the per-project endpoint and the
    class-level overview builder.
    """
    if not submissions:
        return {
            "project_id": project_id,
            "logical_project_id": logical_project_id,
            "error": "该项目还没有任何可用于案例对标的提交记录",
            "top_cases": [],
        }

    submissions_sorted = sorted(submissions, key=lambda row: _safe_str(row.get("created_at", "")))
    latest = submissions_sorted[-1]

    diagnosis = latest.get("diagnosis", {}) if isinstance(latest.get("diagnosis"), dict) else {}
    overall_score = _safe_float(diagnosis.get("overall_score", latest.get("overall_score", 0)))
    triggered_rules_raw = diagnosis.get("triggered_rules", []) or latest.get("triggered_rules", []) or []
    student_risks = _normalize_rules(triggered_rules_raw)
    risk_level = _risk_level(overall_score, triggered_rules_raw)
    diagnosis_rubric = diagnosis.get("rubric", []) if isinstance(diagnosis.get("rubric"), list) else []

    student_id = _safe_str(latest.get("student_id", ""))
    class_id = _safe_str(latest.get("class_id", ""))
    cohort_id = _safe_str(latest.get("cohort_id", ""))
    project_label = _project_label(logical_project_id or project_id, submissions_sorted)

    # Aggregate rag_cases across submissions
    case_stats: dict[str, dict[str, Any]] = {}
    case_risk_counts: dict[str, int] = {}
    case_rubric_map: dict[str, dict[str, Any]] = {}
    rag_turn_count = 0
    rag_case_hits = 0

    for sub in submissions_sorted:
        rag_list = _extract_rag_cases(sub)
        if not rag_list:
            continue
        rag_turn_count += 1
        for case in rag_list:
            case_id = _safe_str(case.get("case_id") or case.get("project_name") or case.get("id") or "")
            if not case_id:
                continue

            stats = case_stats.setdefault(
                case_id,
                {
                    "case_id": case_id,
                    "project_name": _safe_str(case.get("project_name", "")),
                    "category": _safe_str(case.get("category", "")),
                    "hit_count": 0,
                    "similarity_sum": 0.0,
                    "max_similarity": 0.0,
                    "rubric_coverage": case.get("rubric_coverage") if isinstance(case.get("rubric_coverage"), list) else [],
                    "risk_flags": [],
                    "summary": _safe_str(case.get("summary", ""))[:400],
                },
            )

            stats["hit_count"] += 1
            rag_case_hits += 1

            sim = _safe_float(case.get("similarity", 0.0))
            stats["similarity_sum"] += sim
            if sim > stats["max_similarity"]:
                stats["max_similarity"] = sim

            # Aggregate risk flags per case and globally
            flags = [
                _safe_str(f)
                for f in (case.get("risk_flags") or [])
                if _safe_str(f)
            ]
            if flags:
                existing_flags = set(stats.get("risk_flags", []))
                for rf in flags:
                    if rf not in existing_flags:
                        stats.setdefault("risk_flags", []).append(rf)
                        existing_flags.add(rf)
                    case_risk_counts[rf] = case_risk_counts.get(rf, 0) + 1

            # Aggregate rubric coverage across cases
            rc_list = case.get("rubric_coverage") or []
            if isinstance(rc_list, list):
                for entry in rc_list:
                    if not isinstance(entry, dict):
                        continue
                    rubric_item = _safe_str(entry.get("rubric_item") or entry.get("item") or "")
                    if not rubric_item:
                        continue
                    bucket = case_rubric_map.setdefault(
                        rubric_item,
                        {"rubric_item": rubric_item, "covered_count": 0, "total_count": 0},
                    )
                    bucket["total_count"] += 1
                    if bool(entry.get("covered")):
                        bucket["covered_count"] += 1

    # Finalize case stats
    for stats in case_stats.values():
        hits = max(1, int(stats.get("hit_count", 0) or 0))
        stats["avg_similarity"] = round(float(stats.get("similarity_sum", 0.0)) / hits, 4)

    top_cases = sorted(
        case_stats.values(),
        key=lambda row: (int(row.get("hit_count", 0) or 0), float(row.get("max_similarity", 0.0) or 0.0)),
        reverse=True,
    )

    case_risks = [
        {"risk_id": rid, "count": count}
        for rid, count in sorted(case_risk_counts.items(), key=lambda kv: kv[1], reverse=True)
    ]

    case_rubric = sorted(
        case_rubric_map.values(),
        key=lambda row: (float(row.get("covered_count", 0) or 0) / max(int(row.get("total_count", 0) or 0), 1)),
        reverse=True,
    )

    if not top_cases:
        return {
            "project_id": project_id,
            "logical_project_id": logical_project_id,
            "student_project": {
                "project_id": project_id,
                "logical_project_id": logical_project_id,
                "student_id": student_id,
                "class_id": class_id,
                "cohort_id": cohort_id,
                "project_name": project_label,
                "overall_score": overall_score,
                "risk_level": risk_level,
            },
            "top_cases": [],
            "similarity": {
                "rag_turn_count": rag_turn_count,
                "rag_case_hits": rag_case_hits,
                "avg_top_similarity": 0.0,
                "max_top_similarity": 0.0,
            },
            "student_rubric": diagnosis_rubric,
            "case_rubric": [],
            "student_risks": student_risks,
            "case_risks": [],
        }

    top_k = top_cases[:3]
    avg_top_similarity = sum(c.get("avg_similarity", 0.0) for c in top_k) / max(len(top_k), 1)
    max_top_similarity = max(c.get("max_similarity", 0.0) for c in top_k)

    return {
        "project_id": project_id,
        "logical_project_id": logical_project_id,
        "student_project": {
            "project_id": project_id,
            "logical_project_id": logical_project_id,
            "student_id": student_id,
            "class_id": class_id,
            "cohort_id": cohort_id,
            "project_name": project_label,
            "overall_score": overall_score,
            "risk_level": risk_level,
        },
        "top_cases": top_k,
        "similarity": {
            "rag_turn_count": rag_turn_count,
            "rag_case_hits": rag_case_hits,
            "avg_top_similarity": round(avg_top_similarity, 4),
            "max_top_similarity": round(max_top_similarity, 4),
        },
        "student_rubric": diagnosis_rubric,
        "case_rubric": case_rubric,
        "student_risks": student_risks,
        "case_risks": case_risks,
    }


def _build_case_benchmark_for_project(project_id: str, logical_project_id: str = "") -> dict[str, Any]:
    """Public builder for a single project/logical project case benchmark."""
    project_state = json_store.load_project(project_id)
    submissions = _project_submissions_by_logical_id(project_state, logical_project_id)
    return _build_case_benchmark_from_submissions(project_id, logical_project_id or project_id, submissions)


def _build_case_benchmark_overview(class_id: str | None = None, cohort_id: str | None = None) -> dict[str, Any]:
    """Class-level overview of case benchmarking for teacher dashboard.

    Groups submissions by (project_id, logical_project_id) filtered by
    class_id / cohort_id, then runs the per-project builder and keeps
    items that have at least one retrieved case.
    """
    projects = json_store.list_projects()
    grouped: dict[tuple[str, str], list[dict]] = {}

    for project in projects:
        pid = _safe_str(project.get("project_id", ""))
        state = json_store.load_project(pid)
        for sub in state.get("submissions", []) or []:
            if class_id and sub.get("class_id") != class_id:
                continue
            if cohort_id and sub.get("cohort_id") != cohort_id:
                continue
            logical_id = _safe_str(sub.get("logical_project_id") or sub.get("project_id") or sub.get("conversation_id") or pid)
            grouped.setdefault((pid, logical_id), []).append(sub)

    items: list[dict[str, Any]] = []
    for (pid, logical_id), subs in grouped.items():
        benchmark = _build_case_benchmark_from_submissions(pid, logical_id, subs)
        if benchmark.get("top_cases"):
            # For class overview we only keep a light-weight representative
            rep_cases = benchmark["top_cases"][:2]
            items.append(
                {
                    "student_project": benchmark.get("student_project", {}),
                    "representative_cases": rep_cases,
                    "similarity": benchmark.get("similarity", {}),
                    "student_risks": benchmark.get("student_risks", []),
                    "case_risks": benchmark.get("case_risks", []),
                }
            )

    items.sort(
        key=lambda row: (
            -len(row.get("student_risks", []) or []),
            -float(row.get("similarity", {}).get("avg_top_similarity", 0.0) or 0.0),
        ),
    )

    return {
        "class_id": class_id,
        "cohort_id": cohort_id,
        "project_count": len(items),
        "items": items,
    }


def _review_score_band(score: float) -> str:
    score = _safe_float(score)
    lower = max(0, int(score - 1))
    upper = min(10, int(score + 1))
    return f"{lower}-{upper}/10"


def _risk_level(overall_score: float, triggered_rules: list[Any]) -> str:
    rule_count = len(triggered_rules or [])
    score = _safe_float(overall_score)
    if rule_count >= 4 or score < 4.5:
        return "高"
    if rule_count >= 2 or score < 6.5:
        return "中"
    return "低"


def _assessment_evidence_chain(filtered_subs: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for sub in filtered_subs[-8:]:
        quotes = _safe_evidence_quotes(sub.get("evidence_quotes", []))
        if not quotes:
            fallback_quote = re.sub(r"\s+", " ", _safe_str(sub.get("raw_text", ""))).strip()[:120]
            fallback_risks = _normalize_rules(
                sub.get("triggered_rules")
                or (sub.get("diagnosis", {}) if isinstance(sub.get("diagnosis"), dict) else {}).get("triggered_rules", [])
            )
            if fallback_quote:
                quotes = [{
                    "quote": fallback_quote,
                    "risk_id": fallback_risks[0] if fallback_risks else "",
                    "risk_name": get_rule_name(fallback_risks[0]) if fallback_risks else "原文片段",
                    "source": "dialogue",
                }]
        # Try to infer rubric items linked to this submission from diagnosis rubric
        diag = sub.get("diagnosis", {}) if isinstance(sub.get("diagnosis"), dict) else {}
        diagnosis_rubric = diag.get("rubric", []) if isinstance(diag.get("rubric"), list) else []
        rubric_names = [
            str(item.get("item", ""))
            for item in diagnosis_rubric
            if isinstance(item, dict) and _safe_float(item.get("score", 0)) < 8
        ]
        # Normalized rule ids on this submission
        rule_ids = _normalize_rules(diag.get("triggered_rules", []) or sub.get("triggered_rules", []))
        for quote in quotes[:4]:
            rows.append({
                **quote,
                "created_at": sub.get("created_at", ""),
                "project_phase": _safe_str(sub.get("project_phase", "")),
                "source_type": _safe_str(sub.get("source_type", "")),
                "submission_id": _safe_str(sub.get("submission_id", "")),
                # Optional richer context for evidence-trace views
                "rubric_items": rubric_names,
                "rule_ids": rule_ids,
            })
    if len(rows) < 2:
        extra_rows: list[dict] = []
        for sub in filtered_subs[-2:]:
            fallback_quote = re.sub(r"\s+", " ", _safe_str(sub.get("raw_text", ""))).strip()[:120]
            if fallback_quote:
                extra_rows.append({
                    "quote": fallback_quote,
                    "risk_id": "",
                    "risk_name": "原文片段",
                    "source": "dialogue",
                    "created_at": sub.get("created_at", ""),
                    "project_phase": _safe_str(sub.get("project_phase", "")),
                    "source_type": _safe_str(sub.get("source_type", "")),
                    "submission_id": _safe_str(sub.get("submission_id", "")),
                    "rubric_items": [],
                    "rule_ids": [],
                })
        rows.extend(extra_rows)
    return rows[-12:]


def _assessment_rubric(latest_sub: dict) -> list[dict]:
    diagnosis = latest_sub.get("diagnosis", {}) if isinstance(latest_sub.get("diagnosis"), dict) else {}
    raw_text = _safe_str(latest_sub.get("raw_text", ""))
    triggered_rules = diagnosis.get("triggered_rules", []) or []
    evidence = _safe_evidence_quotes(latest_sub.get("evidence_quotes", []))
    rubric_items = [
        {"id": "R1", "name": "问题定义", "weight": 0.12, "good": ["痛点", "需求", "场景"]},
        {"id": "R2", "name": "用户证据", "weight": 0.14, "good": ["访谈", "用户", "验证"]},
        {"id": "R3", "name": "方案可行性", "weight": 0.12, "good": ["方案", "技术", "实现"]},
        {"id": "R4", "name": "商业模式", "weight": 0.14, "good": ["市场", "盈利", "商业模式"]},
        {"id": "R5", "name": "竞争与市场", "weight": 0.1, "good": ["竞品", "市场", "对比"]},
        {"id": "R6", "name": "财务逻辑", "weight": 0.08, "good": ["收入", "成本", "定价"]},
        {"id": "R7", "name": "创新与差异", "weight": 0.1, "good": ["创新", "优势", "差异"]},
        {"id": "R8", "name": "执行与里程碑", "weight": 0.1, "good": ["团队", "执行", "里程碑"]},
        {"id": "R9", "name": "表达与材料", "weight": 0.1, "good": ["路演", "表达", "材料", "文档"]},
    ]
    diagnosis_rubric = diagnosis.get("rubric", []) if isinstance(diagnosis.get("rubric"), list) else []
    diagnosis_map = {str(item.get("item", "")): item for item in diagnosis_rubric if isinstance(item, dict)}
    diag_name_map = {
        "R1": "Problem Definition",
        "R2": "User Evidence Strength",
        "R3": "Solution Feasibility",
        "R4": "Business Model Consistency",
        "R5": "Market & Competition",
        "R6": "Financial Logic",
        "R7": "Innovation & Differentiation",
        "R8": "Team & Execution",
        "R9": "Presentation Quality",
    }
    results: list[dict] = []
    project_stage = _safe_str(diagnosis.get("project_stage", ""))
    for item in rubric_items:
        diag_item = diagnosis_map.get(diag_name_map[item["id"]], {})
        keyword_hits = sum(1 for kw in item["good"] if kw in raw_text)
        if diag_item:
            score = max(1.0, min(5.0, round(_safe_float(diag_item.get("score", 0)) / 2, 1)))
        else:
            penalty = 0.3 if len(triggered_rules) >= 3 else 0
            score = max(1.0, min(5.0, round(2.4 + keyword_hits * 0.5 - penalty, 1)))
        reason_bits = []
        if diag_item.get("reason"):
            reason_bits.append(_safe_str(diag_item.get("reason")))
        elif keyword_hits > 0:
            reason_bits.append(f"命中 {keyword_hits} 个与“{item['name']}”相关的关键词")
        else:
            reason_bits.append("该维度的直接表述偏少")
        if triggered_rules:
            reason_bits.append(f"当前提交触发 {len(triggered_rules)} 项风险规则")
        if evidence:
            reason_bits.append(f"可回溯证据 {min(len(evidence), 2)} 处")
        if project_stage:
            reason_bits.append(f"当前阶段：{project_stage}")
        revision_suggestion = (
            f"优先补强“{item['name']}”的具体论证，并补上可引用的学生原文或材料证据。"
            if not diag_item.get("status") == "ok"
            else f"该维度已初步成立，下一步应把“{item['name']}”从可讲清提升到可证明。"
        )
        # 构建 rationale，把分数从"黑盒结果"变成可追溯的公式
        if diag_item:
            base_val = round(_safe_float(diag_item.get("score", 0)) / 2, 1)
            formula_lines = [
                f"基准分：诊断 {diag_name_map[item['id']]} 原始分 {_safe_float(diag_item.get('score', 0)):.1f}/10",
                f"换算：{_safe_float(diag_item.get('score', 0)):.1f} ÷ 2 = {base_val:.1f}（映射到 0-5 分制）",
                f"裁剪：max(1.0, min(5.0, {base_val:.1f})) = {score}",
            ]
            formula = "clip(diag_dim_score / 2, 1, 5)"
            inputs = [
                {"label": "诊断原始分", "value": round(_safe_float(diag_item.get("score", 0)), 1)},
                {"label": "映射系数", "value": "÷ 2"},
                {"label": "关键词命中", "value": keyword_hits},
            ]
        else:
            penalty = 0.3 if len(triggered_rules) >= 3 else 0
            raw = 2.4 + keyword_hits * 0.5 - penalty
            formula_lines = [
                f"基准分：2.4（无诊断数据时的保底起点）",
                f"关键词命中：+{keyword_hits} × 0.5 = +{keyword_hits * 0.5:.1f}",
                f"规则惩罚：−{penalty:.1f}（触发 ≥3 条规则时扣 0.3）" if penalty else "规则惩罚：0（当前触发规则 < 3 条）",
                f"合计：2.4 + {keyword_hits * 0.5:.1f} − {penalty:.1f} = {raw:.1f}",
                f"裁剪：max(1.0, min(5.0, {raw:.1f})) = {score}",
            ]
            formula = "clip(2.4 + kw_hits*0.5 − penalty, 1, 5)"
            inputs = [
                {"label": "起点基准", "value": 2.4},
                {"label": "关键词命中", "value": keyword_hits, "impact": f"+{keyword_hits * 0.5:.1f}"},
                {"label": "规则惩罚", "value": penalty, "impact": f"−{penalty:.1f}"},
            ]
        contributing = [
            {"label": "命中关键词", "detail": "、".join(kw for kw in item["good"] if kw in raw_text) or "（无）"},
            {"label": "触发风险规则", "detail": f"{len(triggered_rules)} 条"},
            {"label": "可引用证据", "detail": f"{len(evidence)} 条"},
        ]
        rationale = {
            "field": f"rubric:{item['id']}",
            "value": score,
            "formula": formula,
            "formula_display": "\n".join(formula_lines),
            "inputs": inputs,
            "contributing_evidence": contributing,
            "note": f"满分 5 · 权重 {int(item['weight'] * 100)}% · 加权贡献 {round(score * item['weight'], 2)}",
        }
        results.append({
            "item_id": item["id"],
            "item_name": item["name"],
            "score": score,
            "max_score": 5,
            "weight": item["weight"],
            "reason": "；".join(reason_bits) + "。",
            "revision_suggestion": revision_suggestion,
            "evidence_quotes": [q.get("quote", "") for q in evidence[:2] if q.get("quote")],
            "rationale": rationale,
        })
    return results


def _build_revision_suggestions(
    diagnosis: dict,
    rubric_items: list[dict],
    latest_task: dict,
    evidence_chain: list[dict],
) -> list[str]:
    suggestions: list[str] = []
    for weakness in (diagnosis.get("weaknesses") or [])[:3]:
        if weakness:
            suggestions.append(f"针对“{_safe_str(weakness)}”补一段明确论证，并在正文中加上对应证据。")
    for item in rubric_items:
        if _safe_float(item.get("score", 0)) <= 3.2:
            suggestions.append(_safe_str(item.get("revision_suggestion", "")))
    if latest_task.get("description"):
        suggestions.append(f"按下一步任务推进：{_safe_str(latest_task.get('description', ''))}")
    if len(evidence_chain) < 2:
        suggestions.append("当前可引用证据不足，建议至少补充 2 处学生原文、访谈或文档片段。")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in suggestions:
        key = _safe_str(item)
        if key and key not in seen:
            seen.add(key)
            deduped.append(key)
    return deduped[:5]


def _coverage_ratio(projects: list[dict], blocked_rules: set[str], evidence_required: bool = False) -> float:
    if not projects:
        return 0.0
    covered = 0
    for proj in projects:
        risks = set(_normalize_rules((proj.get("latest_diagnosis") or {}).get("triggered_rules", [])) or proj.get("top_risks", []))
        has_evidence = len(proj.get("evidence_quotes") or []) >= 1 or len(proj.get("risk_evidence") or []) >= 1
        if risks.intersection(blocked_rules):
            continue
        if evidence_required and not has_evidence:
            continue
        covered += 1
    return round(covered / max(len(projects), 1) * 100, 1)


def _build_team_insight_payload(team_id: str) -> dict:
    team = team_store.get_team(team_id)
    if not team:
        return {"team_id": team_id, "error": "团队不存在"}

    students: list[dict] = []
    projects: list[dict] = []
    rule_frequency: dict[str, int] = {}
    for member in team.get("members", []):
        uid = _safe_str(member.get("user_id", ""))
        if not uid:
            continue
        info = user_store.get_by_id(uid) or {}
        stats = _aggregate_student_data(uid, include_detail=True)
        students.append({
            "student_id": uid,
            "display_name": info.get("display_name", uid[:8]),
            "avg_score": stats.get("avg_score", 0),
            "project_count": stats.get("project_count", 0),
        })
        for proj in (stats.get("projects") or []):
            projects.append({
                **proj,
                "student_id": uid,
                "student_name": info.get("display_name", uid[:8]),
            })
            for rule_id in _normalize_rules((proj.get("latest_diagnosis") or {}).get("triggered_rules", []) or proj.get("top_risks", [])):
                rule_frequency[rule_id] = rule_frequency.get(rule_id, 0) + 1

    total_projects = len(projects)
    avg_rubric_score = round(sum(_safe_float(p.get("latest_score", 0)) for p in projects) / max(total_projects, 1), 2)
    sorted_rules = sorted(rule_frequency.items(), key=lambda kv: kv[1], reverse=True)
    coverage_summary = [
        {"topic": "问题定义掌握率", "ratio": _coverage_ratio(projects, {"H1", "H5"})},
        {"topic": "证据验证掌握率", "ratio": _coverage_ratio(projects, {"H5", "H15"}, evidence_required=True)},
        {"topic": "商业建模掌握率", "ratio": _coverage_ratio(projects, {"H2", "H4", "H8"})},
        {"topic": "执行规划掌握率", "ratio": _coverage_ratio(projects, {"H10", "H12"})},
    ]
    top_mistakes = []
    for rule_id, count in sorted_rules[:5]:
        ratio = round(count / max(total_projects, 1) * 100, 1)
        exemplar = next((p for p in projects if rule_id in _normalize_rules((p.get("latest_diagnosis") or {}).get("triggered_rules", []) or p.get("top_risks", []))), None)
        top_mistakes.append({
            "rule_id": rule_id,
            "rule_name": get_rule_name(rule_id),
            "hit_count": count,
            "ratio": ratio,
            "summary": f"{ratio}% 的项目出现“{get_rule_name(rule_id)}”问题。",
            "project_name": exemplar.get("project_name", "") if exemplar else "",
            "student_name": exemplar.get("student_name", "") if exemplar else "",
        })
    high_risk_projects = sorted(
        [
            {
                "project_id": p.get("project_id", ""),
                "project_name": p.get("project_name", ""),
                "student_id": p.get("student_id", ""),
                "student_name": p.get("student_name", ""),
                "latest_score": p.get("latest_score", 0),
                "risk_count": len(p.get("top_risks", []) or []),
                "reason": p.get("current_summary") or ((p.get("latest_diagnosis") or {}).get("bottleneck", "")) or "需要老师重点复查。",
            }
            for p in projects
            if _safe_float(p.get("latest_score", 0)) < 6.5 or len(p.get("top_risks", []) or []) >= 2
        ],
        key=lambda row: (row["risk_count"], -_safe_float(row.get("latest_score", 0))),
        reverse=True,
    )[:6]
    suggested_interventions = []
    for item in top_mistakes[:3]:
        suggested_interventions.append({
            "title": f"围绕{item['rule_name']}安排专项教学",
            "plan": f"预警：{item['ratio']}% 的项目在“{item['rule_name']}”上存在共性问题。下周教学计划：1. 理论讲解该问题的判断标准；2. 展示一个正反案例对照；3. 要求所有团队补交对应证据或修正版画布。",
            "linked_rule_id": item["rule_id"],
        })
    return {
        "team_id": team_id,
        "team_name": team.get("team_name", ""),
        "coverage_summary": coverage_summary,
        "top_mistakes": top_mistakes,
        "high_risk_projects": high_risk_projects,
        "suggested_teaching_interventions": suggested_interventions,
        "statistics_json": {
            "total_projects": total_projects,
            "average_rubric_score": avg_rubric_score,
            "rule_trigger_frequency": {rule_id: count for rule_id, count in sorted_rules[:8]},
        },
    }


def _active_teacher_interventions(project_state: dict) -> list[dict]:
    items = list(project_state.get("teacher_interventions", []) or [])
    visible = [row for row in items if row.get("status") in {"sent", "viewed", "completed"}]
    visible.sort(key=lambda row: row.get("updated_at", row.get("created_at", "")), reverse=True)
    return visible


def _match_teacher_interventions(message: str, interventions: list[dict]) -> list[dict]:
    msg_terms = _topic_terms(message)
    ranked: list[tuple[int, dict]] = []
    for item in interventions:
        hay = " ".join([
            _safe_str(item.get("title", "")),
            _safe_str(item.get("reason_summary", "")),
            " ".join(_safe_str(x) for x in (item.get("action_items") or [])),
            " ".join(_safe_str(x) for x in (item.get("acceptance_criteria") or [])),
        ])
        overlap = len(msg_terms.intersection(_topic_terms(hay)))
        if overlap > 0:
            ranked.append((overlap, item))
    ranked.sort(key=lambda row: row[0], reverse=True)
    return [item for _, item in ranked[:2]]


def _build_teacher_runtime_context(project_state: dict, message: str) -> tuple[str, list[dict]]:
    teacher_fb = project_state.get("teacher_feedback", [])
    parts: list[str] = []
    if teacher_fb:
        latest = teacher_fb[-1]
        parts.append(f"最近一次教师反馈：{latest.get('comment', '')}\n关注点: {latest.get('focus_tags', [])}")
    active_interventions = _active_teacher_interventions(project_state)
    matched_interventions = _match_teacher_interventions(message, active_interventions)
    if matched_interventions:
        rendered = []
        for item in matched_interventions:
            rendered.append(
                "\n".join([
                    f"教师干预任务：{_safe_str(item.get('title', ''))}",
                    f"原因：{_safe_str(item.get('reason_summary', ''))}",
                    f"行动项：{'；'.join(_safe_str(x) for x in (item.get('action_items') or [])[:3])}",
                ])
            )
        parts.append("请优先遵循以下教师干预要求：\n" + "\n\n".join(rendered))
    return "\n\n".join(p for p in parts if p), matched_interventions


def _build_conversation_eval_payload(project_id: str, logical_project_id: str = "") -> dict:
    project_state = json_store.load_project(project_id)
    filtered_subs = [
        sub for sub in _project_submissions_by_logical_id(project_state, logical_project_id)
        if str(sub.get("source_type", "")).startswith("dialogue_turn")
    ]
    if not filtered_subs:
        return {"project_id": project_id, "logical_project_id": logical_project_id, "error": "该项目暂无可用于评估的多轮对话记录"}
    filtered_subs.sort(key=lambda row: row.get("created_at", ""))
    conversation_id = _safe_str(filtered_subs[-1].get("conversation_id", ""))
    if conversation_id:
        filtered_subs = [row for row in filtered_subs if row.get("conversation_id") == conversation_id]
    turns = filtered_subs[-9:]
    texts = [_safe_str(row.get("raw_text", "")) for row in turns if _safe_str(row.get("raw_text", ""))]
    if not texts:
        return {"project_id": project_id, "logical_project_id": logical_project_id, "error": "对话记录为空，无法生成过程评估"}

    all_text = "\n".join(texts)
    avg_score = round(sum(_safe_float((row.get("diagnosis", {}) if isinstance(row.get("diagnosis"), dict) else {}).get("overall_score", row.get("overall_score", 0))) for row in turns) / max(len(turns), 1), 2)
    rule_count = sum(len(_normalize_rules((row.get("diagnosis", {}) if isinstance(row.get("diagnosis"), dict) else {}).get("triggered_rules", []))) for row in turns)
    def _score_for(keywords: list[str], bonus: float = 0.0) -> float:
        hits = sum(1 for kw in keywords if kw in all_text.lower())
        base = 1.2 + min(hits, 4) * 0.8 + bonus
        if avg_score >= 7:
            base += 0.5
        elif avg_score < 5.5:
            base -= 0.3
        if rule_count >= 8:
            base -= 0.2
        return max(0.0, min(5.0, round(base, 1)))

    capability_scores = [
        {"dimension": "Empathy", "label": "痛点发现", "score": _score_for(["用户", "痛点", "需求", "场景", "访谈"], 0.2)},
        {"dimension": "Ideation", "label": "方案策划", "score": _score_for(["方案", "功能", "解决", "设计", "mvp"], 0.1)},
        {"dimension": "Business", "label": "商业建模", "score": _score_for(["商业模式", "盈利", "市场", "渠道", "定价", "tam", "ltv"], 0.0)},
        {"dimension": "Execution", "label": "资源杠杆", "score": _score_for(["执行", "里程碑", "团队", "资源", "落地"], 0.0)},
        {"dimension": "Logic", "label": "逻辑表达", "score": _score_for(["因为", "所以", "因此", "验证", "数据"], 0.1)},
    ]

    buckets = [turns[: max(1, math.ceil(len(turns) / 3))], turns[max(1, math.ceil(len(turns) / 3)): max(2, math.ceil(len(turns) * 2 / 3))], turns[max(2, math.ceil(len(turns) * 2 / 3)):]]
    round_titles = ["第一轮（核心价值探测）", "第二轮（逻辑压力测试）", "第三轮（落地可行性）"]
    round_reports = []
    for idx, bucket in enumerate(buckets):
        if not bucket:
            continue
        bucket_text = "\n".join(_safe_str(row.get("raw_text", "")) for row in bucket)
        latest = bucket[-1]
        diag = _safe_diagnosis(latest.get("diagnosis", {}))
        quote = re.sub(r"\s+", " ", _safe_str(latest.get("raw_text", ""))).strip()[:110]
        intent_mix: dict[str, int] = {}
        for row in bucket:
            intent = _normalize_intent(row.get("intent", ""), _safe_str(row.get("raw_text", "")))
            intent_mix[intent] = intent_mix.get(intent, 0) + 1
        dominant = max(intent_mix.items(), key=lambda kv: kv[1])[0] if intent_mix else "综合咨询"
        summary = diag.get("bottleneck") or _safe_str((latest.get("next_task") or {}).get("description", "")) or "该轮更多体现为老师可继续追问的探索状态。"
        round_reports.append({
            "round_index": idx + 1,
            "title": round_titles[idx],
            "dominant_intent": dominant,
            "summary": summary,
            "phase": _safe_str(latest.get("project_phase", "")) or "持续迭代",
            "quote": quote,
            "score": _safe_float(diag.get("overall_score", latest.get("overall_score", 0))),
            "risk_rules": _normalize_rules(diag.get("triggered_rules", []))[:3],
        })

    evidence_quotes = [
        {
            "created_at": row.get("created_at", ""),
            "quote": re.sub(r"\s+", " ", _safe_str(row.get("raw_text", ""))).strip()[:120],
            "phase": _safe_str(row.get("project_phase", "")) or "持续迭代",
        }
        for row in turns
        if _safe_str(row.get("raw_text", "")).strip()
    ][:5]

    return {
        "project_id": project_id,
        "logical_project_id": logical_project_id or _safe_str(turns[-1].get("logical_project_id", "")),
        "conversation_id": conversation_id,
        "turn_count": len(turns),
        "capability_scores": capability_scores,
        "round_reports": round_reports,
        "evidence_quotes": evidence_quotes,
        "overall_summary": f"该项目最近 {len(turns)} 轮对话平均分约为 {avg_score}，当前更主要暴露在“{round_reports[-1]['dominant_intent'] if round_reports else '综合咨询'}”相关的能力短板上。",
        "trace_summary": {
            "agents_called": [
                _safe_str(x)
                for x in ((turns[-1].get("agent_outputs", {}) if isinstance(turns[-1].get("agent_outputs"), dict) else {}).get("orchestration", {}) or {}).get("agents_called", [])[:8]
            ],
            "workflow_strategy": _safe_str((((turns[-1].get("agent_outputs", {}) if isinstance(turns[-1].get("agent_outputs"), dict) else {}).get("orchestration", {})) or {}).get("strategy", "")),
            "matched_teacher_interventions": [
                {
                    "title": _safe_str(item.get("title", "")),
                    "reason_summary": _safe_str(item.get("reason_summary", "")),
                }
                for item in (turns[-1].get("matched_teacher_interventions", []) or [])[:3]
                if isinstance(item, dict)
            ],
        },
    }


def _build_assessment_payload(project_id: str, logical_project_id: str = "") -> dict:
    project_state = json_store.load_project(project_id)
    filtered_subs = _project_submissions_by_logical_id(project_state, logical_project_id)
    if not filtered_subs:
        return {
            "project_id": project_id,
            "logical_project_id": logical_project_id,
            "error": "该项目暂无可用于批改的提交记录",
        }
    latest_sub = filtered_subs[-1]
    agent_summary = _safe_agent_summary(latest_sub)
    agent_meta = agent_summary.get("_meta", {}) if isinstance(agent_summary.get("_meta"), dict) else {}
    matched_teacher_interventions = [
        {
            "title": _safe_str(item.get("title", "")),
            "reason_summary": _safe_str(item.get("reason_summary", "")),
            "priority": _safe_str(item.get("priority", "")),
        }
        for item in (latest_sub.get("matched_teacher_interventions", []) or [])[:3]
        if isinstance(item, dict)
    ]
    diagnosis = _safe_diagnosis(latest_sub.get("diagnosis", {}))
    latest_task = latest_sub.get("next_task", {}) if isinstance(latest_sub.get("next_task"), dict) else {}
    evidence_chain = _assessment_evidence_chain(filtered_subs)
    rubric_items = _assessment_rubric(latest_sub)
    weighted_score = round(sum(float(item["score"]) * float(item["weight"]) for item in rubric_items), 2)
    overall_score = _safe_float(diagnosis.get("overall_score", latest_sub.get("overall_score", 0)))
    risk_level = _risk_level(overall_score, latest_sub.get("diagnosis", {}).get("triggered_rules", []) if isinstance(latest_sub.get("diagnosis"), dict) else [])
    reviews = project_state.get("teacher_assistant_reviews", []) or []
    current_review = None
    for item in reversed(reviews):
        if logical_project_id and item.get("logical_project_id") != logical_project_id:
            continue
        current_review = item
        break
    # Build quick 24h/72h layered plans from competition advisor + competition score helpers
    quick_plan_24h: list[dict] = []
    quick_plan_72h: list[dict] = []
    agent_outputs = latest_sub.get("agent_outputs", {}) if isinstance(latest_sub.get("agent_outputs"), dict) else {}
    comp_adv = agent_outputs.get("competition_advisor", {}) if isinstance(agent_outputs.get("competition_advisor"), dict) else {}
    rubric_advice = comp_adv.get("rubric_advice", []) if isinstance(comp_adv.get("rubric_advice"), list) else []
    for row in rubric_advice:
        if not isinstance(row, dict):
            continue
        item_name = _safe_str(row.get("item", ""))
        fix24 = _safe_str(row.get("minimal_fix_24h", ""))
        fix72 = _safe_str(row.get("minimal_fix_72h", ""))
        if fix24:
            quick_plan_24h.append({
                "source": "competition_advisor",
                "rubric_item": item_name,
                "title": f"补强 {item_name}",
                "description": fix24,
            })
        if fix72:
            quick_plan_72h.append({
                "source": "competition_advisor",
                "rubric_item": item_name,
                "title": f"深度优化 {item_name}",
                "description": fix72,
            })
    # Augment with generic quick fixes derived from competition-score helper
    try:
        comp_score = teacher_competition_score_predict(project_id)
    except Exception:
        comp_score = {}
    for text in (comp_score.get("quick_fixes_24h") or [])[:6]:
        quick_plan_24h.append({
            "source": "competition_score",
            "rubric_item": "",
            "title": _safe_str(text)[:40],
            "description": _safe_str(text),
        })
    for text in (comp_score.get("quick_fixes_72h") or [])[:8]:
        quick_plan_72h.append({
            "source": "competition_score",
            "rubric_item": "",
            "title": _safe_str(text)[:40],
            "description": _safe_str(text),
        })
    # Deduplicate by (title, description)
    def _dedup_plan(items: list[dict]) -> list[dict]:
        seen: set[tuple[str, str]] = set()
        out: list[dict] = []
        for it in items:
            key = (_safe_str(it.get("title", "")), _safe_str(it.get("description", "")))
            if not key[0] and not key[1]:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(it)
        return out[:10]

    quick_plan_24h = _dedup_plan(quick_plan_24h)
    quick_plan_72h = _dedup_plan(quick_plan_72h)
    return {
        "project_id": project_id,
        "logical_project_id": logical_project_id or _safe_str(latest_sub.get("logical_project_id") or latest_sub.get("project_id") or latest_sub.get("conversation_id", "")),
        "student_id": latest_sub.get("student_id", ""),
        "project_phase": _safe_str(latest_sub.get("project_phase", "")) or "持续迭代",
        "project_name": _project_label(logical_project_id or project_id, filtered_subs),
        "latest_submission_time": latest_sub.get("created_at", ""),
        "submission_count": len(filtered_subs),
        "overall_score": overall_score,
        "score_band": _review_score_band(overall_score),
        "risk_level": risk_level,
        "summary": _safe_str((latest_sub.get("kg_analysis") or {}).get("insight", "")) or _safe_str((latest_sub.get("hypergraph_insight") or {}).get("summary", "")) or diagnosis.get("bottleneck", ""),
        "diagnosis": diagnosis,
        "revision_suggestions": _build_revision_suggestions(diagnosis, rubric_items, latest_task, evidence_chain),
        "next_task": {
            "title": _safe_str(latest_task.get("title", "")),
            "description": _safe_str(latest_task.get("description", "")),
            "acceptance_criteria": [_safe_str(x) for x in (latest_task.get("acceptance_criteria") or [])[:5]],
        },
        "rubric_items": rubric_items,
        "overall_weighted_score": weighted_score,
        "evidence_chain": evidence_chain,
        "quick_plan_24h": quick_plan_24h,
        "quick_plan_72h": quick_plan_72h,
        "existing_review": current_review or {},
        "instructor_review_notes": _safe_str((current_review or {}).get("summary", "")),
        "workflow_trace": {
            "strategy": _safe_str(agent_meta.get("strategy", "")),
            "intent": _safe_str(agent_meta.get("intent", "")),
            "intent_shape": _safe_str(agent_meta.get("intent_shape", "")) or "single",
            "intent_reason": _safe_str(agent_meta.get("intent_reason", "")),
            "intent_confidence": float(agent_meta.get("intent_confidence", 0) or 0),
            "agents_called": [_safe_str(x) for x in (agent_meta.get("agents_called") or [])[:8]],
            "resolved_agents": [_safe_str(x) for x in (agent_meta.get("resolved_agents") or [])[:8]],
            "agent_reasoning": _safe_str(agent_meta.get("agent_reasoning", "")),
            "pipeline": [_safe_str(x) for x in (agent_meta.get("pipeline") or [])[:6]],
            "matched_teacher_interventions": matched_teacher_interventions,
        },
    }


def _derive_intervention_hint(student: dict) -> dict:
    intents = student.get("intent_distribution", {}) or {}
    dominant = max(intents.items(), key=lambda kv: kv[1])[0] if intents else "综合咨询"
    phase = _safe_str(student.get("latest_phase", "")) or "持续迭代"
    suggestion = student.get("teacher_intervention") or f"围绕“{dominant}”做一次针对性辅导。"
    return {
        "dominant_intent": dominant,
        "phase": phase,
        "suggestion": suggestion,
    }


def _collect_team_interventions(team_id: str) -> list[dict]:
    team = team_store.get_team(team_id)
    if not team:
        return []
    interventions: list[dict] = []
    seen: set[str] = set()
    for member in team.get("members", []):
        uid = _safe_str(member.get("user_id", ""))
        if not uid:
            continue
        data = json_store.load_project(f"project-{uid}")
        for item in (data.get("teacher_interventions") or []):
            iid = _safe_str(item.get("intervention_id", ""))
            if not iid or iid in seen:
                continue
            if item.get("scope_type") == "team" and item.get("scope_id") == team_id:
                interventions.append(item)
                seen.add(iid)
            elif item.get("target_student_id") == uid:
                interventions.append(item)
                seen.add(iid)
    interventions.sort(key=lambda row: row.get("updated_at", row.get("created_at", "")), reverse=True)
    return interventions


def _build_team_intervention_payload(team_id: str, teacher_id: str = "") -> dict:
    team = team_store.get_team(team_id)
    if not team:
        return {"team_id": team_id, "error": "团队不存在"}
    students = []
    all_rules: dict[str, int] = {}
    for member in team.get("members", []):
        uid = _safe_str(member.get("user_id", ""))
        if not uid:
            continue
        info = user_store.get_by_id(uid) or {}
        stats = _aggregate_student_data(uid, include_detail=True)
        hint = _derive_intervention_hint(stats)
        for proj in (stats.get("projects") or []):
            for risk in (proj.get("top_risks") or []):
                key = _safe_str(risk)
                if key:
                    all_rules[key] = all_rules.get(key, 0) + 1
        students.append({
            "student_id": uid,
            "display_name": info.get("display_name", uid[:8]),
            "avg_score": stats.get("avg_score", 0),
            "risk_count": stats.get("risk_count", 0),
            "latest_phase": stats.get("latest_phase", ""),
            "intent_distribution": stats.get("intent_distribution", {}),
            "student_case_summary": stats.get("student_case_summary", ""),
            "teacher_intervention": hint["suggestion"],
            "dominant_intent": hint["dominant_intent"],
            "projects": (stats.get("projects") or [])[:5],
        })
    shared_problems = [
        {
            "rule_id": rule_id,
            "name": get_rule_name(rule_id),
            "hit_count": count,
            "priority": "高" if count >= 3 else "中",
        }
        for rule_id, count in sorted(all_rules.items(), key=lambda kv: kv[1], reverse=True)[:5]
    ]
    suggested_plans = []
    for item in shared_problems[:3]:
        suggested_plans.append({
            "title": f"围绕{item['name']}安排专项干预",
            "reason_summary": f"{item['name']}在团队内出现 {item['hit_count']} 次，适合做集中讲解与案例纠偏。",
            "action_items": [
                "老师用 10 分钟说明问题本质",
                "展示一个正反案例对照",
                "要求学生按模板补齐关键证据",
            ],
            "acceptance_criteria": [
                "学生能说清楚问题与目标用户",
                "项目文档补齐对应证据",
                "下一轮提交中该风险显著减少",
            ],
        })
    return {
        "team_id": team_id,
        "team_name": team.get("team_name", ""),
        "teacher_id": teacher_id or team.get("teacher_id", ""),
        "students": students,
        "shared_problems": shared_problems,
        "suggested_plans": suggested_plans,
        "existing_interventions": _collect_team_interventions(team_id),
        "team_insight": _build_team_insight_payload(team_id),
    }


def _target_projects_for_intervention(payload: TeacherAssistantInterventionPayload) -> list[dict]:
    targets: list[dict] = []
    if payload.scope_type == "team":
        team = team_store.get_team(payload.scope_id)
        if not team:
            return targets
        for member in team.get("members", []):
            uid = _safe_str(member.get("user_id", ""))
            if uid:
                targets.append({
                    "project_id": f"project-{uid}",
                    "student_id": uid,
                })
    elif payload.scope_type == "student":
        student_id = _safe_str(payload.target_student_id or payload.scope_id)
        if student_id:
            targets.append({
                "project_id": f"project-{student_id}",
                "student_id": student_id,
            })
    else:
        student_id = _safe_str(payload.target_student_id or "")
        project_id = _safe_str(payload.project_id or payload.scope_id)
        if project_id:
            targets.append({
                "project_id": project_id,
                "student_id": student_id,
            })
    return targets


def get_rule_name(rule_id: str) -> str:
    mapping = {
        "H1": "客户与价值错位",
        "H2": "渠道不可达",
        "H3": "支付意愿证据不足",
        "H4": "市场规模口径混乱",
        "H5": "需求证据不足",
        "H6": "竞品对比不可比",
        "H7": "创新点不可验证",
        "H8": "单位经济不成立",
        "H9": "增长逻辑跳跃",
        "H10": "里程碑不可交付",
        "H11": "合规缺口",
        "H12": "技术路线与资源不匹配",
        "H13": "实验设计不合格",
        "H14": "路演叙事断裂",
        "H15": "评分证据覆盖不足",
    }
    return mapping.get(rule_id, rule_id)


def _build_teacher_assistant_dashboard(teacher_id: str) -> dict:
    teams = team_store.list_by_teacher(teacher_id)
    pending_assessments: list[dict] = []
    pending_interventions: list[dict] = []
    followups: list[dict] = []
    shared_focus: list[dict] = []
    for team in teams:
        inter_payload = _build_team_intervention_payload(team.get("team_id", ""), teacher_id)
        for problem in (inter_payload.get("shared_problems") or [])[:2]:
            shared_focus.append({
                "team_id": team.get("team_id", ""),
                "team_name": team.get("team_name", ""),
                **problem,
            })
        for stu in inter_payload.get("students", []):
            student_id = _safe_str(stu.get("student_id", ""))
            root_project_id = f"project-{student_id}"
            project_state = json_store.load_project(root_project_id)
            reviews = project_state.get("teacher_assistant_reviews", []) or []
            reviewed_ids = {item.get("logical_project_id") for item in reviews if item.get("status") in {"approved", "sent"}}
            for proj in (stu.get("projects") or [])[:4]:
                lp = _safe_str(proj.get("project_id", ""))
                if lp in reviewed_ids:
                    continue
                pending_assessments.append({
                    "project_id": root_project_id,
                    "logical_project_id": lp,
                    "project_name": proj.get("project_name", ""),
                    "student_id": student_id,
                    "student_name": stu.get("display_name", ""),
                    "team_id": team.get("team_id", ""),
                    "team_name": team.get("team_name", ""),
                    "latest_score": proj.get("latest_score", 0),
                    "project_phase": proj.get("project_phase", ""),
                    "top_risks": proj.get("top_risks", []),
                    "current_summary": proj.get("current_summary", ""),
                })
            for intervention in (project_state.get("teacher_interventions") or []):
                if intervention.get("teacher_id") != teacher_id:
                    continue
                status = intervention.get("status", "")
                if status in {"draft", "approved"}:
                    pending_interventions.append({
                        **intervention,
                        "student_name": stu.get("display_name", ""),
                        "team_name": team.get("team_name", ""),
                    })
                if status in {"sent", "viewed"}:
                    followups.append({
                        **intervention,
                        "student_name": stu.get("display_name", ""),
                        "team_name": team.get("team_name", ""),
                    })
    pending_assessments.sort(key=lambda row: (len(row.get("top_risks", [])), -_safe_float(row.get("latest_score", 0))), reverse=True)
    pending_interventions.sort(key=lambda row: row.get("updated_at", row.get("created_at", "")), reverse=True)
    followups.sort(key=lambda row: row.get("updated_at", row.get("created_at", "")), reverse=True)
    shared_focus.sort(key=lambda row: row.get("hit_count", 0), reverse=True)
    return {
        "teacher_id": teacher_id,
        "team_count": len(teams),
        "pending_assessments": pending_assessments[:8],
        "pending_interventions": pending_interventions[:8],
        "followups": followups[:8],
        "shared_focus": shared_focus[:6],
    }


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
    rubric_scores = _assessment_rubric(latest_sub)
    overall_weighted_score = round(sum(_safe_float(item.get("score")) * _safe_float(item.get("weight")) for item in rubric_scores), 2)
    
    return {
        "project_id": project_id,
        "student_id": latest_sub.get("student_id", ""),
        "evaluation_time": datetime.utcnow().isoformat(),
        "rubric_items": rubric_scores,
        "overall_weighted_score": round(overall_weighted_score, 2),
        "max_weighted_score": 5.0,
        "score_band": diagnosis.get("score_band", ""),
        "project_stage": diagnosis.get("project_stage", ""),
        "grading_principles": diagnosis.get("grading_principles", []),
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
    high_risk = sum(1 for r in triggered_rules if isinstance(r, dict) and r.get("severity") == "high")
    medium_risk = sum(1 for r in triggered_rules if isinstance(r, dict) and r.get("severity") == "medium")
    project_stage = _safe_str(diagnosis.get("project_stage", ""))
    stage_bonus = {"idea": -6, "structured": 0, "validated": 5, "document": 8}.get(project_stage, 0)

    # 竞赛预测评分：强调证据链和成熟度，避免过高或过低
    competition_score = overall_score * 8.0 + 20 + stage_bonus - high_risk * 4.0 - medium_risk * 1.5
    if overall_score > 0:
        competition_score = max(35, competition_score)
    competition_score = min(95, max(0, competition_score))
    
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


@app.get("/api/teacher/project/{project_id}/evidence-trace")
def teacher_project_evidence_trace(project_id: str, logical_project_id: str = "") -> dict:
    """证据链追溯视图：按项目聚合最近提交的证据片段与规则/评分维度关联。

    该接口在 `_build_assessment_payload` 的 evidence_chain 基础上，补充
    submission_id、rubric_items、rule_ids 等上下文，供前端追溯到材料与规则。
    """
    project_state = json_store.load_project(project_id)
    filtered_subs = _project_submissions_by_logical_id(project_state, logical_project_id)
    if not filtered_subs:
        return {
            "project_id": project_id,
            "logical_project_id": logical_project_id,
            "error": "该项目暂无可用于证据溯源的提交记录",
        }
    evidence_chain = _assessment_evidence_chain(filtered_subs)
    # 计算每条Rubric的证据数量与风险规则聚合
    rubric_stats: dict[str, dict] = {}
    rule_stats: dict[str, dict] = {}
    for row in evidence_chain:
        rubric_items = row.get("rubric_items") or []
        rule_ids = row.get("rule_ids") or ([] if not row.get("risk_id") else [row.get("risk_id")])
        for rid in rule_ids:
            rid_s = _safe_str(rid).upper()
            if not rid_s:
                continue
            bucket = rule_stats.setdefault(
                rid_s,
                {
                    "rule_id": rid_s,
                    "rule_name": get_rule_name(rid_s),
                    "fallacy": RULE_FALLACY_MAP.get(rid_s, ""),
                    "edge_families": RULE_EDGE_MAP.get(rid_s, []),
                    "hit_count": 0,
                },
            )
            bucket["hit_count"] += 1
        for item in rubric_items:
            name = _safe_str(item)
            if not name:
                continue
            b = rubric_stats.setdefault(
                name,
                {
                    "rubric_item": name,
                    "evidence_count": 0,
                    "rule_ids": set(),
                },
            )
            b["evidence_count"] += 1
            for rid in rule_ids:
                if not rid:
                    continue
                b["rule_ids"].add(_safe_str(rid).upper())
    rubric_rows = []
    for name, b in rubric_stats.items():
        rule_list = sorted(list(b.get("rule_ids", set())))
        rubric_rows.append(
            {
                "rubric_item": name,
                "evidence_count": int(b.get("evidence_count", 0) or 0),
                "rule_ids": rule_list,
            }
        )
    rubric_rows.sort(key=lambda r: (-int(r["evidence_count"]), r["rubric_item"]))
    rule_rows = sorted(
        rule_stats.values(),
        key=lambda r: (-int(r.get("hit_count", 0) or 0), r["rule_id"]),
    )
    return {
        "project_id": project_id,
        "logical_project_id": logical_project_id,
        "evidence_chain": evidence_chain,
        "rubric_summary": rubric_rows,
        "rule_summary": rule_rows,
    }


@app.get("/api/teacher/project/{project_id}/rule-dashboard")
def teacher_project_rule_dashboard(project_id: str, logical_project_id: str = "") -> dict:
    """规则触发雷达 & 红线看板（项目级）。

    聚合指定项目/逻辑项目下所有提交中的规则触发情况，输出：
    - radar: H 规则在该项目中的触发频度（0-10）
    - timeline: 按时间的规则命中时间线
    - summary: 每条规则的谬误名称、超图族等
    """
    project_state = json_store.load_project(project_id)
    submissions = _project_submissions_by_logical_id(project_state, logical_project_id)
    if not submissions:
        return {
            "project_id": project_id,
            "logical_project_id": logical_project_id,
            "error": "该项目暂无可用于规则分析的提交记录",
        }
    submissions_sorted = sorted(submissions, key=lambda row: _safe_str(row.get("created_at", "")))
    rule_counts: dict[str, int] = {}
    timeline: list[dict] = []
    for sub in submissions_sorted:
        created_at = _safe_str(sub.get("created_at", ""))
        diag = sub.get("diagnosis", {}) if isinstance(sub.get("diagnosis"), dict) else {}
        triggered_raw = diag.get("triggered_rules", []) or sub.get("triggered_rules", []) or []
        rule_ids = _normalize_rules(triggered_raw)
        unique_rules = set(rid.upper() for rid in rule_ids if rid)
        if unique_rules:
            timeline.append({
                "created_at": created_at,
                "project_phase": _safe_str(sub.get("project_phase", "")),
                "rule_ids": sorted(unique_rules),
            })
        for rid in unique_rules:
            rule_counts[rid] = rule_counts.get(rid, 0) + 1
    if not rule_counts:
        return {
            "project_id": project_id,
            "logical_project_id": logical_project_id,
            "radar": [],
            "timeline": timeline,
            "rules": [],
        }
    max_hits = max(rule_counts.values()) or 1
    radar = []
    summary_rows = []
    for rid, count in sorted(rule_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        rid_u = _safe_str(rid).upper()
        severity = "high" if count >= 4 else "medium" if count >= 2 else "low"
        radar.append({
            "rule": rid_u,
            "label": get_rule_name(rid_u),
            "value": round((count / max_hits) * 10, 2),
            "raw_hits": count,
            "severity": severity,
        })
        summary_rows.append({
            "rule_id": rid_u,
            "rule_name": get_rule_name(rid_u),
            "fallacy": RULE_FALLACY_MAP.get(rid_u, ""),
            "edge_families": RULE_EDGE_MAP.get(rid_u, []),
            "hit_count": count,
            "severity": severity,
        })
    return {
        "project_id": project_id,
        "logical_project_id": logical_project_id,
        "radar": radar,
        "timeline": timeline,
        "rules": summary_rows,
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
        "shared_problems": shared_problems[:5],
        "recommended_next_class_focus": "针对Top 2-3的共性问题设计专项讲解与练习",
    }


# ═══════════════════════════════════════════════════════════════════════
#  Chat — Contacts (auto-aggregate teammates + teachers)
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/chat/contacts")
def chat_contacts(user_id: str = "") -> dict:
    if not user_id:
        raise HTTPException(400, "需要 user_id")
    seen: set[str] = {user_id}
    contacts: list[dict] = []
    my_teams_member = team_store.list_by_member(user_id)
    my_teams_teacher = team_store.list_by_teacher(user_id)
    seen_team_ids: set[str] = set()
    my_teams: list[dict] = []
    for t in my_teams_member + my_teams_teacher:
        tid = t.get("team_id", "")
        if tid not in seen_team_ids:
            seen_team_ids.add(tid)
            my_teams.append(t)
    team_infos: list[dict] = []
    for t in my_teams:
        tid = t.get("team_id", "")
        tname = _safe_str(t.get("team_name", ""))
        members_info: list[dict] = []
        for m_entry in t.get("members", []):
            mid = m_entry.get("user_id", "") if isinstance(m_entry, dict) else str(m_entry)
            if not mid:
                continue
            u = user_store.get_by_id(mid)
            if u:
                members_info.append({"user_id": mid, "display_name": _safe_str(u.get("display_name", "")), "role": u.get("role", "student")})
                if mid not in seen:
                    seen.add(mid)
                    contacts.append({"user_id": mid, "display_name": _safe_str(u.get("display_name", "")), "role": u.get("role", "student"), "source": "team", "team_name": tname})
        teacher_id = t.get("teacher_id", "")
        if teacher_id and teacher_id not in seen:
            tu = user_store.get_by_id(teacher_id)
            if tu:
                seen.add(teacher_id)
                contacts.append({"user_id": teacher_id, "display_name": _safe_str(tu.get("display_name", "")), "role": "teacher", "source": "teacher"})
                members_info.append({"user_id": teacher_id, "display_name": _safe_str(tu.get("display_name", "")), "role": "teacher"})
        team_infos.append({"team_id": tid, "team_name": tname, "members": members_info})
    current_user = user_store.get_by_id(user_id)
    current_role = (current_user or {}).get("role", "student")
    if current_role != "teacher":
        all_teachers = user_store.list_users(role="teacher")
        for tc in all_teachers:
            tcid = tc.get("user_id", "")
            if tcid and tcid not in seen:
                seen.add(tcid)
                contacts.append({"user_id": tcid, "display_name": _safe_str(tc.get("display_name", "")), "role": "teacher", "source": "teacher"})
    else:
        all_students = user_store.list_users(role="student")
        for st in all_students:
            stid = st.get("user_id", "")
            if stid and stid not in seen:
                seen.add(stid)
                contacts.append({"user_id": stid, "display_name": _safe_str(st.get("display_name", "")), "role": "student", "source": "student"})
    contacts.append({"user_id": "ai_xiaowen", "display_name": "小文 AI", "role": "ai", "source": "system"})
    return {"contacts": contacts, "teams": team_infos}


# ═══════════════════════════════════════════════════════════════════════
#  Chat Room — REST API + WebSocket
# ═══════════════════════════════════════════════════════════════════════

@app.post("/api/chat/rooms")
def chat_create_room(payload: ChatRoomCreatePayload) -> dict:
    room = chat_store.create_room(
        name=payload.name,
        room_type=payload.room_type,
        members=payload.members,
        admin_ids=payload.admin_ids or None,
        team_id=payload.team_id,
        project_id=payload.project_id,
    )
    return {"status": "ok", "room": room}


@app.get("/api/chat/rooms")
def chat_list_rooms(user_id: str = "") -> dict:
    if not user_id:
        raise HTTPException(400, "需要 user_id")
    rooms = chat_store.list_rooms_for_user(user_id)
    rooms.sort(key=lambda r: r.get("last_message_at") or r.get("created_at") or "", reverse=True)
    return {"rooms": rooms}


@app.get("/api/chat/rooms/{room_id}")
def chat_get_room(room_id: str) -> dict:
    room = chat_store.get_room(room_id)
    if not room:
        raise HTTPException(404, "聊天室不存在")
    return {"room": room}


@app.delete("/api/chat/rooms/{room_id}")
def chat_delete_room(room_id: str) -> dict:
    ok = chat_store.delete_room(room_id)
    if not ok:
        raise HTTPException(404, "聊天室不存在")
    return {"status": "ok"}


@app.post("/api/chat/rooms/{room_id}/members")
def chat_add_member(room_id: str, payload: ChatRoomAddMemberPayload) -> dict:
    room = chat_store.add_member(room_id, payload.user_id)
    if not room:
        raise HTTPException(404, "聊天室不存在")
    return {"status": "ok", "room": room}


@app.delete("/api/chat/rooms/{room_id}/members/{user_id}")
def chat_remove_member(room_id: str, user_id: str) -> dict:
    room = chat_store.remove_member(room_id, user_id)
    if not room:
        raise HTTPException(404, "聊天室不存在")
    return {"status": "ok", "room": room}


@app.get("/api/chat/rooms/{room_id}/messages")
def chat_get_messages(room_id: str, limit: int = 50, before: str = "") -> dict:
    msgs = chat_store.get_messages(room_id, limit=limit, before=before or None)
    return {"messages": msgs}


@app.post("/api/chat/rooms/{room_id}/messages")
def chat_send_message(room_id: str, payload: ChatMessageSendPayload) -> dict:
    room = chat_store.get_room(room_id)
    if not room:
        raise HTTPException(404, "聊天室不存在")
    msg = chat_store.add_message(
        room_id=room_id,
        sender_id=payload.sender_id,
        sender_name=payload.sender_name,
        msg_type=payload.msg_type,
        content=payload.content,
        mentions=payload.mentions,
        reply_to=payload.reply_to,
    )
    _broadcast_to_room(room_id, {"type": "new_message", "message": msg})
    should_trigger_ai = (
        "ai_xiaowen" in (payload.mentions or [])
        or "@小文" in payload.content
        or "ai_xiaowen" in room.get("members", [])
    )
    if should_trigger_ai:
        import threading
        threading.Thread(
            target=_handle_xiaowen_mention,
            args=(room_id, room.get("project_id"), payload.content, payload.sender_name),
            daemon=True,
        ).start()
    return {"status": "ok", "message": msg}


@app.post("/api/chat/rooms/{room_id}/reactions")
def chat_toggle_reaction(room_id: str, payload: ChatReactionPayload) -> dict:
    msg_id = ""
    return {"status": "ok"}


@app.post("/api/chat/rooms/{room_id}/files")
async def chat_upload_file(
    room_id: str,
    sender_id: str = Form(""),
    sender_name: str = Form(""),
    file: UploadFile = File(...),
) -> dict:
    room = chat_store.get_room(room_id)
    if not room:
        raise HTTPException(404, "聊天室不存在")
    room_dir = chat_files_root / room_id
    room_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid4().hex[:8]}_{file.filename}"
    target = room_dir / safe_name
    content = await file.read()
    target.write_bytes(content)

    file_meta = {
        "filename": file.filename,
        "stored_name": safe_name,
        "size": len(content),
        "content_type": file.content_type or "",
        "url": f"/chat_files/{room_id}/{safe_name}",
    }
    is_image = (file.content_type or "").startswith("image/")
    msg = chat_store.add_message(
        room_id=room_id,
        sender_id=sender_id,
        sender_name=sender_name,
        msg_type="image" if is_image else "file",
        content=file.filename or "文件",
        file_meta=file_meta,
    )
    _broadcast_to_room(room_id, {"type": "new_message", "message": msg})
    return {"status": "ok", "message": msg}


@app.get("/api/chat/rooms/{room_id}/files")
def chat_list_files(room_id: str) -> dict:
    files = chat_store.list_files(room_id)
    return {"files": files}


@app.get("/api/chat/rooms/{room_id}/ai-history")
def chat_ai_history(room_id: str) -> dict:
    """Return persisted AI analysis entries for the shared AI panel."""
    entries = chat_store.get_ai_analyses(room_id)
    return {"entries": entries}


@app.delete("/api/chat/rooms/{room_id}/ai-history/{entry_id}")
def chat_delete_ai_entry(room_id: str, entry_id: str) -> dict:
    ok = chat_store.delete_ai_analysis(room_id, entry_id)
    return {"ok": ok}


def _broadcast_to_room(room_id: str, data: dict) -> None:
    """Thread-safe broadcast to all WebSocket connections in a room."""
    import asyncio
    conns = _ws_rooms.get(room_id, {})
    if not conns:
        return
    payload = json.dumps(data, ensure_ascii=False)

    async def _send_all():
        for uid, ws in list(conns.items()):
            try:
                await ws.send_text(payload)
            except Exception:
                conns.pop(uid, None)

    loop = _main_loop
    if loop is None:
        logger.warning("_broadcast_to_room: _main_loop not set yet, skipping")
        return

    try:
        asyncio.get_running_loop()
        # We're inside the event loop thread (async endpoint) — just schedule
        asyncio.ensure_future(_send_all())
    except RuntimeError:
        # We're in a background / threadpool thread — schedule and wait
        try:
            future = asyncio.run_coroutine_threadsafe(_send_all(), loop)
            future.result(timeout=8)
        except Exception as exc:
            logger.warning(f"_broadcast_to_room thread-safe send error: {exc}")


_DEEP_KEYWORDS = frozenset([
    "深度分析", "深度", "项目诊断", "竞品分析", "商业模式", "打分", "评分",
    "SWOT", "市场分析", "盈利模式", "技术方案", "融资", "BP", "路演",
    "痛点分析", "用户画像", "MVP", "竞争壁垒", "差异化",
])


def _classify_xiaowen_intent(query: str, history_ctx: str) -> str:
    """Decide shallow vs deep mode. Returns 'shallow' or 'deep'."""
    q_lower = query.lower()
    if any(kw in q_lower for kw in _DEEP_KEYWORDS):
        return "deep"
    if len(query) < 30 and not any(kw in q_lower for kw in ("项目", "创业", "比赛", "产品", "方案")):
        return "shallow"
    if not composer_llm.enabled:
        return "shallow"
    try:
        result = composer_llm.chat_json(
            system_prompt=(
                "你是意图分类器。判断用户消息需要浅层回复还是深层项目分析。\n"
                "浅层(shallow)：闲聊、翻译、总结讨论、整理资料、写纪要、简单问答等。\n"
                "深层(deep)：涉及项目诊断、竞品分析、商业模式设计、打分评估、"
                "市场分析、技术方案评审、创业建议等需要多维度深入分析的问题。\n"
                "只返回JSON：{\"mode\": \"shallow\"} 或 {\"mode\": \"deep\"}"
            ),
            user_prompt=f"聊天上下文：\n{history_ctx[-500:]}\n\n用户消息：{query[:300]}",
            model=settings.llm_fast_model,
            temperature=0.0,
        )
        return result.get("mode", "shallow") if result.get("mode") in ("shallow", "deep") else "shallow"
    except Exception:
        return "shallow"


def _handle_xiaowen_mention(room_id: str, project_id: str | None, content: str, sender_name: str) -> None:
    """Dual-mode AI: shallow (direct LLM) or deep (full multi-agent workflow).
    Reads full conversation context, broadcasts structured ai_analysis to all members."""
    try:
        query = content.replace("@小文", "").replace("@xiaowen", "").strip()
        if not query:
            query = "你好，请问有什么可以帮助你的？"

        # ── Build rich conversation context from last 30 messages ──
        recent_msgs = chat_store.get_messages(room_id, limit=30)
        history_lines = []
        conv_messages = []
        for m in recent_msgs:
            mtype = m.get("type", "")
            if mtype in ("text", "ai_reply"):
                is_ai = m.get("sender_id") == "ai_xiaowen"
                name = "小文" if is_ai else m.get("sender_name", "用户")
                text = m.get("content", "")[:500]
                history_lines.append(f"{name}: {text}")
                conv_messages.append({
                    "role": "assistant" if is_ai else "user",
                    "content": text,
                })
        history_ctx = "\n".join(history_lines[-20:])

        mode = _classify_xiaowen_intent(query, history_ctx)
        logger.info(f"@小文 intent classified as: {mode} for query: {query[:80]}")

        thinking_text = "小文正在思考..." if mode == "shallow" else "小文正在深度分析（可能需要 30 秒）..."
        thinking_msg = chat_store.add_message(
            room_id=room_id,
            sender_id="ai_xiaowen",
            sender_name="小文",
            msg_type="system",
            content=thinking_text,
        )
        _broadcast_to_room(room_id, {"type": "new_message", "message": thinking_msg})

        reply_text = ""

        if mode == "deep":
            try:
                from app.services.graph_workflow import run_workflow
                result = run_workflow(
                    message=query,
                    mode="coursework",
                    history_context=history_ctx,
                    conversation_messages=conv_messages[-10:],
                )
                reply_text = result.get("assistant_message", "")
                if not reply_text or len(reply_text.strip()) < 10:
                    coach = result.get("coach_output", {})
                    analyst = result.get("analyst_output", {})
                    parts = []
                    if isinstance(coach, dict) and coach.get("reply"):
                        parts.append(coach["reply"])
                    if isinstance(analyst, dict) and analyst.get("reply"):
                        parts.append(analyst["reply"])
                    if parts:
                        reply_text = "\n\n".join(parts)
            except Exception as e:
                logger.error(f"@小文 deep mode failed, falling back to shallow: {e}")
                mode = "shallow"

        if mode == "shallow" or not reply_text or len(reply_text.strip()) < 5:
            logger.info("@小文 shallow path, llm_enabled=%s", composer_llm.enabled)
            system_prompt = (
                "你是「小文」，一个轻量级办公助手，服务于大学生创新创业项目团队的聊天群。\n"
                "你能看到群里所有人的完整对话，请基于对话内容给出有用的回复。\n"
                "你的核心能力：回答问题、翻译内容、总结讨论、整理资料、给出简洁建议。\n"
                "风格要求：友好、简洁、有条理。不要长篇大论，直接给出有用的回答。\n"
                "以下是聊天群的最近对话内容：\n"
                f"{history_ctx}\n"
            )
            if composer_llm.enabled:
                try:
                    reply_text = composer_llm.chat_text(
                        system_prompt=system_prompt,
                        user_prompt=f"{sender_name} 说: {query}",
                        temperature=0.5,
                    )
                    logger.info("@小文 shallow LLM returned %d chars", len(reply_text))
                except Exception as llm_err:
                    logger.error("@小文 shallow LLM exception: %s", llm_err)
                    reply_text = ""
            else:
                reply_text = f"收到你的消息：「{query[:50]}」。目前 AI 服务未启用，请联系管理员。"

        if not reply_text or len(reply_text.strip()) < 2:
            reply_text = "我暂时没有更多建议，你可以再详细描述一下。"

        ai_msg = chat_store.add_message(
            room_id=room_id,
            sender_id="ai_xiaowen",
            sender_name="小文",
            msg_type="ai_reply",
            content=reply_text,
        )
        _broadcast_to_room(room_id, {"type": "new_message", "message": ai_msg})

        # ── Broadcast + persist structured AI analysis for shared panel ──
        analysis_entry = {
            "id": ai_msg["msg_id"],
            "query": query[:200],
            "reply": reply_text,
            "mode": mode,
            "sender": sender_name,
            "time": ai_msg["created_at"],
        }
        chat_store.save_ai_analysis(room_id, analysis_entry)
        _broadcast_to_room(room_id, {"type": "ai_analysis", "entry": analysis_entry})

    except Exception as e:
        logger.error(f"@小文 AI reply failed: {e}")
        err_msg = chat_store.add_message(
            room_id=room_id,
            sender_id="ai_xiaowen",
            sender_name="小文",
            msg_type="ai_reply",
            content="抱歉，我暂时无法回复，请稍后再试。",
        )
        _broadcast_to_room(room_id, {"type": "new_message", "message": err_msg})


@app.websocket("/ws/chat/{room_id}")
async def chat_websocket(websocket: WebSocket, room_id: str, user_id: str = "", user_name: str = ""):
    import asyncio as _aio
    global _main_loop
    if _main_loop is None:
        _main_loop = _aio.get_running_loop()
    await websocket.accept()
    if room_id not in _ws_rooms:
        _ws_rooms[room_id] = {}
    _ws_rooms[room_id][user_id] = websocket

    for uid, ws in list(_ws_rooms[room_id].items()):
        if uid != user_id:
            try:
                await ws.send_text(json.dumps({
                    "type": "user_joined", "user_id": user_id, "user_name": user_name
                }, ensure_ascii=False))
            except Exception:
                _ws_rooms[room_id].pop(uid, None)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
            except Exception:
                continue

            msg_type = payload.get("type", "text")

            if msg_type in ("video_offer", "video_answer", "ice_candidate", "video_hang_up"):
                target = payload.get("target_user")
                if target and target in _ws_rooms.get(room_id, {}):
                    try:
                        await _ws_rooms[room_id][target].send_text(json.dumps({
                            **payload, "from_user": user_id, "from_name": user_name,
                        }, ensure_ascii=False))
                    except Exception:
                        pass
                continue

            if msg_type == "reaction":
                msg_id = payload.get("msg_id", "")
                emoji = payload.get("emoji", "")
                if msg_id and emoji:
                    updated = chat_store.add_reaction(room_id, msg_id, user_id, emoji)
                    if updated:
                        for uid2, ws2 in list(_ws_rooms.get(room_id, {}).items()):
                            try:
                                await ws2.send_text(json.dumps({
                                    "type": "reaction_update", "msg_id": msg_id,
                                    "reactions": updated.get("reactions", {}),
                                }, ensure_ascii=False))
                            except Exception:
                                pass
                continue

            if msg_type == "typing":
                for uid2, ws2 in list(_ws_rooms.get(room_id, {}).items()):
                    if uid2 != user_id:
                        try:
                            await ws2.send_text(json.dumps({
                                "type": "typing", "user_id": user_id, "user_name": user_name
                            }, ensure_ascii=False))
                        except Exception:
                            pass
                continue

            content = payload.get("content", "")
            mentions = payload.get("mentions", [])
            reply_to = payload.get("reply_to")
            msg = chat_store.add_message(
                room_id=room_id,
                sender_id=user_id,
                sender_name=user_name,
                msg_type="text",
                content=content,
                mentions=mentions,
                reply_to=reply_to,
            )
            for uid2, ws2 in list(_ws_rooms.get(room_id, {}).items()):
                try:
                    await ws2.send_text(json.dumps({
                        "type": "new_message", "message": msg,
                    }, ensure_ascii=False))
                except Exception:
                    _ws_rooms.get(room_id, {}).pop(uid2, None)

            room = chat_store.get_room(room_id)
            should_trigger_ai = (
                "ai_xiaowen" in mentions
                or "@小文" in content
                or "ai_xiaowen" in (room or {}).get("members", [])
            )
            if should_trigger_ai:
                import threading
                threading.Thread(
                    target=_handle_xiaowen_mention,
                    args=(room_id, (room or {}).get("project_id"), content, user_name),
                    daemon=True,
                ).start()

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _ws_rooms.get(room_id, {}).pop(user_id, None)
        if not _ws_rooms.get(room_id):
            _ws_rooms.pop(room_id, None)
        for uid2, ws2 in list(_ws_rooms.get(room_id, {}).items()):
            try:
                import asyncio
                asyncio.ensure_future(ws2.send_text(json.dumps({
                    "type": "user_left", "user_id": user_id, "user_name": user_name
                }, ensure_ascii=False)))
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════
#  Budget Module — REST API (multi-plan per user)
# ═══════════════════════════════════════════════════════════════════════

from app.services.budget_storage import PURPOSE_META as BUDGET_PURPOSE_META


@app.get("/api/budget/purposes")
def budget_purposes() -> dict:
    return {"status": "ok", "purposes": BUDGET_PURPOSE_META}


@app.get("/api/budget/revenue-patterns")
def budget_revenue_patterns(user_id: str | None = None) -> dict:
    """返回所有可选的收入模式模板。如果传 user_id，会读项目认知里的 track_vector
    给出 1-3 个推荐 pattern。前端用这些模板动态渲染收入流字段。"""
    from app.services.revenue_models import (
        list_pattern_metadata,
        recommend_patterns,
    )
    metadata = list_pattern_metadata()
    recommended: list[str] = []
    if user_id:
        try:
            project_id = f"project-{user_id}"
            ps = json_store.load_project(project_id) or {}
            recommended = recommend_patterns(ps.get("track_vector"))
        except Exception:
            recommended = []
    return {
        "status": "ok",
        "patterns": metadata,
        "recommended": recommended,
    }


@app.get("/api/budget/plans/{user_id}")
def budget_list_plans(user_id: str) -> dict:
    plans = budget_store.list_plans(user_id)
    return {"status": "ok", "plans": plans}


@app.post("/api/budget/plans/{user_id}")
def budget_create_plan(user_id: str, payload: BudgetCreatePayload) -> dict:
    data = budget_store.create_plan(user_id, payload.name, payload.purpose)
    return {"status": "ok", "plan": data}


@app.delete("/api/budget/plans/{user_id}/{plan_id}")
def budget_delete_plan(user_id: str, plan_id: str) -> dict:
    ok = budget_store.delete_plan(user_id, plan_id)
    return {"status": "ok" if ok else "not_found"}


@app.get("/api/budget/{user_id}/{plan_id}")
def budget_get(user_id: str, plan_id: str) -> dict:
    data = budget_store.load(user_id, plan_id)
    if data is None:
        return {"status": "not_found", "budget": None}
    return {"status": "ok", "budget": data}


@app.put("/api/budget/{user_id}/{plan_id}")
def budget_save(user_id: str, plan_id: str, payload: BudgetSavePayload) -> dict:
    existing = budget_store.load(user_id, plan_id)
    if existing is None:
        return {"status": "not_found"}
    if payload.project_costs is not None:
        existing["project_costs"] = payload.project_costs
    if payload.business_finance is not None:
        existing["business_finance"] = payload.business_finance
    if payload.competition_budget is not None:
        existing["competition_budget"] = payload.competition_budget
    if payload.funding_plan is not None:
        existing["funding_plan"] = payload.funding_plan
    if payload.name is not None:
        existing["name"] = payload.name
    if payload.visible_tabs is not None:
        existing["visible_tabs"] = payload.visible_tabs
    if payload.ai_result is not None:
        existing["ai_result"] = payload.ai_result
    if payload.ai_chat_history is not None:
        existing["ai_chat_history"] = payload.ai_chat_history
    existing = BudgetStorage.compute_cash_flow(existing)
    saved = budget_store.save(user_id, plan_id, existing)
    return {"status": "ok", "budget": saved}


@app.post("/api/budget/{user_id}/{plan_id}/ai-rollback")
def budget_ai_rollback(user_id: str, plan_id: str, payload: dict) -> dict:
    """回滚 AI 自动写入的字段。
    payload: {"stream_index": int, "fields": ["price","monthly_users",...] | "all"}
    """
    budget = budget_store.load(user_id, plan_id)
    if budget is None:
        return {"status": "not_found"}
    biz = budget.setdefault("business_finance", {})
    streams = biz.get("revenue_streams") or []
    si = int(payload.get("stream_index", 0))
    fields = payload.get("fields") or "all"
    rolled: list[dict] = []
    if 0 <= si < len(streams):
        s = streams[si]
        ai_meta = (s or {}).get("_ai_meta") or {}
        field_meta = ai_meta.get("fields") or {}
        inputs = (s or {}).get("inputs") or {}
        targets = list(field_meta.keys()) if fields == "all" else list(fields)
        for f in targets:
            if f in field_meta:
                prev = field_meta[f].get("prev_value")
                if prev is None:
                    inputs.pop(f, None)
                else:
                    inputs[f] = prev
                rolled.append({"stream_index": si, "field": f, "restored_to": prev})
                field_meta.pop(f, None)
        if not field_meta:
            ai_meta.pop("fields", None)
        s["inputs"] = inputs
        if ai_meta:
            s["_ai_meta"] = ai_meta
        else:
            s.pop("_ai_meta", None)
        # 如果是整条 AI 创建的 stream 且字段全部回滚, 删除整条
        if (ai_meta.get("ai_created") and not field_meta and fields == "all"):
            streams.pop(si)
            rolled.append({"removed_stream": si})
    budget = BudgetStorage.compute_cash_flow(budget)
    saved = budget_store.save(user_id, plan_id, budget)
    return {"status": "ok", "rolled": rolled, "budget": saved}


@app.post("/api/budget/{user_id}/{plan_id}/ai-suggest")
def budget_ai_suggest(user_id: str, plan_id: str, payload: BudgetAISuggestPayload) -> dict:
    budget = budget_store.load(user_id, plan_id)
    if budget is None:
        return {"status": "not_found"}
    budget = BudgetStorage.compute_cash_flow(budget)
    summary = budget.get("summary", {})
    cost_cats = (budget.get("project_costs") or {}).get("categories") or []
    cost_names = [item.get("name", "") for cat in cost_cats for item in cat.get("items", []) if item.get("name")]
    streams = (budget.get("business_finance") or {}).get("revenue_streams") or []

    system = """你是一位资深创业财务顾问兼比赛评委。请根据学生的项目信息和当前预算数据，给出全面的预算诊断和建议。
必须返回一个纯JSON对象，包含以下字段：
1. diagnosis: 对象，包含 missing_items(字符串数组, 缺失的常见成本项), unreasonable_flags(字符串数组, 不合理的假设或数字), risk_warnings(字符串数组, 2-4条风险提示)
2. template: 对象，包含 suggested_costs(数组, 每项{name,estimated,category}), revenue_model(字符串, 收入模式建议), scenario_advice(字符串, 三档情景参数建议)
3. pitch_summary: 字符串, Markdown格式的比赛答辩预算说明(200-400字, 包含钱花在哪/为什么值得/预期回报)
4. faq: 数组, 3个对象每个{question, suggested_answer}, 评委最可能追问的财务问题及建议回答"""

    budget_context = f"""项目类型：{payload.project_type or '未指定'}
项目描述：{payload.project_description or '未提供详细描述'}
方案名称：{budget.get('name', '未命名')}
方案用途：{budget.get('purpose', '未知')}
当前预算概况：
- 项目成本合计：¥{summary.get('project_cost_total', 0)}
- 比赛预算合计：¥{summary.get('competition_cost_total', 0)}
- 总投入：¥{summary.get('total_investment', 0)}
- 基准月收入：¥{summary.get('baseline_monthly_revenue', 0)}
- 基准盈亏平衡月：{summary.get('breakeven_baseline', '未知')}
- 健康度评分：{summary.get('health_score', 0)}/100
- 资金缺口：¥{summary.get('funding_gap', 0)}
已填写成本项：{', '.join(cost_names) if cost_names else '暂无'}
收入来源数量：{len(streams)}"""

    try:
        suggestions = composer_llm.chat_json(
            system_prompt=system,
            user_prompt=budget_context,
            model=settings.llm_fast_model,
            temperature=0.3,
        )
        if not suggestions:
            raise ValueError("Empty AI response")
    except Exception as e:
        logger.error(f"Budget AI suggest failed: {e}")
        suggestions = {
            "diagnosis": {
                "missing_items": ["市场调研费用", "知识产权/专利费", "测试与质量保障费"],
                "unreasonable_flags": [],
                "risk_warnings": ["注意控制初期API调用成本", "学生用户付费意愿较低，需要验证"],
            },
            "template": {
                "suggested_costs": [
                    {"name": "云服务器(12个月)", "estimated": 2400, "category": "技术开发"},
                    {"name": "域名(1年)", "estimated": 60, "category": "技术开发"},
                    {"name": "API调用费", "estimated": 1000, "category": "技术开发"},
                    {"name": "设计工具", "estimated": 500, "category": "技术开发"},
                    {"name": "推广费用", "estimated": 2000, "category": "运营推广"},
                ],
                "revenue_model": "建议采用免费增值(Freemium)模式，基础功能免费，高级功能按月订阅。",
                "scenario_advice": "悲观情景月增长率设为5%，基准10%，乐观18%。",
            },
            "pitch_summary": "## 预算说明\n\n本项目预计总投入约¥6,000，主要用于技术开发和早期推广。",
            "faq": [
                {"question": "你的盈利模式是什么？", "suggested_answer": "采用免费增值模式。"},
                {"question": "初期资金从哪里来？", "suggested_answer": "团队自筹为主，同时申请学校创业基金支持。"},
                {"question": "如果用户增长不及预期怎么办？", "suggested_answer": "设置了悲观情景预案。"},
            ],
        }
    budget.setdefault("ai_suggestions", []).append({
        "timestamp": _now_iso(),
        "suggestions": suggestions,
    })
    budget_store.save(user_id, plan_id, budget)
    return {"status": "ok", "suggestions": suggestions}


@app.post("/api/budget/{user_id}/{plan_id}/ai-chat")
def budget_ai_chat(user_id: str, plan_id: str, payload: BudgetAIChatPayload) -> dict:
    budget = budget_store.load(user_id, plan_id)
    if budget is None:
        return {"status": "not_found"}
    budget = BudgetStorage.compute_cash_flow(budget)
    summary = budget.get("summary", {})

    system = "你是一位专业的创业财务顾问。学生正在使用财务工作台规划项目预算，请基于当前预算数据回答他们的问题。回答简洁实用，用中文，可用Markdown格式。"

    context = f"""方案名称：{budget.get('name', '未命名')}
当前预算概况：总投入¥{summary.get('total_investment', 0)}，基准月收入¥{summary.get('baseline_monthly_revenue', 0)}，盈亏平衡{summary.get('breakeven_baseline', '未知')}个月，健康度{summary.get('health_score', 0)}/100。
学生的问题：{payload.question}"""

    try:
        reply = composer_llm.chat_text(
            system_prompt=system,
            user_prompt=context,
            model=settings.llm_fast_model,
            temperature=0.5,
        )
        if not reply:
            reply = "抱歉，暂时无法回答。请稍后再试。"
    except Exception as e:
        logger.error(f"Budget AI chat failed: {e}")
        reply = "AI 服务暂时不可用，请稍后再试。"
    return {"status": "ok", "reply": reply}


# ═══════════════════════════════════════════════════════════════════════
#  Business Plan Module — conversation-scoped draft + revisions
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/business-plan/latest", response_model=BusinessPlanResponse)
def business_plan_latest(project_id: str, conversation_id: str) -> BusinessPlanResponse:
    readiness = business_plan_service.get_readiness(project_id, conversation_id)
    plan = business_plan_service.get_latest(project_id, conversation_id)
    return BusinessPlanResponse(status="ok", plan=plan, readiness=readiness)


@app.get("/api/business-plan/{plan_id}", response_model=BusinessPlanResponse)
def business_plan_detail(plan_id: str) -> BusinessPlanResponse:
    plan = business_plan_service.get_plan(plan_id)
    if not plan:
        return BusinessPlanResponse(status="not_found", plan=None, readiness={})
    readiness = business_plan_service.get_readiness(
        str(plan.get("project_id") or ""),
        str(plan.get("conversation_id") or ""),
    )
    return BusinessPlanResponse(status="ok", plan=plan, readiness=readiness)


# ══════════════════════════════════════════════════════════════════
#  Finance Report API
# ══════════════════════════════════════════════════════════════════


def _norm_user_key(raw: str) -> str:
    return (raw or "").strip().lower()


@app.get("/api/finance/report/{user_id}", response_model=FinanceReportResponse)
def finance_report_get(user_id: str) -> FinanceReportResponse:
    key = _norm_user_key(user_id)
    if not key:
        return FinanceReportResponse(status="invalid_user", report=None, detail="缺少 user_id")
    report = finance_report_service.load_latest(key)
    if not report:
        return FinanceReportResponse(status="not_found", report=None, detail="尚未生成财务分析报告")
    return FinanceReportResponse(status="ok", report=report)


@app.get("/api/finance/report/{user_id}/status", response_model=FinanceReportStatusResponse)
def finance_report_status(user_id: str) -> FinanceReportStatusResponse:
    key = _norm_user_key(user_id)
    st = finance_report_service.get_status(key)
    return FinanceReportStatusResponse(
        status=str(st.get("status", "idle")),
        detail=str(st.get("detail", "")),
        updated_at=str(st.get("updated_at", "")),
    )


@app.post("/api/finance/report/generate", response_model=FinanceReportResponse)
def finance_report_generate(payload: FinanceReportGeneratePayload) -> FinanceReportResponse:
    key = _norm_user_key(payload.user_id)
    if not key:
        return FinanceReportResponse(status="invalid_user", report=None, detail="缺少 user_id")
    try:
        report = finance_report_service.generate(
            user_id=key,
            plan_id=payload.plan_id,
            project_id=payload.project_id,
            conversation_id=payload.conversation_id,
            industry_hint=payload.industry_hint,
            context_text=payload.context_text,
            use_llm_explain=payload.use_llm_explain,
        )
        return FinanceReportResponse(status="ok", report=report)
    except RuntimeError as exc:
        return FinanceReportResponse(status="busy", report=None, detail=str(exc))
    except Exception as exc:
        logger.exception("finance_report_generate failed: %s", exc)
        return FinanceReportResponse(status="error", report=None, detail=str(exc))


@app.post("/api/finance/report/{user_id}/regenerate", response_model=FinanceReportResponse)
def finance_report_regenerate(user_id: str, payload: FinanceReportGeneratePayload) -> FinanceReportResponse:
    # 路径 user_id 优先
    payload.user_id = user_id or payload.user_id
    return finance_report_generate(payload)


# ══════════════════════════════════════════════════════════════════
#  行业财务基线 —— 老师/管理员维护接口
# ══════════════════════════════════════════════════════════════════

@app.get("/api/finance/baselines")
def finance_baselines_list() -> dict[str, Any]:
    """列出所有行业的基线记录（含来源、更新时间、证据）。"""
    try:
        finance_baseline_service.init_seed_if_missing()
        records = finance_baseline_service.list_all_baselines()
        return {"count": len(records), "baselines": records}
    except Exception as exc:
        logger.exception("finance_baselines_list failed: %s", exc)
        return {"count": 0, "baselines": [], "error": str(exc)}


@app.post("/api/finance/baselines/refresh")
def finance_baselines_refresh(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    联网刷新指定行业（或全部）的基线数据。
    payload: {"industry": "SaaS"} 或 {"industry": "all"} 或 {} (默认 all)
    """
    payload = payload or {}
    target = (payload.get("industry") or "all").strip()
    try:
        finance_baseline_service.init_seed_if_missing()
        updated: list[dict] = []
        failed: list[str] = []
        if target == "all" or not target:
            from app.services.finance_analyst import INDUSTRY_BASELINES
            keys = list(INDUSTRY_BASELINES.keys())
        else:
            keys = [target]
        for key in keys:
            rec = finance_baseline_service.refresh_from_web(key)
            if rec:
                updated.append({
                    "industry": key,
                    "source": rec.get("source"),
                    "updated_at": rec.get("updated_at"),
                    "evidence_count": len(rec.get("evidence", []) or []),
                })
            else:
                failed.append(key)
        return {
            "ok": True,
            "updated": updated,
            "failed": failed,
            "note": "failed 表示该行业联网检索或 LLM 抽数失败，仍保留旧版缓存",
        }
    except Exception as exc:
        logger.exception("finance_baselines_refresh failed: %s", exc)
        return {"ok": False, "error": str(exc)}


@app.post("/api/business-plan/generate", response_model=BusinessPlanResponse)
def business_plan_generate(payload: BusinessPlanGeneratePayload) -> BusinessPlanResponse:
    result = business_plan_service.generate_plan(
        mode=payload.mode,
        project_id=payload.project_id,
        conversation_id=payload.conversation_id,
        student_id=payload.student_id,
        allow_low_confidence=payload.allow_low_confidence,
    )
    return BusinessPlanResponse(
        status=str(result.get("status") or "ok"),
        plan=result.get("plan"),
        readiness=result.get("readiness") or {},
    )


@app.post("/api/business-plan/{plan_id}/refresh", response_model=BusinessPlanResponse)
def business_plan_refresh(plan_id: str) -> BusinessPlanResponse:
    result = business_plan_service.refresh_plan(plan_id)
    if result.get("status") == "not_found":
        return BusinessPlanResponse(status="not_found", plan=None, readiness={})
    plan = result.get("plan")
    readiness = result.get("readiness") or business_plan_service.get_readiness(
        str((plan or {}).get("project_id") or ""),
        str((plan or {}).get("conversation_id") or ""),
    )
    return BusinessPlanResponse(status=str(result.get("status") or "ok"), plan=plan, readiness=readiness)


@app.put("/api/business-plan/{plan_id}/sections/{section_id}", response_model=BusinessPlanResponse)
def business_plan_update_section(
    plan_id: str,
    section_id: str,
    payload: BusinessPlanSectionUpdatePayload,
) -> BusinessPlanResponse:
    plan = business_plan_service.update_section(
        plan_id,
        section_id,
        content=payload.content,
        field_map=payload.field_map,
        display_title=payload.display_title,
    )
    if not plan:
        return BusinessPlanResponse(status="not_found", plan=None, readiness={})
    readiness = business_plan_service.get_readiness(
        str(plan.get("project_id") or ""),
        str(plan.get("conversation_id") or ""),
    )
    return BusinessPlanResponse(status="ok", plan=plan, readiness=readiness)


@app.post("/api/business-plan/{plan_id}/revisions/{revision_id}/accept", response_model=BusinessPlanResponse)
def business_plan_accept_revision(plan_id: str, revision_id: str) -> BusinessPlanResponse:
    plan = business_plan_service.accept_revision(plan_id, revision_id)
    if not plan:
        return BusinessPlanResponse(status="not_found", plan=None, readiness={})
    readiness = business_plan_service.get_readiness(
        str(plan.get("project_id") or ""),
        str(plan.get("conversation_id") or ""),
    )
    return BusinessPlanResponse(status="ok", plan=plan, readiness=readiness)


@app.post("/api/business-plan/{plan_id}/revisions/{revision_id}/reject", response_model=BusinessPlanResponse)
def business_plan_reject_revision(plan_id: str, revision_id: str) -> BusinessPlanResponse:
    plan = business_plan_service.reject_revision(plan_id, revision_id)
    if not plan:
        return BusinessPlanResponse(status="not_found", plan=None, readiness={})
    readiness = business_plan_service.get_readiness(
        str(plan.get("project_id") or ""),
        str(plan.get("conversation_id") or ""),
    )
    return BusinessPlanResponse(status="ok", plan=plan, readiness=readiness)


@app.post("/api/business-plan/{plan_id}/revisions/accept-all", response_model=BusinessPlanResponse)
def business_plan_accept_all(plan_id: str) -> BusinessPlanResponse:
    result = business_plan_service.accept_all_revisions(plan_id)
    if result.get("status") == "not_found":
        return BusinessPlanResponse(status="not_found", plan=None, readiness={})
    plan = result.get("plan") or {}
    readiness = business_plan_service.get_readiness(
        str(plan.get("project_id") or ""),
        str(plan.get("conversation_id") or ""),
    )
    return BusinessPlanResponse(status=str(result.get("status") or "ok"), plan=plan, readiness=readiness)


@app.post("/api/business-plan/{plan_id}/revisions/reject-all", response_model=BusinessPlanResponse)
def business_plan_reject_all(plan_id: str) -> BusinessPlanResponse:
    result = business_plan_service.reject_all_revisions(plan_id)
    if result.get("status") == "not_found":
        return BusinessPlanResponse(status="not_found", plan=None, readiness={})
    plan = result.get("plan") or {}
    readiness = business_plan_service.get_readiness(
        str(plan.get("project_id") or ""),
        str(plan.get("conversation_id") or ""),
    )
    return BusinessPlanResponse(status=str(result.get("status") or "ok"), plan=plan, readiness=readiness)


# ── 教师端：按项目查看学生计划书列表（只读入口） ─────────────
@app.get("/api/teacher/project/{project_id}/business-plans")
def teacher_list_business_plans(project_id: str) -> dict:
    rows = business_plan_store.list_by_project(project_id)
    return {"status": "ok", "plans": rows}


# ── 教师端：按学生聚合计划书列表（学生计划书 Tab 的主数据源） ─
@app.get("/api/teacher/student-plans")
def teacher_student_plans(teacher_id: str = "", team_id: str = "") -> dict:
    """按老师的团队遍历学生 → 每位学生的 project-{user_id} 取全部计划书。

    返回结构：
    {
      "status": "ok",
      "teams": [
        {
          "team_id": "...",
          "team_name": "...",
          "students": [
            {
              "student_id": "<user_id>",
              "display_name": "...",
              "student_id_code": "<学号字段>",
              "class_id": "...",
              "project_id": "project-<user_id>",
              "plans": [ { plan_id, title, version_tier, updated_at, word_count, comment_count, unresolved_count }, ... ]
            }
          ]
        }
      ]
    }
    """
    all_teams = team_store.list_all() or []
    teams_out: list[dict[str, Any]] = []
    for t in all_teams:
        if teacher_id and t.get("teacher_id") != teacher_id:
            continue
        tid = str(t.get("team_id") or "")
        if team_id and tid != team_id:
            continue
        students_out: list[dict[str, Any]] = []
        for m in (t.get("members") or []):
            uid = str(m.get("user_id") or "")
            if not uid:
                continue
            user_info = user_store.get_by_id(uid) or {}
            project_id = f"project-{uid}"
            student_project_state = ensure_project_cognition(json_store.load_project(project_id))
            plans = business_plan_store.list_by_project(project_id)
            enriched_plans: list[dict[str, Any]] = []
            for p in plans:
                plan_id = str(p.get("plan_id") or "")
                word_count = 0
                try:
                    target = business_plan_store._plan_file(  # internal helper is fine here
                        project_id, str(p.get("conversation_id") or ""), plan_id,
                    )
                    if target.exists():
                        data = json.loads(target.read_text(encoding="utf-8"))
                        for s in (data.get("sections") or []):
                            word_count += len(re.findall(r"[\u4e00-\u9fff]", str(s.get("content") or "")))
                except Exception:
                    pass
                comments = business_plan_store.list_comments(plan_id)
                unresolved = sum(1 for c in comments if str(c.get("status") or "open") != "resolved")
                enriched_plans.append({
                    **p,
                    "word_count": word_count,
                    "comment_count": len(comments),
                    "unresolved_count": unresolved,
                })
            if enriched_plans:
                students_out.append({
                    "student_id": uid,
                    "display_name": user_info.get("display_name") or uid[:8],
                    "student_id_code": user_info.get("student_id") or "",
                    "class_id": user_info.get("class_id") or "",
                    "project_id": project_id,
                    "track_vector": student_project_state.get("track_vector", {}),
                    "project_stage_v2": student_project_state.get("project_stage_v2", ""),
                    "track_labels": describe_track_vector(student_project_state.get("track_vector")),
                    "plans": enriched_plans,
                })
        if students_out:
            teams_out.append({
                "team_id": tid,
                "team_name": str(t.get("team_name") or t.get("name") or "团队"),
                "students": students_out,
            })
    return {"status": "ok", "teams": teams_out}


# ── 教师批注 CRUD（按 plan_id，独立文件存储） ────────────────
@app.get("/api/business-plan/{plan_id}/comments")
def business_plan_comments_list(plan_id: str) -> dict:
    return business_plan_service.list_plan_comments(plan_id)


@app.post("/api/business-plan/{plan_id}/comments")
def business_plan_comments_add(plan_id: str, payload: dict) -> dict:
    if not isinstance(payload, dict):
        payload = {}
    return business_plan_service.add_plan_comment(plan_id, payload)


@app.patch("/api/business-plan/{plan_id}/comments/{comment_id}")
def business_plan_comments_update(plan_id: str, comment_id: str, payload: dict) -> dict:
    if not isinstance(payload, dict):
        payload = {}
    return business_plan_service.update_plan_comment(plan_id, comment_id, payload)


@app.delete("/api/business-plan/{plan_id}/comments/{comment_id}")
def business_plan_comments_delete(plan_id: str, comment_id: str) -> dict:
    return business_plan_service.delete_plan_comment(plan_id, comment_id)


# ── 润色为正式稿：执行摘要 + 每章小结 ────────────────────────
@app.post("/api/business-plan/{plan_id}/finalize", response_model=BusinessPlanResponse)
def business_plan_finalize(plan_id: str) -> BusinessPlanResponse:
    result = business_plan_service.finalize_plan(plan_id)
    status = str(result.get("status") or "ok")
    if status == "not_found":
        return BusinessPlanResponse(status="not_found", plan=None, readiness={})
    plan = result.get("plan") or {}
    readiness = business_plan_service.get_readiness(
        str(plan.get("project_id") or ""),
        str(plan.get("conversation_id") or ""),
    ) if plan else {}
    return BusinessPlanResponse(status=status, plan=plan if plan else None, readiness=readiness)


# ── 版本快照：手动保存 / 列表 / 回滚 ────────────────────────
@app.post("/api/business-plan/{plan_id}/snapshots")
def business_plan_snapshot_create(plan_id: str, payload: dict) -> dict:
    label = ""
    if isinstance(payload, dict):
        label = str(payload.get("label") or "").strip()
    return business_plan_service.create_snapshot(plan_id, label=label)


@app.get("/api/business-plan/{plan_id}/snapshots")
def business_plan_snapshot_list(plan_id: str) -> dict:
    return business_plan_service.list_snapshots(plan_id)


@app.post("/api/business-plan/{plan_id}/snapshots/{snap_id}/rollback", response_model=BusinessPlanResponse)
def business_plan_snapshot_rollback(plan_id: str, snap_id: str) -> BusinessPlanResponse:
    result = business_plan_service.rollback_to_snapshot(plan_id, snap_id)
    status = str(result.get("status") or "ok")
    if status == "not_found":
        return BusinessPlanResponse(status="not_found", plan=None, readiness={})
    plan = result.get("plan") or {}
    readiness = business_plan_service.get_readiness(
        str(plan.get("project_id") or ""),
        str(plan.get("conversation_id") or ""),
    ) if plan else {}
    return BusinessPlanResponse(status=status, plan=plan if plan else None, readiness=readiness)


# ── 单章深化闭环 ────────────────────────────────────────────────
@app.get("/api/business-plan/{plan_id}/chapter/{section_id}/deepen-questions")
def business_plan_chapter_deepen_questions(plan_id: str, section_id: str) -> dict:
    return business_plan_service.generate_chapter_deepen_questions(plan_id, section_id)


@app.post("/api/business-plan/{plan_id}/chapter/{section_id}/deepen", response_model=BusinessPlanResponse)
def business_plan_chapter_deepen_apply(
    plan_id: str,
    section_id: str,
    payload: dict,
) -> BusinessPlanResponse:
    answers = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(answers, list):
        answers = []
    result = business_plan_service.apply_chapter_deepen(plan_id, section_id, answers)
    status = str(result.get("status") or "ok")
    plan = result.get("plan") or {}
    readiness = business_plan_service.get_readiness(
        str(plan.get("project_id") or ""),
        str(plan.get("conversation_id") or ""),
    ) if plan else {}
    return BusinessPlanResponse(status=status, plan=plan if plan else None, readiness=readiness)


@app.post("/api/business-plan/{plan_id}/upgrade", response_model=BusinessPlanResponse)
def business_plan_upgrade(plan_id: str, payload: BusinessPlanUpgradePayload) -> BusinessPlanResponse:
    result = business_plan_service.upgrade_plan(plan_id, mode=payload.mode)
    if result.get("status") == "not_found":
        return BusinessPlanResponse(status="not_found", plan=None, readiness={})
    plan = result.get("plan")
    readiness = business_plan_service.get_readiness(
        str((plan or {}).get("project_id") or ""),
        str((plan or {}).get("conversation_id") or ""),
    )
    return BusinessPlanResponse(status=str(result.get("status") or "ok"), plan=plan, readiness=readiness)


# ── 竞赛分支：从主干 fork 出一份竞赛优化版 ─────────────────────
@app.post("/api/business-plan/{plan_id}/fork-competition", response_model=BusinessPlanResponse)
def business_plan_fork_competition(
    plan_id: str,
    payload: BusinessPlanForkCompetitionPayload,
) -> BusinessPlanResponse:
    result = business_plan_service.fork_for_competition(
        plan_id,
        competition_type=payload.competition_type,
        refresh_kb_reference=payload.refresh_kb_reference,
    )
    if result.get("status") in {"not_found", "invalid"}:
        return BusinessPlanResponse(status=str(result["status"]), plan=None, readiness={})
    plan = result.get("plan")
    readiness = business_plan_service.get_readiness(
        str((plan or {}).get("project_id") or ""),
        str((plan or {}).get("conversation_id") or ""),
    ) if plan else {}
    return BusinessPlanResponse(
        status=str(result.get("status") or "ok"),
        plan=plan,
        readiness=readiness,
    )


# ── 教练模式切换（项目教练 ↔ 竞赛教练） ─────────────────────────
@app.patch("/api/business-plan/{plan_id}/coaching-mode", response_model=BusinessPlanResponse)
def business_plan_set_coaching_mode(
    plan_id: str,
    payload: BusinessPlanCoachingModePayload,
) -> BusinessPlanResponse:
    result = business_plan_service.set_coaching_mode(plan_id, payload.mode)
    if result.get("status") == "not_found":
        return BusinessPlanResponse(status="not_found", plan=None, readiness={})
    plan = result.get("plan")
    readiness = business_plan_service.get_readiness(
        str((plan or {}).get("project_id") or ""),
        str((plan or {}).get("conversation_id") or ""),
    ) if plan else {}
    resp = BusinessPlanResponse(
        status=str(result.get("status") or "ok"),
        plan=plan,
        readiness=readiness,
    )
    return resp


# ── 竞赛教练议题板 ─────────────────────────────────────────────
@app.get("/api/business-plan/{plan_id}/agenda")
def business_plan_list_agenda(plan_id: str, status: str = "") -> dict:
    return business_plan_service.list_agenda(plan_id, status_filter=status)


@app.post("/api/business-plan/{plan_id}/agenda/apply", response_model=BusinessPlanResponse)
def business_plan_apply_agenda(
    plan_id: str,
    payload: BusinessPlanAgendaApplyPayload,
) -> BusinessPlanResponse:
    result = business_plan_service.apply_agenda(
        plan_id,
        agenda_ids=payload.agenda_ids,
        target_section_map=payload.target_section_map or None,
    )
    if result.get("status") == "not_found":
        return BusinessPlanResponse(status="not_found", plan=None, readiness={})
    plan = result.get("plan")
    readiness = business_plan_service.get_readiness(
        str((plan or {}).get("project_id") or ""),
        str((plan or {}).get("conversation_id") or ""),
    ) if plan else {}
    return BusinessPlanResponse(
        status=str(result.get("status") or "ok"),
        plan=plan,
        readiness=readiness,
    )


@app.patch("/api/business-plan/{plan_id}/agenda/{agenda_id}")
def business_plan_patch_agenda(
    plan_id: str,
    agenda_id: str,
    payload: BusinessPlanAgendaPatchPayload,
) -> dict:
    return business_plan_service.patch_agenda(
        plan_id,
        agenda_id,
        status=payload.status,
        section_id_hint=payload.section_id_hint,
    )


@app.post("/api/business-plan/{plan_id}/agenda/review")
def business_plan_agenda_review(
    plan_id: str,
    payload: BusinessPlanAgendaReviewPayload | None = None,
) -> dict:
    """评委视角全书巡检：逐章调 LLM jury agent 出 0~2 条议题入库。
    同步返回，受 _REVIEW_MIN_INTERVAL_SEC 节流（默认 60s）。"""
    payload = payload or BusinessPlanAgendaReviewPayload()
    return business_plan_service.run_jury_review(
        plan_id,
        section_ids=list(payload.section_ids or []),
        force=bool(payload.force),
    )


# ── 所有相关分支（主干 + fork）聚合查询 ─────────────────────────
@app.get("/api/business-plan/{plan_id}/siblings")
def business_plan_siblings(plan_id: str) -> dict:
    """返回同一 project+conversation 下所有计划书（主干+所有 fork），便于前端做切换。"""
    plan = business_plan_service.get_plan(plan_id)
    if not plan:
        return {"status": "not_found", "plans": []}
    project_id = str(plan.get("project_id") or "")
    conversation_id = str(plan.get("conversation_id") or "")
    plan_dir = business_plan_store._plan_dir(project_id, conversation_id)
    out = []
    for p in sorted(plan_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not data.get("plan_id"):
            continue
        out.append({
            "plan_id": data.get("plan_id"),
            "title": data.get("title"),
            "plan_type": data.get("plan_type") or "main",
            "fork_of": data.get("fork_of"),
            "mode": data.get("mode") or "learning",
            "version_tier": data.get("version_tier"),
            "submission_status": data.get("submission_status") or "draft",
            "updated_at": data.get("updated_at"),
        })
    return {"status": "ok", "plans": out}


# ── 教师评分：POST 写入 / GET 读取 ──────────────────────────────
@app.post("/api/business-plan/{plan_id}/grade", response_model=BusinessPlanGradingResponse)
def business_plan_grade(
    plan_id: str,
    payload: BusinessPlanGradingPayload,
) -> BusinessPlanGradingResponse:
    result = business_plan_service.grade_plan(plan_id, payload.dict())
    return BusinessPlanGradingResponse(
        status=str(result.get("status") or "ok"),
        grading=result.get("grading"),
    )


@app.get("/api/business-plan/{plan_id}/grading", response_model=BusinessPlanGradingResponse)
def business_plan_grading_get(plan_id: str) -> BusinessPlanGradingResponse:
    result = business_plan_service.get_grading(plan_id)
    return BusinessPlanGradingResponse(
        status=str(result.get("status") or "ok"),
        grading=result.get("grading"),
    )


# ── 计划书对比 ────────────────────────────────────────────────
@app.post("/api/business-plan/compare", response_model=BusinessPlanCompareResponse)
def business_plan_compare(payload: BusinessPlanComparePayload) -> BusinessPlanCompareResponse:
    result = business_plan_service.compare_plans(
        payload.plan_ids,
        focus_sections=payload.focus_sections,
        use_llm=payload.use_llm,
    )
    return BusinessPlanCompareResponse(
        status=str(result.get("status") or "ok"),
        comparison=result.get("comparison"),
    )


# ── 教师端按分类分组的计划书列表（跨学生 + 跨项目） ─────────────
@app.get("/api/teacher/student-plans-grouped")
def teacher_student_plans_grouped(teacher_id: str = "", team_id: str = "") -> dict:
    """把 teacher_student_plans 的结果拍平后，按项目品类二次分组，方便教师做跨学生对比。"""
    base = teacher_student_plans(teacher_id=teacher_id, team_id=team_id)
    flat: list[dict[str, Any]] = []
    for t in base.get("teams") or []:
        for s in t.get("students") or []:
            for p in s.get("plans") or []:
                flat.append({
                    **p,
                    "team_id": t.get("team_id"),
                    "team_name": t.get("team_name"),
                    "student_id": s.get("student_id"),
                    "display_name": s.get("display_name"),
                    "student_id_code": s.get("student_id_code"),
                    "class_id": s.get("class_id"),
                    "project_id": s.get("project_id"),
                })
    groups = business_plan_service.list_plans_grouped_by_category(flat)
    return {"status": "ok", "groups": groups}


@app.post(
    "/api/business-plan/{plan_id}/sections/{section_id}/deepen-questions",
    response_model=BusinessPlanQuestionsResponse,
)
def business_plan_deepen_questions(plan_id: str, section_id: str) -> BusinessPlanQuestionsResponse:
    result = business_plan_service.generate_deepen_questions(plan_id, section_id)
    return BusinessPlanQuestionsResponse(
        status=str(result.get("status") or "ok"),
        questions=result.get("questions") or [],
    )


@app.post(
    "/api/business-plan/{plan_id}/sections/{section_id}/expand",
    response_model=BusinessPlanResponse,
)
def business_plan_expand_section(
    plan_id: str,
    section_id: str,
    payload: BusinessPlanExpandPayload,
) -> BusinessPlanResponse:
    answers = [a.dict() for a in payload.answers]
    result = business_plan_service.expand_section(
        plan_id,
        section_id,
        answers=answers,
        merge_strategy=payload.merge_strategy,
    )
    if result.get("status") == "not_found":
        return BusinessPlanResponse(status="not_found", plan=None, readiness={})
    plan = result.get("plan")
    readiness = business_plan_service.get_readiness(
        str((plan or {}).get("project_id") or ""),
        str((plan or {}).get("conversation_id") or ""),
    ) if plan else {}
    return BusinessPlanResponse(status=str(result.get("status") or "ok"), plan=plan, readiness=readiness)


@app.get(
    "/api/business-plan/{plan_id}/deepen-suggestions",
    response_model=BusinessPlanSuggestionsResponse,
)
def business_plan_deepen_suggestions(plan_id: str) -> BusinessPlanSuggestionsResponse:
    result = business_plan_service.generate_deepen_suggestions(plan_id)
    return BusinessPlanSuggestionsResponse(
        status=str(result.get("status") or "ok"),
        suggestions=result.get("suggestions") or [],
    )


@app.post("/api/business-plan/{plan_id}/export")
def business_plan_export(plan_id: str, payload: BusinessPlanExportPayload) -> dict:
    return business_plan_service.export_plan(
        plan_id=plan_id,
        export_mode=payload.export_mode,
        export_format=payload.export_format,
        cover_info=payload.cover_info,
    )


@app.get("/api/business-plan/exports/{filename}")
def business_plan_export_download(filename: str):
    from fastapi.responses import FileResponse

    safe = re.sub(r"[\\/]+", "", filename)
    target = business_plan_exports_root / safe
    if not target.exists() or not target.is_file():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="export not found")
    return FileResponse(
        path=str(target),
        filename=safe,
        media_type="application/octet-stream",
    )


def _now_iso() -> str:
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    return _dt.now(_tz(_td(hours=8))).isoformat()


from uuid import uuid4


# ── KG Explorer panel endpoints ─────────────────────────────

@app.get("/api/kg/subgraphs")
def kg_subgraphs() -> dict:
    """Return entire KG organized into dimension-based logical subgraphs for force-graph rendering.

    在原有"维度子图（Neo4j 投影）"之外，附加 `ability_subgraphs` 字段：
    把 `app.services.ability_subgraphs.ABILITY_SUBGRAPHS` 的运行时能力子图也透出，
    让前端 KG 可视化页可以同时展示"知识库维度子图 + 运行时能力子图"。
    它不是 Neo4j 里的子图，而是本体节点的话题切片（创新评估 / 商业模式构建 / 模拟路演）。
    """
    base = graph_service.get_subgraph_data() or {}
    try:
        from app.services.ability_subgraphs import ABILITY_SUBGRAPHS
        from app.services.kg_ontology import ONTOLOGY_NODES, serialize_node
        ability_payload: list[dict] = []
        # 颜色与 KBGraphPanel 既有 subgraphs 区分开（避免色盘冲突）
        color_map = {
            "innovation_evaluation": "#a78bfa",
            "business_model_construction": "#60a5fa",
            "simulated_roadshow": "#f472b6",
        }
        for sub in ABILITY_SUBGRAPHS.values():
            nodes_full: list[dict] = []
            kind_count: dict[str, int] = {}
            for nid in sub.ontology_nodes:
                node = ONTOLOGY_NODES.get(nid)
                if not node:
                    continue
                payload = serialize_node(node)
                nodes_full.append(payload)
                kind_count[payload["kind"]] = kind_count.get(payload["kind"], 0) + 1
            ability_payload.append({
                "id": sub.id,
                "name": sub.name,
                "description": sub.description,
                "purpose": sub.purpose,
                "color": color_map.get(sub.id, "#94a3b8"),
                "node_count": len(nodes_full),
                "ontology_nodes": nodes_full,
                "rubric_dimensions": list(sub.rubric_dimensions),
                "hyperedge_families": list(sub.hyperedge_families),
                "related_rule_ids": list(sub.related_rule_ids),
                "trigger_keywords": list(sub.trigger_keywords),
                "applies_to_stage": list(sub.applies_to_stage),
                "applies_to_spectrum": list(sub.applies_to_spectrum),
                "kind_distribution": kind_count,
            })
        base["ability_subgraphs"] = ability_payload
    except Exception as exc:  # noqa: BLE001
        base["ability_subgraphs"] = []
        base.setdefault("warnings", []).append(f"ability_subgraphs failed: {exc}")
    return base


@app.get("/api/kg/subgraph-overview")
def kg_subgraph_overview() -> dict:
    """Return meta-level overview: one node per subgraph + cross-subgraph links."""
    return graph_service.get_subgraph_overview()


@app.get("/api/kg/subgraph-detail/{sg_id}")
def kg_subgraph_detail(sg_id: str) -> dict:
    """Return all nodes and project connections for a single subgraph dimension."""
    return graph_service.get_single_subgraph(sg_id)


@app.get("/api/kg/hypergraph-viz")
def kg_hypergraph_viz() -> dict:
    """Return Hyperedge/HyperNode graph data from in-memory hypergraph (no Neo4j dependency)."""
    return hypergraph_service.get_viz_data()


@app.get("/api/kg/search")
def kg_search(q: str = "", subgraph: str = "", category: str = "", limit: int = 30) -> dict:
    """Search KG nodes by keyword with optional subgraph/category filters."""
    return graph_service.search_kg(q, subgraph_filter=subgraph, category_filter=category, limit=limit)


@app.get("/api/kg/quality")
def kg_quality() -> dict:
    """Return pre-computed KG quality evaluation report.

    如果报告不存在或读失败：返回 status=not_generated/error，让前端
    展示『数据未就绪』灰态而不是拿不到数据报错。
    """
    import json as _json
    from datetime import datetime as _dt
    quality_path = settings.data_root / "kg_quality" / "quality_report.json"
    if not quality_path.exists():
        return {
            "status": "not_generated",
            "report_path": str(quality_path),
            "message": "知识图谱质量报告尚未生成",
            "hint": "在 workspace 根目录执行：python scripts/evaluate_kg_quality.py",
            "dimensions": [],
        }
    try:
        data = _json.loads(quality_path.read_text(encoding="utf-8"))
        # 附加元信息：报告生成时间 / 距今多久 / 文件路径
        try:
            mtime = quality_path.stat().st_mtime
            generated_at = _dt.fromtimestamp(mtime).isoformat(timespec="seconds")
            age_days = round((_dt.now().timestamp() - mtime) / 86400, 1)
        except Exception:
            generated_at = None
            age_days = None
        data.setdefault("status", "ok")
        data["report_meta"] = {
            "generated_at": generated_at,
            "age_days": age_days,
            "is_stale": (age_days is not None and age_days > 7),
            "report_path": str(quality_path),
            "refresh_hint": "python scripts/evaluate_kg_quality.py",
        }
        return data
    except Exception as exc:
        return {
            "status": "error",
            "error": f"failed to read quality report: {exc}",
            "report_path": str(quality_path),
            "hint": "请检查报告文件是否被损坏，或重新执行 scripts/evaluate_kg_quality.py 生成",
            "dimensions": [],
        }


# ── Dimension Chinese Names ─────────────────────────────────

DIM_CN: dict[str, str] = {
    "Problem Definition": "问题定义",
    "User Evidence Strength": "用户证据",
    "Solution Feasibility": "方案可行性",
    "Business Model Consistency": "商业模式一致性",
    "Market & Competition": "市场与竞争",
    "Financial Logic": "财务逻辑",
    "Innovation & Differentiation": "创新差异化",
    "Team & Execution": "团队执行力",
    "Presentation Quality": "表达质量",
}

def _dim_cn(dim: str) -> str:
    return DIM_CN.get(dim, dim)


# ── Syndrome Templates ──────────────────────────────────────

SYNDROME_TEMPLATES: list[dict] = [
    {
        "id": "market_validation_gap",
        "label": "市场验证缺失",
        "stage_focus": "early",
        "rule_set": {"H1", "H4", "H5", "H6"},
        "weakness_dims": {"Problem Definition", "Market & Competition", "User Evidence Strength"},
        "severity_thresholds": {"warning_ratio": 0.3, "critical_ratio": 0.5, "min_students": 1},
        "teacher_signal": "学生能讲想法，但无法证明「谁会买、为什么买、市场有多大」",
        "description_tpl": "{ratio}% 的项目在目标用户识别、市场竞争格局或需求验证上存在明显缺口",
        "intervention_steps": [
            {"step": 1, "title": "市场验证工作坊", "action": "讲解用户画像-痛点-市场规模的三角验证方法，用正反案例对照", "expected_output": "每组提交修订版用户画像 + 市场规模测算"},
            {"step": 2, "title": "竞品分析补交", "action": "要求每组补充至少 3 个竞品的对照表（价格、替代门槛、差异化点）", "expected_output": "竞品对照表（含数据来源标注）"},
            {"step": 3, "title": "用户证据任务", "action": "每组至少完成 3 份用户访谈或问卷，提取原话作为痛点证据", "expected_output": "用户访谈记录 + 痛点证据摘要"},
        ],
    },
    {
        "id": "business_model_broken",
        "label": "商业模型断裂",
        "stage_focus": "middle",
        "rule_set": {"H2", "H3", "H8", "H9"},
        "weakness_dims": {"Business Model Consistency", "Financial Logic"},
        "teacher_signal": "能讲产品功能，但讲不清「怎么赚钱、成本多少、多久回本」",
        "description_tpl": "{ratio}% 的项目在价值主张与盈利路径之间的逻辑链不完整",
        "intervention_steps": [
            {"step": 1, "title": "商业模式复盘课", "action": "用商业模式画布逐块对照，重点检查价值主张→渠道→收入→成本的闭环", "expected_output": "修订版商业模式画布"},
            {"step": 2, "title": "单位经济补课", "action": "讲解 CAC/LTV/毛利率等核心指标，要求每组用实际数据或合理假设计算", "expected_output": "单位经济模型表（含假设说明）"},
            {"step": 3, "title": "定价策略验证", "action": "要求每组对比竞品定价，论证自身定价的合理性和用户付费意愿依据", "expected_output": "定价策略说明 + 竞品价格对照"},
        ],
    },
    {
        "id": "execution_hollow",
        "label": "执行落地空心化",
        "stage_focus": "middle",
        "rule_set": {"H10", "H12", "H13"},
        "weakness_dims": {"Team & Execution", "Solution Feasibility"},
        "teacher_signal": "PPT 很完整，但里程碑、资源分工、MVP 路线说不清楚",
        "description_tpl": "{ratio}% 的项目在执行计划、团队分工或 MVP 范围上缺乏具体可落地的路径",
        "intervention_steps": [
            {"step": 1, "title": "里程碑拆解会", "action": "每组当场把接下来 8 周拆成 4 个里程碑，明确每个里程碑的交付物和负责人", "expected_output": "里程碑甘特图 + 分工表"},
            {"step": 2, "title": "MVP 范围校正", "action": "引导学生区分核心功能与非核心功能，砍掉不必要的范围膨胀", "expected_output": "MVP 功能清单（标注优先级 P0/P1/P2）"},
            {"step": 3, "title": "资源匹配审查", "action": "检查团队人力、技术栈、外部资源是否能支撑当前计划", "expected_output": "资源缺口清单 + 补救方案"},
        ],
    },
    {
        "id": "evidence_weak",
        "label": "证据支撑薄弱",
        "stage_focus": "cross_stage",
        "rule_set": {"H5", "H14", "H15"},
        "weakness_dims": {"User Evidence Strength", "Presentation Quality"},
        "teacher_signal": "论断很多，证据很少；说服性不足，缺少数据、原话或案例支撑",
        "description_tpl": "{ratio}% 的项目核心主张缺少充分的数据佐证或用户验证证据",
        "intervention_steps": [
            {"step": 1, "title": "证据审计课", "action": "逐页审查每组 PPT，标注「无证据支撑」的论断，讲解证据分级标准", "expected_output": "证据审计清单（每个论断标注证据等级）"},
            {"step": 2, "title": "用户验证冲刺", "action": "每组在一周内完成至少 5 条一手证据（访谈、问卷、数据分析、专家评审）", "expected_output": "证据清单 + 原始数据/原话"},
            {"step": 3, "title": "路演表达改进", "action": "要求每个关键论断后必须跟一条证据，练习「论断→证据→推论」表达结构", "expected_output": "修订版路演脚本"},
        ],
    },
    {
        "id": "innovation_inflated",
        "label": "创新差异化虚高",
        "stage_focus": "early",
        "rule_set": {"H6", "H7"},
        "weakness_dims": {"Innovation & Differentiation", "Market & Competition"},
        "teacher_signal": "过度强调「创新」，但缺乏对替代方案和竞品路径的证明",
        "description_tpl": "{ratio}% 的项目声称的创新点缺少竞品对照和落地门槛验证",
        "intervention_steps": [
            {"step": 1, "title": "竞品深度对照", "action": "每组选 2-3 个最接近的竞品，从功能、价格、用户群、技术路线四维度逐项对比", "expected_output": "竞品深度对比矩阵"},
            {"step": 2, "title": "差异化重写", "action": "基于对比结果，重新定义差异化：不是「我有什么」，而是「用户为什么不用竞品而用我」", "expected_output": "修订版差异化声明（含用户视角论证）"},
            {"step": 3, "title": "技术门槛验证", "action": "如果声称技术创新，需提供原型/Demo 或技术可行性分析", "expected_output": "技术可行性说明或原型截图"},
        ],
    },
    {
        "id": "risk_blind_spot",
        "label": "风险识别盲区",
        "stage_focus": "late",
        "rule_set": {"H11", "H22"},
        "weakness_dims": set(),
        "teacher_signal": "学生只讲机会，不讲边界条件、法规限制或伦理风险",
        "description_tpl": "{ratio}% 的项目未识别或未讨论合规、伦理或法规层面的潜在风险",
        "intervention_steps": [
            {"step": 1, "title": "风险复盘课", "action": "讲解创业项目常见的法律、合规、伦理风险类型，用真实案例说明忽视风险的后果", "expected_output": "风险自查清单（每组填写）"},
            {"step": 2, "title": "合规补充清单", "action": "每组列出项目涉及的数据隐私、行业法规、资质许可等合规要求", "expected_output": "合规要求清单 + 应对策略"},
            {"step": 3, "title": "伦理审查讨论", "action": "如项目涉及 AI/算法/用户数据，组织一次伦理审查讨论，识别潜在偏见和公平性问题", "expected_output": "伦理审查简报"},
        ],
    },
]


# ── Team Diagnosis endpoint ─────────────────────────────────

def _get_project_triggered_rules(proj: dict) -> set[str]:
    """Extract triggered rule IDs from a project."""
    diag = proj.get("latest_diagnosis") or {}
    raw = diag.get("triggered_rules", []) or proj.get("top_risks", [])
    rules: set[str] = set()
    for item in (raw or []):
        rid = item if isinstance(item, str) else (item.get("rule_id") or item.get("id") or "")
        if rid:
            rules.add(rid.strip().upper())
    return rules


def _compute_syndromes(student_project_map: list[dict], total_projects: int) -> list[dict]:
    """Compute which syndromes are triggered for a team."""
    syndromes_out: list[dict] = []
    for tpl in SYNDROME_TEMPLATES:
        rule_set = tpl["rule_set"]
        affected: list[dict] = []
        for sp in student_project_map:
            overlap = sp["rules"] & rule_set
            if len(overlap) >= max(1, len(rule_set) // 2):
                affected.append({
                    "student_id": sp["student_id"],
                    "display_name": sp["display_name"],
                    "project_id": sp.get("project_id", ""),
                    "project_name": sp.get("project_name", ""),
                    "avg_score": sp.get("avg_score", 0),
                    "risk_count": sp.get("risk_count", 0),
                    "trigger_rules": sorted(overlap),
                })
        if not affected:
            continue
        unique_students = {a["student_id"] for a in affected}
        ratio = round(len(affected) / max(total_projects, 1) * 100)
        thresholds = tpl.get("severity_thresholds", {})
        warn_r = thresholds.get("warning_ratio", 0.3)
        crit_r = thresholds.get("critical_ratio", 0.5)
        min_stu = thresholds.get("min_students", 1)
        frac = len(affected) / max(total_projects, 1)
        if frac >= crit_r and len(unique_students) >= min_stu:
            severity = "critical"
        elif frac >= warn_r and len(unique_students) >= min_stu:
            severity = "warning"
        elif len(unique_students) >= 1:
            severity = "potential"
        else:
            continue
        syndromes_out.append({
            "id": tpl["id"],
            "label": tpl["label"],
            "severity": severity,
            "affected_project_count": len(affected),
            "affected_student_count": len(unique_students),
            "affected_ratio": ratio,
            "stage_focus": tpl.get("stage_focus", "cross_stage"),
            "related_rules": sorted(rule_set),
            "related_dimensions": sorted(tpl.get("weakness_dims", set())),
            "description": tpl["description_tpl"].format(ratio=ratio),
            "teacher_signal": tpl["teacher_signal"],
            "affected_students": affected[:8],
            "intervention_steps": tpl["intervention_steps"],
        })
    syndromes_out.sort(key=lambda s: (0 if s["severity"] == "critical" else 1 if s["severity"] == "warning" else 2, -s["affected_ratio"]))
    return syndromes_out


def _build_priority_intervention(syndromes: list[dict], team_avg: float, top_strengths: list) -> str:
    """Build a specific, actionable priority_intervention sentence."""
    critical = [s for s in syndromes if s["severity"] == "critical"]
    warning = [s for s in syndromes if s["severity"] == "warning"]
    if critical:
        s = critical[0]
        return (
            f"本周优先处理「{s['label']}」：已有 {s['affected_student_count']} 名学生的 "
            f"{s['affected_project_count']} 个项目同时出现此问题（{s['affected_ratio']}%），"
            f"建议立即开展一次「{s['intervention_steps'][0]['title']}」。"
        )
    if warning:
        s = warning[0]
        return (
            f"当前最值得关注的是「{s['label']}」：{s['affected_student_count']} 名学生的项目"
            f"在此方面存在共性缺口，建议安排「{s['intervention_steps'][0]['title']}」。"
        )
    strength_text = "、".join(s[0] for s in top_strengths[:2]) if top_strengths else "多个维度"
    return f"团队整体状态稳定，在{strength_text}上表现较好。可引导学生在已有基础上深化细节。"


def _build_student_project_issues(projects: list[dict], syndromes: list[dict]) -> list[dict]:
    """Build project-level issues for a single student."""
    issues: list[dict] = []
    syndrome_map = {s["id"]: s for s in syndromes}
    for proj in projects:
        proj_rules = _get_project_triggered_rules(proj)
        if not proj_rules:
            continue
        matched_syndromes: list[str] = []
        for tpl in SYNDROME_TEMPLATES:
            overlap = proj_rules & tpl["rule_set"]
            if len(overlap) >= max(1, len(tpl["rule_set"]) // 2):
                matched_syndromes.append(tpl["id"])
        if not matched_syndromes:
            rule_names = [get_rule_name(r) for r in sorted(proj_rules)[:3]]
            issue_title = "存在风险规则触发"
            issue_summary = f"项目触发了 {', '.join(rule_names)} 等风险，需要逐项排查修正。"
        else:
            primary = syndrome_map.get(matched_syndromes[0]) or {}
            issue_title = primary.get("label", "存在问题")
            issue_summary = primary.get("teacher_signal", "") or primary.get("description", "")
        diag = proj.get("latest_diagnosis") or {}
        bottleneck = diag.get("bottleneck") or proj.get("current_summary") or ""
        if bottleneck and len(issue_summary) < 80:
            issue_summary = f"{issue_summary}。具体表现：{bottleneck[:80]}"
        issues.append({
            "project_id": proj.get("project_id", ""),
            "project_name": proj.get("project_name", ""),
            "syndrome_ids": matched_syndromes,
            "issue_title": issue_title,
            "issue_summary": issue_summary.strip().rstrip("。") + "。",
            "trigger_rules": sorted(proj_rules),
            "weak_dimensions": sorted(set(
                dim for sid in matched_syndromes
                for dim in (syndrome_map.get(sid, {}).get("related_dimensions", []))
            )),
        })
    return issues


def _build_student_advice(portrait: dict, project_issues: list[dict]) -> list[dict]:
    """Generate actionable advice for a student based on their weaknesses and project issues."""
    advice: list[dict] = []
    weakness_dims = set(portrait.get("weakness_dimensions") or [])
    all_syndromes: set[str] = set()
    for pi in project_issues:
        all_syndromes.update(pi.get("syndrome_ids", []))

    advice_map = {
        "market_validation_gap": {
            "title": "补充用户验证证据",
            "advice": "1) 本周完成至少 3 份目标用户访谈，要求提取用户原话作为痛点证据；2) 补交竞品对照表（至少 3 个竞品，含价格、替代门槛、用户群差异）；3) 基于访谈结果重新评估市场规模假设，标注数据来源",
            "expected_output": "用户访谈记录（含原话摘录）+ 竞品对照表 + 修订版市场规模测算",
            "teacher_talk_point": "和学生讨论：你的目标用户到底是谁？他们现在用什么替代方案？你怎么确定他们愿意换用你的方案？",
        },
        "business_model_broken": {
            "title": "重写商业模式逻辑链",
            "advice": "1) 重新填写商业模式画布的收入和成本板块，确保价值主张→渠道→收入→成本形成闭环；2) 用 CAC/LTV 公式验证定价合理性；3) 补充用户付费意愿证据（如问卷/访谈中的价格敏感度数据）",
            "expected_output": "修订版商业模式画布 + 单位经济模型表（含假设说明）",
            "teacher_talk_point": "和学生讨论：你每获取一个用户要花多少钱？用户的生命周期价值是多少？你的毛利率能撑住多久？",
        },
        "execution_hollow": {
            "title": "细化执行路线图",
            "advice": "1) 把接下来 8 周拆成 4 个里程碑，每个里程碑写清交付物和负责人；2) 重新定义 MVP 范围，区分 P0（必做）/P1（应做）/P2（可不做），砍掉 P2；3) 检查团队人力和技术栈是否能支撑当前计划",
            "expected_output": "里程碑甘特图（含分工）+ MVP 功能优先级表 + 资源缺口清单",
            "teacher_talk_point": "和学生讨论：如果只能做一件事来验证你的核心假设，那是什么？你现在的计划里有多少是不验证核心假设的？",
        },
        "evidence_weak": {
            "title": "证据补强",
            "advice": "1) 逐页检查 PPT/BP，给每个核心论断标注证据来源和等级（一手数据 > 二手数据 > 类比推测）；2) 补充至少 5 条一手证据（用户访谈原话、问卷数据、产品测试结果、专家评审意见）；3) 练习「论断→证据→推论」的表达结构",
            "expected_output": "证据审计清单（每个论断标注证据等级）+ 一手证据文档",
            "teacher_talk_point": "和学生讨论：你这个结论的依据是什么？是你自己觉得还是有人告诉你的？能不能给我看原始数据？",
        },
        "innovation_inflated": {
            "title": "差异化重新论证",
            "advice": "1) 选 2-3 个最接近的竞品做深度对比（功能、价格、用户群、技术路线四个维度）；2) 基于对比结果重写差异化声明——不是「我有什么」，而是「用户为什么不用竞品而用我」；3) 如声称技术创新，提供原型/Demo 或可行性分析",
            "expected_output": "竞品深度对比矩阵 + 修订版差异化声明（含用户视角论证）",
            "teacher_talk_point": "和学生讨论：如果用户已经在用某个竞品，你凭什么让他换到你这里来？换的成本是什么？",
        },
        "risk_blind_spot": {
            "title": "补充风险分析",
            "advice": "1) 列出项目涉及的数据隐私、行业法规、资质许可等合规要求；2) 如涉及 AI/算法，讨论潜在偏见和公平性问题；3) 制定至少 2 个风险应对预案（如果某关键假设不成立怎么办）",
            "expected_output": "风险自查清单 + 合规要求清单 + 风险应对预案",
            "teacher_talk_point": "和学生讨论：你的项目最大的风险是什么？如果政策/法规不允许你这么做怎么办？",
        },
    }
    for sid in all_syndromes:
        if sid in advice_map:
            a = dict(advice_map[sid])
            related_projects = [pi["project_name"] for pi in project_issues if sid in pi.get("syndrome_ids", []) and pi.get("project_name")]
            if related_projects:
                a["related_projects"] = related_projects[:3]
            advice.append(a)
    if not advice and weakness_dims:
        cn_dims = [_dim_cn(d) for d in sorted(weakness_dims)[:3]]
        dim_str = "、".join(cn_dims)
        advice.append({
            "title": f"改善薄弱维度：{dim_str}",
            "advice": f"在{dim_str}方面加强论述深度，补充数据或案例支撑，确保每个论断都有对应证据",
            "expected_output": "修订版对应章节",
            "teacher_talk_point": f"和学生讨论{cn_dims[0]}方面的具体不足之处",
        })
    return advice[:4]


def _build_student_mini_summary(sp: dict, project_issues: list[dict], advice: list[dict], priority: str) -> dict:
    """Build a rich mini portrait for a student, visible in team-detail view."""
    portrait = sp.get("portrait", {})
    strengths = [_dim_cn(d) for d in (portrait.get("strength_dimensions") or [])[:3]]
    weaknesses = [_dim_cn(d) for d in (portrait.get("weakness_dimensions") or [])[:3]]
    behavior = portrait.get("behavioral_pattern", {})
    rubric = portrait.get("rubric_heatmap", [])
    best_rubric = max(rubric, key=lambda r: r.get("avg_score", 0), default=None) if rubric else None
    worst_rubric = min(rubric, key=lambda r: r.get("avg_score", 0), default=None) if rubric else None

    situation_bullets: list[str] = []
    for pi in project_issues[:3]:
        pname = pi.get("project_name") or "项目"
        title = pi.get("issue_title", "")
        summary = pi.get("issue_summary", "")
        if summary and len(summary) > 60:
            summary = summary[:58] + "..."
        situation_bullets.append(f"「{pname}」{title}：{summary}" if title else f"「{pname}」{summary}")

    if not situation_bullets:
        if sp.get("avg_score", 0) >= 7 and strengths:
            situation_bullets.append(f"整体表现良好，在{strengths[0]}方面尤为突出")
        elif sp.get("total_submissions", 0) == 0:
            situation_bullets.append("暂无提交记录，无法生成项目诊断")
        else:
            situation_bullets.append("暂未检测到明显系统性问题")

    advice_bullets: list[str] = []
    for a in advice[:3]:
        related = a.get("related_projects", [])
        prefix = f"（涉及{'、'.join(related[:2])}）" if related else ""
        advice_bullets.append(f"{a['title']}{prefix}：{a['advice'][:80]}...")
        if a.get("teacher_talk_point"):
            advice_bullets.append(f"  谈话要点 → {a['teacher_talk_point']}")

    overall = ""
    if priority == "high":
        main_issue = project_issues[0]["issue_title"] if project_issues else "多个维度薄弱"
        overall = f"该学生当前最大的问题是{main_issue}，建议教师本周优先与其面谈，围绕{advice[0]['title'] if advice else '薄弱环节'}展开辅导。"
    elif priority == "medium":
        overall = f"该学生存在一定共性问题，{'、'.join(weaknesses[:2]) if weaknesses else '部分维度'}需要关注，建议安排一次针对性讨论。"
    else:
        if strengths:
            overall = f"该学生整体状态稳定，{strengths[0]}表现突出。可引导其在已有基础上深化细节。"
        else:
            overall = "该学生整体状态平稳，暂无紧急干预需求。"

    return {
        "overall": overall,
        "situation_bullets": situation_bullets,
        "advice_bullets": advice_bullets,
        "strengths_cn": strengths,
        "weaknesses_cn": weaknesses,
        "best_dimension": _dim_cn(best_rubric["item"]) if best_rubric else None,
        "best_score": round(best_rubric["avg_score"], 1) if best_rubric else None,
        "worst_dimension": _dim_cn(worst_rubric["item"]) if worst_rubric else None,
        "worst_score": round(worst_rubric["avg_score"], 1) if worst_rubric else None,
        "submit_count": behavior.get("total_submissions", sp.get("total_submissions", 0)),
        "improvement_rate": behavior.get("improvement_rate", 0),
        "teacher_talk_points": [a.get("teacher_talk_point", "") for a in advice[:2] if a.get("teacher_talk_point")],
    }


@app.get("/api/teacher/team-diagnosis")
def teacher_team_diagnosis(teacher_id: str = "") -> dict:
    """Generate intervention-priority diagnosis cards for each team."""
    if not teacher_id:
        return {"teams": []}

    teams_raw = team_store.list_by_teacher(teacher_id)
    diagnosis_cards: list[dict] = []

    for team in teams_raw:
        tid = _safe_str(team.get("team_id", ""))
        tname = _safe_str(team.get("team_name", ""))
        members = list(team.get("members", []) or [])
        if not members:
            continue

        team_scores: list[float] = []
        team_risks = 0
        active_count = 0
        at_risk_students: list[dict] = []
        strength_pool: dict[str, int] = {}
        weakness_pool: dict[str, int] = {}
        student_project_map: list[dict] = []
        student_portraits: list[dict] = []
        student_projects_cache: dict[str, list] = {}

        for member in members:
            uid = _safe_str(member.get("user_id", ""))
            if not uid:
                continue
            info = user_store.get_by_id(uid)
            display_name = _safe_str((info or {}).get("display_name", uid[:8]))

            stats = _aggregate_student_data(uid, include_detail=True)
            avg_sc = float(stats.get("avg_score", 0) or 0)
            risk_c = int(stats.get("risk_count", 0) or 0)
            total_sub = int(stats.get("total_submissions", 0) or 0)

            if avg_sc > 0:
                team_scores.append(avg_sc)
            if total_sub > 0:
                active_count += 1
            team_risks += risk_c

            portrait = stats.get("portrait", {})
            for s in (portrait.get("strength_dimensions") or []):
                strength_pool[s] = strength_pool.get(s, 0) + 1
            for w in (portrait.get("weakness_dimensions") or []):
                weakness_pool[w] = weakness_pool.get(w, 0) + 1

            stu_projects = stats.get("projects") or []
            student_projects_cache[uid] = stu_projects
            for proj in stu_projects:
                proj_rules = _get_project_triggered_rules(proj)
                student_project_map.append({
                    "student_id": uid,
                    "display_name": display_name,
                    "project_id": proj.get("project_id", ""),
                    "project_name": proj.get("project_name", ""),
                    "avg_score": avg_sc,
                    "risk_count": risk_c,
                    "rules": proj_rules,
                })

            stu_card = {
                "student_id": uid,
                "display_name": display_name,
                "avg_score": avg_sc,
                "risk_count": risk_c,
                "total_submissions": total_sub,
                "latest_phase": stats.get("latest_phase", ""),
                "trend": stats.get("trend", 0),
                "portrait": portrait,
                "project_snapshots": stats.get("project_snapshots", [])[:3],
            }
            student_portraits.append(stu_card)

            if avg_sc > 0 and (avg_sc < 5.5 or risk_c >= 2):
                weak = portrait.get("weakness_dimensions", [])
                reason_parts = []
                if avg_sc < 5.5:
                    reason_parts.append(f"均分仅 {avg_sc}")
                if risk_c >= 2:
                    reason_parts.append(f"触发 {risk_c} 次风险")
                if weak:
                    reason_parts.append(f"薄弱: {', '.join(weak[:3])}")
                at_risk_students.append({
                    "student_id": uid,
                    "display_name": display_name,
                    "avg_score": avg_sc,
                    "risk_count": risk_c,
                    "reason": "；".join(reason_parts),
                    "weakness_dimensions": weak[:3],
                })

        team_avg = round(sum(team_scores) / len(team_scores), 1) if team_scores else 0
        health = _compute_team_health(team_avg, team_risks, active_count, len(members))

        top_weaknesses = sorted(weakness_pool.items(), key=lambda kv: kv[1], reverse=True)[:3]
        top_strengths = sorted(strength_pool.items(), key=lambda kv: kv[1], reverse=True)[:3]

        syndromes = _compute_syndromes(student_project_map, len(student_project_map))
        priority_intervention = _build_priority_intervention(syndromes, team_avg, top_strengths)

        crit_syndrome_ids = {s["id"] for s in syndromes if s["severity"] == "critical"}
        warn_syndrome_ids = {s["id"] for s in syndromes if s["severity"] == "warning"}
        for sp in student_portraits:
            uid = sp["student_id"]
            stu_projects = student_projects_cache.get(uid, [])
            sp["project_issues"] = _build_student_project_issues(stu_projects, syndromes)
            sp["actionable_advice"] = _build_student_advice(sp.get("portrait", {}), sp["project_issues"])
            has_critical = any(si in crit_syndrome_ids for pi in sp["project_issues"] for si in pi.get("syndrome_ids", []))
            has_warning = any(si in warn_syndrome_ids for pi in sp["project_issues"] for si in pi.get("syndrome_ids", []))
            sp["teacher_intervention_priority"] = "high" if has_critical else "medium" if has_warning else "low"
            sp["mini_summary"] = _build_student_mini_summary(sp, sp["project_issues"], sp["actionable_advice"], sp["teacher_intervention_priority"])

        active_ratio = round(active_count / max(len(members), 1) * 100)
        str_cn = [_dim_cn(s[0]) for s in top_strengths[:2]]
        weak_cn = [_dim_cn(w[0]) for w in top_weaknesses[:2]]
        high_pri = [sp for sp in student_portraits if sp["teacher_intervention_priority"] == "high"]
        med_pri = [sp for sp in student_portraits if sp["teacher_intervention_priority"] == "medium"]

        detail_bullets: list[str] = []
        if team_avg > 0:
            if team_avg >= 7:
                detail_bullets.append(f"团队均分 {team_avg}，整体表现良好。{len(members)} 名成员中 {active_count} 人活跃（{active_ratio}%）")
            elif team_avg >= 5:
                detail_bullets.append(f"团队均分 {team_avg}，处于中等水平。{len(members)} 名成员中 {active_count} 人活跃（{active_ratio}%）")
            else:
                detail_bullets.append(f"团队均分仅 {team_avg}，整体水平偏低，需要重点关注。活跃率 {active_ratio}%")
        for syn in syndromes:
            if syn["severity"] in ("critical", "warning"):
                names = "、".join(a["display_name"] for a in syn.get("affected_students", [])[:3])
                detail_bullets.append(
                    f"{'紧急' if syn['severity'] == 'critical' else '关注'}：{syn['label']} — "
                    f"{syn['description']}（涉及 {names}）"
                )
        if weak_cn:
            weak_ratio = max((w[1] for w in top_weaknesses[:1]), default=0)
            detail_bullets.append(f"最突出的共性短板是「{weak_cn[0]}」，{weak_ratio}/{len(members)} 名学生在此维度得分偏低")
        if str_cn:
            str_ratio = max((s[1] for s in top_strengths[:1]), default=0)
            detail_bullets.append(f"团队优势集中在「{str_cn[0]}」，{str_ratio}/{len(members)} 名学生在此维度表现突出")
        if high_pri:
            names = "、".join(sp["display_name"] for sp in high_pri[:3])
            detail_bullets.append(f"需优先干预的学生：{names}（共 {len(high_pri)} 人）")
        elif med_pri:
            names = "、".join(sp["display_name"] for sp in med_pri[:3])
            detail_bullets.append(f"需关注的学生：{names}（共 {len(med_pri)} 人）")
        if not detail_bullets:
            detail_bullets.append("数据不足，暂无法生成团队画像")

        overall_parts: list[str] = []
        if syndromes and syndromes[0]["severity"] in ("critical", "warning"):
            s0 = syndromes[0]
            overall_parts.append(f"当前最需关注的问题是「{s0['label']}」")
            if s0.get("intervention_steps"):
                overall_parts.append(f"建议本周优先开展「{s0['intervention_steps'][0]['title']}」")
        elif high_pri:
            overall_parts.append(f"建议优先与 {high_pri[0]['display_name']} 面谈")
        if weak_cn:
            overall_parts.append(f"教学重点放在「{weak_cn[0]}」方面的补强")
        overall_assessment = "；".join(overall_parts) + "。" if overall_parts else "团队整体状态稳定，可引导学生在已有基础上深化细节。"

        # ── Aggregate rubric heatmap across team ──
        rubric_agg: dict[str, list[float]] = {}
        all_submissions_counts: list[int] = []
        all_trends: list[float] = []
        rule_counter: dict[str, int] = {}
        for sp in student_portraits:
            port = sp.get("portrait", {})
            for rh in (port.get("rubric_heatmap") or []):
                if isinstance(rh, dict) and rh.get("item"):
                    rubric_agg.setdefault(rh["item"], []).append(float(rh.get("avg_score", 0) or 0))
            all_submissions_counts.append(int(sp.get("total_submissions", 0) or 0))
            t = float(sp.get("trend", 0) or 0)
            if sp.get("total_submissions", 0) > 0:
                all_trends.append(t)
            for proj in student_projects_cache.get(sp["student_id"], []):
                for rid in _get_project_triggered_rules(proj):
                    rule_counter[rid] = rule_counter.get(rid, 0) + 1

        rubric_heatmap_team = []
        for rname, scores in sorted(rubric_agg.items(), key=lambda kv: sum(kv[1]) / len(kv[1]) if kv[1] else 0):
            avg_v = round(sum(scores) / len(scores), 1) if scores else 0
            sorted_scores = sorted(scores)
            lo = round(sorted_scores[0], 1) if sorted_scores else 0
            hi = round(sorted_scores[-1], 1) if sorted_scores else 0
            zone = "优势区" if avg_v >= 7 else ("平均区" if avg_v >= 5 else "短板区")
            dim_cn = _dim_cn(rname)
            show_scores = [f"{s:.1f}" for s in sorted_scores[:8]]
            more_suffix = " + …" if len(sorted_scores) > 8 else ""
            team_rationale = {
                "field": f"rubric_heatmap_team:{rname}",
                "value": avg_v,
                "formula": "avg(per_student_dim_avg) where per_student = avg(submission_scores)",
                "formula_display": (
                    f"团队 {dim_cn}（{rname}） 均分 = Σ(每位学生该维度均分) ÷ {len(scores)}\n"
                    f"= ({' + '.join(show_scores)}{more_suffix}) ÷ {len(scores)}\n"
                    f"= {avg_v}（最低 {lo} · 最高 {hi} · 样本 {len(scores)} 人）\n"
                    f"归属：{zone}（≥7 优势 / 5-6.9 平均 / <5 短板）"
                ),
                "inputs": [
                    {"label": f"学生 {i+1}", "value": round(float(s), 2)}
                    for i, s in enumerate(sorted_scores[:12])
                ],
                "note": f"{zone} · {len(scores)} 人样本",
            }
            rubric_heatmap_team.append({
                "item": rname,
                "item_cn": dim_cn,
                "avg_score": avg_v,
                "sample_count": len(scores),
                "rationale": team_rationale,
            })

        score_distribution = {
            "good": sum(1 for sp in student_portraits if sp.get("avg_score", 0) >= 7),
            "average": sum(1 for sp in student_portraits if 5 <= sp.get("avg_score", 0) < 7),
            "weak": sum(1 for sp in student_portraits if 0 < sp.get("avg_score", 0) < 5),
            "no_data": sum(1 for sp in student_portraits if sp.get("avg_score", 0) <= 0),
        }

        non_zero_subs = [c for c in all_submissions_counts if c > 0]
        max_sub_sp = max(student_portraits, key=lambda sp: sp.get("total_submissions", 0), default=None) if student_portraits else None
        min_sub_sp = min((sp for sp in student_portraits if sp.get("total_submissions", 0) > 0), key=lambda sp: sp["total_submissions"], default=None)
        engagement_stats = {
            "avg_submissions": round(sum(non_zero_subs) / len(non_zero_subs), 1) if non_zero_subs else 0,
            "max_submissions": max(all_submissions_counts) if all_submissions_counts else 0,
            "min_submissions": min(non_zero_subs) if non_zero_subs else 0,
            "max_name": max_sub_sp["display_name"] if max_sub_sp else "",
            "min_name": min_sub_sp["display_name"] if min_sub_sp else "",
            "total_submissions": sum(all_submissions_counts),
        }

        improving = sum(1 for t in all_trends if t > 0)
        declining = sum(1 for t in all_trends if t < 0)
        active_with_data = len(all_trends)
        if active_with_data > 0:
            if improving > declining:
                trend_summary = f"近期 {improving}/{active_with_data} 名活跃学生呈进步趋势"
            elif declining > improving:
                trend_summary = f"近期 {declining}/{active_with_data} 名活跃学生成绩下滑，需关注"
            else:
                trend_summary = f"{active_with_data} 名活跃学生成绩波动不大，整体稳定"
        else:
            trend_summary = "数据不足，暂无法判断趋势"

        risk_rule_top3 = sorted(rule_counter.items(), key=lambda kv: kv[1], reverse=True)[:3]
        risk_rule_top3_list = [{"rule_id": rid, "count": cnt, "label": _dim_cn(rid) if rid in DIM_CN else rid} for rid, cnt in risk_rule_top3]

        team_portrait = {
            "summary": detail_bullets[0] if detail_bullets else "",
            "health_label": "良好" if health["level"] == "healthy" else "一般" if health["level"] == "warning" else "需关注",
            "active_ratio": active_ratio,
            "top_strengths": str_cn,
            "top_weaknesses": weak_cn,
            "detail_bullets": detail_bullets,
            "overall_assessment": overall_assessment,
            "syndrome_count": len(syndromes),
            "critical_count": sum(1 for s in syndromes if s["severity"] == "critical"),
            "warning_count": sum(1 for s in syndromes if s["severity"] == "warning"),
            "high_priority_count": len(high_pri),
            "medium_priority_count": len(med_pri),
            "rubric_heatmap_team": rubric_heatmap_team,
            "score_distribution": score_distribution,
            "engagement_stats": engagement_stats,
            "trend_summary": trend_summary,
            "risk_rule_top3": risk_rule_top3_list,
        }

        diagnosis_cards.append({
            "team_id": tid,
            "team_name": tname,
            "member_count": len(members),
            "active_count": active_count,
            "team_avg_score": team_avg,
            "team_risk_count": team_risks,
            "health_score": health["score"],
            "health_level": health["level"],
            "health_summary": health["summary"],
            "priority_intervention": priority_intervention,
            "team_portrait": team_portrait,
            "syndromes": syndromes,
            "at_risk_students": at_risk_students,
            "top_weaknesses": [{"dim": w[0], "count": w[1]} for w in top_weaknesses],
            "top_strengths": [{"dim": s[0], "count": s[1]} for s in top_strengths],
            "student_portraits": student_portraits,
        })

    diagnosis_cards.sort(key=lambda c: c["health_score"])
    return {"teams": diagnosis_cards}


def _compute_team_health(avg_score: float, risk_count: int, active: int, total: int) -> dict:
    """Compute a 0-100 health score for a team."""
    score = 50.0
    if avg_score > 0:
        score = min(40, avg_score * 5)
    active_ratio = (active / max(total, 1))
    score += active_ratio * 30
    risk_penalty = min(30, risk_count * 3)
    score = max(0, min(100, score - risk_penalty + 20))
    score = round(score, 1)
    if score >= 75:
        level = "healthy"
        summary = "团队整体状态良好，继续保持。"
    elif score >= 50:
        level = "warning"
        summary = "部分学生需要关注，建议针对性辅导。"
    else:
        level = "critical"
        summary = "团队需要紧急干预，多名学生存在风险。"
    return {"score": score, "level": level, "summary": summary}


# ══════════════════════════════════════════════════════════════════
# 学生画像 / 教师订正 / 证据溯源  ——  新增接口
# ══════════════════════════════════════════════════════════════════

def _apply_overrides_everywhere(payload: dict, project_id: str, conversation_ids: list[str | None] | None = None) -> dict:
    """在任意返回对象上批量应用教师订正（直接 walk 所有 rationale）。"""
    try:
        cids: list[str | None] = conversation_ids if conversation_ids is not None else [None]
        overrides = ai_override_store.list_many(project_id, cids)
        if overrides:
            _ov_walk_apply(payload, overrides)
    except Exception as exc:  # noqa: BLE001
        logger.debug("apply overrides failed: %s", exc)
    return payload


def _link_triggered_rule_messages(
    project_id: str,
    conversation_id: str,
    triggered_rules: list[dict],
) -> None:
    """原地为每条 triggered_rule 补 source_message 信息。"""
    if not triggered_rules or not conversation_id:
        return
    for rule in triggered_rules:
        if not isinstance(rule, dict):
            continue
        quote = str(rule.get("quote") or "").strip()
        if not quote:
            continue
        hits = evidence_linker.link_text(project_id, conversation_id, quote, top_k=1)
        if hits:
            h = hits[0]
            rule["source_message_id"] = h["message_id"]
            rule["source_message_turn"] = h["turn_index"]
            rule["source_message_role"] = h["role"]
            rule["source_message_excerpt"] = h["excerpt"]
            rule["source_message_confidence"] = h["confidence"]


# ───────────────── 学生画像 endpoints ─────────────────
def _compute_student_health(avg_score: float, risk_count: int, submission_count: int) -> dict:
    """单学生 0-100 健康指数（与团队同风格）。"""
    score = 40.0
    if avg_score > 0:
        score = min(60, avg_score * 7)
    activity_bonus = min(20, submission_count * 4)
    score += activity_bonus
    risk_penalty = min(30, risk_count * 2)
    score = max(0, min(100, score - risk_penalty + 10))
    score = round(score, 1)
    if score >= 75:
        level, label = "healthy", "表现良好"
    elif score >= 50:
        level, label = "warning", "一般可提升"
    else:
        level, label = "critical", "需重点关注"
    return {"score": score, "level": level, "label": label}


def _build_student_panorama(
    submissions: list[dict],
    rubric_heatmap: list[dict],
    avg_score: float,
    trend: float,
    risk_count: int,
    strength_dims: list[str],
    weakness_dims: list[str],
    scope_label: str = "全部会话",
) -> dict:
    """把单学生（或单会话）聚合数据整理成与团队画像同 schema 的 panorama 结构。"""
    total_subs = len(submissions or [])
    # Health
    health = _compute_student_health(avg_score, risk_count, total_subs)

    # rubric_heatmap 补 item_cn
    heatmap_team_style = []
    for rh in (rubric_heatmap or []):
        if not isinstance(rh, dict) or not rh.get("item"):
            continue
        heatmap_team_style.append({
            "item": rh["item"],
            "item_cn": _dim_cn(rh["item"]),
            "avg_score": rh.get("avg_score", 0),
            "sample_count": rh.get("count", 0),
        })
    heatmap_team_style.sort(key=lambda h: h["avg_score"])

    # 中文强/弱
    top_strengths_cn = [_dim_cn(d) for d in (strength_dims or [])[:3]]
    top_weaknesses_cn = [_dim_cn(d) for d in (weakness_dims or [])[:3]]

    # 风险 Top3
    rule_counter: dict[str, int] = {}
    score_distribution = {"good": 0, "average": 0, "weak": 0, "no_data": 0}
    recent_scores: list[float] = []
    for s in (submissions or []):
        sc = 0.0
        diag = s.get("diagnosis") or {}
        if isinstance(diag, dict):
            sc = float(diag.get("overall_score", 0) or 0)
        if not sc:
            sc = float(s.get("overall_score", 0) or 0)
        if sc >= 7:
            score_distribution["good"] += 1
        elif sc >= 5:
            score_distribution["average"] += 1
        elif sc > 0:
            score_distribution["weak"] += 1
        else:
            score_distribution["no_data"] += 1
        if sc > 0:
            recent_scores.append(sc)
        triggered = s.get("triggered_rules") or []
        if not triggered and isinstance(diag, dict):
            triggered = diag.get("triggered_rules") or []
        for tr in triggered:
            if isinstance(tr, dict):
                rid = str(tr.get("id") or tr.get("rule_id") or "")
            else:
                rid = str(tr or "")
            if rid:
                rule_counter[rid] = rule_counter.get(rid, 0) + 1
    risk_top3 = sorted(rule_counter.items(), key=lambda kv: kv[1], reverse=True)[:3]
    risk_rule_top3_list = [
        {"rule_id": rid, "count": cnt, "label": _dim_cn(rid) if rid in DIM_CN else rid}
        for rid, cnt in risk_top3
    ]

    # Engagement（单学生语义：总提交、近 7 天节奏、最近一次）
    engagement_stats = {
        "total_submissions": total_subs,
        "scored_count": len(recent_scores),
        "risk_count": risk_count,
    }

    # trend_summary
    if total_subs >= 4:
        if trend > 0.3:
            trend_summary = f"近期趋势 +{trend:.1f}，呈稳步进步"
        elif trend < -0.3:
            trend_summary = f"近期趋势 {trend:.1f}，需关注回落"
        else:
            trend_summary = f"近期波动 {trend:+.1f}，整体平稳"
    elif total_subs > 0:
        trend_summary = "数据量较少，暂无法判断趋势"
    else:
        trend_summary = "尚无诊断数据"

    # detail_bullets
    detail_bullets: list[str] = []
    if avg_score > 0:
        detail_bullets.append(f"{scope_label}均分 {avg_score}/10，健康指数 {health['score']}")
    else:
        detail_bullets.append(f"{scope_label}尚无完整打分数据，先完成一次提交即可建立画像")
    if top_strengths_cn:
        detail_bullets.append(f"优势维度：{'、'.join(top_strengths_cn)}")
    if top_weaknesses_cn:
        detail_bullets.append(f"待加强：{'、'.join(top_weaknesses_cn)}")
    if risk_rule_top3_list:
        detail_bullets.append(
            "高频风险："
            + "、".join(f"{r['rule_id']}({r['count']}次)" for r in risk_rule_top3_list)
        )

    # overall_assessment
    parts: list[str] = []
    if health["level"] == "healthy":
        parts.append(f"整体表现良好（{health['score']}）")
    elif health["level"] == "warning":
        parts.append(f"整体中等水平（{health['score']}），有提升空间")
    else:
        parts.append(f"整体需要重点关注（{health['score']}）")
    if top_strengths_cn:
        parts.append(f"继续保持「{top_strengths_cn[0]}」优势")
    if top_weaknesses_cn:
        parts.append(f"优先补强「{top_weaknesses_cn[0]}」")
    if risk_rule_top3_list:
        parts.append(f"当前最高频风险为 {risk_rule_top3_list[0]['rule_id']}")
    overall_assessment = "；".join(parts) + "。"

    return {
        "health_score": health["score"],
        "health_level": health["level"],
        "health_label": health["label"],
        "rubric_heatmap_team": heatmap_team_style,
        "top_strengths": top_strengths_cn,
        "top_weaknesses": top_weaknesses_cn,
        "risk_rule_top3": risk_rule_top3_list,
        "engagement_stats": engagement_stats,
        "trend_summary": trend_summary,
        "overall_assessment": overall_assessment,
        "detail_bullets": detail_bullets,
        "score_distribution": score_distribution,
    }


@app.get("/api/student/{user_id}/portrait/overall")
def student_portrait_overall(user_id: str) -> dict:
    """学生总画像：跨所有会话聚合。"""
    data = _aggregate_student_data(user_id, include_detail=True)
    portrait = dict(data.get("portrait") or {})
    portrait["total_submissions"] = data.get("total_submissions", 0)
    portrait["project_count"] = data.get("project_count", 0)
    portrait["avg_score"] = data.get("avg_score", 0.0)
    portrait["trend"] = data.get("trend", 0.0)
    portrait["risk_count"] = data.get("risk_count", 0)
    portrait["latest_phase"] = data.get("latest_phase", "")
    portrait["intent_distribution"] = data.get("intent_distribution", {}) or {}
    portrait["intent_shape_distribution"] = data.get("intent_shape_distribution", {}) or {}
    portrait["student_case_summary"] = data.get("student_case_summary", "") or ""
    # 团队画像同结构字段（panorama）
    project_id = f"project-{user_id}"
    project = json_store.load_project(project_id)
    all_subs = list(project.get("submissions", []) or [])
    panorama = _build_student_panorama(
        submissions=all_subs,
        rubric_heatmap=portrait.get("rubric_heatmap") or [],
        avg_score=float(data.get("avg_score", 0.0) or 0.0),
        trend=float(data.get("trend", 0.0) or 0.0),
        risk_count=int(data.get("risk_count", 0) or 0),
        strength_dims=portrait.get("strength_dimensions") or [],
        weakness_dims=portrait.get("weakness_dimensions") or [],
        scope_label="总画像",
    )
    portrait.update(panorama)
    # 汇总用：overview_rationale 说明这张画像是如何算出来的
    portrait["overview_rationale"] = {
        "field": "portrait:overall",
        "value": data.get("avg_score", 0.0),
        "formula": "avg(scores across all submissions)",
        "formula_display": (
            f"总画像聚合了该学生全部 {data.get('total_submissions', 0)} 条提交，"
            f"分布在 {data.get('project_count', 0)} 个项目（会话）上。\n"
            f"综合均分 = 全部打分的算术平均 = {data.get('avg_score', 0.0)}\n"
            f"近中期变化 = {data.get('trend', 0.0):+.1f}\n"
            f"健康指数 = {panorama['health_score']}（{panorama['health_label']}）"
        ),
        "inputs": [
            {"label": "项目数", "value": data.get("project_count", 0)},
            {"label": "提交数", "value": data.get("total_submissions", 0)},
            {"label": "触发风险次数", "value": data.get("risk_count", 0)},
            {"label": "健康指数", "value": panorama["health_score"]},
        ],
        "note": "默认按所有会话聚合，若要按会话单独查看请切换 Tab。",
    }
    all_cids = [None] + [str((c.get("conversation_id") or "")) for c in conv_store.list_conversations(project_id)]
    return _apply_overrides_everywhere({"portrait": portrait}, project_id, all_cids)


@app.get("/api/student/{user_id}/portrait/conversations")
def student_portrait_conversations(user_id: str) -> dict:
    """学生按会话的画像列表：每个会话一张卡（轻量版）。"""
    project_id = f"project-{user_id}"
    data = _aggregate_student_data(user_id, include_detail=True)
    project_snapshots = data.get("project_snapshots") or []
    # 会话列表（精简：取每个 conversation_id 最近一次画像切面）
    convs = conv_store.list_conversations(project_id)
    conv_meta = {str(c["conversation_id"]): c for c in convs}
    # 把 project_snapshots 按 project_id 对齐 conversation_id（约定两者相同时）
    cards = []
    for snap in project_snapshots:
        cid = str(snap.get("project_id") or "")
        meta = conv_meta.get(cid, {}) if cid else {}
        cards.append({
            "conversation_id": cid,
            "title": meta.get("title") or snap.get("project_name") or cid[:8],
            "last_score": snap.get("latest_score", 0),
            "project_phase": snap.get("project_phase", ""),
            "summary": snap.get("current_summary", ""),
            "top_risks": snap.get("top_risks", []),
            "intent_distribution": snap.get("intent_distribution", {}),
            "message_count": meta.get("message_count", 0),
            "created_at": meta.get("created_at", ""),
        })
    return _apply_overrides_everywhere(
        {"project_id": project_id, "cards": cards},
        project_id,
        [c["conversation_id"] for c in cards if c.get("conversation_id")],
    )


@app.get("/api/student/{user_id}/portrait/conversation/{conversation_id}")
def student_portrait_conversation_detail(user_id: str, conversation_id: str) -> dict:
    """单个会话的画像详情：rubric 趋势、风险、成熟度、消息数量等。"""
    project_id = f"project-{user_id}"
    data = _aggregate_student_data(user_id, include_detail=True)
    proj = next((p for p in (data.get("projects") or []) if p.get("project_id") == conversation_id), None)
    if not proj:
        return {"status": "not_found", "conversation_id": conversation_id}
    # 本会话的原始 submissions（用于 panorama 的风险统计）
    proj_raw_subs = [
        s for s in (json_store.load_project(project_id).get("submissions") or [])
        if _safe_str(s.get("logical_project_id") or s.get("project_id") or s.get("conversation_id") or "") == conversation_id
    ]
    # 本会话的 rubric heatmap
    rubric_scores: dict[str, list[float]] = {}
    for sub in proj.get("submissions", []):
        diag = sub.get("diagnosis") or {}
        for r in (diag.get("rubric") or []):
            if isinstance(r, dict) and r.get("item"):
                rubric_scores.setdefault(r["item"], []).append(float(r.get("score", 0) or 0))
    heatmap = []
    strength_dims_conv: list[str] = []
    weakness_dims_conv: list[str] = []
    for name, arr in rubric_scores.items():
        avg_rs = round(sum(arr) / len(arr), 2) if arr else 0
        if avg_rs >= 7:
            strength_dims_conv.append(name)
        elif avg_rs < 5:
            weakness_dims_conv.append(name)
        heatmap.append({
            "item": name,
            "avg_score": avg_rs,
            "count": len(arr),
            "rationale": {
                "field": f"rubric_heatmap:{conversation_id}:{name}",
                "value": avg_rs,
                "formula": "avg(dim scores in this conversation)",
                "formula_display": (
                    f"本会话 {name} 均分 = ({' + '.join(f'{x:.1f}' for x in arr[:6])}"
                    + (" + …" if len(arr) > 6 else "")
                    + f") ÷ {len(arr)} = {avg_rs}"
                ),
                "inputs": [{"label": f"第{i+1}次", "value": round(float(x), 2)} for i, x in enumerate(arr[:10])],
                "note": f"仅统计本会话 {len(arr)} 次评分",
            },
        })
    # 本会话趋势
    p_scores = []
    for sub in proj.get("submissions", []):
        sc = float(sub.get("overall_score", 0) or 0)
        if not sc:
            diag = sub.get("diagnosis") or {}
            sc = float(diag.get("overall_score", 0) or 0) if isinstance(diag, dict) else 0
        if sc > 0:
            p_scores.append(sc)
    conv_avg = round(sum(p_scores) / len(p_scores), 1) if p_scores else 0.0
    conv_trend = 0.0
    if len(p_scores) >= 4:
        mid = len(p_scores) // 2
        conv_trend = round(sum(p_scores[mid:]) / (len(p_scores) - mid) - sum(p_scores[:mid]) / mid, 1)
    conv_risk_count = sum(1 for s in proj_raw_subs if (s.get("triggered_rules") or []))

    panorama = _build_student_panorama(
        submissions=proj_raw_subs,
        rubric_heatmap=heatmap,
        avg_score=conv_avg,
        trend=conv_trend,
        risk_count=conv_risk_count,
        strength_dims=strength_dims_conv,
        weakness_dims=weakness_dims_conv,
        scope_label="本会话",
    )
    # 本会话的最近一次 maturity（从最新 bp 取）
    try:
        latest_bp = business_plan_service.get_latest(project_id, conversation_id) or {}
    except Exception:
        latest_bp = {}
    maturity_snapshot = (latest_bp.get("readiness") or {}) if isinstance(latest_bp, dict) else {}
    # 提供与 overall 对齐的 portrait 对象
    portrait_payload = {
        **panorama,
        "avg_score": conv_avg,
        "trend": conv_trend,
        "risk_count": conv_risk_count,
        "total_submissions": len(proj_raw_subs),
        "rubric_heatmap": heatmap,
        "strength_dimensions": strength_dims_conv,
        "weakness_dimensions": weakness_dims_conv,
        "latest_phase": proj.get("project_phase", ""),
        "overview_rationale": {
            "field": f"portrait:conversation:{conversation_id}",
            "value": conv_avg,
            "formula": "avg(scores in this conversation)",
            "formula_display": (
                f"本会话共 {len(proj_raw_subs)} 次提交，\n"
                f"有效打分 {len(p_scores)} 次 → 均分 {conv_avg}\n"
                f"近中期变化 {conv_trend:+.1f}\n"
                f"健康指数 = {panorama['health_score']}（{panorama['health_label']}）"
            ),
            "inputs": [
                {"label": "提交数", "value": len(proj_raw_subs)},
                {"label": "有效打分", "value": len(p_scores)},
                {"label": "触发风险次数", "value": conv_risk_count},
                {"label": "健康指数", "value": panorama["health_score"]},
            ],
            "note": "只统计该会话（项目）内的数据",
        },
    }
    payload = {
        "conversation_id": conversation_id,
        "project_card": proj,
        "rubric_heatmap": heatmap,
        "maturity_snapshot": maturity_snapshot,
        "portrait": portrait_payload,
    }
    return _apply_overrides_everywhere(payload, project_id, [conversation_id, None])


# ───────────────── 教师订正 endpoints ─────────────────
@app.get("/api/teacher/overrides")
def teacher_overrides_list(
    project_id: str,
    conversation_id: str = "",
    target_type: str = "",
    target_key: str = "",
) -> dict:
    cid = conversation_id.strip() or None
    return {
        "overrides": ai_override_store.list(
            project_id,
            cid,
            target_type=target_type or None,
            target_key=target_key or None,
        )
    }


@app.post("/api/teacher/overrides")
def teacher_overrides_upsert(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {"status": "error", "detail": "invalid payload"}
    try:
        record = ai_override_store.upsert(payload)
        return {"status": "ok", "override": record}
    except ValueError as exc:
        return {"status": "error", "detail": str(exc)}


@app.delete("/api/teacher/overrides/{override_id}")
def teacher_overrides_delete(override_id: str, project_id: str, conversation_id: str = "") -> dict:
    cid = conversation_id.strip() or None
    ok = ai_override_store.delete(project_id, cid, override_id)
    return {"status": "ok" if ok else "not_found"}


# ───────────────── 重构版 evidence-trace ─────────────────
@app.get("/api/teacher/project/{project_id}/evidence-trace-v2")
def teacher_project_evidence_trace_v2(project_id: str, logical_project_id: str = "") -> dict:
    """「按结论分组」的证据树：每个 rubric 维度 / 风险规则 / 综合分 都单独成组，
    其下挂相关证据消息（含 source_message_id）。前端可以直接树形渲染。"""
    project_state = json_store.load_project(project_id)
    filtered_subs = _project_submissions_by_logical_id(project_state, logical_project_id)
    if not filtered_subs:
        return {
            "project_id": project_id,
            "logical_project_id": logical_project_id,
            "error": "该项目暂无可用于证据溯源的提交记录",
        }
    evidence_chain = _assessment_evidence_chain(filtered_subs)

    # 收集每个 submission 对应的 conversation_id，用于消息回定
    sub_to_cid: dict[str, str] = {}
    for sub in filtered_subs:
        sid = str(sub.get("submission_id") or "")
        cid = str(sub.get("conversation_id") or "")
        if sid:
            sub_to_cid[sid] = cid

    # 1) rubric 维度分组
    rubric_groups: dict[str, dict] = {}
    rule_groups: dict[str, dict] = {}
    for row in evidence_chain:
        sid = str(row.get("submission_id") or "")
        cid = sub_to_cid.get(sid, "")
        quote = str(row.get("quote") or "")
        link = None
        if cid and quote:
            links = evidence_linker.link_text(project_id, cid, quote, top_k=1)
            link = links[0] if links else None
        enriched_ev = {
            **row,
            "conversation_id": cid,
            "source_message_id": (link or {}).get("message_id"),
            "source_message_turn": (link or {}).get("turn_index"),
            "source_message_role": (link or {}).get("role"),
            "source_message_confidence": (link or {}).get("confidence"),
        }
        for rubric in (row.get("rubric_items") or []):
            bucket = rubric_groups.setdefault(rubric, {
                "conclusion_type": "rubric",
                "conclusion_key": rubric,
                "label": rubric,
                "evidence": [],
            })
            bucket["evidence"].append(enriched_ev)
        for rid in (row.get("rule_ids") or []):
            rid_u = str(rid).upper()
            if not rid_u:
                continue
            bucket = rule_groups.setdefault(rid_u, {
                "conclusion_type": "risk",
                "conclusion_key": rid_u,
                "label": f"{rid_u} · {get_rule_name(rid_u)}",
                "fallacy": RULE_FALLACY_MAP.get(rid_u, ""),
                "edge_families": RULE_EDGE_MAP.get(rid_u, []),
                "evidence": [],
            })
            bucket["evidence"].append(enriched_ev)

    # 2) 综合分分组 —— 把最近一次 diagnosis 的 overall_rationale 拿出来
    overall_group = None
    tier1_groups: list[dict] = []
    last_sub = filtered_subs[-1] if filtered_subs else None
    last_diag_obj: dict = {}
    if last_sub:
        last_diag_obj = last_sub.get("diagnosis") or {}
        overall_rat = last_diag_obj.get("overall_rationale")
        if overall_rat:
            overall_group = {
                "conclusion_type": "overall",
                "conclusion_key": "overall",
                "label": "综合分",
                "rationale": overall_rat,
                "evidence": [],
            }
        # ── Tier 1：挂上 project_phase / bottleneck / summary / next_task 的 rationale ──
        for tier1_key, tier1_label, tier1_rat_key in [
            ("project_phase", "项目阶段判定", "project_phase_rationale"),
            ("bottleneck", "核心瓶颈", "bottleneck_rationale"),
            ("summary", "诊断总结", "summary_rationale"),
        ]:
            rat = last_diag_obj.get(tier1_rat_key)
            if rat:
                tier1_groups.append({
                    "conclusion_type": "tier1",
                    "conclusion_key": tier1_key,
                    "label": tier1_label,
                    "rationale": rat,
                    "evidence": [],
                })
        # next_task 的 rationale 放在 next_task.rationale 里
        last_next = last_sub.get("next_task") or {}
        if isinstance(last_next, dict) and last_next.get("rationale"):
            tier1_groups.append({
                "conclusion_type": "tier1",
                "conclusion_key": "next_task",
                "label": "下一步任务",
                "rationale": last_next.get("rationale"),
                "evidence": [],
            })

    # ── 把每个 rubric 维度的 rationale（含 reasoning_steps）挂到分组 ──
    if last_diag_obj:
        for _rb in (last_diag_obj.get("rubric") or []):
            if not isinstance(_rb, dict):
                continue
            _item = str(_rb.get("item") or "")
            if not _item or _item not in rubric_groups:
                # 如果有 rubric 但没有证据也露出 rationale
                if _item and _rb.get("rationale"):
                    rubric_groups[_item] = {
                        "conclusion_type": "rubric",
                        "conclusion_key": _item,
                        "label": _item,
                        "evidence": [],
                    }
            if _item and _rb.get("rationale") and _item in rubric_groups:
                rubric_groups[_item]["rationale"] = _rb.get("rationale")
                rubric_groups[_item]["score"] = _rb.get("score")

    all_cids = list({cid for cid in sub_to_cid.values() if cid})
    payload = {
        "project_id": project_id,
        "logical_project_id": logical_project_id,
        "overall": overall_group,
        "tier1_groups": tier1_groups,
        "rubric_groups": sorted(rubric_groups.values(), key=lambda g: -len(g["evidence"])),
        "rule_groups": sorted(rule_groups.values(), key=lambda g: -len(g["evidence"])),
        "total_evidence": sum(len(g["evidence"]) for g in rubric_groups.values())
                         + sum(len(g["evidence"]) for g in rule_groups.values()),
    }
    return _apply_overrides_everywhere(payload, project_id, all_cids or [None])



# ══════════════════════════════════════════════════════════════════
# 学生画像 / 教师订正 / 证据溯源  ——  新增接口
# ══════════════════════════════════════════════════════════════════

def _apply_overrides_everywhere(payload: dict, project_id: str, conversation_ids: list[str | None] | None = None) -> dict:
    """在任意返回对象上批量应用教师订正（直接 walk 所有 rationale）。"""
    try:
        cids: list[str | None] = conversation_ids if conversation_ids is not None else [None]
        overrides = ai_override_store.list_many(project_id, cids)
        if overrides:
            _ov_walk_apply(payload, overrides)
    except Exception as exc:  # noqa: BLE001
        logger.debug("apply overrides failed: %s", exc)
    return payload


def _link_triggered_rule_messages(
    project_id: str,
    conversation_id: str,
    triggered_rules: list[dict],
) -> None:
    """原地为每条 triggered_rule 补 source_message 信息。"""
    if not triggered_rules or not conversation_id:
        return
    for rule in triggered_rules:
        if not isinstance(rule, dict):
            continue
        quote = str(rule.get("quote") or "").strip()
        if not quote:
            continue
        hits = evidence_linker.link_text(project_id, conversation_id, quote, top_k=1)
        if hits:
            h = hits[0]
            rule["source_message_id"] = h["message_id"]
            rule["source_message_turn"] = h["turn_index"]
            rule["source_message_role"] = h["role"]
            rule["source_message_excerpt"] = h["excerpt"]
            rule["source_message_confidence"] = h["confidence"]


# ───────────────── 学生画像 endpoints ─────────────────
def _compute_student_health(avg_score: float, risk_count: int, submission_count: int) -> dict:
    """单学生 0-100 健康指数（与团队同风格）。"""
    score = 40.0
    if avg_score > 0:
        score = min(60, avg_score * 7)
    activity_bonus = min(20, submission_count * 4)
    score += activity_bonus
    risk_penalty = min(30, risk_count * 2)
    score = max(0, min(100, score - risk_penalty + 10))
    score = round(score, 1)
    if score >= 75:
        level, label = "healthy", "表现良好"
    elif score >= 50:
        level, label = "warning", "一般可提升"
    else:
        level, label = "critical", "需重点关注"
    return {"score": score, "level": level, "label": label}


def _build_student_panorama(
    submissions: list[dict],
    rubric_heatmap: list[dict],
    avg_score: float,
    trend: float,
    risk_count: int,
    strength_dims: list[str],
    weakness_dims: list[str],
    scope_label: str = "全部会话",
) -> dict:
    """把单学生（或单会话）聚合数据整理成与团队画像同 schema 的 panorama 结构。"""
    total_subs = len(submissions or [])
    # Health
    health = _compute_student_health(avg_score, risk_count, total_subs)

    # rubric_heatmap 补 item_cn
    heatmap_team_style = []
    for rh in (rubric_heatmap or []):
        if not isinstance(rh, dict) or not rh.get("item"):
            continue
        heatmap_team_style.append({
            "item": rh["item"],
            "item_cn": _dim_cn(rh["item"]),
            "avg_score": rh.get("avg_score", 0),
            "sample_count": rh.get("count", 0),
        })
    heatmap_team_style.sort(key=lambda h: h["avg_score"])

    # 中文强/弱
    top_strengths_cn = [_dim_cn(d) for d in (strength_dims or [])[:3]]
    top_weaknesses_cn = [_dim_cn(d) for d in (weakness_dims or [])[:3]]

    # 风险 Top3
    rule_counter: dict[str, int] = {}
    score_distribution = {"good": 0, "average": 0, "weak": 0, "no_data": 0}
    recent_scores: list[float] = []
    for s in (submissions or []):
        sc = 0.0
        diag = s.get("diagnosis") or {}
        if isinstance(diag, dict):
            sc = float(diag.get("overall_score", 0) or 0)
        if not sc:
            sc = float(s.get("overall_score", 0) or 0)
        if sc >= 7:
            score_distribution["good"] += 1
        elif sc >= 5:
            score_distribution["average"] += 1
        elif sc > 0:
            score_distribution["weak"] += 1
        else:
            score_distribution["no_data"] += 1
        if sc > 0:
            recent_scores.append(sc)
        triggered = s.get("triggered_rules") or []
        if not triggered and isinstance(diag, dict):
            triggered = diag.get("triggered_rules") or []
        for tr in triggered:
            if isinstance(tr, dict):
                rid = str(tr.get("id") or tr.get("rule_id") or "")
            else:
                rid = str(tr or "")
            if rid:
                rule_counter[rid] = rule_counter.get(rid, 0) + 1
    risk_top3 = sorted(rule_counter.items(), key=lambda kv: kv[1], reverse=True)[:3]
    risk_rule_top3_list = [
        {"rule_id": rid, "count": cnt, "label": _dim_cn(rid) if rid in DIM_CN else rid}
        for rid, cnt in risk_top3
    ]

    # Engagement（单学生语义：总提交、近 7 天节奏、最近一次）
    engagement_stats = {
        "total_submissions": total_subs,
        "scored_count": len(recent_scores),
        "risk_count": risk_count,
    }

    # trend_summary
    if total_subs >= 4:
        if trend > 0.3:
            trend_summary = f"近期趋势 +{trend:.1f}，呈稳步进步"
        elif trend < -0.3:
            trend_summary = f"近期趋势 {trend:.1f}，需关注回落"
        else:
            trend_summary = f"近期波动 {trend:+.1f}，整体平稳"
    elif total_subs > 0:
        trend_summary = "数据量较少，暂无法判断趋势"
    else:
        trend_summary = "尚无诊断数据"

    # detail_bullets
    detail_bullets: list[str] = []
    if avg_score > 0:
        detail_bullets.append(f"{scope_label}均分 {avg_score}/10，健康指数 {health['score']}")
    else:
        detail_bullets.append(f"{scope_label}尚无完整打分数据，先完成一次提交即可建立画像")
    if top_strengths_cn:
        detail_bullets.append(f"优势维度：{'、'.join(top_strengths_cn)}")
    if top_weaknesses_cn:
        detail_bullets.append(f"待加强：{'、'.join(top_weaknesses_cn)}")
    if risk_rule_top3_list:
        detail_bullets.append(
            "高频风险："
            + "、".join(f"{r['rule_id']}({r['count']}次)" for r in risk_rule_top3_list)
        )

    # overall_assessment
    parts: list[str] = []
    if health["level"] == "healthy":
        parts.append(f"整体表现良好（{health['score']}）")
    elif health["level"] == "warning":
        parts.append(f"整体中等水平（{health['score']}），有提升空间")
    else:
        parts.append(f"整体需要重点关注（{health['score']}）")
    if top_strengths_cn:
        parts.append(f"继续保持「{top_strengths_cn[0]}」优势")
    if top_weaknesses_cn:
        parts.append(f"优先补强「{top_weaknesses_cn[0]}」")
    if risk_rule_top3_list:
        parts.append(f"当前最高频风险为 {risk_rule_top3_list[0]['rule_id']}")
    overall_assessment = "；".join(parts) + "。"

    return {
        "health_score": health["score"],
        "health_level": health["level"],
        "health_label": health["label"],
        "rubric_heatmap_team": heatmap_team_style,
        "top_strengths": top_strengths_cn,
        "top_weaknesses": top_weaknesses_cn,
        "risk_rule_top3": risk_rule_top3_list,
        "engagement_stats": engagement_stats,
        "trend_summary": trend_summary,
        "overall_assessment": overall_assessment,
        "detail_bullets": detail_bullets,
        "score_distribution": score_distribution,
    }


@app.get("/api/student/{user_id}/portrait/overall")
def student_portrait_overall(user_id: str) -> dict:
    """学生总画像：跨所有会话聚合。"""
    data = _aggregate_student_data(user_id, include_detail=True)
    portrait = dict(data.get("portrait") or {})
    portrait["total_submissions"] = data.get("total_submissions", 0)
    portrait["project_count"] = data.get("project_count", 0)
    portrait["avg_score"] = data.get("avg_score", 0.0)
    portrait["trend"] = data.get("trend", 0.0)
    portrait["risk_count"] = data.get("risk_count", 0)
    portrait["latest_phase"] = data.get("latest_phase", "")
    portrait["intent_distribution"] = data.get("intent_distribution", {}) or {}
    portrait["intent_shape_distribution"] = data.get("intent_shape_distribution", {}) or {}
    portrait["student_case_summary"] = data.get("student_case_summary", "") or ""
    # 团队画像同结构字段（panorama）
    project_id = f"project-{user_id}"
    project = json_store.load_project(project_id)
    all_subs = list(project.get("submissions", []) or [])
    panorama = _build_student_panorama(
        submissions=all_subs,
        rubric_heatmap=portrait.get("rubric_heatmap") or [],
        avg_score=float(data.get("avg_score", 0.0) or 0.0),
        trend=float(data.get("trend", 0.0) or 0.0),
        risk_count=int(data.get("risk_count", 0) or 0),
        strength_dims=portrait.get("strength_dimensions") or [],
        weakness_dims=portrait.get("weakness_dimensions") or [],
        scope_label="总画像",
    )
    portrait.update(panorama)
    # 汇总用：overview_rationale 说明这张画像是如何算出来的
    portrait["overview_rationale"] = {
        "field": "portrait:overall",
        "value": data.get("avg_score", 0.0),
        "formula": "avg(scores across all submissions)",
        "formula_display": (
            f"总画像聚合了该学生全部 {data.get('total_submissions', 0)} 条提交，"
            f"分布在 {data.get('project_count', 0)} 个项目（会话）上。\n"
            f"综合均分 = 全部打分的算术平均 = {data.get('avg_score', 0.0)}\n"
            f"近中期变化 = {data.get('trend', 0.0):+.1f}\n"
            f"健康指数 = {panorama['health_score']}（{panorama['health_label']}）"
        ),
        "inputs": [
            {"label": "项目数", "value": data.get("project_count", 0)},
            {"label": "提交数", "value": data.get("total_submissions", 0)},
            {"label": "触发风险次数", "value": data.get("risk_count", 0)},
            {"label": "健康指数", "value": panorama["health_score"]},
        ],
        "note": "默认按所有会话聚合，若要按会话单独查看请切换 Tab。",
    }
    all_cids = [None] + [str((c.get("conversation_id") or "")) for c in conv_store.list_conversations(project_id)]
    return _apply_overrides_everywhere({"portrait": portrait}, project_id, all_cids)


@app.get("/api/student/{user_id}/portrait/conversations")
def student_portrait_conversations(user_id: str) -> dict:
    """学生按会话的画像列表：每个会话一张卡（轻量版）。"""
    project_id = f"project-{user_id}"
    data = _aggregate_student_data(user_id, include_detail=True)
    project_snapshots = data.get("project_snapshots") or []
    # 会话列表（精简：取每个 conversation_id 最近一次画像切面）
    convs = conv_store.list_conversations(project_id)
    conv_meta = {str(c["conversation_id"]): c for c in convs}
    # 把 project_snapshots 按 project_id 对齐 conversation_id（约定两者相同时）
    cards = []
    for snap in project_snapshots:
        cid = str(snap.get("project_id") or "")
        meta = conv_meta.get(cid, {}) if cid else {}
        cards.append({
            "conversation_id": cid,
            "title": meta.get("title") or snap.get("project_name") or cid[:8],
            "last_score": snap.get("latest_score", 0),
            "project_phase": snap.get("project_phase", ""),
            "summary": snap.get("current_summary", ""),
            "top_risks": snap.get("top_risks", []),
            "intent_distribution": snap.get("intent_distribution", {}),
            "message_count": meta.get("message_count", 0),
            "created_at": meta.get("created_at", ""),
        })
    return _apply_overrides_everywhere(
        {"project_id": project_id, "cards": cards},
        project_id,
        [c["conversation_id"] for c in cards if c.get("conversation_id")],
    )


@app.get("/api/student/{user_id}/portrait/conversation/{conversation_id}")
def student_portrait_conversation_detail(user_id: str, conversation_id: str) -> dict:
    """单个会话的画像详情：rubric 趋势、风险、成熟度、消息数量等。"""
    project_id = f"project-{user_id}"
    data = _aggregate_student_data(user_id, include_detail=True)
    proj = next((p for p in (data.get("projects") or []) if p.get("project_id") == conversation_id), None)
    if not proj:
        return {"status": "not_found", "conversation_id": conversation_id}
    # 本会话的原始 submissions（用于 panorama 的风险统计）
    proj_raw_subs = [
        s for s in (json_store.load_project(project_id).get("submissions") or [])
        if _safe_str(s.get("logical_project_id") or s.get("project_id") or s.get("conversation_id") or "") == conversation_id
    ]
    # 本会话的 rubric heatmap
    rubric_scores: dict[str, list[float]] = {}
    for sub in proj.get("submissions", []):
        diag = sub.get("diagnosis") or {}
        for r in (diag.get("rubric") or []):
            if isinstance(r, dict) and r.get("item"):
                rubric_scores.setdefault(r["item"], []).append(float(r.get("score", 0) or 0))
    heatmap = []
    strength_dims_conv: list[str] = []
    weakness_dims_conv: list[str] = []
    for name, arr in rubric_scores.items():
        avg_rs = round(sum(arr) / len(arr), 2) if arr else 0
        if avg_rs >= 7:
            strength_dims_conv.append(name)
        elif avg_rs < 5:
            weakness_dims_conv.append(name)
        heatmap.append({
            "item": name,
            "avg_score": avg_rs,
            "count": len(arr),
            "rationale": {
                "field": f"rubric_heatmap:{conversation_id}:{name}",
                "value": avg_rs,
                "formula": "avg(dim scores in this conversation)",
                "formula_display": (
                    f"本会话 {name} 均分 = ({' + '.join(f'{x:.1f}' for x in arr[:6])}"
                    + (" + …" if len(arr) > 6 else "")
                    + f") ÷ {len(arr)} = {avg_rs}"
                ),
                "inputs": [{"label": f"第{i+1}次", "value": round(float(x), 2)} for i, x in enumerate(arr[:10])],
                "note": f"仅统计本会话 {len(arr)} 次评分",
            },
        })
    # 本会话趋势
    p_scores = []
    for sub in proj.get("submissions", []):
        sc = float(sub.get("overall_score", 0) or 0)
        if not sc:
            diag = sub.get("diagnosis") or {}
            sc = float(diag.get("overall_score", 0) or 0) if isinstance(diag, dict) else 0
        if sc > 0:
            p_scores.append(sc)
    conv_avg = round(sum(p_scores) / len(p_scores), 1) if p_scores else 0.0
    conv_trend = 0.0
    if len(p_scores) >= 4:
        mid = len(p_scores) // 2
        conv_trend = round(sum(p_scores[mid:]) / (len(p_scores) - mid) - sum(p_scores[:mid]) / mid, 1)
    conv_risk_count = sum(1 for s in proj_raw_subs if (s.get("triggered_rules") or []))

    panorama = _build_student_panorama(
        submissions=proj_raw_subs,
        rubric_heatmap=heatmap,
        avg_score=conv_avg,
        trend=conv_trend,
        risk_count=conv_risk_count,
        strength_dims=strength_dims_conv,
        weakness_dims=weakness_dims_conv,
        scope_label="本会话",
    )
    # 本会话的最近一次 maturity（从最新 bp 取）
    try:
        latest_bp = business_plan_service.get_latest(project_id, conversation_id) or {}
    except Exception:
        latest_bp = {}
    maturity_snapshot = (latest_bp.get("readiness") or {}) if isinstance(latest_bp, dict) else {}
    # 提供与 overall 对齐的 portrait 对象
    portrait_payload = {
        **panorama,
        "avg_score": conv_avg,
        "trend": conv_trend,
        "risk_count": conv_risk_count,
        "total_submissions": len(proj_raw_subs),
        "rubric_heatmap": heatmap,
        "strength_dimensions": strength_dims_conv,
        "weakness_dimensions": weakness_dims_conv,
        "latest_phase": proj.get("project_phase", ""),
        "overview_rationale": {
            "field": f"portrait:conversation:{conversation_id}",
            "value": conv_avg,
            "formula": "avg(scores in this conversation)",
            "formula_display": (
                f"本会话共 {len(proj_raw_subs)} 次提交，\n"
                f"有效打分 {len(p_scores)} 次 → 均分 {conv_avg}\n"
                f"近中期变化 {conv_trend:+.1f}\n"
                f"健康指数 = {panorama['health_score']}（{panorama['health_label']}）"
            ),
            "inputs": [
                {"label": "提交数", "value": len(proj_raw_subs)},
                {"label": "有效打分", "value": len(p_scores)},
                {"label": "触发风险次数", "value": conv_risk_count},
                {"label": "健康指数", "value": panorama["health_score"]},
            ],
            "note": "只统计该会话（项目）内的数据",
        },
    }
    payload = {
        "conversation_id": conversation_id,
        "project_card": proj,
        "rubric_heatmap": heatmap,
        "maturity_snapshot": maturity_snapshot,
        "portrait": portrait_payload,
    }
    return _apply_overrides_everywhere(payload, project_id, [conversation_id, None])


# ───────────────── 教师订正 endpoints ─────────────────
@app.get("/api/teacher/overrides")
def teacher_overrides_list(
    project_id: str,
    conversation_id: str = "",
    target_type: str = "",
    target_key: str = "",
) -> dict:
    cid = conversation_id.strip() or None
    return {
        "overrides": ai_override_store.list(
            project_id,
            cid,
            target_type=target_type or None,
            target_key=target_key or None,
        )
    }


@app.post("/api/teacher/overrides")
def teacher_overrides_upsert(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {"status": "error", "detail": "invalid payload"}
    try:
        record = ai_override_store.upsert(payload)
        return {"status": "ok", "override": record}
    except ValueError as exc:
        return {"status": "error", "detail": str(exc)}


@app.delete("/api/teacher/overrides/{override_id}")
def teacher_overrides_delete(override_id: str, project_id: str, conversation_id: str = "") -> dict:
    cid = conversation_id.strip() or None
    ok = ai_override_store.delete(project_id, cid, override_id)
    return {"status": "ok" if ok else "not_found"}


# ───────────────── 重构版 evidence-trace ─────────────────
@app.get("/api/teacher/project/{project_id}/evidence-trace-v2")
def teacher_project_evidence_trace_v2(project_id: str, logical_project_id: str = "") -> dict:
    """「按结论分组」的证据树：每个 rubric 维度 / 风险规则 / 综合分 都单独成组，
    其下挂相关证据消息（含 source_message_id）。前端可以直接树形渲染。"""
    project_state = json_store.load_project(project_id)
    filtered_subs = _project_submissions_by_logical_id(project_state, logical_project_id)
    if not filtered_subs:
        return {
            "project_id": project_id,
            "logical_project_id": logical_project_id,
            "error": "该项目暂无可用于证据溯源的提交记录",
        }
    evidence_chain = _assessment_evidence_chain(filtered_subs)

    # 收集每个 submission 对应的 conversation_id，用于消息回定
    sub_to_cid: dict[str, str] = {}
    for sub in filtered_subs:
        sid = str(sub.get("submission_id") or "")
        cid = str(sub.get("conversation_id") or "")
        if sid:
            sub_to_cid[sid] = cid

    # 1) rubric 维度分组
    rubric_groups: dict[str, dict] = {}
    rule_groups: dict[str, dict] = {}
    for row in evidence_chain:
        sid = str(row.get("submission_id") or "")
        cid = sub_to_cid.get(sid, "")
        quote = str(row.get("quote") or "")
        link = None
        if cid and quote:
            links = evidence_linker.link_text(project_id, cid, quote, top_k=1)
            link = links[0] if links else None
        enriched_ev = {
            **row,
            "conversation_id": cid,
            "source_message_id": (link or {}).get("message_id"),
            "source_message_turn": (link or {}).get("turn_index"),
            "source_message_role": (link or {}).get("role"),
            "source_message_confidence": (link or {}).get("confidence"),
        }
        for rubric in (row.get("rubric_items") or []):
            bucket = rubric_groups.setdefault(rubric, {
                "conclusion_type": "rubric",
                "conclusion_key": rubric,
                "label": rubric,
                "evidence": [],
            })
            bucket["evidence"].append(enriched_ev)
        for rid in (row.get("rule_ids") or []):
            rid_u = str(rid).upper()
            if not rid_u:
                continue
            bucket = rule_groups.setdefault(rid_u, {
                "conclusion_type": "risk",
                "conclusion_key": rid_u,
                "label": f"{rid_u} · {get_rule_name(rid_u)}",
                "fallacy": RULE_FALLACY_MAP.get(rid_u, ""),
                "edge_families": RULE_EDGE_MAP.get(rid_u, []),
                "evidence": [],
            })
            bucket["evidence"].append(enriched_ev)

    # 2) 综合分分组 —— 把最近一次 diagnosis 的 overall_rationale 拿出来
    overall_group = None
    tier1_groups: list[dict] = []
    last_sub = filtered_subs[-1] if filtered_subs else None
    last_diag_obj: dict = {}
    if last_sub:
        last_diag_obj = last_sub.get("diagnosis") or {}
        overall_rat = last_diag_obj.get("overall_rationale")
        if overall_rat:
            overall_group = {
                "conclusion_type": "overall",
                "conclusion_key": "overall",
                "label": "综合分",
                "rationale": overall_rat,
                "evidence": [],
            }
        # ── Tier 1：挂上 project_phase / bottleneck / summary / next_task 的 rationale ──
        for tier1_key, tier1_label, tier1_rat_key in [
            ("project_phase", "项目阶段判定", "project_phase_rationale"),
            ("bottleneck", "核心瓶颈", "bottleneck_rationale"),
            ("summary", "诊断总结", "summary_rationale"),
        ]:
            rat = last_diag_obj.get(tier1_rat_key)
            if rat:
                tier1_groups.append({
                    "conclusion_type": "tier1",
                    "conclusion_key": tier1_key,
                    "label": tier1_label,
                    "rationale": rat,
                    "evidence": [],
                })
        # next_task 的 rationale 放在 next_task.rationale 里
        last_next = last_sub.get("next_task") or {}
        if isinstance(last_next, dict) and last_next.get("rationale"):
            tier1_groups.append({
                "conclusion_type": "tier1",
                "conclusion_key": "next_task",
                "label": "下一步任务",
                "rationale": last_next.get("rationale"),
                "evidence": [],
            })

    # ── 把每个 rubric 维度的 rationale（含 reasoning_steps）挂到分组 ──
    if last_diag_obj:
        for _rb in (last_diag_obj.get("rubric") or []):
            if not isinstance(_rb, dict):
                continue
            _item = str(_rb.get("item") or "")
            if not _item or _item not in rubric_groups:
                # 如果有 rubric 但没有证据也露出 rationale
                if _item and _rb.get("rationale"):
                    rubric_groups[_item] = {
                        "conclusion_type": "rubric",
                        "conclusion_key": _item,
                        "label": _item,
                        "evidence": [],
                    }
            if _item and _rb.get("rationale") and _item in rubric_groups:
                rubric_groups[_item]["rationale"] = _rb.get("rationale")
                rubric_groups[_item]["score"] = _rb.get("score")

    all_cids = list({cid for cid in sub_to_cid.values() if cid})
    payload = {
        "project_id": project_id,
        "logical_project_id": logical_project_id,
        "overall": overall_group,
        "tier1_groups": tier1_groups,
        "rubric_groups": sorted(rubric_groups.values(), key=lambda g: -len(g["evidence"])),
        "rule_groups": sorted(rule_groups.values(), key=lambda g: -len(g["evidence"])),
        "total_evidence": sum(len(g["evidence"]) for g in rubric_groups.values())
                         + sum(len(g["evidence"]) for g in rule_groups.values()),
    }
    return _apply_overrides_everywhere(payload, project_id, all_cids or [None])



import pandas as pd
from fastapi import UploadFile
# ── 批量导入用户与团队（CSV/Excel/JSON） ──────────────────────────────
@app.post("/api/admin/users/import_csv")
async def admin_import_users_csv(
    file: UploadFile = File(...),
    meta: str = Form(None),
    data: str = Form(None),
    request: Request = None
):
    """
    支持 CSV/Excel/JSON 批量导入用户与团队，字段：account, name, role, email, team_name, invite_code, password
    1. 解析文件或 data 字段
    2. 校验字段完整性、格式、重复
    3. 自动创建/合并团队，成员自动加入
    4. 只追加新用户/团队，不做删除/覆盖
    5. 生成导入日志，错误项单独返回
    """
    import os
    import json as _json
    from datetime import datetime
    from pathlib import Path
    from uuid import uuid4
    # 1. 解析数据
    rows = []
    filename = file.filename
    ext = filename.split(".")[-1].lower()
    try:
        if data:
            rows = _json.loads(data)
        elif ext == "csv":
            df = pd.read_csv(file.file)
            rows = df.to_dict(orient="records")
        elif ext in ("xlsx", "xls"):  # Excel
            df = pd.read_excel(file.file)
            rows = df.to_dict(orient="records")
        else:
            raise Exception("仅支持 .csv/.xlsx/.xls 文件")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {e}")
    if not rows or not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="未检测到有效数据")
    # 2. 校验与处理
    required_fields = ["account", "name", "role", "email", "team_name", "invite_code", "password"]
    success, failed, errors = 0, 0, []
    new_users, new_teams = [], []
    user_ids, team_ids = set(), set()
    users_json = (settings.data_root / "users" / "users.json")
    teams_json = (settings.data_root / "teams" / "teams.json")
    # 加载现有数据
    try:
        users_data = _json.loads(users_json.read_text("utf-8")) if users_json.exists() else []
    except Exception:
        users_data = []
    try:
        teams_data = _json.loads(teams_json.read_text("utf-8")) if teams_json.exists() else []
    except Exception:
        teams_data = []
    existing_emails = set()
    existing_names = set()
    for u in users_data:
        user_ids.add(str(u.get("user_id") or u.get("email") or u.get("account") or "").strip())
        email = str(u.get("email") or "").strip().lower()
        name = str(u.get("display_name") or u.get("name") or "").strip()
        if email:
            existing_emails.add(email)
        if name:
            existing_names.add(name)
    for t in teams_data:
        team_ids.add(str(t.get("team_id") or t.get("invite_code") or t.get("team_name") or "").strip())
    # 3. 处理每一行
    for idx, row in enumerate(rows):
        # 字段标准化
        item = {k: str(row.get(k, "")).strip() for k in required_fields}
        # team_name 和 invite_code 可以为空
        # email 和 password 可自动填充
        if not item["account"] or not item["name"] or not item["role"]:
            failed += 1
            errors.append({"row": idx+1, "reason": "account/name/role 不能为空", "item": item})
            continue
        if not item["email"]:
            item["email"] = f"{item['account']}@local"
        if not item["password"]:
            item["password"] = f"{item['account']}+123"
        if item["role"] not in ("student", "teacher", "admin"):
            failed += 1
            errors.append({"row": idx+1, "reason": "角色无效", "item": item})
            continue
        # 邮箱唯一
        email_lower = item["email"].lower()
        if email_lower in existing_emails:
            failed += 1
            errors.append({"row": idx+1, "reason": "邮箱已存在", "item": item})
            continue
        # 姓名唯一
        if item["name"] in existing_names:
            failed += 1
            errors.append({"row": idx+1, "reason": "姓名已存在", "item": item})
            continue
        if item["account"] in user_ids:
            failed += 1
            errors.append({"row": idx+1, "reason": "账号已存在", "item": item})
            continue
        # 导入后也要加入集合，防止本批次重复
        existing_emails.add(email_lower)
        existing_names.add(item["name"])
        # 检查团队是否存在，不存在则创建（team_name/invite_code都为空则不创建团队）
        team = None
        if item["team_name"] or item["invite_code"]:
            team = next((t for t in teams_data if (item["team_name"] and t.get("team_name") == item["team_name"]) or (item["invite_code"] and t.get("invite_code") == item["invite_code"])), None)
            if not team:
                team_id = f"team-{uuid4().hex[:8]}"
                team = {
                    "team_id": team_id,
                    "team_name": item["team_name"],
                    "invite_code": item["invite_code"],
                    "teacher_id": "",
                    "teacher_name": "",
                    "members": [],
                    "created_at": datetime.utcnow().isoformat(),
                }
                # 如果是教师，自动归属
                if item["role"] == "teacher":
                    team["teacher_id"] = "user-" + item["account"] if not item["account"].startswith("user-") else item["account"]
                    team["teacher_name"] = item["name"]
                teams_data.append(team)
                team_ids.add(team_id)
                new_teams.append(team)
        # 创建用户
        user_id = f"user-{uuid4().hex[:8]}"
        user = {
            "user_id": user_id,
            "display_name": item["name"],
            "role": item["role"],
            "email": item["email"],
            "password": item["password"],
            "status": "active",
            "team_names": [item["team_name"]] if item["team_name"] else [],
            "last_login": "",
        }
        users_data.append(user)
        user_ids.add(item["account"])
        new_users.append(user)
        # 加入团队：仅非教师用户加入 members
        if team and "members" in team and item["role"] != "teacher":
            team["members"].append({"user_id": user_id, "joined_at": datetime.utcnow().isoformat()})
        # 如果是教师，补充团队teacher_id/teacher_name（但不加入 members）
        if team and item["role"] == "teacher":
            team["teacher_id"] = user_id
            team["teacher_name"] = item["name"]
        success += 1
    # 4. 数据落盘
    try:
        users_json.write_text(_json.dumps(users_data, ensure_ascii=False, indent=2), encoding="utf-8")
        teams_json.write_text(_json.dumps(teams_data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据写入失败: {e}")
    # 5. 写入日志
    logs_dir = settings.data_root / "import_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_obj = {
        "filename": filename,
        "meta": meta,
        "time": datetime.utcnow().isoformat(),
        "operator": str(request.headers.get("X-User", "admin")),
        "total": len(rows),
        "success": success,
        "failed": failed,
        "errors": errors,
        "new_users": [u["user_id"] for u in new_users],
        "new_teams": [t["team_id"] for t in new_teams],
    }
    log_path = logs_dir / f"import_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}.json"
    log_path.write_text(_json.dumps(log_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    # 6. 返回结果
    return {
        "status": "ok",
        "filename": filename,
        "total": len(rows),
        "success": success,
        "failed": failed,
        "errors": errors,
        "new_users": [u["user_id"] for u in new_users],
        "new_teams": [t["team_id"] for t in new_teams],
        "log": str(log_path.name),
    }
from fastapi import Body
# 批量创建教师账号及团队（前端新UI专用）
@app.post("/api/admin/teachers/batch_with_teams")
def admin_batch_create_teachers_with_teams(
    payload: dict = Body(...)
):
    """
    批量创建教师账号和团队，每个教师可自定义账号、姓名、团队名、邀请码、密码。
    前端需传入 teachers: [{account, name, team_name, invite_code, password}]
    """
    teachers = payload.get("teachers")
    if not isinstance(teachers, list) or not teachers:
        raise HTTPException(status_code=400, detail="参数格式错误：teachers 必须为非空数组")
    results = []
    for t in teachers:
        account = str(t.get("account", "")).strip()
        name = str(t.get("name", "")).strip()
        password = str(t.get("password", "")).strip()
        teams = t.get("teams", [])
        if not (account and name and password and isinstance(teams, list) and teams):
            results.append({"account": account, "success": False, "reason": "信息不完整"})
            continue
        # 检查账号是否已存在
        if user_store.get_by_email(account):
            results.append({"account": account, "success": False, "reason": "账号已存在"})
            continue
        # 创建教师账号
        try:
            user, _ = user_store.admin_create_user({
                "role": "teacher",
                "display_name": name,
                "email": account,
                "password": password,
            })
        except Exception as e:
            results.append({"account": account, "success": False, "reason": f"创建账号失败: {e}"})
            continue
        teacher_id = user.get("user_id")
        # 为该教师批量创建团队
        team_results = []
        for tm in teams:
            team_name = str(tm.get("team_name", "")).strip()
            invite_code = str(tm.get("invite_code", "")).strip().upper()
            if not (team_name and invite_code):
                team_results.append({"team_name": team_name, "success": False, "reason": "团队信息不完整"})
                continue
            # 检查团队邀请码是否冲突
            if team_store.find_by_invite_code(invite_code):
                team_results.append({"team_name": team_name, "invite_code": invite_code, "success": False, "reason": "邀请码已被占用"})
            else:
                try:
                    team = team_store.create_team_with_custom_code(
                        teacher_id=teacher_id,
                        teacher_name=name,
                        team_name=team_name,
                        invite_code=invite_code,
                    )
                    team_results.append({
                        "team_name": team_name,
                        "invite_code": invite_code,
                        "team_id": team.get("team_id"),
                        "success": True
                    })
                except Exception as e:
                    team_results.append({"team_name": team_name, "invite_code": invite_code, "success": False, "reason": f"创建团队失败: {e}"})
        results.append({
            "account": account,
            "teacher_id": teacher_id,
            "success": True,
            "teams": team_results
        })
    return {"status": "ok", "results": results}