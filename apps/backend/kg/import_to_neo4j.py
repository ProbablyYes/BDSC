from __future__ import annotations

"""Offline helper script: import structured cases into Neo4j.

The online诊断与反馈链路已经完全基于 HyperNetX + JSON 完成：
- 文件抽取: HypergraphDocument / ingest.build_metadata / ingest.extract_case_struct
- 知识库 + 超图诊断: kg_ontology / diagnosis_engine / hypergraph_service

本脚本仅作为可选的运维工具，将 `graph_seed/case_structured` 中的案例
导入 Neo4j 进行离线可视化和统计分析，不再是核心依赖。
"""

import json
from pathlib import Path

from neo4j import GraphDatabase

from app.config import settings
from app.services.diagnosis_engine import RULES, RUBRICS
from app.services.kg_ontology import (
    ONTOLOGY_NODES,
    RUBRIC_EVIDENCE_CHAIN,
    RULE_ONTOLOGY_MAP,
    RULE_TASK_MAP,
)


def load_cases() -> list[dict]:
    structured_dir = settings.data_root / "graph_seed" / "case_structured"
    manifest_path = structured_dir / "manifest.json"
    if not manifest_path.exists():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = []
    for item in manifest:
        out = structured_dir / item["output_file"]
        if not out.exists():
            continue
        cases.append(json.loads(out.read_text(encoding="utf-8")))
    return cases


def to_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


# Static alignment from instance-level nodes to high-level ontology concepts.
ONTOLOGY_ANCHORS: dict[str, list[str]] = {
    # 谁是项目直接服务的对象 → 目标用户细分概念
    "Stakeholder": ["C_user_segment"],
    # 痛点文本 → 问题定义概念
    "PainPoint": ["C_problem"],
    # 方案要点 → 解决方案概念
    "Solution": ["C_solution"],
    # 商业模式要点 → 商业模式概念
    "BusinessModelAspect": ["C_business_model"],
    # 市场分析要点 → 市场规模与竞争格局概念
    "Market": ["C_market_size", "C_competition"],
    # 执行计划 → 里程碑/路线图概念
    "ExecutionStep": ["C_roadmap"],
    # 风险控制要点 → 风险与合规概念
    "RiskControlPoint": ["C_risk_control"],
}


# Static meta-information for RiskRule and RubricItem,
# aligned with diagnosis_engine defaults.
RISK_RULE_META: dict[str, dict[str, str]] = {
    str(row.get("id")): {
        "name": str(row.get("name", "")),
        "severity": str(row.get("severity", "")),
    }
    for row in RULES
    if row.get("id")
}

RUBRIC_META: dict[str, dict[str, float]] = {
    str(row.get("item")): {"weight": float(row.get("weight", 0.0))}
    for row in RUBRICS
    if row.get("item")
}


def ensure_ontology(tx) -> None:
    """Materialize OntologyNode definitions into Neo4j.

    每次导入前调用一次，确保所有本体节点都在图中，便于后续“实例→概念”对齐。
    """
    for node in ONTOLOGY_NODES.values():
        tx.run(
            """
            MERGE (o:OntologyNode {id: $id})
            SET o.kind = $kind,
                o.label = $label,
                o.description = $description
            """,
            id=node.id,
            kind=node.kind,
            label=node.label,
            description=node.description,
        )


