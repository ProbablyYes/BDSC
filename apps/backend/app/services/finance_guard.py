"""
finance_guard — 对话旁路财务守望钩子

学生每次发消息后，后台自动扫是否涉及定价/商业模式/市场/融资；
若涉及且能抽出关键假设，立即跑 finance_analyst 的 3 个快模块做合理性
速判，有红/黄线才产出「财务提醒卡片」挂到本轮 agent_trace。

设计：
- 全流程 < 500ms：关键词正则 + 简单 slot 抽取 + 纯计算模块
- 不调 LLM（分析深度由 finance_report 负责），降低延迟 + 失败风险
- 全绿不打扰
- 失败静默（guard 自己异常不阻塞主 chat 链路）
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.services.finance_analyst import (
    _match_industry,
    analyze_unit_economics,
    evaluate_rationality,
    extract_assumptions_from_budget,
    recommend_pricing_framework,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
#  触发关键词
# ══════════════════════════════════════════════════════════════════

_FINANCE_TRIGGERS: dict[str, list[str]] = {
    "pricing": [
        "定价", "收费", "价格", "月费", "年费", "订阅", "月付", "年付",
        "免费", "付费", "多少钱", "收多少", "卖多少", "售价",
    ],
    "unit_econ": [
        "CAC", "cac", "LTV", "ltv", "获客成本", "付费率",
        "转化率", "复购", "留存", "ARPU", "arpu", "毛利",
    ],
    "market": [
        "市场规模", "TAM", "SAM", "SOM", "tam", "sam", "som",
        "市场份额", "可触达", "潜在用户", "行业空间",
    ],
    "cashflow": [
        "烧钱", "现金流", "回本", "盈亏平衡", "Runway", "runway",
        "跑道", "净利润", "盈利", "月支出",
    ],
    "funding": [
        "融资", "天使轮", "A轮", "a轮", "种子轮", "投资人", "估值",
        "稀释", "pre-A", "preA",
    ],
    "cost": [
        "固定成本", "变动成本", "边际成本", "服务器成本", "运营成本",
    ],
    "nonprofit": [
        "公益", "慈善", "非营利", "志愿", "受益人", "服务对象",
        "帮扶", "留守", "独居", "社工", "捐赠", "募捐", "支教",
        # 放宽: 加入更多公益/社会创新口径词汇
        "受助", "资助", "帮助", "弱势群体", "社区服务", "社会创新", "可持续",
        "乡村振兴", "环保", "环境保护", "残障", "残疾人", "失能老人",
        "困境儿童", "公益组织", "NGO", "ngo", "基金会", "社会企业", "社创",
        "csr", "CSR", "义卖", "义诊", "义教", "公益传播", "倡导", "公共服务",
    ],
}

# 强信号定价模式：符合即一票通过，数字一定是月价 / 产品单价
_PRICE_STRONG_PATTERNS = [
    re.compile(r"¥\s*(\d{1,6}(?:\.\d{1,2})?)"),
    re.compile(r"(\d{1,6}(?:\.\d{1,2})?)\s*(?:元|块|rmb|人民币|cny)\s*/\s*(?:月|年)", re.IGNORECASE),
    re.compile(r"(\d{1,6}(?:\.\d{1,2})?)\s*/\s*(?:月|年)"),
    re.compile(r"月(?:价|付|费|收|租|卡)\s*[:：]?\s*[^\d]{0,4}(\d{1,6})"),
    re.compile(r"年(?:价|付|费|卡)\s*[:：]?\s*[^\d]{0,4}(\d{1,6})"),
    re.compile(r"(?:定价|售价|收费|标价|订阅\s*费?|会员\s*费?|课\s*价)\s*[:：]?\s*[^\d]{0,4}(\d{1,6})"),
]

# 弱信号定价模式（"X 元 / X 块"）：只在正向定价语境下才采纳，且避开 CAC/成本
_PRICE_WEAK_PATTERNS = [
    re.compile(r"(\d{1,6}(?:\.\d{1,2})?)\s*(?:元|块|rmb|人民币|cny)", re.IGNORECASE),
]

# 弱信号匹配时要求附近出现的"正向词"：说明学生在讨论定价而不是成本
_PRICE_WEAK_POSITIVE = [
    "定价", "售价", "收费", "订阅", "会员", "月费", "年费", "收", "卖",
    "客单价", "arpu", "price", "月付", "年付", "月卡", "年卡",
]

# 弱信号匹配时要求附近不出现的"负向词"：表明数字是成本 / 获客开销
_PRICE_WEAK_NEGATIVE = [
    "cac", "获客", "成本", "花费", "投入", "服务器", "运营", "推广",
    "投流", "广告", "采购", "供应商", "工资", "薪资", "物流", "房租",
    "押金", "补贴", "违约", "罚款", "亏损",
]

# 转化率模式：5% / 百分之五 / 0.05
_PERCENT_PATTERN = re.compile(r"(\d{1,3}(?:\.\d{1,2})?)\s*%")


# ══════════════════════════════════════════════════════════════════
#  触发检测
# ══════════════════════════════════════════════════════════════════

def detect_triggers(text: str) -> list[str]:
    """返回命中的分类标签 list。"""
    text_lower = (text or "").lower()
    hits: list[str] = []
    for tag, keywords in _FINANCE_TRIGGERS.items():
        if any(kw.lower() in text_lower for kw in keywords):
            hits.append(tag)
    # 强信号定价（只有这类一票触发）
    if "pricing" not in hits and any(p.search(text or "") for p in _PRICE_STRONG_PATTERNS):
        hits.append("pricing")
    # 弱信号定价：需要出现正向词才算（避免"成本 500 元"被误触发）
    if "pricing" not in hits:
        lower_all = (text or "").lower()
        if any(pos in lower_all for pos in _PRICE_WEAK_POSITIVE) and any(
            p.search(text or "") for p in _PRICE_WEAK_PATTERNS
        ):
            hits.append("pricing")
    return hits


# ══════════════════════════════════════════════════════════════════
#  轻量 slot fill（无 LLM 版本：正则 + 历史合并）
# ══════════════════════════════════════════════════════════════════

def _extract_price_from_text(text: str) -> float:
    """抽取月价 / 产品单价。强信号一票通过，弱信号要求正向词 + 排除负向词。"""
    if not text:
        return 0.0
    # 1) 强信号：直接返回第一个命中
    for pat in _PRICE_STRONG_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                return float(m.group(1))
            except (TypeError, ValueError):
                continue

    # 2) 弱信号（"X 元"）：需要正向词命中且不在负向上下文中
    lower = text.lower()
    for pat in _PRICE_WEAK_PATTERNS:
        for m in pat.finditer(text):
            # 以该数字为中心取 ±12 字符窗口
            start = max(0, m.start() - 12)
            end = min(len(text), m.end() + 12)
            window = lower[start:end]
            # 在 ±30 字符的更大窗口里才看是否有正向定价词
            big_start = max(0, m.start() - 30)
            big_end = min(len(text), m.end() + 30)
            big_window = lower[big_start:big_end]
            if any(neg in window for neg in _PRICE_WEAK_NEGATIVE):
                continue  # 附近是 CAC/成本 → 跳过
            if not any(pos in big_window for pos in _PRICE_WEAK_POSITIVE):
                continue  # 没有定价语境 → 不信
            try:
                return float(m.group(1))
            except (TypeError, ValueError):
                continue
    return 0.0


_PCT_BOUNDARY_RE = re.compile(r"[，,。；;！!？?\n]")


def _extract_percent_from_text(text: str, near_keywords: list[str]) -> float:
    """在每个 % 之前 15 字符的窗口里找关键词。

    原则：
    1) 中文习惯，关键词永远在数字**之前**（``毛利 75%``、``留存 70%``），不向后看
    2) 窗口在遇到前一个 % / 标点（逗号/句号/分号等）时截断，避免串味
    3) 无关键词命中则不返回（避免把一个裸 3% 塞进多字段）
    """
    if not text:
        return 0.0
    lower = text.lower()
    matches = list(_PERCENT_PATTERN.finditer(text))
    if not matches:
        return 0.0
    for i, m in enumerate(matches):
        # 前窗口边界：不跨越前一个 %，也不跨越最近的标点
        prev_end = matches[i - 1].end() if i > 0 else 0
        raw_start = max(prev_end, m.start() - 15)
        # 从 raw_start 到 m.start() 之间若有标点，再往后收窄
        window_pre = lower[raw_start: m.start()]
        boundary_match = None
        for bm in _PCT_BOUNDARY_RE.finditer(window_pre):
            boundary_match = bm  # 取最后一个
        if boundary_match is not None:
            start = raw_start + boundary_match.end()
        else:
            start = raw_start
        window = lower[start: m.start()]
        if any(kw.lower() in window for kw in near_keywords):
            try:
                v = float(m.group(1))
                return v / 100 if v > 1 else v
            except (TypeError, ValueError):
                continue
    return 0.0


def _extract_number_near(text: str, keywords: list[str]) -> float:
    """在关键词附近抓一个纯数字（含 10k/万这种单位）。"""
    if not text:
        return 0.0
    def _parse(window: str) -> float:
        m = re.search(r"(\d{1,8}(?:\.\d{1,3})?)\s*(万|千|k|m)?", window, re.IGNORECASE)
        if not m:
            return 0.0
        try:
            v = float(m.group(1))
            unit = (m.group(2) or "").lower()
            if unit == "万":
                v *= 1e4
            elif unit in ("千", "k"):
                v *= 1e3
            elif unit == "m":
                v *= 1e6
            return v
        except (TypeError, ValueError):
            return 0.0
    for kw in keywords:
        idx = text.find(kw)
        if idx < 0:
            continue
        after = text[idx + len(kw): idx + len(kw) + 24]
        v = _parse(after)
        if v > 0:
            return v
        window = text[max(0, idx - 5): idx + len(kw) + 20]
        v = _parse(window)
        if v > 0:
            return v
    return 0.0


def slot_fill_from_text(text: str, history: list[dict] | None = None) -> dict[str, Any]:
    """用正则 + 历史拼一个 assumptions 字典。失败返回 {}。"""
    merged = ""
    if text:
        merged += text + "\n"
    if history:
        # 只看最近 6 轮学生发言，避免上下文污染
        recent_user = [m for m in history[-12:] if isinstance(m, dict) and m.get("role") == "user"]
        for m in recent_user[-6:]:
            c = m.get("content", "")
            if isinstance(c, str):
                merged += c + "\n"

    out: dict[str, Any] = {}

    # price
    p = _extract_price_from_text(text) or _extract_price_from_text(merged)
    if p > 0:
        out["monthly_price"] = p

    # conversion / retention
    conv = _extract_percent_from_text(merged, ["转化", "付费", "conversion"])
    if conv > 0:
        out["paid_conversion_rate"] = conv
    retention = _extract_percent_from_text(merged, ["留存", "retention", "续费"])
    if retention > 0:
        out["monthly_retention"] = retention
    margin = _extract_percent_from_text(merged, ["毛利", "margin"])
    if margin > 0:
        out["gross_margin"] = margin

    # cac
    cac = _extract_number_near(merged, ["CAC", "cac", "获客成本"])
    if cac > 0:
        out["cac"] = cac

    # users
    target_population = _extract_number_near(
        merged,
        ["目标总人群", "总人群", "目标市场", "目标客户", "客户总量", "企业客户", "用户", "付费用户", "DAU", "MAU"],
    )
    if target_population > 0:
        out["target_user_population"] = target_population
    monthly_active = _extract_number_near(merged, ["月活用户", "活跃用户", "月活", "MAU", "DAU"])
    if monthly_active > 0 and "paid_conversion_rate" in out and "new_users_per_month" not in out:
        out["new_users_per_month"] = monthly_active * out["paid_conversion_rate"]
    explicit_new_users = _extract_number_near(merged, ["每月新增付费客户", "每月新增客户", "月新增付费客户", "月新增客户", "每月新增"])
    if explicit_new_users > 0:
        out["new_users_per_month"] = explicit_new_users
    serviceable_users = _extract_number_near(merged, ["可服务", "可覆盖", "能覆盖", "可触达用户池", "服务人群", "真正能服务"])
    if serviceable_users > 0:
        out["serviceable_user_population"] = serviceable_users
    first_year_reach = _extract_number_near(merged, ["首年预计能触达", "首年触达", "第一年触达", "首年覆盖", "第一年覆盖", "首年可达", "首年"])
    if first_year_reach > 0:
        out["first_year_reach_users"] = first_year_reach

    # ARPU / annual
    arpu_yr = _extract_number_near(merged, ["年 ARPU", "年 arpu", "annual arpu", "年客单价", "年付"])
    if arpu_yr > 0:
        out["annual_arpu"] = arpu_yr
    elif "monthly_price" in out:
        out["annual_arpu"] = out["monthly_price"] * 12

    fixed_costs = _extract_number_near(merged, ["月固定成本", "固定成本", "每月固定支出"])
    if fixed_costs > 0:
        out["fixed_costs_monthly"] = fixed_costs
    initial_capital = _extract_number_near(merged, ["启动资金", "起始资金", "初始资金", "账上现金"])
    if initial_capital > 0:
        out["initial_capital"] = initial_capital

    # 公益：单位受益人成本（"每服务一个 X 的成本是 Y 元"、"人均成本 Y 元"）
    cpb = _extract_number_near(
        merged,
        ["每服务一个", "每帮助一个", "每个受益人", "受益人成本", "人均成本", "人均费用",
         "每名学生", "每个孩子", "每户"],
    )
    if cpb > 0:
        out["cost_per_beneficiary"] = cpb

    return out


# ══════════════════════════════════════════════════════════════════
#  主入口 scan_message
# ══════════════════════════════════════════════════════════════════

def scan_message(
    text: str,
    history: list[dict] | None = None,
    budget_snapshot: dict | None = None,
    user_id: str = "",
    industry_hint: str = "",
) -> dict[str, Any]:
    """
    返回结构:
      {
        "triggered": bool,
        "hits": ["pricing", ...],      # 命中的分类
        "cards": [...],                 # 财务提醒卡片（仅非绿色才放）
        "evidence_for_diagnosis": {...},
        "industry": str,
      }
    失败时静默返回 {"triggered": False}.
    """
    try:
        if not text or not isinstance(text, str):
            return {"triggered": False}

        hits = detect_triggers(text)
        if not hits:
            return {"triggered": False}

        # 命中 nonprofit 关键词时：文本已经明确是公益项目，覆盖前端传的 industry_hint
        # 放宽公益识别: 即使没命中 nonprofit, 但 history 里曾命中过公益词且本轮没有商业反向词, 仍切公益
        is_public_hint = "nonprofit" in hits
        if not is_public_hint and history:
            recent_text = " ".join(
                str((m or {}).get("content", ""))
                for m in (history[-12:] or []) if isinstance(m, dict)
            )
            recent_lower = recent_text.lower()
            public_kw_hits = sum(1 for kw in _FINANCE_TRIGGERS["nonprofit"] if kw.lower() in recent_lower)
            biz_strong = ["盈利", "估值", "上市", "融资", "ipo", "退出", "收入翻番", "市值"]
            biz_hits = sum(1 for kw in biz_strong if kw in recent_lower)
            if public_kw_hits >= 2 and biz_hits == 0:
                is_public_hint = True
        if is_public_hint:
            industry = "社会公益"
        else:
            industry = _match_industry(industry_hint or "")

        # 合并三路 assumptions：text/history > budget（创新阶段对话信号最权威，预算仅兜底）
        text_slots = slot_fill_from_text(text, history=history)
        budget_slots = extract_assumptions_from_budget(budget_snapshot or {})
        # 先放 budget 垫底，再用 text 里的非空字段覆盖同名项
        assumptions: dict[str, Any] = {
            **{k: v for k, v in budget_slots.items() if v},
            **{k: v for k, v in text_slots.items() if v},
        }

        cards: list[dict] = []

        # 按 hits 分派
        ran_ue = False
        should_run_ue = (
            "pricing" in hits or "unit_econ" in hits or "cashflow" in hits
            or ("nonprofit" in hits and assumptions.get("cost_per_beneficiary"))
        )
        if should_run_ue:
            ue = analyze_unit_economics(assumptions, industry=industry)
            ran_ue = True
            if ue.get("verdict", {}).get("level") in ("red", "yellow"):
                cards.append(ue)
        if "pricing" in hits:
            # 推荐定价框架（总是产出绿灯）— 但当已触发红色单位经济时补一条
            if any(c.get("verdict", {}).get("level") == "red" for c in cards):
                pf = recommend_pricing_framework(
                    project_type=industry,
                    stage="idea",
                    industry=industry,
                )
                cards.append(pf)
        if hits and ran_ue:
            rat = evaluate_rationality(assumptions, industry=industry)
            if rat.get("verdict", {}).get("level") in ("red", "yellow"):
                cards.append(rat)

        # 合并证据
        merged_evidence: dict[str, float] = {}
        for c in cards:
            for k, v in (c.get("evidence_for_diagnosis") or {}).items():
                merged_evidence[k] = max(merged_evidence.get(k, 0.0), float(v))

        if not cards:
            return {"triggered": False, "hits": hits}

        return {
            "triggered": True,
            "hits": hits,
            "cards": cards,
            "evidence_for_diagnosis": merged_evidence,
            "industry": industry,
        }
    except Exception as exc:
        logger.warning("finance_guard.scan_message failed silently: %s", exc)
        return {"triggered": False}


__all__ = ["detect_triggers", "slot_fill_from_text", "scan_message"]
