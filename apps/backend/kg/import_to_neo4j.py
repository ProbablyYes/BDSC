from __future__ import annotations

import json
from pathlib import Path

from neo4j import GraphDatabase

from app.config import settings


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


def upsert_case(tx, case: dict) -> None:
    source = case["source"]
    profile = case["project_profile"]
    risk_flags = to_list(case.get("risk_flags", []))

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

    for risk in risk_flags:
        tx.run(
            """
            MATCH (p:Project {id: $case_id})
            MERGE (r:RiskRule {id: $risk_id})
            MERGE (p)-[:HITS_RULE]->(r)
            """,
            case_id=case["case_id"],
            risk_id=risk,
        )

    for market in to_list(profile.get("market_analysis", []))[:10]:
        tx.run("MERGE (:Market {name: $name})", name=market)

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
        tx.run(
            """
            MATCH (p:Project {id: $case_id})
            MERGE (r:RubricItem {name: $rubric_name})
            MERGE (p)-[rel:EVALUATED_BY]->(r)
            SET rel.covered = $covered
            """,
            case_id=case["case_id"],
            rubric_name=rubric_name,
            covered=bool(item.get("covered", False)),
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
        for case in cases:
            session.execute_write(upsert_case, case)
    driver.close()
    print(f"imported cases: {len(cases)}")


if __name__ == "__main__":
    main()
