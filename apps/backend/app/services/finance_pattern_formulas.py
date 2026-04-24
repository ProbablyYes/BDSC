"""
finance_pattern_formulas — 按 RevenuePattern 分支的财务公式 / 合理区间 / 杠杆库

为什么单独拆出来？
- 旧 finance_analyst 默认所有项目都是 SaaS（用 monthly_price × paying_users），
  对 B2B 项目制 / 平台抽佣 / 硬件销售 / 公益资助完全不贴。
- 这里给每个 pattern 配:
    1. unit_econ:           pattern 自己的"单位经济"指标(LTV/CAC 不再一刀切)
    2. cash_flow_signal:    pattern 自己的月营收公式
    3. levers:              情景分析时的关键杠杆字段(替代单一 conversion_multiplier)
    4. reasonable_ranges:   每个核心字段的合理区间(用于自动建模 + 校验)
    5. kind:                pattern 大类(growth / enterprise / platform / hardware / public)
- six modules 在调用前先把每条 stream 通过 PATTERN_FORMULAS 路由到对应公式，再加权汇总。

设计原则：
- 纯函数，无 IO，失败兜底 applicable=False
- 所有 ranges 来自公开行业报告中位区间(16Z / 艾瑞 / 易观 / 民政部公益数据)，仅供课程级建模
- 不重复 revenue_models 已有的 compute_monthly；只关注衍生指标(如 B2B 的 ARR、平台的 take rate 健康度)
"""
from __future__ import annotations

from typing import Any

from app.services.revenue_models import PATTERNS, _f, normalize_stream


# ══════════════════════════════════════════════════════════════════
#  字段参考区间(用于默认值/说明，不直接驱动结论)
# ══════════════════════════════════════════════════════════════════
# 每条: {"low": x, "median": y, "high": z, "unit": "...", "note": "..."}

REASONABLE_RANGES: dict[str, dict[str, dict[str, Any]]] = {
    "subscription": {
        "monthly_users":   {"low": 100,   "median": 5000,   "high": 100_000, "unit": "人",   "note": "校园 / 早期 SaaS 月活"},
        "conversion_rate": {"low": 0.01,  "median": 0.05,   "high": 0.15,    "unit": "比例", "note": "免费转付费率，C 端 1-5%"},
        "price":           {"low": 9,     "median": 49,     "high": 299,     "unit": "元/月", "note": "C 端订阅月费"},
    },
    "transaction": {
        "monthly_buyers":   {"low": 100,   "median": 2000,   "high": 50_000, "unit": "人",   "note": ""},
        "avg_order_value":  {"low": 30,    "median": 120,    "high": 800,    "unit": "元/单", "note": "电商客单"},
        "orders_per_buyer": {"low": 1.0,   "median": 1.5,    "high": 4.0,    "unit": "单/人/月", "note": "复购"},
    },
    "project_b2b": {
        "contracts_per_month":      {"low": 0.2,   "median": 1.0,    "high": 4.0,    "unit": "份/月",  "note": "早期项目制公司"},
        "contract_value":           {"low": 20_000, "median": 100_000, "high": 800_000, "unit": "元/份",  "note": "教育/政企采购"},
        "contract_duration_months": {"low": 3,     "median": 6,      "high": 24,     "unit": "月",    "note": ""},
        "renewal_rate":             {"low": 0.20,  "median": 0.50,   "high": 0.85,   "unit": "比例",   "note": "续约率"},
    },
    "platform_commission": {
        "monthly_gmv":      {"low": 50_000, "median": 500_000, "high": 10_000_000, "unit": "元/月", "note": ""},
        "commission_rate":  {"low": 0.03,   "median": 0.10,    "high": 0.25,       "unit": "比例", "note": "Take rate, 3-25%"},
        "active_sellers":   {"low": 20,     "median": 200,     "high": 5_000,      "unit": "家",   "note": "活跃供给方"},
    },
    "hardware_sales": {
        "monthly_units": {"low": 50,    "median": 500,    "high": 10_000, "unit": "台/件", "note": ""},
        "unit_price":    {"low": 99,    "median": 999,    "high": 9_999,  "unit": "元/件", "note": ""},
        "unit_cost":     {"low": 30,    "median": 400,    "high": 5_000,  "unit": "元/件", "note": "BOM + 制造"},
    },
    "grant_funded": {
        "active_grants":         {"low": 1,        "median": 3,        "high": 10,       "unit": "个",    "note": "在期资助项目数"},
        "grant_value_yearly":    {"low": 30_000,   "median": 200_000,  "high": 2_000_000, "unit": "元/年", "note": "校园 / 中型公益单笔"},
        "renewal_rate":          {"low": 0.30,     "median": 0.60,     "high": 0.85,     "unit": "比例",   "note": "续期概率"},
        "beneficiaries_served":  {"low": 50,       "median": 500,      "high": 50_000,   "unit": "人/月", "note": "月触达受益人"},
    },
    "donation": {
        "monthly_donors":  {"low": 10,    "median": 100,    "high": 5_000,  "unit": "个",   "note": "月活捐赠方"},
        "avg_donation":    {"low": 50,    "median": 1_000,  "high": 50_000, "unit": "元/方", "note": "C 端 50-500 / 企业 5k-50k"},
        "donor_retention": {"low": 0.20,  "median": 0.40,   "high": 0.75,   "unit": "比例", "note": ""},
    },
}


