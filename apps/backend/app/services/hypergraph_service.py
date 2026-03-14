from collections import Counter
from dataclasses import dataclass
from typing import Any

import hypernetx as hnx

from app.services.graph_service import GraphService


@dataclass
class HyperedgeRecord:
    hyperedge_id: str
    type: str
    support: int
    teaching_note: str
    category: str | None
    rules: list[str]


class HypergraphService:
    """
    Build/query teaching hypergraph with HyperNetX.
    """

    def __init__(self, graph_service: GraphService) -> None:
        self.graph_service = graph_service
        self._hypergraph: hnx.Hypergraph | None = None
        self._records: list[HyperedgeRecord] = []
        self._rule_alias = {
            "H4": ["market_size_fallacy"],
            "H5": ["weak_user_evidence"],
            "H6": ["no_competitor_claim"],
            "H8": ["unit_economics_not_proven", "unit_economics_unsound"],
            "H11": ["compliance_not_covered"],
        }

    def rebuild(self, min_pattern_support: int = 2, max_edges: int = 30) -> dict[str, Any]:
        min_pattern_support = max(1, min(min_pattern_support, 10))
        max_edges = max(5, min(max_edges, 100))

        try:
            rows = self.graph_service._query_with_fallback(  # noqa: SLF001
                lambda session: list(
                    session.run(
                        """
                        MATCH (p:Project)-[:BELONGS_TO]->(c:Category)
                        OPTIONAL MATCH (p)-[:HITS_RULE]->(r:RiskRule)
                        WITH p, c, collect(DISTINCT r.id) AS rule_ids, count(DISTINCT r) AS risk_count,
                             coalesce(p.confidence, 0.0) AS confidence
                        RETURN p.id AS project_id,
                               c.name AS category,
                               [x IN rule_ids WHERE x IS NOT NULL] AS rule_ids,
                               risk_count,
                               confidence
                        """
                    )
                )
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"hypergraph source query failed: {exc}"}

        risk_counter: Counter[tuple[str, tuple[str, ...]]] = Counter()
        value_counter: Counter[str] = Counter()

        for row in rows:
            category = str(row.get("category") or "未分类")
            rule_ids = sorted(str(x) for x in (row.get("rule_ids") or []) if x)
            risk_count = int(row.get("risk_count") or 0)
            confidence = float(row.get("confidence") or 0.0)

            if len(rule_ids) >= 2:
                risk_counter[(category, tuple(rule_ids))] += 1
            if confidence >= 0.75 and risk_count <= 1:
                value_counter[category] += 1

        edge_to_nodes: dict[str, set[str]] = {}
        records: list[HyperedgeRecord] = []

        created_risk = 0
        for idx, ((category, rules), support) in enumerate(risk_counter.most_common(max_edges), start=1):
            if support < min_pattern_support:
                continue
            edge_id = f"he_risk_{idx:03d}"
            node_set = {f"Category::{category}"} | {f"RiskRule::{rid}" for rid in rules}
            edge_to_nodes[edge_id] = node_set
            records.append(
                HyperedgeRecord(
                    hyperedge_id=edge_id,
                    type="Risk_Pattern_Edge",
                    support=support,
                    teaching_note=f"{category} 类项目常见风险组合：{'、'.join(rules)}",
                    category=category,
                    rules=list(rules),
                )
            )
            created_risk += 1

        created_value = 0
        for idx, (category, support) in enumerate(value_counter.most_common(max_edges), start=1):
            edge_id = f"he_value_{idx:03d}"
            edge_to_nodes[edge_id] = {f"Category::{category}"}
            records.append(
                HyperedgeRecord(
                    hyperedge_id=edge_id,
                    type="Value_Loop_Edge",
                    support=support,
                    teaching_note=f"{category} 类项目中存在较稳定的低风险高置信样本，可作为价值闭环参考。",
                    category=category,
                    rules=[],
                )
            )
            created_value += 1

        self._hypergraph = hnx.Hypergraph(edge_to_nodes) if edge_to_nodes else hnx.Hypergraph({})
        self._records = records

        return {
            "ok": True,
            "created": {
                "risk_pattern_edges": created_risk,
                "value_loop_edges": created_value,
                "resource_leverage_edges": 0,
            },
            "notes": "HyperNetX 超图已重建（内存态）。",
        }

    def insight(self, category: str | None = None, rule_ids: list[str] | None = None, limit: int = 5) -> dict[str, Any]:
        if not self._records:
            rebuilt = self.rebuild(min_pattern_support=2, max_edges=30)
            if not rebuilt.get("ok"):
                return {"ok": False, "edges": [], "error": rebuilt.get("error", "rebuild failed")}

        safe_rules = [str(x) for x in (rule_ids or []) if x]
        expanded_rules: set[str] = set(safe_rules)
        for rid in safe_rules:
            for alias in self._rule_alias.get(rid, []):
                expanded_rules.add(alias)
        matched: list[dict[str, Any]] = []
        for rec in self._records:
            cat_hit = bool(category and rec.category == category)
            rule_hit = any(r in rec.rules for r in expanded_rules) if expanded_rules else False
            if (not category and not safe_rules) or cat_hit or rule_hit:
                matched.append(
                    {
                        "hyperedge_id": rec.hyperedge_id,
                        "type": rec.type,
                        "support": rec.support,
                        "teaching_note": rec.teaching_note,
                        "categories": [rec.category] if rec.category else [],
                        "rules": rec.rules,
                    }
                )

        matched.sort(key=lambda x: int(x.get("support") or 0), reverse=True)
        return {
            "ok": True,
            "edges": matched[: max(1, min(limit, 20))],
            "matched_by": {"category": category, "rule_ids": safe_rules, "expanded_rule_ids": sorted(expanded_rules)},
            "meta": {"engine": "hypernetx", "edge_count": len(self._records)},
        }
