"""
finance_analyst — 财务建模六模块纯函数库

给学生的商业模式做"统计建模 / 经济学估算 / 合理性评估"。
六个模块：
  1. analyze_unit_economics    单位经济 (CAC/LTV/Payback)
  2. project_cash_flow         36 个月现金流推演 + Runway
  3. evaluate_rationality      合理性评估（对比行业基准）
  4. estimate_market_size      TAM/SAM/SOM 双路估算
  5. recommend_pricing_framework 定价策略框架
  6. match_funding_stage       融资节奏匹配

设计原则：
- 纯函数，无状态，无 IO
- 输入做 None/缺失兜底，不抛
- 每个模块返回统一结构（见文末 _empty_card）
- 同一份代码给 finance_guard（快判，跑子集不加 LLM）
  和 finance_report_service（深度，跑全部 + LLM 润色）共用
"""
from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
#  行业基准库
# ══════════════════════════════════════════════════════════════════
# 每个行业四个量：cac_range 获客成本区间（元），monthly_price 月价区间（元），
# monthly_retention 月留存率区间，gross_margin 毛利率区间。
# 数据来源：行业公开报告中位区间，仅供课程级建模教学使用。
#
# v2 起新增 thresholds 子字段：每个行业带自己的红/黄灯阈值。
# 设计原则：阈值是"行业共识"（来自 16Z/Bessemer/天风 SaaS 白皮书等行研机构的中位值），
# LLM 联网刷新时不抽 thresholds（怕被网页噪声污染），只刷价格/CAC/留存/毛利这四个区间。
# thresholds 缺失时由 _get_thresholds() 回退到 _DEFAULT_THRESHOLDS。

# 全局兜底阈值（找不到行业 thresholds 时用，对应"教科书 VC 通识"）
_DEFAULT_THRESHOLDS: dict[str, float] = {
    "ltv_cac_healthy": 3.0,           # LTV/CAC ≥ 3 绿
    "ltv_cac_warning": 1.5,           # 1.5–3 黄；< 1.5 红
    "payback_healthy_months": 6.0,    # Payback ≤ 6 月绿
    "payback_warning_months": 12.0,   # 6–12 月黄；> 12 月红
    "runway_red_months": 12.0,        # 现金 12 月内耗尽 → 红
    "runway_warning_months": 18.0,    # 12–18 月 → 黄
    "breakeven_green_months": 18.0,   # ≤ 18 月转正 → 绿
    "breakeven_warning_months": 24.0, # 18–24 月 → 黄
    "cpb_healthy_ratio": 1.0,         # CPB / 行业中位 ≤ 1.0 → 绿（仅公益）
    "cpb_warning_ratio": 1.5,         # 1.0–1.5 → 黄；> 1.5 → 红
}

INDUSTRY_BASELINES: dict[str, dict[str, Any]] = {
    "教育": {
        "cac_range": [30, 120],
        "monthly_price_range": [29, 99],
        "monthly_retention": [0.70, 0.90],
        "gross_margin": [0.60, 0.85],
        "avg_user_lifetime_months": 9,
        "note": "教育类看重留存与续费，CAC 对价格敏感度高",
        # 教育周期短、客单低，资金周转快，用通识但 Payback 略宽
        "thresholds": {
            "ltv_cac_healthy": 3.0,
            "ltv_cac_warning": 1.5,
            "payback_healthy_months": 9.0,
            "payback_warning_months": 15.0,
            "runway_red_months": 9.0,
            "runway_warning_months": 15.0,
            "breakeven_green_months": 18.0,
            "breakeven_warning_months": 24.0,
            "_source": "seed_v2",
        },
    },
    "SaaS": {
        "cac_range": [200, 1500],
        "monthly_price_range": [99, 999],
        "monthly_retention": [0.85, 0.97],
        "gross_margin": [0.70, 0.85],
        "avg_user_lifetime_months": 24,
        "note": "SaaS 关键看净收入留存（NRR）和回本周期",
        # SaaS 烧钱期长、回本慢但 LTV 高（订阅+高留存），按 16Z 经验值放宽 Payback / Breakeven
        "thresholds": {
            "ltv_cac_healthy": 3.0,
            "ltv_cac_warning": 1.5,
            "payback_healthy_months": 12.0,
            "payback_warning_months": 18.0,
            "runway_red_months": 12.0,
            "runway_warning_months": 18.0,
            "breakeven_green_months": 24.0,
            "breakeven_warning_months": 36.0,
            "_source": "seed_v2",
        },
    },
    "电商": {
        "cac_range": [40, 200],
        "monthly_price_range": [50, 300],
        "monthly_retention": [0.30, 0.70],
        "gross_margin": [0.15, 0.40],
        "avg_user_lifetime_months": 6,
        "note": "电商以复购频次为核心，毛利率普遍较薄",
        # 电商毛利薄、必须快回本：Payback 收紧到 3/6 月；LTV/CAC 口径放低（毛利薄难撑 3）
        "thresholds": {
            "ltv_cac_healthy": 2.0,
            "ltv_cac_warning": 1.0,
            "payback_healthy_months": 3.0,
            "payback_warning_months": 6.0,
            "runway_red_months": 6.0,
            "runway_warning_months": 12.0,
            "breakeven_green_months": 12.0,
            "breakeven_warning_months": 18.0,
            "_source": "seed_v2",
        },
    },
    "硬件": {
        "cac_range": [80, 400],
        "monthly_price_range": [199, 2999],
        "monthly_retention": [0.50, 0.80],
        "gross_margin": [0.20, 0.45],
        "avg_user_lifetime_months": 18,
        "note": "硬件重资产，注意库存 / 售后 / 供应链成本",
        # 硬件首付即回收大部分成本，Payback 容忍中等；Runway 因供应链/库存吃现金，红线偏紧
        "thresholds": {
            "ltv_cac_healthy": 2.5,
            "ltv_cac_warning": 1.2,
            "payback_healthy_months": 9.0,
            "payback_warning_months": 18.0,
            "runway_red_months": 12.0,
            "runway_warning_months": 18.0,
            "breakeven_green_months": 18.0,
            "breakeven_warning_months": 30.0,
            "_source": "seed_v2",
        },
    },
    "社会公益": {
        "cac_range": [10, 80],
        "monthly_price_range": [0, 0],
        "monthly_retention": [0.40, 0.75],
        "gross_margin": [0, 0],
        "avg_user_lifetime_months": 12,
        "cost_per_beneficiary_range": [50, 500],
        "note": "公益项目不适用 LTV/CAC 口径，应看单位受益人成本与可持续性",
        "is_nonprofit": True,
        # 公益不评 LTV/CAC/Payback；只看 CPB 偏离行业中位的比例
        "thresholds": {
            "cpb_healthy_ratio": 1.0,
            "cpb_warning_ratio": 1.5,
            "runway_red_months": 6.0,        # 公益项目对现金更敏感（依赖资助到位）
            "runway_warning_months": 12.0,
            "breakeven_green_months": 24.0,  # 公益不强求转正
            "breakeven_warning_months": 36.0,
            "_source": "seed_v2",
        },
    },
}


def _get_baseline(industry_hint: str, *, allow_online: bool = False) -> dict[str, Any]:
    """
    通过 finance_baseline_service 三层解析拿 baseline。
    service 不可用 / 出错时回退到硬编码 INDUSTRY_BASELINES。
    allow_online=False：只读本地缓存（供聊天侧 finance_guard 用）；
    allow_online=True：过期时尝试联网刷新（供深度报告用）。
    """
    try:
        from . import finance_baseline_service as _fbs
        return _fbs.resolve_baseline(industry_hint, allow_online=allow_online)
    except Exception as exc:
        logger.warning("resolve_baseline fallback to hardcoded (%s): %s", industry_hint, exc)
        ind = _match_industry(industry_hint)
        return dict(INDUSTRY_BASELINES.get(ind, INDUSTRY_BASELINES["教育"]))


def _match_industry(industry_hint: str) -> str:
    """把自由文本行业提示归一到内置基准库 key。"""
    text = (industry_hint or "").lower()
    if not text:
        return "教育"
    mapping = [
        (["公益", "慈善", "非营利", "社会创新", "乡村振兴", "特殊群体"], "社会公益"),
        (["saas", "企业服务", "b2b 软件", "订阅制", "to b"], "SaaS"),
        (["电商", "零售", "b2c 商品", "商城"], "电商"),
        (["硬件", "iot", "设备", "可穿戴", "传感器"], "硬件"),
        (["教育", "学习", "培训", "课程", "学生", "职业教育", "k12"], "教育"),
    ]
    for keys, label in mapping:
        if any(k in text for k in keys):
            return label
    return "教育"


# ══════════════════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════════════════

def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _in_range(value: float, lo: float, hi: float) -> bool:
    return lo <= value <= hi


def _verdict_from_ratio(value: float, healthy: float, warning: float, higher_better: bool = True) -> dict[str, Any]:
    """按阈值生成红黄绿灯。higher_better=True 时 value 越大越好。"""
    if higher_better:
        if value >= healthy:
            return {"level": "green", "score": min(1.0, value / (healthy * 1.3))}
        if value >= warning:
            return {"level": "yellow", "score": 0.5 + 0.3 * (value - warning) / max(healthy - warning, 0.1)}
        return {"level": "red", "score": max(0.0, 0.4 * value / warning)}
    # lower better
    if value <= healthy:
        return {"level": "green", "score": max(0.3, 1.0 - value / (healthy * 1.3))}
    if value <= warning:
        return {"level": "yellow", "score": 0.6 - 0.2 * (value - healthy) / max(warning - healthy, 0.1)}
    return {"level": "red", "score": 0.2}


def _empty_card(module: str, title: str) -> dict[str, Any]:
    return {
        "module": module,
        "title": title,
        "inputs": {},
        "outputs": {},
        "verdict": {"level": "gray", "score": 0.0, "reason": "输入不足，暂无法建模"},
        "framework_explain": "",
        "suggestions": [],
        "missing_inputs": [],
        "evidence_for_diagnosis": {},
        "baseline_meta": {},
    }


