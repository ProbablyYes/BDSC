import json
import secrets
import string
from hashlib import pbkdf2_hmac
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


BJ_TZ = timezone(timedelta(hours=8))


def _now_iso() -> str:
    return datetime.now(BJ_TZ).isoformat()


class JsonStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _project_file(self, project_id: str) -> Path:
        return self.root / f"{project_id}.json"

    def load_project(self, project_id: str) -> dict:
        target = self._project_file(project_id)
        if not target.exists():
            return {
                "project_id": project_id,
                "submissions": [],
                "teacher_feedback": [],
                "teacher_assistant_reviews": [],
                "teacher_interventions": [],
                "teacher_annotations": [],
                "teacher_feedback_files": [],
                "teacher_document_edits": [],
            }
        data = json.loads(target.read_text(encoding="utf-8"))
        # new确保新增字段存在
        if "teacher_assistant_reviews" not in data:
            data["teacher_assistant_reviews"] = []
        if "teacher_interventions" not in data:
            data["teacher_interventions"] = []
        if "teacher_annotations" not in data:
            data["teacher_annotations"] = []
        if "teacher_feedback_files" not in data:
            data["teacher_feedback_files"] = []
        if "teacher_document_edits" not in data:
            data["teacher_document_edits"] = []
        return data

    def save_project(self, project_id: str, payload: dict) -> None:
        target = self._project_file(project_id)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def append_submission(self, project_id: str, submission: dict) -> dict:
        data = self.load_project(project_id)
        saved_submission = {
            **submission,
            "submission_id": str(uuid4()),
            "created_at": _now_iso(),
        }
        data["submissions"].append(saved_submission)
        self.save_project(project_id, data)
        return saved_submission

    def append_teacher_feedback(self, project_id: str, teacher_feedback: dict) -> str:
        data = self.load_project(project_id)
        feedback_id = str(uuid4())
        data["teacher_feedback"].append(
            {
                **teacher_feedback,
                "feedback_id": feedback_id,
                "created_at": _now_iso(),
            }
        )
        self.save_project(project_id, data)
        return feedback_id

    def upsert_teacher_assistant_review(self, project_id: str, review: dict) -> dict:
        data = self.load_project(project_id)
        reviews = data.setdefault("teacher_assistant_reviews", [])
        review_id = str(review.get("review_id") or uuid4())
        logical_project_id = str(review.get("logical_project_id", "")).strip()
        target_idx = -1
        for idx, item in enumerate(reviews):
            if item.get("review_id") == review_id:
                target_idx = idx
                break
            if logical_project_id and item.get("logical_project_id") == logical_project_id and item.get("teacher_id") == review.get("teacher_id"):
                target_idx = idx
                break
        base = {
            "review_id": review_id,
            "created_at": _now_iso(),
        }
        if target_idx >= 0:
            base = reviews[target_idx]
            reviews[target_idx] = {
                **base,
                **review,
                "review_id": base.get("review_id", review_id),
                "updated_at": _now_iso(),
            }
            saved = reviews[target_idx]
        else:
            saved = {
                **base,
                **review,
                "updated_at": _now_iso(),
            }
            reviews.append(saved)
        self.save_project(project_id, data)
        return saved

    def upsert_teacher_intervention(self, project_id: str, intervention: dict, intervention_id: str | None = None) -> dict:
        data = self.load_project(project_id)
        items = data.setdefault("teacher_interventions", [])
        real_id = intervention_id or str(intervention.get("intervention_id") or uuid4())
        target_idx = -1
        for idx, item in enumerate(items):
            if item.get("intervention_id") == real_id:
                target_idx = idx
                break
        if target_idx >= 0:
            existing = items[target_idx]
            items[target_idx] = {
                **existing,
                **intervention,
                "intervention_id": real_id,
                "updated_at": _now_iso(),
            }
            saved = items[target_idx]
        else:
            saved = {
                **intervention,
                "intervention_id": real_id,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            items.append(saved)
        self.save_project(project_id, data)
        return saved

    def update_teacher_intervention(self, project_id: str, intervention_id: str, patch: dict) -> dict | None:
        data = self.load_project(project_id)
        items = data.setdefault("teacher_interventions", [])
        for idx, item in enumerate(items):
            if item.get("intervention_id") != intervention_id:
                continue
            items[idx] = {
                **item,
                **patch,
                "intervention_id": intervention_id,
                "updated_at": _now_iso(),
            }
            self.save_project(project_id, data)
            return items[idx]
        return None

    def list_projects(self) -> list[dict]:
        projects: list[dict] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                projects.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                continue
        return projects


class ConversationStorage:
    """Stores conversations as individual JSON files under data/conversations/{project_id}/."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _conv_dir(self, project_id: str) -> Path:
        d = self.root / project_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def create(self, project_id: str, student_id: str, title: str = "") -> dict:
        conv_id = str(uuid4())
        conv = {
            "conversation_id": conv_id,
            "project_id": project_id,
            "student_id": student_id,
            "title": title or "新对话",
            "summary": "",
            "created_at": _now_iso(),
            "messages": [],
        }
        path = self._conv_dir(project_id) / f"{conv_id}.json"
        path.write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")
        return conv

    def list_conversations(self, project_id: str) -> list[dict]:
        d = self._conv_dir(project_id)
        convs: list[dict] = []
        for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                convs.append({
                    "conversation_id": data["conversation_id"],
                    "title": data.get("title", ""),
                    "created_at": data.get("created_at", ""),
                    "message_count": len(data.get("messages", [])),
                    "last_message": data.get("summary", "") or (data.get("messages") or [{}])[-1].get("content", "")[:60] if data.get("messages") else "",
                })
            except Exception:  # noqa: BLE001
                continue
        return convs

    def get(self, project_id: str, conversation_id: str) -> dict | None:
        path = self._conv_dir(project_id) / f"{conversation_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def delete(self, project_id: str, conversation_id: str) -> bool:
        path = self._conv_dir(project_id) / f"{conversation_id}.json"
        if not path.exists():
            return False
        path.unlink()
        return True

    def append_message(self, project_id: str, conversation_id: str, message: dict) -> None:
        path = self._conv_dir(project_id) / f"{conversation_id}.json"
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        data["messages"].append({
            **message,
            "timestamp": _now_iso(),
        })
        if message.get("role") == "assistant":
            trace = message.get("agent_trace", {}) or {}
            diagnosis = trace.get("diagnosis", {}) if isinstance(trace, dict) else {}
            next_task = trace.get("next_task", {}) if isinstance(trace, dict) else {}
            kg = trace.get("kg_analysis", {}) if isinstance(trace, dict) else {}
            category = trace.get("category", "") if isinstance(trace, dict) else ""
            title = (
                (next_task.get("title", "") if isinstance(next_task, dict) else "")
                or (diagnosis.get("bottleneck", "") if isinstance(diagnosis, dict) else "")
                or (kg.get("insight", "") if isinstance(kg, dict) else "")
                or str(message.get("content", ""))
            )
            summary = (
                (kg.get("insight", "") if isinstance(kg, dict) else "")
                or (diagnosis.get("bottleneck", "") if isinstance(diagnosis, dict) else "")
                or (next_task.get("description", "") if isinstance(next_task, dict) else "")
                or str(message.get("content", ""))
            )
            if category:
                title = f"{category} · {title}" if title else category
            title = str(title).replace("\n", " ").strip()[:24] or "新对话"
            summary = str(summary).replace("\n", " ").strip()[:60]
            if data.get("title") == "新对话":
                data["title"] = title
            data["summary"] = summary
        elif len(data["messages"]) == 1 and data.get("title") == "新对话":
            data["summary"] = str(message.get("content", "")).strip()[:60]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class UserStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.target = self.root / "users.json"
        if not self.target.exists():
            self.target.write_text("[]", encoding="utf-8")

    def _load(self) -> list[dict]:
        try:
            return json.loads(self.target.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return []

    def _save(self, users: list[dict]) -> None:
        self.target.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")

    def _hash_password(self, password: str, salt: str | None = None) -> tuple[str, str]:
        real_salt = salt or secrets.token_hex(16)
        password_hash = pbkdf2_hmac("sha256", password.encode("utf-8"), real_salt.encode("utf-8"), 120000).hex()
        return real_salt, password_hash

    def _public_user(self, user: dict) -> dict:
        return {
            "user_id": user.get("user_id"),
            "role": user.get("role"),
            "display_name": user.get("display_name"),
            "email": user.get("email"),
            "student_id": user.get("student_id"),
            "class_id": user.get("class_id"),
            "cohort_id": user.get("cohort_id"),
            "bio": user.get("bio", ""),
            "created_at": user.get("created_at"),
            "status": user.get("status", "active"),
            "last_login": user.get("last_login", ""),
        }

    def get_by_id(self, user_id: str) -> dict | None:
        for user in self._load():
            if user.get("user_id") == user_id:
                return self._public_user(user)
        return None

    def get_by_email(self, email: str) -> dict | None:
        email_key = email.strip().lower()
        for user in self._load():
            if str(user.get("email", "")).strip().lower() == email_key:
                return user
        return None

    def get_by_student_id(self, student_id: str) -> dict | None:
        sid = student_id.strip()
        if not sid:
            return None
        for user in self._load():
            if str(user.get("student_id", "")).strip() == sid:
                return user
        return None

    def create_user(self, payload: dict) -> dict:
        users = self._load()
        email = str(payload.get("email", "")).strip().lower()
        if not email:
            raise ValueError("邮箱不能为空")
        if any(str(user.get("email", "")).strip().lower() == email for user in users):
            raise ValueError("该邮箱已注册")

        salt, password_hash = self._hash_password(str(payload.get("password", "")))
        now = _now_iso()
        user = {
            "user_id": str(uuid4()),
            "role": payload.get("role", "student"),
            "display_name": str(payload.get("display_name", "")).strip() or email.split("@")[0],
            "email": email,
            "student_id": str(payload.get("student_id", "")).strip() or None,
            "class_id": str(payload.get("class_id", "")).strip() or None,
            "cohort_id": str(payload.get("cohort_id", "")).strip() or None,
            "bio": str(payload.get("bio", "")).strip(),
            "password_salt": salt,
            "password_hash": password_hash,
            "status": "active",
            "last_login": "",
            "created_at": now,
            "updated_at": now,
        }
        users.append(user)
        self._save(users)
        return self._public_user(user)

    def authenticate(self, email: str, password: str) -> dict | None:
        users = self._load()
        email_key = email.strip().lower()
        for user in users:
            if str(user.get("email", "")).strip().lower() != email_key:
                continue
            salt = str(user.get("password_salt", ""))
            _, password_hash = self._hash_password(password, salt)
            if password_hash != user.get("password_hash"):
                return None
            user["last_login"] = _now_iso()
            user["updated_at"] = _now_iso()
            self._save(users)
            return self._public_user(user)
        return None

    def change_password(self, email: str, current_password: str, new_password: str) -> dict | None:
        users = self._load()
        email_key = email.strip().lower()
        for user in users:
            if str(user.get("email", "")).strip().lower() != email_key:
                continue
            salt = str(user.get("password_salt", ""))
            _, current_hash = self._hash_password(current_password, salt)
            if current_hash != user.get("password_hash"):
                return None
            new_salt, new_hash = self._hash_password(new_password)
            user["password_salt"] = new_salt
            user["password_hash"] = new_hash
            user["updated_at"] = _now_iso()
            self._save(users)
            return self._public_user(user)
        return None

    def list_users(self, role: str | None = None, class_id: str | None = None, keyword: str | None = None) -> list[dict]:
        users = self._load()
        result: list[dict] = []
        role_key = (role or "").strip().lower()
        class_key = (class_id or "").strip()
        kw = (keyword or "").strip().lower()
        for user in users:
            if role_key and str(user.get("role", "")).strip().lower() != role_key:
                continue
            if class_key and str(user.get("class_id", "")) != class_key:
                continue
            if kw:
                blob = " ".join(
                    [
                        str(user.get("display_name", "")),
                        str(user.get("email", "")),
                        str(user.get("student_id", "")),
                        str(user.get("user_id", "")),
                    ]
                ).lower()
                if kw not in blob:
                    continue
            result.append(self._public_user(user))
        return result

    def update_user(self, user_id: str, payload: dict) -> dict | None:
        users = self._load()
        email_new = str(payload.get("email", "")).strip().lower() if payload.get("email") is not None else None
        for idx, user in enumerate(users):
            if user.get("user_id") != user_id:
                continue
            if email_new:
                for other in users:
                    if other is user:
                        continue
                    if str(other.get("email", "")).strip().lower() == email_new:
                        raise ValueError("该邮箱已被其他账号使用")
                user["email"] = email_new
            if "role" in payload and payload["role"]:
                user["role"] = payload["role"]
            if "display_name" in payload and payload["display_name"] is not None:
                user["display_name"] = str(payload["display_name"]).strip()
            if "student_id" in payload:
                v = str(payload["student_id"] or "").strip()
                user["student_id"] = v or None
            if "class_id" in payload:
                v = str(payload["class_id"] or "").strip()
                user["class_id"] = v or None
            if "cohort_id" in payload:
                v = str(payload["cohort_id"] or "").strip()
                user["cohort_id"] = v or None
            if "bio" in payload and payload["bio"] is not None:
                user["bio"] = str(payload["bio"]).strip()
            if "status" in payload and payload["status"] in {"active", "disabled"}:
                user["status"] = payload["status"]
            user["updated_at"] = _now_iso()
            users[idx] = user
            self._save(users)
            return self._public_user(user)
        return None

    def delete_user(self, user_id: str) -> bool:
        users = self._load()
        new_users = [u for u in users if u.get("user_id") != user_id]
        if len(new_users) == len(users):
            return False
        self._save(new_users)
        return True

    def admin_change_password(self, user_id: str, new_password: str) -> dict | None:
        users = self._load()
        for idx, user in enumerate(users):
            if user.get("user_id") != user_id:
                continue
            salt, password_hash = self._hash_password(new_password)
            user["password_salt"] = salt
            user["password_hash"] = password_hash
            user["updated_at"] = _now_iso()
            users[idx] = user
            self._save(users)
            return self._public_user(user)
        return None

    def admin_create_user(self, payload: dict) -> tuple[dict, str | None]:
        users = self._load()
        email = str(payload.get("email", "")).strip().lower()
        if not email:
            raise ValueError("邮箱不能为空")
        if any(str(user.get("email", "")).strip().lower() == email for user in users):
            raise ValueError("该邮箱已注册")
        raw_password = str(payload.get("password") or "").strip()
        if not raw_password:
            alphabet = string.ascii_letters + string.digits
            raw_password = "".join(secrets.choice(alphabet) for _ in range(10))
        salt, password_hash = self._hash_password(raw_password)
        now = _now_iso()
        user = {
            "user_id": str(uuid4()),
            "role": payload.get("role", "student"),
            "display_name": str(payload.get("display_name", "")).strip() or email.split("@")[0],
            "email": email,
            "student_id": str(payload.get("student_id", "")).strip() or None,
            "class_id": str(payload.get("class_id", "")).strip() or None,
            "cohort_id": str(payload.get("cohort_id", "")).strip() or None,
            "bio": str(payload.get("bio", "")).strip(),
            "password_salt": salt,
            "password_hash": password_hash,
            "status": payload.get("status", "active"),
            "last_login": "",
            "created_at": now,
            "updated_at": now,
        }
        users.append(user)
        self._save(users)
        return self._public_user(user), raw_password

    def get_or_create_by_phone(self, phone: str) -> dict:
        """Find user by phone or auto-create a student account."""
        phone = phone.strip()
        users = self._load()
        for user in users:
            if str(user.get("phone", "")).strip() == phone:
                return self._public_user(user)
        # auto-create
        now = _now_iso()
        salt, pw_hash = self._hash_password(secrets.token_hex(8))
        user = {
            "user_id": str(uuid4()),
            "role": "student",
            "display_name": f"用户{phone[-4:]}",
            "email": f"{phone}@phone.local",
            "phone": phone,
            "student_id": None,
            "class_id": None,
            "cohort_id": None,
            "bio": "",
            "password_salt": salt,
            "password_hash": pw_hash,
            "created_at": now,
            "updated_at": now,
        }
        users.append(user)
        self._save(users)
        return self._public_user(user)


class TeamStorage:
    """Manages teams with JSON file persistence at data/teams/teams.json."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.target = self.root / "teams.json"
        if not self.target.exists():
            self.target.write_text("[]", encoding="utf-8")

    def _load(self) -> list[dict]:
        try:
            return json.loads(self.target.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(self, teams: list[dict]) -> None:
        self.target.write_text(json.dumps(teams, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _gen_invite_code() -> str:
        chars = string.ascii_uppercase + string.digits
        return "".join(secrets.choice(chars) for _ in range(6))

    def create_team(self, teacher_id: str, teacher_name: str, team_name: str) -> dict:
        teams = self._load()
        code = self._gen_invite_code()
        while any(t.get("invite_code") == code for t in teams):
            code = self._gen_invite_code()
        team = {
            "team_id": str(uuid4()),
            "team_name": team_name.strip(),
            "invite_code": code,
            "teacher_id": teacher_id,
            "teacher_name": teacher_name,
            "members": [],
            "created_at": _now_iso(),
        }
        teams.append(team)
        self._save(teams)
        return team

    def get_team(self, team_id: str) -> dict | None:
        for t in self._load():
            if t.get("team_id") == team_id:
                return t
        return None

    def find_by_invite_code(self, code: str) -> dict | None:
        code = code.strip().upper()
        for t in self._load():
            if t.get("invite_code") == code:
                return t
        return None

    def list_by_teacher(self, teacher_id: str) -> list[dict]:
        return [t for t in self._load() if t.get("teacher_id") == teacher_id]

    def list_by_member(self, user_id: str) -> list[dict]:
        result = []
        for t in self._load():
            if any(m.get("user_id") == user_id for m in t.get("members", [])):
                result.append(t)
        return result

    def list_all(self) -> list[dict]:
        return self._load()

    def add_member(self, team_id: str, user_id: str) -> dict | None:
        teams = self._load()
        for t in teams:
            if t.get("team_id") != team_id:
                continue
            if any(m.get("user_id") == user_id for m in t.get("members", [])):
                return t
            t.setdefault("members", []).append({
                "user_id": user_id,
                "joined_at": _now_iso(),
            })
            self._save(teams)
            return t
        return None

    def remove_member(self, team_id: str, user_id: str) -> dict | None:
        teams = self._load()
        for t in teams:
            if t.get("team_id") != team_id:
                continue
            t["members"] = [m for m in t.get("members", []) if m.get("user_id") != user_id]
            self._save(teams)
            return t
        return None

    def rename_team(self, team_id: str, teacher_id: str, team_name: str) -> dict | None:
        teams = self._load()
        name = team_name.strip()
        if not name:
            return None
        for t in teams:
            if t.get("team_id") != team_id or t.get("teacher_id") != teacher_id:
                continue
            t["team_name"] = name
            self._save(teams)
            return t
        return None

    def delete_team(self, team_id: str, teacher_id: str) -> bool:
        teams = self._load()
        new_teams = [t for t in teams if not (t.get("team_id") == team_id and t.get("teacher_id") == teacher_id)]
        if len(new_teams) == len(teams):
            return False
        self._save(new_teams)
        return True
