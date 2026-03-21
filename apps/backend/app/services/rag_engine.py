"""
RAG engine: load 89 structured case JSONs, build in-memory vector index,
and retrieve the most relevant cases for a given query.

Uses SiliconFlow embedding API (BAAI/bge-m3) via the OpenAI-compatible client.
Fallback: TF-IDF cosine similarity when embedding API is unavailable.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM = 1024


@dataclass
class CaseChunk:
    case_id: str
    category: str
    project_name: str
    summary: str
    pain_points: list[str]
    solution: list[str]
    innovation_points: list[str]
    business_model: list[str]
    evidence_quotes: list[str]
    risk_flags: list[str]
    rubric_coverage: list[dict]
    confidence: float
    text_for_search: str = ""
    embedding: np.ndarray | None = field(default=None, repr=False)


_GARBAGE_PATTERNS = re.compile(
    r"^[\d\s\.…·—]+$|^目录$|^前言|^第[一二三四五六七八九十]|^参赛作品|^\d+$"
)

_MOJIBAKE_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_LATIN_GARBLE_RE = re.compile(r"[\xc0-\xff]{3,}")
_CJK_RARE_RE = re.compile(
    r"[\u3400-\u4DBF"   # CJK Extension A (rare)
    r"\U00020000-\U0002A6DF"  # CJK Extension B (very rare)
    r"\U0002A700-\U0002EBEF"  # CJK Extensions C-F
    r"\u2E80-\u2EFF"    # CJK Radicals Supplement
    r"\u2FF0-\u2FFF"    # Ideographic Description Characters
    r"\u31C0-\u31EF"    # CJK Strokes
    r"⃻↯☛]"
)


def _has_cjk_garble(text: str) -> bool:
    """Detect if text contains rare CJK characters that indicate mojibake."""
    if not text:
        return False
    rare_count = len(_CJK_RARE_RE.findall(text))
    total_cjk = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4DBF]", text))
    if total_cjk == 0:
        return False
    return rare_count / max(total_cjk, 1) > 0.15


def _fix_garbled(text: str) -> str:
    """Attempt to fix common encoding issues in PDF-extracted Chinese text."""
    if not text:
        return text
    if _has_cjk_garble(text):
        text = _CJK_RARE_RE.sub("", text)
        allowed = (
            "\u4e00-\u9fffA-Za-z0-9\\s"
            "\uff0c\u3002\u3001\uff1b\uff1a"
            "\u201c\u201d\u2018\u2019"
            "\uff08\uff09\u3010\u3011\u300a\u300b"
            "\uff01\uff1f.%/\u3000\uff01-\uff5e\\-"
        )
        text = re.sub(f"[^{allowed}]", " ", text)
        text = re.sub(r"\s{2,}", " ", text)
    text = _MOJIBAKE_RE.sub("", text)
    try:
        if _LATIN_GARBLE_RE.search(text):
            fixed = text.encode("latin-1").decode("utf-8", errors="ignore")
            if len(fixed) > len(text) * 0.3:
                text = fixed
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    try:
        if _LATIN_GARBLE_RE.search(text):
            fixed = text.encode("cp1252").decode("utf-8", errors="ignore")
            if len(fixed) > len(text) * 0.3:
                text = fixed
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    text = (
        text
        .replace("\ufffd", "")
        .replace("\u00e2\u0080\u0093", "\u2013")
        .replace("\u00e2\u0080\u0094", "\u2014")
        .replace("\u00e2\u0080\u0098", "\u2018")
        .replace("\u00e2\u0080\u0099", "\u2019")
        .replace("\u00e2\u0080\u009c", "\u201c")
        .replace("\u00e2\u0080\u009d", "\u201d")
        .replace("\u00c3\u00a9", "\u00e9")
    )
    return text.strip()


def _clean_list(items: list) -> list[str]:
    """Remove garbage entries from extracted lists."""
    cleaned: list[str] = []
    for item in items:
        s = _fix_garbled(str(item).strip())
        if len(s) < 3 or _GARBAGE_PATTERNS.match(s):
            continue
        cleaned.append(s)
    return cleaned


def _case_quality_score(case: dict) -> float:
    """Score 0-1 indicating how well the case was parsed."""
    score = 0.0
    stats = case.get("document_stats", {})
    core = stats.get("core_text_chars", 0)
    full = stats.get("full_text_chars", 1)
    if core > 500:
        score += 0.3
    if full > 0 and core / full > 0.3:
        score += 0.2

    profile = case.get("project_profile", {})
    for key in ("pain_points", "solution", "target_users"):
        items = _clean_list(profile.get(key, []))
        if len(items) >= 2:
            score += 0.1

    evidence = case.get("evidence", [])
    real_quotes = [e for e in evidence if len(str(e.get("quote", ""))) > 20]
    if len(real_quotes) >= 2:
        score += 0.2
    return min(1.0, score)


def _build_search_text(case: dict) -> str:
    """Flatten case JSON into a single searchable text block."""
    parts: list[str] = []
    profile = case.get("project_profile", {})
    if profile.get("project_name"):
        parts.append(f"项目：{profile['project_name']}")
    for key in ("target_users", "pain_points", "solution", "innovation_points",
                "business_model", "market_analysis", "execution_plan", "risk_control"):
        items = _clean_list(profile.get(key, []))
        if items:
            parts.append(" ".join(items[:5]))
    evidence = case.get("evidence", [])
    for ev in evidence[:6]:
        quote = str(ev.get("quote", ""))
        if len(quote) > 20:
            parts.append(quote)
    if case.get("summary"):
        parts.append(case["summary"][:500])
    return "\n".join(parts)[:2000]


def _load_cases(case_dir: Path) -> list[CaseChunk]:
    raw_chunks: list[tuple[float, CaseChunk]] = []
    for fp in sorted(case_dir.glob("case_*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue

        quality = _case_quality_score(data)
        if quality < 0.2:
            continue

        raw_summary = data.get("summary", "")
        if _has_cjk_garble(raw_summary):
            logger.info("Skipping garbled case: %s", fp.name)
            continue

        profile = data.get("project_profile", {})
        evidence = data.get("evidence", [])
        chunk = CaseChunk(
            case_id=data.get("case_id", fp.stem),
            category=data.get("source", {}).get("category", "未分类"),
            project_name=_fix_garbled(profile.get("project_name", "未知项目")),
            summary=_fix_garbled(raw_summary)[:600],
            pain_points=_clean_list(profile.get("pain_points", [])),
            solution=_clean_list(profile.get("solution", [])),
            innovation_points=_clean_list(profile.get("innovation_points", [])),
            business_model=_clean_list(profile.get("business_model", []))[:4],
            evidence_quotes=[_fix_garbled(e.get("quote", "")) for e in evidence[:4]
                             if len(str(e.get("quote", ""))) > 20],
            risk_flags=data.get("risk_flags", []),
            rubric_coverage=data.get("rubric_coverage", []),
            confidence=float(data.get("confidence", 0)),
            text_for_search=_build_search_text(data),
        )
        raw_chunks.append((quality, chunk))

    # deduplicate by project_name: keep the one with highest quality
    seen: dict[str, tuple[float, CaseChunk]] = {}
    for quality, chunk in raw_chunks:
        key = chunk.project_name.strip()
        if key not in seen or quality > seen[key][0]:
            seen[key] = (quality, chunk)

    chunks = [chunk for _, chunk in seen.values()]
    logger.info("RAG: loaded %d unique cases (filtered from %d raw, dir=%s)",
                len(chunks), len(raw_chunks), case_dir)
    return chunks


def _tfidf_similarity(query: str, documents: list[str]) -> np.ndarray:
    """Simple TF-IDF cosine similarity fallback (no external deps)."""
    all_texts = [query] + documents
    vocab: dict[str, int] = {}
    for text in all_texts:
        for ch in re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z]+", text.lower()):
            if ch not in vocab:
                vocab[ch] = len(vocab)

    if not vocab:
        return np.zeros(len(documents))

    matrix = np.zeros((len(all_texts), len(vocab)))
    for i, text in enumerate(all_texts):
        for ch in re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z]+", text.lower()):
            if ch in vocab:
                matrix[i, vocab[ch]] += 1

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    matrix = matrix / norms
    scores = matrix[1:] @ matrix[0]
    return scores


class RagEngine:
    def __init__(self) -> None:
        self._chunks: list[CaseChunk] = []
        self._embeddings: np.ndarray | None = None
        self._client: OpenAI | None = None
        self._embed_ready = False

    def initialize(self) -> None:
        case_dir = settings.data_root / "graph_seed" / "case_structured"
        if not case_dir.exists():
            logger.warning("RAG: case directory not found: %s", case_dir)
            return
        self._chunks = _load_cases(case_dir)
        if not self._chunks:
            return

        if settings.llm_api_key and settings.llm_base_url:
            self._client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
            self._build_embeddings()

    def _build_embeddings(self) -> None:
        if not self._client or not self._chunks:
            return
        texts = [c.text_for_search for c in self._chunks]
        try:
            batch_size = 20
            all_embs: list[list[float]] = []
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                resp = self._client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
                for item in resp.data:
                    all_embs.append(item.embedding)
            self._embeddings = np.array(all_embs, dtype=np.float32)
            norms = np.linalg.norm(self._embeddings, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            self._embeddings = self._embeddings / norms
            self._embed_ready = True
            logger.info("RAG: built embeddings for %d cases (dim=%d)", len(self._chunks), self._embeddings.shape[1])
        except Exception as exc:
            logger.warning("RAG: embedding API failed, falling back to TF-IDF: %s", exc)
            self._embed_ready = False

    def _embed_query(self, query: str) -> np.ndarray | None:
        if not self._client:
            return None
        try:
            resp = self._client.embeddings.create(model=EMBEDDING_MODEL, input=[query[:1500]])
            vec = np.array(resp.data[0].embedding, dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            return vec
        except Exception:
            return None

    def retrieve(self, query: str, top_k: int = 3, category_filter: str | None = None) -> list[dict[str, Any]]:
        if not self._chunks:
            return []

        working_chunks = self._chunks
        working_indices = list(range(len(self._chunks)))
        if category_filter:
            pairs = [(i, c) for i, c in enumerate(self._chunks) if c.category == category_filter]
            if not pairs:
                pairs = list(enumerate(self._chunks))
            working_indices = [p[0] for p in pairs]
            working_chunks = [p[1] for p in pairs]

        scores: np.ndarray
        if self._embed_ready and self._embeddings is not None:
            q_vec = self._embed_query(query)
            if q_vec is not None:
                subset_embs = self._embeddings[working_indices]
                scores = subset_embs @ q_vec
            else:
                texts = [c.text_for_search for c in working_chunks]
                scores = _tfidf_similarity(query, texts)
        else:
            texts = [c.text_for_search for c in working_chunks]
            scores = _tfidf_similarity(query, texts)

        ranked = np.argsort(scores)[::-1]
        results: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for idx in ranked:
            if len(results) >= top_k:
                break
            c = working_chunks[idx]
            if c.project_name in seen_names:
                continue
            seen_names.add(c.project_name)
            results.append({
                "case_id": c.case_id,
                "category": c.category,
                "project_name": c.project_name,
                "similarity": round(float(scores[idx]), 4),
                "pain_points": c.pain_points[:3],
                "solution": c.solution[:3],
                "innovation_points": c.innovation_points[:2],
                "evidence_quotes": c.evidence_quotes[:2],
                "risk_flags": c.risk_flags,
                "rubric_coverage": c.rubric_coverage,
                "summary": c.summary[:300],
            })
        return results

    def format_for_llm(self, results: list[dict[str, Any]], max_chars: int = 1500) -> str:
        """Format RAG results into a compact context block for LLM prompts."""
        if not results:
            return ""
        parts: list[str] = []
        for i, r in enumerate(results[:3], 1):
            part = f"### 参考案例{i}: {r['project_name']}（{r['category']}，相似度{r['similarity']:.0%}）\n"
            if r.get("pain_points"):
                part += f"- 痛点: {'; '.join(r['pain_points'][:2])}\n"
            if r.get("solution"):
                part += f"- 方案: {'; '.join(r['solution'][:2])}\n"
            if r.get("evidence_quotes"):
                part += f"- 证据引用: \"{r['evidence_quotes'][0][:100]}\"\n"
            covered = [rc["rubric_item"] for rc in r.get("rubric_coverage", []) if rc.get("covered")]
            uncovered = [rc["rubric_item"] for rc in r.get("rubric_coverage", []) if not rc.get("covered")]
            if covered:
                part += f"- 评分项已覆盖: {', '.join(covered)}\n"
            if uncovered:
                part += f"- 评分项未覆盖: {', '.join(uncovered)}\n"
            parts.append(part)
        text = "\n".join(parts)
        return text[:max_chars]

    @property
    def case_count(self) -> int:
        return len(self._chunks)

    @property
    def embed_ready(self) -> bool:
        return self._embed_ready