def _neutral_level(issue_count: int = 0, missing_count: int = 0, *, computed: bool = True) -> dict[str, Any]:
    """把结论语义降级为中性状态，而不是行业优劣判断。"""
    if not computed:
        return {"level": "gray", "score": 0.0}
    if issue_count > 0:
        return {"level": "red", "score": 0.35}
    if missing_count > 0:
        return {"level": "yellow", "score": 0.58}
    return {"level": "green", "score": 0.82}


def _summarize_unit_econ_levers(price: float, margin: float, retention: float, cac: float) -> list[str]:
    """返回当前单位经济最敏感的 2-3 个杠杆。"""
    if price <= 0 or margin <= 0 or retention <= 0 or retention >= 1 or cac <= 0:
        return []
    base_lifetime = 1.0 / max(1.0 - retention, 0.01)
    base_ratio = (price * margin * base_lifetime) / cac if cac > 0 else 0
    if base_ratio <= 0:
        return []

    lever_impacts: list[tuple[str, float, str]] = []

    def _impact(name: str, new_price: float, new_margin: float, new_retention: float, new_cac: float, desc: str) -> None:
        lifetime = 1.0 / max(1.0 - new_retention, 0.01)
        new_ratio = (new_price * new_margin * lifetime) / max(new_cac, 1e-6)
        delta = abs(new_ratio - base_ratio) / base_ratio
        lever_impacts.append((name, delta, desc))

    _impact("price", price * 1.1, margin, retention, cac, "提价会线性抬高月毛利和 LTV")
    _impact("margin", price, min(margin * 1.1, 0.99), retention, cac, "毛利改善会直接改善单用户回收")
    _impact("retention", price, margin, min(retention + 0.05, 0.99), cac, "留存改善会放大生命周期价值")
    _impact("cac", price, margin, retention, cac * 0.9, "获客成本下降会直接缩短回收周期")
    lever_impacts.sort(key=lambda item: item[1], reverse=True)
    return [f"{name}: {desc}" for name, _, desc in lever_impacts[:3]]


def _summarize_cashflow_implications(
    projection: list[dict[str, Any]],
    *,
    fixed: float,
    cap0: float,
    breakeven_month: int | None,
    runway_exhausted_month: int | None,
) -> list[str]:
    if not projection:
        return []
    month1 = projection[0]
    month6 = projection[min(5, len(projection) - 1)]
    last = projection[-1]
    conclusions: list[str] = []
    if month1.get("revenue", 0) < fixed and fixed > 0:
        conclusions.append("前期收入低于固定成本，模型早期更依赖启动资金或外部融资缓冲")
    if breakeven_month is not None:
        conclusions.append(f"若维持当前增长轨迹，模型会在第 {breakeven_month} 个月进入单月正现金流")
    elif runway_exhausted_month is not None:
        conclusions.append(f"若不改假设，累计现金会在第 {runway_exhausted_month} 个月前后转负")
    else:
        conclusions.append("在当前 36 个月窗口内，模型仍主要依赖增长兑现而非自然回本")
    if month6.get("revenue", 0) > month1.get("revenue", 0) * 2:
        conclusions.append("该现金流轨迹对增长假设较敏感，后段收入占比明显高于前段")
    if last.get("cash", 0) > cap0 and cap0 > 0:
        conclusions.append("按当前假设，累计现金最终高于起始资金，说明模型具备自我滚动空间")
    return conclusions[:3]


def _summarize_market_implications(outputs: dict[str, Any]) -> list[str]:
    conclusions: list[str] = []
    tam = _safe_float(outputs.get("bottom_up_tam"))
    sam = _safe_float(outputs.get("bottom_up_sam"))
    som = _safe_float(outputs.get("bottom_up_som_yr1"))
    if tam > 0 and sam > 0:
        if sam > tam:
            conclusions.append("当前 SAM 已大于 TAM，市场边界定义存在冲突")
        else:
            conclusions.append(f"当前模型把可服务市场收敛到 TAM 的 {sam / tam:.1%}，说明已经给出了明确服务边界")
    if sam > 0 and som > 0:
        if som > sam:
            conclusions.append("首年 SOM 已超过 SAM，说明落地节奏或转化口径还没有统一")
        else:
            conclusions.append(f"首年 SOM 占 SAM 的 {som / sam:.1%}，说明已经把“能服务”与“首年能拿下”区分开了")
    ratio = _safe_float(outputs.get("tam_crosscheck_ratio"))
    if ratio > 0:
        conclusions.append(f"自上而下与自下而上 TAM 相差约 {ratio:.2f}x，适合继续核对总量口径和下钻假设")
    return conclusions[:3]


def _extract_meta(baseline: dict[str, Any]) -> dict[str, Any]:
    """从 baseline dict 里剥出 _meta（resolve_baseline 附带的来源追踪信息）。"""
    meta = baseline.get("_meta") if isinstance(baseline, dict) else None
    if isinstance(meta, dict):
        return dict(meta)
    return {}


def _get_thresholds(baseline: dict[str, Any]) -> dict[str, float]:
    """
    从 baseline 取该行业的红/黄灯阈值，缺哪条就用 _DEFAULT_THRESHOLDS 补哪条。
    向后兼容：旧版 baseline 文件没有 thresholds 字段时整体回退到 default。
    """
    out: dict[str, float] = dict(_DEFAULT_THRESHOLDS)
    if isinstance(baseline, dict):
        ind_th = baseline.get("thresholds")
        if isinstance(ind_th, dict):
            for k, v in ind_th.items():
                if k.startswith("_"):
                    continue  # 跳过 _source 等元字段
                try:
                    out[k] = float(v)
                except (TypeError, ValueError):
                    continue
    return out


def _thresholds_meta(baseline: dict[str, Any]) -> dict[str, Any]:
    """用于卡片输出 thresholds_used 字段：暴露阈值与出处。"""
    th = _get_thresholds(baseline)
    src = "default"
    if isinstance(baseline, dict):
        ind_th = baseline.get("thresholds")
        if isinstance(ind_th, dict):
            src = str(ind_th.get("_source") or "industry")
    return {"values": th, "source": src}


# ══════════════════════════════════════════════════════════════════
#  模块 1：单位经济 Unit Economics
# ══════════════════════════════════════════════════════════════════

