"""End-to-end test: dialogue -> signal extract -> write budget -> recompute cash flow -> finance modules.

No LLM, no Neo4j, no network. Plain ASCII output for Windows GBK terminal.
"""
import sys, os, tempfile, io
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# Force UTF-8 stdout so ASCII Y / arrows work in any locale.
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

from pathlib import Path
from app.services.budget_storage import BudgetStorage
from app.services.finance_signal_extractor import (
    extract_finance_signals, apply_signals_to_budget,
)
from app.services.finance_analyst import (
    extract_assumptions_from_budget, analyze_unit_economics,
    project_cash_flow,
)


SCENARIOS = [
    {
        "uid": "e2e_sub",
        "name": "Subscription SaaS (商业 + 创业)",
        "industry": "教育",
        "messages": [
            "我们想给中学生做个英语阅读 SaaS, 月费 49 元",
            "目标月活用户 8000 人, 付费转化率大概 4%",
            "毛利率 75%, 留存率 88%, 获客成本 (CAC) 约 200 元",
            "月固定成本 30000 元, 启动资金 500000 元",
        ],
    },
    {
        "uid": "e2e_b2b",
        "name": "Project B2B (商业 + 创新)",
        "industry": "教育",
        "messages": [
            "我们做学校采购的智慧教育解决方案",
            "单合同 30 万, 服务周期 12 个月, 月新签 1 份",
            "续约率 60%, 毛利率约 50%, 月固定成本 8 万",
        ],
    },
    {
        "uid": "e2e_grant",
        "name": "Grant Funded (公益 + 创新)",
        "industry": "社会公益",
        "messages": [
            "我们做留守儿童陪伴公益项目, 主要靠基金会资助",
            "在期资助 5 个项目, 单个项目年度金额 20 万, 续期率 70%",
            "每月服务受益人 800 人, 月固定成本 2 万",
        ],
    },
]


def Y(x):
    """Render currency without ¥ (GBK can't encode it)."""
    try:
        return f"RMB{x:,.0f}"
    except Exception:
        return str(x)


def run_scenario(sc, storage):
    print("\n" + "=" * 78)
    print(f"  Scenario: {sc['name']}")
    print("=" * 78)
    user_id = sc["uid"]
    plan = storage.create_plan(user_id, sc["name"], purpose="business")
    plan_id = plan["plan_id"]

    history = []
    for msg in sc["messages"]:
        sigs = extract_finance_signals(msg, history=history)
        history.append({"role": "user", "content": msg})
        if not sigs.get("triggered"):
            continue
        applied = apply_signals_to_budget(
            user_id=user_id, plan_id=plan_id, signals=sigs,
            source_message_id="test", confidence_threshold=0.6,
            storage=storage,
        )
        print(f"  - msg: {msg[:50]}")
        print(f"      pattern={sigs.get('primary_pattern')} | summary={sigs.get('summary','')[:60]}")
        for a in (applied.get("applied") or []):
            print(f"      -> stream[{a['stream_index']}].{a['field']} = {a['new']}  (was {a['old']})")

    final = storage.load(user_id, plan_id) or {}
    biz = final.get("business_finance") or {}
    streams = biz.get("revenue_streams") or []
    print(f"\n  Final streams = {len(streams)}")
    for i, s in enumerate(streams):
        print(f"     [{i}] pattern={s.get('pattern_key'):22s} monthly={Y(s.get('monthly_revenue') or 0)}")
        print(f"          inputs={s.get('inputs')}")

    assumptions = extract_assumptions_from_budget(final)
    print(f"\n  assumptions.dominant_pattern = {assumptions.get('dominant_pattern')}")
    print(f"               pattern_mix      = {assumptions.get('pattern_mix')}")
    print(f"               kind_mix         = {assumptions.get('kind_mix')}")
    print(f"               is_public        = {assumptions.get('is_public')}")
    print(f"               by_stream count  = {len(assumptions.get('by_stream') or [])}")

    ue = analyze_unit_economics(assumptions, industry=sc["industry"])
    print(f"\n  unit_econ verdict: {ue['verdict']['level']:6s} score={ue['verdict']['score']}")
    print(f"     reason: {ue['verdict']['reason'][:120]}")
    for ps in (ue.get("outputs", {}).get("per_stream") or []):
        kpi = ps.get("primary_kpi") or ("", None, "")
        print(f"     - [{ps['pattern_label']}] {kpi[0]}={kpi[1]}{kpi[2]} ({ps['health']})")

    cf = project_cash_flow(assumptions, months=18, industry=sc["industry"])
    print(f"\n  cash_flow verdict: {cf['verdict']['level']:6s}  reason={cf['verdict']['reason'][:90]}")
    proj = cf.get("outputs", {}).get("projection") or []
    if proj:
        print(f"     m1-m3 revenue: " + " / ".join(Y(p['revenue']) for p in proj[:3]))
        print(f"     last revenue / cash: {Y(proj[-1]['revenue'])} / {Y(proj[-1]['cash'])}")

    sr = (final.get("business_finance") or {}).get("scenario_results") or {}
    if sr:
        print("\n  Scenario compare (annual):")
        for k in ("conservative", "baseline", "optimistic"):
            v = sr.get(k, {})
            be = v.get("months_to_breakeven")
            print(f"     {k:14s} annual_rev={Y(v.get('annual_revenue',0))}  net={Y(v.get('annual_net',0))}  breakeven_m={be}")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="bdsc_fin_e2e_"))
    print(f"[temp budget root]: {tmp}")
    storage = BudgetStorage(tmp)
    for sc in SCENARIOS:
        try:
            run_scenario(sc, storage)
        except Exception as exc:
            import traceback; traceback.print_exc()
            print(f"[FAIL] {sc['name']}: {exc}")


if __name__ == "__main__":
    main()