# ══════════════════════════════════════════════════════════════════
#  Pattern → 大类 / 杠杆 / 适配性
# ══════════════════════════════════════════════════════════════════

PATTERN_KIND: dict[str, str] = {
    "subscription":        "growth",
    "transaction":         "growth",
    "project_b2b":         "enterprise",
    "platform_commission": "platform",
    "hardware_sales":      "hardware",
    "grant_funded":        "public",
    "donation":            "public",
}


# 每个 pattern 在做"情景分析"时真正影响命运的 3-5 个杠杆
# (替代旧的 conversion_multiplier / revenue_multiplier 一刀切)
PATTERN_LEVERS: dict[str, list[dict[str, Any]]] = {
    "subscription": [
        {"field": "conversion_rate", "label": "付费转化率", "scenarios": {"pessimistic": 0.5, "baseline": 1.0, "optimistic": 1.6}},
        {"field": "monthly_users",   "label": "月活规模",   "scenarios": {"pessimistic": 0.6, "baseline": 1.0, "optimistic": 1.8}},
        {"field": "price",           "label": "月价",       "scenarios": {"pessimistic": 0.85, "baseline": 1.0, "optimistic": 1.2}},
    ],
    "transaction": [
        {"field": "monthly_buyers",   "label": "月买家",     "scenarios": {"pessimistic": 0.6, "baseline": 1.0, "optimistic": 1.7}},
        {"field": "avg_order_value",  "label": "客单价",     "scenarios": {"pessimistic": 0.8, "baseline": 1.0, "optimistic": 1.25}},
        {"field": "orders_per_buyer", "label": "复购频次",   "scenarios": {"pessimistic": 0.7, "baseline": 1.0, "optimistic": 1.5}},
    ],
    "project_b2b": [
        {"field": "contracts_per_month", "label": "中标率/月新签", "scenarios": {"pessimistic": 0.5, "baseline": 1.0, "optimistic": 2.0}},
        {"field": "contract_value",      "label": "合同金额",       "scenarios": {"pessimistic": 0.7, "baseline": 1.0, "optimistic": 1.5}},
        {"field": "renewal_rate",        "label": "续约率",         "scenarios": {"pessimistic": 0.6, "baseline": 1.0, "optimistic": 1.4}},
    ],
    "platform_commission": [
        {"field": "monthly_gmv",      "label": "月 GMV",     "scenarios": {"pessimistic": 0.5, "baseline": 1.0, "optimistic": 2.0}},
        {"field": "commission_rate",  "label": "Take rate",  "scenarios": {"pessimistic": 0.7, "baseline": 1.0, "optimistic": 1.3}},
        {"field": "active_sellers",   "label": "卖家活跃",   "scenarios": {"pessimistic": 0.7, "baseline": 1.0, "optimistic": 1.5}},
    ],
    "hardware_sales": [
        {"field": "monthly_units", "label": "月销量",     "scenarios": {"pessimistic": 0.6, "baseline": 1.0, "optimistic": 1.7}},
        {"field": "unit_price",    "label": "出厂价",     "scenarios": {"pessimistic": 0.9, "baseline": 1.0, "optimistic": 1.15}},
        {"field": "unit_cost",     "label": "BOM 成本",   "scenarios": {"pessimistic": 1.15, "baseline": 1.0, "optimistic": 0.85}},
    ],
    "grant_funded": [
        {"field": "active_grants",      "label": "在期资助数", "scenarios": {"pessimistic": 0.5, "baseline": 1.0, "optimistic": 1.6}},
        {"field": "grant_value_yearly", "label": "单笔年额",   "scenarios": {"pessimistic": 0.7, "baseline": 1.0, "optimistic": 1.4}},
        {"field": "renewal_rate",       "label": "续期概率",   "scenarios": {"pessimistic": 0.6, "baseline": 1.0, "optimistic": 1.3}},
    ],
    "donation": [
        {"field": "monthly_donors",  "label": "月捐赠方",     "scenarios": {"pessimistic": 0.5, "baseline": 1.0, "optimistic": 1.8}},
        {"field": "avg_donation",    "label": "平均捐赠额",   "scenarios": {"pessimistic": 0.8, "baseline": 1.0, "optimistic": 1.3}},
        {"field": "donor_retention", "label": "捐赠方留存",   "scenarios": {"pessimistic": 0.7, "baseline": 1.0, "optimistic": 1.3}},
    ],
}