def analyze_unit_economics(
    assumptions: dict,
    industry: str = "教育",
    *,
    allow_online: bool = False,
) -> dict[str, Any]:
    """
    关键假设字段（都在 assumptions 里，允许缺失）:
      - monthly_price:       月价 / ARPU
      - gross_margin:        毛利率 0-1
      - monthly_retention:   月留存率 0-1
      - cac:                 获客成本
      - avg_lifetime_months: （可选）平均留存月数，若缺用 1/(1-retention)
    allow_online: 是否允许基线数据联网刷新（深度报告用 True，聊天侧用 False）。

    新行为(2025-04 升级)：当 assumptions 里带 by_stream 时，自动按 pattern 分支跑
    finance_pattern_formulas.evaluate_stream_unit_econ, 按月营收加权出综合 verdict。
    若同时出现 grant_funded / donation, 自动切公益口径(不要求 LTV/CAC)。
    """
    # --- pattern 化分支（优先于老 SaaS 逻辑） ---
    by_stream = assumptions.get("by_stream") if isinstance(assumptions, dict) else None
    if isinstance(by_stream, list) and by_stream:
        return _analyze_unit_econ_pattern_aware(assumptions, industry=industry, allow_online=allow_online)

    ind = _match_industry(industry)
    baseline = _get_baseline(industry, allow_online=allow_online)
    card = _empty_card("unit_economics", "单位经济分析")
    card["baseline_meta"] = _extract_meta(baseline)
    card["thresholds_used"] = _thresholds_meta(baseline)

    is_nonprofit = baseline.get("is_nonprofit")

    price = _safe_float(assumptions.get("monthly_price"))
    margin = _safe_float(assumptions.get("gross_margin"))
    retention = _safe_float(assumptions.get("monthly_retention"))
    cac = _safe_float(assumptions.get("cac"))
    lifetime = _safe_float(assumptions.get("avg_lifetime_months"))

    missing: list[dict] = []
    if price <= 0 and not is_nonprofit:
        missing.append({"field": "monthly_price", "hint": "请在财政预算→收入模型填入月价", "target_tab": "biz"})
    if margin <= 0 and not is_nonprofit:
        missing.append({"field": "gross_margin", "hint": "毛利率=（单价-变动成本）/单价，先估个大致值", "target_tab": "biz"})
    if retention <= 0 and retention < 1:
        missing.append({"field": "monthly_retention", "hint": "月留存率（0-1），可从过往项目参考", "target_tab": "biz"})
    if cac <= 0:
        missing.append({"field": "cac", "hint": "每获取一个付费用户的成本，含广告/人力", "target_tab": "biz"})

    card["inputs"] = {
        "monthly_price": price,
        "gross_margin": margin,
        "monthly_retention": retention,
        "cac": cac,
        "industry": ind,
    }
    card["missing_inputs"] = missing

    # 公益项目切换替代口径
    if is_nonprofit:
        cpb = _safe_float(assumptions.get("cost_per_beneficiary"))
        if cpb <= 0:
            missing.append({
                "field": "cost_per_beneficiary",
                "hint": "覆盖一个受益人的平均成本",
                "target_tab": "biz",
            })
            card["framework_explain"] = (
                "公益项目不直接适用 LTV/CAC。建议看「单位受益人成本」CPB = 年度支出 / 服务的受益人数，"
                "以及「可持续性比率」= 可持续性收入（会员费/捐赠续期） / 年度刚性支出。"
            )
            card["suggestions"] = [
                "用 CPB 评估效率，再结合受益人画像说服资助方",
                "加入「可持续性收入占比」指标（建议 > 40%）",
            ]
            return card
        baseline_low, baseline_high = baseline["cost_per_beneficiary_range"]
        ref_mid = (baseline_low + baseline_high) / 2 if (baseline_low + baseline_high) > 0 else 0
        dev = cpb / ref_mid if ref_mid > 0 else 0
        card["outputs"] = {
            "cost_per_beneficiary": cpb,
            "reference_range": [baseline_low, baseline_high],
            "reference_gap_ratio": round(dev, 2) if dev > 0 else None,
        }
        verdict_meta = _neutral_level(missing_count=len(missing))
        card["verdict"] = {
            "level": verdict_meta["level"],
            "score": round(verdict_meta["score"], 2),
            "reason": (
                f"已按当前数据算出单位受益人成本 CPB≈¥{cpb:.0f}"
                + (
                    f"，若参考现有样例区间 ¥{baseline_low:.0f}-{baseline_high:.0f}，与参考中位差异约 {dev:.2f}x"
                    if dev > 0 else ""
                )
                + "。该差异仅用于帮助统一口径，不直接代表优劣。"
            ),
        }
        card["framework_explain"] = (
            "CPB（Cost Per Beneficiary）衡量覆盖一个受益对象平均需要多少资源。"
            "本模块只负责把项目自己的 CPB 算清楚，并把它与公开资料中的现有样例口径并排展示，"
            "帮助你判断后续应该补哪类证据。"
        )
        card["suggestions"] = [
            "补充受益对象定义，避免不同项目把“人次”“人”混在一起",
            "如果要对外展示 CPB，请同时写清资金口径、受益人统计周期和服务边界",
        ]
        card["evidence_for_diagnosis"]["H8"] = 0.72 if cpb > 0 else 0.3
        return card

    # 商业项目主路径
    if price <= 0 or cac <= 0 or retention <= 0:
        card["verdict"]["reason"] = "缺少关键假设（定价 / CAC / 留存），无法完成单位经济建模"
        card["framework_explain"] = (
            "单位经济（Unit Economics）衡量“每获得一个用户，在其生命周期内能产生多少毛利”。"
            "本模块会先把公式拆开，再指出哪些假设缺失或哪些地方在当前假设下无法回本。"
        )
        return card

    margin_eff = margin if margin > 0 else 0.7  # 缺失时默认 70%
    if lifetime <= 0:
        # 月留存 r → 期望留存月数 = 1/(1-r)
        lifetime = 1.0 / max(1.0 - retention, 0.01)

    ltv = price * margin_eff * lifetime
    ratio = ltv / cac if cac > 0 else 0
    # Payback Period（月）= CAC / 月毛利
    monthly_gross = price * margin_eff
    payback = cac / monthly_gross if monthly_gross > 0 else float("inf")

    card["outputs"] = {
        "arpu": round(price, 2),
        "gross_margin": round(margin_eff, 2),
        "avg_lifetime_months": round(lifetime, 1),
        "ltv": round(ltv, 2),
        "cac": round(cac, 2),
        "ltv_cac_ratio": round(ratio, 2),
        "payback_period_months": round(payback, 1) if math.isfinite(payback) else None,
    }

    issue_count = 0
    reason = f"已按当前假设拆出 LTV/CAC={ratio:.2f}"
    if math.isfinite(payback):
        reason += f"，Payback≈{payback:.1f} 月"
    if ratio < 1:
        issue_count += 1
        reason += "；单用户生命周期毛利尚不足以覆盖获客成本"
    if not math.isfinite(payback):
        issue_count += 1
        reason += "；当前月毛利不足，无法形成可计算的回收周期"
    elif ratio >= 1:
        reason += "；这意味着当前获客投入在生命周期内具备回收可能"
    verdict_meta = _neutral_level(issue_count=issue_count, missing_count=len(missing))
    driver_notes = _summarize_unit_econ_levers(price, margin_eff, retention, cac)
    card["outputs"]["analysis_conclusion"] = (
        "单用户生命周期价值尚不能覆盖获客成本，规模扩大只会放大亏损"
        if ratio < 1 else
        "当前模型已经能形成正向单位经济，后续重点转向回收速度和留存稳定性"
    )
    if driver_notes:
        card["outputs"]["key_levers"] = driver_notes
    card["verdict"] = {"level": verdict_meta["level"], "score": round(verdict_meta["score"], 2), "reason": reason}

    card["framework_explain"] = (
        "**单位经济三件套**：\n"
        "- LTV（用户终身价值）= 月 ARPU × 毛利率 × 平均生命周期月数\n"
        "- CAC（获客成本）= 获客投入 / 新增付费用户数\n"
        "- Payback（回本周期）= CAC / 月毛利\n\n"
        "本模块不再用外部行业阈值硬判“高/低/合理”，而是只回答三件事：\n"
        "1. 公式能否完整算出来；2. 当前假设下是否能覆盖获客成本；3. 还缺哪些关键变量。"
    )
    card["suggestions"] = _build_ue_suggestions(ratio, payback, price, baseline, ind, None)
    if driver_notes:
        card["suggestions"] += [f"敏感杠杆：{note}" for note in driver_notes[:2]]

    card["evidence_for_diagnosis"]["H8"] = 0.82 if ratio >= 1 else 0.35
    card["evidence_for_diagnosis"]["H18"] = 0.6 if retention > 0 else 0.3
    return card


# ──────────────────────────────────────────────────────────────────
#  Pattern-aware Unit Economics（新主路径，by_stream 模式）
# ──────────────────────────────────────────────────────────────────

def _analyze_unit_econ_pattern_aware(
    assumptions: dict,
    *,
    industry: str = "教育",
    allow_online: bool = False,
) -> dict[str, Any]:
    """每条 revenue_stream 各自走自己 pattern 的 unit_econ; 按月营收加权 verdict。"""
    from app.services.finance_pattern_formulas import (
        evaluate_stream_unit_econ, PATTERN_KIND,
    )

    by_stream: list[dict[str, Any]] = assumptions.get("by_stream") or []
    is_public_project = bool(assumptions.get("is_public"))

    # 公益项目把行业兜底到"社会公益"
    if is_public_project and industry not in ("社会公益",):
        industry = "社会公益"

    ind = _match_industry(industry)
    baseline = _get_baseline(industry, allow_online=allow_online)
    thresholds = _get_thresholds(baseline)
    card = _empty_card("unit_economics", "单位经济分析（按收入模式分支）")
    card["baseline_meta"] = _extract_meta(baseline)
    card["thresholds_used"] = _thresholds_meta(baseline)

    cac = _safe_float(assumptions.get("cac"))
    margin = _safe_float(assumptions.get("gross_margin"))
    cpb = _safe_float(assumptions.get("cost_per_beneficiary"))
    baseline_cpb = None
    if baseline.get("cost_per_beneficiary_range"):
        try:
            lo, hi = baseline["cost_per_beneficiary_range"]
            baseline_cpb = (float(lo), float(hi))
        except Exception:
            baseline_cpb = None

    per_stream_results: list[dict[str, Any]] = []
    total_revenue = 0.0
    for s in by_stream:
        rev = max(0.0, _safe_float(s.get("monthly_revenue")))
        result = evaluate_stream_unit_econ(
            s,
            gross_margin=margin,
            cac=cac,
            cost_per_beneficiary=cpb,
            monthly_retention=_safe_float(assumptions.get("monthly_retention")),
            avg_lifetime_months=_safe_float(assumptions.get("avg_lifetime_months")),
            baseline_cpb=baseline_cpb,
            thresholds=thresholds,
        )
        result["weight"] = round(rev, 2)
        result["stream_name"] = s.get("name") or result.get("pattern_label")
        per_stream_results.append(result)
        total_revenue += rev

    # 加权状态：只反映“信息完备度 / 是否存在内部矛盾”
    level_score = {"green": 0.82, "yellow": 0.58, "red": 0.35, "gray": 0.18}
    weighted_score = 0.0
    issue_count = 0
    missing_count = 0
    weight_sum = 0.0
    for r in per_stream_results:
        w = max(r["weight"], 1.0)
        weighted_score += level_score.get(r["health"], 0.5) * w
        weight_sum += w
        if r["health"] == "red":
            issue_count += 1
        elif r["health"] == "yellow":
            missing_count += 1
        elif r["health"] == "gray":
            missing_count += 1
    overall_score = weighted_score / weight_sum if weight_sum > 0 else 0.5
    verdict_meta = _neutral_level(issue_count=issue_count, missing_count=missing_count, computed=bool(per_stream_results))
    level = verdict_meta["level"]

    # 把每条流压成可读 reason
    pieces = []
    stream_conclusions: list[str] = []
    for r in per_stream_results[:3]:
        kpi = r.get("primary_kpi") or ("", None, "")
        if kpi[0] and kpi[1] is not None:
            pieces.append(f"[{r.get('pattern_label')}] {kpi[0]}={kpi[1]}{kpi[2]}")
        else:
            pieces.append(f"[{r.get('pattern_label')}] {r.get('reason')}")
    for r in per_stream_results:
        stream_conclusions.append(f"[{r.get('pattern_label')}] {r.get('reason')}")
    reason = "；".join(pieces) if pieces else "未识别到收入流"
    if issue_count > 0:
        reason += "；其中至少一条收入流在当前假设下存在内部矛盾，需要重点复核"
    elif missing_count > 0:
        reason += "；已完成初步拆解，但仍有部分关键假设缺失"

    card["inputs"] = {
        "industry": ind,
        "stream_count": len(by_stream),
        "is_public_project": is_public_project,
        "dominant_pattern": assumptions.get("dominant_pattern"),
        "dominant_kind": assumptions.get("dominant_kind"),
        "kind_mix": assumptions.get("kind_mix"),
        "pattern_mix": assumptions.get("pattern_mix"),
    }
    card["outputs"] = {
        "per_stream": per_stream_results,
        "total_monthly_revenue": round(total_revenue, 2),
        "weighted_review_score": round(overall_score, 2),
        "stream_conclusions": stream_conclusions[:5],
        "analysis_conclusion": (
            "多条收入流之间已经可以形成可读的收入结构，可继续验证各流之间的协同和资源分配"
            if issue_count == 0 and missing_count == 0
            else "当前收入结构已经初步成形，但仍需补关键变量，才能判断每条流对整体模型的真实贡献"
            if issue_count == 0
            else "当前至少有一条核心收入流在现有假设下会拖累整体模型，应优先复核这条流的关键假设"
        ),
    }
    card["verdict"] = {
        "level": level,
        "score": round(verdict_meta["score"], 2),
        "reason": reason,
    }
    framework = (
        "**单位经济(按收入模式分支)**：本项目识别到 "
        f"{len(by_stream)} 条收入流, "
        f"主导模式 {assumptions.get('dominant_pattern') or '—'}({assumptions.get('dominant_kind') or '—'} 大类)。\n\n"
        "- 订阅型: 先拆付费漏斗、月毛利、留存与 CAC 是否可串起来\n"
        "- 交易型: 先拆客单价、复购、月人均毛利与回收周期\n"
        "- 项目制 B2B: 先拆合同金额、周期、续约与 ARR\n"
        "- 平台抽佣: 先拆 GMV、抽成率、卖家规模与平台抽成\n"
        "- 硬件: 先拆单价、单位成本与单件毛利\n"
        "- 公益: 先拆资助/捐赠来源、受益人数与 CPB"
    )
    card["framework_explain"] = framework
    suggestions: list[str] = []
    for r in per_stream_results:
        if r.get("missing"):
            for m in r["missing"]:
                suggestions.append(f"[{r.get('pattern_label')}] 补充 {m.get('field')}: {m.get('hint')}")
        if r["health"] == "red":
            suggestions.append(f"[{r.get('pattern_label')}] {r.get('reason')}")
    card["suggestions"] = suggestions[:8]

    # 证据回流：H8 单位经济、H18 复购/留存
    card["evidence_for_diagnosis"]["H8"] = 0.8 if level == "green" else 0.55 if level == "yellow" else 0.3
    return card


