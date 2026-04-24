from __future__ import annotations

"""运行时本体接入（Runtime Ontology Grounding）。

把 ontology 真正用起来要解决两件事：
1. **覆盖映射**：本轮诊断/超图涉及哪些本体节点，哪些被对话覆盖到了？
2. **可执行约束**：用一段简短的 prompt 片段告诉 agent
   “请围绕这些概念/方法/交付物生成回答，并指出还缺哪些证据/任务”。

这个模块只做摘要计算，不调 LLM、不依赖 Neo4j。
"""

from typing import Any

from app.services.kg_ontology import ONTOLOGY_NODES, serialize_node
from app.services.ontology_resolver import get_resolver


# 把诊断里出现的 entity type 粗分到对应的本体概念，供"覆盖映射"使用。
_ENTITY_TYPE_TO_CONCEPT: dict[str, str] = {
    "stakeholder": "C_user_segment",
    "pain_point": "C_problem",
    "solution": "C_solution",
    "innovation": "C_moat",
    "technology": "C_solution",
    "market": "C_market_size",
    "competitor": "C_competition",
    "resource": "C_team",
    "business_model": "C_business_model",
    "execution_step": "C_roadmap",
    "risk_control": "C_risk_control",
    "team": "C_team",
    "evidence": "C_rubric_dimension_evidence",
    "channel": "C_channel",
    "risk": "C_risk_control",
}


def _node_payload(nid: str) -> dict[str, Any] | None:
    node = ONTOLOGY_NODES.get(nid)
    if not node:
        return None
    # 序列化包含 aliases / parent / stage_expected / probing_questions
    return serialize_node(node)


