import json
import logging
import math
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.schemas import (
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
    DialogueTurnPayload,
    DialogueTurnResponse,
    HealthResponse,
    ProjectSnapshotResponse,
    SmsLoginPayload,
    SmsSendPayload,
    SmsSendResponse,
    StudentInterventionViewPayload,
    TeamCreatePayload,
    TeamJoinPayload,
    TeamResponse,
    TeacherAssistantAssessmentReviewPayload,
    TeacherAssistantInterventionPayload,
    TeacherAssistantInterventionSendPayload,
    TeacherFeedbackRequest,
    TeacherFeedbackResponse,
    TeamUpdatePayload,
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


logger = logging.getLogger(__name__)

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


@app.get("/api/admin/logs")
def admin_logs() -> dict:
    """Admin view of access logs + aggregate statistics."""
    return _load_access_logs()


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
    }


def _safe_hypergraph_insight(hg: Any) -> dict:
    if not isinstance(hg, dict):
        return {}
    edges = []
    for e in (hg.get("edges") or [])[:8]:
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
        "top_signals": [_safe_str(x) for x in (hg.get("top_signals") or [])[:5]],
        "key_dimensions": [_safe_str(x) for x in (hg.get("key_dimensions") or [])[:5]],
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
    if conversation_id:
        for row in reversed(subs):
            if row.get("conversation_id") == conversation_id and row.get("logical_project_id"):
                return str(row.get("logical_project_id"))
    terms = _topic_terms(message)
    if conversation_id and terms:
        for row in reversed(subs[-12:]):
            row_terms = _topic_terms(" ".join([
                _safe_str(row.get("raw_text", "")),
                _safe_str((row.get("next_task") or {}).get("title", "")),
                _safe_str((row.get("diagnosis") or {}).get("bottleneck", "")),
            ]))
            if len(terms.intersection(row_terms)) >= 3 and row.get("logical_project_id"):
                return str(row.get("logical_project_id"))
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
        "matched_teacher_interventions": matched_interventions or [],
        "kb_utilization": result.get("kb_utilization", {}),
        "rag_enrichment_insight": result.get("rag_enrichment_insight", ""),
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
    filename = _safe_str(latest.get("filename", ""))
    if filename:
        stem = Path(filename).stem.strip()
        if stem:
            return stem[:24]
    raw = _safe_str(latest.get("raw_text", "")).replace("\n", " ").strip()
    if raw:
        words = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{4,}", raw)
        if words:
            return "".join(words[:2])[:24]
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
            latest_diag = _safe_diagnosis(latest.get("diagnosis", {}))
            latest_kg = _safe_kg_analysis(latest.get("kg_analysis", {}))
            latest_hyper = _safe_hypergraph_insight(latest.get("hypergraph_insight", {}))
            latest_hyper_student = _safe_hypergraph_student(
                latest.get("hypergraph_student")
                or (latest.get("agent_outputs", {}) if isinstance(latest.get("agent_outputs"), dict) else {}).get("hypergraph_student", {})
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
            for rid in (latest_diag.get("triggered_rules") or [])[:4]:
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
                        "next_task": _safe_str(s.get("next_task", {}).get("description", "") if isinstance(s.get("next_task"), dict) else s.get("next_task", "")),
                        "triggered_rules": _normalize_rules(s.get("triggered_rules") or s.get("diagnosis", {}).get("triggered_rules", [])),
                        "text_preview": (s.get("raw_text") or "")[:80],
                        "evidence_quotes": _safe_evidence_quotes(s.get("evidence_quotes", [])),
                        "diagnosis": _safe_diagnosis(s.get("diagnosis", {})),
                        "agent_outputs": _safe_agent_summary(s),
                        "kg_analysis": _safe_kg_analysis(s.get("kg_analysis", {})),
                        "hypergraph_insight": _safe_hypergraph_insight(s.get("hypergraph_insight", {})),
                        "hypergraph_student": _safe_hypergraph_student(
                            s.get("hypergraph_student")
                            or (s.get("agent_outputs", {}) if isinstance(s.get("agent_outputs"), dict) else {}).get("hypergraph_student", {})
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

    relevant_other = [row for row in recent if row not in same_conv]
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

    # ── run LangGraph workflow ──
    result = run_workflow(
        message=payload.message,
        mode=payload.mode,
        project_state=scoped_project_state,
        history_context=history_context,
        conversation_messages=conv_messages,
        teacher_feedback_context=tfb_ctx,
        competition_type=getattr(payload, "competition_type", "") or "",
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
    logical_project_id = _derive_logical_project_id(project_state, conv_id, payload.message, payload.project_id)
    project_phase = _infer_project_phase(payload.message, next_task, kg_analysis)
    intent = _normalize_intent(result.get("intent", ""), payload.message)
    intent_confidence = float(result.get("intent_confidence", 0) or 0)
    intent_shape = _safe_str(result.get("intent_shape", "")) or "single"
    evidence_quotes = _extract_evidence_quotes(payload.message, diagnosis)
    import logging as _log
    _log.getLogger("main").info("API response: hyper_student.ok=%s, kg_entities=%d", hyper_student.get("ok"), len(kg_analysis.get("entities", [])))

    agent_trace = _build_agent_trace(
        result,
        mode=payload.mode,
        llm_enabled=composer_llm.enabled,
        matched_interventions=matched_interventions,
    )

    # ── persist to project state ──
    json_store.append_submission(
        payload.project_id,
        {
            "student_id": payload.student_id,
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
            "pressure_test_trace": result.get("pressure_test_trace"),
            "matched_teacher_interventions": matched_interventions,
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
        pressure_test_trace=result.get("pressure_test_trace", {}),
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
            }
            yield f"data: {json.dumps({'type': 'meta', 'data': side_data}, ensure_ascii=False)}\n\n"

            full_text = ""
            for chunk in stream_orchestrator(pre):
                full_text += chunk
                yield f"data: {json.dumps({'type': 'token', 'data': chunk}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'data': full_text}, ensure_ascii=False)}\n\n"

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
                },
            })
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
                "logical_project_id": _safe_str(sub.get("logical_project_id") or sub.get("project_id") or sub.get("conversation_id", "")),
                "student_id": sub.get("student_id", ""),
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
            "teaching_modules": [],
            "evidence_citations": [],
            "teaching_focus": "",
            "teaching_action": "",
        }

    sorted_by_score = sorted(rows, key=lambda item: float(item.get("latest_score", 0) or 0), reverse=True)
    sorted_by_risk = sorted(rows, key=lambda item: len(item.get("top_risks") or []), reverse=True)
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
    top_risks = sorted(risk_counter.items(), key=lambda item: item[1], reverse=True)[:3]
    dominant_intent = sorted(intent_counter.items(), key=lambda item: item[1], reverse=True)[0][0] if intent_counter else "综合咨询"
    snapshot = {
        "category": category,
        "project_count": len(rows),
        "avg_score": avg_score,
        "dominant_intent": dominant_intent,
        "top_sample": sorted_by_score[:5],
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
            'teaching_modules: string[],\n'
            'evidence_citations: [{"claim": string, "project_name": string, "evidence": string}],\n'
            'teaching_focus: string, teaching_action: string。\n'
            "要求：\n"
            "1. 聚焦老师接下来该先看什么、为什么。\n"
            "2. 不要泛泛而谈，尽量结合风险、分数、迭代、项目名称给出判断。\n"
            "3. 必须体现至少一个高分样本和一个高风险样本之间的对照分析。\n"
            "4. 每个数组控制在 2-4 条。\n"
            "5. 中文输出，简洁但信息密度高，像老师真正会看的教学分析报告。"
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
        "teaching_modules": result.get("teaching_modules") or fallback["teaching_modules"],
        "evidence_citations": result.get("evidence_citations") or fallback["evidence_citations"],
        "teaching_focus": _safe_str(result.get("teaching_focus", fallback["teaching_focus"])),
        "teaching_action": _safe_str(result.get("teaching_action", fallback["teaching_action"])),
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
def rebuild_hypergraph(min_pattern_support: int = 1, max_edges: int = 80) -> dict:
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
        for quote in quotes[:4]:
            rows.append({
                **quote,
                "created_at": sub.get("created_at", ""),
                "project_phase": _safe_str(sub.get("project_phase", "")),
                "source_type": _safe_str(sub.get("source_type", "")),
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
        results.append({
            "item_id": item["id"],
            "item_name": item["name"],
            "score": score,
            "max_score": 5,
            "weight": item["weight"],
            "reason": "；".join(reason_bits) + "。",
            "revision_suggestion": revision_suggestion,
            "evidence_quotes": [q.get("quote", "") for q in evidence[:2] if q.get("quote")],
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