def _build_ue_suggestions(
    ratio: float,
    payback: float,
    price: float,
    baseline: dict,
    ind: str,
    thresholds: dict[str, float] | None = None,
) -> list[str]:
    out: list[str] = []
    if ratio < 1:
        out.append("当前假设下 LTV 尚未覆盖 CAC，优先检查定价、毛利和获客口径是否口径一致")
        out.append("把 CAC 分渠道拆开，区分投放成本、销售人力和转介绍成本")
    else:
        out.append("下一步可做敏感性分析：分别只调价格、留存、CAC，观察哪一项对 LTV/CAC 影响最大")
    if math.isfinite(payback):
        out.append(f"把 Payback {payback:.1f} 月写成月度回收路径，便于和现金流模块对照")
    if price > 0:
        out.append(f"为当前定价 ¥{price:.0f} 补一条证据链：用户支付意愿、竞品价位或成本拆解至少选一类")
    return out


# ══════════════════════════════════════════════════════════════════
#  模块 2：36 个月现金流推演
# ══════════════════════════════════════════════════════════════════

def project_cash_flow(
    assumptions: dict,
    months: int = 36,
    *,
    industry: str = "教育",
    allow_online: bool = False,
) -> dict[str, Any]:
    """
    关键假设：
      - initial_capital:        起始资金
      - fixed_costs_monthly:    月固定成本
      - variable_cost_per_user: 每付费用户月变动成本
      - monthly_price:          月价
      - new_users_per_month:    月新增付费用户
      - monthly_retention:      月留存率
      - growth_rate_monthly:    月增长率（new_users 的自然增长）
    industry 决定 runway / breakeven 红黄线（不同行业容忍度不同）。
    """
    card = _empty_card("cash_flow", "现金流推演与 Runway")
    baseline = _get_baseline(industry, allow_online=allow_online)
    ind = _match_industry(industry)
    card["baseline_meta"] = _extract_meta(baseline)
    card["thresholds_used"] = _thresholds_meta(baseline)

    cap0 = _safe_float(assumptions.get("initial_capital"))
    fixed = _safe_float(assumptions.get("fixed_costs_monthly"))
    var = _safe_float(assumptions.get("variable_cost_per_user"))
    price = _safe_float(assumptions.get("monthly_price"))
    new_users = _safe_float(assumptions.get("new_users_per_month"))
    retention = _safe_float(assumptions.get("monthly_retention"))
    growth = _safe_float(assumptions.get("growth_rate_monthly"))

    # pattern-aware: 当存在 by_stream 时, 用每条流自己 pattern 的月营收做种子
    by_stream = assumptions.get("by_stream") if isinstance(assumptions, dict) else None
    streams_revenue_seed = 0.0
    if isinstance(by_stream, list) and by_stream:
        streams_revenue_seed = sum(max(0.0, _safe_float(s.get("monthly_revenue"))) for s in by_stream)
        # 如果用户没显式给 monthly_price/new_users 但有 by_stream, 直接用 streams 替代后续 paying×price 估算
        if streams_revenue_seed > 0 and (price <= 0 or new_users <= 0):
            # 在月度模拟里把这条作为"已知营收基线"传入 (后续 for-loop 会用)
            pass

    card["inputs"] = {
        "initial_capital": cap0,
        "fixed_costs_monthly": fixed,
        "variable_cost_per_user": var,
        "monthly_price": price,
        "new_users_per_month": new_users,
        "monthly_retention": retention,
        "growth_rate_monthly": growth,
        "streams_baseline_revenue": round(streams_revenue_seed, 2) if streams_revenue_seed > 0 else None,
        "stream_count": len(by_stream) if isinstance(by_stream, list) else 0,
    }

    missing = []
    if fixed <= 0:
        missing.append({"field": "fixed_costs_monthly", "hint": "月固定成本（服务器/房租/工资）", "target_tab": "cost"})
    if price <= 0:
        missing.append({"field": "monthly_price", "hint": "月均单价", "target_tab": "biz"})
    card["missing_inputs"] = missing

    if fixed <= 0 and price <= 0 and streams_revenue_seed <= 0:
        card["verdict"]["reason"] = "缺少月固定成本或定价/收入流，无法模拟现金流"
        card["framework_explain"] = (
            "**现金流推演**一般用 36 个月 Excel 模型：逐月模拟付费用户存量、MRR、成本、净现金和累计现金。"
            "**Runway（剩余跑道）** = 当前现金 / 平均月烧钱率，是投资人判断下一轮紧迫度的核心指标。"
        )
        return card

    # 逐月模拟
    paying = 0.0  # 存量付费用户
    cash = cap0
    projection = []
    breakeven_month: int | None = None
    runway_exhausted_month: int | None = None

    for m in range(1, months + 1):
        new_m = new_users * ((1 + growth) ** (m - 1)) if growth else new_users
        paying = paying * max(0.0, retention) + new_m  # 留存衰减 + 新增
        # pattern-aware: 优先用 streams_revenue_seed (按月增长扩张), 再叠加 paying × price 的兜底
        if streams_revenue_seed > 0:
            base_growth = (1 + growth) ** (m - 1) if growth else 1.0
            revenue = streams_revenue_seed * base_growth
            if price > 0 and paying > 0:
                # 学生既配置了 streams, 又显式给了 price + new_users → 视为"双轨", 取较保守者(streams 通常更准)
                revenue = max(revenue, paying * price * 0.0)  # 不叠加, 避免双计
        else:
            revenue = paying * price
        cost = fixed + var * paying
        net = revenue - cost
        cash += net
        projection.append({
            "month": m,
            "paying_users": round(paying, 1),
            "revenue": round(revenue, 2),
            "cost": round(cost, 2),
            "net": round(net, 2),
            "cash": round(cash, 2),
        })
        if breakeven_month is None and net > 0 and m >= 2:
            breakeven_month = m
        if runway_exhausted_month is None and cash < 0:
            runway_exhausted_month = m

    # burn rate / runway
    early = projection[:6] if len(projection) >= 6 else projection
    avg_burn = max(0.0, -sum(p["net"] for p in early) / max(len(early), 1))
    runway_months = (cap0 / avg_burn) if avg_burn > 0 else None

    card["outputs"] = {
        "months_simulated": months,
        "breakeven_month": breakeven_month,
        "runway_exhausted_month": runway_exhausted_month,
        "avg_burn_rate_first6": round(avg_burn, 2),
        "runway_months": round(runway_months, 1) if runway_months else None,
        "end_cash": round(cash, 2),
        "projection": projection,
        "peak_paying_users": round(max(p["paying_users"] for p in projection), 1),
        "total_revenue_36m": round(sum(p["revenue"] for p in projection), 2),
    }
    implications = _summarize_cashflow_implications(
        projection,
        fixed=fixed,
        cap0=cap0,
        breakeven_month=breakeven_month,
        runway_exhausted_month=runway_exhausted_month,
    )
    if implications:
        card["outputs"]["analysis_conclusion"] = implications[0]
        card["outputs"]["cashflow_implications"] = implications

    if runway_exhausted_month is not None:
        level = "red"
        reason = f"按当前假设，模拟到第 {runway_exhausted_month} 个月累计现金转负"
        card["evidence_for_diagnosis"]["H24"] = 0.3
    elif breakeven_month is not None:
        level = "green"
        reason = (
            f"按当前假设，第 {breakeven_month} 个月开始月度净现金转正"
            + (f"，静态 Runway≈{runway_months:.1f} 月" if runway_months else "")
        )
        card["evidence_for_diagnosis"]["H24"] = 0.8
    else:
        level = "yellow"
        reason = f"按当前假设，36 个月窗口内尚未出现单月净现金转正，末月现金约 ¥{cash:.0f}"
        card["evidence_for_diagnosis"]["H24"] = 0.5
    card["verdict"] = {
        "level": level,
        "score": {"green": 0.82, "yellow": 0.58, "red": 0.35}.get(level, 0.3),
        "reason": reason,
    }

    card["framework_explain"] = (
        "**现金流推演 36 月模型**：逐月计算付费存量 = 上月存量 × 留存率 + 新增；\n"
        "MRR = 付费存量 × ARPU；成本 = 固定 + 变动×付费数；净现金 = MRR - 成本；累计现金 = 上月累计 + 净。\n\n"
        "本模块不再把回本月份或 Runway 与行业阈值直接比较，而是直接展示“在你当前假设下会发生什么”。"
        "如果你需要对外论证，再补充融资计划、价格实验或渠道拆解来解释这些轨迹。"
    )
    card["suggestions"] = _build_cf_suggestions(
        breakeven_month, runway_exhausted_month, avg_burn, cap0, None
    )
    if implications:
        card["suggestions"] += [f"影响判断：{item}" for item in implications[1:3]]

    return card


