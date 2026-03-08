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
            driver = GraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password),
            )
            with driver.session(**self._session_kwargs()) as session:
                result = session.run("RETURN 'ok' AS status")
                status = result.single()["status"]
            driver.close()
            return GraphSignal(connected=status == "ok", detail="neo4j connected")
        except Neo4jError as exc:
            return GraphSignal(connected=False, detail=f"neo4j error: {exc.code}")
        except Exception as exc:  # noqa: BLE001
            return GraphSignal(connected=False, detail=f"neo4j unavailable: {exc}")

    def _session_kwargs(self) -> dict[str, Any]:
        return {"database": self.database} if self.database else {}

    def teacher_dashboard(self, category: str | None = None, limit: int = 8) -> dict[str, Any]:
        try:
            driver = GraphDatabase.driver(self.uri, auth=(self.username, self.password))
            with driver.session(**self._session_kwargs()) as session:
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

            driver.close()
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
        except Exception as exc:  # noqa: BLE001
            return {"error": f"dashboard query failed: {exc}"}

    def project_evidence(self, project_id: str) -> dict[str, Any]:
        try:
            driver = GraphDatabase.driver(self.uri, auth=(self.username, self.password))
            with driver.session(**self._session_kwargs()) as session:
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
            driver.close()
            return {
                "project": dict(project),
                "evidence": [dict(r) for r in evidence_rows],
                "rubric_coverage": [dict(r) for r in rubric_rows],
                "risk_rules": [dict(r) for r in risk_rows],
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": f"project evidence query failed: {exc}"}

    def baseline_snapshot(self, limit: int = 8) -> dict[str, Any]:
        try:
            driver = GraphDatabase.driver(self.uri, auth=(self.username, self.password))
            with driver.session(**self._session_kwargs()) as session:
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

            driver.close()
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
        except Exception as exc:  # noqa: BLE001
            return {"error": f"baseline query failed: {exc}"}
