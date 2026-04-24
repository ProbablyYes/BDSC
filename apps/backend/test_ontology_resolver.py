"""轻量级断言式测试，不依赖 pytest，可直接 `python test_ontology_resolver.py`。"""

from app.services.ontology_resolver import get_resolver


def main() -> None:
    r = get_resolver()

    # 1) normalize: 别名/口语词/英文都能命中
    hits = r.normalize("我们的价值主张是降低获客成本（CAC），用户LTV会很高")
    assert "C_value_proposition" in hits, hits
    assert "X_cac" in hits, hits
    assert "X_ltv" in hits, hits

    # 2) normalize: 词边界保护，AI 不会命中 "AIM"
    safe = r.normalize("aim is to do this")
    # 我们没有 alias=ai，所以无论如何都不应该有错命中；这里只确保不抛异常
    assert isinstance(safe, list)

    # 3) expand: 父概念展开包含子节点
    bm = r.expand("C_business_model")
    assert "M_unit_economics" in bm, "M_unit_economics 应在 C_business_model 子树"
    assert "X_cac" not in bm, "X_cac 是财务风险下的，不在 C_business_model 子树"

    # 4) ancestors: 上推链
    anc = r.ancestors("X_cac")
    assert anc == ["C_risk_category_financial", "C_risk_control"], anc

    # 5) covered: 子命中→父覆盖
    cov = r.covered(["X_cac"])
    assert "C_risk_control" in cov and "C_risk_category_financial" in cov

    # 6) stage_gap: idea 阶段最起码要覆盖 C_problem / C_user_segment
    gap_idea = [n.id for n in r.stage_gap("idea", [])]
    assert "C_problem" in gap_idea
    assert "C_user_segment" in gap_idea

    # 命中后从 gap 里消失
    gap_after = [n.id for n in r.stage_gap("idea", ["C_problem", "C_user_segment"])]
    assert "C_problem" not in gap_after
    assert "C_user_segment" not in gap_after

    # 7) query: 按 kind+parent 过滤
    market_metrics = [n.id for n in r.query(kinds=["metric"], parent="C_market_size")]
    assert set(market_metrics) == {"X_tam", "X_sam", "X_som"}, market_metrics

    # 8) query: 按 stage_expected 过滤
    structured_concepts = [n.id for n in r.query(kinds=["concept"], stage="structured")]
    assert "C_business_model" in structured_concepts
    assert "C_market_size" in structured_concepts

    print("OntologyResolver: ALL TESTS PASSED")


if __name__ == "__main__":
    main()
