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

    def append_submission(self, project_id: str, submission: dict) -> None:
        data = self.load_project(project_id)
        data["submissions"].append(
            {
                **submission,
                "submission_id": str(uuid4()),
                "created_at": datetime.utcnow().isoformat(),
            }
        )
        self.save_project(project_id, data)

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
