from __future__ import annotations

"""能力子图（Ability Subgraph）：在大本体上做的“话题切片”。

设计目标：
- 每个能力子图描述一个分析视角下学生最该关注的本体概念集合，
  以及对应的 rubric 维度、超边家族、风险规则和检索关键词。
- 编排层根据当前 track_vector / project_stage_v2 / 意图选择 1~2 个子图，
  在 prompt / RAG / Neo4j 检索 / 前端展示时统一聚焦同一组节点，
  保证“同一轮里多个面板看的是一件事”。
- 子图本身只是声明式数据结构，与 Neo4j 是否可用无关；如果 Neo4j 在线，
  graph_service 可以基于它再做一次小图检索。

注意：本文件只依赖 kg_ontology 的本体节点 id，不引入运行时副作用。
"""

from dataclasses import dataclass, field
from typing import Any, Iterable

from app.services.kg_ontology import ONTOLOGY_NODES


@dataclass(frozen=True)
class AbilitySubgraph:
    id: str
    name: str
    description: str
    purpose: str
    # 本体节点 id（来自 kg_ontology），决定我们关注的概念/方法/交付物/指标/任务/风险
    ontology_nodes: tuple[str, ...]
    # 与诊断引擎对齐的 rubric 维度名（见 RUBRIC_EVIDENCE_CHAIN 的 key）
    rubric_dimensions: tuple[str, ...]
    # 超图家族关键词，用于命中超边检索
    hyperedge_families: tuple[str, ...]
    # 相关 H 系列风险规则
    related_rule_ids: tuple[str, ...]
    # 触发关键词，用于在 message/diagnosis 中粗匹配
    trigger_keywords: tuple[str, ...]
    # 本子图给 agent 的“关注点摘要”，会注入到 oriented_hint 末尾
    focus_brief: str
    # 适用阶段：idea / structured / validated / scale；空集合 = 全阶段适用
    applies_to_stage: tuple[str, ...] = field(default_factory=tuple)
    # 适用光谱端点：innov_strong / venture_strong / biz_strong / public_strong；空 = 不限
    applies_to_spectrum: tuple[str, ...] = field(default_factory=tuple)


