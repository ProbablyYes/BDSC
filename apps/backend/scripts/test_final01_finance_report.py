from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

from app.main import budget_store, finance_report_service
from app.services.finance_signal_extractor import apply_signals_to_budget, extract_finance_signals


USER_ID = "99fed9ab-486c-4b22-8329-b3c6466e17d2"  # final-01

SCENARIOS = [
    {
        "name": "finance-reg-commercial-detailed",
        "industry": "教育",
        "initial_messages": [
            (
                "我们在做一个面向中小企业法务的合同审查 SaaS。"
                "客户主要是 20-300 人规模、没有完整法务中台的企业，核心价值是把合同初审效率从 4 小时压到 30 分钟。"
                "现在已经有 12 家试点客户，团队希望把它做成一个能稳定续费的订阅业务。"
            ),
            (
                "目前我们的商业化思路已经比较清楚，但财务口径还不够全。"
                "我想先看系统在缺少部分假设的情况下会提示我们补什么，再逐步补齐。"
            ),
        ],
        "supplement_messages": [
            "补充订阅模型核心假设：月费 299 元/月，月活用户 12000 人，付费转化率 18%。",
            "继续补充单位经济：CAC 650 元，毛利率 78%，月留存率 87%，起始资金 800000 元，月固定成本 85000 元。",
            "继续补充市场规模：目标总人群 120000 家企业，可服务人群 12000 家，首年预计能触达 3000 家，年 ARPU 3588 元。",
            "继续补充现金流口径：每月新增付费客户 48 家，月增长率 0.08，单个付费客户月变动成本 35 元。",
        ],
    },
    {
        "name": "finance-reg-public-detailed",
        "industry": "社会公益",
        "initial_messages": [
            (
                "我们在做乡镇寄宿制女生经期支持项目，希望兼顾公益影响和长期可持续。"
                "第一阶段先覆盖西南地区样本学校，验证物资发放、经期教育和同伴支持能不能稳定跑起来。"
            ),
            (
                "当前我们还没有把公益项目的财务口径完全拆开，"
                "想先看系统会提示哪些关键假设，再逐步补完整。"
            ),
        ],
        "supplement_messages": [
            "补充公益收入与服务口径：在期资助 12 个项目，单个资助年度金额 150000 元，续期率 70%，每月服务受益人 6000 人。",
            "继续补充公益效率口径：单位受益人成本 38 元，目标总人群 180000 人，可服务人群 24000 人，首年覆盖 6000 人，服务转化率 65%。",
            "继续补充资金与现金流：折算年 ARPU 480 元，起始资金 1200000 元，月固定成本 85000 元，单个受益人月变动成本 6 元。",
        ],
    },
]


def _apply_message(plan_id: str, history: list[dict], idx: int, message: str) -> None:
    signals = extract_finance_signals(message, history=history)
    history.append({"role": "user", "content": message})
    applied = apply_signals_to_budget(
        USER_ID,
        plan_id,
        signals,
        source_message_id=f"turn-{idx}",
        overwrite=True,
        storage=budget_store,
    )
    print(f"turn {idx}: pattern={signals.get('primary_pattern')} summary={signals.get('summary')}")
    print(
        f"         applied={len(applied.get('applied') or [])} "
        f"stream_added={applied.get('stream_added')}"
    )


def _generate_report(plan_id: str, industry: str, history: list[dict]) -> tuple[dict, dict]:
    report = finance_report_service.generate(
        USER_ID,
        plan_id=plan_id,
        industry_hint=industry,
        context_text="\n".join(item["content"] for item in history if item.get("role") == "user"),
        use_llm_explain=False,
    )
    modules = {m["module"]: m for m in report.get("modules") or []}
    return report, modules


def _print_stage(label: str, modules: dict) -> list[str]:
    print(f"\n--- {label} ---")
    missing_all: list[str] = []
    summary = modules.get("finance_summary") or {}
    if summary:
        verdict = summary.get("verdict") or {}
        outputs = summary.get("outputs") or {}
        print(f"finance_summary  => {verdict.get('level')} | {verdict.get('reason')}")
        findings = outputs.get("key_findings") or []
        if findings:
            for item in findings[:4]:
                print(f"                 · {item}")
    for key in ("unit_economics", "cash_flow", "rationality", "market_size"):
        module = modules.get(key) or {}
        verdict = module.get("verdict") or {}
        print(f"{key:16s} => {verdict.get('level')} | {verdict.get('reason')}")
        missing_inputs = module.get("missing_inputs") or []
        if missing_inputs:
            fields = [m.get("field") for m in missing_inputs if m.get("field")]
            missing_all.extend(fields)
            print(f"{'':16s} missing => {fields}")
    market = modules.get("market_size") or {}
    print("market outputs:", market.get("outputs"))
    return missing_all


def run_scenario(scenario: dict) -> None:
    plan = budget_store.create_plan(USER_ID, scenario["name"], purpose="business")
    plan_id = plan["plan_id"]
    history: list[dict] = []
    print(f"\n=== {scenario['name']} | plan={plan_id} ===")

    turn = 1
    for message in scenario["initial_messages"]:
        _apply_message(plan_id, history, turn, message)
        turn += 1

    _, modules = _generate_report(plan_id, scenario["industry"], history)
    missing_before = _print_stage("第一次报告（先看系统要求补什么）", modules)
    print("需要补充的字段:", sorted(set(missing_before)))

    for message in scenario["supplement_messages"]:
        _apply_message(plan_id, history, turn, message)
        turn += 1

    _, modules = _generate_report(plan_id, scenario["industry"], history)
    missing_after = _print_stage("补充假设后的最终报告", modules)
    print("最终仍缺字段:", sorted(set(missing_after)))


def main() -> int:
    for scenario in SCENARIOS:
        run_scenario(scenario)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