# ══════════════════════════════════════════════════════════════════
#  Per-pattern 单位经济(unit_econ)函数
#  统一返回:
#    {
#      "applicable": bool,
#      "metrics": {<key>: <value>, ...},      # 具体可计算的指标
#      "health":  "green|yellow|red|gray",  # 语义已降级：已分析 / 需复核 / 存在内部矛盾 / 信息不足
#      "reason":  "...",
#      "missing": [{"field":..., "hint":...}],
#      "primary_kpi": (label, value, unit),
#    }
# ══════════════════════════════════════════════════════════════════

def _gray(reason: str = "数据不足") -> dict[str, Any]:
    return {"applicable": False, "metrics": {}, "health": "gray", "reason": reason, "missing": []}


def _ue_subscription(inputs: dict, *, gross_margin: float = 0.7, cac: float = 0.0,
                     monthly_retention: float = 0.0,
                     avg_lifetime_months: float = 0.0,
                     thresholds: dict[str, float] | None = None,
                     **_) -> dict[str, Any]:
    price = _f(inputs.get("price"))
    users = _f(inputs.get("monthly_users"))
    conv  = _f(inputs.get("conversion_rate"))
    if price <= 0 or conv <= 0 or users <= 0:
        return _gray("缺少月费、月活或付费转化率")
    paying = users * conv
    monthly_gross = price * max(gross_margin, 0.0)
    metrics: dict[str, Any] = {
        "paying_users": round(paying, 1),
        "monthly_gross_per_user": round(monthly_gross, 2),
    }
    missing: list[dict[str, Any]] = []
    health = "green"
    reason = f"已拆出订阅收入漏斗：付费用户≈{paying:.0f} 人，月毛利/用户≈¥{monthly_gross:.1f}"
    lifetime = avg_lifetime_months
    if lifetime <= 0 and 0 < monthly_retention < 1:
        lifetime = 1.0 / max(1.0 - monthly_retention, 0.01)
    if lifetime > 0:
        ltv = monthly_gross * lifetime
        metrics["avg_lifetime_months"] = round(lifetime, 1)
        metrics["ltv_estimate"] = round(ltv, 2)
        reason += f"，按当前留存假设 LTV≈¥{ltv:.0f}"
    else:
        missing.append({"field": "monthly_retention", "hint": "订阅模型若要估算 LTV，需要留存或生命周期假设"})
    if cac > 0 and metrics.get("ltv_estimate"):
        ltv = _f(metrics.get("ltv_estimate"))
        ratio = ltv / cac
        metrics["ltv_cac"] = round(ratio, 2)
        metrics["cac"] = round(cac, 2)
        if ratio < 1:
            health = "red"
            reason += f"；按你当前假设 LTV/CAC={ratio:.2f}，单用户生命周期价值尚不足以覆盖获客成本"
        else:
            reason += f"；按你当前假设 LTV/CAC={ratio:.2f}"
    elif cac > 0:
        missing.append({"field": "monthly_retention", "hint": "已有 CAC，但还缺留存/生命周期，无法判断获客回收"})
    return {
        "applicable": True, "metrics": metrics, "health": health, "reason": reason,
        "missing": missing + ([] if cac > 0 else [{"field": "cac", "hint": "填获客成本可补全 LTV/CAC"}]),
        "primary_kpi": ("LTV/CAC", metrics.get("ltv_cac"), "x") if "ltv_cac" in metrics else ("月毛利/用户", round(monthly_gross, 0), "元"),
    }


