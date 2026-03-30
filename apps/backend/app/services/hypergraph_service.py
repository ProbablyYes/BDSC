"""HyperNetX-based hypergraph service for teaching & student analysis.

This service focuses on **logical consistency diagnosis** rather than
storage. It exposes three layers that correspond directly to the
requirements:

1. Hyperedge templates (>=20 types)
     - Declarative patterns over KG dimensions, e.g.
         "痛点-人群-解决方案-商业模式闭环"、"问题-方案-证据三角" 等。
2. Consistency rules (>=20 rules)
     - G1–G20 operate on dimension coverage + text signals to检测
         “无竞争对手”、“1% 市场份额”、“CAC 与渠道不匹配”等逻辑幻觉。
3. Student dynamic analysis
     - Builds a temporary HyperNetX hypergraph from extracted entities
         and applies the above templates/rules to produce可追溯的诊断结果。

It does **not** parse raw files itself; all文件解析与分段由
``HypergraphDocument`` 完成，本服务只消费结构化后的 KG 实体。"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import hypernetx as hnx

from app.config import settings
from app.services.graph_service import GraphService
from app.services.kg_ontology import ONTOLOGY_NODES

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────
#  Data classes
# ─────────────────────────────────────────────────────

@dataclass
class HyperedgeRecord:
    hyperedge_id: str
    type: str
    support: int
    teaching_note: str
    category: str | None
    rules: list[str] = field(default_factory=list)
    rubrics: list[str] = field(default_factory=list)
    evidence_quotes: list[str] = field(default_factory=list)
    retrieval_reason: str = ""
    node_set: set[str] | None = None


# ─────────────────────────────────────────────────────
#  Hyperedge templates & diagnostic rules (declarative)
# ─────────────────────────────────────────────────────

# Each template describes an ideal or diagnostic hyperedge pattern
# across dimensions (stakeholder, pain_point, solution, etc.).
_HYPEREDGE_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "T1_user_pain_solution_bm",
        "name": "痛点-人群-解决方案-商业模式闭环",
        "dimensions": ["stakeholder", "pain_point", "solution", "business_model"],
        "description": "用户→痛点→方案→商业模式形成完整闭环",
        "pattern_type": "ideal",
        "linked_rules": ["H1", "H2", "H3"],
    },
    {
        "id": "T2_user_pain_evidence",
        "name": "痛点证据链",
        "dimensions": ["stakeholder", "pain_point", "evidence"],
        "description": "针对核心痛点提供用户证据",
        "pattern_type": "ideal",
        "linked_rules": ["H5"],
    },
    {
        "id": "T3_solution_tech_market",
        "name": "方案-技术-市场匹配",
        "dimensions": ["solution", "technology", "market"],
        "description": "技术路线与目标市场匹配",
    },
    {
        "id": "T4_market_competition_solution",
        "name": "市场-竞品-方案定位",
        "dimensions": ["market", "competitor", "solution"],
        "description": "在既有竞争格局中清晰定位方案",
    },
    {
        "id": "T5_business_model_finance",
        "name": "商业模式-财务逻辑",
        "dimensions": ["business_model", "resource", "team"],
        "description": "商业模式与资源/团队可行性匹配",
    },
    {
        "id": "T6_unit_economics",
        "name": "单位经济模型闭环",
        "dimensions": ["business_model", "market", "resource"],
        "description": "单位经济与市场/资源约束一致",
        "pattern_type": "ideal",
        "linked_rules": ["H8", "H9"],
    },
    {
        "id": "T7_growth_path",
        "name": "增长路径",
        "dimensions": ["stakeholder", "channel", "market"],
        "description": "获客渠道与目标用户/市场相匹配",
    },
    {
        "id": "T8_team_execution",
        "name": "团队-里程碑-资源",
        "dimensions": ["team", "resource", "market"],
        "description": "团队能力与关键资源支撑里程碑达成",
    },
    {
        "id": "T9_risk_control",
        "name": "风险与合规",
        "dimensions": ["risk", "evidence", "market"],
        "description": "涉及数据/合规场景时给出控制措施",
        "pattern_type": "ideal",
        "linked_rules": ["H11"],
    },
    {
        "id": "T10_user_pain_solution_evidence",
        "name": "问题-方案-证据三角",
        "dimensions": ["stakeholder", "pain_point", "solution", "evidence"],
        "description": "核心方案有用户与实验双重证据支持",
        "pattern_type": "ideal",
        "linked_rules": ["H5", "H7"],
    },
    # 占位模板用于覆盖更多变体，便于后续细化
    {
        "id": "T11_market_size_growth",
        "name": "市场规模-增长假设",
        "dimensions": ["market", "business_model"],
        "description": "市场规模与增长路径假设一致",
        "pattern_type": "risk",
        "linked_rules": ["H4", "H9"],
    },
    {
        "id": "T12_competition_moat",
        "name": "竞品-护城河",
        "dimensions": ["competitor", "resource", "business_model"],
        "description": "在竞争格局中说明护城河与资源壁垒",
        "pattern_type": "ideal",
        "linked_rules": ["H6", "H7"],
    },
    {
        "id": "T13_tech_feasibility",
        "name": "技术可行性",
        "dimensions": ["technology", "team", "resource"],
        "description": "技术方案与团队/资源能力匹配",
    },
    {
        "id": "T14_evidence_financial",
        "name": "证据-财务",
        "dimensions": ["evidence", "business_model"],
        "description": "财务模型关键参数有数据或实验支撑",
        "pattern_type": "risk",
        "linked_rules": ["H8"],
    },
    {
        "id": "T15_evidence_market",
        "name": "证据-市场规模",
        "dimensions": ["evidence", "market"],
        "description": "市场规模假设有公开数据或调研支撑",
        "pattern_type": "risk",
        "linked_rules": ["H4"],
    },
    {
        "id": "T16_user_channel",
        "name": "用户-渠道匹配",
        "dimensions": ["stakeholder", "channel"],
        "description": "获客渠道与用户行为习惯匹配",
        "pattern_type": "ideal",
        "linked_rules": ["H2"],
    },
    {
        "id": "T17_pain_solution_pricing",
        "name": "痛点-方案-定价",
        "dimensions": ["pain_point", "solution", "business_model"],
        "description": "定价与痛点强度/替代方案价格一致",
        "pattern_type": "risk",
        "linked_rules": ["H3"],
    },
    {
        "id": "T18_team_risk",
        "name": "团队-风险",
        "dimensions": ["team", "risk"],
        "description": "关键风险有明确负责人与缓解计划",
        "pattern_type": "ideal",
        "linked_rules": ["H10", "H11"],
    },
    {
        "id": "T19_loop_full",
        "name": "完整商业闭环",
        "dimensions": [
            "stakeholder", "pain_point", "solution",
            "market", "competitor", "business_model",
        ],
        "description": "从用户到商业模式的完整闭环",
        "pattern_type": "ideal",
        "linked_rules": ["H1", "H2", "H3", "H4", "H6", "H8"],
    },
    {
        "id": "T20_growth_defensibility",
        "name": "增长-护城河",
        "dimensions": ["market", "business_model", "resource"],
        "description": "增长路径与护城河相互支撑",
        "pattern_type": "ideal",
        "linked_rules": ["H6", "H9", "H12"],
    },
]


def _load_teacher_overrides() -> dict:
    """Load optional teacher override configuration for hypergraph layer."""
    try:
        cfg_dir = settings.workspace_root / "config"
        overrides_path = cfg_dir / "teacher_overrides.json"
        if not overrides_path.exists():
            return {}
        data = json.loads(overrides_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _apply_template_overrides(templates: list[dict[str, Any]], overrides: list[dict] | None) -> list[dict[str, Any]]:
    if not overrides:
        return templates
    by_id: dict[str, dict[str, Any]] = {str(t.get("id")): t for t in templates if t.get("id")}
    for ov in overrides:
        tid = str(ov.get("id") or "").strip()
        if not tid:
            continue
        base = by_id.get(tid, {"id": tid})
        patch = {k: v for k, v in ov.items() if k != "id"}
        base.update(patch)
        by_id[tid] = base
    return list(by_id.values())


# Hypergraph-level consistency rules (>=20) operating on dimension
# coverage and simple text signals. Each rule returns a warning and
# optional pressure-test questions.
_CONSISTENCY_RULES: list[dict[str, Any]] = [
    {
        "id": "G1_no_competitor",
        "description": "未识别竞品或替代品时触发",
        "predicate": lambda dims, ents: not dims.get("competitor"),
        "message": "未给出任何直接或间接竞品，建议补充替代方案分析。",
        "pressure": [
            "请列出至少3个用户当前可能在用的替代方案（包括线下/手工方案）？",
            "如果明天某个互联网巨头免费提供类似服务，你的差异化在哪里？",
        ],
    },
    {
        "id": "G2_user_without_evidence",
        "description": "有目标用户与痛点，但缺少证据维度",
        "predicate": lambda dims, ents: dims.get("stakeholder") and dims.get("pain_point") and not dims.get("evidence"),
        "message": "已描述用户与痛点，但缺少任何访谈或问卷等证据。",
        "pressure": [
            "你是否进行过至少8次深度访谈？请给出1-2条用户原话。",
            "如果评委质疑这是你想象出来的痛点，你会拿出哪份材料？",
        ],
    },
    {
        "id": "G3_solution_without_pain",
        "description": "有方案与技术但没有清晰痛点",
        "predicate": lambda dims, ents: dims.get("solution") and not dims.get("pain_point"),
        "message": "描述了方案但缺少明确的用户痛点，可能是解无问题。",
        "pressure": [
            "请用一句话说清楚：哪一类用户，在什么具体场景下，被什么事情折磨？",
        ],
    },
    {
        "id": "G4_cac_without_channel",
        "description": "提到 CAC/投放预算但缺少渠道与转化逻辑",
        "predicate": lambda dims, ents: any("cac" in e.lower() for e in ents.get("text", [])) and not dims.get("channel"),
        "message": "涉及 CAC/投放，却未说明具体渠道与转化率假设。",
        "pressure": [
            "你的获客渠道具体是什么？请给出每个渠道的转化率假设。",
            "如果渠道成本上涨50%，你的 CAC 是否仍然可接受？",
        ],
    },
    {
        "id": "G5_growth_jump",
        "description": "出现1%市场/指数增长等跳跃式假设",
        "predicate": lambda dims, ents: any("1%" in e or "百分之一" in e for e in ents.get("text", [])),
        "message": "包含自上而下的1%市场假设，缺少自下而上的增长路径。",
        "pressure": [
            "请从一个具体渠道开始，自下而上估算第一年你能获得多少付费用户？",
        ],
    },
    {
        "id": "G6_no_market",
        "description": "缺少市场维度",
        "predicate": lambda dims, ents: not dims.get("market"),
        "message": "尚未说明市场规模或目标市场，无法评估商业空间。",
        "pressure": [
            "请给出目标市场的大致规模以及主要数据来源（行业报告/公开数据等）。",
        ],
    },
    {
        "id": "G7_no_business_model",
        "description": "没有商业模式描述",
        "predicate": lambda dims, ents: dims.get("solution") and not dims.get("business_model"),
        "message": "已有方案，但尚未说明谁为此付费以及如何收钱。",
        "pressure": [
            "谁在什么场景下，为你的方案实际掏钱？一次多少钱？",
        ],
    },
    {
        "id": "G8_finance_without_evidence",
        "description": "有财务/盈利表述但缺少数据来源",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])).lower() for k in ["营收", "利润", "盈利"]) and not dims.get("evidence"),
        "message": "谈到营收/盈利，但缺少任何数据来源或测算过程。",
        "pressure": [
            "你的收入与成本假设分别来自哪些数据或实验？",
        ],
    },
    {
        "id": "G9_risk_without_control",
        "description": "涉及隐私/数据/医疗等高风险场景但无控制措施",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])).lower() for k in ["隐私", "数据", "医疗", "未成年人"]) and not dims.get("risk"),
        "message": "涉及高敏感场景但缺少合规与风险控制说明。",
        "pressure": [
            "请画出一张数据流图，并标出每一步采用的合规措施？",
        ],
    },
    {
        "id": "G10_team_mismatch",
        "description": "技术/行业复杂而团队维度缺失",
        "predicate": lambda dims, ents: dims.get("technology") and not dims.get("team"),
        "message": "技术路线较重，但未说明团队能力与分工。",
        "pressure": [
            "谁来负责核心技术实现？他/她过往有哪些相关经验？",
        ],
    },
    # 额外规则占位，保证数量充足且覆盖逻辑幻觉场景
    {
        "id": "G11_no_channel_detail",
        "description": "只有模糊的线上推广/自媒体说法",
        "predicate": lambda dims, ents: dims.get("stakeholder") and not dims.get("channel"),
        "message": "获客方式仅停留在模糊的线上推广，缺少可执行渠道。",
        "pressure": [
            "请列出3个最有可能触达目标用户的具体渠道，并估算每个渠道的 CAC。",
        ],
    },
    {
        "id": "G12_solution_overengineered",
        "description": "技术堆叠过多而痛点不明确",
        "predicate": lambda dims, ents: dims.get("technology") and not dims.get("pain_point"),
        "message": "技术方案复杂，但看不出是为了解决哪个具体痛点。",
        "pressure": [
            "请删除80%的技术描述，只保留与核心痛点直接相关的部分。",
        ],
    },
    {
        "id": "G13_no_evidence_for_competition",
        "description": "声称有护城河但无竞品/替代品对比",
        "predicate": lambda dims, ents: dims.get("business_model") and not dims.get("competitor"),
        "message": "谈到优势/护城河，但缺少与竞品或替代方案的对比。",
        "pressure": [
            "请完成一张至少包含3个竞品/替代品的对比表，并标出你的2-3个关键差异。",
        ],
    },
    {
        "id": "G14_no_growth_logic",
        "description": "没有给出从0到1的增长路径",
        "predicate": lambda dims, ents: dims.get("business_model") and not dims.get("market"),
        "message": "尚未说明从冷启动到规模化的增长路径。",
        "pressure": [
            "用3-5步描述你从第一个付费用户到前100个用户的获取路径。",
        ],
    },
    {
        "id": "G15_resource_gap",
        "description": "依赖关键资源但未说明获取方式",
        "predicate": lambda dims, ents: dims.get("resource") and not dims.get("evidence"),
        "message": "提到重要资源，但没有说明如何获取与成本。",
        "pressure": [
            "这些关键资源目前掌握在谁手里？你如何以可接受的成本获得？",
        ],
    },
    {
        "id": "G16_team_no_roadmap",
        "description": "团队存在但缺少里程碑规划",
        "predicate": lambda dims, ents: dims.get("team") and not dims.get("resource"),
        "message": "团队已介绍，但缺少阶段性里程碑与分工。",
        "pressure": [
            "未来3个月内你们各自要完成哪些可验收的里程碑？",
        ],
    },
    {
        "id": "G17_evidence_scattered",
        "description": "有零散数据但未形成证据链",
        "predicate": lambda dims, ents: dims.get("evidence") and not (dims.get("stakeholder") and dims.get("pain_point")),
        "message": "存在零散数据，但未围绕核心用户与痛点形成闭环证据链。",
        "pressure": [
            "请将现有证据按“用户-痛点-方案效果”三个维度重新整理。",
        ],
    },
    {
        "id": "G18_overclaim_no_metric",
        "description": "存在“颠覆/革命性”等强表述但无指标",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])).lower() for k in ["颠覆", "革命", "改变行业"]) and not dims.get("evidence"),
        "message": "存在强烈主观判断，但缺少任何可量化指标。",
        "pressure": [
            "请给出3个可以量化的指标，用来证明你所谓的“颠覆性”。",
        ],
    },
    {
        "id": "G19_no_metric_focus",
        "description": "没有明确单一北极星指标",
        "predicate": lambda dims, ents: not any(k in " ".join(ents.get("text", [])).lower() for k in ["留存", "转化", "复购", "活跃"]),
        "message": "缺少聚焦的核心业务指标，难以评估项目进展。",
        "pressure": [
            "如果只能选一个指标衡量项目成败，你会选什么？为什么？",
        ],
    },
    {
        "id": "G20_no_risk_section",
        "description": "商业计划中完全没有风险章节",
        "predicate": lambda dims, ents: not dims.get("risk"),
        "message": "商业计划中缺少风险与对策章节，评委难以信任预期。",
        "pressure": [
            "请列出3个最可能让项目失败的风险，并给出各自的一条缓解措施。",
        ],
    },
]


_OVERRIDES = _load_teacher_overrides()
_HYPEREDGE_TEMPLATES = _apply_template_overrides(_HYPEREDGE_TEMPLATES, _OVERRIDES.get("hyperedge_templates"))


# ─────────────────────────────────────────────────────
#  Main service
# ─────────────────────────────────────────────────────

class HypergraphService:
    """Build/query teaching hypergraph + student dynamic analysis with HyperNetX."""

    def __init__(self, graph_service: GraphService) -> None:
        self.graph_service = graph_service
        self._hypergraph: hnx.Hypergraph | None = None
        self._records: list[HyperedgeRecord] = []
        self._family_counts: dict[str, int] = {}
        self._rule_alias: dict[str, list[str]] = {
            "H4": ["market_size_fallacy", "H9", "H19"],
            "H5": ["weak_user_evidence"],
            "H6": ["no_competitor_claim"],
            "H8": ["unit_economics_not_proven", "unit_economics_unsound"],
            "H11": ["compliance_not_covered"],
        }
        # Predefined hyperedge templates for logical loops.
        # These are used when analysing student content and do not
        # depend on Neo4j topology.
        self._edge_templates: list[dict[str, Any]] = _HYPEREDGE_TEMPLATES
        # Predefined hypergraph-level consistency rules.
        self._consistency_rules: list[dict[str, Any]] = _CONSISTENCY_RULES

    # ═══════════════════════════════════════════════════
    #  1. Rebuild global teaching hypergraph from Neo4j
    # ═══════════════════════════════════════════════════

    def rebuild(self, min_pattern_support: int = 1, max_edges: int = 50) -> dict[str, Any]:
        min_pattern_support = max(1, min(min_pattern_support, 10))
        max_edges = max(5, min(max_edges, 100))

        try:
            rows = self.graph_service._query_with_fallback(
                lambda session: list(
                    session.run(
                        """
                        MATCH (p:Project)-[:BELONGS_TO]->(c:Category)
                        RETURN p.id AS project_id,
                               c.name AS category,
                               coalesce(p.confidence, 0.0) AS confidence,
                               [(p)-[:HAS_TARGET_USER]->(u:Stakeholder) | u.name] AS stakeholders,
                               [(p)-[:HAS_PAIN]->(pain:PainPoint) | pain.name] AS pains,
                               [(p)-[:HAS_SOLUTION]->(sol:Solution) | sol.name] AS solutions,
                               [(p)-[:HAS_INNOVATION]->(inv:InnovationPoint) | inv.name] AS innovations,
                               [(p)-[:HAS_BUSINESS_MODEL]->(bm:BusinessModelAspect) | bm.name] AS business_models,
                               [(p)-[:HAS_MARKET_ANALYSIS]->(m:Market) | m.name] AS markets,
                               [(p)-[:HAS_EXECUTION_STEP]->(ex:ExecutionStep) | ex.name] AS execution_steps,
                               [(p)-[:HAS_RISK_CONTROL]->(rc:RiskControlPoint) | rc.name] AS risk_controls,
                               [(p)-[:HAS_EVIDENCE]->(e:Evidence) | {quote: coalesce(e.quote, ''), type: coalesce(e.type, ''), source_unit: coalesce(e.source_unit, '')}] AS evidence_rows,
                               [(p)-[ev:EVALUATED_BY]->(ri:RubricItem) | {name: ri.name, covered: coalesce(ev.covered, false)}] AS rubric_rows,
                               [(p)-[:HITS_RULE]->(r:RiskRule) | r.id] AS rule_ids
                        """
                    )
                )
            )
        except Exception as exc:
            logger.warning("Hypergraph source query failed: %s", exc)
            rows = []

        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            evidence_rows = []
            for item in row.get("evidence_rows") or []:
                if not isinstance(item, dict):
                    continue
                quote = str(item.get("quote", "")).strip()
                evidence_rows.append({
                    "quote": quote[:160],
                    "type": str(item.get("type", "")).strip(),
                    "source_unit": str(item.get("source_unit", "")).strip(),
                })
            rubric_rows = []
            for item in row.get("rubric_rows") or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                if not name:
                    continue
                rubric_rows.append({
                    "name": name,
                    "covered": bool(item.get("covered", False)),
                })
            normalized_rows.append({
                "project_id": str(row.get("project_id") or ""),
                "category": str(row.get("category") or "未分类"),
                "confidence": float(row.get("confidence") or 0.0),
                "stakeholders": self._unique_texts(list(row.get("stakeholders") or [])),
                "pains": self._unique_texts(list(row.get("pains") or [])),
                "solutions": self._unique_texts(list(row.get("solutions") or [])),
                "innovations": self._unique_texts(list(row.get("innovations") or [])),
                "business_models": self._unique_texts(list(row.get("business_models") or [])),
                "markets": self._unique_texts(list(row.get("markets") or [])),
                "execution_steps": self._unique_texts(list(row.get("execution_steps") or [])),
                "risk_controls": self._unique_texts(list(row.get("risk_controls") or [])),
                "evidence_rows": evidence_rows[:8],
                "rubric_rows": rubric_rows[:12],
                "rule_ids": self._unique_texts(list(row.get("rule_ids") or []), max_items=8),
            })
        return normalized_rows

    def _load_ontology_rows(self) -> list[dict[str, Any]]:
        try:
            return self.graph_service._query_with_fallback(
                lambda session: list(
                    session.run(
                        """
                        MATCH (n)-[:INSTANCE_OF]->(o:OntologyNode)
                        OPTIONAL MATCH (p:Project)-[:BELONGS_TO]->(c:Category)
                        WHERE EXISTS { MATCH (p)-[:HAS_TARGET_USER]->(n) }
                           OR EXISTS { MATCH (p)-[:HAS_PAIN]->(n) }
                           OR EXISTS { MATCH (p)-[:HAS_SOLUTION]->(n) }
                           OR EXISTS { MATCH (p)-[:HAS_BUSINESS_MODEL]->(n) }
                           OR EXISTS { MATCH (p)-[:HAS_MARKET_ANALYSIS]->(n) }
                           OR EXISTS { MATCH (p)-[:HAS_EXECUTION_STEP]->(n) }
                           OR EXISTS { MATCH (p)-[:HAS_RISK_CONTROL]->(n) }
                        RETURN coalesce(o.id, o.name, 'unknown') AS ontology_id,
                               coalesce(o.name, o.id, 'unknown') AS ontology_name,
                               coalesce(n.name, n.id, '') AS instance_name,
                               head(labels(n)) AS instance_label,
                               collect(DISTINCT c.name)[0..5] AS categories,
                               count(DISTINCT p) AS support
                        ORDER BY support DESC
                        LIMIT 40
                        """
                    )
                )
            )
        except Exception:
            return []

    def _register_pattern(self, bucket: dict[tuple, dict[str, Any]], key: tuple, payload: dict[str, Any]) -> None:
        slot = bucket.setdefault(
            key,
            {
                "support": 0,
                "category": payload.get("category"),
                "node_set": set(),
                "rules": set(),
                "rubrics": set(),
                "evidence_quotes": [],
                "teaching_note": payload.get("teaching_note", ""),
                "retrieval_reason": payload.get("retrieval_reason", ""),
            },
        )
        slot["support"] += 1
        slot["node_set"].update(payload.get("node_set", set()))
        slot["rules"].update(payload.get("rules", []))
        slot["rubrics"].update(payload.get("rubrics", []))
        for quote in payload.get("evidence_quotes", []):
            q = str(quote or "").strip()
            if q and q not in slot["evidence_quotes"]:
                slot["evidence_quotes"].append(q[:160])
        if not slot["teaching_note"]:
            slot["teaching_note"] = payload.get("teaching_note", "")
        if not slot["retrieval_reason"]:
            slot["retrieval_reason"] = payload.get("retrieval_reason", "")

    def _add_record(
        self,
        edge_to_nodes: dict[str, set[str]],
        records: list[HyperedgeRecord],
        edge_type: str,
        payload: dict[str, Any],
    ) -> None:
        node_set = {str(x) for x in payload.get("node_set", set()) if str(x)}
        if len(node_set) < 3:
            return
        idx = self._family_counts.get(edge_type, 0) + 1
        self._family_counts[edge_type] = idx
        edge_id = f"{EDGE_PREFIX.get(edge_type, 'he_misc_')}{idx:03d}"
        edge_to_nodes[edge_id] = node_set
        records.append(
            HyperedgeRecord(
                hyperedge_id=edge_id,
                type=edge_type,
                support=int(payload.get("support", 1) or 1),
                teaching_note=str(payload.get("teaching_note", "") or EDGE_FAMILY_LABELS.get(edge_type, edge_type)),
                category=str(payload.get("category") or "") or None,
                rules=sorted({str(x) for x in payload.get("rules", []) if x}),
                rubrics=sorted({str(x) for x in payload.get("rubrics", []) if x}),
                evidence_quotes=[str(x)[:160] for x in (payload.get("evidence_quotes", []) or [])[:3] if x],
                retrieval_reason=str(payload.get("retrieval_reason", "")),
                node_set=node_set,
            )
        )

    # ═══════════════════════════════════════════════════
    #  1. Rebuild global teaching hypergraph from Neo4j
    # ═══════════════════════════════════════════════════

    def rebuild(self, min_pattern_support: int = 1, max_edges: int = 50) -> dict[str, Any]:
        min_pattern_support = max(1, min(min_pattern_support, 10))
        max_edges = max(5, min(max_edges, 100))
        rows = self._load_project_rows()
        ontology_rows = self._load_ontology_rows()
        edge_to_nodes: dict[str, set[str]] = {}
        records: list[HyperedgeRecord] = []
        self._family_counts = {}
        families: dict[str, dict[tuple, dict[str, Any]]] = {k: {} for k in EDGE_TARGET_COUNTS}

        for row in rows:
            category = str(row.get("category") or "未分类")
            stakeholders = list(row.get("stakeholders") or [])
            pains = list(row.get("pains") or [])
            solutions = list(row.get("solutions") or [])
            innovations = list(row.get("innovations") or [])
            business_models = list(row.get("business_models") or [])
            markets = list(row.get("markets") or [])
            execution_steps = list(row.get("execution_steps") or [])
            risk_controls = list(row.get("risk_controls") or [])
            evidence_rows = list(row.get("evidence_rows") or [])
            rubric_rows = list(row.get("rubric_rows") or [])
            rule_ids = list(row.get("rule_ids") or [])
            evidence_quotes = [str(e.get("quote", "")).strip() for e in evidence_rows if isinstance(e, dict) and e.get("quote")]
            evidence_types = self._unique_texts([e.get("type", "") for e in evidence_rows if isinstance(e, dict)])
            covered_rubrics = self._unique_texts([r.get("name", "") for r in rubric_rows if isinstance(r, dict) and r.get("covered")])
            uncovered_rubrics = self._unique_texts([r.get("name", "") for r in rubric_rows if isinstance(r, dict) and not r.get("covered")])

            if pains and solutions:
                stakeholder = stakeholders[0] if stakeholders else "未细分用户"
                business_model = business_models[0] if business_models else "商业模式待补强"
                market = markets[0] if markets else "市场分析待补强"
                pain = pains[0]
                solution = solutions[0]
                key = (category, stakeholder, pain, solution, business_model, market)
                self._register_pattern(
                    families["Value_Loop_Edge"],
                    key,
                    {
                        "category": category,
                        "node_set": {
                            f"Category::{category}",
                            f"Stakeholder::{stakeholder}",
                            f"PainPoint::{pain}",
                            f"Solution::{solution}",
                            f"BusinessModelAspect::{business_model}",
                            f"Market::{market}",
                        },
                        "rules": rule_ids,
                        "rubrics": covered_rubrics,
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类项目常围绕“{stakeholder}—{pain}—{solution}”形成价值闭环，并需要通过{business_model}完成变现。",
                        "retrieval_reason": "目标用户、痛点、方案与商业模式同时出现，适合做价值闭环检索。",
                    },
                )

            if stakeholders and pains:
                stakeholder = stakeholders[0]
                pain = pains[0]
                solution = solutions[0] if solutions else "解决方案待补强"
                key = (category, stakeholder, pain, solution)
                self._register_pattern(
                    families["User_Pain_Fit_Edge"],
                    key,
                    {
                        "category": category,
                        "node_set": {
                            f"Category::{category}",
                            f"Stakeholder::{stakeholder}",
                            f"PainPoint::{pain}",
                            f"Solution::{solution}",
                        },
                        "rules": rule_ids,
                        "rubrics": covered_rubrics,
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类项目中，面向“{stakeholder}”的项目经常围绕“{pain}”来设计方案匹配。",
                        "retrieval_reason": "用户与痛点同时明确，适合用于用户痛点匹配追问。",
                    },
                )

            if rule_ids:
                rule_tuple = tuple(sorted(rule_ids[:3]))
                rubric_tuple = tuple(sorted((uncovered_rubrics or covered_rubrics)[:2]))
                key = (category, rule_tuple, rubric_tuple)
                self._register_pattern(
                    families["Risk_Pattern_Edge"],
                    key,
                    {
                        "category": category,
                        "node_set": {f"Category::{category}"} | {f"RiskRule::{rid}" for rid in rule_tuple} | {f"RubricItem::{rb}" for rb in rubric_tuple},
                        "rules": list(rule_tuple),
                        "rubrics": list(rubric_tuple),
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类项目常见风险模式为“{'、'.join(rule_tuple)}”，通常会拖累{'、'.join(rubric_tuple) if rubric_tuple else '多个评分维度'}。",
                        "retrieval_reason": "风险规则与Rubric覆盖共同命中，适合做风险模式检索。",
                    },
                )

            if evidence_types and (covered_rubrics or uncovered_rubrics or rule_ids):
                rubric_anchor = tuple(sorted((uncovered_rubrics or covered_rubrics)[:2]))
                evidence_anchor = tuple(sorted(evidence_types[:2]))
                rule_anchor = tuple(sorted(rule_ids[:2]))
                key = (category, evidence_anchor, rubric_anchor, rule_anchor)
                self._register_pattern(
                    families["Evidence_Grounding_Edge"],
                    key,
                    {
                        "category": category,
                        "node_set": {f"Category::{category}"} | {f"EvidenceType::{x}" for x in evidence_anchor} | {f"RubricItem::{x}" for x in rubric_anchor} | {f"RiskRule::{x}" for x in rule_anchor},
                        "rules": list(rule_anchor),
                        "rubrics": list(rubric_anchor),
                        "evidence_quotes": evidence_quotes[:3],
                        "teaching_note": f"{category}类项目常用“{'、'.join(evidence_anchor)}”类证据支撑{'、'.join(rubric_anchor) if rubric_anchor else '核心判断'}。",
                        "retrieval_reason": "证据类型与评分维度能对齐，适合做证据锚定检索。",
                    },
                )

            market_rule_hit = any(rid in {"H4", "H6", "H9", "H16", "H17", "H19"} for rid in rule_ids)
            if markets or market_rule_hit:
                market = markets[0] if markets else "市场口径待校准"
                stakeholder = stakeholders[0] if stakeholders else "目标用户待细化"
                innovation = innovations[0] if innovations else (solutions[0] if solutions else "差异化待说明")
                key = (category, market, stakeholder, innovation)
                self._register_pattern(
                    families["Market_Competition_Edge"],
                    key,
                    {
                        "category": category,
                        "node_set": {
                            f"Category::{category}",
                            f"Market::{market}",
                            f"Stakeholder::{stakeholder}",
                            f"InnovationPoint::{innovation}",
                        },
                        "rules": [rid for rid in rule_ids if rid in {"H4", "H6", "H9", "H16", "H17", "H19"}],
                        "rubrics": uncovered_rubrics or covered_rubrics,
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类项目的竞争与市场判断，通常要同时回答市场口径、替代方案和差异化价值三个问题。",
                        "retrieval_reason": "市场/竞争相关节点或规则被命中，适合做竞争与替代方案追问。",
                    },
                )

            execution_rule_hit = any(rid in {"H10", "H12", "H21", "H22"} for rid in rule_ids)
            if execution_steps or execution_rule_hit:
                step = execution_steps[0] if execution_steps else "执行路径待拆解"
                business_model = business_models[0] if business_models else "商业闭环待补强"
                risk_control = risk_controls[0] if risk_controls else "风控机制待细化"
                key = (category, step, business_model, risk_control)
                self._register_pattern(
                    families["Execution_Gap_Edge"],
                    key,
                    {
                        "category": category,
                        "node_set": {
                            f"Category::{category}",
                            f"ExecutionStep::{step}",
                            f"BusinessModelAspect::{business_model}",
                            f"RiskControlPoint::{risk_control}",
                        },
                        "rules": [rid for rid in rule_ids if rid in {"H10", "H12", "H21", "H22"}],
                        "rubrics": [rb for rb in (covered_rubrics + uncovered_rubrics) if rb in {"Team & Execution", "Business Model Consistency"}],
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类项目在执行层面最常见的问题，是步骤、商业闭环和风控机制没有一起落地。",
                        "retrieval_reason": "执行节点或执行类风险被命中，适合做执行断裂追问。",
                    },
                )

            compliance_rule_hit = any(rid in {"H11", "H22"} for rid in rule_ids)
            if risk_controls or compliance_rule_hit:
                risk_control = risk_controls[0] if risk_controls else "合规措施待细化"
                evidence_type = evidence_types[0] if evidence_types else "制度证据待补充"
                key = (category, risk_control, evidence_type)
                self._register_pattern(
                    families["Compliance_Safety_Edge"],
                    key,
                    {
                        "category": category,
                        "node_set": {
                            f"Category::{category}",
                            f"RiskControlPoint::{risk_control}",
                            f"EvidenceType::{evidence_type}",
                            "RubricItem:合规与风险",
                        },
                        "rules": [rid for rid in rule_ids if rid in {"H11", "H22"}],
                        "rubrics": [rb for rb in (covered_rubrics + uncovered_rubrics) if "risk" in rb.lower() or "presentation" in rb.lower()],
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类项目一旦涉及数据、伦理或合规，就必须把措施写成可执行流程，而不是停留在原则层面。",
                        "retrieval_reason": "合规/风控节点或规则被命中，适合做安全边界追问。",
                    },
                )

            innovation_rule_hit = any(rid in {"H7", "H13", "H23"} for rid in rule_ids)
            if innovations or innovation_rule_hit:
                innovation = innovations[0] if innovations else "创新主张待验证"
                evidence_type = evidence_types[0] if evidence_types else "验证证据待补充"
                market = markets[0] if markets else "应用场景待限定"
                key = (category, innovation, evidence_type, market)
                self._register_pattern(
                    families["Innovation_Validation_Edge"],
                    key,
                    {
                        "category": category,
                        "node_set": {
                            f"Category::{category}",
                            f"InnovationPoint::{innovation}",
                            f"EvidenceType::{evidence_type}",
                            f"Market::{market}",
                        },
                        "rules": [rid for rid in rule_ids if rid in {"H7", "H13", "H23"}],
                        "rubrics": [rb for rb in (covered_rubrics + uncovered_rubrics) if rb in {"Innovation & Differentiation", "Solution Feasibility"}],
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类项目的创新点必须能落到具体场景和可验证证据上，否则只是口号。",
                        "retrieval_reason": "创新主张或验证类规则被命中，适合做创新验证追问。",
                    },
                )

        for row in ontology_rows:
            ontology_name = str(row.get("ontology_name") or "未知本体")
            ontology_id = str(row.get("ontology_id") or ontology_name)
            instance_name = str(row.get("instance_name") or "").strip()
            instance_label = str(row.get("instance_label") or "实例")
            categories = self._unique_texts(list(row.get("categories") or []), max_items=3)
            support = int(row.get("support") or 0)
            if not instance_name or support < min_pattern_support:
                continue
            category = categories[0] if categories else "跨类别"
            key = (ontology_id, instance_name, tuple(categories))
            self._register_pattern(
                families["Ontology_Grounded_Edge"],
                key,
                {
                    "category": category,
                    "node_set": {f"OntologyNode::{ontology_name}", f"{instance_label}::{instance_name}"} | {f"Category::{c}" for c in categories},
                    "rules": [],
                    "rubrics": [],
                    "evidence_quotes": [],
                    "teaching_note": f"本体概念“{ontology_name}”在真实案例中常落地为“{instance_name}”等表述。",
                    "retrieval_reason": "教学本体与实例表达被打通，适合做概念落地解释。",
                },
            )
            families["Ontology_Grounded_Edge"][key]["support"] = support

        total_budget = max_edges
        created_counts: Counter[str] = Counter()
        for edge_type, target_count in EDGE_TARGET_COUNTS.items():
            patterns = list(families[edge_type].values())
            patterns.sort(key=lambda item: (int(item.get("support", 0)), len(item.get("node_set", []))), reverse=True)
            count = 0
            for payload in patterns:
                if total_budget <= 0 or count >= target_count:
                    break
                if int(payload.get("support", 0)) < min_pattern_support:
                    continue
                self._add_record(edge_to_nodes, records, edge_type, payload)
                count += 1
                total_budget -= 1
            created_counts[edge_type] = count

        self._hypergraph = hnx.Hypergraph(edge_to_nodes) if edge_to_nodes else hnx.Hypergraph({})
        self._records = records
        return {
            "ok": True,
            "created": dict(created_counts),
            "total_nodes": len(self._hypergraph.nodes) if self._hypergraph else 0,
            "total_edges": len(self._hypergraph.edges) if self._hypergraph else 0,
            "notes": "HyperNetX 超图已重建（按现有 KG schema 构建 6-8 个超边族）。",
        }

    # ═══════════════════════════════════════════════════
    #  2. Query existing hypergraph for teaching insights
    # ═══════════════════════════════════════════════════

    def insight(
        self,
        category: str | None = None,
        rule_ids: list[str] | None = None,
        preferred_edge_types: list[str] | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        if not self._records:
            rebuilt = self.rebuild(min_pattern_support=1, max_edges=50)
            if not rebuilt.get("ok"):
                return {"ok": False, "edges": [], "error": rebuilt.get("error", "rebuild failed")}

        safe_rules = [str(x) for x in (rule_ids or []) if x]
        safe_edge_types = [str(x) for x in (preferred_edge_types or []) if x]
        expanded_rules: set[str] = set(safe_rules)
        for rid in safe_rules:
            for alias in self._rule_alias.get(rid, []):
                expanded_rules.add(alias)

        matched: list[tuple[float, dict[str, Any]]] = []
        for rec in self._records:
            cat_hit = bool(category and rec.category and rec.category == category)
            rule_hit = any(r in rec.rules for r in expanded_rules) if expanded_rules else False
            type_hit = rec.type in safe_edge_types if safe_edge_types else False
            if (not category and not safe_rules and not safe_edge_types) or cat_hit or rule_hit or type_hit:
                score = 0.0
                if cat_hit:
                    score += 2.0
                if rule_hit:
                    score += 3.0
                if type_hit:
                    score += 1.8
                score += min(2.0, rec.support / 5)
                matched.append((score, {
                    "hyperedge_id": rec.hyperedge_id,
                    "type": rec.type,
                    "support": rec.support,
                    "teaching_note": rec.teaching_note,
                    "categories": [rec.category] if rec.category else [],
                    "rules": rec.rules,
                    "rubrics": rec.rubrics,
                    "evidence_quotes": rec.evidence_quotes,
                    "retrieval_reason": rec.retrieval_reason,
                    "nodes": sorted(rec.node_set) if rec.node_set else [],
                    "match_score": round(score, 2),
                }))

        matched.sort(key=lambda item: item[0], reverse=True)

        topology = self._get_topology_stats()

        return {
            "ok": True,
            "edges": [item for _, item in matched[:max(1, min(limit, 20))]],
            "matched_by": {
                "category": category,
                "rule_ids": safe_rules,
                "expanded_rule_ids": sorted(expanded_rules),
                "preferred_edge_types": safe_edge_types,
            },
            "topology": topology,
            "meta": {
                "engine": "hypernetx",
                "edge_count": len(self._records),
                "node_count": len(self._hypergraph.nodes) if self._hypergraph else 0,
                "family_counts": dict(self._family_counts),
            },
        }

    def _get_topology_stats(self) -> dict[str, Any]:
        """Extract topology statistics from the built hypergraph."""
        if not self._hypergraph or len(self._hypergraph.edges) == 0:
            return {}
        try:
            hg = self._hypergraph
            node_degrees = {}
            for node in list(hg.nodes)[:20]:
                try:
                    memberships = hg.nodes.memberships[node]
                    node_degrees[str(node)] = len(memberships)
                except Exception:
                    pass

            edge_sizes = {}
            for edge in list(hg.edges)[:20]:
                try:
                    edge_sizes[str(edge)] = len(hg.edges[edge])
                except Exception:
                    pass

            hub_nodes = sorted(node_degrees.items(), key=lambda x: -x[1])[:5]

            return {
                "hub_nodes": [{"node": n, "degree": d, "interpretation": self._interpret_hub(n, d)} for n, d in hub_nodes],
                "avg_edge_size": round(sum(edge_sizes.values()) / max(1, len(edge_sizes)), 1) if edge_sizes else 0,
                "max_edge_size": max(edge_sizes.values()) if edge_sizes else 0,
            }
        except Exception as exc:
            logger.warning("Topology stats extraction failed: %s", exc)
            return {}

    @staticmethod
    def _interpret_hub(node: str, degree: int) -> str:
        """Generate a human-readable interpretation of a hub node."""
        if "::" in node:
            ntype, name = node.split("::", 1)
        else:
            ntype, name = "Unknown", node

        if ntype == "RiskRule":
            return f"风险规则「{name}」关联{degree}种模式，是最普遍的问题"
        elif ntype == "Category":
            return f"「{name}」类别出现在{degree}种超边中，是最活跃的赛道"
        elif ntype == "Stakeholder":
            return f"目标用户「{name}」被{degree}种模式共享，是高频用户群"
        elif ntype == "PainPoint":
            return f"痛点「{name}」连接了{degree}种模式，是高频真实问题"
        elif ntype == "Market":
            return f"市场「{name}」涉及{degree}种模式，是热门目标市场"
        elif ntype == "RubricItem":
            return f"评分维度「{name}」被{degree}种模式反复命中，是重要教学检查点"
        return f"节点「{name}」关联{degree}种模式"

    # ═══════════════════════════════════════════════════
    #  3. Student content dynamic hypergraph analysis
    # ═══════════════════════════════════════════════════

    def analyze_student_content(
        self,
        entities: list[dict],
        relationships: list[dict],
        structural_gaps: list[str] | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        """
        Build a temporary hypergraph from student's KG entities and perform
        cross-dimensional pattern discovery.

        Returns structured insights about the student's project:
        - Dimension coverage (which key areas are addressed)
        - Cross-dimensional connections (which entities bridge multiple dimensions)
        - Missing dimensions (gaps that weaken the project)
        - Pattern matches with known good/bad patterns from teaching hypergraph
        """
        if not entities:
            return {
                "ok": False,
                "dimensions": {},
                "cross_links": [],
                "coverage_score": 0,
                "pattern_warnings": [],
                "pattern_strengths": [],
                "projected_edge_types": [],
                "missing_dimensions": ["无法分析：未提取到实体"],
            }

        DIMENSIONS = {
            "stakeholder": "目标用户",
            "pain_point": "痛点问题",
            "solution": "解决方案",
            "innovation": "创新点",
            "market": "目标市场",
            "competitor": "竞争格局",
            "business_model": "商业模式",
            "execution_step": "执行步骤",
            "risk_control": "风控合规",
            "evidence": "证据支撑",
            "technology": "技术路线",
            "resource": "资源优势",
            "team": "团队能力",
            # virtual dimensions derived from text/structure
            "evidence": "证据与数据",
            "risk": "风险与合规",
            "channel": "获客渠道",
        }

        dim_entities: dict[str, list[str]] = defaultdict(list)
        entity_map: dict[str, str] = {}
        raw_text_fragments: list[str] = []
        for e in entities:
            etype = str(e.get("type", "other")).lower()
            label = str(e.get("label", ""))
            eid = str(e.get("id", label))
            dim_entities[etype].append(label)
            entity_map[eid] = etype
            if label:
                raw_text_fragments.append(label)

        # Build student hypergraph edges
        student_edges: dict[str, set[str]] = {}

        for dim, ents in dim_entities.items():
            if ents:
                edge_id = f"dim_{dim}"
                student_edges[edge_id] = {f"{dim}::{e}" for e in ents}

        projected_edge_types: list[str] = []
        if dim_entities.get("stakeholder") and dim_entities.get("pain_point") and dim_entities.get("solution"):
            projected_edge_types.append("User_Pain_Fit_Edge")
        if dim_entities.get("pain_point") and dim_entities.get("solution") and dim_entities.get("business_model"):
            projected_edge_types.append("Value_Loop_Edge")
        if dim_entities.get("market") or dim_entities.get("competitor"):
            projected_edge_types.append("Market_Competition_Edge")
        if dim_entities.get("evidence"):
            projected_edge_types.append("Evidence_Grounding_Edge")
        if dim_entities.get("execution_step") or dim_entities.get("team"):
            projected_edge_types.append("Execution_Gap_Edge")
        if dim_entities.get("risk_control"):
            projected_edge_types.append("Compliance_Safety_Edge")
        if dim_entities.get("innovation"):
            projected_edge_types.append("Innovation_Validation_Edge")

        for rel in relationships:
            src = str(rel.get("source", ""))
            tgt = str(rel.get("target", ""))
            src_type = entity_map.get(src, "other")
            tgt_type = entity_map.get(tgt, "other")
            if src_type != tgt_type:
                edge_id = f"cross_{src}_{tgt}"
                student_edges[edge_id] = {f"{src_type}::{src}", f"{tgt_type}::{tgt}"}

        try:
            student_hg = hnx.Hypergraph(student_edges) if student_edges else None
        except Exception:
            student_hg = None

        # ── Dimension coverage analysis ──
        covered_dims = set(dim_entities.keys()) & set(DIMENSIONS.keys())
        all_dims = set(DIMENSIONS.keys())
        missing_dims = all_dims - covered_dims
        coverage_score = round(len(covered_dims) / max(1, len(all_dims)) * 10, 1)

        dimensions_detail = {}
        for dim, display_name in DIMENSIONS.items():
            ents = dim_entities.get(dim, [])
            dimensions_detail[dim] = {
                "name": display_name,
                "covered": len(ents) > 0,
                "entities": ents[:5],
                "count": len(ents),
            }

        # ── Cross-dimensional connections ──
        cross_links = []
        for rel in relationships:
            src = str(rel.get("source", ""))
            tgt = str(rel.get("target", ""))
            src_type = entity_map.get(src, "other")
            tgt_type = entity_map.get(tgt, "other")
            if src_type != tgt_type and src_type in DIMENSIONS and tgt_type in DIMENSIONS:
                cross_links.append({
                    "from_dim": DIMENSIONS[src_type],
                    "to_dim": DIMENSIONS[tgt_type],
                    "from_entity": src,
                    "to_entity": tgt,
                    "relation": str(rel.get("relation", "")),
                })

        # ── Hub entity analysis (using HyperNetX topology) ──
        hub_entities = []
        if student_hg and len(student_hg.nodes) > 0:
            try:
                for node in list(student_hg.nodes)[:30]:
                    try:
                        memberships = student_hg.nodes.memberships[node]
                        deg = len(memberships)
                    except Exception:
                        deg = 0
                    if deg >= 2:
                        node_str = str(node)
                        if "::" in node_str:
                            ntype, nname = node_str.split("::", 1)
                        else:
                            ntype, nname = "other", node_str
                        hub_entities.append({
                            "entity": nname, "type": ntype, "connections": deg,
                            "note": f"「{nname}」连接{deg}个维度，是项目的核心支撑点",
                        })
                hub_entities.sort(key=lambda x: -x["connections"])
            except Exception:
                pass

        # ── Pattern matching against teaching hypergraph ──
        pattern_warnings = []
        pattern_strengths = []
        if self._records:
            student_rule_like = set()
            if not dim_entities.get("stakeholder"):
                student_rule_like.add("weak_user_evidence")
            if not dim_entities.get("competitor"):
                student_rule_like.add("no_competitor_claim")
            if not dim_entities.get("market"):
                student_rule_like.add("market_size_fallacy")
            if not dim_entities.get("evidence"):
                student_rule_like.add("evidence_weak")

            for rec in self._records:
                if rec.type == "Risk_Pattern_Edge":
                    overlap = student_rule_like & set(rec.rules)
                    if overlap and (not category or rec.category == category):
                        pattern_warnings.append({
                            "pattern_id": rec.hyperedge_id,
                            "warning": rec.teaching_note,
                            "matched_rules": sorted(overlap),
                            "support": rec.support,
                            "edge_type": rec.type,
                        })
                elif rec.type in {"Value_Loop_Edge", "User_Pain_Fit_Edge", "Evidence_Grounding_Edge"}:
                    if category and rec.category == category and coverage_score >= 6:
                        pattern_strengths.append({
                            "pattern_id": rec.hyperedge_id,
                            "note": rec.teaching_note,
                            "support": rec.support,
                            "edge_type": rec.type,
                        })
                elif rec.type in {"Market_Competition_Edge", "Execution_Gap_Edge", "Compliance_Safety_Edge", "Innovation_Validation_Edge"}:
                    if (not category or rec.category == category):
                        pattern_strengths.append({
                            "pattern_id": rec.hyperedge_id,
                            "note": rec.teaching_note,
                            "support": rec.support,
                            "edge_type": rec.type,
                        })

        # ── Missing dimension recommendations ──
        missing_recommendations = []
        gap_importance = {
            "stakeholder": ("极高", "缺少明确的目标用户画像，评委会质疑'你为谁解决问题'"),
            "pain_point": ("极高", "没有清晰的痛点描述，项目缺乏存在的理由"),
            "solution": ("高", "缺少具体的解决方案描述"),
            "market": ("高", "没有市场分析，无法评估商业可行性"),
            "competitor": ("中", "缺少竞争分析，评委会问'为什么是你'"),
            "business_model": ("中", "商业模式不清晰，盈利路径不明"),
            "technology": ("中", "技术路线未说明，可行性存疑"),
            "resource": ("低", "未提及资源优势，但可后续补充"),
            "team": ("低", "团队信息缺失，但非必须一开始就有"),
        }
        for dim in missing_dims:
            if dim in gap_importance:
                importance, reason = gap_importance[dim]
                missing_recommendations.append({
                    "dimension": DIMENSIONS.get(dim, dim),
                    "importance": importance,
                    "recommendation": reason,
                })
        if structural_gaps:
            for gap in structural_gaps[:3]:
                missing_recommendations.append({
                    "dimension": "结构性",
                    "importance": "高",
                    "recommendation": gap,
                })
        missing_recommendations.sort(
            key=lambda x: {"极高": 0, "高": 1, "中": 2, "低": 3}.get(x["importance"], 4)
        )

        # ── Template-based loop coverage (using declarative templates) ──
        template_matches: list[dict[str, Any]] = []
        dim_presence = {k: bool(v) for k, v in dim_entities.items()}
        for tmpl in self._edge_templates:
            dims = tmpl.get("dimensions", [])
            missing_t = [d for d in dims if not dim_presence.get(d)]
            status = "complete" if not missing_t else ("partial" if len(missing_t) < len(dims) else "missing")
            template_matches.append({
                "id": tmpl.get("id"),
                "name": tmpl.get("name"),
                "description": tmpl.get("description"),
                "dimensions": dims,
                "missing_dimensions": missing_t,
                "status": status,
                "pattern_type": tmpl.get("pattern_type", "neutral"),
                "linked_rules": list(tmpl.get("linked_rules", [])),
            })

        # ── Consistency rules over dimensions + raw text ──
        consistency_issues: list[dict[str, Any]] = []
        text_ctx = " ".join(raw_text_fragments)
        rule_env = {
            "text": [text_ctx],
        }
        for rule in self._consistency_rules:
            pred: Callable[[dict, dict], bool] = rule.get("predicate")  # type: ignore[assignment]
            try:
                if callable(pred) and pred(dim_presence, rule_env):
                    consistency_issues.append({
                        "id": rule.get("id"),
                        "description": rule.get("description"),
                        "message": rule.get("message"),
                        "pressure_questions": list(rule.get("pressure", [])),
                    })
            except Exception:
                continue

        return {
            "ok": True,
            "coverage_score": coverage_score,
            "covered_count": len(covered_dims),
            "total_dimensions": len(all_dims),
            "dimensions": dimensions_detail,
            "cross_links": cross_links[:10],
            "hub_entities": hub_entities[:5],
            "pattern_warnings": pattern_warnings[:5],
            "pattern_strengths": pattern_strengths[:3],
            "projected_edge_types": projected_edge_types,
            "missing_dimensions": missing_recommendations[:6],
            "template_matches": template_matches,
            "consistency_issues": consistency_issues,
            "student_graph_stats": {
                "nodes": len(student_hg.nodes) if student_hg else 0,
                "edges": len(student_hg.edges) if student_hg else 0,
            },
        }