def _build_cf_suggestions(
    breakeven: int | None,
    exhausted: int | None,
    burn: float,
    cap: float,
    thresholds: dict[str, float] | None = None,
) -> list[str]:
    out: list[str] = []
    if exhausted is not None:
        out.append(f"把第 {exhausted} 个月现金转负前的关键变量单独列出来：收入、固定成本、融资补充")
        out.append("建议追加一个“减支版”与“融资版”场景，观察现金断点是否后移")
    if breakeven is None:
        out.append("36 个月内未转正时，优先把价格、转化、固定成本分别做单变量敏感性分析")
    elif breakeven:
        out.append(f"把第 {breakeven} 个月转正的来源拆开，说明是价格提升、用户增长还是成本下降驱动")
    if burn > 0 and cap > 0 and burn > cap / 6:
        out.append(f"当前前 6 个月平均净流出约 ¥{burn:.0f}/月，建议把大额固定成本单列解释")
    out.append("至少保留三组情景：基线、保守、积极，并说明每组只改了哪些假设")
    return out


# ══════════════════════════════════════════════════════════════════
#  模块 3：合理性评估（对比行业基准）
# ══════════════════════════════════════════════════════════════════

def evaluate_rationality(
    collected: dict,
    industry: str = "教育",
    *,
    allow_online: bool = False,
) -> dict[str, Any]:
    """
    不再做“是否落在行业合理区间”的硬判断，只做口径一致性与内部约束自检。
    """
    ind = _match_industry(industry)
    baseline = _get_baseline(industry, allow_online=allow_online)
    card = _empty_card("rationality", "假设自检与口径一致性")
    card["baseline_meta"] = _extract_meta(baseline)
    card["thresholds_used"] = _thresholds_meta(baseline)
    fields = (
        "monthly_price", "cac", "monthly_retention", "gross_margin",
        "target_user_population", "serviceable_user_population",
        "first_year_reach_users", "paid_conversion_rate", "annual_arpu"
    )
    card["inputs"] = {"industry": ind, **{k: v for k, v in collected.items() if k in fields}}

    checks: list[dict[str, Any]] = []
    issue_count = 0
    review_count = 0

    def _add(field: str, level: str, note: str) -> None:
        nonlocal issue_count, review_count
        checks.append({"field": field, "level": level, "note": note})
        if level == "red":
            issue_count += 1
        elif level == "yellow":
            review_count += 1

    monthly_price = _safe_float(collected.get("monthly_price"))
    cac = _safe_float(collected.get("cac"))
    retention = _safe_float(collected.get("monthly_retention"))
    margin = _safe_float(collected.get("gross_margin"))
    cpb = _safe_float(collected.get("cost_per_beneficiary"))
    target_pop = _safe_float(collected.get("target_user_population"))
    serviceable_pop = _safe_float(collected.get("serviceable_user_population"))
    reach = _safe_float(collected.get("first_year_reach_users"))
    conv = _safe_float(collected.get("paid_conversion_rate"))
    arpu_yr = _safe_float(collected.get("annual_arpu"))
    is_public = bool(collected.get("is_public"))

    if is_public:
        if cpb <= 0:
            _add("cost_per_beneficiary", "yellow", "尚未填写单位受益人成本，公益项目难以比较覆盖效率")
        else:
            _add("cost_per_beneficiary", "green", f"已给出单位受益人成本：¥{cpb:.2f}/人")

        if target_pop <= 0:
            _add("target_user_population", "yellow", "尚未填写目标受益人总量，TAM 无法估算")
        else:
            _add("target_user_population", "green", f"已给出目标受益人总量：{target_pop:,.0f}")

        if serviceable_pop > target_pop > 0:
            _add("serviceable_user_population", "red", "SAM 人群不能大于目标总受益人群")
        elif serviceable_pop <= 0:
            _add("serviceable_user_population", "yellow", "尚未填写可服务人群，SAM 无法估算")
        else:
            _add("serviceable_user_population", "green", f"已给出可服务人群：{serviceable_pop:,.0f}")

        if reach > serviceable_pop > 0:
            _add("first_year_reach_users", "yellow", "首年覆盖人数超过当前可服务人群，请确认服务边界")
        elif reach <= 0:
            _add("first_year_reach_users", "yellow", "尚未填写首年覆盖人数，SOM 无法估算")
        else:
            _add("first_year_reach_users", "green", f"已给出首年覆盖人数：{reach:,.0f}")

        if conv < 0 or conv > 1:
            _add("paid_conversion_rate", "red", "服务转化率需要落在 0-1 之间")
        elif conv == 0:
            _add("paid_conversion_rate", "yellow", "尚未填写服务转化率，首年实际覆盖强度无法估算")
        else:
            _add("paid_conversion_rate", "green", f"已给出服务转化率：{conv:.1%}")

        if arpu_yr < 0:
            _add("annual_arpu", "red", "年 ARPU 不能为负数")
        elif arpu_yr == 0:
            _add("annual_arpu", "yellow", "尚未填写按资助/服务折算的年 ARPU，TAM/SAM 金额口径无法形成")
        else:
            _add("annual_arpu", "green", f"已给出折算后的年 ARPU：¥{arpu_yr:,.0f}")

        card["outputs"] = {
            "checks": checks,
            "industry_note": baseline.get("note", ""),
            "analysis_conclusion": (
                "公益项目的服务边界、覆盖人数和资金折算口径已经基本闭环"
                if issue_count == 0 and review_count == 0
                else "当前公益模型已经能初步计算，但仍需补齐覆盖或资金口径说明"
            ),
        }

        verdict_meta = _neutral_level(issue_count=issue_count, missing_count=review_count)
        non_green_notes = [c["note"] for c in checks if c["level"] != "green"]
        card["verdict"] = {
            "level": verdict_meta["level"],
            "score": verdict_meta["score"],
            "reason": "；".join(non_green_notes[:4]) if non_green_notes else f"已完成 {len(checks)} 项公益口径自检，暂未发现明显内部矛盾",
        }
        card["framework_explain"] = (
            f"**公益项目口径自检**（{ind}）：\n"
            "本模块优先检查受益对象、可服务边界、首年覆盖、单位受益人成本和折算后的资金口径，"
            "不再强制套用商业项目常见的 CAC / 毛利率 / 付费留存。"
        )
        sugg = []
        for c in checks:
            if c["level"] == "red":
                sugg.append(f"{c['note']}——请先统一统计口径")
            elif c["level"] == "yellow":
                sugg.append(f"{c['note']}——补资金口径或覆盖范围说明即可")
        if not sugg:
            sugg.append("下一步建议把资金来源拆成可持续收入、一次性资助和不确定资金三类")
        card["suggestions"] = sugg
        card["evidence_for_diagnosis"]["H3"] = 0.8 if issue_count == 0 else 0.35
        card["evidence_for_diagnosis"]["H26"] = 0.72 if review_count <= 2 else 0.5
        return card

    if monthly_price < 0:
        _add("monthly_price", "red", "定价不能为负数")
    elif monthly_price == 0:
        _add("monthly_price", "yellow", "尚未填写定价，订阅或交易类收入无法闭环")
    else:
        _add("monthly_price", "green", f"已给出定价口径：¥{monthly_price:.2f}")

    if cac < 0:
        _add("cac", "red", "CAC 不能为负数")
    elif cac == 0:
        _add("cac", "yellow", "尚未填写 CAC，获客回收路径无法验证")
    else:
        _add("cac", "green", f"已给出 CAC 口径：¥{cac:.2f}")

    if retention < 0 or retention > 1:
        _add("monthly_retention", "red", "月留存率需要落在 0-1 之间")
    elif retention == 0:
        _add("monthly_retention", "yellow", "尚未填写月留存率，生命周期难以估计")
    else:
        _add("monthly_retention", "green", f"已给出月留存率：{retention:.1%}")

    if margin < 0 or margin > 1:
        _add("gross_margin", "red", "毛利率需要落在 0-1 之间")
    elif margin == 0:
        _add("gross_margin", "yellow", "尚未填写毛利率，LTV 与回收周期都会受影响")
    else:
        _add("gross_margin", "green", f"已给出毛利率：{margin:.1%}")

    if target_pop > 0 and serviceable_pop > target_pop:
        _add("serviceable_user_population", "red", "SAM 人群不能大于目标总人群 TAM")
    elif serviceable_pop > 0:
        _add("serviceable_user_population", "green", f"已给出可服务人群：{serviceable_pop:,.0f}")

    if target_pop > 0 and reach > target_pop:
        _add("first_year_reach_users", "red", "首年触达人数不能超过目标总人群")
    elif serviceable_pop > 0 and reach > serviceable_pop:
        _add("first_year_reach_users", "yellow", "首年触达人数超过当前 SAM 口径，请确认是“触达”还是“可服务”")
    elif reach > 0:
        _add("first_year_reach_users", "green", f"已给出首年触达人数：{reach:,.0f}")

    if conv < 0 or conv > 1:
        _add("paid_conversion_rate", "red", "付费转化率需要落在 0-1 之间")
    elif conv == 0:
        _add("paid_conversion_rate", "yellow", "尚未填写付费转化率，SOM 无法闭环")
    else:
        _add("paid_conversion_rate", "green", f"已给出付费转化率：{conv:.1%}")

    if reach > 0 and conv > 0 and target_pop > 0 and reach * conv > target_pop:
        _add("som_consistency", "red", "按当前 reach × conversion 推出的首年付费人数已超过目标总人群")
    if arpu_yr < 0:
        _add("annual_arpu", "red", "年 ARPU 不能为负数")
    elif arpu_yr == 0:
        _add("annual_arpu", "yellow", "尚未填写年 ARPU，TAM/SAM/SOM 金额口径无法闭环")
    elif monthly_price > 0 and abs(arpu_yr - monthly_price * 12) > max(monthly_price * 12 * 0.5, 1):
        _add("annual_arpu", "yellow", "年 ARPU 与月价推导结果差异较大，请确认是否包含年付折扣或多档产品")
    else:
        _add("annual_arpu", "green", f"已给出年 ARPU：¥{arpu_yr:,.0f}")

    card["outputs"] = {
        "checks": checks,
        "industry_note": baseline.get("note", ""),
        "analysis_conclusion": (
            "当前商业模型的关键数字已经能互相闭环"
            if issue_count == 0 and review_count == 0
            else "当前模型已经形成基础公式链条，但仍有部分数字口径尚未闭合"
        ),
    }

    if not checks:
        card["verdict"]["reason"] = "还没有可用于自检的数值，先补定价、CAC、留存、毛利中的至少一项"
        card["missing_inputs"] = [
            {"field": "monthly_price", "hint": "月价 / ARPU", "target_tab": "biz"},
            {"field": "cac", "hint": "获客成本", "target_tab": "biz"},
            {"field": "monthly_retention", "hint": "月留存率", "target_tab": "biz"},
            {"field": "gross_margin", "hint": "毛利率", "target_tab": "biz"},
        ]
        return card

    verdict_meta = _neutral_level(issue_count=issue_count, missing_count=review_count)
    non_green_notes = [c["note"] for c in checks if c["level"] != "green"]
    card["verdict"] = {
        "level": verdict_meta["level"],
        "score": verdict_meta["score"],
        "reason": "；".join(non_green_notes[:4]) if non_green_notes else f"已完成 {len(checks)} 项口径自检，暂未发现明显内部矛盾",
    }

    card["framework_explain"] = (
        f"**口径一致性自检**（{ind}）：\n"
        "本模块不回答“这个数高不高”，只检查三类问题：\n"
        "1. 数值是否合法（例如比例是否在 0-1 内）；\n"
        "2. 公式是否能闭环（例如有定价但没有年 ARPU）；\n"
        "3. TAM/SAM/SOM 与收入假设之间是否互相打架。"
    )

    sugg = []
    for c in checks:
        if c["level"] == "red":
            sugg.append(f"{c['note']}——请先统一口径后再讨论优劣")
        elif c["level"] == "yellow":
            sugg.append(f"{c['note']}——补一条来源说明或计算过程即可")
    if not sugg:
        sugg.append("下一步建议把这些假设接入情景分析，验证现金流对单变量变化的敏感度")
    card["suggestions"] = sugg

    card["evidence_for_diagnosis"]["H3"] = 0.8 if issue_count == 0 else 0.35
    card["evidence_for_diagnosis"]["H26"] = 0.72 if review_count <= 2 else 0.5

    return card


