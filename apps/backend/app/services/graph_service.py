import logging
import time
from dataclasses import dataclass
from typing import Any

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired

from .kb_quality_extensions import (
    augment_wilson_intervals,
    compute_canonical_coverage,
    compute_degree_histogram,
    compute_lifecycle_representativeness,
    compute_ontology_constraint_compliance,
    compute_top_entities_per_label,
    load_canonical_concepts,
    load_lifecycle_map,
    sample_traceability_chains,
)

logger = logging.getLogger(__name__)

# 抑制 Neo4j 6.x 驱动对服务器端通知（如 "label does not exist" 告警）
# 刷屏 stderr / 被前端捕获的问题。这些通知仅为提示，不影响查询结果。
for _ln in ("neo4j.notifications", "neo4j", "neo4j.io", "neo4j.pool"):
    logging.getLogger(_ln).setLevel(logging.ERROR)

_TRANSIENT_ERRORS = (ServiceUnavailable, SessionExpired, ConnectionResetError, TimeoutError, OSError)


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
        self._shared_driver = None

    def _driver(self):
        if self._shared_driver is not None:
            return self._shared_driver
        driver_kwargs: dict[str, Any] = dict(
            auth=(self.username, self.password),
            connection_timeout=5,
            max_connection_lifetime=300,
            max_connection_pool_size=10,
            connection_acquisition_timeout=8,
            max_transaction_retry_time=8,
        )
        # Neo4j Python driver 5.7+ / 6.x 通过 notifications_min_severity="OFF"
        # 从源头关闭服务器端通知（避免 "label does not exist" 告警刷屏）。
        # 兼容老版本：不支持该参数时回退到常规配置。
        try:
            self._shared_driver = GraphDatabase.driver(
                self.uri,
                notifications_min_severity="OFF",
                **driver_kwargs,
            )
        except TypeError:
            self._shared_driver = GraphDatabase.driver(self.uri, **driver_kwargs)
        return self._shared_driver

    def close(self):
        if self._shared_driver:
            try:
                self._shared_driver.close()
            except Exception:  # noqa: BLE001
                pass
            self._shared_driver = None

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

    def _query_with_fallback(self, query_fn, *, max_retries: int = 2):
        """
        Run a query against the configured database with transient-error retry.

        注意：历史版本里会把 database="" 作为兜底候选一起尝试，但在 Aura Free 实例
        上没有可用的默认 `neo4j` 库，该兜底只会触发 DatabaseNotFound / 路由错误，
        反而把真正短暂的抖动放大成 6 次失败、50+s 超时。这里改为只使用配置库，
        并把 DatabaseNotFound 当作永久错立即抛出。
        """
        target_db = self.database or ""
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            driver = self._driver()
            try:
                session_kwargs = {"database": target_db} if target_db else {}
                with driver.session(**session_kwargs) as session:
                    return query_fn(session)
            except _TRANSIENT_ERRORS as exc:
                last_exc = exc
                logger.warning(
                    "Neo4j transient error (attempt %d/%d, db=%r): %s",
                    attempt + 1, max_retries + 1, target_db, exc,
                )
                self.close()
            except Neo4jError as exc:
                code = getattr(exc, "code", "") or ""
                if "DatabaseNotFound" in code or "Database.DatabaseNotFound" in code:
                    logger.error(
                        "Neo4j database %r not found — check NEO4J_DATABASE config; not retrying.",
                        target_db,
                    )
                    raise
                last_exc = exc
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                break
            if attempt < max_retries:
                wait = min(2 ** attempt, 4)
                logger.info("Retrying Neo4j in %.1fs …", wait)
                time.sleep(wait)

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

    def get_kb_stats(self) -> dict[str, Any]:
        """Return comprehensive knowledge base statistics from Neo4j."""
        try:
            def _query(session):
                total_nodes = int(session.run("MATCH (n) RETURN count(n) AS c").single()["c"])
                total_rels = int(session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"])

                label_rows = list(session.run(
                    "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC"
                ))
                node_labels = {r["label"]: int(r["cnt"]) for r in label_rows}

                rel_rows = list(session.run(
                    "MATCH ()-[r]->() RETURN type(r) AS rtype, count(r) AS cnt ORDER BY cnt DESC"
                ))
                rel_types = {r["rtype"]: int(r["cnt"]) for r in rel_rows}

                cat_rows = list(session.run(
                    "MATCH (c:Category)<-[:BELONGS_TO]-(p:Project) "
                    "RETURN c.name AS cat, count(p) AS cnt ORDER BY cnt DESC"
                ))
                categories = [{"name": r["cat"], "count": int(r["cnt"])} for r in cat_rows]

                dim_rows = list(session.run("""
                    MATCH (p:Project)
                    OPTIONAL MATCH (p)-[:HAS_PAIN]->(pain:PainPoint)
                    OPTIONAL MATCH (p)-[:HAS_SOLUTION]->(sol:Solution)
                    OPTIONAL MATCH (p)-[:HAS_BUSINESS_MODEL]->(bm:BusinessModelAspect)
                    OPTIONAL MATCH (p)-[:HAS_MARKET_ANALYSIS]->(mkt:Market)
                    OPTIONAL MATCH (p)-[:HAS_INNOVATION]->(inn:InnovationPoint)
                    OPTIONAL MATCH (p)-[:HAS_EVIDENCE]->(ev:Evidence)
                    OPTIONAL MATCH (p)-[:HAS_EXECUTION_STEP]->(ex:ExecutionStep)
                    OPTIONAL MATCH (p)-[:HAS_TARGET_USER]->(st:Stakeholder)
                    OPTIONAL MATCH (p)-[:HAS_RISK_CONTROL]->(rc:RiskControlPoint)
                    RETURN
                        count(DISTINCT pain) AS total_pains,
                        count(DISTINCT sol) AS total_solutions,
                        count(DISTINCT bm) AS total_biz_models,
                        count(DISTINCT mkt) AS total_markets,
                        count(DISTINCT inn) AS total_innovations,
                        count(DISTINCT ev) AS total_evidence,
                        count(DISTINCT ex) AS total_exec_steps,
                        count(DISTINCT st) AS total_stakeholders,
                        count(DISTINCT rc) AS total_risk_controls
                """))
                dim_data = dim_rows[0] if dim_rows else {}

                hyper_nodes = int(session.run("MATCH (h:HyperNode) RETURN count(h) AS c").single()["c"])
                hyper_edges = int(session.run("MATCH (h:Hyperedge) RETURN count(h) AS c").single()["c"])
                onto_nodes = int(session.run("MATCH (o:OntologyNode) RETURN count(o) AS c").single()["c"])
                risk_rules = int(session.run("MATCH (r:RiskRule) RETURN count(r) AS c").single()["c"])
                rubric_items = int(session.run("MATCH (r:RubricItem) RETURN count(r) AS c").single()["c"])

                dims = {
                    "pain_points": int(dim_data.get("total_pains", 0)),
                    "solutions": int(dim_data.get("total_solutions", 0)),
                    "business_models": int(dim_data.get("total_biz_models", 0)),
                    "markets": int(dim_data.get("total_markets", 0)),
                    "innovations": int(dim_data.get("total_innovations", 0)),
                    "evidence": int(dim_data.get("total_evidence", 0)),
                    "execution_steps": int(dim_data.get("total_exec_steps", 0)),
                    "stakeholders": int(dim_data.get("total_stakeholders", 0)),
                    "risk_controls": int(dim_data.get("total_risk_controls", 0)),
                }
                total_projects = node_labels.get("Project", 0)

                # ── Rationality Metrics ──
                import math as _math

                # 1. Case Representativeness
                cat_counts = [c["count"] for c in categories if c.get("count", 0) > 0]
                n_cats = len(cat_counts)
                cat_total = sum(cat_counts)
                if cat_total > 0 and n_cats > 1:
                    cat_props = [c / cat_total for c in cat_counts]
                    cat_entropy = -sum(p * _math.log2(p) for p in cat_props)
                    cat_balance = round(cat_entropy / _math.log2(n_cats), 4)
                else:
                    cat_balance = 0
                category_coverage = n_cats

                dim_specs = [
                    ("pain_points", "痛点", "HAS_PAIN"),
                    ("solutions", "方案", "HAS_SOLUTION"),
                    ("business_models", "商业模式", "HAS_BUSINESS_MODEL"),
                    ("markets", "市场", "HAS_MARKET_ANALYSIS"),
                    ("innovations", "创新点", "HAS_INNOVATION"),
                    ("evidence", "证据", "HAS_EVIDENCE"),
                    ("execution_steps", "执行步骤", "HAS_EXECUTION_STEP"),
                    ("stakeholders", "目标用户", "HAS_TARGET_USER"),
                    ("risk_controls", "风控", "HAS_RISK_CONTROL"),
                ]
                low_frequency_dim_config = {
                    "execution_steps": {
                        "reason": "执行步骤通常只在方案已经较具体、里程碑较明确的案例中出现，不要求所有项目都高频覆盖。",
                        "expected_presence_range": [0.55, 0.85],
                        "missing_weight": 0.6,
                    },
                    "risk_controls": {
                        "reason": "风控更多在高监管、高安全或实施复杂度较高的案例中集中出现，低于通用维度覆盖并不直接代表抽取失真。",
                        "expected_presence_range": [0.5, 0.8],
                        "missing_weight": 0.55,
                    },
                }

                # 2. Content Richness
                dim_values = [
                    dims.get("pain_points", 0), dims.get("solutions", 0),
                    dims.get("business_models", 0), dims.get("markets", 0),
                    dims.get("innovations", 0), dims.get("evidence", 0),
                    dims.get("execution_steps", 0), dims.get("stakeholders", 0),
                    dims.get("risk_controls", 0),
                ]
                dim_names_list = ["痛点", "方案", "商业模式", "市场", "创新点", "证据", "执行步骤", "目标用户", "风控"]
                n_dim_types = len(dim_values)
                dim_total_ents = sum(dim_values)
                dim_covered = sum(1 for v in dim_values if v > 0)
                if dim_total_ents > 0 and dim_covered > 1:
                    dim_props = [v / dim_total_ents for v in dim_values if v > 0]
                    dim_entropy = -sum(p * _math.log2(p) for p in dim_props)
                    dim_balance = round(dim_entropy / _math.log2(n_dim_types), 4)
                else:
                    dim_balance = 0
                avg_entities_per_project = round(dim_total_ents / max(1, total_projects), 2)
                evidence_density = round(dims.get("evidence", 0) / max(1, total_projects), 2)

                # 3. Node Quality - entity sharing (requires additional query)
                try:
                    sharing_result = session.run(
                        """
                        MATCH (p:Project)-[]->(e)
                        WHERE NOT e:Category AND NOT e:RiskRule AND NOT e:RubricItem
                          AND NOT e:OntologyNode AND NOT e:Evidence
                          AND NOT e:EducationLevel AND NOT e:AwardLevel
                          AND NOT e:Competition AND NOT e:CompetitionDomain
                          AND NOT e:Entrepreneurship AND NOT e:HyperNode AND NOT e:Hyperedge
                        WITH e, count(DISTINCT p) AS proj_count
                        RETURN count(e) AS total_entities,
                               sum(CASE WHEN proj_count >= 2 THEN 1 ELSE 0 END) AS shared_entities,
                               avg(proj_count) AS avg_projects_per_entity
                        """
                    ).single()
                    total_dim_entities = int(sharing_result["total_entities"] or 0)
                    shared_entities = int(sharing_result["shared_entities"] or 0)
                    avg_proj_per_ent = round(float(sharing_result["avg_projects_per_entity"] or 0), 2)
                    sharing_rate = round(shared_entities / max(1, total_dim_entities), 4)
                except Exception:
                    total_dim_entities = 0
                    shared_entities = 0
                    avg_proj_per_ent = 0
                    sharing_rate = 0

                # 4. Graph Structure
                graph_density = round(2 * total_rels / max(1, total_nodes * (total_nodes - 1)), 6) if total_nodes > 1 else 0
                avg_degree = round(2 * total_rels / max(1, total_nodes), 2)
                max_possible_edges = int(total_nodes * (total_nodes - 1) / 2) if total_nodes > 1 else 0
                try:
                    degree_profile = session.run(
                        """
                        MATCH (n)
                        OPTIONAL MATCH (n)-[r]-()
                        WITH n, count(r) AS degree
                        RETURN sum(CASE WHEN degree = 0 THEN 1 ELSE 0 END) AS isolated_nodes,
                               sum(CASE WHEN degree = 1 THEN 1 ELSE 0 END) AS degree1_nodes,
                               sum(CASE WHEN degree <= 2 THEN 1 ELSE 0 END) AS degree_le2_nodes
                        """
                    ).single()
                    isolated_nodes = int((degree_profile or {}).get("isolated_nodes") or 0)
                    degree1_nodes = int((degree_profile or {}).get("degree1_nodes") or 0)
                    degree_le2_nodes = int((degree_profile or {}).get("degree_le2_nodes") or 0)
                except Exception:
                    isolated_nodes = 0
                    degree1_nodes = 0
                    degree_le2_nodes = 0
                try:
                    project_anchor_result = session.run(
                        """
                        MATCH (p:Project)-[r]-()
                        RETURN count(r) AS project_anchor_relationships
                        """
                    ).single()
                    project_anchor_relationships = int(
                        (project_anchor_result or {}).get("project_anchor_relationships") or 0
                    )
                except Exception:
                    project_anchor_relationships = 0
                sparse_node_ratio = round(degree_le2_nodes / max(1, total_nodes), 4)
                project_anchor_ratio = round(project_anchor_relationships / max(1, total_rels), 4)

                # 4.5 Extraction Quality / Auditability
                coverage_query = session.run(
                    """
                    MATCH (p:Project)
                    OPTIONAL MATCH (p)-[:HAS_PAIN]->(pain:PainPoint)
                    OPTIONAL MATCH (p)-[:HAS_SOLUTION]->(sol:Solution)
                    OPTIONAL MATCH (p)-[:HAS_BUSINESS_MODEL]->(bm:BusinessModelAspect)
                    OPTIONAL MATCH (p)-[:HAS_MARKET_ANALYSIS]->(mkt:Market)
                    OPTIONAL MATCH (p)-[:HAS_INNOVATION]->(inn:InnovationPoint)
                    OPTIONAL MATCH (p)-[:HAS_EVIDENCE]->(ev:Evidence)
                    OPTIONAL MATCH (p)-[:HAS_EXECUTION_STEP]->(ex:ExecutionStep)
                    OPTIONAL MATCH (p)-[:HAS_TARGET_USER]->(st:Stakeholder)
                    OPTIONAL MATCH (p)-[:HAS_RISK_CONTROL]->(rc:RiskControlPoint)
                    WITH p,
                         CASE WHEN count(DISTINCT pain) > 0 THEN 1 ELSE 0 END AS has_pain,
                         CASE WHEN count(DISTINCT sol) > 0 THEN 1 ELSE 0 END AS has_solution,
                         CASE WHEN count(DISTINCT bm) > 0 THEN 1 ELSE 0 END AS has_bm,
                         CASE WHEN count(DISTINCT mkt) > 0 THEN 1 ELSE 0 END AS has_market,
                         CASE WHEN count(DISTINCT inn) > 0 THEN 1 ELSE 0 END AS has_innovation,
                         CASE WHEN count(DISTINCT ev) > 0 THEN 1 ELSE 0 END AS has_evidence,
                         CASE WHEN count(DISTINCT ex) > 0 THEN 1 ELSE 0 END AS has_exec,
                         CASE WHEN count(DISTINCT st) > 0 THEN 1 ELSE 0 END AS has_stakeholder,
                         CASE WHEN count(DISTINCT rc) > 0 THEN 1 ELSE 0 END AS has_risk,
                         CASE
                           WHEN count(
                             DISTINCT CASE
                               WHEN trim(coalesce(ev.quote, "")) <> "" OR trim(coalesce(ev.source_unit, "")) <> ""
                               THEN ev
                             END
                           ) > 0
                           THEN 1 ELSE 0
                         END AS has_traceable_evidence
                    RETURN count(p) AS total_projects,
                           sum(has_pain) AS pain_projects,
                           sum(has_solution) AS solution_projects,
                           sum(has_bm) AS bm_projects,
                           sum(has_market) AS market_projects,
                           sum(has_innovation) AS innovation_projects,
                           sum(has_evidence) AS evidence_projects,
                           sum(has_exec) AS exec_projects,
                           sum(has_stakeholder) AS stakeholder_projects,
                           sum(has_risk) AS risk_projects,
                           sum(has_traceable_evidence) AS projects_with_traceable_evidence,
                           sum(CASE WHEN has_pain = 1 AND has_traceable_evidence = 1 THEN 1 ELSE 0 END) AS pain_traceable_projects,
                           sum(CASE WHEN has_solution = 1 AND has_traceable_evidence = 1 THEN 1 ELSE 0 END) AS solution_traceable_projects,
                           sum(CASE WHEN has_bm = 1 AND has_traceable_evidence = 1 THEN 1 ELSE 0 END) AS bm_traceable_projects,
                           sum(CASE WHEN has_market = 1 AND has_traceable_evidence = 1 THEN 1 ELSE 0 END) AS market_traceable_projects,
                           sum(CASE WHEN has_innovation = 1 AND has_traceable_evidence = 1 THEN 1 ELSE 0 END) AS innovation_traceable_projects,
                           sum(CASE WHEN has_evidence = 1 AND has_traceable_evidence = 1 THEN 1 ELSE 0 END) AS evidence_traceable_projects,
                           sum(CASE WHEN has_exec = 1 AND has_traceable_evidence = 1 THEN 1 ELSE 0 END) AS exec_traceable_projects,
                           sum(CASE WHEN has_stakeholder = 1 AND has_traceable_evidence = 1 THEN 1 ELSE 0 END) AS stakeholder_traceable_projects,
                           sum(CASE WHEN has_risk = 1 AND has_traceable_evidence = 1 THEN 1 ELSE 0 END) AS risk_traceable_projects
                    """
                ).single()

                entity_traceability = session.run(
                    """
                    MATCH (p:Project)
                    OPTIONAL MATCH (p)-[:HAS_EVIDENCE]->(ev:Evidence)
                    WITH p,
                         CASE
                           WHEN count(
                             DISTINCT CASE
                               WHEN trim(coalesce(ev.quote, "")) <> "" OR trim(coalesce(ev.source_unit, "")) <> ""
                               THEN ev
                             END
                           ) > 0
                           THEN 1 ELSE 0
                         END AS has_traceable_evidence
                    OPTIONAL MATCH (p)-[:HAS_PAIN|HAS_SOLUTION|HAS_BUSINESS_MODEL|HAS_MARKET_ANALYSIS|HAS_INNOVATION|HAS_EVIDENCE|HAS_EXECUTION_STEP|HAS_TARGET_USER|HAS_RISK_CONTROL]->(dim)
                    WITH has_traceable_evidence, count(DISTINCT dim) AS entity_count
                    RETURN sum(entity_count) AS total_entities,
                           sum(CASE WHEN has_traceable_evidence = 1 THEN entity_count ELSE 0 END) AS traceable_entities
                    """
                ).single()

                total_traceable_entities = int((entity_traceability or {}).get("traceable_entities") or 0)
                total_entities_for_trace = int((entity_traceability or {}).get("total_entities") or 0)
                projects_with_evidence = int((coverage_query or {}).get("evidence_projects") or 0)
                projects_with_traceable_evidence = int((coverage_query or {}).get("projects_with_traceable_evidence") or 0)
                project_evidence_coverage = round(projects_with_evidence / max(1, total_projects), 4)
                project_traceable_coverage = round(projects_with_traceable_evidence / max(1, total_projects), 4)
                traceability_rate = round(total_traceable_entities / max(1, total_entities_for_trace), 4)

                dimension_missing_rate = []
                evidence_backed_dimensions = []
                low_frequency_dimensions = []
                weighted_missing_sum = 0.0
                weighted_missing_denominator = 0.0
                for dim_key, dim_name, _ in dim_specs:
                    base_name = dim_key.replace("pain_points", "pain").replace("solutions", "solution").replace("business_models", "bm").replace("markets", "market").replace("innovations", "innovation").replace("execution_steps", "exec").replace("stakeholders", "stakeholder").replace("risk_controls", "risk")
                    proj_count = int((coverage_query or {}).get(f"{base_name}_projects") or 0)
                    trace_proj_count = int((coverage_query or {}).get(f"{base_name}_traceable_projects") or 0)
                    missing_count = max(0, total_projects - proj_count)
                    missing_rate = round(missing_count / max(1, total_projects), 4)
                    evidence_backed_rate = round(trace_proj_count / max(1, proj_count), 4) if proj_count > 0 else 0
                    dim_meta = low_frequency_dim_config.get(dim_key)
                    missing_weight = float((dim_meta or {}).get("missing_weight") or 1.0)
                    weighted_missing_sum += missing_rate * missing_weight
                    weighted_missing_denominator += missing_weight
                    dimension_missing_rate.append({
                        "key": dim_key,
                        "name": dim_name,
                        "project_count": proj_count,
                        "missing_count": missing_count,
                        "missing_rate": missing_rate,
                        "is_low_frequency_expected": bool(dim_meta),
                        "missing_weight": missing_weight,
                    })
                    evidence_backed_dimensions.append({
                        "key": dim_key,
                        "name": dim_name,
                        "project_count": proj_count,
                        "traceable_project_count": trace_proj_count,
                        "evidence_backed_rate": evidence_backed_rate,
                        "is_low_frequency_expected": bool(dim_meta),
                    })
                    if dim_meta:
                        observed_presence_rate = round(proj_count / max(1, total_projects), 4)
                        expected_range = dim_meta.get("expected_presence_range") or [0.0, 1.0]
                        low_frequency_dimensions.append({
                            "key": dim_key,
                            "name": dim_name,
                            "observed_presence_rate": observed_presence_rate,
                            "expected_min": expected_range[0],
                            "expected_max": expected_range[1],
                            "reason": dim_meta.get("reason") or "",
                            "status": (
                                "符合预期"
                                if expected_range[0] <= observed_presence_rate <= expected_range[1]
                                else ("低于预期" if observed_presence_rate < expected_range[0] else "高于预期")
                            ),
                        })

                avg_dim_count = (dim_total_ents / max(1, n_dim_types)) if n_dim_types else 0
                dimension_overrepresented = []
                dimension_underrepresented = []
                for idx, dim_name in enumerate(dim_names_list):
                    dim_count = dim_values[idx]
                    ratio = round(dim_count / max(1, avg_dim_count), 2)
                    row = {"name": dim_name, "count": dim_count, "ratio_to_mean": ratio}
                    if ratio >= 1.25:
                        dimension_overrepresented.append(row)
                    elif ratio <= 0.75:
                        dimension_underrepresented.append(row)

                audit_project_rows = list(session.run(
                    """
                    MATCH (p:Project)-[:BELONGS_TO]->(c:Category)
                    OPTIONAL MATCH (p)-[:HAS_PAIN]->(pain:PainPoint)
                    OPTIONAL MATCH (p)-[:HAS_SOLUTION]->(sol:Solution)
                    OPTIONAL MATCH (p)-[:HAS_INNOVATION]->(inn:InnovationPoint)
                    OPTIONAL MATCH (p)-[:HAS_BUSINESS_MODEL]->(bm:BusinessModelAspect)
                    OPTIONAL MATCH (p)-[:HAS_TARGET_USER]->(st:Stakeholder)
                    OPTIONAL MATCH (p)-[:HAS_MARKET_ANALYSIS]->(mkt:Market)
                    OPTIONAL MATCH (p)-[:HAS_EXECUTION_STEP]->(ex:ExecutionStep)
                    OPTIONAL MATCH (p)-[:HAS_RISK_CONTROL]->(rc:RiskControlPoint)
                    OPTIONAL MATCH (p)-[:HAS_EVIDENCE]->(ev:Evidence)
                    WITH p, c,
                         count(DISTINCT pain) AS pain_count,
                         count(DISTINCT sol) AS solution_count,
                         count(DISTINCT inn) AS innovation_count,
                         count(DISTINCT bm) AS business_model_count,
                         count(DISTINCT st) AS stakeholder_count,
                         count(DISTINCT mkt) AS market_count,
                         count(DISTINCT ex) AS execution_count,
                         count(DISTINCT rc) AS risk_count,
                         count(DISTINCT ev) AS evidence_count,
                         count(DISTINCT CASE WHEN trim(coalesce(ev.quote, "")) <> "" THEN ev END) AS quote_evidence_count,
                         count(DISTINCT CASE WHEN trim(coalesce(ev.source_unit, "")) <> "" THEN ev END) AS source_evidence_count
                    RETURN p.id AS project_id,
                           p.name AS project_name,
                           c.name AS category,
                           p.source_file AS source_file,
                           pain_count, solution_count, innovation_count, business_model_count,
                           stakeholder_count, market_count, execution_count, risk_count,
                           evidence_count, quote_evidence_count, source_evidence_count
                    """
                ))
                sample_rows = list(session.run(
                    """
                    MATCH (p:Project)-[:BELONGS_TO]->(c:Category)
                    OPTIONAL MATCH (p)-[:HAS_PAIN]->(pain:PainPoint)
                    OPTIONAL MATCH (p)-[:HAS_SOLUTION]->(sol:Solution)
                    OPTIONAL MATCH (p)-[:HAS_INNOVATION]->(inn:InnovationPoint)
                    OPTIONAL MATCH (p)-[:HAS_BUSINESS_MODEL]->(bm:BusinessModelAspect)
                    OPTIONAL MATCH (p)-[:HAS_EVIDENCE]->(ev:Evidence)
                    WITH p, c,
                         collect(DISTINCT pain.name)[..2] AS pains,
                         collect(DISTINCT sol.name)[..2] AS solutions,
                         collect(DISTINCT inn.name)[..1] AS innovations,
                         collect(DISTINCT bm.name)[..1] AS business_models,
                         collect(
                           DISTINCT CASE
                             WHEN trim(coalesce(ev.quote, "")) <> "" OR trim(coalesce(ev.source_unit, "")) <> ""
                             THEN {
                               quote: coalesce(ev.quote, ""),
                               source_unit: coalesce(ev.source_unit, ""),
                               type: coalesce(ev.type, "")
                             }
                           END
                         )[..3] AS evidence_samples,
                         count(DISTINCT ev) AS evidence_count
                    WHERE evidence_count > 0
                    RETURN p.id AS project_id,
                           p.name AS project_name,
                           c.name AS category,
                           p.source_file AS source_file,
                           pains, solutions, innovations, business_models,
                           evidence_count, evidence_samples
                    ORDER BY evidence_count DESC, p.name ASC
                    LIMIT 300
                    """
                ))
                audit_candidates: list[dict[str, Any]] = []
                audit_buckets: dict[str, list[dict[str, Any]]] = {}
                for row in sample_rows:
                    evidence_samples = [e for e in (row.get("evidence_samples") or []) if e]
                    if not evidence_samples:
                        continue
                    category_name = str(row.get("category") or "")
                    pains = [x for x in (row.get("pains") or []) if x][:2]
                    solutions = [x for x in (row.get("solutions") or []) if x][:2]
                    innovations = [x for x in (row.get("innovations") or []) if x][:1]
                    business_models = [x for x in (row.get("business_models") or []) if x][:1]
                    candidate = {
                        "project_id": row.get("project_id"),
                        "project_name": row.get("project_name"),
                        "category": category_name,
                        "source_file": row.get("source_file") or "",
                        "pains": pains,
                        "solutions": solutions,
                        "innovations": innovations,
                        "business_models": business_models,
                        "evidence_count": int(row.get("evidence_count") or 0),
                        "evidence_samples": evidence_samples[:3],
                        "key_dimension_count": sum(
                            1 for bucket in [pains, solutions, innovations, business_models] if bucket
                        ),
                    }
                    audit_candidates.append(candidate)
                    audit_buckets.setdefault(category_name or "未分类", []).append(candidate)

                for items in audit_buckets.values():
                    items.sort(
                        key=lambda item: (
                            -int(item.get("evidence_count") or 0),
                            -int(item.get("key_dimension_count") or 0),
                            str(item.get("project_name") or ""),
                        )
                    )

                audit_target_size = 0
                if projects_with_traceable_evidence > 0:
                    audit_target_size = min(
                        projects_with_traceable_evidence,
                        18,
                        max(12, int(round(projects_with_traceable_evidence * 0.16))),
                    )
                strata_categories = [cat for cat, items in audit_buckets.items() if items]
                quota_map = {cat: 0 for cat in strata_categories}
                if strata_categories and audit_target_size > 0:
                    if audit_target_size >= len(strata_categories):
                        for cat in strata_categories:
                            quota_map[cat] = 1
                        remaining_slots = audit_target_size - len(strata_categories)
                    else:
                        strata_sorted = sorted(
                            strata_categories,
                            key=lambda cat: len(audit_buckets[cat]),
                            reverse=True,
                        )
                        for cat in strata_sorted[:audit_target_size]:
                            quota_map[cat] = 1
                        remaining_slots = 0

                    while remaining_slots > 0:
                        available_cats = [
                            cat for cat in strata_categories
                            if quota_map[cat] < len(audit_buckets[cat])
                        ]
                        if not available_cats:
                            break
                        target_cat = max(
                            available_cats,
                            key=lambda cat: len(audit_buckets[cat]) / max(1, quota_map[cat] + 1),
                        )
                        quota_map[target_cat] += 1
                        remaining_slots -= 1

                sampled_items: list[dict[str, Any]] = []
                for cat in strata_categories:
                    sampled_items.extend(audit_buckets[cat][:quota_map.get(cat, 0)])
                sampled_items.sort(
                    key=lambda item: (
                        -int(item.get("evidence_count") or 0),
                        -int(item.get("key_dimension_count") or 0),
                        str(item.get("project_name") or ""),
                    )
                )

                display_sample_limit = 6
                sample_audit_pool = [
                    {
                        **item,
                        "evidence_samples": (item.get("evidence_samples") or [])[:2],
                    }
                    for item in sampled_items[:display_sample_limit]
                ]

                audit_sample_size = len(sampled_items)
                audit_sample_evidence = sum(int(item.get("evidence_count") or 0) for item in sampled_items)
                audit_snippet_count = sum(len(item.get("evidence_samples") or []) for item in sampled_items)
                audit_traceable_snippet_count = sum(
                    1
                    for item in sampled_items
                    for ev in (item.get("evidence_samples") or [])
                    if str(ev.get("quote", "")).strip() or str(ev.get("source_unit", "")).strip()
                )
                audit_quote_project_count = sum(
                    1
                    for item in sampled_items
                    if any(str(ev.get("quote", "")).strip() for ev in (item.get("evidence_samples") or []))
                )
                audit_source_project_count = sum(
                    1
                    for item in sampled_items
                    if any(str(ev.get("source_unit", "")).strip() for ev in (item.get("evidence_samples") or []))
                )
                audit_multi_evidence_count = sum(
                    1 for item in sampled_items if int(item.get("evidence_count") or 0) >= 2
                )
                audit_key_dimension_count = sum(
                    1 for item in sampled_items if int(item.get("key_dimension_count") or 0) >= 2
                )
                audit_category_coverage = round(
                    len({item.get("category") for item in sampled_items if item.get("category")}) / max(1, n_cats),
                    4,
                )
                audit_category_strata = [
                    {
                        "category": cat,
                        "universe_count": len(audit_buckets[cat]),
                        "sampled_count": quota_map.get(cat, 0),
                        "sample_rate": round(quota_map.get(cat, 0) / max(1, len(audit_buckets[cat])), 4),
                    }
                    for cat in sorted(
                        strata_categories,
                        key=lambda key: len(audit_buckets[key]),
                        reverse=True,
                    )
                ]
                sample_audit_summary = {
                    "sample_size": audit_sample_size,
                    "display_size": len(sample_audit_pool),
                    "sample_universe": projects_with_traceable_evidence,
                    "sample_coverage": round(audit_sample_size / max(1, projects_with_traceable_evidence), 4),
                    "avg_evidence_per_sample": round(audit_sample_evidence / max(1, audit_sample_size), 2),
                    "avg_key_dimension_count": round(
                        sum(int(item.get("key_dimension_count") or 0) for item in sampled_items) / max(1, audit_sample_size),
                        2,
                    ),
                    "category_coverage": audit_category_coverage,
                    "traceable_snippet_rate": round(audit_traceable_snippet_count / max(1, audit_snippet_count), 4),
                    "quote_presence_rate": round(audit_quote_project_count / max(1, audit_sample_size), 4),
                    "source_unit_presence_rate": round(audit_source_project_count / max(1, audit_sample_size), 4),
                    "multi_evidence_support_rate": round(audit_multi_evidence_count / max(1, audit_sample_size), 4),
                    "key_dimension_presence_rate": round(audit_key_dimension_count / max(1, audit_sample_size), 4),
                    "category_strata": audit_category_strata,
                    "sampling_method": "以含可追溯证据的项目为总体，按类别分层抽样；每类至少抽取1个样本，其余名额按类别项目占比分配，层内按证据条数与关键维度数排序抽取",
                    "audit_focus": [
                        "样本是否覆盖主要类别，而不是只展示个别好案例",
                        "抽取字段是否能对应到原文quote/source_unit",
                        "关键维度是否有证据支撑",
                        "同一项目是否具备多条证据与多维度信息，避免单点支撑",
                    ],
                }

                audit_universe_rows = [
                    row for row in audit_project_rows
                    if int(row.get("evidence_count") or 0) > 0
                ]
                audit_universe_size = len(audit_universe_rows)
                audit_rule_specs = [
                    {
                        "key": "locatable_evidence",
                        "name": "证据定位完备率",
                        "formula": "同时含 quote 与 source_unit 的项目数 / 含证据项目数",
                        "meaning": "回答证据是否不仅存在，而且能看到原文摘录并定位来源位置。",
                        "pass_count": sum(
                            1
                            for row in audit_universe_rows
                            if int(row.get("quote_evidence_count") or 0) > 0
                            and int(row.get("source_evidence_count") or 0) > 0
                        ),
                    },
                    {
                        "key": "multi_evidence",
                        "name": "多证据支撑率",
                        "formula": "证据数 >= 2 的项目数 / 含证据项目数",
                        "meaning": "回答结构判断是否只依赖单条证据，还是至少有双证据支撑。",
                        "pass_count": sum(
                            1 for row in audit_universe_rows if int(row.get("evidence_count") or 0) >= 2
                        ),
                    },
                    {
                        "key": "multi_dimension",
                        "name": "多维标签联查率",
                        "formula": "关键维度数 >= 2 的项目数 / 含证据项目数",
                        "meaning": "回答一个项目是否同时呈现多个分析维度，避免只靠单点字段形成判断。",
                        "pass_count": sum(
                            1
                            for row in audit_universe_rows
                            if sum(
                                1
                                for field_name in [
                                    "pain_count",
                                    "solution_count",
                                    "innovation_count",
                                    "business_model_count",
                                    "stakeholder_count",
                                    "market_count",
                                ]
                                if int(row.get(field_name) or 0) > 0
                            ) >= 2
                        ),
                    },
                    {
                        "key": "audit_closure",
                        "name": "审计闭环率",
                        "formula": "同时满足『可定位 + 多证据 + 多维标签』的项目数 / 含证据项目数",
                        "meaning": "回答进入审计的项目里，有多少项目已经具备比较完整的复核条件。",
                        "pass_count": sum(
                            1
                            for row in audit_universe_rows
                            if int(row.get("quote_evidence_count") or 0) > 0
                            and int(row.get("source_evidence_count") or 0) > 0
                            and int(row.get("evidence_count") or 0) >= 2
                            and sum(
                                1
                                for field_name in [
                                    "pain_count",
                                    "solution_count",
                                    "innovation_count",
                                    "business_model_count",
                                    "stakeholder_count",
                                    "market_count",
                                ]
                                if int(row.get(field_name) or 0) > 0
                            ) >= 2
                        ),
                    },
                ]
                audit_rule_results = []
                for spec in audit_rule_specs:
                    pass_count = int(spec["pass_count"])
                    fail_count = max(0, audit_universe_size - pass_count)
                    audit_rule_results.append({
                        "key": spec["key"],
                        "name": spec["name"],
                        "formula": spec["formula"],
                        "meaning": spec["meaning"],
                        "universe_size": audit_universe_size,
                        "pass_count": pass_count,
                        "fail_count": fail_count,
                        "pass_rate": round(pass_count / max(1, audit_universe_size), 4),
                    })
                audit_failure_distribution = sorted(
                    [
                        {
                            "name": item["name"],
                            "fail_count": item["fail_count"],
                            "fail_rate": round(item["fail_count"] / max(1, item["universe_size"]), 4),
                        }
                        for item in audit_rule_results
                    ],
                    key=lambda item: item["fail_count"],
                    reverse=True,
                )
                audit_total_checks = sum(item["universe_size"] for item in audit_rule_results)
                audit_total_passes = sum(item["pass_count"] for item in audit_rule_results)
                audit_summary = {
                    "rule_count": len(audit_rule_results),
                    "audit_universe": audit_universe_size,
                    "total_checks": audit_total_checks,
                    "total_passes": audit_total_passes,
                    "overall_pass_rate": round(audit_total_passes / max(1, audit_total_checks), 4),
                    "methodology": "基于进入审计总体的规则核验，而不是仅展示个别样本。每条规则都统计样本空间、通过数、失败数与通过率。",
                    "rule_results": audit_rule_results,
                    "failure_distribution": audit_failure_distribution,
                }

                semantic_specs = [
                    {
                        "key": "pain_points",
                        "name": "痛点",
                        "label": "PainPoint",
                        "theory_basis": "Lean Canvas 的 Problem + Design Thinking 的需求洞察",
                        "positive_keywords": ["痛点", "问题", "难", "低", "高", "慢", "贵", "不足", "缺", "瓶颈", "障碍", "压力", "风险", "不便"],
                        "counter_keywords": ["方案", "系统", "平台", "服务", "模型", "产品", "收费", "商业"],
                        "closure_fields": ["solution_count", "stakeholder_count"],
                        "dim_alias": "pain",
                    },
                    {
                        "key": "solutions",
                        "name": "方案",
                        "label": "Solution",
                        "theory_basis": "Lean Canvas 的 Solution + 产品机制描述",
                        "positive_keywords": ["方案", "系统", "平台", "服务", "工具", "机制", "模型", "产品", "助手", "引擎", "装置"],
                        "counter_keywords": ["痛点", "问题", "用户需求", "市场规模", "收费", "收入"],
                        "closure_fields": ["pain_count", "business_model_count", "innovation_count"],
                        "dim_alias": "solution",
                    },
                    {
                        "key": "stakeholders",
                        "name": "目标用户",
                        "label": "Stakeholder",
                        "theory_basis": "Lean Canvas / BMC 的 Customer Segments",
                        "positive_keywords": ["用户", "学生", "教师", "家长", "老人", "企业", "医院", "学校", "商户", "农户", "客户", "机构", "人群"],
                        "counter_keywords": ["市场", "渠道", "平台", "方案", "系统", "产品"],
                        "closure_fields": ["pain_count", "market_count"],
                        "dim_alias": "stakeholder",
                    },
                    {
                        "key": "business_models",
                        "name": "商业模式",
                        "label": "BusinessModelAspect",
                        "theory_basis": "BMC 的 Revenue Streams / Value Capture",
                        "positive_keywords": ["收费", "收入", "订阅", "会员", "佣金", "服务费", "SaaS", "B2B", "B2C", "租赁", "销售", "分成", "变现", "商业模式"],
                        "counter_keywords": ["痛点", "用户", "技术", "平台", "问题", "市场背景"],
                        "closure_fields": ["solution_count", "market_count", "stakeholder_count"],
                        "dim_alias": "bm",
                    },
                ]

                def _contains_any(text: str, keywords: list[str]) -> bool:
                    return any(keyword and keyword in text for keyword in keywords)

                label_validity_details = []
                confusion_pair_counter: dict[tuple[str, str], int] = {}
                semantic_weighted_total = 0
                semantic_score_accumulator = 0.0
                semantic_score_formula = "0.35×边界命中率 + 0.20×(1-反例触发率) + 0.25×证据-标签一致率 + 0.20×结构闭环率"
                for spec in semantic_specs:
                    entity_rows = list(session.run(
                        f"MATCH (n:{spec['label']}) RETURN coalesce(n.name, '') AS name"
                    ))
                    entity_names = [str(row.get("name") or "").strip() for row in entity_rows if str(row.get("name") or "").strip()]
                    total_items = len(entity_names)
                    boundary_hits = 0
                    counter_hits = 0
                    for name in entity_names:
                        if _contains_any(name, spec["positive_keywords"]):
                            boundary_hits += 1
                        if _contains_any(name, spec["counter_keywords"]):
                            counter_hits += 1
                        for other_spec in semantic_specs:
                            if other_spec["key"] == spec["key"]:
                                continue
                            if _contains_any(name, other_spec["positive_keywords"]):
                                confusion_pair_counter[(spec["name"], other_spec["name"])] = confusion_pair_counter.get((spec["name"], other_spec["name"]), 0) + 1

                    dim_proj_count = int((coverage_query or {}).get(f"{spec['dim_alias']}_projects") or 0)
                    dim_trace_proj_count = int((coverage_query or {}).get(f"{spec['dim_alias']}_traceable_projects") or 0)
                    evidence_alignment_rate = round(dim_trace_proj_count / max(1, dim_proj_count), 4) if dim_proj_count > 0 else 0
                    closure_pass_count = sum(
                        1
                        for row in audit_project_rows
                        if int(row.get(f"{spec['dim_alias']}_count") or 0) > 0
                        and any(int(row.get(field_name) or 0) > 0 for field_name in spec["closure_fields"])
                    )
                    closure_rate = round(closure_pass_count / max(1, dim_proj_count), 4) if dim_proj_count > 0 else 0
                    boundary_hit_rate = round(boundary_hits / max(1, total_items), 4) if total_items > 0 else 0
                    counter_signal_rate = round(counter_hits / max(1, total_items), 4) if total_items > 0 else 0
                    validity_score = round(
                        boundary_hit_rate * 0.35
                        + (1 - counter_signal_rate) * 0.20
                        + evidence_alignment_rate * 0.25
                        + closure_rate * 0.20,
                        4,
                    )
                    semantic_weighted_total += total_items
                    semantic_score_accumulator += validity_score * total_items
                    label_validity_details.append({
                        "key": spec["key"],
                        "name": spec["name"],
                        "theory_basis": spec["theory_basis"],
                        "total_items": total_items,
                        "boundary_hit_count": boundary_hits,
                        "boundary_hit_rate": boundary_hit_rate,
                        "counter_signal_count": counter_hits,
                        "counter_signal_rate": counter_signal_rate,
                        "evidence_alignment_count": dim_trace_proj_count,
                        "evidence_alignment_rate": evidence_alignment_rate,
                        "closure_pass_count": closure_pass_count,
                        "closure_rate": closure_rate,
                        "validity_score": validity_score,
                        "positive_cues": spec["positive_keywords"][:6],
                        "common_confusions": spec["counter_keywords"][:5],
                        "closure_fields": spec["closure_fields"],
                    })

                confusion_pairs = sorted(
                    [
                        {
                            "from_label": src,
                            "to_label": dst,
                            "suspected_count": cnt,
                            "suspected_rate": round(
                                cnt / max(
                                    1,
                                    next(
                                        (item["total_items"] for item in label_validity_details if item["name"] == src),
                                        1,
                                    ),
                                ),
                                4,
                            ),
                        }
                        for (src, dst), cnt in confusion_pair_counter.items()
                    ],
                    key=lambda item: item["suspected_count"],
                    reverse=True,
                )[:6]
                semantic_validity = {
                    "methodology": "采用基于理论边界的弱监督代理法，不直接宣称严格语义准确率。方法把标签判定拆成四个可量化代理维度：标签边界命中、反例触发、证据-标签一致、结构闭环。",
                    "strategy": [
                        "理论锚点：每个标签先绑定到 Lean Canvas / BMC / Design Thinking 等经典框架中的对应概念。",
                        "边界规则：为每个标签定义正向语义线索与反向混淆线索，统计命中与误触发情况。",
                        "证据一致：检查含该标签的项目里，有多少项目能回到带 quote/source_unit 的证据。",
                        "结构闭环：检查标签是否与其应出现的上下游标签共同出现，例如痛点是否接到方案。",
                    ],
                    "score_formula": semantic_score_formula,
                    "overall_validity_score": round(semantic_score_accumulator / max(1, semantic_weighted_total), 4),
                    "labels": label_validity_details,
                    "confusion_pairs": confusion_pairs,
                }

                # 5. Framework Alignment
                KB_FRAMEWORK_MAP = {
                    "Lean Canvas": {
                        "mapped_dims": ["痛点", "方案", "目标用户", "商业模式", "市场"],
                        "dims_keys": ["pain_points", "solutions", "stakeholders", "business_models", "markets"],
                    },
                    "Business Model Canvas": {
                        "mapped_dims": ["目标用户", "方案", "商业模式", "市场", "执行步骤"],
                        "dims_keys": ["stakeholders", "solutions", "business_models", "markets", "execution_steps"],
                    },
                    "Porter Value Chain": {
                        "mapped_dims": ["方案", "创新点", "执行步骤", "风控"],
                        "dims_keys": ["solutions", "innovations", "execution_steps", "risk_controls"],
                    },
                }
                fw_alignment = []
                for fw_name, fw_info in KB_FRAMEWORK_MAP.items():
                    matched = sum(1 for dk in fw_info["dims_keys"] if dims.get(dk, 0) > 0)
                    fw_alignment.append({
                        "framework": fw_name,
                        "matched_dims": fw_info["mapped_dims"],
                        "coverage": round(matched / max(1, len(fw_info["dims_keys"])), 2),
                    })

                avg_missing_rate = round(
                    sum(item["missing_rate"] for item in dimension_missing_rate) / max(1, len(dimension_missing_rate)),
                    4,
                )
                missing_control = round(1 - avg_missing_rate, 4)
                adjusted_missing_control = round(
                    1 - (weighted_missing_sum / max(1e-9, weighted_missing_denominator)),
                    4,
                )

                # 6. Composite
                # v2 权重（纳入 semantic_validity 与 audit_pass_rate，替代"只看结构不看内容"）：
                #   0.12 类别均衡 + 0.12 维度均衡 + 0.15 维度覆盖
                # + 0.12 实体可追溯 + 0.12 项目可追溯覆盖 + 0.07 缺失控制
                # + 0.15 语义有效性（代理）+ 0.15 规则核验通过率 = 1.00
                semantic_overall = float(semantic_validity.get("overall_validity_score") or 0.0)
                audit_overall = float(audit_summary.get("overall_pass_rate") or 0.0)
                dim_coverage_val = dim_covered / max(1, n_dim_types)
                composite = round(
                    cat_balance * 0.12
                    + dim_balance * 0.12
                    + dim_coverage_val * 0.15
                    + traceability_rate * 0.12
                    + project_traceable_coverage * 0.12
                    + adjusted_missing_control * 0.07
                    + semantic_overall * 0.15
                    + audit_overall * 0.15,
                    4,
                )
                score_breakdown = [
                    {
                        "key": "category_balance",
                        "label": "类别均衡度",
                        "value": cat_balance,
                        "weight": 0.12,
                        "weighted_score": round(cat_balance * 12, 2),
                        "formula": "Shannon 熵归一化: H/log2(N)",
                    },
                    {
                        "key": "dimension_balance",
                        "label": "维度均衡度",
                        "value": dim_balance,
                        "weight": 0.12,
                        "weighted_score": round(dim_balance * 12, 2),
                        "formula": "各维度实体数分布的 Shannon 熵归一化",
                    },
                    {
                        "key": "dimension_coverage",
                        "label": "维度覆盖率",
                        "value": round(dim_coverage_val, 4),
                        "weight": 0.15,
                        "weighted_score": round(dim_coverage_val * 15, 2),
                        "formula": "有实体维度数 / 总维度数",
                    },
                    {
                        "key": "traceability_rate",
                        "label": "实体可追溯率",
                        "value": traceability_rate,
                        "weight": 0.12,
                        "weighted_score": round(traceability_rate * 12, 2),
                        "formula": "有 quote/source_unit 的实体数 / 总实体数",
                    },
                    {
                        "key": "project_traceable_coverage",
                        "label": "项目可追溯覆盖",
                        "value": project_traceable_coverage,
                        "weight": 0.12,
                        "weighted_score": round(project_traceable_coverage * 12, 2),
                        "formula": "至少含 1 条可追溯证据的项目数 / 总项目数",
                    },
                    {
                        "key": "adjusted_missing_control",
                        "label": "缺失控制（频次修正）",
                        "value": adjusted_missing_control,
                        "weight": 0.07,
                        "weighted_score": round(adjusted_missing_control * 7, 2),
                        "formula": "1 - 加权平均维度缺失率；执行步骤/风控按低频维度降低缺失惩罚",
                    },
                    {
                        "key": "semantic_validity",
                        "label": "标签语义有效性",
                        "value": round(semantic_overall, 4),
                        "weight": 0.15,
                        "weighted_score": round(semantic_overall * 15, 2),
                        "formula": "0.35×边界命中率 + 0.20×(1-反例触发率) + 0.25×证据一致率 + 0.20×结构闭环率（四代理加权平均）",
                    },
                    {
                        "key": "audit_pass_rate",
                        "label": "规则核验通过率",
                        "value": round(audit_overall, 4),
                        "weight": 0.15,
                        "weighted_score": round(audit_overall * 15, 2),
                        "formula": "全体项目规则总通过数 / 规则核查总数（audit_summary.overall_pass_rate）",
                    },
                ]

                # ── 六维扩展指标（B/E/D/A/C）──────────────────────
                try:
                    canonical_doc = load_canonical_concepts()
                    canonical_coverage = compute_canonical_coverage(session, canonical_doc)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("canonical_coverage failed: %s", exc)
                    canonical_coverage = {"error": str(exc)}

                try:
                    canonical_top_entities = compute_top_entities_per_label(
                        session,
                        labels=[
                            "PainPoint", "Solution", "BusinessModelAspect", "Market",
                            "InnovationPoint", "Stakeholder", "ExecutionStep", "RiskControlPoint",
                        ],
                        top_k=10,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("top_entities failed: %s", exc)
                    canonical_top_entities = {}

                try:
                    lifecycle_doc = load_lifecycle_map()
                    lifecycle_representativeness = compute_lifecycle_representativeness(session, lifecycle_doc)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("lifecycle_representativeness failed: %s", exc)
                    lifecycle_representativeness = {"error": str(exc)}

                try:
                    ontology_constraints = compute_ontology_constraint_compliance(session)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ontology_constraints failed: %s", exc)
                    ontology_constraints = {"error": str(exc)}

                try:
                    degree_histogram = compute_degree_histogram(session)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("degree_histogram failed: %s", exc)
                    degree_histogram = {"error": str(exc)}

                try:
                    semantic_validity["labels"] = augment_wilson_intervals(semantic_validity.get("labels") or [])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("wilson augmentation failed: %s", exc)

                try:
                    trace_samples = sample_traceability_chains(session, k=3)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("trace_samples failed: %s", exc)
                    trace_samples = []

                rationality = {
                    "representativeness": {
                        "category_count": n_cats,
                        "category_balance": cat_balance,
                        "total_projects": total_projects,
                        "category_distribution": [{"name": c.get("name", ""), "count": c.get("count", 0)} for c in categories],
                    },
                    "content_richness": {
                        "dimension_balance": dim_balance,
                        "dimension_coverage": round(dim_covered / n_dim_types, 4),
                        "dimensions_detail": [
                            {"name": dim_names_list[i], "count": dim_values[i]}
                            for i in range(n_dim_types)
                        ],
                        "avg_entities_per_project": avg_entities_per_project,
                        "evidence_density": evidence_density,
                        "total_entities": dim_total_ents,
                    },
                    "node_quality": {
                        "total_dim_entities": total_dim_entities,
                        "shared_entities": shared_entities,
                        "sharing_rate": sharing_rate,
                        "avg_projects_per_entity": avg_proj_per_ent,
                    },
                    "graph_structure": {
                        "total_nodes": total_nodes,
                        "total_relationships": total_rels,
                        "graph_density": graph_density,
                        "avg_degree": avg_degree,
                        "max_possible_edges": max_possible_edges,
                        "project_anchor_relationships": project_anchor_relationships,
                        "project_anchor_ratio": project_anchor_ratio,
                        "isolated_nodes": isolated_nodes,
                        "degree1_nodes": degree1_nodes,
                        "degree_le2_nodes": degree_le2_nodes,
                        "sparse_node_ratio": sparse_node_ratio,
                    },
                    "extraction_quality": {
                        "traceability_rate": traceability_rate,
                        "traceable_entities": total_traceable_entities,
                        "total_entities": total_entities_for_trace,
                        "project_evidence_coverage": project_evidence_coverage,
                        "project_traceable_coverage": project_traceable_coverage,
                        "projects_with_evidence": projects_with_evidence,
                        "projects_with_traceable_evidence": projects_with_traceable_evidence,
                        "dimension_missing_rate": dimension_missing_rate,
                        "dimension_overrepresented": sorted(
                            dimension_overrepresented,
                            key=lambda item: item["ratio_to_mean"],
                            reverse=True,
                        ),
                        "dimension_underrepresented": sorted(
                            dimension_underrepresented,
                            key=lambda item: item["ratio_to_mean"],
                        ),
                        "evidence_backed_dimensions": sorted(
                            evidence_backed_dimensions,
                            key=lambda item: item["evidence_backed_rate"],
                            reverse=True,
                        ),
                        "sample_audit_pool": sample_audit_pool,
                        "sample_audit_summary": sample_audit_summary,
                        "audit_summary": audit_summary,
                        "semantic_validity": semantic_validity,
                        "low_frequency_dimensions": low_frequency_dimensions,
                        "missing_control": missing_control,
                        "adjusted_missing_control": adjusted_missing_control,
                    },
                    "framework_alignment": fw_alignment,
                    "composite_score": composite,
                    "score_breakdown": score_breakdown,
                    "score_formula": "0.12×cat_balance + 0.12×dim_balance + 0.15×dim_coverage + 0.12×traceability_rate + 0.12×project_traceable_coverage + 0.07×adjusted_missing_control + 0.15×semantic_validity + 0.15×audit_pass_rate",
                    # ── 六维扩展指标（不进入 composite，独立披露） ──
                    "canonical_coverage": canonical_coverage,
                    "canonical_top_entities": canonical_top_entities,
                    "lifecycle_representativeness": lifecycle_representativeness,
                    "ontology_constraints": ontology_constraints,
                    "degree_histogram": degree_histogram,
                    "trace_samples": trace_samples,
                    "method_disclosures": {
                        "references": [
                            {"key": "zaveri2016", "citation": "Zaveri, A. et al. (2016). Quality assessment for Linked Data: A Survey. Semantic Web 7(1), 63-93."},
                            {"key": "paulheim2017", "citation": "Paulheim, H. (2017). Knowledge Graph Refinement: A Survey of Approaches and Evaluation Methods. Semantic Web 8(3), 489-508."},
                            {"key": "farber2018", "citation": "Färber, M. et al. (2018). Linked Data Quality of DBpedia, Freebase, OpenCyc, Wikidata, and YAGO. Semantic Web 9(1), 77-129."},
                            {"key": "osterwalder2010", "citation": "Osterwalder, A. & Pigneur, Y. (2010). Business Model Generation."},
                            {"key": "ries2011", "citation": "Ries, E. (2011). The Lean Startup."},
                        ],
                        "limitations": [
                            "本项目无人工金标准（ground truth）标注，正确性采用弱监督四代理法（Paulheim 2017）。",
                            "核心概念清单基于关键词匹配（contains），可能低估同义词未覆盖的命中；后续版本拟接入向量召回。",
                            "行业→阶段映射是静态启发式，个别案例可能被错分；整体统计在大样本上成立。",
                        ],
                        "chip_types": {
                            "hard": "硬指标（直接计数/比例/图结构）",
                            "proxy": "代理指标（弱监督，无金标）",
                            "sample": "抽样估计（Wilson 置信区间）",
                        },
                    },
                }

                return {
                    "total_nodes": total_nodes,
                    "total_relationships": total_rels,
                    "total_projects": total_projects,
                    "total_categories": node_labels.get("Category", 0),
                    "node_labels": node_labels,
                    "relationship_types": rel_types,
                    "categories": categories,
                    "dimensions": dims,
                    "hypergraph": {"nodes": hyper_nodes, "edges": hyper_edges},
                    "ontology_nodes": onto_nodes,
                    "risk_rules": risk_rules,
                    "rubric_items": rubric_items,
                    "rationality": rationality,
                }
            return self._query_with_fallback(_query)
        except Exception as exc:
            return {"error": f"kb_stats query failed: {exc}"}

    def get_kb_insights(self, limit: int = 8) -> dict[str, Any]:
        """Return top entities across key dimensions + sample project excerpts for teacher overview."""
        try:
            def _query(session):
                results: dict[str, Any] = {}
                dim_queries = {
                    "top_pains": ("PainPoint", "HAS_PAIN"),
                    "top_solutions": ("Solution", "HAS_SOLUTION"),
                    "top_innovations": ("InnovationPoint", "HAS_INNOVATION"),
                    "top_biz_models": ("BusinessModelAspect", "HAS_BUSINESS_MODEL"),
                    "top_markets": ("Market", "HAS_MARKET_ANALYSIS"),
                    "top_risks": ("RiskControlPoint", "HAS_RISK_CONTROL"),
                }
                for key, (node_label, rel_type) in dim_queries.items():
                    rows = list(session.run(
                        f"MATCH (p:Project)-[:{rel_type}]->(n:{node_label}) "
                        f"RETURN n.name AS name, count(DISTINCT p) AS projects "
                        f"ORDER BY projects DESC LIMIT $lim",
                        lim=limit,
                    ))
                    results[key] = [{"name": r["name"], "projects": int(r["projects"])} for r in rows]

                rubric_rows = list(session.run(
                    "MATCH (r:RubricItem) RETURN r.id AS id, r.weight AS weight, r.description AS desc "
                    "ORDER BY r.weight DESC LIMIT $lim", lim=limit
                ))
                results["rubric_items"] = [
                    {"id": r["id"], "weight": r["weight"], "description": r["desc"]}
                    for r in rubric_rows
                ]

                risk_rule_rows = list(session.run(
                    "MATCH (r:RiskRule) "
                    "OPTIONAL MATCH (p:Project)-[:HITS_RULE]->(r) "
                    "RETURN r.id AS id, r.description AS desc, r.severity AS severity, count(DISTINCT p) AS hits "
                    "ORDER BY hits DESC LIMIT $lim", lim=limit
                ))
                results["risk_rules_detail"] = [
                    {"id": r["id"], "description": r["desc"], "severity": r["severity"], "hits": int(r["hits"])}
                    for r in risk_rule_rows
                ]

                sample_rows = list(session.run(
                    "MATCH (p:Project)-[:BELONGS_TO]->(c:Category) "
                    "OPTIONAL MATCH (p)-[:HAS_PAIN]->(pain:PainPoint) "
                    "OPTIONAL MATCH (p)-[:HAS_SOLUTION]->(sol:Solution) "
                    "OPTIONAL MATCH (p)-[:HAS_INNOVATION]->(inn:InnovationPoint) "
                    "WITH p, c, collect(DISTINCT pain.name)[..2] AS pains, "
                    "     collect(DISTINCT sol.name)[..2] AS sols, "
                    "     collect(DISTINCT inn.name)[..1] AS inns "
                    "RETURN p.name AS name, c.name AS category, "
                    "       p.confidence AS confidence, pains, sols, inns "
                    "ORDER BY p.confidence DESC LIMIT 12"
                ))
                results["sample_cases"] = [
                    {
                        "name": r["name"], "category": r["category"],
                        "confidence": r["confidence"],
                        "pains": list(r["pains"] or []),
                        "solutions": list(r["sols"] or []),
                        "innovations": list(r["inns"] or []),
                    }
                    for r in sample_rows
                ]

                return results
            return self._query_with_fallback(_query)
        except Exception as exc:
            return {"error": f"kb_insights query failed: {exc}"}

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

    def merge_student_entities(
        self, project_id: str, entities: list[dict], relationships: list[dict],
        conversation_id: str = "",
    ) -> dict[str, Any]:
        """Write student-extracted KG entities into Neo4j with session isolation.

        Student entities use the `StudentEntity` label (NOT `Entity`) so they
        never pollute the standard case library.  Each node carries
        `conversation_id` and `source_project` so they can be queried per-session.
        """
        if not entities:
            return {"ok": True, "merged": 0}
        conv_id = str(conversation_id or project_id)[:120]
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
                        MERGE (e:StudentEntity {label: $label, conversation_id: $cid})
                        ON CREATE SET e.type = $etype, e.source_project = $pid, e.id = $eid
                        ON MATCH SET e.last_seen_project = $pid
                        """,
                        label=label, etype=etype, pid=project_id, eid=eid, cid=conv_id,
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
                        MATCH (a:StudentEntity {label: $src, conversation_id: $cid}),
                              (b:StudentEntity {label: $tgt, conversation_id: $cid})
                        MERGE (a)-[r:STUDENT_RELATES_TO {description: $desc}]->(b)
                        ON CREATE SET r.source_project = $pid
                        """,
                        src=src_label, tgt=tgt_label, desc=desc, pid=project_id, cid=conv_id,
                    )
                return merged

            merged = self._query_with_fallback(_write)
            return {"ok": True, "merged": merged}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def find_similar_entities(self, labels: list[str], limit: int = 5) -> list[dict[str, Any]]:
        """Find entities in Neo4j that match given labels and return their relationships.

        Dual-search: first tries Entity nodes (student-uploaded KG), then falls
        back to case-library dimension nodes (PainPoint, Solution, etc.) for
        broader recall.
        """
        if not labels:
            return []
        try:
            def _query(session):
                results = []
                seen: set[str] = set()

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
                        key = f"{row.get('entity')}|{row.get('related_entity')}"
                        if key not in seen:
                            seen.add(key)
                            results.append(dict(row))

                if len(results) < limit:
                    remaining = limit - len(results)
                    for label in labels[:4]:
                        if len(label) < 2:
                            continue
                        rows = list(session.run(
                            """
                            MATCH (dim)<-[r]-(p:Project)
                            WHERE (dim:PainPoint OR dim:Solution OR dim:InnovationPoint
                                   OR dim:BusinessModelAspect OR dim:Market OR dim:Evidence)
                              AND toLower(dim.name) CONTAINS toLower($label)
                            OPTIONAL MATCH (p)-[:BELONGS_TO]->(cat:Category)
                            RETURN dim.name AS entity, labels(dim)[0] AS type,
                                   p.name AS project, type(r) AS rel_type,
                                   cat.name AS related_entity
                            LIMIT $limit
                            """,
                            label=label, limit=remaining,
                        ))
                        for row in rows:
                            key = f"{row.get('entity')}|{row.get('project')}"
                            if key not in seen:
                                seen.add(key)
                                results.append(dict(row))
                            if len(results) >= limit:
                                break
                        if len(results) >= limit:
                            break

                return results[:limit]

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

    def search_cases_by_dimension(
        self,
        category: str | None = None,
        risk_rule_ids: list[str] | None = None,
        rubric_items: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Structured search over the standard case library (Project nodes).

        Unlike ``search_nodes`` (generic substring match), this leverages the
        graph schema (Project -> Category, Project -> RiskRule, Project -> RubricItem)
        to perform **precise** filtering and return rich metadata for agent context.
        """
        try:
            def _query(session):
                conditions: list[str] = []
                params: dict[str, Any] = {"limit": limit}

                if category:
                    conditions.append("c.name = $category")
                    params["category"] = category

                if risk_rule_ids:
                    conditions.append(
                        "ANY(rid IN $risk_rule_ids WHERE (p)-[:HITS_RULE]->(:RiskRule {id: rid}))"
                    )
                    params["risk_rule_ids"] = list(risk_rule_ids)[:6]

                if rubric_items:
                    conditions.append(
                        "ANY(rn IN $rubric_items WHERE (p)-[:EVALUATED_BY]->(:RubricItem {name: rn}))"
                    )
                    params["rubric_items"] = list(rubric_items)[:6]

                where_clause = " AND ".join(conditions) if conditions else "true"
                cypher = f"""
                    MATCH (p:Project)-[:BELONGS_TO]->(c:Category)
                    WHERE {where_clause}
                    OPTIONAL MATCH (p)-[:HITS_RULE]->(rr:RiskRule)
                    OPTIONAL MATCH (p)-[ev:EVALUATED_BY]->(ri:RubricItem)
                    WITH p, c,
                         collect(DISTINCT rr.id) AS rules,
                         collect(DISTINCT CASE WHEN ev.covered THEN ri.name END) AS covered_rubrics,
                         collect(DISTINCT CASE WHEN NOT ev.covered THEN ri.name END) AS uncovered_rubrics
                    RETURN p.id AS project_id,
                           p.name AS project_name,
                           c.name AS category,
                           p.confidence AS confidence,
                           rules,
                           covered_rubrics,
                           uncovered_rubrics,
                           size(covered_rubrics) AS covered_count,
                           size(uncovered_rubrics) AS uncovered_count
                    ORDER BY covered_count DESC
                    LIMIT $limit
                """
                rows = list(session.run(cypher, **params))
                return [dict(r) for r in rows]

            return self._query_with_fallback(_query)
        except Exception as exc:
            logger.warning("search_cases_by_dimension failed: %s", exc)
            return []

    _DIM_NODE_MAP: dict[str, tuple[str, str]] = {
        "pain_point":      ("PainPoint",           "HAS_PAIN"),
        "solution":        ("Solution",             "HAS_SOLUTION"),
        "business_model":  ("BusinessModelAspect",  "HAS_BUSINESS_MODEL"),
        "technology":      ("Solution",             "HAS_SOLUTION"),
        "market":          ("Market",               "HAS_MARKET_ANALYSIS"),
        "competitor":      ("Market",               "HAS_MARKET_ANALYSIS"),
        "innovation":      ("InnovationPoint",      "HAS_INNOVATION"),
        "evidence":        ("Evidence",             "HAS_EVIDENCE"),
        "resource":        ("ExecutionStep",        "HAS_EXECUTION_STEP"),
        "team":            ("ExecutionStep",        "HAS_EXECUTION_STEP"),
        "stakeholder":     ("PainPoint",            "HAS_PAIN"),
        "execution_step":  ("ExecutionStep",        "HAS_EXECUTION_STEP"),
        "risk_control":    ("Evidence",             "HAS_EVIDENCE"),
    }

    def search_by_dimension_entities(
        self,
        entity_labels: list[str],
        entity_types: list[str],
        exclude_ids: list[str] | None = None,
        limit: int = 4,
        category: str = "",
    ) -> list[dict[str, Any]]:
        """Graph-structural cross-project retrieval (dual-channel #2).

        Three complementary strategies run in one session:
        1. **Shared-node fan-out** — find projects that share the SAME dimension
           nodes (e.g. same PainPoint, same BusinessModelAspect) → "who else
           faces this exact pain?" / "who else uses this revenue model?"
        2. **Structural-pattern match** — find projects that have the same
           graph topology (e.g. Project→PainPoint→Solution chain complete)
           where the student's chain is broken → complementary inspiration.
        3. **Keyword fallback** — CONTAINS on node names for broader recall.

        Returns projects ranked by structural relevance score.
        ``category`` optionally biases ranking toward same-category projects.
        """
        if not entity_labels:
            return []
        _exclude = set(exclude_ids or [])
        _category = str(category or "").strip().lower()
        pairs: list[tuple[str, str, str, str]] = []
        _skipped_types: list[str] = []
        for lbl, etype in zip(entity_labels[:16], entity_types[:16]):
            mapping = self._DIM_NODE_MAP.get(etype)
            if not mapping:
                _skipped_types.append(f"{lbl}({etype})")
                continue
            keyword = str(lbl).strip()
            if len(keyword) < 2:
                continue
            node_label, rel_type = mapping
            pairs.append((keyword, etype, node_label, rel_type))
        if _skipped_types:
            import logging
            logging.getLogger(__name__).info(
                "search_by_dimension_entities: skipped unmapped types: %s", _skipped_types
            )
        if not pairs:
            import logging
            logging.getLogger(__name__).warning(
                "search_by_dimension_entities: no valid pairs after mapping (input types: %s)",
                list(zip(entity_labels[:5], entity_types[:5])),
            )
            return []

        type_groups: dict[str, list[str]] = {}
        for kw, etype, nl, rt in pairs:
            type_groups.setdefault(etype, []).append(kw)
        _student_keywords = {kw.lower() for kw, _, _, _ in pairs}

        try:
            def _query(session):
                all_hits: dict[str, dict[str, Any]] = {}

                def _add_hit(pid, pname, category, dim_type, node_name, source):
                    if pid in _exclude:
                        return
                    if pid not in all_hits:
                        all_hits[pid] = {
                            "project_id": pid,
                            "project_name": pname or pid,
                            "category": category or "",
                            "matched_dimensions": [],
                            "matched_nodes": [],
                            "match_sources": [],
                            "retrieval_channel": "graph",
                        }
                    entry = all_hits[pid]
                    if dim_type and dim_type not in entry["matched_dimensions"]:
                        entry["matched_dimensions"].append(dim_type)
                    nd = f"{dim_type}:{node_name}" if node_name else dim_type
                    if nd not in entry["matched_nodes"]:
                        entry["matched_nodes"].append(nd)
                    if source not in entry["match_sources"]:
                        entry["match_sources"].append(source)

                # Strategy 1: Shared-node fan-out
                # "Find other projects connected to the SAME dimension node"
                for keyword, etype, node_label, rel_type in pairs[:6]:
                    try:
                        rows = list(session.run(
                            f"""
                            MATCH (n:{node_label})<-[:{rel_type}]-(p1:Project)
                            WHERE toLower(n.name) CONTAINS toLower($kw)
                            WITH n
                            MATCH (n)<-[:{rel_type}]-(p2:Project)
                            OPTIONAL MATCH (p2)-[:BELONGS_TO]->(cat:Category)
                            RETURN DISTINCT p2.id AS pid, p2.name AS pname,
                                   cat.name AS category, n.name AS shared_node
                            LIMIT 6
                            """,
                            kw=keyword,
                        ))
                        for r in rows:
                            _add_hit(r["pid"], r["pname"], r["category"],
                                     etype, r["shared_node"], "shared_node")
                    except Exception:
                        pass

                # Strategy 2: Structural complement (scoped by student keywords)
                # Only pick projects whose complement nodes are textually
                # relevant to the student, preventing generic "any project
                # with evidence" results.
                student_types = set(type_groups.keys())
                complement_targets = []
                if "pain_point" in student_types and "business_model" not in student_types:
                    complement_targets.append(("HAS_PAIN", "HAS_BUSINESS_MODEL", "business_model"))
                if "solution" in student_types and "evidence" not in student_types:
                    complement_targets.append(("HAS_SOLUTION", "HAS_EVIDENCE", "evidence"))
                if "pain_point" in student_types and "evidence" not in student_types:
                    complement_targets.append(("HAS_PAIN", "HAS_EVIDENCE", "evidence"))
                if "market" not in student_types:
                    complement_targets.append(("HAS_SOLUTION", "HAS_MARKET_ANALYSIS", "market"))

                for has_rel, needs_rel, dim_label in complement_targets[:3]:
                    try:
                        rows = list(session.run(
                            f"""
                            MATCH (p:Project)-[:{has_rel}]->(src_node)
                            WHERE EXISTS {{ MATCH (p)-[:{needs_rel}]->() }}
                            OPTIONAL MATCH (p)-[:BELONGS_TO]->(cat:Category)
                            OPTIONAL MATCH (p)-[:{needs_rel}]->(comp_node)
                            RETURN DISTINCT p.id AS pid, p.name AS pname,
                                   cat.name AS category,
                                   comp_node.name AS comp_name,
                                   src_node.name AS src_name
                            LIMIT 12
                            """,
                        ))
                        for r in rows:
                            src_name = str(r.get("src_name") or "").lower()
                            pname = str(r.get("pname") or "").lower()
                            has_kw_overlap = any(
                                kw in src_name or kw in pname
                                for kw in _student_keywords
                                if len(kw) >= 2
                            )
                            cat_match = (
                                _category
                                and str(r.get("category") or "").strip().lower() == _category
                            )
                            if has_kw_overlap or cat_match:
                                _add_hit(r["pid"], r["pname"], r["category"],
                                         dim_label, r["comp_name"], "complement")
                    except Exception:
                        pass

                # Strategy 3: Keyword fallback (narrower scope)
                for keyword, etype, node_label, rel_type in pairs[:6]:
                    if any(keyword.lower() in " ".join(h.get("matched_nodes", [])).lower()
                           for h in all_hits.values()):
                        continue
                    try:
                        rows = list(session.run(
                            f"""
                            MATCH (p:Project)-[:{rel_type}]->(n:{node_label})
                            WHERE toLower(n.name) CONTAINS toLower($kw)
                            OPTIONAL MATCH (p)-[:BELONGS_TO]->(cat:Category)
                            RETURN DISTINCT p.id AS pid, p.name AS pname,
                                   cat.name AS category, n.name AS matched_node
                            LIMIT 5
                            """,
                            kw=keyword,
                        ))
                        for r in rows:
                            _add_hit(r["pid"], r["pname"], r["category"],
                                     etype, r["matched_node"], "keyword")
                    except Exception:
                        pass

                # Rank: keyword relevance first, then category match, then
                # source quality, then dimension breadth.
                def _score(h):
                    s = 0.0
                    nodes_text = " ".join(
                        str(n) for n in h.get("matched_nodes", [])
                    ).lower()
                    pname_text = str(h.get("project_name", "")).lower()
                    kw_hits = sum(
                        1 for kw in _student_keywords
                        if len(kw) >= 2 and (kw in nodes_text or kw in pname_text)
                    )
                    s += kw_hits * 5
                    if _category and str(h.get("category", "")).strip().lower() == _category:
                        s += 4
                    sources = h.get("match_sources", [])
                    if "shared_node" in sources:
                        s += 3
                    if "complement" in sources:
                        s += 1
                    s += len(h.get("matched_dimensions", []))
                    return s

                ranked = sorted(all_hits.values(), key=_score, reverse=True)[:limit]

                # Enrich top hits with project context (what they did)
                for hit in ranked:
                    pid = hit.get("project_id", "")
                    if not pid:
                        continue
                    try:
                        ctx_rows = list(session.run(
                            """
                            MATCH (p:Project {id: $pid})
                            OPTIONAL MATCH (p)-[:HAS_PAIN]->(pain:PainPoint)
                            OPTIONAL MATCH (p)-[:HAS_SOLUTION]->(sol:Solution)
                            OPTIONAL MATCH (p)-[:HAS_INNOVATION]->(inn:InnovationPoint)
                            OPTIONAL MATCH (p)-[:HAS_BUSINESS_MODEL]->(bm:BusinessModelAspect)
                            OPTIONAL MATCH (p)-[:HAS_EVIDENCE]->(ev:Evidence)
                            RETURN collect(DISTINCT pain.name) AS pains,
                                   collect(DISTINCT sol.name) AS solutions,
                                   collect(DISTINCT inn.name) AS innovations,
                                   collect(DISTINCT bm.name) AS biz_models,
                                   collect(DISTINCT ev.name) AS evidences
                            """,
                            pid=pid,
                        ))
                        if ctx_rows:
                            r = ctx_rows[0]
                            hit["context"] = {
                                "pains": [x for x in (r["pains"] or []) if x][:5],
                                "solutions": [x for x in (r["solutions"] or []) if x][:5],
                                "innovations": [x for x in (r["innovations"] or []) if x][:4],
                                "biz_models": [x for x in (r["biz_models"] or []) if x][:4],
                                "evidences": [x for x in (r["evidences"] or []) if x][:3],
                            }
                    except Exception:
                        pass

                return ranked

            return self._query_with_fallback(_query)
        except Exception as exc:
            logger.warning("search_by_dimension_entities failed: %s", exc)
            return []

    def enrich_rag_hits(
        self,
        case_ids: list[str],
        student_rule_ids: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Batch-enrich RAG-retrieved cases with Neo4j graph context.

        Uses case_id === Project.id bridge to pull rich relationships for
        each RAG hit in a single round-trip, plus rule overlap comparison.
        """
        if not case_ids:
            return {}
        try:
            _student_rules = set(student_rule_ids or [])

            def _query(session):
                rows = list(session.run(
                    """
                    UNWIND $ids AS cid
                    MATCH (p:Project {id: cid})
                    OPTIONAL MATCH (p)-[:BELONGS_TO]->(cat:Category)
                    OPTIONAL MATCH (p)-[:HAS_PAIN]->(pain:PainPoint)
                    OPTIONAL MATCH (p)-[:HAS_SOLUTION]->(sol:Solution)
                    OPTIONAL MATCH (p)-[:HAS_INNOVATION]->(inn:InnovationPoint)
                    OPTIONAL MATCH (p)-[:HAS_BUSINESS_MODEL]->(bm:BusinessModelAspect)
                    OPTIONAL MATCH (p)-[:HITS_RULE]->(rr:RiskRule)
                    OPTIONAL MATCH (p)-[ev:EVALUATED_BY]->(ri:RubricItem)
                    OPTIONAL MATCH (p)-[:HAS_EVIDENCE]->(e:Evidence)
                    OPTIONAL MATCH (p)-[:HAS_MARKET_ANALYSIS]->(mkt:Market)
                    OPTIONAL MATCH (p)-[:HAS_EXECUTION_STEP]->(exec:ExecutionStep)
                    WITH p, cat,
                         collect(DISTINCT pain.name) AS pains,
                         collect(DISTINCT sol.name) AS solutions,
                         collect(DISTINCT inn.name) AS innovations,
                         collect(DISTINCT bm.name) AS biz_models,
                         collect(DISTINCT {id: rr.id, name: rr.name, severity: rr.severity}) AS rules,
                         collect(DISTINCT {item: ri.name, covered: ev.covered, score: ev.score}) AS rubrics,
                         collect(DISTINCT {type: e.type, quote: e.quote}) AS evidences,
                         collect(DISTINCT mkt.name) AS markets,
                         collect(DISTINCT exec.name) AS exec_steps
                    RETURN p.id AS project_id,
                           p.name AS project_name,
                           cat.name AS category,
                           p.confidence AS confidence,
                           pains, solutions, innovations, biz_models,
                           rules, rubrics, evidences, markets, exec_steps
                    """,
                    ids=case_ids[:8],
                ))
                result: dict[str, dict[str, Any]] = {}
                for row in rows:
                    pid = row["project_id"]
                    case_rule_ids = {r["id"] for r in row["rules"] if r.get("id")}
                    covered = [r["item"] for r in row["rubrics"] if r.get("covered")]
                    uncovered = [r["item"] for r in row["rubrics"] if r.get("item") and not r.get("covered")]
                    real_ev = [e for e in row["evidences"] if e.get("quote") and len(str(e["quote"])) > 10]
                    result[pid] = {
                        "neo4j_enriched": True,
                        "graph_pains": [x for x in row["pains"] if x][:5],
                        "graph_solutions": [x for x in row["solutions"] if x][:5],
                        "graph_innovations": [x for x in row["innovations"] if x][:4],
                        "graph_biz_models": [x for x in row["biz_models"] if x][:4],
                        "graph_markets": [x for x in row["markets"] if x][:4],
                        "graph_exec_steps": [x for x in row["exec_steps"] if x][:4],
                        "graph_rules": [
                            {"id": r["id"], "name": r.get("name", ""), "severity": r.get("severity", "")}
                            for r in row["rules"] if r.get("id")
                        ],
                        "graph_rubric_covered": covered,
                        "graph_rubric_uncovered": uncovered,
                        "graph_evidence_count": len(real_ev),
                        "graph_evidence_samples": [
                            {"type": e.get("type", ""), "quote": str(e.get("quote", ""))[:150]}
                            for e in real_ev[:3]
                        ],
                        "rule_overlap": {
                            "shared": sorted(case_rule_ids & _student_rules),
                            "only_in_case": sorted(case_rule_ids - _student_rules),
                            "only_in_student": sorted(_student_rules - case_rule_ids),
                        },
                    }
                return result

            return self._query_with_fallback(_query)
        except Exception as exc:
            logger.warning("enrich_rag_hits failed: %s", exc)
            return {}

    def find_complementary_cases(
        self,
        weak_rubric_items: list[str],
        exclude_ids: list[str] | None = None,
        limit: int = 3,
    ) -> list[str]:
        """Find case_ids whose projects are STRONG in the student's weak dimensions.

        This enables "complementary search": instead of finding similar cases,
        find cases that excel where the student is weakest.
        """
        if not weak_rubric_items:
            return []
        try:
            _excl = exclude_ids or []

            def _query(session):
                rows = list(session.run(
                    """
                    UNWIND $items AS rubric_name
                    MATCH (p:Project)-[ev:EVALUATED_BY]->(ri:RubricItem {name: rubric_name})
                    WHERE ev.covered = true AND NOT p.id IN $exclude
                    WITH p, count(DISTINCT ri) AS covered_count
                    ORDER BY covered_count DESC
                    LIMIT $lim
                    RETURN p.id AS case_id
                    """,
                    items=weak_rubric_items[:5],
                    exclude=_excl,
                    lim=limit,
                ))
                return [row["case_id"] for row in rows if row.get("case_id")]

            return self._query_with_fallback(_query)
        except Exception as exc:
            logger.warning("find_complementary_cases failed: %s", exc)
            return []

    def persist_hypergraph_records(self, records: list[dict[str, Any]], version: str = "v2") -> dict[str, Any]:
        if not records:
            return {"ok": True, "saved": 0, "members": 0, "projects": 0}
        try:
            def _write(session):
                session.run("MATCH (h:Hyperedge) DETACH DELETE h")
                session.run("MATCH (n:HyperNode) WHERE NOT (n)--() OR ALL(r IN [(n)-[rel]-() | type(rel)] WHERE r = 'HAS_MEMBER') DETACH DELETE n")

                edge_params = []
                for rec in records:
                    edge_params.append({
                        "id": rec.get("hyperedge_id", ""),
                        "family": rec.get("type", ""),
                        "label": rec.get("family_label", ""),
                        "category": rec.get("category") or "",
                        "support": int(rec.get("support", 0) or 0),
                        "confidence": float(rec.get("confidence", 0) or 0),
                        "severity": str(rec.get("severity", "") or ""),
                        "score_impact": float(rec.get("score_impact", 0) or 0),
                        "stage_scope": str(rec.get("stage_scope", "") or ""),
                        "teaching_note": str(rec.get("teaching_note", "") or ""),
                        "retrieval_reason": str(rec.get("retrieval_reason", "") or ""),
                        "rule_count": len(rec.get("rules") or []),
                        "rubric_count": len(rec.get("rubrics") or []),
                        "version": version,
                    })
                session.run(
                    """
                    UNWIND $edges AS e
                    MERGE (h:Hyperedge {id: e.id})
                    SET h.family = e.family, h.label = e.label, h.category = e.category,
                        h.support = e.support, h.confidence = e.confidence,
                        h.severity = e.severity, h.score_impact = e.score_impact,
                        h.stage_scope = e.stage_scope, h.teaching_note = e.teaching_note,
                        h.retrieval_reason = e.retrieval_reason,
                        h.rule_count = e.rule_count, h.rubric_count = e.rubric_count,
                        h.version = e.version
                    """,
                    edges=edge_params,
                )
                saved = len(edge_params)

                member_params = []
                for rec in records:
                    eid = rec.get("hyperedge_id", "")
                    for member in rec.get("member_nodes") or []:
                        key = str(member.get("key", "")).strip()
                        if not key:
                            continue
                        member_params.append({
                            "key": key,
                            "type": str(member.get("type", "") or ""),
                            "name": str(member.get("name", "") or ""),
                            "display": str(member.get("display", "") or ""),
                            "edge_id": eid,
                        })
                BATCH = 500
                members = 0
                for i in range(0, len(member_params), BATCH):
                    batch = member_params[i:i + BATCH]
                    session.run(
                        """
                        UNWIND $items AS m
                        MERGE (n:HyperNode {key: m.key})
                        SET n.type = m.type, n.name = m.name, n.display = m.display, n.label = m.display
                        WITH n, m
                        MATCH (h:Hyperedge {id: m.edge_id})
                        MERGE (h)-[:HAS_MEMBER {role: m.type}]->(n)
                        """,
                        items=batch,
                    )
                    members += len(batch)

                rule_params = []
                for rec in records:
                    eid = rec.get("hyperedge_id", "")
                    for rule_id in rec.get("rules") or []:
                        rule_params.append({"edge_id": eid, "rule_id": str(rule_id)})
                if rule_params:
                    session.run(
                        """
                        UNWIND $items AS r
                        MATCH (h:Hyperedge {id: r.edge_id})
                        MATCH (rr:RiskRule {id: r.rule_id})
                        MERGE (h)-[:TRIGGERS_RULE]->(rr)
                        """,
                        items=rule_params,
                    )

                rubric_params = []
                for rec in records:
                    eid = rec.get("hyperedge_id", "")
                    for rubric in rec.get("rubrics") or []:
                        rubric_params.append({"edge_id": eid, "rubric": str(rubric)})
                if rubric_params:
                    session.run(
                        """
                        UNWIND $items AS r
                        MATCH (h:Hyperedge {id: r.edge_id})
                        MATCH (ri:RubricItem {name: r.rubric})
                        MERGE (h)-[:ALIGNS_WITH]->(ri)
                        """,
                        items=rubric_params,
                    )

                project_params = []
                for rec in records:
                    eid = rec.get("hyperedge_id", "")
                    for pid in rec.get("source_project_ids") or []:
                        project_params.append({"edge_id": eid, "project_id": str(pid)})
                if project_params:
                    session.run(
                        """
                        UNWIND $items AS p
                        MATCH (h:Hyperedge {id: p.edge_id})
                        MATCH (pr:Project {id: p.project_id})
                        MERGE (h)-[:SUPPORTED_BY]->(pr)
                        """,
                        items=project_params,
                    )

                return {"saved": saved, "members": members, "projects": len(project_params)}

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

    # ── KG Explorer panel APIs ──────────────────────────────────

    DIMENSION_SUBGRAPHS: list[tuple[str, str, str, str]] = [
        ("pain", "PainPoint", "HAS_PAIN", "#f87171"),
        ("solution", "Solution", "HAS_SOLUTION", "#60a5fa"),
        ("innovation", "InnovationPoint", "HAS_INNOVATION", "#a78bfa"),
        ("business_model", "BusinessModelAspect", "HAS_BUSINESS_MODEL", "#34d399"),
        ("market", "Market", "HAS_MARKET_ANALYSIS", "#fbbf24"),
        ("execution", "ExecutionStep", "HAS_EXECUTION_STEP", "#38bdf8"),
        ("risk_control", "RiskControlPoint", "HAS_RISK_CONTROL", "#fb923c"),
        ("evidence", "Evidence", "HAS_EVIDENCE", "#94a3b8"),
        ("stakeholder", "Stakeholder", "HAS_TARGET_USER", "#f0abfc"),
        # 新增赛事类型
        ("entrepreneur_domain", "Entrepreneurship", "ENTREPRENEURSHIP", "#fb923c"),
        ("competition", "Competition", "PARTICIPATED_IN", "#f472b6"),
        # 创业案例特殊处理见下
    ]

    EXTRA_SUBGRAPHS: list[tuple[str, str, str, str]] = [
        ("category", "Category", "BELONGS_TO", "#c4b5fd"),
        ("risk_rule", "RiskRule", "HITS_RULE", "#fca5a5"),
        ("rubric", "RubricItem", "EVALUATED_BY", "#6ee7b7"),
        # 创业案例特殊处理见下
    ]

    SG_LABELS: dict[str, str] = {
        "pain": "痛点", "solution": "方案", "innovation": "创新点",
        "business_model": "商业模式", "market": "市场分析", "execution": "执行计划",
        "risk_control": "风控", "evidence": "证据", "stakeholder": "利益方",
        "category": "类别", "risk_rule": "风险规则", "rubric": "评审标准",
        "entrepreneur_domain": "创业领域", "competition": "赛事类型",
        "entrepreneurship": "创业案例", "innovation_case": "创新案例",
        "project": "项目",
    }

    def get_subgraph_overview(self) -> dict[str, Any]:
        """Return meta-level overview: one node per subgraph + cross-subgraph links, with competition/entrepreneurship support."""
        try:
            def _query(session):
                all_sgs = self.DIMENSION_SUBGRAPHS + self.EXTRA_SUBGRAPHS
                sg_meta: list[dict] = []
                sg_node_counts: dict[str, int] = {}

                project_rows = list(session.run(
                    "MATCH (p:Project) RETURN count(p) AS cnt"
                ))
                project_count = project_rows[0]["cnt"] if project_rows else 0
                sg_node_counts["project"] = project_count

                # 标准子图
                for sg_id, node_label, rel_type, color in all_sgs:
                    count_rows = list(session.run(
                        f"MATCH (n:{node_label}) RETURN count(n) AS cnt"
                    ))
                    node_count = count_rows[0]["cnt"] if count_rows else 0
                    sg_node_counts[sg_id] = node_count

                    project_link_rows = list(session.run(
                        f"MATCH (p:Project)-[:{rel_type}]->(n:{node_label}) "
                        f"RETURN count(DISTINCT p) AS projects"
                    ))
                    linked_projects = project_link_rows[0]["projects"] if project_link_rows else 0

                    edge_rows = list(session.run(
                        f"MATCH (p:Project)-[r:{rel_type}]->(n:{node_label}) RETURN count(r) AS cnt"
                    ))
                    edge_count = edge_rows[0]["cnt"] if edge_rows else 0

                    top_rows = list(session.run(
                        f"MATCH (p:Project)-[:{rel_type}]->(n:{node_label}) "
                        f"WITH n.name AS name, count(DISTINCT p) AS freq "
                        f"ORDER BY freq DESC LIMIT 5 "
                        f"RETURN name, freq"
                    ))

                    cat_rows = list(session.run(
                        f"MATCH (p:Project)-[:{rel_type}]->(n:{node_label}), "
                        f"      (p)-[:BELONGS_TO]->(c:Category) "
                        f"RETURN c.name AS cat, count(DISTINCT n) AS cnt "
                        f"ORDER BY cnt DESC LIMIT 10"
                    ))

                    sg_meta.append({
                        "id": sg_id,
                        "label": self.SG_LABELS.get(sg_id, node_label),
                        "node_label": node_label,
                        "color": color,
                        "node_count": node_count,
                        "edge_count": edge_count,
                        "linked_projects": linked_projects,
                        "top_nodes": [{"name": r["name"], "freq": r["freq"]} for r in top_rows],
                        "category_dist": [{"cat": r["cat"], "count": r["cnt"]} for r in cat_rows],
                        "type": "competition" if sg_id in ["competition", "competition_domain"] else "dimension",
                    })

                # 创业领域（创业项目）
                ent_domains = list(session.run(
                    "MATCH (p:Project)-[e:ENTREPRENEURSHIP]->(n:Entrepreneurship) "
                    "OPTIONAL MATCH (p)-[:BELONGS_TO]->(c:Category) "
                    "RETURN p.id AS pid, p.name AS pname, c.name AS cat, n.name AS nname, e.level_rank AS level_rank, e.level AS level, elementId(n) AS nid"
                ))
                for ent in ent_domains:
                    # 颜色逻辑：level_rank=2 红色，其余橙色
                    color = "#fb923c"
                    try:
                        level_rank = int(ent["level_rank"] or 0)
                    except Exception:
                        level_rank = 0
                    if level_rank == 2:
                        color = "#ef4444"  # 红色高亮
                    sg_meta.append({
                        "id": f"entrepreneur_domain_{ent['nid']}",
                        "label": ent["nname"],
                        "node_label": "Entrepreneurship",
                        "color": color,
                        "node_count": 1,
                        "edge_count": 1,
                        "linked_projects": 1,
                        "top_nodes": [{"name": ent["nname"], "freq": 1, "level": ent["level"], "level_rank": ent["level_rank"]}],
                        "category_dist": [{"cat": ent["cat"] or "", "count": 1}],
                        "type": "entrepreneur_domain",
                        "level": ent["level"],
                        "level_rank": ent["level_rank"],
                        "project_id": ent["pid"],
                    })
                # 赛事类型节点全部只用 PARTICIPATED_IN
                comp_types = list(session.run(
                    "MATCH (p:Project)-[:PARTICIPATED_IN]->(n:Competition) "
                    "OPTIONAL MATCH (p)-[:BELONGS_TO]->(c:Category) "
                    "RETURN p.id AS pid, p.name AS pname, c.name AS cat, n.name AS nname, elementId(n) AS nid"
                ))
                for c in comp_types:
                    sg_meta.append({
                        "id": f"competition_{c['nid']}",
                        "label": c["nname"],
                        "node_label": "Competition",
                        "color": "#f472b6",
                        "node_count": 1,
                        "edge_count": 1,
                        "linked_projects": 1,
                        "top_nodes": [{"name": c["nname"], "freq": 1}],
                        "category_dist": [{"cat": c["cat"] or "", "count": 1}],
                        "type": "competition",
                    })

                # 创业/创新案例区分
                # 创业案例
                ent_cases = list(session.run(
                    "MATCH (e:Entrepreneurship)<-[r:ENTREPRENEURSHIP]-(p:Project)" 
                    "RETURN p.id AS pid, p.name AS pname, r.level AS relevance, e.name AS ename, r.level_rank AS level_rank"
                ))
                for e in ent_cases:
                    color = "#fb923c"
                    try:
                        level_rank = int(e["level_rank"] or 0)
                    except Exception:
                        level_rank = 0
                    if level_rank == 2:
                        color = "#ef4444"
                    sg_meta.append({
                        "id": f"entrepreneurship_{e['pid']}",
                        "label": e["pname"],
                        "node_label": "Project",
                        "color": color,
                        "node_count": 1,
                        "edge_count": 1,
                        "linked_projects": 1,
                        "top_nodes": [{"name": e["ename"], "freq": 1, "level_rank": e["level_rank"]}],
                        "category_dist": [],
                        "type": "entrepreneurship",
                        "level_rank": e["level_rank"],
                    })
                # 创新案例（未标注创业的项目）
                inno_cases = list(session.run(
                    "MATCH (p:Project) WHERE NOT (p)-[:ENTREPRENEURSHIP]->(:Entrepreneurship)" 
                    "RETURN p.id AS pid, p.name AS pname"
                ))
                for i in inno_cases:
                    sg_meta.append({
                        "id": f"entrepreneurship_{i['pid']}",
                        "label": "innovation",
                        "node_label": "Project",
                        "color": color,
                        "node_count": 1,
                        "edge_count": 1,
                        "linked_projects": 1,
                        "top_nodes": [{"name": i["pname"], "freq": 1}],
                        "category_dist": [],
                        "type": "innovation",
                    })

                cross_links: list[dict] = []
                for i, (sg_a, _, rel_a, _) in enumerate(all_sgs):
                    for j, (sg_b, _, rel_b, _) in enumerate(all_sgs):
                        if j <= i:
                            continue
                        nl_a = all_sgs[i][1]
                        nl_b = all_sgs[j][1]
                        shared_rows = list(session.run(
                            f"MATCH (p:Project)-[:{rel_a}]->(a:{nl_a}), "
                            f"      (p)-[:{rel_b}]->(b:{nl_b}) "
                            f"RETURN count(DISTINCT p) AS shared"
                        ))
                        shared = shared_rows[0]["shared"] if shared_rows else 0
                        if shared > 0:
                            cross_links.append({
                                "source": sg_a, "target": sg_b,
                                "shared_projects": shared,
                            })

                overview_nodes = [
                    {"id": "project", "label": "项目", "color": "#ffffff",
                     "node_count": project_count, "node_label": "Project", "type": "project"},
                ]
                for m in sg_meta:
                    overview_nodes.append({
                        "id": m["id"], "label": m["label"], "color": m["color"],
                        "node_count": m["node_count"], "node_label": m["node_label"], "type": m["type"]
                    })
                overview_links = []
                for m in sg_meta:
                    if m["linked_projects"] > 0:
                        overview_links.append({
                            "source": "project", "target": m["id"],
                            "weight": m["edge_count"],
                        })
                for cl in cross_links:
                    overview_links.append({
                        "source": cl["source"], "target": cl["target"],
                        "weight": cl["shared_projects"],
                    })

                return {
                    "subgraphs": sg_meta,
                    "overview_graph": {"nodes": overview_nodes, "links": overview_links},
                    "cross_links": cross_links,
                    "total_kg_nodes": sum(sg_node_counts.values()),
                    "total_projects": project_count,
                }

            return self._query_with_fallback(_query)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"subgraph overview failed: {exc}"}

    def get_single_subgraph(self, sg_id: str) -> dict[str, Any]:
        """Return all nodes + project connections for a single subgraph dimension."""
        try:
            all_sgs = {s[0]: s for s in self.DIMENSION_SUBGRAPHS + self.EXTRA_SUBGRAPHS}
            if sg_id not in all_sgs:
                return {"error": f"Unknown subgraph: {sg_id}"}

            _, node_label, rel_type, color = all_sgs[sg_id]

            def _query(session):
                nodes: list[dict] = []
                links: list[dict] = []
                node_set: set[str] = set()

                rows = list(session.run(
                    f"MATCH (p:Project)-[:{rel_type}]->(n:{node_label}) "
                    f"OPTIONAL MATCH (p)-[:BELONGS_TO]->(c:Category) "
                    f"RETURN p.id AS pid, p.name AS pname, c.name AS cat, "
                    f"       n.name AS nname, elementId(n) AS nid"
                ))
                for r in rows:
                    pid = r["pid"]
                    if pid not in node_set:
                        node_set.add(pid)
                        nodes.append({
                            "id": pid, "name": r["pname"] or pid,
                            "type": "Project", "category": r["cat"] or "",
                            "color": "#ffffff", "size": 6,
                        })
                    nid = f"{sg_id}_{r['nid']}"
                    if nid not in node_set:
                        node_set.add(nid)
                        nodes.append({
                            "id": nid, "name": r["nname"] or "",
                            "type": node_label, "color": color, "size": 4,
                        })
                    links.append({"source": pid, "target": nid, "type": rel_type})

                node_freq: dict[str, int] = {}
                cat_dist: dict[str, int] = {}
                for r in rows:
                    nname = r["nname"] or ""
                    node_freq[nname] = node_freq.get(nname, 0) + 1
                    cat = r["cat"] or "未分类"
                    cat_dist[cat] = cat_dist.get(cat, 0) + 1

                top_nodes = sorted(node_freq.items(), key=lambda x: -x[1])[:15]
                cat_stats = sorted(cat_dist.items(), key=lambda x: -x[1])

                return {
                    "sg_id": sg_id,
                    "sg_label": self.SG_LABELS.get(sg_id, node_label),
                    "node_label": node_label,
                    "color": color,
                    "graph": {"nodes": nodes, "links": links},
                    "stats": {
                        "entity_count": len([n for n in nodes if n["type"] != "Project"]),
                        "project_count": len([n for n in nodes if n["type"] == "Project"]),
                        "edge_count": len(links),
                    },
                    "top_nodes": [{"name": n, "freq": f} for n, f in top_nodes],
                    "category_dist": [{"cat": c, "count": n} for c, n in cat_stats],
                }

            return self._query_with_fallback(_query)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"single subgraph query failed: {exc}"}

    def get_subgraph_data(self) -> dict[str, Any]:
        """Return the full KG organized into dimension-based logical subgraphs."""
        try:
            def _query(session):
                subgraphs: list[dict] = []
                all_nodes: list[dict] = []
                all_links: list[dict] = []
                node_id_set: set[str] = set()

                project_rows = list(session.run(
                    "MATCH (p:Project)-[:BELONGS_TO]->(c:Category) "
                    "RETURN p.id AS id, p.name AS name, c.name AS category, p.confidence AS confidence"
                ))
                for r in project_rows:
                    pid = r["id"]
                    if pid not in node_id_set:
                        node_id_set.add(pid)
                        all_nodes.append({
                            "id": pid, "name": r["name"] or pid,
                            "type": "Project", "subgraph": "project",
                            "category": r["category"] or "", "confidence": r["confidence"],
                            "color": "#ffffff", "size": 6,
                        })

                for sg_id, node_label, rel_type, color in self.DIMENSION_SUBGRAPHS:
                    rows = list(session.run(
                        f"MATCH (p:Project)-[:{rel_type}]->(n:{node_label}) "
                        f"RETURN p.id AS pid, n.name AS name, elementId(n) AS nid",
                    ))
                    sg_nodes: list[dict] = []
                    sg_links: list[dict] = []
                    for r in rows:
                        nid = f"{sg_id}_{r['nid']}"
                        if nid not in node_id_set:
                            node_id_set.add(nid)
                            node = {
                                "id": nid, "name": r["name"] or "",
                                "type": node_label, "subgraph": sg_id,
                                "color": color, "size": 4,
                            }
                            all_nodes.append(node)
                            sg_nodes.append(node)
                        link = {"source": r["pid"], "target": nid, "type": rel_type}
                        all_links.append(link)
                        sg_links.append(link)

                    subgraphs.append({
                        "id": sg_id,
                        "label": node_label,
                        "rel_type": rel_type,
                        "color": color,
                        "node_count": len(sg_nodes),
                        "edge_count": len(sg_links),
                    })

                cat_rows = list(session.run(
                    "MATCH (c:Category) RETURN c.name AS name, elementId(c) AS cid"
                ))
                cat_sg_nodes = []
                for r in cat_rows:
                    cid = f"cat_{r['cid']}"
                    if cid not in node_id_set:
                        node_id_set.add(cid)
                        node = {"id": cid, "name": r["name"] or "", "type": "Category", "subgraph": "category", "color": "#a78bfa", "size": 5}
                        all_nodes.append(node)
                        cat_sg_nodes.append(node)
                cat_link_rows = list(session.run(
                    "MATCH (p:Project)-[:BELONGS_TO]->(c:Category) RETURN p.id AS pid, elementId(c) AS cid"
                ))
                cat_sg_links = []
                for r in cat_link_rows:
                    link = {"source": r["pid"], "target": f"cat_{r['cid']}", "type": "BELONGS_TO"}
                    all_links.append(link)
                    cat_sg_links.append(link)
                subgraphs.append({"id": "category", "label": "Category", "rel_type": "BELONGS_TO", "color": "#a78bfa", "node_count": len(cat_sg_nodes), "edge_count": len(cat_sg_links)})

                rr_rows = list(session.run(
                    "MATCH (r:RiskRule) RETURN r.id AS rid, r.name AS name, elementId(r) AS nid"
                ))
                rr_sg_nodes = []
                for r in rr_rows:
                    nid = f"rule_{r['nid']}"
                    if nid not in node_id_set:
                        node_id_set.add(nid)
                        node = {"id": nid, "name": r["name"] or r["rid"], "type": "RiskRule", "subgraph": "risk_rule", "color": "#f87171", "size": 5}
                        all_nodes.append(node)
                        rr_sg_nodes.append(node)
                hr_rows = list(session.run(
                    "MATCH (p:Project)-[:HITS_RULE]->(r:RiskRule) RETURN p.id AS pid, elementId(r) AS rid"
                ))
                rr_sg_links = []
                for r in hr_rows:
                    link = {"source": r["pid"], "target": f"rule_{r['rid']}", "type": "HITS_RULE"}
                    all_links.append(link)
                    rr_sg_links.append(link)
                subgraphs.append({"id": "risk_rule", "label": "RiskRule", "rel_type": "HITS_RULE", "color": "#f87171", "node_count": len(rr_sg_nodes), "edge_count": len(rr_sg_links)})

                ri_rows = list(session.run(
                    "MATCH (ri:RubricItem) RETURN ri.id AS riid, ri.name AS name, elementId(ri) AS nid"
                ))
                ri_sg_nodes = []
                for r in ri_rows:
                    nid = f"rubric_{r['nid']}"
                    if nid not in node_id_set:
                        node_id_set.add(nid)
                        node = {"id": nid, "name": r["name"] or r["riid"], "type": "RubricItem", "subgraph": "rubric", "color": "#4ade80", "size": 5}
                        all_nodes.append(node)
                        ri_sg_nodes.append(node)
                ev_rows = list(session.run(
                    "MATCH (p:Project)-[:EVALUATED_BY]->(ri:RubricItem) RETURN p.id AS pid, elementId(ri) AS riid"
                ))
                ri_sg_links = []
                for r in ev_rows:
                    link = {"source": r["pid"], "target": f"rubric_{r['riid']}", "type": "EVALUATED_BY"}
                    all_links.append(link)
                    ri_sg_links.append(link)
                subgraphs.append({"id": "rubric", "label": "RubricItem", "rel_type": "EVALUATED_BY", "color": "#4ade80", "node_count": len(ri_sg_nodes), "edge_count": len(ri_sg_links)})

                return {
                    "subgraphs": subgraphs,
                    "graph": {"nodes": all_nodes, "links": all_links},
                    "stats": {
                        "total_nodes": len(all_nodes),
                        "total_links": len(all_links),
                        "total_projects": len(project_rows),
                        "subgraph_count": len(subgraphs),
                    },
                }

            return self._query_with_fallback(_query)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"subgraph query failed: {exc}"}

    def get_hypergraph_viz(self) -> dict[str, Any]:
        """Return Hyperedge / HyperNode data formatted for force-graph rendering."""
        try:
            def _query(session):
                nodes: list[dict] = []
                links: list[dict] = []
                node_set: set[str] = set()

                he_rows = list(session.run(
                    "MATCH (h:Hyperedge) "
                    "RETURN elementId(h) AS eid, h.label AS label, h.type AS htype, "
                    "       h.project_id AS pid, h.weight AS weight LIMIT 5000"
                ))
                for r in he_rows:
                    nid = f"he_{r['eid']}"
                    node_set.add(nid)
                    nodes.append({
                        "id": nid, "name": r["label"] or "hyperedge",
                        "type": "Hyperedge", "htype": r["htype"] or "",
                        "project_id": r["pid"] or "",
                        "weight": float(r["weight"] or 1),
                        "color": "#f59e0b", "size": 8, "shape": "rect",
                    })

                hn_rows = list(session.run(
                    "MATCH (n:HyperNode) "
                    "RETURN elementId(n) AS nid, n.label AS label, n.type AS ntype, "
                    "       n.segment_index AS seg LIMIT 10000"
                ))
                for r in hn_rows:
                    nid = f"hn_{r['nid']}"
                    node_set.add(nid)
                    nodes.append({
                        "id": nid, "name": r["label"] or "node",
                        "type": "HyperNode", "ntype": r["ntype"] or "",
                        "color": "#38bdf8", "size": 3,
                    })

                member_rows = list(session.run(
                    "MATCH (h:Hyperedge)-[:HAS_MEMBER]->(n:HyperNode) "
                    "RETURN elementId(h) AS hid, elementId(n) AS nid LIMIT 20000"
                ))
                for r in member_rows:
                    links.append({
                        "source": f"he_{r['hid']}", "target": f"hn_{r['nid']}",
                        "type": "HAS_MEMBER",
                    })

                rule_rows = list(session.run(
                    "MATCH (h:Hyperedge)-[:TRIGGERS_RULE]->(rr:RiskRule) "
                    "RETURN elementId(h) AS hid, rr.id AS rid, rr.name AS rname LIMIT 5000"
                ))
                for r in rule_rows:
                    rid = f"rule_{r['rid']}"
                    if rid not in node_set:
                        node_set.add(rid)
                        nodes.append({
                            "id": rid, "name": r["rname"] or r["rid"],
                            "type": "RiskRule", "color": "#ef4444", "size": 5,
                        })
                    links.append({"source": f"he_{r['hid']}", "target": rid, "type": "TRIGGERS_RULE"})

                align_rows = list(session.run(
                    "MATCH (h:Hyperedge)-[:ALIGNS_WITH]->(ri:RubricItem) "
                    "RETURN elementId(h) AS hid, ri.id AS riid, ri.name AS riname LIMIT 5000"
                ))
                for r in align_rows:
                    riid = f"rubric_{r['riid']}"
                    if riid not in node_set:
                        node_set.add(riid)
                        nodes.append({
                            "id": riid, "name": r["riname"] or r["riid"],
                            "type": "RubricItem", "color": "#22c55e", "size": 5,
                        })
                    links.append({"source": f"he_{r['hid']}", "target": riid, "type": "ALIGNS_WITH"})

                return {
                    "graph": {"nodes": nodes, "links": links},
                    "stats": {
                        "total_hyperedges": len(he_rows),
                        "total_hypernodes": len(hn_rows),
                        "total_links": len(links),
                    },
                }

            return self._query_with_fallback(_query)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"hypergraph viz query failed: {exc}"}

    def search_kg(self, query: str, subgraph_filter: str = "", category_filter: str = "", limit: int = 30) -> dict[str, Any]:
        """Full-text search across all dimension nodes, returning matched nodes + their project context."""
        if not query or len(query.strip()) < 1:
            return {"results": [], "count": 0}
        try:
            def _query(session):
                results: list[dict] = []
                seen: set[str] = set()
                q = query.strip()

                search_targets = self.DIMENSION_SUBGRAPHS
                if subgraph_filter:
                    search_targets = [t for t in search_targets if t[0] == subgraph_filter]

                for sg_id, node_label, rel_type, color in search_targets:
                    cat_clause = ""
                    params: dict[str, Any] = {"q": q, "lim": limit}
                    if category_filter:
                        cat_clause = "AND cat.name = $cat"
                        params["cat"] = category_filter

                    rows = list(session.run(
                        f"MATCH (p:Project)-[:{rel_type}]->(n:{node_label}) "
                        f"OPTIONAL MATCH (p)-[:BELONGS_TO]->(cat:Category) "
                        f"WHERE toLower(n.name) CONTAINS toLower($q) {cat_clause} "
                        f"RETURN n.name AS name, elementId(n) AS nid, "
                        f"       p.id AS project_id, p.name AS project_name, "
                        f"       cat.name AS category "
                        f"LIMIT $lim",
                        **params,
                    ))
                    for r in rows:
                        key = f"{sg_id}_{r['nid']}"
                        if key in seen:
                            continue
                        seen.add(key)
                        results.append({
                            "node_id": key,
                            "name": r["name"],
                            "subgraph": sg_id,
                            "subgraph_label": node_label,
                            "color": color,
                            "project_id": r["project_id"],
                            "project_name": r["project_name"],
                            "category": r["category"] or "",
                        })
                    if len(results) >= limit:
                        break

                return {"results": results[:limit], "count": len(results)}

            return self._query_with_fallback(_query)
        except Exception as exc:  # noqa: BLE001
            return {"results": [], "count": 0, "error": str(exc)}
