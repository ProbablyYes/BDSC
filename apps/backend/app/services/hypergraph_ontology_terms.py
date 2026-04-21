"""超图本体术语表。

解决老师/学生在质量评估页看到"77 超边家族 / 95 超边模式 / 一致性规则 50 /
当前项目命中 X"这些数字时的困惑："明明是超边，为什么又有模式？一致性规则
数量怎么一直在变？"

这里一次性把术语钉死，前端术语卡与 tooltip 都从这里取文字。后端改数不改
语义时只改本表即可。
"""
from __future__ import annotations

from typing import Any


ONTOLOGY_TERMS: dict[str, dict[str, Any]] = {
    "hyperedge_family": {
        "label": "超边家族",
        "label_en": "Hyperedge Family",
        "role": "抽象类",
        "one_liner": "77 类跨维度语义关联的抽象定义（例：价值闭环、单位经济闭环、风险-证据闭环）。",
        "why_exists": (
            "超图里的每条超边都属于某一\"类\"，好比普通图里每条边都有\"关系类型\"。"
            "家族就是这个类型表，给每类超边一个可复用的教学诊断语义。"
        ),
        "count_nature": "static",
        "count_source": "hypergraph_service._FAMILY_META / EDGE_FAMILY_LABELS",
        "changes_with_project": False,
    },
    "hyperedge_pattern": {
        "label": "超边模式",
        "label_en": "Hyperedge Pattern",
        "aliases_old": ["超边模板", "hyperedge_template"],
        "role": "评分锚点",
        "one_liner": (
            "在家族之上挑出的\"理想/风险/中性\"诊断模式，每条写清\"这条超边若齐全"
            "要涉及哪些维度、对齐哪些规则\"。"
        ),
        "why_exists": (
            "家族只说\"这种关系存在\"，模式进一步说\"这种关系在满分项目里长什么样\"。"
            "它是把家族变成可打分锚点的中间层，不是超边的\"类\"，而是评分检查项。"
        ),
        "note": "旧代码里把它命名为 template，容易让人误解成\"超边的类\"。本页统一改称\"模式 (pattern)\"。",
        "count_nature": "static",
        "count_source": "hypergraph_service._HYPEREDGE_TEMPLATES",
        "changes_with_project": False,
    },
    "hyperedge_instance": {
        "label": "超边实例",
        "label_en": "Hyperedge Instance",
        "role": "真实数据",
        "one_liner": "入库案例或当前学生项目中被真实识别出的一条具体超边（属于某个家族，可能命中某条模式）。",
        "why_exists": "家族/模式是定义，实例是真数据。对\"96 个案例中入库 360 条超边\"这句里的 360 就是实例数。",
        "count_nature": "dynamic_per_corpus_or_project",
        "count_source": "Neo4j :Hyperedge 节点 / hypergraph_student.matched_edges",
        "changes_with_project": True,
    },
    "consistency_rule": {
        "label": "一致性规则",
        "label_en": "Consistency Rule",
        "role": "静态诊断规则",
        "one_liner": "G1..G50 共 50 条，基于维度覆盖 + 文本信号判定的规则，总数恒定。",
        "why_exists": "从另一个角度（不是结构而是\"缺口+证据\"）对项目做合理性检查，与模式互补。",
        "count_nature": "static",
        "count_source": "hypergraph_service._CONSISTENCY_RULES (len == 50)",
        "changes_with_project": False,
        "stable_total": 50,
    },
    "triggered_rule": {
        "label": "本项目命中的规则",
        "label_en": "Triggered Rule",
        "role": "运行时结果",
        "one_liner": "针对当前学生项目实际触发的一致性规则子集，数量 0-50 变化；这里的数字会随项目变化。",
        "why_exists": (
            "这才是老师在学生端会看到\"一直在变\"的那个数——总数（50）不变，变的是触发数。"
            "页面里必须把这两件事区分开。"
        ),
        "count_nature": "dynamic_per_project",
        "count_source": "hypergraph_student.consistency_issues",
        "changes_with_project": True,
    },
    "risk_rule": {
        "label": "风险规则",
        "label_en": "Risk Rule",
        "role": "评审量表关联规则",
        "one_liner": "H 系列规则（H1..H??），直接挂在 rubric 评分维度上，由多智能体诊断触发。与一致性规则是两条独立体系。",
        "why_exists": "一致性规则看结构缺口；风险规则看评审扣分点。两套并行，避免单一视角。",
        "count_nature": "static",
        "count_source": "data/graph_seed/rules/ (case_knowledge + diagnosis_engine)",
        "changes_with_project": False,
    },
}


NUMBER_SOURCES_EXPLAINER: list[dict[str, Any]] = [
    {
        "slot": "design_families",
        "label": "设计层 · 家族总数",
        "value_hint": 77,
        "source": "hypergraph_service._FAMILY_META",
        "meaning": "系统在本体设计阶段定义了多少类超边。与具体数据无关，这是\"上限\"。",
    },
    {
        "slot": "enrolled_families",
        "label": "已入库 · 家族数",
        "value_hint": 45,
        "source": "data/kg_quality/quality_report.json.hypergraph_quality",
        "meaning": "在 96 个真实案例里被真正实例化过的家族数，反映语料覆盖。",
    },
    {
        "slot": "design_patterns",
        "label": "设计层 · 模式总数",
        "value_hint": None,
        "source": "hypergraph_service._HYPEREDGE_TEMPLATES",
        "meaning": "系统定义的诊断模式总数，每条模式是家族的\"理想形态\"。",
    },
    {
        "slot": "consistency_rules_total",
        "label": "一致性规则 · 总定义",
        "value_hint": 50,
        "source": "hypergraph_service._CONSISTENCY_RULES",
        "meaning": "静态规则库，恒定 50 条——不会变。",
    },
    {
        "slot": "triggered_rules_current",
        "label": "当前项目 · 命中规则数",
        "value_hint": "0..50",
        "source": "hypergraph_student.consistency_issues",
        "meaning": "这个数才会随项目变化。看到\"规则数量在变\"指的是这个，不是总数。",
    },
]


def get_terms_payload() -> dict[str, Any]:
    """返回可直接塞进 /api/hypergraph/catalog 响应的 payload。"""
    return {
        "terms": ONTOLOGY_TERMS,
        "number_sources": NUMBER_SOURCES_EXPLAINER,
        "note": (
            "本术语表统一质量评估页所有数量口径，解答『为什么超边有模板 / 规则数为何在变』"
            "两类典型困惑。"
        ),
    }
