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
    tags: list[str] = field(default_factory=list)
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


def _infer_subgraph_tags(case: dict, search_text: str) -> list[str]:
    """根据 case 文本/字段推断它属于哪些"能力子图"，给它打 subgraph:xxx tag。

    判定规则（粗规则即可，目的是让 RAG 在选 subgraph_filter 时能命中）：
      - innovation_evaluation：含创新/壁垒/差异化关键词 ≥2 ，或 innovation_points 非空
      - business_model_construction：含商业模式/收入/成本/客单价等 ≥2 ，或 business_model 非空
      - simulated_roadshow：含路演/答辩/评委/Q&A 等 ≥1
    """
    try:
        from app.services.ability_subgraphs import ABILITY_SUBGRAPHS
    except Exception:
        return []

    text_low = (search_text or "").lower()
    profile = case.get("project_profile") or {}
    out: list[str] = []

    for sub_id, sub in ABILITY_SUBGRAPHS.items():
        kws = [kw.lower() for kw in sub.trigger_keywords]
        hits = sum(1 for kw in kws if kw and kw in text_low)
        # 字段加权
        if sub_id == "innovation_evaluation" and (profile.get("innovation_points") or []):
            hits += 1
        if sub_id == "business_model_construction" and (profile.get("business_model") or []):
            hits += 1
        # 阈值：路演子图允许 1 命中即打标签（关键词更稀疏），其它要 2
        threshold = 1 if sub_id == "simulated_roadshow" else 2
        if hits >= threshold:
            out.append(f"subgraph:{sub_id}")
    return out


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
        tags = data.get("tags", []) or []
        if not isinstance(tags, list):
            tags = [str(tags)]

        for cls in data.get("分类", []):
            if not isinstance(cls, dict) or cls.get("类型") != "赛事":
                continue
            cname = cls.get("名称", "")
            if "互联网" in cname:
                tags.append("competition:internet_plus")
            elif "挑战杯" in cname:
                tags.append("competition:challenge_cup")
            elif "大创" in cname or "创青春" in cname:
                tags.append("competition:dachuang")

        search_text = _build_search_text(data)
        # 自动给 case 打 ability subgraph 标签（subgraph:innovation_evaluation 等）
        # 这样 retrieve(subgraph_filter=...) 才能真正在 RAG 里加权
        auto_tags = _infer_subgraph_tags(data, search_text)
        merged_tags = [_fix_garbled(str(t)) for t in tags if str(t).strip()] + auto_tags

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
            tags=merged_tags,
            text_for_search=search_text,
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

    # ------------------------------------------------------------------
    # MMR: balance relevance with diversity via embedding similarity
    # ------------------------------------------------------------------
    def _mmr_select(
        self,
        working_indices: list[int],
        working_chunks: list[CaseChunk],
        scores_normed: np.ndarray,
        top_k: int,
        exclude_ids: set[str] | None,
        lambda_param: float = 0.55,
    ) -> list[int]:
        """Return local indices selected by Maximal Marginal Relevance."""
        if self._embeddings is None:
            return []
        subset_embs = self._embeddings[working_indices]
        n = len(working_indices)
        candidates = set(range(n))
        if exclude_ids:
            candidates = {i for i in candidates
                          if working_chunks[i].case_id not in exclude_ids}
        if not candidates:
            return []

        selected: list[int] = []
        seen_names: set[str] = set()
        max_per_cat = max(1, (top_k + 1) // 2)
        cat_count: dict[str, int] = {}

        while len(selected) < top_k and candidates:
            best_local: int | None = None
            best_mmr = -1e9
            for idx in candidates:
                relevance = float(scores_normed[idx])
                if selected:
                    sim_to_sel = float(max(
                        np.dot(subset_embs[idx], subset_embs[s])
                        for s in selected
                    ))
                else:
                    sim_to_sel = 0.0
                mmr = lambda_param * relevance - (1 - lambda_param) * sim_to_sel
                if mmr > best_mmr:
                    best_mmr = mmr
                    best_local = idx
            if best_local is None:
                break
            candidates.discard(best_local)
            chunk = working_chunks[best_local]
            if chunk.project_name in seen_names:
                continue
            cat = chunk.category
            if cat_count.get(cat, 0) >= max_per_cat:
                continue
            seen_names.add(chunk.project_name)
            cat_count[cat] = cat_count.get(cat, 0) + 1
            selected.append(best_local)
        return selected

    # ------------------------------------------------------------------
    # Category-aware greedy fallback (no embeddings)
    # ------------------------------------------------------------------
    @staticmethod
    def _category_aware_select(
        working_chunks: list[CaseChunk],
        ranked_indices: np.ndarray,
        top_k: int,
        exclude_ids: set[str] | None,
    ) -> list[int]:
        selected: list[int] = []
        seen_names: set[str] = set()
        max_per_cat = max(1, (top_k + 1) // 2)
        cat_count: dict[str, int] = {}
        for local_idx_np in ranked_indices:
            if len(selected) >= top_k:
                break
            local_idx = int(local_idx_np)
            c = working_chunks[local_idx]
            if exclude_ids and c.case_id in exclude_ids:
                continue
            if c.project_name in seen_names:
                continue
            cat = c.category
            if cat_count.get(cat, 0) >= max_per_cat:
                continue
            seen_names.add(c.project_name)
            cat_count[cat] = cat_count.get(cat, 0) + 1
            selected.append(local_idx)
        return selected

    # ------------------------------------------------------------------
    # Main retrieval
    # ------------------------------------------------------------------
    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        category_filter: str | None = None,
        tags: list[str] | None = None,
        mode: str = "auto",
        exclude_ids: set[str] | None = None,
        competition_type: str | None = None,
        subgraph_filter: list[str] | None = None,
        ontology_boost: bool = True,
    ) -> list[dict[str, Any]]:
        """Retrieve most relevant cases with diversity-aware reranking.

        Improvements over v1:
        - ``exclude_ids``: skip cases already cited in earlier turns
        - MMR reranking when embeddings available (balances relevance + diversity)
        - Category cap: single category cannot dominate results
        - Soft fallback: if exclusion leaves too few results, retry without it
        """
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

        tag_filter = set(tags or [])
        if tag_filter:
            tagged_pairs: list[tuple[int, CaseChunk]] = []
            for idx, chunk in zip(working_indices, working_chunks):
                chunk_tags = set(chunk.tags or [])
                if tag_filter.issubset(chunk_tags):
                    tagged_pairs.append((idx, chunk))
            if tagged_pairs:
                working_indices = [p[0] for p in tagged_pairs]
                working_chunks = [p[1] for p in tagged_pairs]

        if not working_chunks:
            return []

        texts = [c.text_for_search for c in working_chunks]
        keyword_scores: np.ndarray = _tfidf_similarity(query, texts)

        vector_scores: np.ndarray | None = None
        if self._embed_ready and self._embeddings is not None and working_indices:
            q_vec = self._embed_query(query)
            if q_vec is not None:
                subset_embs = self._embeddings[working_indices]
                vector_scores = subset_embs @ q_vec

        effective_mode = (mode or settings.rag_retrieval_mode).lower()
        if effective_mode not in {"auto", "keyword", "vector", "hybrid"}:
            effective_mode = "auto"

        def _norm(arr: np.ndarray | None) -> np.ndarray | None:
            if arr is None or arr.size == 0:
                return None
            arr = arr.astype(float)
            mx, mn = float(arr.max()), float(arr.min())
            return np.ones_like(arr) * 0.5 if mx - mn < 1e-8 else (arr - mn) / (mx - mn)

        scores: np.ndarray
        if effective_mode == "keyword":
            scores = keyword_scores
        elif effective_mode == "vector":
            scores = vector_scores if vector_scores is not None else keyword_scores
        elif effective_mode == "hybrid":
            if vector_scores is not None:
                k_n = _norm(keyword_scores) or keyword_scores
                v_n = _norm(vector_scores) or vector_scores
                alpha = max(0.0, min(1.0, float(getattr(settings, "rag_hybrid_alpha", 0.6) or 0.6)))
                scores = (1.0 - alpha) * k_n + alpha * v_n
            else:
                scores = keyword_scores
        else:
            if vector_scores is not None:
                scores = vector_scores
                effective_mode = "vector"
            else:
                scores = keyword_scores
                effective_mode = "keyword"

        scores_normed = _norm(scores)
        if scores_normed is None:
            scores_normed = scores

        if competition_type:
            comp_tag = f"competition:{competition_type}"
            for i, chunk in enumerate(working_chunks):
                if comp_tag in (chunk.tags or []):
                    scores_normed[i] = min(1.0, float(scores_normed[i]) + 0.08)

        # ── 子图加权（P2 配套） ──
        # subgraph_filter 来自 select_ability_subgraphs 的结果（如 ["innovation_eval"]），
        # 命中 case.tags 里 "subgraph:xxx" 的 case 加分。
        if subgraph_filter:
            sub_tags = {f"subgraph:{s}" for s in subgraph_filter if s}
            for i, chunk in enumerate(working_chunks):
                ct = set(chunk.tags or [])
                if ct & sub_tags:
                    scores_normed[i] = min(1.0, float(scores_normed[i]) + 0.12)

        # ── 本体驱动加权（Step 6: RAG 接入 ontology resolver） ──
        # 1) normalize 查询 → 一组 canonical concept_id
        # 2) 把这些概念 + 其祖先（父概念命中=子概念也算相关）作为本体上下文
        # 3) 检查每个 case.text_for_search 含有这些概念的 label / aliases 多少次，按命中数加分
        # 4) 在结果里返回 concept_hits（前端可显示"为何召回该 case"）
        case_concept_hits: list[list[str]] = [[] for _ in working_chunks]
        if ontology_boost:
            try:
                from app.services.ontology_resolver import get_resolver
                from app.services.kg_ontology import ONTOLOGY_NODES
                resolver = get_resolver()
                q_ids = resolver.normalize(query)
                if q_ids:
                    # 同时考虑祖先：用户问 CAC，提到"商业模式"的 case 也算相关
                    ctx_ids: set[str] = set()
                    for qid in q_ids:
                        ctx_ids.add(qid)
                        for anc in resolver.ancestors(qid):
                            ctx_ids.add(anc)

                    # 收集每个概念的 label/aliases（小写，用作 substring 匹配）
                    label_to_id: list[tuple[str, str]] = []
                    for cid in ctx_ids:
                        node = ONTOLOGY_NODES.get(cid)
                        if not node:
                            continue
                        label_to_id.append((node.label.lower(), cid))
                        for al in node.aliases:
                            if al:
                                label_to_id.append((al.lower(), cid))

                    if label_to_id:
                        for i, chunk in enumerate(working_chunks):
                            text_l = (chunk.text_for_search or "").lower()
                            if not text_l:
                                continue
                            hit_set: set[str] = set()
                            for label, cid in label_to_id:
                                if not label:
                                    continue
                                if label in text_l:
                                    hit_set.add(cid)
                            if hit_set:
                                # 每命中一个概念 +0.04，最多 +0.20
                                bonus = min(0.20, 0.04 * len(hit_set))
                                scores_normed[i] = min(1.0, float(scores_normed[i]) + bonus)
                                case_concept_hits[i] = sorted(hit_set)
            except Exception:
                # 本体加权失败不影响主检索流程
                pass

        use_mmr = (self._embed_ready and self._embeddings is not None
                   and vector_scores is not None and len(working_chunks) > top_k)

        # 同步把竞赛/子图/本体加权回写到 raw scores，否则非-MMR 路径排序会忽略这些 boost
        scores = scores_normed.copy()

        def _select(excl: set[str] | None) -> list[int]:
            if use_mmr:
                return self._mmr_select(
                    working_indices, working_chunks, scores_normed,
                    top_k, exclude_ids=excl, lambda_param=0.55,
                )
            ranked = np.argsort(scores)[::-1]
            return self._category_aware_select(working_chunks, ranked, top_k, exclude_ids=excl)

        chosen = _select(exclude_ids)
        if len(chosen) < min(top_k, len(working_chunks)) and exclude_ids:
            chosen = _select(None)

        results: list[dict[str, Any]] = []
        for local_idx in chosen:
            c = working_chunks[local_idx]
            kw_score = float(keyword_scores[local_idx]) if keyword_scores.size else 0.0
            vec_score = float(vector_scores[local_idx]) if vector_scores is not None else 0.0
            combined = float(scores[local_idx])
            concept_hits = case_concept_hits[local_idx] if local_idx < len(case_concept_hits) else []
            sub_hits = sorted(set(c.tags or []) & {f"subgraph:{s}" for s in (subgraph_filter or [])})
            results.append({
                "case_id": c.case_id,
                "category": c.category,
                "project_name": c.project_name,
                "similarity": round(combined, 4),
                "score_keyword": round(kw_score, 4),
                "score_vector": round(vec_score, 4),
                "retrieval_mode": effective_mode,
                "tags": c.tags,
                "pain_points": c.pain_points[:3],
                "solution": c.solution[:3],
                "innovation_points": c.innovation_points[:3],
                "business_model": c.business_model[:3],
                "evidence_quotes": c.evidence_quotes[:2],
                "risk_flags": c.risk_flags,
                "rubric_coverage": c.rubric_coverage,
                "summary": c.summary[:300],
                # —— 召回原因解释（前端可展示"为何召回该 case"） ——
                "concept_hits": concept_hits,
                "subgraph_hits": [t.replace("subgraph:", "") for t in sub_hits],
            })
        return results

    def format_for_llm(self, results: list[dict[str, Any]], max_chars: int = 2500) -> str:
        """Format RAG results for LLM prompts. When Neo4j enrichment is present,
        uses graph fields for richer context including rule overlap and rubric comparison."""
        if not results:
            return ""
        show_n = min(len(results), 4)
        parts: list[str] = []
        for i, r in enumerate(results[:show_n], 1):
            enriched = r.get("neo4j_enriched", False)
            part = f"### 参考案例{i}: {r['project_name']}（{r['category']}，相似度{r['similarity']:.0%}）\n"

            pains = r.get("graph_pains") if enriched else r.get("pain_points")
            sols = r.get("graph_solutions") if enriched else r.get("solution")
            inns = r.get("graph_innovations") if enriched else r.get("innovation_points")
            biz = r.get("graph_biz_models") if enriched else r.get("business_model")

            if pains:
                part += f"- 痛点: {'; '.join(pains[:4])}\n"
            if sols:
                part += f"- 方案: {'; '.join(sols[:4])}\n"
            if inns:
                part += f"- 创新点: {'; '.join(inns[:3])}\n"
            if biz:
                part += f"- 商业模式: {'; '.join(biz[:3])}\n"

            if enriched:
                overlap = r.get("rule_overlap", {})
                shared = overlap.get("shared", [])
                only_case = overlap.get("only_in_case", [])
                only_student = overlap.get("only_in_student", [])
                if shared:
                    part += f"- 你和此案例共同触发的风险: {', '.join(shared[:4])}\n"
                if only_case:
                    part += f"- 此案例额外触发的风险(你未触发): {', '.join(only_case[:4])}\n"
                if only_student:
                    part += f"- 你独有的风险(此案例未触发): {', '.join(only_student[:4])}\n"

                cov = r.get("graph_rubric_covered", [])
                uncov = r.get("graph_rubric_uncovered", [])
                if cov:
                    part += f"- 案例已覆盖评分维度: {', '.join(cov)}\n"
                if uncov:
                    part += f"- 案例未覆盖评分维度: {', '.join(uncov)}\n"

                ev_count = r.get("graph_evidence_count", 0)
                if ev_count:
                    part += f"- 案例证据链: {ev_count}条\n"

                markets = r.get("graph_markets", [])
                if markets:
                    part += f"- 市场分析: {'; '.join(markets[:3])}\n"
            else:
                if r.get("evidence_quotes"):
                    part += f"- 证据引用: \"{r['evidence_quotes'][0][:120]}\"\n"
                covered = [rc["rubric_item"] for rc in r.get("rubric_coverage", []) if rc.get("covered")]
                uncovered = [rc["rubric_item"] for rc in r.get("rubric_coverage", []) if not rc.get("covered")]
                if covered:
                    part += f"- 已覆盖评分项: {', '.join(covered)}\n"
                if uncovered:
                    part += f"- 未覆盖评分项: {', '.join(uncovered)}\n"

            parts.append(part)
        text = "\n".join(parts)
        return text[:max_chars]

    @staticmethod
    def format_enrichment_insight(results: list[dict[str, Any]]) -> str:
        """Extract cross-case comparison insights from enriched RAG results.

        Produces a concise text block highlighting patterns across all retrieved
        cases versus the student's project, suitable for injection into agent prompts.
        """
        enriched = [r for r in results if r.get("neo4j_enriched")]
        if not enriched:
            return ""
        lines: list[str] = []

        all_shared: list[str] = []
        all_only_student: list[str] = []
        case_rubric_covered: dict[str, int] = {}
        case_rubric_uncovered: dict[str, int] = {}
        for r in enriched:
            overlap = r.get("rule_overlap", {})
            all_shared.extend(overlap.get("shared", []))
            all_only_student.extend(overlap.get("only_in_student", []))
            for dim in r.get("graph_rubric_covered", []):
                case_rubric_covered[dim] = case_rubric_covered.get(dim, 0) + 1
            for dim in r.get("graph_rubric_uncovered", []):
                case_rubric_uncovered[dim] = case_rubric_uncovered.get(dim, 0) + 1

        n = len(enriched)
        if all_only_student:
            from collections import Counter
            top_student_only = Counter(all_only_student).most_common(3)
            student_risk_str = ", ".join(f"{rid}(你独有)" for rid, _ in top_student_only)
            lines.append(f"风险对比: {student_risk_str}——参考案例中都没有触发这些规则，说明这可能是你项目特有的薄弱环节。")

        dims_all_covered = [d for d, c in case_rubric_covered.items() if c == n]
        dims_student_gap = [d for d in dims_all_covered if d in case_rubric_uncovered or d not in case_rubric_covered]
        if dims_all_covered:
            lines.append(f"参考案例普遍覆盖的维度: {', '.join(dims_all_covered[:5])}。")

        categories = [r.get("category", "") for r in enriched if r.get("category")]
        if len(set(categories)) > 1:
            lines.append(f"跨领域启发: 本轮案例来自{', '.join(set(categories))}等{len(set(categories))}个不同领域。")

        return "\n".join(lines) if lines else ""

    @property
    def case_count(self) -> int:
        return len(self._chunks)

    @property
    def embed_ready(self) -> bool:
        return self._embed_ready
