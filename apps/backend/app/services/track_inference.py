from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from typing import Any

from app.services.project_cognition import (
    clamp_track_value,
    default_track_inference_meta,
    ensure_project_cognition,
    normalize_track_vector,
)


BJ_TZ = timezone(timedelta(hours=8))

SOURCE_WEIGHTS = {
    "student": 1.0,
    "structured": 0.8,
    "inferred": 0.45,
    "agent": 0.25,
    "system": 0.2,
}


def _now_iso() -> str:
    return datetime.now(BJ_TZ).isoformat()


def _keyword_score(text: str, keywords: list[str]) -> float:
    score = 0.0
    lowered = str(text or "").lower()
    for kw in keywords:
        if kw and kw.lower() in lowered:
            score += 1.0
    return score


def infer_track_vector(
    message: str,
    *,
    diagnosis: dict[str, Any] | None = None,
    category: str = "",
    competition_type: str = "",
    structured_signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnosis = diagnosis if isinstance(diagnosis, dict) else {}
    structured_signals = structured_signals if isinstance(structured_signals, dict) else {}
    text = "\n".join(
        item for item in [
            str(message or ""),
            str(diagnosis.get("bottleneck") or ""),
            str(category or ""),
            str(competition_type or ""),
        ] if item
    )

    innov_score = _keyword_score(text, [
        "创新", "技术路线", "论文", "实验", "算法", "专利", "baseline",
        "科研", "可复现", "novelty", "原创", "前沿", "技术突破", "首创",
    ])
    venture_score = _keyword_score(text, [
        "创业", "用户", "mvp", "获客", "增长", "商业模式", "融资",
        "渠道", "留存", "付费", "试点", "推广", "团队", "市场",
    ])
    biz_score = _keyword_score(text, [
        "营收", "利润", "毛利", "收费", "定价", "现金流", "客户",
        "合同", "复购", "gmv", "订阅", "广告", "to b", "to c",
        "回本", "盈利", "成本", "客单价",
    ])
    # 公益词库放宽：把"受益人画像 / 服务对象 / 资金来源 / 价值主张"四类
    # 实际表达都覆盖进来，避免只有写"公益"两个字时才算公益。
    public_score = _keyword_score(text, [
        # 价值与立场
        "公益", "社会价值", "社会影响", "社会问题", "社会创新",
        "可持续", "可及性", "普惠", "包容", "包容性", "公共服务",
        # 受益人 / 服务对象（关键）
        "受益人", "受助", "弱势群体", "弱势", "独居", "留守", "残障",
        "失能", "孤儿", "老人", "儿童", "助老", "助残", "助学",
        # 实施主体 / 资源
        "志愿者", "义工", "捐赠", "非营利", "ngo", "公益基金",
        "社会企业", "民政", "街道", "社区", "乡村", "扶贫", "帮扶",
        "赋能", "义诊", "义教",
        # 资金来源
        "政府购买", "政府支持", "csr", "资助", "公益基金", "社会资本",
        "sroi",
    ])

    # 类目硬偏置
    if "公益" in category or "社会" in category:
        public_score += 1.5
    # 挑战杯涵盖科技作品/红色专项/哲社等多类，不再只压向"创新"
    # （否则公益挑战杯也会被识别为创新驱动）。
    if competition_type == "challenge_cup":
        innov_score += 0.3
        public_score += 0.3
    if competition_type == "internet_plus":
        venture_score += 0.5
        biz_score += 0.4

    # 公益判定的"显著性"加成：如果命中 >=2 个公益词，且文本里几乎没有
    # 营收类硬商业词，再追加一档，避免被同语境里的"用户/团队"等词稀释。
    if public_score >= 2.0 and biz_score < 1.5:
        public_score += 1.0

    signal_bonus = 0.0
    for key, value in structured_signals.items():
        try:
            num = float(value or 0)
        except Exception:
            continue
        if num <= 0:
            continue
        if any(token in key.lower() for token in ["revenue", "ltv", "cac", "pricing", "budget"]):
            biz_score += min(num, 1.0) * 0.5
            venture_score += min(num, 1.0) * 0.2
            signal_bonus += 0.1
        if any(token in key.lower() for token in ["evidence", "interview", "experiment", "validation"]):
            innov_score += min(num, 1.0) * 0.25
            venture_score += min(num, 1.0) * 0.25
            signal_bonus += 0.1

    # 归一到 [-1, 1]：用 tanh 而不是 (v-i)/(v+i)。
    # 旧公式的问题：当 v 和 i 同时很高时分子→0，"既创新又创业"的项目永远归零；
    # 同时小幅差异（v=2, i=1）也会被 (v+i) 稀释成 0.33。
    # 新公式 tanh((v-i) / scale)：
    #   - 差 1 个关键词 → 约 ±0.46（小幅偏离也能识别）
    #   - 差 2 个关键词 → 约 ±0.76
    #   - 差 3+ 个关键词 → 接近 ±1（饱和）
    #   - 双方都强但相等 → 0（这是合理的"中立"）
    iv_total = innov_score + venture_score
    bp_total = biz_score + public_score
    innov_venture = clamp_track_value(math.tanh((venture_score - innov_score) / 2.0)) if iv_total > 0 else 0.0
    biz_public = clamp_track_value(math.tanh((public_score - biz_score) / 2.0)) if bp_total > 0 else 0.0

    # 信号总量越多置信度越高（旧版每个关键词加 0.045 太小，调到 0.07）
    confidence = min(0.92, 0.30 + iv_total * 0.07 + bp_total * 0.07 + signal_bonus)
    evidence = []
    if innov_score:
        evidence.append(f"创新信号 {innov_score:.1f}")
    if venture_score:
        evidence.append(f"创业信号 {venture_score:.1f}")
    if biz_score:
        evidence.append(f"商业信号 {biz_score:.1f}")
    if public_score:
        evidence.append(f"公益信号 {public_score:.1f}")

    return {
        "track_vector": {
            "innov_venture": innov_venture,
            "biz_public": biz_public,
            "source": "inferred",
            "updated_at": _now_iso(),
        },
        "confidence": round(confidence, 4),
        "source_mix": {
            "message": 1.0,
            "diagnosis": 1.0 if diagnosis else 0.0,
            "structured_signals": 1.0 if structured_signals else 0.0,
        },
        "reason": "基于当前轮文本信号、诊断摘要与结构化证据推断双光谱位置。",
        "evidence": evidence,
    }


def _update_streak(meta: dict[str, Any], axis: str, delta: float) -> None:
    streaks = meta.setdefault("streaks", {})
    current = streaks.get(axis)
    if not isinstance(current, dict):
        current = {"direction": "neutral", "count": 0}
    direction = "positive" if delta > 0.02 else "negative" if delta < -0.02 else "neutral"
    if direction == "neutral":
        streaks[axis] = {"direction": "neutral", "count": 0}
        return
    if current.get("direction") == direction:
        count = int(current.get("count") or 0) + 1
    else:
        count = 1
    streaks[axis] = {"direction": direction, "count": count}


def _blend_axis(current: float, target: float, confidence: float, weight: float, streak: dict[str, Any]) -> float:
    diff = target - current
    if abs(diff) < 0.02:
        return current

    # 冷启动通道：当前几乎没有先验（|current| < 0.08），且推断方向明确（|target| >= 0.3）、
    # 置信度足够（>=0.45）时，允许一次性挪 0.6 倍 diff，让"第一次就能识别出明确偏向"。
    # 这条通道只在前期生效，进入显著区后惯性恢复正常。
    cold_start = abs(current) < 0.08 and abs(target) >= 0.3 and confidence >= 0.45
    if cold_start:
        return clamp_track_value(current + diff * 0.6)

    # 低置信度推断只允许 ±0.10 的微调
    if confidence < 0.45:
        diff = max(min(diff, 0.1), -0.1)
    # 大跨度（|diff| >= 0.3）需要至少 1 次同向 streak 才放行；旧版要求 2 次太严
    if abs(diff) >= 0.3 and int(streak.get("count") or 0) < 1:
        diff = max(min(diff, 0.22), -0.22)
    alpha = max(0.15, min(0.75, weight * max(confidence, 0.25)))
    return clamp_track_value(current + diff * alpha)


def merge_track_vector(
    current_state: dict[str, Any] | None,
    inferred: dict[str, Any],
    *,
    source: str = "inferred",
) -> tuple[dict[str, Any], dict[str, Any]]:
    state = ensure_project_cognition(current_state)
    current = normalize_track_vector(state.get("track_vector"))
    current_meta = state.get("track_inference_meta")
    if not isinstance(current_meta, dict):
        current_meta = default_track_inference_meta()

    incoming = normalize_track_vector((inferred or {}).get("track_vector"))
    confidence = float((inferred or {}).get("confidence") or 0.0)
    source_key = str(source or incoming.get("source") or "inferred")
    weight = SOURCE_WEIGHTS.get(source_key, SOURCE_WEIGHTS["inferred"])
    streaks = current_meta.get("streaks") if isinstance(current_meta.get("streaks"), dict) else {}

    next_vector = {
        "innov_venture": _blend_axis(
            float(current.get("innov_venture") or 0.0),
            float(incoming.get("innov_venture") or 0.0),
            confidence,
            weight,
            streaks.get("innov_venture") or {},
        ),
        "biz_public": _blend_axis(
            float(current.get("biz_public") or 0.0),
            float(incoming.get("biz_public") or 0.0),
            confidence,
            weight,
            streaks.get("biz_public") or {},
        ),
        "source": source_key,
        "updated_at": _now_iso(),
    }

    next_meta = default_track_inference_meta()
    next_meta.update(current_meta)
    next_meta["confidence"] = round(confidence, 4)
    next_meta["source_mix"] = inferred.get("source_mix") if isinstance(inferred.get("source_mix"), dict) else {}
    next_meta["last_reason"] = str(inferred.get("reason") or "")
    next_meta["last_evidence"] = list(inferred.get("evidence") or [])[:6]
    _update_streak(next_meta, "innov_venture", next_vector["innov_venture"] - float(current.get("innov_venture") or 0.0))
    _update_streak(next_meta, "biz_public", next_vector["biz_public"] - float(current.get("biz_public") or 0.0))

    snapshot = {
        "innov_venture": next_vector["innov_venture"],
        "biz_public": next_vector["biz_public"],
        "source": source_key,
        "confidence": round(confidence, 4),
        "reason": str(inferred.get("reason") or ""),
        "updated_at": next_vector["updated_at"],
    }
    history = list(state.get("track_history") or [])
    history.append(snapshot)
    state["track_history"] = history[-20:]
    state["track_vector"] = next_vector
    state["track_inference_meta"] = next_meta
    return state, snapshot


def infer_project_stage_v2(diagnosis: dict[str, Any] | None, current_state: dict[str, Any] | None = None) -> str:
    diagnosis = diagnosis if isinstance(diagnosis, dict) else {}
    raw_stage = str(diagnosis.get("project_stage") or "").strip()
    mapped = {
        "idea": "idea",
        "structured": "structured",
        "validated": "validated",
        "document": "validated",
        "scale": "scale",
    }.get(raw_stage)
    if mapped:
        return mapped
    state = ensure_project_cognition(current_state)
    prev = str(state.get("project_stage_v2") or "").strip()
    return prev or "structured"
