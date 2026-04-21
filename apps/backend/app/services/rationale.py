"""
统一的「打分 / 结论」可追溯 payload：
- Rationale 表示一条结论的完整推理链：最终值 + 公式 + 各输入 + 贡献证据
- RationaleInput 表示一个输入项（带权重、来源消息/提交、excerpt）
- 前后端共享同一形状；前端 RationaleCard 组件照此结构直接渲染

约定：
- field 形如 "rubric:resource" / "maturity:users" / "overall" / "risk:R12" / "portrait:strength_top1"
- value 可为数值或标签字符串
- formula 是机器可读公式（伪代码），formula_display 是给老师看的中文算式
- inputs 是参与计算的项；contributing_evidence 是更细颗粒的证据消息
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class RationaleInput:
    """参与计算的单条输入（如一个 submission 的某个评分维度，或一个 slot）。"""
    label: str
    value: float | str
    weight: float | None = None
    source_message_id: str | None = None
    source_submission_id: str | None = None
    source_conversation_id: str | None = None
    excerpt: str = ""
    agent: str | None = None
    rule_id: str | None = None
    impact: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None and v != ""}


@dataclass
class ContributingEvidence:
    """细颗粒证据消息（比 RationaleInput 更轻量，仅用于「点这条消息跳过去」）。"""
    message_id: str = ""
    turn_index: int | None = None
    role: str = ""
    excerpt: str = ""
    impact: str = ""
    agent: str | None = None
    rule_id: str | None = None
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {k: v for k, v in asdict(self).items() if v is not None and v != ""}
        return data


@dataclass
class Rationale:
    field: str
    value: float | str
    formula: str = ""
    formula_display: str = ""
    inputs: list[RationaleInput] = field(default_factory=list)
    contributing_evidence: list[ContributingEvidence] = field(default_factory=list)
    teacher_override: dict[str, Any] | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "field": self.field,
            "value": self.value,
        }
        if self.formula:
            out["formula"] = self.formula
        if self.formula_display:
            out["formula_display"] = self.formula_display
        if self.inputs:
            out["inputs"] = [i.to_dict() for i in self.inputs]
        if self.contributing_evidence:
            out["contributing_evidence"] = [e.to_dict() for e in self.contributing_evidence]
        if self.teacher_override:
            out["teacher_override"] = self.teacher_override
        if self.note:
            out["note"] = self.note
        return out


# ─── 构造帮助函数 ────────────────────────────────────────────────
def build_rubric_rationale(
    dim_key: str,
    dim_name: str,
    avg_score: float,
    sub_scores: list[tuple[str, float, str]],
    *,
    weight: float = 1.0,
    evidence: list[ContributingEvidence] | None = None,
) -> Rationale:
    """rubric 某维度的分：avg = Σ(submission_score) / N。

    sub_scores: [(submission_id, score, excerpt)]。
    """
    inputs = [
        RationaleInput(
            label=f"提交 {sid[:8]}",
            value=float(sc),
            source_submission_id=sid,
            excerpt=(excerpt or "")[:160],
        )
        for sid, sc, excerpt in sub_scores
    ]
    n = max(1, len(sub_scores))
    formula_display = (
        f"{dim_name}均分 = Σ(各次提交分) ÷ 提交数"
        f"\n= ({' + '.join(f'{sc:.1f}' for _, sc, _ in sub_scores) or '0'}) ÷ {n}"
        f"\n= {avg_score:.2f}"
    )
    return Rationale(
        field=f"rubric:{dim_key}",
        value=round(float(avg_score), 2),
        formula="avg(submission_scores)",
        formula_display=formula_display,
        inputs=inputs,
        contributing_evidence=evidence or [],
        note=f"权重 {weight} · 共 {n} 次提交",
    )


def build_overall_rationale(
    overall_score: float,
    rubric_contrib: list[tuple[str, float, float]],
    risk_deductions: list[tuple[str, str, float]],
) -> Rationale:
    """overall = Σ(rubric_i × w_i) − Σ(risk_j × impact_j)。

    rubric_contrib: [(dim_key, score, weight)]
    risk_deductions: [(rule_id, rule_name, deduction)]
    """
    inputs: list[RationaleInput] = []
    parts: list[str] = []
    weighted_total = 0.0
    weight_sum = 0.0
    for dim, sc, w in rubric_contrib:
        inputs.append(RationaleInput(label=f"rubric·{dim}", value=round(sc, 2), weight=w, impact=f"+{sc * w:.2f}"))
        parts.append(f"{sc:.1f}×{w:.1f}")
        weighted_total += sc * w
        weight_sum += w
    deduct_total = 0.0
    for rid, rname, imp in risk_deductions:
        inputs.append(RationaleInput(label=f"风险·{rid}", value=rname, weight=-1.0, rule_id=rid, impact=f"−{abs(imp):.2f}"))
        deduct_total += abs(imp)
    formula_display = (
        "综合分 = Σ(rubric_i × weight_i) − Σ(风险扣分)\n"
        f"= ({' + '.join(parts) or '0'}) − {deduct_total:.2f}\n"
        f"= {weighted_total:.2f} − {deduct_total:.2f}\n"
        f"= {overall_score:.2f}"
    )
    return Rationale(
        field="overall",
        value=round(float(overall_score), 2),
        formula="Σ(rubric×w) − Σ(risk_impact)",
        formula_display=formula_display,
        inputs=inputs,
        note=f"rubric 权重合计 {weight_sum:.1f}；扣分合计 {deduct_total:.2f}",
    )


def build_maturity_field_rationale(
    field_key: str,
    field_name: str,
    level: str,
    score: float,
    slot_excerpts: list[tuple[str, str, str | None]],
    *,
    level_explain: str = "",
) -> Rationale:
    """maturity 某 field 的等级 / 得分 rationale。

    slot_excerpts: [(slot_name, excerpt, source_message_id)]
    """
    inputs = [
        RationaleInput(
            label=slot,
            value=(excerpt or "")[:80] or "—",
            excerpt=excerpt or "",
            source_message_id=mid,
        )
        for slot, excerpt, mid in slot_excerpts
    ]
    filled = sum(1 for _, ex, _ in slot_excerpts if (ex or "").strip())
    total = max(1, len(slot_excerpts))
    formula_display = (
        f"{field_name} 等级 = {level}\n"
        f"依据：已填核心信息 {filled}/{total}；得分权重 {score:.2f}。\n"
        + (f"说明：{level_explain}" if level_explain else "")
    )
    return Rationale(
        field=f"maturity:{field_key}",
        value=level,
        formula="fill_ratio → level",
        formula_display=formula_display,
        inputs=inputs,
        note=f"已填 {filled}/{total} · 得分 {score:.2f}",
    )


def build_risk_rationale(
    rule_id: str,
    rule_name: str,
    score_impact: float,
    evidence: list[ContributingEvidence],
    *,
    matched_keywords: list[str] | None = None,
    agent: str | None = None,
) -> Rationale:
    """风险规则的 rationale：为什么触发 + 扣多少分。"""
    keywords_text = "、".join(matched_keywords or []) or "(无)"
    formula_display = (
        f"触发条件：命中关键词 [{keywords_text}] 且缺少必填信息\n"
        f"扣分：{score_impact:+.2f}（将进入综合分调整）"
    )
    inputs: list[RationaleInput] = []
    for kw in (matched_keywords or [])[:6]:
        inputs.append(RationaleInput(label="关键词命中", value=kw, impact="触发"))
    return Rationale(
        field=f"risk:{rule_id}",
        value=f"{rule_name}",
        formula="keyword_hit ∧ required_missing ⇒ trigger",
        formula_display=formula_display,
        inputs=inputs,
        contributing_evidence=evidence,
        note=f"agent={agent or '—'} · 扣分 {score_impact:+.2f}",
    )


def build_portrait_rationale(
    target: str,
    title: str,
    value: str,
    contributing_dims: list[tuple[str, float]],
    evidence: list[ContributingEvidence] | None = None,
) -> Rationale:
    """画像类结论（强弱项、Top 风险）。"""
    inputs = [
        RationaleInput(label=dim, value=round(float(sc), 2), impact=f"avg={sc:.2f}")
        for dim, sc in contributing_dims
    ]
    formula_display = (
        f"{title}：根据九维 rubric 均分排序得出。\n"
        + "\n".join(f"- {d}：{sc:.2f}" for d, sc in contributing_dims[:5])
    )
    return Rationale(
        field=f"portrait:{target}",
        value=value,
        formula="rank_by_avg_rubric",
        formula_display=formula_display,
        inputs=inputs,
        contributing_evidence=evidence or [],
    )


__all__ = [
    "Rationale",
    "RationaleInput",
    "ContributingEvidence",
    "build_rubric_rationale",
    "build_overall_rationale",
    "build_maturity_field_rationale",
    "build_risk_rationale",
    "build_portrait_rationale",
]