def upsert_case(tx, case: dict) -> None:
    source = case["source"]
    profile = case["project_profile"]
    risk_flags = to_list(case.get("risk_flags", []))

    # Optional per-case LLM details (rubric scores, rule evidence/reasons).
    rubric_details_index: dict[str, dict] = {}
    for row in case.get("rubric_items_detail", []) or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("item", "")).strip()
        if not name:
            continue
        rubric_details_index[name] = row

    risk_details_index: dict[str, dict] = {}
    for row in case.get("risk_rule_details", []) or []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id", "")).strip()
        if not rid:
            continue
        risk_details_index[rid] = row

    tx.run(
        """
        MERGE (p:Project {id: $case_id})
        SET p.name = $project_name,
            p.summary = $summary,
            p.source_file = $source_file,
            p.category = $category,
            p.confidence = $confidence
        MERGE (c:Category {name: $category})
        MERGE (p)-[:BELONGS_TO]->(c)
        """,
        case_id=case["case_id"],
        project_name=profile.get("project_name", case["case_id"]),
        summary=case.get("summary", ""),
        source_file=source.get("file_path", ""),
        category=source.get("category", "未分类"),
        confidence=float(case.get("confidence", 0.5)),
    )

    # Core project-level semantics
    for user in to_list(profile.get("target_users", []))[:10]:
        tx.run(
            """
            MATCH (p:Project {id: $case_id})
            MERGE (u:Stakeholder {name: $name})
            MERGE (p)-[:HAS_TARGET_USER]->(u)
            """,
            case_id=case["case_id"],
            name=user,
        )

    for pain in to_list(profile.get("pain_points", []))[:10]:
        tx.run(
            """
            MATCH (p:Project {id: $case_id})
            MERGE (n:PainPoint {name: $name})
            MERGE (p)-[:HAS_PAIN]->(n)
            """,
            case_id=case["case_id"],
            name=pain,
        )

    for solution in to_list(profile.get("solution", []))[:10]:
        tx.run(
            """
            MATCH (p:Project {id: $case_id})
            MERGE (n:Solution {name: $name})
            MERGE (p)-[:HAS_SOLUTION]->(n)
            """,
            case_id=case["case_id"],
            name=solution,
        )

    for innovation in to_list(profile.get("innovation_points", []))[:10]:
        tx.run(
            """
            MATCH (p:Project {id: $case_id})
            MERGE (i:InnovationPoint {name: $name})
            MERGE (p)-[:HAS_INNOVATION]->(i)
            """,
            case_id=case["case_id"],
            name=innovation,
        )

    for bm in to_list(profile.get("business_model", []))[:10]:
        tx.run(
            """
            MATCH (p:Project {id: $case_id})
            MERGE (b:BusinessModelAspect {name: $name})
            MERGE (p)-[:HAS_BUSINESS_MODEL]->(b)
            """,
            case_id=case["case_id"],
            name=bm,
        )

    for risk in risk_flags:
        meta = RISK_RULE_META.get(risk, {})
        detail = risk_details_index.get(risk, {})
        tx.run(
            """
            MATCH (p:Project {id: $case_id})
            MERGE (r:RiskRule {id: $risk_id})
            SET r.name = coalesce($risk_name, r.name),
                r.severity = coalesce($risk_severity, r.severity)
            MERGE (p)-[rel:HITS_RULE]->(r)
            SET rel.triggered = true,
                rel.severity = coalesce($rel_severity, rel.severity),
                rel.evidence = coalesce($rel_evidence, rel.evidence),
                rel.reason = coalesce($rel_reason, rel.reason)
            """,
            case_id=case["case_id"],
            risk_id=risk,
            risk_name=meta.get("name"),
            risk_severity=meta.get("severity"),
            rel_severity=detail.get("severity"),
            rel_evidence=detail.get("evidence"),
            rel_reason=detail.get("reason"),
        )

        # Align RiskRule with ontology concepts (what this rule is about).
        for ont_id in RULE_ONTOLOGY_MAP.get(risk, []):
            tx.run(
                """
                MATCH (r:RiskRule {id: $risk_id})
                MATCH (o:OntologyNode {id: $ont_id})
                MERGE (r)-[:TARGETS_CONCEPT]->(o)
                """,
                risk_id=risk,
                ont_id=ont_id,
            )

        # Align RiskRule with recommended learning tasks.
        for task_id in RULE_TASK_MAP.get(risk, []):
            tx.run(
                """
                MATCH (r:RiskRule {id: $risk_id})
                MATCH (t:OntologyNode {id: $task_id})
                MERGE (r)-[:RECOMMENDS_TASK]->(t)
                """,
                risk_id=risk,
                task_id=task_id,
            )

    for market in to_list(profile.get("market_analysis", []))[:10]:
        tx.run(
            """
            MATCH (p:Project {id: $case_id})
            MERGE (m:Market {name: $name})
            MERGE (p)-[:HAS_MARKET_ANALYSIS]->(m)
            """,
            case_id=case["case_id"],
            name=market,
        )

    for step in to_list(profile.get("execution_plan", []))[:10]:
        tx.run(
            """
            MATCH (p:Project {id: $case_id})
            MERGE (e:ExecutionStep {name: $name})
            MERGE (p)-[:HAS_EXECUTION_STEP]->(e)
            """,
            case_id=case["case_id"],
            name=step,
        )

    for rc in to_list(profile.get("risk_control", []))[:10]:
        tx.run(
            """
            MATCH (p:Project {id: $case_id})
            MERGE (r:RiskControlPoint {name: $name})
            MERGE (p)-[:HAS_RISK_CONTROL]->(r)
            """,
            case_id=case["case_id"],
            name=rc,
        )

    for item in case.get("evidence", []):
        if not isinstance(item, dict):
            continue
        evidence_id = str(item.get("id", "")).strip()
        if not evidence_id:
            continue
        tx.run(
            """
            MATCH (p:Project {id: $case_id})
            MERGE (e:Evidence {id: $evidence_id})
            SET e.type = $etype,
                e.quote = $quote,
                e.source_unit = $source_unit
            MERGE (p)-[:HAS_EVIDENCE]->(e)
            """,
            case_id=case["case_id"],
            evidence_id=evidence_id,
            etype=str(item.get("type", "")),
            quote=str(item.get("quote", "")),
            source_unit=str(item.get("source_unit", "")),
        )

    for item in case.get("rubric_coverage", []):
        if not isinstance(item, dict):
            continue
        rubric_name = str(item.get("rubric_item", "")).strip()
        if not rubric_name:
            continue
        meta = RUBRIC_META.get(rubric_name, {})
        covered = bool(item.get("covered", False))
        detail = rubric_details_index.get(rubric_name, {})

        tx.run(
            """
            MATCH (p:Project {id: $case_id})
            MERGE (r:RubricItem {name: $rubric_name})
            SET r.weight = coalesce($weight, r.weight)
            MERGE (p)-[rel:EVALUATED_BY]->(r)
            SET rel.covered = $covered,
                rel.score = coalesce($score, rel.score),
                rel.reason = coalesce($reason, rel.reason)
            """,
            case_id=case["case_id"],
            rubric_name=rubric_name,
            covered=covered,
            weight=meta.get("weight"),
            score=detail.get("score"),
            reason=detail.get("reason"),
        )

        # Link rubric dimension to its ontology-backed evidence chain.
        for ont_id in RUBRIC_EVIDENCE_CHAIN.get(rubric_name, []):
            tx.run(
                """
                MATCH (r:RubricItem {name: $rubric_name})
                MATCH (o:OntologyNode {id: $ont_id})
                MERGE (r)-[:REQUIRES_EVIDENCE_FROM]->(o)
                """,
                rubric_name=rubric_name,
                ont_id=ont_id,
            )

    # Align instance-level nodes in this project to ontology concepts.
    for label, ont_ids in ONTOLOGY_ANCHORS.items():
        for ont_id in ont_ids:
            tx.run(
                f"""
                MATCH (p:Project {{id: $case_id}})-[]->(n:{label})
                MATCH (o:OntologyNode {{id: $ont_id}})
                MERGE (n)-[:INSTANCE_OF]->(o)
                """,
                case_id=case["case_id"],
                ont_id=ont_id,
            )

    # Contextual metadata: education level / award level
    edu_level = str(source.get("education_level", "")).strip()
    if edu_level and edu_level.lower() != "unknown":
        tx.run(
            """
            MATCH (p:Project {id: $case_id})
            MERGE (e:EducationLevel {name: $name})
            MERGE (p)-[:AT_EDU_LEVEL]->(e)
            """,
            case_id=case["case_id"],
            name=edu_level,
        )

    award_level = str(source.get("award_level", "")).strip()
    if award_level:
        tx.run(
            """
            MATCH (p:Project {id: $case_id})
            MERGE (a:AwardLevel {name: $name})
            MERGE (p)-[:HAS_AWARD_LEVEL]->(a)
            """,
            case_id=case["case_id"],
            name=award_level,
        )


def main() -> None:
    cases = load_cases()
    if not cases:
        print("no cases found, run ingest pipeline first.")
        return

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
    )
    session_kwargs = {"database": settings.neo4j_database} if settings.neo4j_database else {}
    with driver.session(**session_kwargs) as session:
        # 先确保本体节点已写入图中
        session.execute_write(ensure_ontology)
        for case in cases:
            session.execute_write(upsert_case, case)
    driver.close()
    print(f"imported cases: {len(cases)}")


if __name__ == "__main__":
    main()
