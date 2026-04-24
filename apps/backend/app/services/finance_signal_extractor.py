"""
finance_signal_extractor — 把"对话里的财务信号"映射到具体 RevenuePattern 的 inputs

为什么需要它？
- finance_guard.slot_fill_from_text 只抽出"扁平 SaaS 字段"(monthly_price, cac, conv...)
- 但用户说的可能是 B2B 合同金额 / 平台 GMV / 公益单个项目 / 月销量等等
- 这里把抽到的扁平信号按"项目当前 dominant pattern"或显式 pattern_key
  映射到具体 stream 的 inputs, 同时返回:
    1) 推断的 pattern (如"客单价 200 元/单 + 月购买 500 人"→ transaction)
    2) 推断的字段 + 数值 + 置信度
    3) 与 reasonable_ranges 对比, 给出"是否在合理区间"的提示
    4) 用于 UI 展示的"已识别字段"列表

主要入口:
- extract_finance_signals(text, history): 返回 SignalBundle
- apply_signals_to_budget(user_id, plan_id, signals, source_message_id):
  把 SignalBundle 按 pattern 写到 budget 对应 stream 的 inputs, 标 _ai_meta
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from app.services.budget_storage import BudgetStorage
from app.services.finance_guard import slot_fill_from_text, detect_triggers
from app.services.finance_pattern_formulas import (
    REASONABLE_RANGES, PATTERN_KIND, get_field_range,
)
from app.services.revenue_models import PATTERNS, normalize_stream

logger = logging.getLogger(__name__)

_BIZ_FLAT_FIELDS = {
    "monthly_price",
    "cac",
    "gross_margin",
    "monthly_retention",
    "fixed_costs_monthly",
    "variable_cost_per_user",
    "growth_rate_monthly",
    "new_users_per_month",
    "initial_capital",
    "cost_per_beneficiary",
    "paid_conversion_rate",
    "target_user_population",
    "serviceable_user_population",
    "first_year_reach_users",
    "annual_arpu",
    "industry_tam_billions",
    "industry_sam_billions",
}


# ══════════════════════════════════════════════════════════════════
#  信号 → pattern 推断
# ══════════════════════════════════════════════════════════════════
#
# 给定一段文本里抽到的字段, 倒推它最可能属于哪个 pattern。
# 一段对话可能同时引出多个 pattern (e.g. "我们卖硬件 1000 元/件, 同时做月度服务订阅 49/月")。

_PATTERN_KEYWORDS: dict[str, list[str]] = {
    "subscription":        ["订阅", "月费", "年费", "会员", "包月", "包年", "saas", "月活", "MAU", "DAU", "付费用户"],
    "transaction":         ["客单价", "客单", "件单价", "复购", "购买", "下单", "电商", "外卖", "餐饮"],
    "project_b2b":         ["合同", "项目制", "中标", "采购", "招标", "to b", "tob", "企业客户", "学校采购", "政府"],
    "platform_commission": ["平台", "撮合", "佣金", "抽成", "take rate", "GMV", "gmv", "成交额", "卖家", "供给方"],
    "hardware_sales":      ["硬件", "设备", "出厂", "BOM", "bom", "出货", "库存", "良率"],
    "grant_funded":        ["资助", "基金会", "政府购买", "支教", "公益项目", "受益人", "服务对象", "civicus"],
    "donation":            ["捐赠", "募捐", "众筹", "csr", "CSR", "赞助", "义卖"],
}

# 字段同义词 → 标准 input field
_FIELD_SYNONYMS: dict[str, list[tuple[str, str]]] = {
    "subscription": [
        ("price",            r"(?:月费|月价|月卡|订阅\s*费|会员\s*费|saas\s*费)\s*[:：]?\s*[¥]?\s*([\d.]+)\s*(?:元|块)?\s*/?\s*(?:月)?"),
        ("price",            r"(?:每月)\s*[¥]?\s*([\d.]+)\s*(?:元|块)"),
        # 月活用户 / MAU / DAU 后允许跟"用户/人"等中文词, 再到数字
        ("monthly_users",    r"(?:月活(?:用户|人数)?|MAU|DAU|月活跃(?:用户|人数)?|月度活跃|月用户(?:数|量)?|目标月活)\s*(?:用户|人数)?\s*[:：]?\s*约?\s*([\d,.]+)\s*(?:万|千|w|人)?"),
        ("conversion_rate",  r"(?:付费率|付费转化率?|付费转化|转化率)\s*(?:大概|约|大约)?\s*[:：]?\s*([\d.]+)\s*%?"),
    ],
    "transaction": [
        ("avg_order_value",  r"(?:客单价|件单价|单价)\s*[:：]?\s*[¥]?\s*([\d.]+)\s*(?:元|块)?"),
        ("monthly_buyers",   r"(?:月(?:活)?(?:购买|订单|买家)|月下单人数)\s*[:：]?\s*约?\s*([\d,.]+)\s*(?:万|千|w)?"),
        ("orders_per_buyer", r"(?:复购|月订单|人均订单)\s*[:：]?\s*([\d.]+)\s*单?"),
    ],
    "project_b2b": [
        ("contract_value",          r"(?:单(?:个)?合同|合同(?:金?额)|项目(?:金额|金))\s*[:：]?\s*约?\s*[¥]?\s*([\d.]+)\s*(万|千|k|w|m)?"),
        ("contracts_per_month",     r"(?:月(?:新签|签单|签约|拿单)|每月.*?合同)\s*[:：]?\s*约?\s*([\d.]+)\s*(?:个|份)?"),
        ("contract_duration_months", r"(?:服务周期|项目周期|合同周期)\s*[:：]?\s*约?\s*([\d.]+)\s*(?:个)?月"),
        ("renewal_rate",            r"(?:续约率|续签率)\s*[:：]?\s*([\d.]+)\s*%?"),
    ],
    "platform_commission": [
        ("monthly_gmv",     r"(?:月\s*GMV|月成交额|月交易额)\s*[:：]?\s*约?\s*[¥]?\s*([\d.]+)\s*(万|千|k|w|m|亿)?"),
        ("commission_rate", r"(?:佣金率|抽成|抽佣|take\s*rate)\s*[:：]?\s*([\d.]+)\s*%?"),
        ("active_sellers",  r"(?:活跃|月)\s*(?:卖家|供给方|商家|店铺)\s*[:：]?\s*约?\s*([\d,.]+)\s*(?:家|个)?"),
    ],
    "hardware_sales": [
        ("unit_price",   r"(?:出厂价|零售价|产品单价|售价|单价)\s*[:：]?\s*[¥]?\s*([\d.]+)\s*(?:元|块)?"),
        ("unit_cost",    r"(?:BOM|bom|物料|生产成本|单位成本)\s*[:：]?\s*[¥]?\s*([\d.]+)\s*(?:元|块)?"),
        ("monthly_units", r"(?:月销量|月出货|每月.*?(?:卖|出货))\s*[:：]?\s*约?\s*([\d,.]+)\s*(?:台|件|套|个)?"),
    ],
    "grant_funded": [
        ("active_grants",      r"(?:在期|当前)\s*(?:资助|项目)\s*([\d.]+)\s*(?:个|项)?"),
        ("grant_value_yearly", r"(?:单(?:个)?项目|每个?项目|每个?资助|单个资助)\s*(?:年(?:度)?)?\s*(?:金额)?\s*[:：]?\s*约?\s*[¥]?\s*([\d.]+)\s*(万|千|k|w|m)?"),
        ("renewal_rate",       r"(?:续期(?:率)?|续约(?:率)?)\s*[:：]?\s*([\d.]+)\s*%?"),
        ("beneficiaries_served", r"(?:月|每月)?\s*(?:服务|惠及|触达|受益|帮扶)\s*(?:人数?|对象)?\s*([\d,.]+)\s*(?:人|名|位|户)?"),
    ],
    "donation": [
        ("monthly_donors", r"(?:月)?\s*(?:活跃)?\s*捐赠(?:方|者|人)?\s*[:：]?\s*约?\s*([\d,.]+)\s*(?:个|名|人)?"),
        ("avg_donation",   r"(?:平均|人均)?\s*捐赠\s*(?:金额|额)\s*[:：]?\s*约?\s*[¥]?\s*([\d.]+)\s*(?:元|块)?"),
        ("donor_retention", r"(?:捐赠方|捐赠人|捐赠者)\s*(?:留存|续(?:捐|赠))\s*[:：]?\s*([\d.]+)\s*%?"),
    ],
}


def _to_number(val: str, unit: str = "") -> float:
    try:
        num = float(val.replace(",", ""))
    except (ValueError, AttributeError):
        return 0.0
    u = (unit or "").lower()
    if u == "万" or u == "w":
        num *= 1e4
    elif u in ("千", "k"):
        num *= 1e3
    elif u == "m":
        num *= 1e6
    elif u == "亿":
        num *= 1e8
    return num


def _normalize_pct(val: float) -> float:
    """规整百分比: > 1 视为百分制, ≤ 1 视为小数。"""
    if val > 1.5:
        return val / 100.0
    return val


def detect_pattern_candidates(text: str) -> list[tuple[str, int]]:
    """根据关键词命中数, 返回 [(pattern_key, score), ...] 按 score 降序。"""
    if not text:
        return []
    lower = text.lower()
    scores: list[tuple[str, int]] = []
    for pkey, kws in _PATTERN_KEYWORDS.items():
        score = sum(1 for kw in kws if kw.lower() in lower)
        if score > 0:
            scores.append((pkey, score))
    scores.sort(key=lambda x: -x[1])
    return scores


def extract_pattern_inputs(text: str, pattern_key: str) -> dict[str, dict[str, Any]]:
    """对给定 pattern, 抽出它的 input 字段。
    返回 {field: {value, raw, confidence, reference_note}}
    """
    if not text or pattern_key not in _FIELD_SYNONYMS:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for field, regex in _FIELD_SYNONYMS[pattern_key]:
        m = re.search(regex, text, re.IGNORECASE)
        if not m:
            continue
        raw = m.group(0)
        try:
            val_str = m.group(1)
        except IndexError:
            continue
        unit = ""
        if m.lastindex and m.lastindex >= 2:
            try:
                unit = m.group(2) or ""
            except (IndexError, ValueError):
                unit = ""
        val = _to_number(val_str, unit)
        if val <= 0:
            continue
        # 百分比字段规整
        if field in ("conversion_rate", "renewal_rate", "commission_rate", "donor_retention"):
            val = _normalize_pct(val)
        # 参考区间只作为说明，不做高低判断
        rng = get_field_range(pattern_key, field) or {}
        reference_note = ""
        if rng:
            low = rng.get("low")
            high = rng.get("high")
            unit_label = rng.get("unit") or ""
            if low is not None or high is not None:
                left = f"{low:g}" if isinstance(low, (int, float)) else "?"
                right = f"{high:g}" if isinstance(high, (int, float)) else "?"
                reference_note = f"公开样例常见记录约在 {left}-{right}{unit_label}"
        out[field] = {
            "value": val,
            "raw": raw.strip(),
            "confidence": 0.85,  # 正则强匹配, 可信度高
            "reference_note": reference_note,
            "range": rng,
        }
    return out


def extract_finance_signals(
    text: str,
    history: list[dict] | None = None,
    *,
    fallback_pattern: str | None = None,
) -> dict[str, Any]:
    """
    主入口: 从消息(+历史)抽出财务信号, 返回结构:
      {
        "triggered": bool,
        "hits": [...],                         # finance_guard 命中的分类
        "candidate_patterns": [(pkey, score)], # 关键词推断
        "pattern_inputs": {pkey: {field: {...}}},  # 每个 pattern 的字段
        "flat_signals": {...},                 # 原 finance_guard slot_fill 输出
        "primary_pattern": pkey,               # 选定的主导 pattern
        "summary": "...",                      # 给前端 banner 用的一句话
        "applied_count": 0,                    # 后续 apply 时填
      }
    """
    text = (text or "").strip()
    if not text:
        return {"triggered": False}

    hits = detect_triggers(text)
    flat_signals = slot_fill_from_text(text, history=history)

    candidates = detect_pattern_candidates(text)
    # 主导 pattern: 关键词命中最多者; 都没有则用 fallback (项目当前的 dominant) 或 subscription
    if candidates:
        primary = candidates[0][0]
    elif flat_signals.get("cost_per_beneficiary"):
        primary = "grant_funded"
    elif fallback_pattern and fallback_pattern in PATTERNS:
        primary = fallback_pattern
    else:
        primary = "subscription"

    pattern_inputs: dict[str, dict[str, Any]] = {}
    # 对所有候选 pattern 都试一次, 让 UI 看见全部信号
    tried = {p for p, _ in candidates}
    tried.add(primary)
    for pkey in tried:
        ext = extract_pattern_inputs(text, pkey)
        if ext:
            pattern_inputs[pkey] = ext

    triggered = bool(hits) or bool(pattern_inputs) or bool(flat_signals)

    # 拼一句 summary
    summary_parts = []
    main_inputs = pattern_inputs.get(primary, {})
    for field, payload in main_inputs.items():
        rng = payload.get("range") or {}
        unit = rng.get("unit", "")
        v = payload["value"]
        # 百分比字段渲染
        if field in ("conversion_rate", "renewal_rate", "commission_rate", "donor_retention"):
            v_str = f"{v*100:.1f}%"
        else:
            v_str = f"{v:,.0f}{unit}"
        summary_parts.append(f"{_field_zh(primary, field)}={v_str}")

    pattern_label = PATTERNS[primary].label if primary in PATTERNS else primary
    summary = ""
    if summary_parts:
        summary = f"识别到「{pattern_label}」: " + "、".join(summary_parts)
    elif flat_signals:
        summary = "识别到通用财务信号 " + ", ".join(f"{k}={v}" for k, v in flat_signals.items())

    return {
        "triggered": triggered,
        "hits": hits,
        "candidate_patterns": candidates,
        "pattern_inputs": pattern_inputs,
        "flat_signals": flat_signals,
        "primary_pattern": primary,
        "primary_pattern_label": pattern_label,
        "summary": summary,
        "kind": PATTERN_KIND.get(primary, "growth"),
    }


def _field_zh(pattern_key: str, field: str) -> str:
    """从 PATTERNS 找字段中文 label。"""
    p = PATTERNS.get(pattern_key)
    if p:
        for fs in p.fields:
            if fs.key == field:
                return fs.label
    return field


# ══════════════════════════════════════════════════════════════════
#  apply: 把 signals 写入预算
# ══════════════════════════════════════════════════════════════════

def apply_signals_to_budget(
    user_id: str,
    plan_id: str,
    signals: dict[str, Any],
    *,
    source_message_id: str = "",
    confidence_threshold: float = 0.6,
    overwrite: bool = False,
    storage: BudgetStorage | None = None,
) -> dict[str, Any]:
    """把 extract_finance_signals 的结果写到 budget 对应 stream 的 inputs。
    返回:
      {
        "applied": [{"stream_index": 0, "pattern": "subscription", "field": "price",
                     "old": 49, "new": 99}],
        "skipped": [{...}],
        "stream_added": bool,
      }
    """
    if not signals or (not signals.get("pattern_inputs") and not signals.get("flat_signals")):
        return {"applied": [], "skipped": [], "stream_added": False}
    if storage is None:
        # 延迟拿默认 storage 实例（避免在模块导入期就建文件夹）
        from app.main import budget_store as _default_store  # type: ignore
        storage = _default_store
    plan = None
    try:
        plan = storage.load(user_id, plan_id)
    except Exception as exc:
        logger.warning("apply_signals_to_budget: load failed user=%s plan=%s err=%s", user_id, plan_id, exc)
    if not plan:
        # 没有指定 plan, 自动用第一份方案
        try:
            plans = storage.list_plans(user_id) or []
            if plans:
                plan_id = plans[0].get("plan_id") or plan_id
                plan = storage.load(user_id, plan_id)
        except Exception:
            pass
    if not plan:
        return {"applied": [], "skipped": [], "stream_added": False, "error": "plan_not_found"}

    biz = plan.setdefault("business_finance", {})
    streams = biz.setdefault("revenue_streams", [])

    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    stream_added = False

    primary_pattern = signals.get("primary_pattern") or "subscription"
    primary_inputs = signals["pattern_inputs"].get(primary_pattern) or {}
    if not primary_inputs:
        # 取置信度第一的有数据的 pattern
        for pkey, fields in signals["pattern_inputs"].items():
            if fields:
                primary_pattern = pkey
                primary_inputs = fields
                break

    flat_signals = signals.get("flat_signals") or {}

    target_idx = None
    inputs: dict[str, Any] = {}
    ai_meta: dict[str, Any] = {}
    field_meta: dict[str, Any] = {}
    if primary_inputs:
        # 找/建对应 pattern 的 stream
        for i, s in enumerate(streams):
            if (s or {}).get("pattern_key") == primary_pattern:
                target_idx = i
                break
        if target_idx is None:
            # 没有对应 pattern 的流 → 新建一条
            meta = PATTERNS.get(primary_pattern)
            new_stream = {
                "name": (meta.label if meta else primary_pattern) + "（AI 自动建立）",
                "pattern_key": primary_pattern,
                "inputs": {},
                "monthly_revenue": 0,
                "_ai_meta": {
                    "ai_created": True,
                    "source": f"msg:{source_message_id}" if source_message_id else "auto",
                    "ts": time.time(),
                },
            }
            streams.append(new_stream)
            target_idx = len(streams) - 1
            stream_added = True

        target = streams[target_idx]
        target = normalize_stream(target)
        streams[target_idx] = target
        inputs = target.setdefault("inputs", {})
        ai_meta = target.setdefault("_ai_meta", {})
        field_meta = ai_meta.setdefault("fields", {})

    for field, payload in primary_inputs.items():
        conf = float(payload.get("confidence") or 0)
        if conf < confidence_threshold:
            skipped.append({"stream_index": target_idx, "field": field, "reason": "low_confidence"})
            continue
        old = inputs.get(field)
        new_val = payload["value"]
        if old is not None and not overwrite:
            try:
                if abs(float(old) - float(new_val)) < 1e-6:
                    skipped.append({"stream_index": target_idx, "field": field, "reason": "no_change"})
                    continue
                # 用户可能已经手填了, 不覆盖, 但写到 _ai_meta.suggestions 里供 UI 提醒
                ai_meta.setdefault("suggestions", []).append({
                    "field": field, "value": new_val, "raw": payload.get("raw"),
                    "source": f"msg:{source_message_id}" if source_message_id else "auto",
                    "ts": time.time(),
                })
                skipped.append({"stream_index": target_idx, "field": field, "reason": "user_value_present", "suggested": new_val})
                continue
            except (TypeError, ValueError):
                pass
        inputs[field] = new_val
        field_meta[field] = {
            "ai_filled": True,
            "value": new_val,
            "prev_value": old,
            "raw": payload.get("raw"),
            "reference_note": payload.get("reference_note"),
            "source": f"msg:{source_message_id}" if source_message_id else "auto",
            "ts": time.time(),
            "confidence": conf,
        }
        applied.append({
            "stream_index": target_idx, "pattern": primary_pattern,
            "field": field, "old": old, "new": new_val,
        })

    flat_meta = biz.setdefault("_ai_flat_meta", {})
    for field, value in flat_signals.items():
        if field not in _BIZ_FLAT_FIELDS:
            continue
        try:
            num = float(value)
        except (TypeError, ValueError):
            continue
        old = biz.get(field)
        if old is not None and not overwrite:
            try:
                if abs(float(old) - num) < 1e-6:
                    continue
            except (TypeError, ValueError):
                pass
        biz[field] = num
        flat_meta[field] = {
            "ai_filled": True,
            "value": num,
            "prev_value": old,
            "source": f"msg:{source_message_id}" if source_message_id else "auto",
            "ts": time.time(),
        }
        applied.append({
            "stream_index": None,
            "pattern": "flat",
            "field": field,
            "old": old,
            "new": num,
        })

    # 写回 + 重算 cash flow
    plan["business_finance"] = biz
    try:
        plan = BudgetStorage.compute_cash_flow(plan)
    except Exception as exc:
        logger.warning("apply_signals: compute_cash_flow failed: %s", exc)
    try:
        storage.save(user_id, plan_id, plan)
    except Exception as exc:
        logger.warning("apply_signals: save failed: %s", exc)
        return {"applied": [], "skipped": skipped, "stream_added": False, "error": str(exc)}

    return {
        "applied": applied,
        "skipped": skipped,
        "stream_added": stream_added,
        "stream_index": target_idx,
        "pattern": primary_pattern,
        "plan_id": plan_id,
    }


__all__ = [
    "extract_finance_signals",
    "extract_pattern_inputs",
    "detect_pattern_candidates",
    "apply_signals_to_budget",
]