ABILITY_SUBGRAPHS: dict[str, AbilitySubgraph] = {
    "innovation_evaluation": AbilitySubgraph(
        id="innovation_evaluation",
        name="创新评估",
        description="围绕新颖性、技术壁垒、差异化与可保护性的子图，重点判断 idea 是否真的创新。",
        purpose="评估项目创新性的真伪：是宣传语层面的差异化，还是有可验证的技术/模式护城河。",
        ontology_nodes=(
            "C_moat", "C_positioning", "C_value_proposition",
            "M_competitor_matrix", "M_mvp", "M_usability_test",
            "D_competition_map", "D_competitor_table",
            "C_challenge_tech_innovation", "C_challenge_evidence_rigor",
            "C_iplus_business_innovation",
            "P_no_competitor_claim",
        ),
        rubric_dimensions=(
            "Innovation & Differentiation",
            "Solution Feasibility",
            "Market & Competition",
        ),
        hyperedge_families=(
            "innovation", "differentiation", "moat",
            "competitor", "tech_validation", "evidence",
        ),
        related_rule_ids=("H6", "H7"),
        trigger_keywords=(
            "创新", "壁垒", "护城河", "差异化", "新颖", "原创",
            "技术领先", "首创", "专利", "独家", "独特", "novel", "innovation",
        ),
        focus_brief=(
            "创新评估子图触发：请重点检查“宣称的创新”能否被三类证据支撑——"
            "(1) 与至少 2 个直接/间接竞品的对比表；(2) 可演示/可验证的技术或体验差异；"
            "(3) 难复制性来源（数据、网络效应、专利、独占渠道、品牌、规模门槛之一）。"
            "若只有口号性差异化，请把这一点列为优先追问。"
        ),
        applies_to_spectrum=("innov_strong",),
    ),
    "business_model_construction": AbilitySubgraph(
        id="business_model_construction",
        name="商业模式构建",
        description="价值主张→渠道→收入→成本→单位经济的闭环子图，判断商业模式是否自洽。",
        purpose="把项目从“点子”推到可持续的商业闭环：确认收入来源、成本结构、获客路径与单位经济。",
        ontology_nodes=(
            "C_business_model", "C_value_proposition", "C_user_segment",
            "C_channel", "C_revenue_stream", "C_cost_structure",
            "C_growth_model", "C_kpi",
            "M_leancanvas", "M_unit_economics", "M_tam_sam_som", "M_sensitivity_analysis",
            "D_financial_model", "D_kpi_report",
            "X_cac", "X_ltv", "X_payback", "X_arpu", "X_margin", "X_runway",
            "C_iplus_tam_sam_som",
            "P_market_size_fallacy",
        ),
        rubric_dimensions=(
            "Business Model Consistency",
            "Market & Competition",
            "Financial Logic",
        ),
        hyperedge_families=(
            "business_model", "revenue_stream", "cost_structure",
            "unit_economics", "channel", "growth", "market_size",
        ),
        related_rule_ids=("H1", "H2", "H3", "H4", "H8", "H9"),
        trigger_keywords=(
            "商业模式", "盈利", "收入", "成本", "客单价", "复购", "CAC", "LTV",
            "客户生命周期", "渠道", "销售", "定价", "市场规模", "TAM", "SAM",
            "盈亏平衡", "现金流", "可持续",
        ),
        focus_brief=(
            "商业模式构建子图触发：请按“目标客群 → 价值主张 → 渠道 → 收入 → 成本 → 单位经济”"
            "顺序逐项检查闭环是否自洽：是否能给出一个可量化的 LTV/CAC 假设来源；"
            "渠道是否真能触达目标客群；收入与成本结构是否对应同一类用户。"
            "若涉及公益侧重，请同时讨论补贴/资助渠道与“可及性 vs 可持续”的取舍。"
        ),
        applies_to_spectrum=("venture_strong", "biz_strong"),
    ),
    "simulated_roadshow": AbilitySubgraph(
        id="simulated_roadshow",
        name="模拟路演与压力测试",
        description="评审视角的子图：路演结构、表达逻辑、关键质询与现场抗压。",
        purpose="模拟评委视角，对项目做结构化质询：找出叙事/数据/逻辑层面最容易被打分扣分的薄弱处。",
        ontology_nodes=(
            "C_rubric_dimension_presentation", "C_rubric_dimension_evidence",
            "C_rubric_dimension_business_model", "C_rubric_dimension_risk",
            "M_storytelling", "M_risk_workshop", "M_sensitivity_analysis",
            "D_pitch_deck", "D_pitch_template_competition",
            "D_rubric_sheet",
            "C_competition_rule_internet_plus",
            "C_competition_rule_challenge_cup",
            "C_competition_rule_dachuang",
            "P_weak_user_evidence",
        ),
        rubric_dimensions=(
            "Presentation Quality",
            "Innovation & Differentiation",
            "Financial Logic",
            "Team & Execution",
        ),
        hyperedge_families=(
            "presentation", "qna", "judge_focus",
            "evidence", "risk_control",
        ),
        related_rule_ids=("H10", "H12", "H14", "H15"),
        trigger_keywords=(
            "路演", "答辩", "评委", "提问", "Q&A", "现场",
            "讲故事", "演示", "pitch", "压测", "压力测试",
            "如果评委问", "答辩问题",
        ),
        focus_brief=(
            "模拟路演子图触发：请按评委视角生成 3-5 个最尖锐的质询，并指出每个问题对应的"
            "证据缺口（用户证据 / 财务模型 / 竞品对比 / 风险预案 / 团队履历）。每条质询要"
            "指明“答得好 vs 答得砸”的分界标准，方便学生现场补料。"
        ),
        applies_to_stage=("validated", "scale"),
    ),
}


# ─────────────────────────────────────────────────────────────────────
# 选择 / 检索接口
# ─────────────────────────────────────────────────────────────────────


def _spectrum_keys_from_track(track_vector: dict[str, Any] | None) -> set[str]:
    """把 track_vector 转成离散端点集合，便于和 applies_to_spectrum 对比。"""
    keys: set[str] = set()
    if not isinstance(track_vector, dict):
        return keys
    iv = float(track_vector.get("innov_venture") or 0.0)
    bp = float(track_vector.get("biz_public") or 0.0)
    if iv <= -0.4:
        keys.add("innov_strong")
    elif iv <= -0.15:
        keys.add("innov_light")
    if iv >= 0.4:
        keys.add("venture_strong")
    elif iv >= 0.15:
        keys.add("venture_light")
    if bp <= -0.4:
        keys.add("biz_strong")
    elif bp <= -0.15:
        keys.add("biz_light")
    if bp >= 0.4:
        keys.add("public_strong")
    elif bp >= 0.15:
        keys.add("public_light")
    return keys


def _stage_match(sub: AbilitySubgraph, stage: str) -> bool:
    if not sub.applies_to_stage:
        return True
    return stage in sub.applies_to_stage


def _spectrum_match(sub: AbilitySubgraph, spectrum_keys: set[str]) -> bool:
    if not sub.applies_to_spectrum:
        return True
    return any(k in spectrum_keys for k in sub.applies_to_spectrum)