def _ue_transaction(inputs: dict, *, gross_margin: float = 0.3, cac: float = 0.0,
                    thresholds: dict[str, float] | None = None,
                    **_) -> dict[str, Any]:
    aov = _f(inputs.get("avg_order_value"))
    opb = _f(inputs.get("orders_per_buyer"), 1.0)
    buyers = _f(inputs.get("monthly_buyers"))
    if aov <= 0:
        return _gray("缺少客单价")
    monthly_per_buyer_gross = aov * opb * gross_margin
    metrics = {
        "buyers": round(buyers, 0),
        "avg_order_value": round(aov, 2),
        "orders_per_month": round(opb, 2),
        "monthly_gross_per_buyer": round(monthly_per_buyer_gross, 2),
    }
    health = "green"
    reason = f"月人均毛利≈¥{monthly_per_buyer_gross:.1f}(客单 {aov:.0f}×复购 {opb:.1f}×毛利 {gross_margin:.0%})"
    if cac > 0:
        payback = cac / monthly_per_buyer_gross if monthly_per_buyer_gross > 0 else float("inf")
        metrics["cac"] = round(cac, 2)
        metrics["payback_months"] = round(payback, 1) if payback != float("inf") else None
        if payback == float("inf"):
            health, reason = "red", "当前客单价、复购与毛利组合无法覆盖单次获客成本"
        else:
            reason += f"，按当前假设 Payback≈{payback:.1f} 月"
    return {"applicable": True, "metrics": metrics, "health": health, "reason": reason,
            "missing": [] if cac > 0 else [{"field": "cac", "hint": "填 CAC 可算回本月数"}],
            "primary_kpi": ("Payback", metrics.get("payback_months"), "月") if metrics.get("payback_months") else ("月人均毛利", round(monthly_per_buyer_gross, 0), "元")}


def _ue_b2b(inputs: dict, *, gross_margin: float = 0.5, cac: float = 0.0, **_) -> dict[str, Any]:
    cv = _f(inputs.get("contract_value"))
    cd = _f(inputs.get("contract_duration_months"), 6)
    cpm = _f(inputs.get("contracts_per_month"))
    rr  = _f(inputs.get("renewal_rate"))
    if cv <= 0:
        return _gray("缺少单合同金额")
    monthly_arr = cv / max(cd, 1.0)
    contract_gross = cv * gross_margin
    expected_lifetime_contracts = 1.0 / max(1.0 - rr, 0.05) if rr > 0 else 1.0
    arr_per_year = cpm * cv
    metrics = {
        "monthly_per_contract_revenue": round(monthly_arr, 2),
        "contract_gross_profit": round(contract_gross, 2),
        "expected_renewals": round(expected_lifetime_contracts, 2),
        "annual_recurring_revenue": round(arr_per_year, 2),
        "renewal_rate": round(rr, 2),
    }
    health = "green"
    reason = f"单合同 ¥{cv:,.0f}, 月度均摊 ¥{monthly_arr:,.0f}, ARR ≈ ¥{arr_per_year:,.0f}"
    if rr > 0:
        reason += f"，当前续约假设 {rr:.0%}"
    else:
        health = "yellow"
        reason += "；尚未给出续约假设，ARR 持续性需要人工复核"
    if cac > 0 and contract_gross > 0:
        cac_payback = cac / (contract_gross / max(cd, 1.0))
        metrics["cac_payback_months"] = round(cac_payback, 1)
        reason += f"；若把单合同毛利分摊，CAC 回收约 {cac_payback:.1f} 月"
    return {"applicable": True, "metrics": metrics, "health": health, "reason": reason,
            "missing": [{"field": "renewal_rate", "hint": "续约率影响 ARR 持续性"}] if rr <= 0 else [],
            "primary_kpi": ("ARR", round(arr_per_year, 0), "元/年")}


