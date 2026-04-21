"""KB 质量评估扩展模块（六维分层评估）。

本模块提供独立的指标计算函数，由 graph_service.get_kb_stats 在 Neo4j session 内调用：

    B 维 抽取完整性：compute_canonical_coverage + compute_top_entities_per_label
    E 维 任务代表性：compute_lifecycle_representativeness（行业→创新/创业阶段静态映射）
    D 维 结构合理性：compute_ontology_constraint_compliance + compute_degree_histogram
    A 维 抽取正确性补强：augment_wilson_intervals（基于现有 semantic_validity.labels）

所有函数只从 Neo4j 取值 + JSON 清单，无硬编码兜底。查询失败时返回空态而非假数据。
"""

from __future__ import annotations

import json
import logging
import math
import random
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

_DATA_ROOT = Path(__file__).resolve().parents[4] / "data"
_CANONICAL_CONCEPTS_PATH = _DATA_ROOT / "kb_canonical_concepts.json"
_LIFECYCLE_MAP_PATH = _DATA_ROOT / "kb_category_lifecycle_map.json"


# ────────────────────────────────────────────────────────────────
# JSON 清单加载（失败时返回 None，调用方自己决定兜底/报错）
# ────────────────────────────────────────────────────────────────
def load_canonical_concepts() -> dict[str, Any] | None:
    try:
        with open(_CANONICAL_CONCEPTS_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        logger.warning("canonical concepts load failed: %s", exc)
        return None


def load_lifecycle_map() -> dict[str, Any] | None:
    try:
        with open(_LIFECYCLE_MAP_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        logger.warning("lifecycle map load failed: %s", exc)
        return None


# ────────────────────────────────────────────────────────────────
# 基础统计工具
# ────────────────────────────────────────────────────────────────
def wilson_ci(hits: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 分数区间（小样本比例的 95% 置信区间）。"""
    if total <= 0:
        return (0.0, 0.0)
    p = hits / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    half = (z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def spearman_rho(xs: list[float], ys: list[float]) -> float | None:
    """Spearman 秩相关系数（无 scipy 依赖）。"""
    if len(xs) != len(ys) or len(xs) < 2:
        return None

    def _rank(values: list[float]) -> list[float]:
        paired = sorted(enumerate(values), key=lambda t: t[1])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(paired):
            j = i
            while j + 1 < len(paired) and paired[j + 1][1] == paired[i][1]:
                j += 1
            avg = (i + j + 2) / 2  # 秩从 1 开始
            for k in range(i, j + 1):
                ranks[paired[k][0]] = avg
            i = j + 1
        return ranks

    rx = _rank(xs)
    ry = _rank(ys)
    n = len(xs)
    mean_x = sum(rx) / n
    mean_y = sum(ry) / n
    num = sum((rx[i] - mean_x) * (ry[i] - mean_y) for i in range(n))
    den_x = math.sqrt(sum((rx[i] - mean_x) ** 2 for i in range(n)))
    den_y = math.sqrt(sum((ry[i] - mean_y) ** 2 for i in range(n)))
    if den_x == 0 or den_y == 0:
        return 0.0
    return round(num / (den_x * den_y), 4)


# ────────────────────────────────────────────────────────────────
# B 维 · 核心概念覆盖率
# ────────────────────────────────────────────────────────────────
def compute_canonical_coverage(session: Any, concepts_doc: dict[str, Any] | None = None) -> dict[str, Any]:
    """逐条概念扫图计数 + 三种覆盖率 + Top-K 实体。

    输出结构：
    {
      "version": "v1",
      "overall": {total_concepts, coverage_binary, coverage_threshold, coverage_weighted},
      "groups": [{key,label,total,hit,threshold_hit,weighted_score, concepts:[...]}],
      "concepts": [{id,name,group,importance,min_freq,hit_count,status,top_entities,...}]
    }
    """
    doc = concepts_doc or load_canonical_concepts()
    if not doc:
        return {"error": "canonical concepts file missing or invalid"}

    concepts = doc.get("concepts") or []
    groups = doc.get("groups") or []
    group_lookup = {g.get("key"): g for g in groups}

    per_concept: list[dict[str, Any]] = []
    label_cache: dict[str, list[dict[str, Any]]] = {}

    def _fetch_label_entities(label: str) -> list[dict[str, Any]]:
        if label in label_cache:
            return label_cache[label]
        try:
            rows = list(session.run(
                f"MATCH (n:{label}) "
                f"OPTIONAL MATCH (p:Project)-[]->(n) "
                f"WITH n, count(DISTINCT p) AS proj_mentions "
                f"WHERE n.name IS NOT NULL AND trim(n.name) <> '' "
                f"RETURN n.name AS name, proj_mentions ORDER BY proj_mentions DESC"
            ))
            entities = [{"name": str(r.get("name") or ""), "freq": int(r.get("proj_mentions") or 0)} for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.warning("fetch label entities failed (%s): %s", label, exc)
            entities = []
        label_cache[label] = entities
        return entities

    for concept in concepts:
        keywords = [str(k).lower() for k in (concept.get("keywords") or []) if k]
        labels = concept.get("search_labels") or []
        min_freq = int(concept.get("min_freq") or 1)
        importance = int(concept.get("importance") or 1)

        hit_entities: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for lbl in labels:
            for ent in _fetch_label_entities(lbl):
                name_l = ent["name"].lower()
                if not keywords:
                    continue
                if any(kw in name_l for kw in keywords):
                    key = f"{lbl}::{ent['name']}"
                    if key in seen_names:
                        continue
                    seen_names.add(key)
                    hit_entities.append({"label": lbl, "name": ent["name"], "freq": ent["freq"]})

        hit_count = sum(e["freq"] for e in hit_entities)
        entity_count = len(hit_entities)

        if hit_count >= min_freq:
            status = "met"
        elif hit_count > 0:
            status = "partial"
        else:
            status = "missed"

        top_entities = sorted(hit_entities, key=lambda e: e["freq"], reverse=True)[:5]

        per_concept.append({
            "id": concept.get("id"),
            "name": concept.get("name"),
            "group": concept.get("group"),
            "importance": importance,
            "min_freq": min_freq,
            "keywords": concept.get("keywords") or [],
            "search_labels": labels,
            "hit_count": hit_count,
            "entity_count": entity_count,
            "status": status,
            "top_entities": top_entities,
        })

    # 组级聚合
    per_group: list[dict[str, Any]] = []
    for g in groups:
        gkey = g.get("key")
        items = [c for c in per_concept if c.get("group") == gkey]
        total = len(items)
        hit = sum(1 for c in items if c["status"] != "missed")
        threshold_hit = sum(1 for c in items if c["status"] == "met")
        imp_num = sum(c["importance"] for c in items)
        imp_hit = sum(c["importance"] * (min(1.0, c["hit_count"] / max(1, c["min_freq"]))) for c in items)
        weighted = round(imp_hit / max(1, imp_num), 4)
        per_group.append({
            "key": gkey,
            "label": g.get("label"),
            "theory": g.get("theory"),
            "total": total,
            "hit": hit,
            "threshold_hit": threshold_hit,
            "hit_rate": round(hit / max(1, total), 4),
            "threshold_rate": round(threshold_hit / max(1, total), 4),
            "weighted_score": weighted,
        })

    total_concepts = len(per_concept)
    total_importance = sum(c["importance"] for c in per_concept) or 1
    coverage_binary = round(sum(1 for c in per_concept if c["status"] != "missed") / max(1, total_concepts), 4)
    coverage_threshold = round(sum(1 for c in per_concept if c["status"] == "met") / max(1, total_concepts), 4)
    coverage_weighted = round(
        sum(c["importance"] * min(1.0, c["hit_count"] / max(1, c["min_freq"])) for c in per_concept)
        / total_importance,
        4,
    )

    return {
        "version": doc.get("version", "v1"),
        "methodology_note": doc.get("methodology_note"),
        "total_concepts": total_concepts,
        "overall": {
            "coverage_binary": coverage_binary,
            "coverage_threshold": coverage_threshold,
            "coverage_weighted": coverage_weighted,
            "formula": "binary = 命中≥1次 / 总数；threshold = 命中≥min_freq 的概念数 / 总数；weighted = Σ(importance · min(1, hit/min_freq)) / Σimportance",
        },
        "groups": per_group,
        "concepts": per_concept,
    }


def compute_top_entities_per_label(session: Any, labels: list[str], top_k: int = 10) -> dict[str, list[dict[str, Any]]]:
    """为每个核心维度 label 取 Top-K 高频实体（按被多少项目引用排序）。"""
    out: dict[str, list[dict[str, Any]]] = {}
    for lbl in labels:
        try:
            rows = list(session.run(
                f"MATCH (p:Project)-[]->(n:{lbl}) "
                f"WITH n, count(DISTINCT p) AS proj_count "
                f"WHERE n.name IS NOT NULL AND trim(n.name) <> '' "
                f"RETURN n.name AS name, proj_count ORDER BY proj_count DESC, n.name ASC LIMIT $k",
                k=top_k,
            ))
            out[lbl] = [{"name": str(r["name"]), "freq": int(r["proj_count"])} for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.warning("top_entities for label %s failed: %s", lbl, exc)
            out[lbl] = []
    return out


# ────────────────────────────────────────────────────────────────
# E 维 · 创新-创业任务代表性
# ────────────────────────────────────────────────────────────────
_LIFECYCLE_DIM_RELS = [
    ("pain_points",     "HAS_PAIN",            "PainPoint"),
    ("solutions",       "HAS_SOLUTION",        "Solution"),
    ("business_models", "HAS_BUSINESS_MODEL",  "BusinessModelAspect"),
    ("markets",         "HAS_MARKET_ANALYSIS", "Market"),
    ("innovations",     "HAS_INNOVATION",      "InnovationPoint"),
    ("evidence",        "HAS_EVIDENCE",        "Evidence"),
    ("execution_steps", "HAS_EXECUTION_STEP",  "ExecutionStep"),
    ("stakeholders",    "HAS_TARGET_USER",     "Stakeholder"),
    ("risk_controls",   "HAS_RISK_CONTROL",    "RiskControlPoint"),
]


def _classify_project_by_kb_label(level_rank: int | None) -> str:
    """按知识库原生标注判定阶段（kb-label-driven / 非算法推断）。

    数据源：Neo4j `(p:Project)-[rel:ENTREPRENEURSHIP]->(:Entrepreneurship)` 的 rel.level_rank。
    该标注来自 ingest 阶段对 PDF 原文的关键词核验（见 ingest/enrich_case_entrepreneurship.py）：
      · rel.level_rank = 2  ← 命中 "有限责任公司 / 有限公司 / 股份有限公司 / 创业公司 / 初创公司"
                              说明项目已以实体公司运营 / 注册 ⇒ 属于「创业」
      · rel.level_rank = 1  ← 命中 "创业 / 大学生创业 / 创业项目 / 创业计划书 / 创业实践 / 创业团队 / 创业大赛"
                              说明项目包含创业活动讨论但未建立实体公司 ⇒ 属于「双栖」
      · 无 ENTREPRENEURSHIP 关系 ← 既没有公司型关键词、也没有创业型关键词
                              说明项目聚焦原创研究 / 产品原型，未触及落地 ⇒ 属于「创新训练」
    """
    if level_rank is None or level_rank <= 0:
        return "innovation"
    if level_rank >= 2:
        return "entrepreneurship"
    return "both"


# 知识库标注驱动分类的显式规则描述（前端展示用）
_CONTENT_CLASSIFY_RULES: list[dict[str, Any]] = [
    {
        "id": "r1",
        "condition": "Neo4j 中 (p:Project)-[:ENTREPRENEURSHIP]->(:Entrepreneurship) 关系的 level_rank = 2",
        "stage": "entrepreneurship",
        "rationale": "原文命中「有限责任公司 / 有限公司 / 股份有限公司 / 创业公司 / 初创公司」中的任一关键词 —— 项目已建立/筹建实体公司，判定为创业",
    },
    {
        "id": "r2",
        "condition": "Neo4j 中该关系的 level_rank = 1",
        "stage": "both",
        "rationale": "原文命中「创业 / 创业项目 / 创业计划书 / 创业实践 / 创业团队 / 创业大赛」中的任一关键词，但未命中公司型关键词 —— 项目讨论创业但尚未落地公司，判定为双栖",
    },
    {
        "id": "r3",
        "condition": "无 ENTREPRENEURSHIP 关系",
        "stage": "innovation",
        "rationale": "原文既无公司型关键词也无创业型关键词 —— 项目聚焦原创研究 / 产品原型 / 技术突破，未触及商业化，判定为创新训练",
    },
]


def compute_lifecycle_representativeness(session: Any, lifecycle_doc: dict[str, Any] | None = None) -> dict[str, Any]:
    """按知识库原生标注（Entrepreneurship 关系的 level_rank）把项目归三阶段桶。

    数据源（非算法推断）：Neo4j `(p:Project)-[rel:ENTREPRENEURSHIP]->(:Entrepreneurship)` 的 rel.level_rank。
    标注逻辑见 `apps/backend/ingest/enrich_case_entrepreneurship.py`（ingest 阶段跑，对 PDF 原文做关键词核验）：

      · rel.level_rank = 2  ⇒ entrepreneurship （创业）      — 命中 "有限责任公司 / 有限公司 / 股份有限公司 / 创业公司 / 初创公司"
      · rel.level_rank = 1  ⇒ both            （双栖）      — 命中 "创业 / 创业项目 / 创业计划书 / 创业实践 / 创业团队 / 创业大赛"
      · 无 ENTREPRENEURSHIP ⇒ innovation      （创新训练）  — 无上述任何关键词

    不再做算法推断（"多少 PainPoint 就算创新"这种 9 维加权）——分类来源是 KB 原生打的结构化标，
    9 维实体数只用于 stage_dim_matrix 观察（不同阶段的创新创业表述密度）。
    """
    doc = lifecycle_doc or load_lifecycle_map()
    # doc 可能为空；但本函数不再依赖 category→stage 静态映射，doc 仅用于读取 theoretical_expectations。
    stage_defs = (doc or {}).get("stage_definitions") or {
        "innovation": {"label": "创新训练", "definition": "以原创研究/产品原型为目标，未涉及公司化落地"},
        "entrepreneurship": {"label": "创业", "definition": "项目已筹建/运营实体公司（有限公司/股份公司/创业公司）"},
        "both": {"label": "双栖", "definition": "项目讨论创业活动但未建立实体公司"},
    }
    expectations = (doc or {}).get("theoretical_expectations") or {}

    try:
        rows = list(session.run(
            """
            MATCH (p:Project)
            OPTIONAL MATCH (p)-[:BELONGS_TO]->(c:Category)
            OPTIONAL MATCH (p)-[rel:ENTREPRENEURSHIP]->(:Entrepreneurship)
            OPTIONAL MATCH (p)-[:HAS_PAIN]->(pain:PainPoint)
            OPTIONAL MATCH (p)-[:HAS_SOLUTION]->(sol:Solution)
            OPTIONAL MATCH (p)-[:HAS_BUSINESS_MODEL]->(bm:BusinessModelAspect)
            OPTIONAL MATCH (p)-[:HAS_MARKET_ANALYSIS]->(mkt:Market)
            OPTIONAL MATCH (p)-[:HAS_INNOVATION]->(inn:InnovationPoint)
            OPTIONAL MATCH (p)-[:HAS_EVIDENCE]->(ev:Evidence)
            OPTIONAL MATCH (p)-[:HAS_EXECUTION_STEP]->(ex:ExecutionStep)
            OPTIONAL MATCH (p)-[:HAS_TARGET_USER]->(st:Stakeholder)
            OPTIONAL MATCH (p)-[:HAS_RISK_CONTROL]->(rc:RiskControlPoint)
            WITH p, c, rel,
                 count(DISTINCT pain) AS pain_count,
                 count(DISTINCT sol) AS sol_count,
                 count(DISTINCT bm) AS bm_count,
                 count(DISTINCT mkt) AS mkt_count,
                 count(DISTINCT inn) AS inn_count,
                 count(DISTINCT ev) AS ev_count,
                 count(DISTINCT ex) AS ex_count,
                 count(DISTINCT st) AS st_count,
                 count(DISTINCT rc) AS rc_count
            RETURN p.id AS project_id, p.name AS project_name,
                   coalesce(c.name, '(无分类)') AS category,
                   rel.level_rank AS level_rank,
                   rel.level AS level_name,
                   pain_count, sol_count, bm_count, mkt_count, inn_count,
                   ev_count, ex_count, st_count, rc_count
            """
        ))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"lifecycle query failed: {exc}"}

    dim_keys = [d[0] for d in _LIFECYCLE_DIM_RELS]
    row_field_map = {
        "pain_points": "pain_count", "solutions": "sol_count", "business_models": "bm_count",
        "markets": "mkt_count", "innovations": "inn_count", "evidence": "ev_count",
        "execution_steps": "ex_count", "stakeholders": "st_count", "risk_controls": "rc_count",
    }
    innov_dims = {"pain_points", "solutions", "innovations", "evidence"}
    entrep_dims = {"business_models", "markets", "execution_steps", "risk_controls"}

    # 初始化 3 桶（KB 原生标注三分类）
    stage_agg: dict[str, dict[str, Any]] = {
        "innovation": {"proj_count": 0, "dim_sum": {dk: 0 for dk in dim_keys}},
        "entrepreneurship": {"proj_count": 0, "dim_sum": {dk: 0 for dk in dim_keys}},
        "both": {"proj_count": 0, "dim_sum": {dk: 0 for dk in dim_keys}},
    }

    per_project: list[dict[str, Any]] = []
    level_rank_hist = {"rank_2": 0, "rank_1": 0, "no_rel": 0}

    for row in rows:
        cat_name = str(row.get("category") or "(无分类)").strip()
        level_rank_raw = row.get("level_rank")
        level_rank = int(level_rank_raw) if level_rank_raw is not None else None
        level_name = str(row.get("level_name") or "").strip()

        # 9 维计数（仅用于后续 stage_dim_matrix 观察）
        per_dim = {dk: int(row.get(row_field_map[dk]) or 0) for dk in dim_keys}
        innov_score = sum(per_dim[dk] for dk in innov_dims)
        entrep_score = sum(per_dim[dk] for dk in entrep_dims)

        # 直接按 KB 标签归桶
        stage = _classify_project_by_kb_label(level_rank)

        if level_rank == 2:
            level_rank_hist["rank_2"] += 1
        elif level_rank == 1:
            level_rank_hist["rank_1"] += 1
        else:
            level_rank_hist["no_rel"] += 1

        bucket = stage_agg[stage]
        bucket["proj_count"] += 1
        for dk in dim_keys:
            bucket["dim_sum"][dk] += per_dim[dk]

        per_project.append({
            "project_id": row.get("project_id"),
            "project_name": row.get("project_name"),
            "category": cat_name,
            "level_rank": level_rank,
            "level_name": level_name or ("high relevance" if level_rank == 2 else "relevance" if level_rank == 1 else "(no entrepreneurship keyword)"),
            "stage": stage,
            "innov_score": innov_score,
            "entrep_score": entrep_score,
            "per_dim": per_dim,
        })

    total_projects = sum(b["proj_count"] for b in stage_agg.values()) or 1

    # 三桶归一化熵（所有桶都参与，因为所有项目都有明确标签）
    stage_entropy = 0.0
    n_nonempty = sum(1 for s in stage_agg if stage_agg[s]["proj_count"] > 0)
    if n_nonempty > 1:
        for s in stage_agg:
            pc = stage_agg[s]["proj_count"]
            if pc > 0:
                p = pc / total_projects
                stage_entropy += -p * math.log2(p)
        stage_entropy = round(stage_entropy / math.log2(n_nonempty), 4)

    # 阶段×维度平均强度矩阵（每项目平均实体数）
    stage_dim_matrix: dict[str, dict[str, float]] = {}
    for stage_key, bucket in stage_agg.items():
        pc = bucket["proj_count"] or 1
        stage_dim_matrix[stage_key] = {
            dk: round(bucket["dim_sum"].get(dk, 0) / pc, 2) for dk in dim_keys
        }

    # Spearman 三阶段均算
    consistency: dict[str, Any] = {}
    for stage_key in ("innovation", "entrepreneurship", "both"):
        observed = [stage_dim_matrix.get(stage_key, {}).get(dk, 0) for dk in dim_keys]
        expected = [expectations.get(stage_key, {}).get(dk, 0) for dk in dim_keys]
        rho = spearman_rho(observed, expected)
        consistency[stage_key] = {
            "rho": rho,
            "observed": dict(zip(dim_keys, observed)),
            "expected": dict(zip(dim_keys, expected)),
        }

    avg_rho = round(
        sum(max(0.0, (consistency[s].get("rho") or 0.0)) for s in ("innovation", "entrepreneurship", "both")) / 3,
        4,
    )
    representativeness_score = round(stage_entropy * 0.4 + avg_rho * 0.6, 4)

    # 最弱桶（用于点出哪个阶段占比偏少）
    weakest_key = min(stage_agg, key=lambda k: stage_agg[k]["proj_count"])
    weakest_stage = weakest_key if stage_agg[weakest_key]["proj_count"] < total_projects * 0.25 else None

    # 审计抽样：每阶段 5 条（稳定 seed），共 15 条左右
    rng = random.Random(2026)
    audit_sample: list[dict[str, Any]] = []
    for stage_key in ("innovation", "entrepreneurship", "both"):
        pool = [rec for rec in per_project if rec["stage"] == stage_key]
        rng.shuffle(pool)
        audit_sample.extend(pool[:5])

    return {
        "version": (doc or {}).get("version", "v3-kb-label"),
        "classification_method": "kb-label-driven",
        "classification_method_note": "分类来自知识库 ingest 阶段对 PDF 原文的关键词核验标注（非算法推断）：ENTREPRENEURSHIP 关系的 level_rank",
        "classification_rules": _CONTENT_CLASSIFY_RULES,
        "classification_source": {
            "ingest_script": "apps/backend/ingest/enrich_case_entrepreneurship.py",
            "neo4j_relationship": "(Project)-[:ENTREPRENEURSHIP]->(Entrepreneurship)",
            "field": "rel.level_rank ∈ {2, 1, None}",
            "high_relevance_keywords": ["有限责任公司", "有限公司", "股份有限公司", "创业公司", "初创公司"],
            "relevance_keywords": ["创业", "大学生创业", "创业项目", "创业计划书", "创业实践", "创业团队", "创业大赛"],
        },
        "level_rank_histogram": level_rank_hist,
        "methodology_note": (doc or {}).get("methodology_note") or "按知识库 ingest 打的原生标签分桶；9 维实体只用于观察不同阶段的表述密度，不参与分类判定。",
        "stage_definitions": stage_defs,
        "stage_counts": {k: v["proj_count"] for k, v in stage_agg.items()},
        "stage_entropy": stage_entropy,
        "stage_dim_matrix": stage_dim_matrix,
        "theoretical_expectations": expectations,
        "theoretical_consistency": consistency,
        "avg_rho_focused": avg_rho,
        "representativeness_score": representativeness_score,
        "representativeness_formula": "0.4·stage_entropy(三桶归一化熵) + 0.6·avg_rho(创新/创业/双栖 三阶段平均秩相关)",
        "weakest_stage": weakest_stage,
        "total_projects": total_projects,
        "per_project_audit_sample": audit_sample,
    }


# ────────────────────────────────────────────────────────────────
# D 维 · 本体约束核查 + 度分布
# ────────────────────────────────────────────────────────────────
_ONTOLOGY_CONSTRAINTS: list[dict[str, Any]] = [
    {
        "id": "c01", "name": "项目必须归属某个行业分类",
        "rationale": "所有 Project 应挂 BELONGS_TO Category，否则无法分桶统计。",
        "violation_cypher":
            "MATCH (p:Project) WHERE NOT (p)-[:BELONGS_TO]->(:Category) RETURN count(p) AS c",
    },
    {
        "id": "c02", "name": "有方案的项目应至少有一个痛点",
        "rationale": "Design Thinking 要求先有痛点再有方案；反向孤立方案通常是抽取错误。",
        "violation_cypher":
            "MATCH (p:Project)-[:HAS_SOLUTION]->(:Solution) WHERE NOT (p)-[:HAS_PAIN]->(:PainPoint) RETURN count(DISTINCT p) AS c",
    },
    {
        "id": "c03", "name": "有商业模式的项目应至少有一个目标用户",
        "rationale": "BMC 的 Revenue Streams 必须指向 Customer Segments，孤立商业模式意味数据不完整。",
        "violation_cypher":
            "MATCH (p:Project)-[:HAS_BUSINESS_MODEL]->(:BusinessModelAspect) WHERE NOT (p)-[:HAS_TARGET_USER]->(:Stakeholder) RETURN count(DISTINCT p) AS c",
    },
    {
        "id": "c04", "name": "有创新点的项目应至少有一个方案或痛点",
        "rationale": "创新点必须附着于具体的问题或技术方案上，孤立创新点是抽取噪声。",
        "violation_cypher":
            "MATCH (p:Project)-[:HAS_INNOVATION]->(:InnovationPoint) WHERE NOT (p)-[:HAS_SOLUTION]->(:Solution) AND NOT (p)-[:HAS_PAIN]->(:PainPoint) RETURN count(DISTINCT p) AS c",
    },
    {
        "id": "c05", "name": "证据节点应带 quote 或 source_unit 之一",
        "rationale": "Evidence 如果两个溯源字段都为空，则无法用于可追溯性评估。",
        "violation_cypher":
            "MATCH (e:Evidence) WHERE (e.quote IS NULL OR trim(coalesce(e.quote,'')) = '') AND (e.source_unit IS NULL OR trim(coalesce(e.source_unit,'')) = '') RETURN count(e) AS c",
    },
    {
        "id": "c06", "name": "每个维度节点应被至少一个项目引用",
        "rationale": "孤立的维度节点（没有任何 Project 挂它）是数据漂移或脏数据。",
        "violation_cypher":
            "MATCH (n) WHERE (n:PainPoint OR n:Solution OR n:BusinessModelAspect OR n:Market OR n:InnovationPoint OR n:Stakeholder OR n:ExecutionStep OR n:RiskControlPoint) AND NOT ()-[]->(n) RETURN count(n) AS c",
    },
    {
        "id": "c07", "name": "项目名称应非空",
        "rationale": "所有 Project 必须有非空 name 才能被检索与展示。",
        "violation_cypher":
            "MATCH (p:Project) WHERE p.name IS NULL OR trim(coalesce(p.name,'')) = '' RETURN count(p) AS c",
    },
    {
        "id": "c08", "name": "维度实体名称应非空",
        "rationale": "空字符串的实体名会污染 Top-K 统计与模糊检索。",
        "violation_cypher":
            "MATCH (n) WHERE (n:PainPoint OR n:Solution OR n:BusinessModelAspect OR n:Market OR n:InnovationPoint OR n:Stakeholder OR n:ExecutionStep OR n:RiskControlPoint) AND (n.name IS NULL OR trim(coalesce(n.name,'')) = '') RETURN count(n) AS c",
    },
    {
        "id": "c09", "name": "项目若触发规则必须真实连接到 RiskRule",
        "rationale": "HITS_RULE 若指向不存在的 RiskRule id 会导致规则统计失真。",
        "violation_cypher":
            "MATCH (p:Project)-[h:HITS_RULE]->(r) WHERE NOT r:RiskRule RETURN count(h) AS c",
    },
    {
        "id": "c10", "name": "重复同名证据不应指向同一项目超过 5 次",
        "rationale": "同一 quote 在同一项目内出现过多次通常是 LLM 抽取重复或 dedup 漏掉。",
        "violation_cypher":
            "MATCH (p:Project)-[:HAS_EVIDENCE]->(e:Evidence) WITH p, e.quote AS q, count(*) AS c WHERE q IS NOT NULL AND trim(q) <> '' AND c > 5 RETURN count(*) AS c",
    },
]


def compute_ontology_constraint_compliance(session: Any) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    pass_count = 0
    for ck in _ONTOLOGY_CONSTRAINTS:
        try:
            row = session.run(ck["violation_cypher"]).single()
            violations = int((row or {}).get("c") or 0)
            passed = violations == 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("constraint %s failed: %s", ck["id"], exc)
            violations = -1
            passed = False
        if passed:
            pass_count += 1
        checks.append({
            "id": ck["id"],
            "name": ck["name"],
            "rationale": ck["rationale"],
            "violations": violations,
            "passed": passed,
        })
    total = len(_ONTOLOGY_CONSTRAINTS)
    return {
        "checks": checks,
        "total_count": total,
        "pass_count": pass_count,
        "pass_rate": round(pass_count / max(1, total), 4),
        "methodology_note": "10 条 Cypher 级别的本体约束，直接在图上跑违反数。0 违反=通过。",
    }


def compute_degree_histogram(session: Any, bins: list[int] | None = None) -> dict[str, Any]:
    """度分布 histogram + 幂律指数简易估计。"""
    bins = bins or [0, 1, 2, 3, 5, 8, 15, 30, 60, 120, 10**9]
    try:
        rows = list(session.run(
            "MATCH (n) OPTIONAL MATCH (n)-[r]-() "
            "WITH n, count(r) AS deg "
            "RETURN deg, count(*) AS cnt ORDER BY deg"
        ))
        raw = [(int(r["deg"]), int(r["cnt"])) for r in rows]
    except Exception as exc:  # noqa: BLE001
        return {"error": f"degree query failed: {exc}"}

    buckets = []
    for i in range(len(bins) - 1):
        lo, hi = bins[i], bins[i + 1]
        cnt = sum(c for d, c in raw if lo <= d < hi)
        buckets.append({
            "range": f"{lo}-{hi - 1 if hi < 10**8 else '∞'}",
            "lo": lo,
            "hi": hi,
            "count": cnt,
        })

    # 幂律指数粗估（最大似然，k_min=1）
    sample = [d for d, c in raw for _ in range(c) if d >= 1]
    alpha = None
    if len(sample) >= 20:
        s = sum(math.log(d) for d in sample)
        alpha = round(1 + len(sample) / s, 3) if s > 0 else None

    total = sum(c for _, c in raw)
    return {
        "histogram": buckets,
        "total_nodes_sampled": total,
        "power_law_alpha": alpha,
        "alpha_interpretation": (
            "2 < α < 3 表示典型无标度网络" if alpha and 2 < alpha < 3
            else ("α ≥ 3 幂律偏平，更接近均质网络" if alpha and alpha >= 3
                  else ("α ≤ 2 重尾异常明显" if alpha else "样本不足，未拟合"))
        ),
    }


# ────────────────────────────────────────────────────────────────
# A 维 · Wilson 置信区间补强
# ────────────────────────────────────────────────────────────────
def augment_wilson_intervals(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为 semantic_validity.labels 的每个 Label 附加 Wilson 95% CI（基于 boundary_hit_count/total_items）。"""
    augmented: list[dict[str, Any]] = []
    for item in labels or []:
        total = int(item.get("total_items") or 0)
        hits = int(item.get("boundary_hit_count") or 0)
        lo, hi = wilson_ci(hits, total)
        augmented.append({
            **item,
            "wilson_ci_lo": round(lo, 4),
            "wilson_ci_hi": round(hi, 4),
            "wilson_ci_label": f"[{round(lo*100, 1)}%, {round(hi*100, 1)}%]" if total > 0 else "—",
            "sample_size_warning": total < 30,
        })
    return augmented


# ────────────────────────────────────────────────────────────────
# C 维 · 可追溯抽样（随机 3 条）
# ────────────────────────────────────────────────────────────────
def sample_traceability_chains(session: Any, k: int = 3, seed: int | None = None) -> list[dict[str, Any]]:
    """随机抽 k 条『实体 → quote → project』链供前端现场展示。"""
    try:
        rows = list(session.run(
            """
            MATCH (p:Project)-[:HAS_EVIDENCE]->(e:Evidence)
            WHERE e.quote IS NOT NULL AND trim(coalesce(e.quote, '')) <> ''
            RETURN p.id AS project_id, p.name AS project_name,
                   e.quote AS quote, e.source_unit AS source_unit,
                   e.type AS evidence_type
            LIMIT 500
            """
        ))
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"sample trace failed: {exc}"}]
    if not rows:
        return []
    rnd = random.Random(seed)
    picks = rnd.sample(rows, min(k, len(rows)))
    out = []
    for r in picks:
        out.append({
            "project_id": r.get("project_id"),
            "project_name": r.get("project_name"),
            "quote": (r.get("quote") or "")[:280],
            "source_unit": r.get("source_unit"),
            "evidence_type": r.get("evidence_type"),
        })
    return out