def select_ability_subgraphs(
    *,
    message: str = "",
    diagnosis: dict[str, Any] | None = None,
    track_vector: dict[str, Any] | None = None,
    project_stage: str = "structured",
    intent: str = "general_chat",
    max_results: int = 2,
) -> list[dict[str, Any]]:
    """根据本轮信号从 ABILITY_SUBGRAPHS 中选 0~max_results 个能力子图。

    返回的每个 dict 包含：
      - id / name / description / purpose / focus_brief
      - ontology_nodes（带 label）
      - rubric_dimensions
      - hyperedge_families / related_rule_ids
      - score / matched_signals（解释为什么命中）
    """
    msg = (message or "").lower()
    diag = diagnosis if isinstance(diagnosis, dict) else {}
    spectrum_keys = _spectrum_keys_from_track(track_vector)

    triggered_rule_ids: set[str] = set()
    for r in (diag.get("triggered_rules") or []):
        if isinstance(r, dict) and r.get("id"):
            triggered_rule_ids.add(str(r["id"]))

    intent_focus_map = {
        "competition_evaluation": ("simulated_roadshow",),
        "feedback_request": ("simulated_roadshow",),
        "project_diagnosis": ("business_model_construction",),
        "idea_brainstorm": ("innovation_evaluation",),
        "learning_concept": (),
    }
    intent_hint = set(intent_focus_map.get(intent, ()))

    scored: list[tuple[float, dict[str, Any]]] = []
    for sub in ABILITY_SUBGRAPHS.values():
        if not _stage_match(sub, project_stage):
            continue
        signals: list[str] = []
        score = 0.0

        # 关键词
        kw_hits = [kw for kw in sub.trigger_keywords if kw.lower() in msg]
        if kw_hits:
            score += min(2.5, 0.6 * len(kw_hits))
            signals.append(f"关键词命中: {', '.join(kw_hits[:3])}")

        # 风险规则
        rule_overlap = triggered_rule_ids & set(sub.related_rule_ids)
        if rule_overlap:
            score += 1.4 * len(rule_overlap)
            signals.append(f"风险规则: {', '.join(sorted(rule_overlap))}")

        # 光谱端点
        if _spectrum_match(sub, spectrum_keys) and sub.applies_to_spectrum:
            score += 1.2
            signals.append(f"光谱端点: {', '.join(sorted(spectrum_keys & set(sub.applies_to_spectrum)))}")

        # 阶段端点
        if sub.applies_to_stage and project_stage in sub.applies_to_stage:
            score += 0.8
            signals.append(f"项目阶段: {project_stage}")

        # 意图提示
        if sub.id in intent_hint:
            score += 1.0
            signals.append(f"意图: {intent}")

        if score <= 0:
            continue

        scored.append((score, _serialize_subgraph(sub, score=round(score, 3), signals=signals)))

    if not scored:
        # 兜底：所有阶段都至少给商业模式构建一个低权重的兜底，否则前端会出现“空子图”
        sub = ABILITY_SUBGRAPHS["business_model_construction"]
        scored.append((0.5, _serialize_subgraph(sub, score=0.5, signals=["默认兜底（无明确触发）"])))

    scored.sort(key=lambda kv: kv[0], reverse=True)
    return [item for _, item in scored[:max_results]]


def _serialize_subgraph(sub: AbilitySubgraph, *, score: float, signals: list[str]) -> dict[str, Any]:
    nodes_payload = []
    for nid in sub.ontology_nodes:
        node = ONTOLOGY_NODES.get(nid)
        if not node:
            continue
        nodes_payload.append(
            {
                "id": node.id,
                "kind": node.kind,
                "label": node.label,
                "description": node.description,
            }
        )
    return {
        "id": sub.id,
        "name": sub.name,
        "description": sub.description,
        "purpose": sub.purpose,
        "focus_brief": sub.focus_brief,
        "ontology_nodes": nodes_payload,
        "rubric_dimensions": list(sub.rubric_dimensions),
        "hyperedge_families": list(sub.hyperedge_families),
        "related_rule_ids": list(sub.related_rule_ids),
        "applies_to_stage": list(sub.applies_to_stage),
        "applies_to_spectrum": list(sub.applies_to_spectrum),
        "score": score,
        "matched_signals": signals,
    }


def collect_subgraph_node_ids(subgraphs: Iterable[dict[str, Any]]) -> list[str]:
    """合并多个能力子图涉及的本体节点 id（去重，保持顺序）。"""
    seen: dict[str, None] = {}
    for sg in subgraphs or []:
        for node in sg.get("ontology_nodes") or []:
            nid = node.get("id") if isinstance(node, dict) else None
            if isinstance(nid, str) and nid not in seen:
                seen[nid] = None
    return list(seen.keys())


def collect_subgraph_focus_briefs(subgraphs: Iterable[dict[str, Any]]) -> str:
    """把多个子图的 focus_brief 合并成一段，用于注入 prompt。"""
    parts: list[str] = []
    for sg in subgraphs or []:
        brief = str(sg.get("focus_brief") or "").strip()
        if brief:
            parts.append(f"【{sg.get('name','子图')}】{brief}")
    return "\n".join(parts)
