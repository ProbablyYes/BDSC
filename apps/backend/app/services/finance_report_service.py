"""
finance_report_service — 深度财务分析报告服务

学生在分析面板点击「生成财务分析报告」后，串行跑 finance_analyst 的六模块，
结合 LLM 对 framework_explain 做教学化润色，存到 data/finance_reports/{user_id}.json。

模式参照 business_plan_service：
  - generate(user_id, plan_id, context) 产出一份报告
  - load_latest(user_id) 读最新一份
  - regenerate(user_id) 重跑

对外：
  - 每个报告结构：report_id / user_id / generated_at / modules[] / merged_evidence / inputs_snapshot
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services.finance_analyst import (
    analyze_unit_economics,
    evaluate_rationality,
    project_cash_flow,
    estimate_market_size,
    recommend_pricing_framework,
    match_funding_stage,
    extract_assumptions_from_budget,
    _match_industry,
)
from app.services.finance_guard import slot_fill_from_text

logger = logging.getLogger(__name__)
BJ_TZ = timezone(timedelta(hours=8))


def _now_iso() -> str:
    return datetime.now(BJ_TZ).isoformat()


def _module_conclusion(module: dict[str, Any]) -> str:
    outputs = module.get("outputs") or {}
    conclusion = outputs.get("analysis_conclusion")
    if isinstance(conclusion, str) and conclusion.strip():
        return conclusion.strip()
    verdict = (module.get("verdict") or {}).get("reason")
    if isinstance(verdict, str) and verdict.strip():
        return verdict.strip()
    return ""


def _build_finance_summary_card(modules: list[dict[str, Any]]) -> dict[str, Any]:
    by_key = {m.get("module"): m for m in modules if isinstance(m, dict)}
    focus_keys = ["unit_economics", "cash_flow", "rationality", "market_size"]
    findings = []
    missing_fields: list[str] = []
    has_red = False
    has_yellow = False

    for key in focus_keys:
        mod = by_key.get(key) or {}
        verdict = mod.get("verdict") or {}
        level = verdict.get("level")
        if level == "red":
            has_red = True
        elif level == "yellow":
            has_yellow = True
        title = mod.get("title") or key
        conclusion = _module_conclusion(mod)
        if conclusion:
            findings.append(f"{title}：{conclusion}")
        for item in (mod.get("missing_inputs") or [])[:3]:
            field = item.get("field")
            if field and field not in missing_fields:
                missing_fields.append(field)

    if has_red:
        overall = "当前模型已经能算出结果，但至少有一条关键财务链路存在内部冲突，继续放大会放大这个问题。"
        level = "red"
        score = 0.35
    elif has_yellow:
        overall = "当前财务模型已形成主链路，但仍有部分关键假设需要补齐，结论更适合用于校准而不是直接定案。"
        level = "yellow"
        score = 0.58
    else:
        overall = "当前财务模型的主要链路已经闭环，可以开始进入版本结构、敏感性和资源配置优化。"
        level = "green"
        score = 0.82

    suggestions = []
    for key in focus_keys:
        for item in ((by_key.get(key) or {}).get("suggestions") or [])[:2]:
            if item not in suggestions:
                suggestions.append(item)
    if missing_fields:
        suggestions.insert(0, f"优先补齐这些关键假设：{', '.join(missing_fields[:6])}")

    return {
        "module": "finance_summary",
        "title": "财务结论摘要",
        "inputs": {},
        "outputs": {
            "analysis_conclusion": overall,
            "key_findings": findings[:4],
            "missing_fields": missing_fields,
        },
        "verdict": {
            "level": level,
            "score": score,
            "reason": overall,
        },
        "framework_explain": "这是对单位经济、现金流、假设自检和市场规模四个模块的合成判断，用来回答“当前商业模式意味着什么”。",
        "suggestions": suggestions[:5],
        "missing_inputs": [],
        "evidence_for_diagnosis": {},
        "baseline_meta": {},
    }


class FinanceReportService:
    """深度财务分析报告生成 + 持久化。"""

    def __init__(
        self,
        data_root: Path,
        budget_store: Any = None,
        conv_store: Any = None,
        json_store: Any = None,
        llm: Any = None,
    ):
        self.root = Path(data_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.budget_store = budget_store
        self.conv_store = conv_store
        self.json_store = json_store
        self.llm = llm
        # 进行中状态：防重入 + 给前端轮询
        self._status: dict[str, dict[str, Any]] = {}

    def _file(self, user_id: str) -> Path:
        safe = str(user_id).replace("/", "_").replace("\\", "_")
        return self.root / f"{safe}.json"

    # ── 状态 ──

    def get_status(self, user_id: str) -> dict[str, Any]:
        return self._status.get(user_id, {"status": "idle"})

    def _set_status(self, user_id: str, status: str, detail: str = "") -> None:
        self._status[user_id] = {"status": status, "detail": detail, "updated_at": _now_iso()}

    # ── 持久化 ──

    def load_latest(self, user_id: str) -> dict | None:
        f = self._file(user_id)
        if not f.exists():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("finance_report load failed for %s: %s", user_id, exc)
            return None

    def _save(self, user_id: str, report: dict) -> dict:
        f = self._file(user_id)
        f.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    # ── 数据采集 ──

    def _collect_inputs(
        self,
        user_id: str,
        plan_id: str | None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        industry_hint: str = "",
        context_text: str = "",
    ) -> tuple[dict, dict]:
        """合并三路输入。返回 (assumptions, context_meta)。"""
        assumptions: dict[str, Any] = {}
        context_meta: dict[str, Any] = {
            "plan_id": plan_id,
            "project_id": project_id,
            "conversation_id": conversation_id,
        }

        # 1) budget snapshot
        budget_snapshot: dict | None = None
        if self.budget_store and user_id:
            try:
                if plan_id:
                    budget_snapshot = self.budget_store.load(user_id, plan_id)
                else:
                    plans = self.budget_store.list_plans(user_id)
                    if plans:
                        first = plans[0]
                        budget_snapshot = self.budget_store.load(user_id, first.get("plan_id", ""))
                        plan_id = first.get("plan_id", "")
                        context_meta["plan_id"] = plan_id
            except Exception as exc:
                logger.warning("load budget snapshot failed: %s", exc)

        if budget_snapshot:
            assumptions.update(extract_assumptions_from_budget(budget_snapshot))
        context_meta["has_budget"] = bool(budget_snapshot)

        # 2) conversation snippet for slot fill
        conv_text = context_text or ""
        if self.conv_store and project_id and conversation_id and not conv_text:
            try:
                conv = self.conv_store.get(project_id, conversation_id)
                if conv:
                    # 把最近 10 条学生发言串起来
                    msgs = conv.get("messages", [])
                    user_msgs = [m for m in msgs if isinstance(m, dict) and m.get("role") == "user"]
                    conv_text = "\n".join(
                        str(m.get("content", ""))[:500] for m in user_msgs[-10:]
                    )
            except Exception as exc:
                logger.warning("load conversation failed: %s", exc)

        if conv_text:
            text_slots = slot_fill_from_text(conv_text)
            # budget 优先
            for k, v in text_slots.items():
                if k not in assumptions or not assumptions.get(k):
                    assumptions[k] = v
        context_meta["conv_len"] = len(conv_text) if conv_text else 0
        context_meta["conv_text"] = conv_text[:4000] if conv_text else ""

        # 3) project state
        project_state: dict[str, Any] = {}
        if self.json_store and project_id:
            try:
                proj = self.json_store.load_project(project_id)
                if proj:
                    project_state = {
                        "has_mvp": bool(proj.get("has_mvp") or proj.get("mvp_done")),
                        "paying_users": 0,
                        "monthly_revenue": 0,
                        "team_size": len(proj.get("team_members", []) or []) or int(proj.get("team_size") or 0),
                        "validated_channel": False,
                        "positive_unit_econ": False,
                    }
            except Exception:
                pass
        context_meta["project_state"] = project_state

        # 4) industry
        ind_raw = industry_hint
        if not ind_raw and conv_text:
            from app.services.case_knowledge import infer_category
            try:
                ind_raw = infer_category(conv_text) or ""
            except Exception:
                ind_raw = ""
        context_meta["industry"] = _match_industry(ind_raw)

        return assumptions, context_meta

    # ── 生成 ──

    def generate(
        self,
        user_id: str,
        plan_id: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        industry_hint: str = "",
        context_text: str = "",
        use_llm_explain: bool = True,
    ) -> dict:
        """同步生成一份完整报告并保存。返回 report dict。"""
        if self._status.get(user_id, {}).get("status") == "running":
            raise RuntimeError("上一次生成还在进行，请稍后再试")

        self._set_status(user_id, "running", "采集输入数据")
        try:
            assumptions, context = self._collect_inputs(
                user_id=user_id,
                plan_id=plan_id,
                project_id=project_id,
                conversation_id=conversation_id,
                industry_hint=industry_hint,
                context_text=context_text,
            )
            industry = context["industry"]
            description = context.get("conv_text", "")[:2000]
            project_state = context.get("project_state") or {}

            self._set_status(user_id, "running", "跑单位经济模型")
            ue = analyze_unit_economics(assumptions, industry=industry, allow_online=True)
            self._set_status(user_id, "running", "跑现金流推演")
            cf = project_cash_flow(assumptions, months=36, industry=industry, allow_online=True)
            self._set_status(user_id, "running", "跑合理性评估")
            rat = evaluate_rationality(assumptions, industry=industry, allow_online=True)
            self._set_status(user_id, "running", "建模 TAM/SAM/SOM")
            mkt_hints = {
                "target_user_population": assumptions.get("target_user_population"),
                "serviceable_user_population": assumptions.get("serviceable_user_population"),
                "serviceable_ratio": assumptions.get("serviceable_ratio"),
                "first_year_reach_users": assumptions.get("first_year_reach_users") or (assumptions.get("new_users_per_month", 0) * 12 if assumptions.get("new_users_per_month") else None),
                "paid_conversion_rate": assumptions.get("paid_conversion_rate"),
                "annual_arpu": assumptions.get("annual_arpu"),
                "industry_tam_billions": assumptions.get("industry_tam_billions"),
                "industry_sam_billions": assumptions.get("industry_sam_billions"),
            }
            mkt = estimate_market_size(description, industry=industry, hints=mkt_hints)
            self._set_status(user_id, "running", "推荐定价策略")
            pf = recommend_pricing_framework(
                project_type=description[:120],
                stage=self._infer_stage(assumptions, project_state),
                industry=industry,
            )
            self._set_status(user_id, "running", "匹配融资节奏")
            fs = match_funding_stage(project_state=project_state, current_need={})

            # ── 新增模块: 财务画像（按 RevenuePattern 大类）──
            try:
                from app.services.finance_pattern_formulas import (
                    detect_pattern_kind_mix, evaluate_stream_unit_econ, PATTERN_KIND,
                )
                from app.services.revenue_models import PATTERNS as _PATTERNS
                by_stream = assumptions.get("by_stream") or []
                mix = detect_pattern_kind_mix(by_stream) if by_stream else {
                    "dominant_kind": None, "dominant_pattern": None,
                    "kind_mix": {}, "pattern_mix": {}, "is_public": False,
                    "total_monthly_revenue": 0.0,
                }
                _persona_label_map = {
                    "growth":    "增长型 SaaS / C 端",
                    "enterprise": "B 端项目制 / 企业服务",
                    "platform":  "双边平台型",
                    "hardware":  "硬件 / 实体产品",
                    "public":    "公益可持续型",
                    None:        "未识别",
                }
                persona = _persona_label_map.get(mix.get("dominant_kind"), "混合型")
                # 每条流跑一遍 unit_econ 拿 KPI
                stream_kpis = []
                for s in by_stream:
                    r = evaluate_stream_unit_econ(s)
                    pkey = r.get("pattern_key")
                    stream_kpis.append({
                        "name": s.get("name") or (_PATTERNS[pkey].label if pkey in _PATTERNS else pkey),
                        "pattern_key": pkey,
                        "kind": r.get("kind"),
                        "monthly_revenue": s.get("monthly_revenue"),
                        "primary_kpi": r.get("primary_kpi"),
                        "health": r.get("health"),
                        "reason": r.get("reason"),
                    })
                persona_card = {
                    "module": "finance_persona",
                    "title": "财务画像（按收入模式）",
                    "inputs": {
                        "stream_count": len(by_stream),
                        "is_public": mix.get("is_public"),
                        "industry": industry,
                    },
                    "outputs": {
                        "persona_label": persona,
                        "dominant_pattern": mix.get("dominant_pattern"),
                        "dominant_kind": mix.get("dominant_kind"),
                        "kind_mix": mix.get("kind_mix"),
                        "pattern_mix": mix.get("pattern_mix"),
                        "total_monthly_revenue": mix.get("total_monthly_revenue"),
                        "stream_kpis": stream_kpis,
                    },
                    "verdict": {
                        "level": "green" if by_stream else "gray",
                        "score": 0.7 if by_stream else 0.3,
                        "reason": (
                            f"识别为「{persona}」, 共 {len(by_stream)} 条收入流, 月营收 ¥{mix.get('total_monthly_revenue',0):,.0f}"
                            if by_stream else "尚未识别到收入流, 后续模块可能数据不全"
                        ),
                    },
                    "framework_explain": (
                        "**财务画像**根据项目当前的收入流模式分布, 给出"
                        "「增长型 / B 端 / 平台 / 硬件 / 公益」等画像标签, "
                        "后续模块的公式与分析视角会据此分支。"
                    ),
                    "suggestions": [],
                    "evidence_for_diagnosis": {},
                    "missing_inputs": [],
                }
                modules = [persona_card, ue, cf, rat, mkt, pf, fs]
            except Exception as _persona_err:
                logger.warning("finance_persona module failed: %s", _persona_err)
                modules = [ue, cf, rat, mkt, pf, fs]

            summary_card = _build_finance_summary_card(modules)
            modules = [summary_card] + modules

            # LLM 润色 framework_explain（可选）
            if use_llm_explain and self.llm is not None and getattr(self.llm, "enabled", False):
                try:
                    self._set_status(user_id, "running", "LLM 润色讲解")
                    self._llm_polish_modules(modules, industry=industry, description=description)
                except Exception as exc:
                    logger.warning("LLM polish failed, keep raw framework_explain: %s", exc)

            # 合并 evidence
            merged_evidence: dict[str, float] = {}
            for m in modules:
                for k, v in (m.get("evidence_for_diagnosis") or {}).items():
                    merged_evidence[k] = max(merged_evidence.get(k, 0.0), float(v))

            baseline_meta = {}
            for m in modules:
                meta = m.get("baseline_meta") or {}
                if meta:
                    baseline_meta = meta
                    break

            report = {
                "report_id": str(uuid4())[:12],
                "user_id": user_id,
                "plan_id": context.get("plan_id"),
                "project_id": project_id,
                "conversation_id": conversation_id,
                "industry": industry,
                "generated_at": _now_iso(),
                "modules": modules,
                "merged_evidence": merged_evidence,
                "inputs_snapshot": assumptions,
                "baseline_meta": baseline_meta,
                "status": "done",
            }
            self._save(user_id, report)
            self._set_status(user_id, "done", "生成完成")
            return report
        except Exception as exc:
            logger.exception("finance_report generate failed: %s", exc)
            self._set_status(user_id, "error", str(exc))
            raise

    def regenerate(
        self,
        user_id: str,
        plan_id: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        industry_hint: str = "",
    ) -> dict:
        return self.generate(
            user_id=user_id,
            plan_id=plan_id,
            project_id=project_id,
            conversation_id=conversation_id,
            industry_hint=industry_hint,
        )

    # ── 辅助 ──

    @staticmethod
    def _infer_stage(assumptions: dict, project_state: dict) -> str:
        if project_state.get("positive_unit_econ") and assumptions.get("monthly_price"):
            return "validated"
        if project_state.get("has_mvp") or assumptions.get("monthly_price"):
            return "structured"
        return "idea"

    def _llm_polish_modules(self, modules: list[dict], industry: str, description: str) -> None:
        """让 LLM 针对学生项目具体化 framework_explain。"""
        try:
            brief = description[:600] if description else "（项目描述缺失，按通用情况讲解）"
            for m in modules:
                raw_explain = m.get("framework_explain", "")
                outputs = m.get("outputs", {})
                resp = self.llm.chat_text(
                    system_prompt=(
                        "你是创业项目财务讲师。学生项目简述如下：\n"
                        f"{brief}\n\n"
                        f"行业：{industry}。请针对本学生项目把给定的「财务分析框架」讲清楚，"
                        "要求：1) 中文 2) 不超过 200 字 3) 先 1 句讲框架是什么；"
                        "然后结合学生项目数据说本次计算怎么算出来的；最后指出最值得他关注的 1 个数字。"
                        "不要用'亲爱的'/'同学'/'亲'这种开场。"
                    ),
                    user_prompt=(
                        f"框架原文：\n{raw_explain}\n\n"
                        f"本次模型输出数据：{json.dumps(outputs, ensure_ascii=False)[:800]}"
                    ),
                    temperature=0.3,
                )
                if isinstance(resp, str) and len(resp.strip()) > 40:
                    m["framework_explain"] = resp.strip() + "\n\n---\n原始讲解：\n" + raw_explain
        except Exception as exc:
            logger.warning("polish_modules inner: %s", exc)


__all__ = ["FinanceReportService"]
