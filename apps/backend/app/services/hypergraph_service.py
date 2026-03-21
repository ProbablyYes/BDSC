"""
HyperNetX-based hypergraph service for teaching & student analysis.

Three hyperedge types (per requirements):
  - Risk_Pattern_Edge:      Project × Market × Outcome × Mistake (risk co-occurrence)
  - Value_Loop_Edge:         Market × Technology × Project        (healthy project clusters)
  - Resource_Leverage_Edge:  Project × Resource × Participant     (resource leverage patterns)

Additionally provides **student-content dynamic analysis**:
  - Builds a temporary hypergraph from KG entities extracted from the student's text
  - Performs cross-dimensional pattern discovery using HyperNetX topology
  - Returns structured insights for agents and frontend
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

import hypernetx as hnx

from app.services.graph_service import GraphService

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
    rules: list[str]
    node_set: set[str] | None = None


# ─────────────────────────────────────────────────────
#  Main service
# ─────────────────────────────────────────────────────

class HypergraphService:
    """Build/query teaching hypergraph + student dynamic analysis with HyperNetX."""

    def __init__(self, graph_service: GraphService) -> None:
        self.graph_service = graph_service
        self._hypergraph: hnx.Hypergraph | None = None
        self._records: list[HyperedgeRecord] = []
        self._rule_alias: dict[str, list[str]] = {
            "H4": ["market_size_fallacy"],
            "H5": ["weak_user_evidence"],
            "H6": ["no_competitor_claim"],
            "H8": ["unit_economics_not_proven", "unit_economics_unsound"],
            "H11": ["compliance_not_covered"],
        }

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
                        OPTIONAL MATCH (p)-[:HITS_RULE]->(r:RiskRule)
                        OPTIONAL MATCH (p)-[:USES_TECH]->(t:Technology)
                        OPTIONAL MATCH (p)-[:TARGETS]->(m:Market)
                        OPTIONAL MATCH (p)-[:HAS_RESOURCE]->(res:Resource)
                        WITH p, c,
                             collect(DISTINCT r.id) AS rule_ids,
                             collect(DISTINCT t.name) AS techs,
                             collect(DISTINCT m.name) AS markets,
                             collect(DISTINCT res.name) AS resources,
                             count(DISTINCT r) AS risk_count,
                             coalesce(p.confidence, 0.0) AS confidence
                        RETURN p.id AS project_id,
                               c.name AS category,
                               [x IN rule_ids WHERE x IS NOT NULL] AS rule_ids,
                               techs, markets, resources,
                               risk_count, confidence
                        """
                    )
                )
            )
        except Exception as exc:
            logger.warning("Hypergraph source query failed: %s", exc)
            rows = []

        if not rows:
            rows = self._fallback_query()

        edge_to_nodes: dict[str, set[str]] = {}
        records: list[HyperedgeRecord] = []

        risk_counter: Counter[tuple[str, tuple[str, ...]]] = Counter()
        value_buckets: dict[str, list[dict]] = defaultdict(list)
        resource_counter: Counter[tuple[str, tuple[str, ...]]] = Counter()

        for row in rows:
            category = str(row.get("category") or "未分类")
            rule_ids = sorted(str(x) for x in (row.get("rule_ids") or []) if x)
            techs = [str(x) for x in (row.get("techs") or []) if x]
            markets = [str(x) for x in (row.get("markets") or []) if x]
            resources = [str(x) for x in (row.get("resources") or []) if x]
            risk_count = int(row.get("risk_count") or 0)
            confidence = float(row.get("confidence") or 0.0)
            project_id = str(row.get("project_id") or "unknown")

            if len(rule_ids) >= 1:
                risk_counter[(category, tuple(rule_ids))] += 1

            if confidence >= 0.6 and risk_count <= 1:
                value_buckets[category].append({
                    "project_id": project_id, "techs": techs, "markets": markets,
                })

            if resources:
                resource_counter[(category, tuple(sorted(resources[:3])))] += 1

        # ── Risk_Pattern_Edge ──
        created_risk = 0
        for idx, ((category, rules), support) in enumerate(
            risk_counter.most_common(max_edges), start=1
        ):
            if support < min_pattern_support:
                continue
            edge_id = f"he_risk_{idx:03d}"
            node_set = {f"Category::{category}"} | {f"RiskRule::{rid}" for rid in rules}
            edge_to_nodes[edge_id] = node_set

            rule_names = "、".join(rules[:4])
            if len(rules) > 4:
                rule_names += f" 等{len(rules)}项"
            records.append(HyperedgeRecord(
                hyperedge_id=edge_id, type="Risk_Pattern_Edge",
                support=support,
                teaching_note=f"{category}类项目常见风险组合：{rule_names}（{support}个项目出现此模式）",
                category=category, rules=list(rules), node_set=node_set,
            ))
            created_risk += 1

        # ── Value_Loop_Edge ──
        created_value = 0
        for idx, (category, projects) in enumerate(
            sorted(value_buckets.items(), key=lambda x: -len(x[1])), start=1
        ):
            if idx > max_edges:
                break
            edge_id = f"he_value_{idx:03d}"
            all_techs = set()
            all_markets = set()
            for p in projects:
                all_techs.update(p.get("techs", []))
                all_markets.update(p.get("markets", []))

            node_set = {f"Category::{category}"}
            node_set |= {f"Technology::{t}" for t in list(all_techs)[:3]}
            node_set |= {f"Market::{m}" for m in list(all_markets)[:3]}
            edge_to_nodes[edge_id] = node_set

            tech_str = "、".join(list(all_techs)[:3]) if all_techs else "多种技术"
            market_str = "、".join(list(all_markets)[:3]) if all_markets else "多个市场"
            records.append(HyperedgeRecord(
                hyperedge_id=edge_id, type="Value_Loop_Edge",
                support=len(projects),
                teaching_note=(
                    f"{category}类有{len(projects)}个低风险高质量项目，"
                    f"技术路线集中在{tech_str}，目标市场为{market_str}——可作为价值闭环参考"
                ),
                category=category, rules=[], node_set=node_set,
            ))
            created_value += 1

        # ── Resource_Leverage_Edge ──
        created_resource = 0
        for idx, ((category, res_tuple), support) in enumerate(
            resource_counter.most_common(max_edges), start=1
        ):
            if support < min_pattern_support:
                continue
            edge_id = f"he_resource_{idx:03d}"
            node_set = {f"Category::{category}"} | {f"Resource::{r}" for r in res_tuple}
            edge_to_nodes[edge_id] = node_set

            res_names = "、".join(res_tuple)
            records.append(HyperedgeRecord(
                hyperedge_id=edge_id, type="Resource_Leverage_Edge",
                support=support,
                teaching_note=f"{category}类项目常利用{res_names}等资源（{support}个项目），建议检查资源获取可行性",
                category=category, rules=[], node_set=node_set,
            ))
            created_resource += 1

        self._hypergraph = hnx.Hypergraph(edge_to_nodes) if edge_to_nodes else hnx.Hypergraph({})
        self._records = records

        return {
            "ok": True,
            "created": {
                "risk_pattern_edges": created_risk,
                "value_loop_edges": created_value,
                "resource_leverage_edges": created_resource,
            },
            "total_nodes": len(self._hypergraph.nodes) if self._hypergraph else 0,
            "total_edges": len(self._hypergraph.edges) if self._hypergraph else 0,
            "notes": "HyperNetX 超图已重建（含三种超边类型）。",
        }

    def _fallback_query(self) -> list[dict]:
        """Fallback: simpler query if USES_TECH/TARGETS/HAS_RESOURCE relations don't exist."""
        try:
            rows = self.graph_service._query_with_fallback(
                lambda session: list(
                    session.run(
                        """
                        MATCH (p:Project)-[:BELONGS_TO]->(c:Category)
                        OPTIONAL MATCH (p)-[:HITS_RULE]->(r:RiskRule)
                        WITH p, c,
                             collect(DISTINCT r.id) AS rule_ids,
                             count(DISTINCT r) AS risk_count,
                             coalesce(p.confidence, 0.0) AS confidence
                        RETURN p.id AS project_id,
                               c.name AS category,
                               rule_ids, risk_count, confidence,
                               [] AS techs, [] AS markets, [] AS resources
                        """
                    )
                )
            )
            return rows
        except Exception as exc:
            logger.warning("Hypergraph fallback query also failed: %s", exc)
            return []

    # ═══════════════════════════════════════════════════
    #  2. Query existing hypergraph for teaching insights
    # ═══════════════════════════════════════════════════

    def insight(
        self,
        category: str | None = None,
        rule_ids: list[str] | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        if not self._records:
            rebuilt = self.rebuild(min_pattern_support=1, max_edges=50)
            if not rebuilt.get("ok"):
                return {"ok": False, "edges": [], "error": rebuilt.get("error", "rebuild failed")}

        safe_rules = [str(x) for x in (rule_ids or []) if x]
        expanded_rules: set[str] = set(safe_rules)
        for rid in safe_rules:
            for alias in self._rule_alias.get(rid, []):
                expanded_rules.add(alias)

        matched: list[dict[str, Any]] = []
        for rec in self._records:
            cat_hit = bool(category and rec.category and rec.category == category)
            rule_hit = any(r in rec.rules for r in expanded_rules) if expanded_rules else False
            if (not category and not safe_rules) or cat_hit or rule_hit:
                matched.append({
                    "hyperedge_id": rec.hyperedge_id,
                    "type": rec.type,
                    "support": rec.support,
                    "teaching_note": rec.teaching_note,
                    "categories": [rec.category] if rec.category else [],
                    "rules": rec.rules,
                    "nodes": sorted(rec.node_set) if rec.node_set else [],
                })

        matched.sort(key=lambda x: int(x.get("support") or 0), reverse=True)

        topology = self._get_topology_stats()

        return {
            "ok": True,
            "edges": matched[:max(1, min(limit, 20))],
            "matched_by": {
                "category": category,
                "rule_ids": safe_rules,
                "expanded_rule_ids": sorted(expanded_rules),
            },
            "topology": topology,
            "meta": {
                "engine": "hypernetx",
                "edge_count": len(self._records),
                "node_count": len(self._hypergraph.nodes) if self._hypergraph else 0,
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
        elif ntype == "Technology":
            return f"技术「{name}」被{degree}个模式共享，是核心技术路线"
        elif ntype == "Market":
            return f"市场「{name}」涉及{degree}种模式，是热门目标市场"
        elif ntype == "Resource":
            return f"资源「{name}」在{degree}种组合中出现，是关键杠杆资源"
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
                "missing_dimensions": ["无法分析：未提取到实体"],
            }

        DIMENSIONS = {
            "stakeholder": "目标用户",
            "pain_point": "痛点问题",
            "solution": "解决方案",
            "product": "产品形态",
            "technology": "技术路线",
            "market": "目标市场",
            "competitor": "竞争格局",
            "resource": "资源优势",
            "business_model": "商业模式",
            "team": "团队能力",
        }

        dim_entities: dict[str, list[str]] = defaultdict(list)
        entity_map: dict[str, str] = {}
        for e in entities:
            etype = str(e.get("type", "other")).lower()
            label = str(e.get("label", ""))
            eid = str(e.get("id", label))
            dim_entities[etype].append(label)
            entity_map[eid] = etype

        # Build student hypergraph edges
        student_edges: dict[str, set[str]] = {}

        for dim, ents in dim_entities.items():
            if ents:
                edge_id = f"dim_{dim}"
                student_edges[edge_id] = {f"{dim}::{e}" for e in ents}

        for rel in relationships:
            src = str(rel.get("source", ""))
            tgt = str(rel.get("target", ""))
            relation = str(rel.get("relation", "related"))
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

            for rec in self._records:
                if rec.type == "Risk_Pattern_Edge":
                    overlap = student_rule_like & set(rec.rules)
                    if overlap and (not category or rec.category == category):
                        pattern_warnings.append({
                            "pattern_id": rec.hyperedge_id,
                            "warning": rec.teaching_note,
                            "matched_rules": sorted(overlap),
                            "support": rec.support,
                        })
                elif rec.type == "Value_Loop_Edge":
                    if category and rec.category == category and coverage_score >= 6:
                        pattern_strengths.append({
                            "pattern_id": rec.hyperedge_id,
                            "note": rec.teaching_note,
                            "support": rec.support,
                        })
                elif rec.type == "Resource_Leverage_Edge":
                    if dim_entities.get("resource") and (not category or rec.category == category):
                        pattern_strengths.append({
                            "pattern_id": rec.hyperedge_id,
                            "note": rec.teaching_note,
                            "support": rec.support,
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
            "missing_dimensions": missing_recommendations[:6],
            "student_graph_stats": {
                "nodes": len(student_hg.nodes) if student_hg else 0,
                "edges": len(student_hg.edges) if student_hg else 0,
            },
        }