def build_ontology_grounding(
    *,
    diagnosis: dict[str, Any] | None,
    kg_analysis: dict[str, Any] | None,
    ability_subgraphs: list[dict[str, Any]] | None,
    user_message: str | None = None,
    stage_v2: str | None = None,
) -> dict[str, Any]:
    """汇总本轮“本体覆盖 vs 缺失”。

    返回结构：
      {
        "covered_concepts": [...nodes],     # 已经在 KG/对话里出现
        "missing_concepts": [...nodes],     # 子图要求、但本轮 KG 里没看到
        "evidence_required":   [...nodes],  # rubric.evidence_chain 平铺去重
        "recommended_tasks":   [...nodes],  # 风险规则推荐的 task 节点
        "related_pitfalls":    [...nodes],  # 子图涉及的 pitfall 节点（提醒 agent 不要犯）
        "concept_index_by_kind": {
            "concept": [...], "method": [...], "deliverable": [...], "metric": [...],
            "task": [...], "pitfall": [...], "evidence": [...],
        },
        "summary_text": "已覆盖 X 个概念（…）。缺失 Y 个（…）。建议补齐：…",
      }
    """
    diag = diagnosis if isinstance(diagnosis, dict) else {}
    kg = kg_analysis if isinstance(kg_analysis, dict) else {}
    subs = ability_subgraphs if isinstance(ability_subgraphs, list) else []
    resolver = get_resolver()

    # ── 1. 已覆盖概念 ──
    # 来源 a) KG entities（type → concept 映射）
    # 来源 b) triggered_rules.ontology_nodes 里的 concept（规则因关键字命中而触发，
    #         意味着对话里实际出现了相关概念）。这条路径让我们在 KG 不可用时仍能更新覆盖率。
    # 来源 c) OntologyResolver.normalize(user_message)：直接用别名/口语词在原文里匹配，
    #         哪怕 KG / 规则都没启动也能拿到覆盖。这是把 ontology 真正用起来的关键路径。
    covered_ids: dict[str, None] = {}

    # 先做 a) c)，然后用 resolver.covered 上推一次祖先（子命中=父覆盖）
    direct_hits: list[str] = []

    for ent in (kg.get("entities") or []):
        if not isinstance(ent, dict):
            continue
        etype = str(ent.get("type") or "").strip().lower()
        cid = _ENTITY_TYPE_TO_CONCEPT.get(etype)
        if cid:
            direct_hits.append(cid)
        # KG 实体的 label/name 也跑一遍 normalize，捕获更细粒度的概念命中
        for key in ("label", "name", "title"):
            txt = ent.get(key)
            if isinstance(txt, str) and txt.strip():
                direct_hits.extend(resolver.normalize(txt))

    if user_message:
        direct_hits.extend(resolver.normalize(user_message))

    for r in (diag.get("triggered_rules") or []):
        if not isinstance(r, dict):
            continue
        for node in (r.get("ontology_nodes") or []):
            if not isinstance(node, dict):
                continue
            nid = node.get("id")
            if isinstance(nid, str) and node.get("kind") == "concept":
                direct_hits.append(nid)

    # 上推祖先（子命中→父也覆盖），这是本体推理式覆盖的核心
    for nid in resolver.covered(direct_hits):
        covered_ids[nid] = None

    # ── 2. 子图期望覆盖的概念集合 ──
    expected_ids: dict[str, None] = {}
    pitfall_ids: dict[str, None] = {}
    for sg in subs:
        for node in (sg.get("ontology_nodes") or []):
            if not isinstance(node, dict):
                continue
            nid = node.get("id")
            kind = node.get("kind")
            if not isinstance(nid, str):
                continue
            if kind == "pitfall":
                pitfall_ids[nid] = None
            elif kind == "concept":
                expected_ids[nid] = None

    missing_ids = [nid for nid in expected_ids if nid not in covered_ids]

    # ── 3. rubric 要求的证据节点 ──
    evidence_required: dict[str, None] = {}
    for row in (diag.get("rubric") or []):
        if not isinstance(row, dict):
            continue
        for node in (row.get("evidence_chain") or []):
            if isinstance(node, dict) and isinstance(node.get("id"), str):
                evidence_required[node["id"]] = None

    # ── 4. 风险规则推荐的任务节点 + 关联本体 ──
    recommended_tasks: dict[str, None] = {}
    for r in (diag.get("triggered_rules") or []):
        if not isinstance(r, dict):
            continue
        for node in (r.get("ontology_tasks") or []):
            if isinstance(node, dict) and isinstance(node.get("id"), str):
                recommended_tasks[node["id"]] = None
        # 风险关联本体也算“需要重点关注”
        for node in (r.get("ontology_nodes") or []):
            if isinstance(node, dict) and isinstance(node.get("id"), str):
                expected_ids[node["id"]] = None

    # ── 5. 拼装返回结构 ──
    def _resolve(ids: list[str] | dict[str, None]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for nid in ids:
            if nid in seen:
                continue
            seen.add(nid)
            payload = _node_payload(nid)
            if payload:
                out.append(payload)
        return out

    covered_payload = _resolve(list(covered_ids.keys()))
    missing_payload = _resolve(missing_ids)
    evidence_payload = _resolve(list(evidence_required.keys()))
    tasks_payload = _resolve(list(recommended_tasks.keys()))
    pitfalls_payload = _resolve(list(pitfall_ids.keys()))

    # 按 kind 重新索引
    concept_index_by_kind: dict[str, list[dict[str, Any]]] = {
        "concept": [],
        "method": [],
        "deliverable": [],
        "metric": [],
        "task": [],
        "pitfall": [],
        "evidence": [],
    }
    all_nodes = covered_payload + missing_payload + evidence_payload + tasks_payload + pitfalls_payload
    seen_nodes: set[str] = set()
    for node in all_nodes:
        if node["id"] in seen_nodes:
            continue
        seen_nodes.add(node["id"])
        concept_index_by_kind.setdefault(node["kind"], []).append(node)

    # 摘要文本（注入到 prompt）
    def _labels(payload: list[dict[str, Any]], limit: int = 5) -> str:
        return ", ".join(n.get("label", "") for n in payload[:limit] if n.get("label"))

    summary_parts: list[str] = []
    if covered_payload:
        summary_parts.append(f"已覆盖概念({len(covered_payload)}): {_labels(covered_payload)}")
    if missing_payload:
        summary_parts.append(f"未覆盖但子图要求({len(missing_payload)}): {_labels(missing_payload)}")
    if evidence_payload:
        summary_parts.append(f"评分需要的证据/方法({len(evidence_payload)}): {_labels(evidence_payload, 6)}")
    if tasks_payload:
        summary_parts.append(f"建议执行任务({len(tasks_payload)}): {_labels(tasks_payload, 4)}")
    if pitfalls_payload:
        summary_parts.append(f"避免落入误区({len(pitfalls_payload)}): {_labels(pitfalls_payload, 3)}")

    # ── 6. Stage 缺口（按当前 project_stage_v2 期望应覆盖、但还没覆盖的 concept） ──
    stage_gap_payload: list[dict[str, Any]] = []
    stage_probing: list[str] = []
    if stage_v2:
        gap_nodes = resolver.stage_gap(stage_v2, list(covered_ids.keys()), kinds=["concept"])
        for node in gap_nodes[:6]:
            payload = serialize_node(node)
            stage_gap_payload.append(payload)
            for q in node.probing_questions[:2]:
                if q and q not in stage_probing:
                    stage_probing.append(q)

    if stage_gap_payload:
        labels = ", ".join(n.get("label", "") for n in stage_gap_payload[:5] if n.get("label"))
        summary_parts.append(f"本阶段({stage_v2})期望但未覆盖({len(stage_gap_payload)}): {labels}")

    summary_text = " | ".join(summary_parts)

    return {
        "covered_concepts": covered_payload,
        "missing_concepts": missing_payload,
        "evidence_required": evidence_payload,
        "recommended_tasks": tasks_payload,
        "related_pitfalls": pitfalls_payload,
        "concept_index_by_kind": concept_index_by_kind,
        "coverage_ratio": (
            round(len(covered_payload) / max(1, len(covered_payload) + len(missing_payload)), 3)
            if (covered_payload or missing_payload) else 0.0
        ),
        "summary_text": summary_text,
        "stage": stage_v2 or "",
        "stage_gap_concepts": stage_gap_payload,
        "stage_probing_questions": stage_probing,
    }


def render_ontology_prompt(grounding: dict[str, Any] | None, *, role: str = "agent") -> str:
    """把本体覆盖摘要渲染成一段 prompt 片段，可以注入到任意 agent 的 system prompt。"""
    if not isinstance(grounding, dict) or not grounding.get("summary_text"):
        return ""
    parts: list[str] = []
    parts.append("### 本轮本体接入（请在你的回答里显式回到这些概念）")
    parts.append(str(grounding.get("summary_text") or "")[:600])

    missing = grounding.get("missing_concepts") or []
    if missing:
        labels = ", ".join((n.get("label") or "") for n in missing[:5] if isinstance(n, dict))
        parts.append(
            f"- **请重点提示学生补齐**：{labels}（这些概念在你的回答里至少要被点名一次，并指出补齐方法）。"
        )

    tasks = grounding.get("recommended_tasks") or []
    if tasks:
        labels = " / ".join((t.get("label") or "") for t in tasks[:3] if isinstance(t, dict))
        parts.append(f"- **可执行任务建议**：{labels}（如果与你的角色相关，请把它写成具体的下一步行动）。")

    pitfalls = grounding.get("related_pitfalls") or []
    if pitfalls and role in {"critic", "advisor", "grader"}:
        labels = " / ".join((p.get("label") or "") for p in pitfalls[:3] if isinstance(p, dict))
        parts.append(f"- **典型误区警示**：{labels}（学生若已经踩到，请在评分/建议中明确指出）。")

    # Stage-aware 追问素材：critic / advisor 角色优先承担
    stage_probing = grounding.get("stage_probing_questions") or []
    if stage_probing and role in {"critic", "advisor"}:
        bullets = "\n  ".join(f"- {q}" for q in stage_probing[:3])
        parts.append(
            f"- **本阶段({grounding.get('stage') or '?'})追问建议**（择1-2条自然融入回答）：\n  {bullets}"
        )

    return "\n".join(parts)
