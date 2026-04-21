"""
AI 结论订正层：教师可以改写任何带 Rationale 的字段，必须提供理由。
学生端 / 教师端返回数据时，统一在 Rationale 上挂 teacher_override=
{teacher_name, reason, ai_value, created_at}。

落盘：data/ai_overrides/{project_id}/{conversation_id | 'overall'}.json
结构：{"overrides": [{...}]}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4


logger = logging.getLogger(__name__)
BJ_TZ = timezone(timedelta(hours=8))


def _now_iso() -> str:
    return datetime.now(BJ_TZ).isoformat()


def _safe_filename(s: str) -> str:
    return "".join(c for c in (s or "_") if c.isalnum() or c in ("-", "_", "."))[:120] or "_"


class AiOverrideStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _file(self, project_id: str, conversation_id: str | None) -> Path:
        pid = _safe_filename(project_id or "_global")
        cid = _safe_filename(conversation_id or "overall")
        d = self.root / pid
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{cid}.json"

    def _load(self, project_id: str, conversation_id: str | None) -> list[dict]:
        p = self._file(project_id, conversation_id)
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return list(data.get("overrides") or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("override load failed: %s", exc)
            return []

    def _save(self, project_id: str, conversation_id: str | None, overrides: list[dict]) -> None:
        p = self._file(project_id, conversation_id)
        p.write_text(
            json.dumps({"overrides": overrides}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list(
        self,
        project_id: str,
        conversation_id: str | None = None,
        *,
        target_type: str | None = None,
        target_key: str | None = None,
    ) -> list[dict]:
        all_ov = self._load(project_id, conversation_id)
        out = all_ov
        if target_type:
            out = [o for o in out if o.get("target_type") == target_type]
        if target_key:
            out = [o for o in out if o.get("target_key") == target_key]
        return out

    def list_many(
        self,
        project_id: str,
        conversation_ids: list[str | None],
    ) -> list[dict]:
        seen = set()
        out: list[dict] = []
        for cid in conversation_ids:
            key = cid or "overall"
            if key in seen:
                continue
            seen.add(key)
            out.extend(self._load(project_id, cid))
        return out

    def upsert(self, payload: dict) -> dict:
        project_id = str(payload.get("project_id") or "").strip()
        conversation_id = str(payload.get("conversation_id") or "").strip() or None
        target_type = str(payload.get("target_type") or "").strip()
        target_key = str(payload.get("target_key") or "").strip()
        if not (project_id and target_type and target_key):
            raise ValueError("project_id / target_type / target_key are required")
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            raise ValueError("修改 AI 结论必须提供理由（reason）")

        overrides = self._load(project_id, conversation_id)
        found_idx: int | None = None
        for i, o in enumerate(overrides):
            if o.get("target_type") == target_type and o.get("target_key") == target_key:
                found_idx = i
                break

        ov_id = str(payload.get("override_id") or "").strip() or (
            overrides[found_idx]["override_id"] if found_idx is not None else str(uuid4())
        )
        record = {
            "override_id": ov_id,
            "project_id": project_id,
            "conversation_id": conversation_id,
            "target_type": target_type,
            "target_key": target_key,
            "ai_value": payload.get("ai_value"),
            "teacher_value": payload.get("teacher_value"),
            "reason": reason,
            "teacher_id": str(payload.get("teacher_id") or ""),
            "teacher_name": str(payload.get("teacher_name") or ""),
            "created_at": _now_iso() if found_idx is None else overrides[found_idx].get("created_at", _now_iso()),
            "updated_at": _now_iso(),
        }
        if found_idx is not None:
            overrides[found_idx] = record
        else:
            overrides.append(record)
        self._save(project_id, conversation_id, overrides)
        return record

    def delete(self, project_id: str, conversation_id: str | None, override_id: str) -> bool:
        overrides = self._load(project_id, conversation_id)
        before = len(overrides)
        overrides = [o for o in overrides if o.get("override_id") != override_id]
        if len(overrides) == before:
            return False
        self._save(project_id, conversation_id, overrides)
        return True


def apply_to_rationale(rationale: dict | None, overrides: list[dict]) -> dict | None:
    """若 overrides 命中 rationale['field']，将 teacher_override 挂到 rationale 上，
    并把 value 替换为教师版本。不会破坏原有 ai_value。"""
    if not rationale or not isinstance(rationale, dict):
        return rationale
    field = str(rationale.get("field") or "")
    if not field:
        return rationale
    match = next((o for o in overrides if _match_target(o, field)), None)
    if not match:
        return rationale
    ai_value = rationale.get("value")
    rationale["teacher_override"] = {
        "teacher_name": match.get("teacher_name") or "老师",
        "teacher_id": match.get("teacher_id") or "",
        "reason": match.get("reason") or "",
        "ai_value": ai_value,
        "created_at": match.get("updated_at") or match.get("created_at"),
    }
    if match.get("teacher_value") is not None and match.get("teacher_value") != "":
        rationale["value"] = match["teacher_value"]
    return rationale


def apply_to_dict_field(obj: dict, field_path: str, overrides: list[dict], target_type: str) -> None:
    """用于非 Rationale 的普通字段（如 portrait.summary / strength_dimensions[0]）。"""
    target_key = f"{target_type}:{field_path}"
    match = next((o for o in overrides if o.get("target_type") == target_type and o.get("target_key") == target_key), None)
    if not match:
        return
    parts = field_path.split(".")
    cur: Any = obj
    for p in parts[:-1]:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return
    if isinstance(cur, dict):
        ai_value = cur.get(parts[-1])
        cur[parts[-1]] = match.get("teacher_value", ai_value)
        cur.setdefault("__teacher_overrides", {})[parts[-1]] = {
            "ai_value": ai_value,
            "teacher_name": match.get("teacher_name") or "老师",
            "reason": match.get("reason") or "",
            "created_at": match.get("updated_at") or match.get("created_at"),
        }


def _match_target(override: dict, rationale_field: str) -> bool:
    target_key = str(override.get("target_key") or "")
    if not target_key:
        return False
    if target_key == rationale_field:
        return True
    # 兼容 target_type:target_key 的写法（前端方便传）
    ttype = str(override.get("target_type") or "")
    if target_key == rationale_field.split(":", 1)[-1] and ttype and rationale_field.startswith(f"{ttype}:"):
        return True
    return False


def walk_and_apply(obj: Any, overrides: list[dict]) -> Any:
    """递归遍历 obj，对每个形如 {"field": "...", "value": ...} 的 rationale 挂 teacher_override。"""
    if not overrides:
        return obj
    if isinstance(obj, dict):
        if "field" in obj and "value" in obj and isinstance(obj.get("field"), str):
            apply_to_rationale(obj, overrides)
        for k, v in list(obj.items()):
            obj[k] = walk_and_apply(v, overrides)
        return obj
    if isinstance(obj, list):
        return [walk_and_apply(i, overrides) for i in obj]
    return obj


__all__ = [
    "AiOverrideStore",
    "apply_to_rationale",
    "apply_to_dict_field",
    "walk_and_apply",
]