def _ue_platform(inputs: dict, *, gross_margin: float = 0.85, **_) -> dict[str, Any]:
    gmv = _f(inputs.get("monthly_gmv"))
    rate = _f(inputs.get("commission_rate"))
    sellers = _f(inputs.get("active_sellers"))
    if gmv <= 0 or rate <= 0:
        return _gray("缺少月 GMV 或佣金率")
    monthly_take = gmv * rate
    seller_arpu = monthly_take / sellers if sellers > 0 else 0
    metrics = {
        "monthly_take": round(monthly_take, 2),
        "take_rate": round(rate, 4),
        "monthly_gmv": round(gmv, 2),
        "active_sellers": round(sellers, 0),
        "seller_arpu_monthly": round(seller_arpu, 2),
    }
    health = "green"
    reason = f"平台月抽成≈¥{monthly_take:,.0f}，当前 take rate={rate:.1%}"
    if sellers <= 0:
        health = "yellow"
        reason += "；缺少活跃卖家规模，双边活跃度无法进一步分析"
    return {"applicable": True, "metrics": metrics, "health": health, "reason": reason,
            "missing": [] if sellers > 0 else [{"field": "active_sellers", "hint": "活跃卖家数影响双边健康"}],
            "primary_kpi": ("Take", round(monthly_take, 0), "元/月")}


def _ue_hardware(inputs: dict, **_) -> dict[str, Any]:
    units = _f(inputs.get("monthly_units"))
    price = _f(inputs.get("unit_price"))
    cost  = _f(inputs.get("unit_cost"))
    if price <= 0 or cost <= 0:
        return _gray("缺少出厂价或单位 BOM 成本")
    margin = (price - cost) / price
    monthly_gross = (price - cost) * units
    metrics = {
        "unit_price": round(price, 2),
        "unit_cost":  round(cost, 2),
        "unit_gross_margin": round(margin, 4),
        "monthly_units": round(units, 0),
        "monthly_gross_profit": round(monthly_gross, 2),
    }
    if margin <= 0:
        health, reason = "red", f"按当前单价与 BOM 成本，单位毛利率 {margin:.1%}，单件仍为负毛利"
    else:
        health, reason = "green", f"单位毛利率 {margin:.1%}，后续需结合售后、库存和渠道费用继续展开"
    return {"applicable": True, "metrics": metrics, "health": health, "reason": reason,
            "missing": [],
            "primary_kpi": ("单位毛利率", round(margin * 100, 1), "%")}


