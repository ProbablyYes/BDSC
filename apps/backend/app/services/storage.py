import json
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
            return {"project_id": project_id, "submissions": [], "teacher_feedback": []}
        return json.loads(target.read_text(encoding="utf-8"))

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