# ══════════════════════════════════════════════════════════════════
#  模块 4：TAM / SAM / SOM
# ══════════════════════════════════════════════════════════════════

def estimate_market_size(
    description: str,
    industry: str = "教育",
    hints: dict | None = None,
) -> dict[str, Any]:
    """
    做 TAM/SAM/SOM 三层拆解。
    不再使用 “SAM=TAM/3” 或 “差异 < 3x 才可信” 这类硬编码规则。
    """
    ind = _match_industry(industry)
    card = _empty_card("market_size", "市场规模 TAM/SAM/SOM")
    hints = hints or {}

    pop = _safe_float(hints.get("target_user_population"))
    serviceable_pop = _safe_float(hints.get("serviceable_user_population"))
    serviceable_ratio = _safe_float(hints.get("serviceable_ratio"))
    reach = _safe_float(hints.get("first_year_reach_users"))
    conv = _safe_float(hints.get("paid_conversion_rate"))
    arpu_yr = _safe_float(hints.get("annual_arpu"))
    top_down_tam = _safe_float(hints.get("industry_tam_billions"))
    top_down_sam = _safe_float(hints.get("industry_sam_billions"))

    card["inputs"] = {
        "industry": ind,
        "target_user_population": pop,
        "serviceable_user_population": serviceable_pop,
        "serviceable_ratio": serviceable_ratio,
        "first_year_reach_users": reach,
        "paid_conversion_rate": conv,
        "annual_arpu": arpu_yr,
        "industry_tam_billions": top_down_tam,
        "industry_sam_billions": top_down_sam,
    }

    missing = []
    if pop <= 0:
        missing.append({"field": "target_user_population", "hint": "目标客群总数（如「全国高校大学生 4000 万」）", "target_tab": "biz"})
    if serviceable_pop <= 0 and serviceable_ratio <= 0:
        missing.append({"field": "serviceable_user_population", "hint": "请补“你实际上能服务的那部分人群”或其比例，用来计算 SAM", "target_tab": "biz"})
    if reach <= 0:
        missing.append({"field": "first_year_reach_users", "hint": "首年通过渠道能接触到多少人", "target_tab": "biz"})
    if conv <= 0:
        missing.append({"field": "paid_conversion_rate", "hint": "触达到付费的转化率（0-1）", "target_tab": "biz"})
    if arpu_yr <= 0:
        missing.append({"field": "annual_arpu", "hint": "年客单价", "target_tab": "biz"})
    card["missing_inputs"] = missing

    outputs: dict[str, Any] = {}

    # 自下而上 bottom-up
    if pop > 0 and arpu_yr > 0:
        outputs["bottom_up_tam"] = round(pop * arpu_yr, 2)
    sam_population = 0.0
    if serviceable_pop > 0:
        sam_population = serviceable_pop
    elif pop > 0 and 0 < serviceable_ratio <= 1:
        sam_population = pop * serviceable_ratio
    if sam_population > 0 and arpu_yr > 0:
        outputs["bottom_up_sam"] = round(sam_population * arpu_yr, 2)
        outputs["serviceable_population_used"] = round(sam_population, 2)
    if reach > 0 and conv > 0 and arpu_yr > 0:
        outputs["bottom_up_som_yr1"] = round(reach * conv * arpu_yr, 2)
        outputs["first_year_paid_users"] = round(reach * conv, 2)

    # 自上而下 top-down
    if top_down_tam > 0:
        outputs["top_down_tam"] = top_down_tam * 1e9
    if top_down_sam > 0:
        outputs["top_down_sam"] = top_down_sam * 1e9

    if outputs.get("bottom_up_tam") and outputs.get("top_down_tam"):
        bu = _safe_float(outputs.get("bottom_up_tam"))
        td = _safe_float(outputs.get("top_down_tam"))
        if td > 0:
            outputs["tam_crosscheck_ratio"] = round(bu / td, 2)
    if outputs.get("bottom_up_sam") and outputs.get("bottom_up_tam"):
        outputs["sam_share_of_tam"] = round(_safe_float(outputs.get("bottom_up_sam")) / max(_safe_float(outputs.get("bottom_up_tam")), 1), 4)
    if outputs.get("bottom_up_som_yr1") and outputs.get("bottom_up_sam"):
        outputs["som_share_of_sam_year1"] = round(_safe_float(outputs.get("bottom_up_som_yr1")) / max(_safe_float(outputs.get("bottom_up_sam")), 1), 4)

    computed_layers = sum(
        1 for key in ("bottom_up_tam", "bottom_up_sam", "bottom_up_som_yr1")
        if outputs.get(key) is not None
    )
    verdict_meta = _neutral_level(missing_count=len(missing), computed=computed_layers > 0)
    if computed_layers == 0:
        card["verdict"]["reason"] = "缺少关键人口、转化或 ARPU 数据，暂时无法形成 TAM/SAM/SOM 金额口径"
    else:
        parts = []
        if outputs.get("bottom_up_tam") is not None:
            parts.append(f"TAM≈¥{_safe_float(outputs['bottom_up_tam']):,.0f}")
        if outputs.get("bottom_up_sam") is not None:
            parts.append(f"SAM≈¥{_safe_float(outputs['bottom_up_sam']):,.0f}")
        if outputs.get("bottom_up_som_yr1") is not None:
            parts.append(f"SOM(首年)≈¥{_safe_float(outputs['bottom_up_som_yr1']):,.0f}")
        if outputs.get("tam_crosscheck_ratio") is not None:
            parts.append(f"TAM 双口径比值≈{_safe_float(outputs['tam_crosscheck_ratio']):.2f}")
        card["verdict"] = {
            "level": verdict_meta["level"],
            "score": verdict_meta["score"],
            "reason": "；".join(parts),
        }
    implications = _summarize_market_implications(outputs)
    if implications:
        outputs["analysis_conclusion"] = implications[0]
        outputs["market_implications"] = implications

    # 简单 sanity：懒惰估法识别
    lazy_hint = "1%" in description or "百分之一" in description or "拿到" in description
    if lazy_hint:
        card["suggestions"].append("检测到“拿下 1% 市场”式表述，建议改写成渠道 × 触达 × 转化 × ARPU 的链条")

    card["outputs"] = outputs
    card["framework_explain"] = (
        "**TAM/SAM/SOM 三层市场**：\n"
        "- TAM（Total Addressable Market）理论上全市场总规模\n"
        "- SAM（Serviceable Addressable Market）你产品能覆盖的子市场\n"
        "- SOM（Serviceable Obtainable Market）现实可拿下的份额\n\n"
        "本模块会尽量把三层都算出来，但不会用固定比例替你补 SAM，也不会把双口径差异直接判成“对/错”。"
        "它只负责把你的市场边界拆清楚，并提示还缺哪一个边界假设。"
    )
    card["suggestions"] += [
        "把 TAM、SAM、SOM 分别对应到“总人群 / 可服务人群 / 首年可拿下人群”三层定义",
        "SAM 最好来自明确的地域、品类、渠道或服务能力边界，而不是固定比例",
        "把 TAM/SAM/SOM 三个数字用漏斗图展示，并在旁边写清各层口径",
    ]
    if implications:
        card["suggestions"] += [f"影响判断：{item}" for item in implications[1:3]]

    return card


# ══════════════════════════════════════════════════════════════════
#  模块 5：定价策略框架
# ══════════════════════════════════════════════════════════════════