def _ue_grant(inputs: dict, *, cost_per_beneficiary: float = 0.0,
              baseline_cpb: tuple[float, float] | None = None, **_) -> dict[str, Any]:
    grants = _f(inputs.get("active_grants"))
    yearly = _f(inputs.get("grant_value_yearly"))
    rr = _f(inputs.get("renewal_rate"))
    bens = _f(inputs.get("beneficiaries_served"))
    if grants <= 0 or yearly <= 0:
        return _gray("缺少在期资助数或年金额")
    monthly_revenue = grants * yearly / 12
    cpb = cost_per_beneficiary if cost_per_beneficiary > 0 else (monthly_revenue / bens if bens > 0 else 0)
    metrics = {
        "monthly_grant_revenue": round(monthly_revenue, 2),
        "active_grants": round(grants, 0),
        "renewal_rate": round(rr, 2),
        "beneficiaries_per_month": round(bens, 0),
        "cost_per_beneficiary": round(cpb, 2) if cpb > 0 else None,
    }
    health = "green"
    reason = f"在期资助 {grants:.0f} 项 × 年额 ¥{yearly:,.0f}, 月均 ¥{monthly_revenue:,.0f}"
    if rr > 0:
        reason += f"，当前续期假设 {rr:.0%}"
    else:
        health = "yellow"
        reason += "；未给出续期假设，持续性需要人工复核"
    if baseline_cpb and cpb > 0:
        lo, hi = baseline_cpb
        mid = (lo + hi) / 2
        if mid > 0:
            dev = cpb / mid
            metrics["cpb_deviation"] = round(dev, 2)
            metrics["cpb_industry_range"] = [lo, hi]
            reason += f"，若参考现有区间，CPB 与参考中位差异约 {dev:.2f}x（仅供背景参考）"
    return {"applicable": True, "metrics": metrics, "health": health, "reason": reason,
            "missing": [{"field": "beneficiaries_served", "hint": "受益人数算 CPB 必填"}] if bens <= 0 else [],
            "primary_kpi": ("CPB", metrics.get("cost_per_beneficiary"), "元/人") if metrics.get("cost_per_beneficiary") else ("月资助收入", round(monthly_revenue, 0), "元")}


def _ue_donation(inputs: dict, **_) -> dict[str, Any]:
    donors = _f(inputs.get("monthly_donors"))
    avg = _f(inputs.get("avg_donation"))
    rr = _f(inputs.get("donor_retention"))
    if donors <= 0 or avg <= 0:
        return _gray("缺少月捐赠方或平均捐赠额")
    monthly_revenue = donors * avg
    expected_donor_lifetime = 1.0 / max(1.0 - rr, 0.05) if rr > 0 else 1.0
    donor_ltv = avg * expected_donor_lifetime
    metrics = {
        "monthly_donation_revenue": round(monthly_revenue, 2),
        "donor_ltv": round(donor_ltv, 2),
        "donor_retention": round(rr, 2),
        "expected_donor_lifetime_months": round(expected_donor_lifetime, 1),
    }
    if rr > 0:
        health, reason = "green", f"月捐赠收入≈¥{monthly_revenue:,.0f}，按当前留存假设预计捐赠方生命周期约 {expected_donor_lifetime:.1f} 月"
    else:
        health, reason = "yellow", f"月捐赠收入≈¥{monthly_revenue:,.0f}，但缺少捐赠方留存，难判断可持续性"
    return {"applicable": True, "metrics": metrics, "health": health, "reason": reason,
            "missing": [],
            "primary_kpi": ("月捐赠收入", round(monthly_revenue, 0), "元")}


PATTERN_UE_FN: dict[str, Any] = {
    "subscription":        _ue_subscription,
    "transaction":         _ue_transaction,
    "project_b2b":         _ue_b2b,
    "platform_commission": _ue_platform,
    "hardware_sales":      _ue_hardware,
    "grant_funded":        _ue_grant,
    "donation":            _ue_donation,
}


# ══════════════════════════════════════════════════════════════════
#  公共入口
# ══════════════════════════════════════════════════════════════════

