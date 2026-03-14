from dataclasses import dataclass
from typing import Any

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError


@dataclass
class GraphSignal:
    connected: bool
    detail: str


class GraphService:
    def __init__(self, uri: str, username: str, password: str, database: str = "") -> None:
        self.uri = uri
        self.username = username
        self.password = password
        self.database = database

    def health(self) -> GraphSignal:
        try:
            def _query(session):
                result = session.run("RETURN 'ok' AS status")
                return result.single()["status"]

            status = self._query_with_fallback(_query)
            return GraphSignal(connected=status == "ok", detail="neo4j connected")
        except Neo4jError as exc:
            return GraphSignal(connected=False, detail=f"neo4j error: {exc.code}")
        except Exception as exc:  # noqa: BLE001
            return GraphSignal(connected=False, detail=f"neo4j unavailable: {exc}")

    def _session_kwargs(self) -> dict[str, Any]:
        return {"database": self.database} if self.database else {}

    def _driver(self):
        return GraphDatabase.driver(self.uri, auth=(self.username, self.password))

    def _query_with_fallback(self, query_fn):
        """
        Try configured database first; fallback to default database when routing/db lookup is unstable.
        """
        db_candidates: list[str] = [self.database] if self.database else [""]
        if self.database:
            db_candidates.append("")

        last_exc: Exception | None = None
        for db_name in db_candidates:
            driver = self._driver()
            try:
                session_kwargs = {"database": db_name} if db_name else {}
                with driver.session(**session_kwargs) as session:
                    return query_fn(session)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
            finally:
                driver.close()
        if last_exc:
            raise last_exc
        raise RuntimeError("neo4j query failed without explicit exception")

    def teacher_dashboard(self, category: str | None = None, limit: int = 8) -> dict[str, Any]:
        try:
            def _query(session):
                total_projects = session.run("MATCH (p:Project) RETURN count(p) AS c").single()["c"]
                total_evidence = session.run("MATCH (e:Evidence) RETURN count(e) AS c").single()["c"]
                total_rules = session.run("MATCH (:Project)-[r:HITS_RULE]->(:RiskRule) RETURN count(r) AS c").single()[
                    "c"
                ]

                category_rows = list(
                    session.run(
                        """
                        MATCH (c:Category)<-[:BELONGS_TO]-(p:Project)
                        RETURN c.name AS category, count(DISTINCT p) AS projects
                        ORDER BY projects DESC
                        """
                    )
                )
                rule_rows = list(
                    session.run(
                        """
                        MATCH (p:Project)-[:HITS_RULE]->(r:RiskRule)
                        RETURN r.id AS rule, count(DISTINCT p) AS projects
                        ORDER BY projects DESC
                        LIMIT $limit
                        """,
                        limit=limit,
                    )
                )
                high_risk_rows = list(
                    session.run(
                        """
                        MATCH (p:Project)-[:BELONGS_TO]->(c:Category)
                        OPTIONAL MATCH (p)-[:HITS_RULE]->(r:RiskRule)
                        WITH p, c, count(DISTINCT r) AS risk_count
                        WHERE risk_count >= 2
                        AND ($category IS NULL OR c.name = $category)
                        RETURN p.id AS project_id,
                               p.name AS project_name,
                               c.name AS category,
                               risk_count,
                               p.confidence AS confidence
                        ORDER BY risk_count DESC, confidence ASC
                        LIMIT $limit
                        """,
                        category=category,
                        limit=limit,
                    )
                )

                return {
                "overview": {
                    "total_projects": total_projects,
                    "total_evidence": total_evidence,
                    "total_rule_hits": total_rules,
                },
                "category_distribution": [dict(r) for r in category_rows],
                "top_risk_rules": [dict(r) for r in rule_rows],
                "high_risk_projects": [dict(r) for r in high_risk_rows],
            }

            return self._query_with_fallback(_query)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"dashboard query failed: {exc}"}

    def project_evidence(self, project_id: str) -> dict[str, Any]:
        try:
            def _query(session):
                project = session.run(
                    """
                    MATCH (p:Project {id: $project_id})-[:BELONGS_TO]->(c:Category)
                    RETURN p.id AS project_id,
                           p.name AS project_name,
                           p.summary AS summary,
                           p.source_file AS source_file,
                           p.confidence AS confidence,
                           c.name AS category
                    """,
                    project_id=project_id,
                ).single()
                if not project:
                    return {"error": "project not found"}

                evidence_rows = list(
                    session.run(
                        """
                        MATCH (p:Project {id: $project_id})-[:HAS_EVIDENCE]->(e:Evidence)
                        RETURN e.id AS evidence_id,
                               e.type AS type,
                               e.quote AS quote,
                               e.source_unit AS source_unit
                        ORDER BY e.id
                        """,
                        project_id=project_id,
                    )
                )
                rubric_rows = list(
                    session.run(
                        """
                        MATCH (p:Project {id: $project_id})-[r:EVALUATED_BY]->(ri:RubricItem)
                        RETURN ri.name AS rubric_item, r.covered AS covered
                        ORDER BY ri.name
                        """,
                        project_id=project_id,
                    )
                )
                risk_rows = list(
                    session.run(
                        """
                        MATCH (p:Project {id: $project_id})-[:HITS_RULE]->(rr:RiskRule)
                        RETURN rr.id AS rule
                        ORDER BY rr.id
                        """,
                        project_id=project_id,
                    )
                )
                return {
                "project": dict(project),
                "evidence": [dict(r) for r in evidence_rows],
                "rubric_coverage": [dict(r) for r in rubric_rows],
                "risk_rules": [dict(r) for r in risk_rows],
            }

            return self._query_with_fallback(_query)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"project evidence query failed: {exc}"}

    def merge_student_entities(self, project_id: str, entities: list[dict], relationships: list[dict]) -> dict[str, Any]:
        """Write student-extracted KG entities and relationships into Neo4j via MERGE."""
        if not entities:
            return {"ok": True, "merged": 0}
        try:
            def _write(session):
                merged = 0
                for ent in entities[:20]:
                    label = str(ent.get("label", ""))[:100]
                    etype = str(ent.get("type", "concept"))[:50]
                    eid = str(ent.get("id", ""))[:50]
                    if not label:
                        continue
                    session.run(
                        """
                        MERGE (e:Entity {label: $label})
                        ON CREATE SET e.type = $etype, e.source_project = $pid, e.id = $eid
                        ON MATCH SET e.last_seen_project = $pid
                        """,
                        label=label, etype=etype, pid=project_id, eid=eid,
                    )
                    merged += 1
                for rel in relationships[:30]:
                    src = str(rel.get("source", ""))
                    tgt = str(rel.get("target", ""))
                    desc = str(rel.get("relation", "related"))[:100]
                    src_label = next((e.get("label", "") for e in entities if e.get("id") == src), src)
                    tgt_label = next((e.get("label", "") for e in entities if e.get("id") == tgt), tgt)
                    if not src_label or not tgt_label:
                        continue
                    session.run(
                        """
                        MATCH (a:Entity {label: $src}), (b:Entity {label: $tgt})
                        MERGE (a)-[r:RELATES_TO {description: $desc}]->(b)
                        ON CREATE SET r.source_project = $pid
                        """,
                        src=src_label, tgt=tgt_label, desc=desc, pid=project_id,
                    )
                return merged

            merged = self._query_with_fallback(_write)
            return {"ok": True, "merged": merged}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def find_similar_entities(self, labels: list[str], limit: int = 5) -> list[dict[str, Any]]:
        """Find entities in Neo4j that match given labels and return their relationships."""
        if not labels:
            return []
        try:
            def _query(session):
                results = []
                for label in labels[:5]:
                    rows = list(session.run(
                        """
                        MATCH (e:Entity)
                        WHERE toLower(e.label) CONTAINS toLower($label)
                        OPTIONAL MATCH (e)-[r]-(other)
                        RETURN e.label AS entity, e.type AS type, e.source_project AS project,
                               type(r) AS rel_type, other.label AS related_entity
                        LIMIT $limit
                        """,
                        label=label, limit=limit,
                    ))
                    for row in rows:
                        results.append(dict(row))
                return results

            return self._query_with_fallback(_query)
        except Exception:
            return []

    def baseline_snapshot(self, limit: int = 8) -> dict[str, Any]:
        try:
            def _query(session):
                total_projects = int(session.run("MATCH (p:Project) RETURN count(DISTINCT p) AS c").single()["c"] or 0)
                overview = session.run(
                    """
                    MATCH (p:Project)
                    OPTIONAL MATCH (p)-[:HITS_RULE]->(r:RiskRule)
                    WITH p, count(DISTINCT r) AS risk_count
                    RETURN count(p) AS project_count,
                           avg(risk_count) AS avg_rule_hits_per_project,
                           avg(CASE WHEN risk_count >= 2 THEN 1.0 ELSE 0.0 END) AS high_risk_ratio
                    """
                ).single()

                rule_rows = list(
                    session.run(
                        """
                        MATCH (p:Project)-[:HITS_RULE]->(r:RiskRule)
                        RETURN r.id AS rule, count(DISTINCT p) AS project_count
                        ORDER BY project_count DESC
                        LIMIT $limit
                        """,
                        limit=limit,
                    )
                )
                category_rows = list(
                    session.run(
                        """
                        MATCH (c:Category)<-[:BELONGS_TO]-(p:Project)
                        RETURN c.name AS category, count(DISTINCT p) AS project_count
                        ORDER BY project_count DESC
                        """
                    )
                )
                evidence_rows = list(
                    session.run(
                        """
                        MATCH (p:Project)
                        OPTIONAL MATCH (p)-[:HAS_EVIDENCE]->(e:Evidence)
                        WITH p, count(e) AS evidence_count
                        RETURN avg(evidence_count) AS avg_evidence_per_project
                        """
                    )
                )

                first_evidence = evidence_rows[0] if evidence_rows else {"avg_evidence_per_project": 0.0}
                return {
                    "project_count": int((overview or {}).get("project_count") or 0),
                    "avg_rule_hits_per_project": round(float((overview or {}).get("avg_rule_hits_per_project") or 0.0), 3),
                    "high_risk_ratio": round(float((overview or {}).get("high_risk_ratio") or 0.0), 3),
                    "avg_evidence_per_project": round(float(first_evidence.get("avg_evidence_per_project") or 0.0), 3),
                    "top_risk_rules": [
                        {
                            **dict(r),
                            "ratio": round((float(dict(r).get("project_count") or 0.0) / total_projects), 3)
                            if total_projects
                            else 0.0,
                        }
                        for r in rule_rows
                    ],
                    "category_distribution": [
                        {
                            **dict(r),
                            "ratio": round((float(dict(r).get("project_count") or 0.0) / total_projects), 3)
                            if total_projects
                            else 0.0,
                        }
                        for r in category_rows
                    ],
                }

            return self._query_with_fallback(_query)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"baseline query failed: {exc}"}
