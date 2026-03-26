import json
import secrets
from hashlib import pbkdf2_hmac
from datetime import datetime
from pathlib import Path
from uuid import uuid4


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
                "teacher_annotations": [],
                "teacher_feedback_files": [],
                "teacher_document_edits": [],
            }
        data = json.loads(target.read_text(encoding="utf-8"))
        # new确保新增字段存在
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
            "created_at": datetime.utcnow().isoformat(),
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
                "created_at": datetime.utcnow().isoformat(),
            }
        )
        self.save_project(project_id, data)
        return feedback_id

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
            "created_at": datetime.utcnow().isoformat(),
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
                    "last_message": (data.get("messages") or [{}])[-1].get("content", "")[:60] if data.get("messages") else "",
                })
            except Exception:  # noqa: BLE001
                continue
        return convs

    def get(self, project_id: str, conversation_id: str) -> dict | None:
        path = self._conv_dir(project_id) / f"{conversation_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def append_message(self, project_id: str, conversation_id: str, message: dict) -> None:
        path = self._conv_dir(project_id) / f"{conversation_id}.json"
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        data["messages"].append({
            **message,
            "timestamp": datetime.utcnow().isoformat(),
        })
        if len(data["messages"]) == 1 and data.get("title") == "新对话":
            data["title"] = str(message.get("content", ""))[:30] or "新对话"
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
        }

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
        now = datetime.utcnow().isoformat()
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
            "created_at": now,
            "updated_at": now,
        }
        users.append(user)
        self._save(users)
        return self._public_user(user)

    def authenticate(self, email: str, password: str) -> dict | None:
        user = self.get_by_email(email)
        if not user:
            return None
        salt = str(user.get("password_salt", ""))
        _, password_hash = self._hash_password(password, salt)
        if password_hash != user.get("password_hash"):
            return None
        return self._public_user(user)

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
            user["updated_at"] = datetime.utcnow().isoformat()
            self._save(users)
            return self._public_user(user)
        return None

    def get_or_create_by_phone(self, phone: str) -> dict:
        """Find user by phone or auto-create a student account."""
        phone = phone.strip()
        users = self._load()
        for user in users:
            if str(user.get("phone", "")).strip() == phone:
                return self._public_user(user)
        # auto-create
        now = datetime.utcnow().isoformat()
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