def evaluate_stream_unit_econ(stream: dict[str, Any], *, gross_margin: float = 0.0,
                              cac: float = 0.0, cost_per_beneficiary: float = 0.0,
                              monthly_retention: float = 0.0, avg_lifetime_months: float = 0.0,
                              baseline_cpb: tuple[float, float] | None = None,
                              thresholds: dict[str, float] | None = None) -> dict[str, Any]:
    """对单条 revenue_stream 跑 pattern 对应的 unit_econ。
    返回 dict, 始终带 pattern_key/pattern_label/kind 三个 meta 字段。
    """
    s = normalize_stream(dict(stream))
    pkey = s.get("pattern_key") or "subscription"
    if pkey not in PATTERN_UE_FN:
        pkey = "subscription"
    inputs = s.get("inputs") or {}
    fn = PATTERN_UE_FN[pkey]
    # 默认毛利率按 pattern 大类粗估
    if gross_margin <= 0:
        gross_margin = {
            "subscription": 0.7, "transaction": 0.3, "project_b2b": 0.5,
            "platform_commission": 0.85, "hardware_sales": 0.0,
            "grant_funded": 0.0, "donation": 0.0,
        }.get(pkey, 0.5)
    try:
        result = fn(inputs, gross_margin=gross_margin, cac=cac,
                    monthly_retention=monthly_retention,
                    avg_lifetime_months=avg_lifetime_months,
                    cost_per_beneficiary=cost_per_beneficiary,
                    baseline_cpb=baseline_cpb, thresholds=thresholds)
    except Exception as exc:
        result = _gray(f"计算异常: {exc}")
    pattern_meta = PATTERNS.get(pkey)
    result["pattern_key"] = pkey
    result["pattern_label"] = pattern_meta.label if pattern_meta else pkey
    result["kind"] = PATTERN_KIND.get(pkey, "growth")
    return result


def get_pattern_levers(pattern_key: str) -> list[dict[str, Any]]:
    """返回该 pattern 的情景杠杆定义。"""
    return PATTERN_LEVERS.get(pattern_key, PATTERN_LEVERS["subscription"])


def get_field_range(pattern_key: str, field: str) -> dict[str, Any] | None:
    """查某个 pattern 某个字段的合理区间, 没有就返回 None。"""
    return REASONABLE_RANGES.get(pattern_key, {}).get(field)


def suggest_value(pattern_key: str, field: str, hint: str = "median") -> float | None:
    """建议一个默认值: hint='low'|'median'|'high'。无定义返回 None。"""
    r = get_field_range(pattern_key, field)
    if not r:
        return None
    return r.get(hint)


def detect_pattern_kind_mix(streams: list[dict[str, Any]]) -> dict[str, Any]:
    """统计一个项目里 pattern 大类的分布(用于"财务画像")。"""
    if not streams:
        return {"dominant_kind": None, "dominant_pattern": None, "kind_mix": {}, "pattern_mix": {}, "is_public": False}
    kind_revenue: dict[str, float] = {}
    pattern_revenue: dict[str, float] = {}
    total = 0.0
    for s in streams:
        s_norm = normalize_stream(dict(s))
        pkey = s_norm.get("pattern_key") or "subscription"
        kind = PATTERN_KIND.get(pkey, "growth")
        rev = max(0.0, _f(s.get("monthly_revenue")))
        if rev <= 0:
            from app.services.revenue_models import compute_stream_monthly_revenue
            rev, _ = compute_stream_monthly_revenue(s_norm)
        rev = max(rev, 1.0)  # 兜底, 让占比可计算
        kind_revenue[kind] = kind_revenue.get(kind, 0.0) + rev
        pattern_revenue[pkey] = pattern_revenue.get(pkey, 0.0) + rev
        total += rev
    if total <= 0:
        return {"dominant_kind": None, "dominant_pattern": None, "kind_mix": {}, "pattern_mix": {}, "is_public": False}
    kind_mix = {k: round(v / total, 3) for k, v in kind_revenue.items()}
    pattern_mix = {k: round(v / total, 3) for k, v in pattern_revenue.items()}
    dominant_kind = max(kind_mix, key=kind_mix.get)
    dominant_pattern = max(pattern_mix, key=pattern_mix.get)
    is_public = kind_mix.get("public", 0.0) >= 0.4
    return {
        "dominant_kind": dominant_kind,
        "dominant_pattern": dominant_pattern,
        "kind_mix": kind_mix,
        "pattern_mix": pattern_mix,
        "is_public": is_public,
        "total_monthly_revenue": round(total, 2),
    }


__all__ = [
    "REASONABLE_RANGES", "PATTERN_KIND", "PATTERN_LEVERS",
    "evaluate_stream_unit_econ", "get_pattern_levers",
    "get_field_range", "suggest_value", "detect_pattern_kind_mix",
]
