"""
ChatStorage — JSON-file-based persistence for chat rooms and messages.
Follows the same pattern as UserStorage / TeamStorage.

Storage layout:
    data/chat/rooms.json               — all room metadata
    data/chat/messages/{room_id}.json   — messages for one room
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

BJ_TZ = timezone(timedelta(hours=8))


def _now_iso() -> str:
    return datetime.now(BJ_TZ).isoformat()


class ChatStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.msg_root = self.root / "messages"
        self.msg_root.mkdir(parents=True, exist_ok=True)
        self.rooms_file = self.root / "rooms.json"
        if not self.rooms_file.exists():
            self.rooms_file.write_text("[]", encoding="utf-8")

    # ── Room helpers ──

    def _load_rooms(self) -> list[dict]:
        try:
            return json.loads(self.rooms_file.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_rooms(self, rooms: list[dict]) -> None:
        self.rooms_file.write_text(
            json.dumps(rooms, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _msg_file(self, room_id: str) -> Path:
        return self.msg_root / f"{room_id}.json"

    def _load_msgs(self, room_id: str) -> list[dict]:
        f = self._msg_file(room_id)
        if not f.exists():
            return []
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_msgs(self, room_id: str, msgs: list[dict]) -> None:
        self._msg_file(room_id).write_text(
            json.dumps(msgs, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── Room CRUD ──

    def create_room(
        self,
        name: str,
        room_type: str,
        members: list[str],
        admin_ids: list[str] | None = None,
        team_id: str | None = None,
        project_id: str | None = None,
    ) -> dict:
        rooms = self._load_rooms()
        room = {
            "room_id": str(uuid4()),
            "type": room_type,
            "name": name,
            "avatar": None,
            "members": members,
            "admin_ids": admin_ids or (members[:1] if members else []),
            "team_id": team_id,
            "project_id": project_id,
            "created_at": _now_iso(),
            "last_message_preview": "",
            "last_message_at": "",
            "unread_counts": {},
        }
        rooms.append(room)
        self._save_rooms(rooms)
        return room

    def get_room(self, room_id: str) -> dict | None:
        for r in self._load_rooms():
            if r["room_id"] == room_id:
                return r
        return None

    def list_rooms_for_user(self, user_id: str) -> list[dict]:
        return [
            r for r in self._load_rooms()
            if user_id in r.get("members", [])
        ]

    def add_member(self, room_id: str, user_id: str) -> dict | None:
        rooms = self._load_rooms()
        for r in rooms:
            if r["room_id"] == room_id:
                if user_id not in r["members"]:
                    r["members"].append(user_id)
                    self._save_rooms(rooms)
                return r
        return None

    def remove_member(self, room_id: str, user_id: str) -> dict | None:
        rooms = self._load_rooms()
        for r in rooms:
            if r["room_id"] == room_id:
                r["members"] = [m for m in r["members"] if m != user_id]
                self._save_rooms(rooms)
                return r
        return None

    def delete_room(self, room_id: str) -> bool:
        rooms = self._load_rooms()
        new = [r for r in rooms if r["room_id"] != room_id]
        if len(new) == len(rooms):
            return False
        self._save_rooms(new)
        f = self._msg_file(room_id)
        if f.exists():
            f.unlink()
        return True

    def update_room_preview(self, room_id: str, preview: str) -> None:
        rooms = self._load_rooms()
        for r in rooms:
            if r["room_id"] == room_id:
                r["last_message_preview"] = preview[:80]
                r["last_message_at"] = _now_iso()
                break
        self._save_rooms(rooms)

    # ── Messages ──

    def add_message(
        self,
        room_id: str,
        sender_id: str,
        sender_name: str,
        msg_type: str,
        content: str,
        mentions: list[str] | None = None,
        reply_to: str | None = None,
        file_meta: dict | None = None,
    ) -> dict:
        msgs = self._load_msgs(room_id)
        msg = {
            "msg_id": str(uuid4()),
            "room_id": room_id,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "type": msg_type,
            "content": content,
            "mentions": mentions or [],
            "reply_to": reply_to,
            "file_meta": file_meta,
            "reactions": {},
            "created_at": _now_iso(),
        }
        msgs.append(msg)
        self._save_msgs(room_id, msgs)
        preview = f"{sender_name}: {content[:40]}" if msg_type == "text" else f"{sender_name}: [{msg_type}]"
        self.update_room_preview(room_id, preview)
        return msg

    def get_messages(
        self, room_id: str, limit: int = 50, before: str | None = None
    ) -> list[dict]:
        msgs = self._load_msgs(room_id)
        if before:
            msgs = [m for m in msgs if m["created_at"] < before]
        return msgs[-limit:]

    def add_reaction(self, room_id: str, msg_id: str, user_id: str, emoji: str) -> dict | None:
        msgs = self._load_msgs(room_id)
        for m in msgs:
            if m["msg_id"] == msg_id:
                reactions = m.setdefault("reactions", {})
                users = reactions.setdefault(emoji, [])
                if user_id in users:
                    users.remove(user_id)
                    if not users:
                        del reactions[emoji]
                else:
                    users.append(user_id)
                self._save_msgs(room_id, msgs)
                return m
        return None

    # ── AI analysis persistence ──

    def _ai_dir(self) -> Path:
        d = self.root / "ai_analyses"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_ai_analysis(self, room_id: str, entry: dict) -> None:
        f = self._ai_dir() / f"{room_id}.json"
        items: list[dict] = []
        if f.exists():
            try:
                items = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                items = []
        items.append(entry)
        if len(items) > 200:
            items = items[-200:]
        f.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_ai_analyses(self, room_id: str) -> list[dict]:
        f = self._ai_dir() / f"{room_id}.json"
        if not f.exists():
            return []
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return []

    def delete_ai_analysis(self, room_id: str, entry_id: str) -> bool:
        f = self._ai_dir() / f"{room_id}.json"
        if not f.exists():
            return False
        try:
            items = json.loads(f.read_text(encoding="utf-8"))
            before = len(items)
            items = [it for it in items if it.get("id") != entry_id]
            if len(items) == before:
                return False
            f.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            return True
        except Exception:
            return False

    # ── Files ──

    def list_files(self, room_id: str) -> list[dict]:
        msgs = self._load_msgs(room_id)
        return [m for m in msgs if m.get("type") in ("file", "image") and m.get("file_meta")]