_PRICING_FRAMEWORKS = [
    {
        "id": "cost_plus",
        "name": "成本加成（Cost-Plus）",
        "when_to_use": "成本结构清晰、毛利预期明确（硬件/生产型、早期试水）",
        "formula": "定价 = 单位成本 × (1 + 目标毛利率)",
        "pros": "简单透明，易向上游沟通",
        "cons": "忽视用户价值感知，可能压低潜在利润",
    },
    {
        "id": "competitor_parity",
        "name": "竞品对比（Competitor Parity）",
        "when_to_use": "已有成熟竞品、差异化不大时做锚定",
        "formula": "定价 = 主竞品 × (1 + 差异化系数 -10%~+30%)",
        "pros": "快速启动，用户有参考",
        "cons": "陷入价格战，难抬高行业上限",
    },
    {
        "id": "value_based",
        "name": "价值基（Value-Based）",
        "when_to_use": "产品能量化帮用户省多少钱 / 多赚多少钱（B2B SaaS、行业软件）",
        "formula": "定价 = 用户可感知价值 × 10%~30% 分成",
        "pros": "天花板最高，能撑高毛利",
        "cons": "需要先做 ROI 访谈 / Case Study 证明价值",
    },
    {
        "id": "van_westendorp",
        "name": "Van Westendorp PSM",
        "when_to_use": "To C 产品首次定价、缺乏历史数据时",
        "formula": "问 4 题：太贵放弃价 / 贵但会买 / 便宜会买 / 太便宜不信价，取交点",
        "pros": "用户主导，结果可直接用",
        "cons": "样本量 ≥ 100 才稳；需要过滤极端回答",
    },
]


def recommend_pricing_framework(
    project_type: str = "",
    stage: str = "idea",
    industry: str = "教育",
) -> dict[str, Any]:
    card = _empty_card("pricing_framework", "定价策略框架推荐")
    ind = _match_industry(industry)

    # 按 industry + stage 推荐
    pick: str
    if ind == "SaaS":
        pick = "value_based" if stage != "idea" else "competitor_parity"
    elif ind == "硬件":
        pick = "cost_plus"
    elif ind == "电商":
        pick = "competitor_parity"
    elif ind == "社会公益":
        pick = "cost_plus"
    else:
        pick = "van_westendorp" if stage == "idea" else "value_based"

    rec = next((f for f in _PRICING_FRAMEWORKS if f["id"] == pick), _PRICING_FRAMEWORKS[0])

    card["inputs"] = {"industry": ind, "stage": stage, "project_type": project_type}
    card["outputs"] = {
        "recommended_id": rec["id"],
        "recommended_name": rec["name"],
        "all_frameworks": _PRICING_FRAMEWORKS,
        "psm_survey_questions": [
            "这个产品在什么价位你会觉得太贵不考虑？",
            "什么价位你觉得贵但会认真考虑下单？",
            "什么价位你觉得便宜划算会马上买？",
            "什么价位你觉得便宜到怀疑它不靠谱？",
        ] if rec["id"] == "van_westendorp" else [],
    }
    card["verdict"] = {"level": "green", "score": 0.7, "reason": f"基于{ind}行业 + {stage} 阶段，推荐用「{rec['name']}」"}
    card["framework_explain"] = (
        f"**{rec['name']}**\n"
        f"- 适用：{rec['when_to_use']}\n"
        f"- 公式：`{rec['formula']}`\n"
        f"- 优点：{rec['pros']}\n"
        f"- 缺点：{rec['cons']}\n\n"
        "其他 3 种框架见下，选择时考虑你的差异化强弱、成本可见度、是否有竞品锚。"
    )
    card["suggestions"] = [
        f"若采纳「{rec['name']}」，下一步执行：" + (
            "做 100 份 PSM 问卷，取 3 条曲线交点作为建议价位区间"
            if rec["id"] == "van_westendorp"
            else "先访谈 5 位目标用户，让他们口述产品每月能帮自己省多少钱 / 多赚多少钱"
            if rec["id"] == "value_based"
            else "梳理单位成本明细表，预设 30%~60% 毛利档测试上下游反应"
            if rec["id"] == "cost_plus"
            else "列出 top 3 竞品价格与用户评论，挑 1 个差异点定 ±10% 的价差"
        ),
        "定价决定后，回来跑一次『单位经济分析』验证 LTV/CAC ≥ 3",
    ]
    card["evidence_for_diagnosis"]["H3"] = 0.6
    return card


# ══════════════════════════════════════════════════════════════════
#  模块 6：融资节奏匹配
# ══════════════════════════════════════════════════════════════════

_FUNDING_STAGES = [
    {
        "id": "preseed",
        "name": "种子轮（Pre-Seed / Seed）",
        "milestone_required": "团队 + 想法 + 市场方向",
        "check_size_cny": [500_000, 3_000_000],
        "dilution_pct": [8, 15],
        "investors": "早期天使、孵化器、校友资助",
    },
    {
        "id": "angel",
        "name": "天使轮",
        "milestone_required": "MVP + 初步验证（数百名种子用户或 DAU）",
        "check_size_cny": [3_000_000, 10_000_000],
        "dilution_pct": [10, 20],
        "investors": "天使投资人、早期机构",
    },
    {
        "id": "seriesA",
        "name": "A 轮",
        "milestone_required": "可重复的获客渠道 + 单位经济为正 + 月度营收规模",
        "check_size_cny": [10_000_000, 50_000_000],
        "dilution_pct": [15, 25],
        "investors": "VC 机构",
    },
    {
        "id": "seriesB",
        "name": "B 轮",
        "milestone_required": "可预测增长曲线 + 市场份额 + 多条产品线",
        "check_size_cny": [50_000_000, 300_000_000],
        "dilution_pct": [15, 25],
        "investors": "VC 中后期基金",
    },
]


def match_funding_stage(
    project_state: dict,
    current_need: dict | None = None,
) -> dict[str, Any]:
    """
    project_state 可含：has_mvp / paying_users / monthly_revenue / team_size / validated_channel / positive_unit_econ
    current_need 可含：ask_amount_cny / target_round_label
    """
    card = _empty_card("funding_stage", "融资节奏匹配")
    has_mvp = bool(project_state.get("has_mvp"))
    paying = _safe_float(project_state.get("paying_users"))
    mrr = _safe_float(project_state.get("monthly_revenue"))
    team = int(_safe_float(project_state.get("team_size")))
    channel_ok = bool(project_state.get("validated_channel"))
    unit_econ_ok = bool(project_state.get("positive_unit_econ"))

    current_need = current_need or {}
    ask = _safe_float(current_need.get("ask_amount_cny"))
    claimed_round = str(current_need.get("target_round_label", "")).lower()

    # 推导当前业务阶段应对应哪一轮
    if unit_econ_ok and mrr >= 100_000 and channel_ok:
        recommended = "seriesA"
    elif has_mvp and paying >= 200:
        recommended = "angel"
    else:
        recommended = "preseed"

    rec = next((f for f in _FUNDING_STAGES if f["id"] == recommended), _FUNDING_STAGES[0])
    card["inputs"] = {
        "has_mvp": has_mvp,
        "paying_users": paying,
        "monthly_revenue": mrr,
        "team_size": team,
        "validated_channel": channel_ok,
        "positive_unit_econ": unit_econ_ok,
        "ask_amount_cny": ask,
        "target_round_label": claimed_round,
    }

    size_lo, size_hi = rec["check_size_cny"]
    card["outputs"] = {
        "recommended_round_id": rec["id"],
        "recommended_round_name": rec["name"],
        "check_size_range_cny": [size_lo, size_hi],
        "dilution_range_pct": rec["dilution_pct"],
        "milestone_required": rec["milestone_required"],
        "typical_investors": rec["investors"],
        "all_stages": _FUNDING_STAGES,
    }

    # 匹配度评估
    mismatch_msg = ""
    if claimed_round:
        claim_rec = next((f for f in _FUNDING_STAGES if f["id"] in claimed_round or claimed_round in f["name"].lower()), None)
        if claim_rec and claim_rec["id"] != rec["id"]:
            order = {f["id"]: i for i, f in enumerate(_FUNDING_STAGES)}
            if order[claim_rec["id"]] > order[rec["id"]]:
                mismatch_msg = f"你打算谈「{claim_rec['name']}」，但业务里程碑更匹配「{rec['name']}」——投资人会追问"
                card["verdict"] = {"level": "red", "score": 0.25, "reason": mismatch_msg}
                card["evidence_for_diagnosis"]["H24"] = 0.25
            else:
                mismatch_msg = f"你说的「{claim_rec['name']}」其实偏早，可直接走「{rec['name']}」"
                card["verdict"] = {"level": "yellow", "score": 0.55, "reason": mismatch_msg}

    if ask > 0:
        if size_lo <= ask <= size_hi:
            if not mismatch_msg:
                card["verdict"] = {"level": "green", "score": 0.85, "reason": f"金额 ¥{ask:.0f} 在 {rec['name']} 常见区间内"}
                card["evidence_for_diagnosis"]["H24"] = 0.8
        elif ask > size_hi * 1.5:
            card["verdict"] = {"level": "red", "score": 0.3, "reason": f"¥{ask:.0f} 高于 {rec['name']} 区间上限 ¥{size_hi:.0f}，除非有里程碑支撑否则难过会"}
            card["evidence_for_diagnosis"]["H24"] = 0.3
        elif ask < size_lo * 0.3:
            card["verdict"] = {"level": "yellow", "score": 0.6, "reason": f"¥{ask:.0f} 低于 {rec['name']} 下限，可能不值得走机构融资，建议走补助/赛事奖金"}

    if card["verdict"]["level"] == "gray":
        card["verdict"] = {
            "level": "yellow",
            "score": 0.6,
            "reason": f"根据业务里程碑，建议走「{rec['name']}」（支票 ¥{size_lo:.0f}-¥{size_hi:.0f}，稀释 {rec['dilution_pct'][0]}%-{rec['dilution_pct'][1]}%）",
        }
        card["evidence_for_diagnosis"]["H24"] = 0.55

    card["framework_explain"] = (
        "**融资节奏与业务里程碑**：机构融资看的不是商业计划书文采，而是三件事：\n"
        "- **种子轮**：团队 + 方向，PPT 融资\n"
        "- **天使轮**：MVP + 百级付费用户 / DAU，证「有人要」\n"
        "- **A 轮**：可重复获客 + 单位经济正 + 月度营收，证「能复制」\n"
        "- **B 轮起**：增长曲线可预测 + 多产品线，证「能规模化」\n\n"
        "错轮次融资的风险：要么被压价稀释过大，要么 DD 失败浪费 3 个月。"
    )
    card["suggestions"] = [
        f"如当前业务在{rec['name']}区间，找「{rec['investors']}」类型的投资人",
        "准备一份 3 页 Teaser：问题-方案-牵引力（Traction 数据）",
        "把里程碑拆成「已完成 / 进行中 / 本轮资金用途」三列，对应里程碑投资逻辑",
    ]
    return card


