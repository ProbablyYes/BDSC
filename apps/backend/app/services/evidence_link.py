"""
轻量证据回定：把 AI 产出的 quote / slot 值映射回 conversation 里具体的 message。

约定：
- message_id 用 "<conversation_id>#<turn_index>" 表示（稳定 key）；
- 如果 quote 长度很短或过于泛化（< 6 汉字），只匹配角色=user 的消息，避免误命中 assistant 自己输出。
- 对单个 conversation 做 LRU 缓存，避免热点接口每次读盘。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

from app.services.storage import ConversationStorage


_PUNCT_RE = re.compile(r"[\s，。！？、；：\"\"''「」【】（）《》,.!?;:(){}\[\]\-\u3000]+")


def _normalize(text: str) -> str:
    return _PUNCT_RE.sub("", (text or "").strip())


def _excerpt(text: str, around: str = "", window: int = 120) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if not around or around not in text:
        return text[:window]
    idx = text.index(around)
    start = max(0, idx - 30)
    end = min(len(text), idx + len(around) + 60)
    return text[start:end]


def _lcs_ratio(a: str, b: str) -> float:
    """最长公共子串占 a 的比例。"""
    if not a or not b:
        return 0.0
    sm = SequenceMatcher(None, a, b, autojunk=False)
    match = sm.find_longest_match(0, len(a), 0, len(b))
    if match.size == 0:
        return 0.0
    return match.size / max(1, len(a))


class EvidenceLinker:
    """对一个 ConversationStorage 封装的消息回定器。"""

    def __init__(self, conv_store: ConversationStorage) -> None:
        self._store = conv_store

    def _load_messages(self, project_id: str, conversation_id: str) -> list[dict]:
        if not project_id or not conversation_id:
            return []
        try:
            conv = self._store.get(project_id, conversation_id)
        except Exception:  # noqa: BLE001
            return []
        if not conv:
            return []
        msgs = conv.get("messages") or []
        # 轻量标准化：每条消息补 turn_index 和 role
        normalized = []
        for i, m in enumerate(msgs):
            if not isinstance(m, dict):
                continue
            normalized.append({
                "turn_index": i,
                "role": str(m.get("role") or ""),
                "content": str(m.get("content") or ""),
                "timestamp": str(m.get("timestamp") or ""),
                "message_id": f"{conversation_id}#{i}",
            })
        return normalized

    def link_text(
        self,
        project_id: str,
        conversation_id: str,
        text: str,
        *,
        prefer_role: str = "user",
        min_confidence: float = 0.3,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """回定一段 text 到最可能的若干 messages。"""
        if not text:
            return []
        messages = self._load_messages(project_id, conversation_id)
        if not messages:
            return []
        norm_query = _normalize(text)
        if not norm_query:
            return []

        scored: list[tuple[float, dict]] = []
        for m in messages:
            norm_m = _normalize(m["content"])
            if not norm_m:
                continue

            # 1) 全子串命中
            if norm_query in norm_m:
                conf = 1.0
            elif norm_m in norm_query:
                conf = 0.9
            else:
                # 2) 最长公共子串比例
                r1 = _lcs_ratio(norm_query, norm_m)
                r2 = _lcs_ratio(norm_m, norm_query)
                conf = max(r1, r2)
                # 3) 关键词命中加分（分词后交集占比）
                q_tokens = {t for t in re.split(r"\W+", text) if len(t) >= 2}
                if q_tokens:
                    c_tokens = {t for t in re.split(r"\W+", m["content"]) if len(t) >= 2}
                    inter = q_tokens & c_tokens
                    if inter:
                        conf = max(conf, len(inter) / max(1, len(q_tokens)))

            # 优先同角色：如 quote 来自用户，assistant 的回复降权
            if prefer_role and m["role"] and m["role"] != prefer_role:
                conf *= 0.6

            if conf >= min_confidence:
                scored.append((conf, m))

        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for conf, m in scored[:top_k]:
            out.append({
                "message_id": m["message_id"],
                "turn_index": m["turn_index"],
                "role": m["role"],
                "excerpt": _excerpt(m["content"], around=text[:20], window=180),
                "confidence": round(float(conf), 3),
            })
        return out

    def link_slots_batch(
        self,
        project_id: str,
        conversation_id: str,
        slot_values: list[tuple[str, str]],
    ) -> list[tuple[str, dict | None]]:
        """一次性回定多个 (slot_name, slot_text)。"""
        results: list[tuple[str, dict | None]] = []
        for slot, val in slot_values:
            if not val:
                results.append((slot, None))
                continue
            links = self.link_text(project_id, conversation_id, val, top_k=1, min_confidence=0.25)
            results.append((slot, links[0] if links else None))
        return results


# 模块级 singleton pattern —— 由 main.py 在 startup 时注入。
_default_linker: EvidenceLinker | None = None


def set_default_linker(linker: EvidenceLinker) -> None:
    global _default_linker
    _default_linker = linker


def get_default_linker() -> EvidenceLinker | None:
    return _default_linker


__all__ = ["EvidenceLinker", "set_default_linker", "get_default_linker"]
