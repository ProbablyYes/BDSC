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

    def search_nodes(self, keywords: list[str], limit_per_keyword: int = 3) -> list[dict[str, Any]]:
        """Best-effort generic node retrieval for tutor grounding/debug logs."""
        if not keywords:
            return []
        try:
            def _query(session):
                results: list[dict[str, Any]] = []
                seen: set[str] = set()
                for keyword in keywords[:4]:
                    rows = list(
                        session.run(
                            """
                            MATCH (n)
                            WITH n, [k IN keys(n) WHERE toLower(toString(n[k])) CONTAINS toLower($keyword)] AS matched_keys
                            WHERE size(matched_keys) > 0
                            RETURN labels(n) AS labels, properties(n) AS props, matched_keys
                            LIMIT $limit
                            """,
                            keyword=keyword,
                            limit=limit_per_keyword,
                        )
                    )
                    for row in rows:
                        labels = list(row.get("labels") or [])
                        props = dict(row.get("props") or {})
                        node_key = f"{labels}|{props}"
                        if node_key in seen:
                            continue
                        seen.add(node_key)
                        trimmed_props = {}
                        for k, v in list(props.items())[:6]:
                            text = str(v)
                            trimmed_props[k] = text[:160]
                        results.append({
                            "labels": labels,
                            "matched_keys": list(row.get("matched_keys") or []),
                            "props": trimmed_props,
                        })
                return results

            return self._query_with_fallback(_query)
        except Exception:
            return []

    def persist_hypergraph_records(self, records: list[dict[str, Any]], version: str = "v2") -> dict[str, Any]:
        if not records:
            return {"ok": True, "saved": 0, "members": 0, "projects": 0}
        try:
            def _write(session):
                session.run(
                    """
                    MATCH (h:Hyperedge)
                    DETACH DELETE h
                    """
                )
                session.run(
                    """
                    MATCH (n:HyperNode)
                    DETACH DELETE n
                    """
                )
                saved = 0
                members = 0
                project_links = 0
                for rec in records:
                    session.run(
                        """
                        MERGE (h:Hyperedge {id: $id})
                        SET h.family = $family,
                            h.label = $label,
                            h.category = $category,
                            h.support = $support,
                            h.confidence = $confidence,
                            h.severity = $severity,
                            h.score_impact = $score_impact,
                            h.stage_scope = $stage_scope,
                            h.teaching_note = $teaching_note,
                            h.retrieval_reason = $retrieval_reason,
                            h.rule_count = $rule_count,
                            h.rubric_count = $rubric_count,
                            h.version = $version
                        """,
                        id=rec.get("hyperedge_id", ""),
                        family=rec.get("type", ""),
                        label=rec.get("family_label", ""),
                        category=rec.get("category"),
                        support=int(rec.get("support", 0) or 0),
                        confidence=float(rec.get("confidence", 0) or 0),
                        severity=str(rec.get("severity", "") or ""),
                        score_impact=float(rec.get("score_impact", 0) or 0),
                        stage_scope=str(rec.get("stage_scope", "") or ""),
                        teaching_note=str(rec.get("teaching_note", "") or ""),
                        retrieval_reason=str(rec.get("retrieval_reason", "") or ""),
                        rule_count=len(rec.get("rules") or []),
                        rubric_count=len(rec.get("rubrics") or []),
                        version=version,
                    )
                    saved += 1

                    for member in rec.get("member_nodes") or []:
                        key = str(member.get("key", "")).strip()
                        if not key:
                            continue
                        session.run(
                            """
                            MERGE (n:HyperNode {key: $key})
                            SET n.type = $type,
                                n.name = $name,
                                n.display = $display
                            WITH n
                            MATCH (h:Hyperedge {id: $edge_id})
                            MERGE (h)-[:HAS_MEMBER {role: $role}]->(n)
                            """,
                            key=key,
                            type=str(member.get("type", "") or ""),
                            name=str(member.get("name", "") or ""),
                            display=str(member.get("display", "") or ""),
                            role=str(member.get("type", "") or ""),
                            edge_id=rec.get("hyperedge_id", ""),
                        )
                        members += 1

                    for rule_id in rec.get("rules") or []:
                        session.run(
                            """
                            MATCH (h:Hyperedge {id: $edge_id})
                            MATCH (r:RiskRule {id: $rule_id})
                            MERGE (h)-[:TRIGGERS_RULE]->(r)
                            """,
                            edge_id=rec.get("hyperedge_id", ""),
                            rule_id=str(rule_id),
                        )

                    for rubric in rec.get("rubrics") or []:
                        session.run(
                            """
                            MATCH (h:Hyperedge {id: $edge_id})
                            MATCH (ri:RubricItem {name: $rubric})
                            MERGE (h)-[:ALIGNS_WITH]->(ri)
                            """,
                            edge_id=rec.get("hyperedge_id", ""),
                            rubric=str(rubric),
                        )

                    for project_id in rec.get("source_project_ids") or []:
                        session.run(
                            """
                            MATCH (h:Hyperedge {id: $edge_id})
                            MATCH (p:Project {id: $project_id})
                            MERGE (h)-[:SUPPORTED_BY]->(p)
                            """,
                            edge_id=rec.get("hyperedge_id", ""),
                            project_id=str(project_id),
                        )
                        project_links += 1

                return {"saved": saved, "members": members, "projects": project_links}

            out = self._query_with_fallback(_write)
            return {"ok": True, **out}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def hypergraph_library_snapshot(self, limit: int = 24) -> dict[str, Any]:
        try:
            def _query(session):
                overview = session.run(
                    """
                    MATCH (h:Hyperedge)
                    OPTIONAL MATCH (h)-[:HAS_MEMBER]->(n:HyperNode)
                    RETURN count(DISTINCT h) AS edge_count,
                           count(DISTINCT n) AS node_count,
                           avg(size([(h)-[:HAS_MEMBER]->(:HyperNode) | 1])) AS avg_member_count
                    """
                ).single()
                family_rows = list(
                    session.run(
                        """
                        MATCH (h:Hyperedge)
                        RETURN h.family AS family,
                               coalesce(h.label, h.family) AS label,
                               count(*) AS count,
                               avg(coalesce(h.support, 0)) AS avg_support
                        ORDER BY count DESC, avg_support DESC
                        """
                    )
                )
                edge_rows = list(
                    session.run(
                        """
                        MATCH (h:Hyperedge)
                        OPTIONAL MATCH (h)-[:HAS_MEMBER]->(n:HyperNode)
                        OPTIONAL MATCH (h)-[:SUPPORTED_BY]->(p:Project)
                        RETURN h.id AS hyperedge_id,
                               h.family AS family,
                               coalesce(h.label, h.family) AS label,
                               h.category AS category,
                               h.support AS support,
                               h.stage_scope AS stage_scope,
                               h.severity AS severity,
                               h.score_impact AS score_impact,
                               h.teaching_note AS teaching_note,
                               collect(DISTINCT n.display)[0..8] AS members,
                               collect(DISTINCT p.id)[0..6] AS source_projects
                        ORDER BY h.support DESC, h.family ASC
                        LIMIT $limit
                        """,
                        limit=limit,
                    )
                )
                return {
                    "overview": {
                        "edge_count": int((overview or {}).get("edge_count") or 0),
                        "node_count": int((overview or {}).get("node_count") or 0),
                        "avg_member_count": round(float((overview or {}).get("avg_member_count") or 0.0), 2),
                    },
                    "families": [dict(r) for r in family_rows],
                    "edges": [dict(r) for r in edge_rows],
                }

            return self._query_with_fallback(_query)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"hypergraph library query failed: {exc}"}

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

    def class_capability_map(self, class_id: str) -> dict[str, Any]:
        """从neo4j查询班级的5维度能力映射数据（通过Category过滤）"""
        try:
            def _query(session):
                # 查询指定category的所有Project的维度评分
                dimension_keys = ["empathy", "ideation", "business", "execution", "pitching"]
                dimension_data = {}
                
                # 先获取该category下的所有project
                projects = list(
                    session.run(
                        """
                        MATCH (p:Project)-[:BELONGS_TO]->(c:Category)
                        WHERE c.name = $category OR c.id = $category
                        RETURN DISTINCT p.id AS project_id
                        """,
                        category=class_id,
                    )
                )
                
                project_ids = [r["project_id"] for r in projects]
                
                if not project_ids:
                    return {"dimension_data": {}, "project_count": 0}
                
                # 对于每个维度，查询平均评分
                for dim in dimension_keys:
                    result = session.run(
                        f"""
                        MATCH (p:Project)-[:{dim.upper()}]->(d)
                        WHERE p.id IN $project_ids
                        RETURN avg(COALESCE(d.score, 6.0)) AS avg_score
                        """,
                        project_ids=project_ids,
                    ).single()
                    
                    avg_score = float(result["avg_score"]) if result and result["avg_score"] else 6.0
                    dimension_data[dim] = round(avg_score, 2)
                
                return {
                    "dimension_data": dimension_data,
                    "project_count": len(project_ids),
                }
            
            return self._query_with_fallback(_query)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"capability map query failed: {exc}"}

    def class_rule_coverage(self, class_id: str) -> dict[str, Any]:
        """从neo4j查询班级的规则覆盖率数据（通过Category过滤）"""
        try:
            def _query(session):
                # 查询指定category的所有Project触发的规则
                projects = list(
                    session.run(
                        """
                        MATCH (p:Project)-[:BELONGS_TO]->(c:Category)
                        WHERE c.name = $category OR c.id = $category
                        RETURN DISTINCT p.id AS project_id
                        """,
                        category=class_id,
                    )
                )
                
                project_ids = [r["project_id"] for r in projects]
                
                if not project_ids:
                    return {"rule_data": [], "total_projects": 0}
                
                # 查询这些项目触发的规则及其计数
                rule_data = list(
                    session.run(
                        """
                        MATCH (p:Project)-[:HITS_RULE]->(r:RiskRule)
                        WHERE p.id IN $project_ids
                        WITH r, count(DISTINCT p) AS hit_count
                        RETURN r.id AS rule_id, r.name AS rule_name, hit_count
                        ORDER BY hit_count DESC
                        """,
                        project_ids=project_ids,
                    )
                )
                
                return {
                    "rule_data": [dict(r) for r in rule_data],
                    "total_projects": len(project_ids),
                }
            
            return self._query_with_fallback(_query)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"rule coverage query failed: {exc}"}