# ══════════════════════════════════════════════════════════════════
#  数据源合并：从 BudgetPanel snapshot + conversation hints 里抽 assumptions
# ══════════════════════════════════════════════════════════════════

_FLAT_BUDGET_KEYS = (
    "monthly_price", "cac", "gross_margin", "monthly_retention",
    "fixed_costs_monthly", "variable_cost_per_user", "growth_rate_monthly",
    "new_users_per_month", "initial_capital", "cost_per_beneficiary",
    "paid_conversion_rate", "target_user_population", "serviceable_user_population",
    "first_year_reach_users", "annual_arpu", "industry_tam_billions", "industry_sam_billions",
)


def extract_assumptions_from_budget(budget: dict | None) -> dict[str, Any]:
    """把 data/budgets/{user}/{plan}.json 里的 business_finance 拍成 assumptions。

    兼容两种输入：
    1) 嵌套的 budget_storage 快照（含 business_finance / summary）
    2) 扁平 dict（{monthly_price: 39, cac: 800, ...}），直接透传已知字段

    返回结构（pattern 化升级版本，向后兼容）:
      flat_keys: 老的 SaaS 心智 flat 字段（_FLAT_BUDGET_KEYS）
      by_stream: [{name, pattern_key, pattern_label, kind, inputs, monthly_revenue}, ...]
      dominant_pattern / dominant_kind / pattern_mix / kind_mix / is_public:
        来自 finance_pattern_formulas.detect_pattern_kind_mix
    """
    if not budget:
        return {}

    # 1) 扁平 dict 兼容：当顶层就有已知 flat key 时，认为是手工/API 传入的简化 snapshot
    if any(k in budget for k in _FLAT_BUDGET_KEYS):
        flat_out: dict[str, Any] = {}
        for k in _FLAT_BUDGET_KEYS:
            v = _safe_float(budget.get(k))
            if v:
                flat_out[k] = v
        # 保底 initial_capital，防止后续现金流模块取 0
        if "initial_capital" not in flat_out:
            flat_out["initial_capital"] = 50_000
        return flat_out

    # 延迟 import，避免循环依赖
    from app.services.revenue_models import normalize_stream, compute_stream_monthly_revenue, PATTERNS
    from app.services.finance_pattern_formulas import PATTERN_KIND, detect_pattern_kind_mix

    biz = (budget or {}).get("business_finance") or {}
    streams = biz.get("revenue_streams") or []

    out: dict[str, Any] = {}

    # 2) 扁平兜底字段（业务支出/增长率等公共维度）
    out["fixed_costs_monthly"] = _safe_float(biz.get("fixed_costs_monthly"))
    out["variable_cost_per_user"] = _safe_float(biz.get("variable_cost_per_user"))
    out["growth_rate_monthly"] = _safe_float(biz.get("growth_rate_monthly"))
    out["monthly_price"] = _safe_float(biz.get("monthly_price"))
    out["cac"] = _safe_float(biz.get("cac"))
    out["gross_margin"] = _safe_float(biz.get("gross_margin"))
    out["monthly_retention"] = _safe_float(biz.get("monthly_retention"))
    out["new_users_per_month"] = _safe_float(biz.get("new_users_per_month"))
    out["initial_capital"] = _safe_float(biz.get("initial_capital"))
    out["cost_per_beneficiary"] = _safe_float(biz.get("cost_per_beneficiary"))
    out["paid_conversion_rate"] = _safe_float(biz.get("paid_conversion_rate"))
    out["target_user_population"] = _safe_float(biz.get("target_user_population"))
    out["serviceable_user_population"] = _safe_float(biz.get("serviceable_user_population"))
    out["first_year_reach_users"] = _safe_float(biz.get("first_year_reach_users"))
    out["annual_arpu"] = _safe_float(biz.get("annual_arpu"))
    out["industry_tam_billions"] = _safe_float(biz.get("industry_tam_billions"))
    out["industry_sam_billions"] = _safe_float(biz.get("industry_sam_billions"))

    # 3) by_stream：每条流都把 inputs 完整保留，并附带 pattern 元信息
    by_stream: list[dict[str, Any]] = []
    for s in streams:
        if not isinstance(s, dict):
            continue
        s_norm = normalize_stream(dict(s))
        pkey = s_norm.get("pattern_key") or "subscription"
        inputs = s_norm.get("inputs") or {}
        rev = _safe_float(s.get("monthly_revenue"))
        if rev <= 0:
            try:
                rev, _ = compute_stream_monthly_revenue(s_norm)
            except Exception:
                rev = 0.0
        meta = PATTERNS.get(pkey)
        by_stream.append({
            "name": s.get("name") or (meta.label if meta else pkey),
            "pattern_key": pkey,
            "pattern_label": meta.label if meta else pkey,
            "kind": PATTERN_KIND.get(pkey, "growth"),
            "inputs": dict(inputs),
            "monthly_revenue": round(max(0.0, rev), 2),
            "ai_meta": s.get("_ai_meta") or {},  # 透传 AI 自动回写元数据
        })
    out["by_stream"] = by_stream

    # 4) 大类汇总（dominant_pattern / kind_mix / is_public）
    mix = detect_pattern_kind_mix(by_stream)
    out.update(mix)

    # 5) 旧字段映射（保持向后兼容；优先取 dominant pattern 的 inputs）
    # 选第一条收入流的输入作为 fallback；dominant_pattern 不一定在 by_stream[0]
    primary_stream = None
    if mix.get("dominant_pattern"):
        primary_stream = next(
            (b for b in by_stream if b["pattern_key"] == mix["dominant_pattern"]),
            by_stream[0] if by_stream else None,
        )
    elif by_stream:
        primary_stream = by_stream[0]

    if primary_stream:
        pi = primary_stream.get("inputs") or {}
        # 把每个 pattern 的"价格 / 用户数 / 转化率"等同义字段映射到老 flat key
        if primary_stream["pattern_key"] == "subscription":
            price = _safe_float(pi.get("price"))
            users = _safe_float(pi.get("monthly_users"))
            conv = _safe_float(pi.get("conversion_rate"))
            if price > 0:
                out["monthly_price"] = price
            if users > 0 and conv > 0:
                out["new_users_per_month"] = users * conv
            elif users > 0:
                out["new_users_per_month"] = users
            if conv > 0:
                out["paid_conversion_rate"] = conv
        elif primary_stream["pattern_key"] == "transaction":
            aov = _safe_float(pi.get("avg_order_value"))
            if aov > 0:
                out["monthly_price"] = aov  # 把客单价映射到月价口径
            buyers = _safe_float(pi.get("monthly_buyers"))
            if buyers > 0:
                out["new_users_per_month"] = buyers
        elif primary_stream["pattern_key"] == "project_b2b":
            cv = _safe_float(pi.get("contract_value"))
            cd = _safe_float(pi.get("contract_duration_months"), 6)
            cpm = _safe_float(pi.get("contracts_per_month"))
            if cv > 0 and cd > 0:
                out["monthly_price"] = cv / max(cd, 1.0)
            if cpm > 0:
                out["new_users_per_month"] = cpm * cd
        elif primary_stream["pattern_key"] == "platform_commission":
            gmv = _safe_float(pi.get("monthly_gmv"))
            rate = _safe_float(pi.get("commission_rate"))
            if gmv > 0 and rate > 0:
                out["monthly_price"] = gmv * rate / max(_safe_float(pi.get("active_sellers"), 1.0), 1.0)
            sellers = _safe_float(pi.get("active_sellers"))
            if sellers > 0:
                out["new_users_per_month"] = sellers
        elif primary_stream["pattern_key"] == "hardware_sales":
            up = _safe_float(pi.get("unit_price"))
            if up > 0:
                out["monthly_price"] = up
            mu = _safe_float(pi.get("monthly_units"))
            if mu > 0:
                out["new_users_per_month"] = mu
        elif primary_stream["pattern_key"] == "grant_funded":
            bens = _safe_float(pi.get("beneficiaries_served"))
            if bens > 0:
                out["new_users_per_month"] = bens
            yearly = _safe_float(pi.get("grant_value_yearly"))
            grants = _safe_float(pi.get("active_grants"))
            if yearly > 0 and grants > 0 and bens > 0:
                # 单受益人月成本 = 月收入 / 月受益人数（缺 cost_per_beneficiary 时的兜底估算）
                monthly_revenue = grants * yearly / 12
                out["cost_per_beneficiary"] = monthly_revenue / bens
        elif primary_stream["pattern_key"] == "donation":
            donors = _safe_float(pi.get("monthly_donors"))
            avg = _safe_float(pi.get("avg_donation"))
            if donors > 0:
                out["new_users_per_month"] = donors
            if avg > 0:
                out["monthly_price"] = avg

    # initial capital: 取 summary.total_investment 做默认
    summary = budget.get("summary") or {}
    out["initial_capital"] = _safe_float(summary.get("total_investment")) or 50_000

    return out


__all__ = [
    "INDUSTRY_BASELINES",
    "analyze_unit_economics",
    "project_cash_flow",
    "evaluate_rationality",
    "estimate_market_size",
    "recommend_pricing_framework",
    "match_funding_stage",
    "extract_assumptions_from_budget",
    "_match_industry",
]
