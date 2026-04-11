"""
BudgetStorage — JSON-file-based persistence for budget plans.
Storage layout: data/budgets/{user_id}/{plan_id}.json
Each user can have multiple plans, each identified by a unique plan_id.
"""

import json, copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

BJ_TZ = timezone(timedelta(hours=8))


def _now_iso() -> str:
    return datetime.now(BJ_TZ).isoformat()


# ── Purpose-specific templates ──────────────────────────────────────

PURPOSE_META = {
    "quick": {
        "label": "快速估算",
        "desc": "只需几分钟，快速评估项目所需资金",
        "visible_tabs": ["cost"],
    },
    "competition": {
        "label": "比赛预算",
        "desc": "针对创新创业大赛，含差旅/材料/赛程阶段",
        "visible_tabs": ["cost", "comp", "fund"],
    },
    "business": {
        "label": "商业计划",
        "desc": "完整商业计划书级别，含收入模型和情景分析",
        "visible_tabs": ["cost", "biz", "comp", "compare", "fund"],
    },
    "coursework": {
        "label": "课程作业",
        "desc": "适合课程要求的精简版财务规划",
        "visible_tabs": ["cost", "biz", "compare"],
    },
}

DEFAULT_COST_CATEGORIES_QUICK = [
    {"name": "技术开发", "items": [
        {"name": "云服务器", "unit_price": 0, "quantity": 1, "total": 0, "note": "", "cost_type": "monthly"},
        {"name": "域名", "unit_price": 0, "quantity": 1, "total": 0, "note": "", "cost_type": "once"},
        {"name": "API / 模型调用", "unit_price": 0, "quantity": 1, "total": 0, "note": "", "cost_type": "monthly"},
    ]},
    {"name": "运营推广", "items": [
        {"name": "线上推广", "unit_price": 0, "quantity": 1, "total": 0, "note": "", "cost_type": "once"},
    ]},
    {"name": "其他", "items": []},
]

DEFAULT_COST_CATEGORIES_FULL = [
    {"name": "技术开发", "items": [
        {"name": "云服务器", "unit_price": 0, "quantity": 12, "total": 0, "note": "按月计费×12", "cost_type": "monthly"},
        {"name": "域名", "unit_price": 0, "quantity": 1, "total": 0, "note": "", "cost_type": "once"},
        {"name": "API / 模型调用", "unit_price": 0, "quantity": 1, "total": 0, "note": "", "cost_type": "monthly"},
        {"name": "开发工具 / 许可证", "unit_price": 0, "quantity": 1, "total": 0, "note": "", "cost_type": "once"},
    ]},
    {"name": "运营推广", "items": [
        {"name": "线上推广", "unit_price": 0, "quantity": 1, "total": 0, "note": "", "cost_type": "once"},
        {"name": "线下活动", "unit_price": 0, "quantity": 1, "total": 0, "note": "", "cost_type": "once"},
        {"name": "内容制作", "unit_price": 0, "quantity": 1, "total": 0, "note": "", "cost_type": "once"},
    ]},
    {"name": "人力成本", "items": [
        {"name": "兼职开发", "unit_price": 0, "quantity": 1, "total": 0, "note": "", "cost_type": "monthly"},
        {"name": "设计外包", "unit_price": 0, "quantity": 1, "total": 0, "note": "", "cost_type": "once"},
    ]},
    {"name": "其他", "items": []},
]

DEFAULT_COMPETITION_ITEMS = [
    {"name": "参赛报名费", "amount": 0, "note": ""},
    {"name": "差旅交通", "amount": 0, "note": ""},
    {"name": "住宿", "amount": 0, "note": ""},
    {"name": "材料打印/展板", "amount": 0, "note": ""},
    {"name": "原型开发费", "amount": 0, "note": ""},
    {"name": "样品制作", "amount": 0, "note": ""},
]

DEFAULT_COMP_STAGES = [
    {"name": "筹备期", "items": []},
    {"name": "初赛", "items": []},
    {"name": "复赛", "items": []},
    {"name": "决赛", "items": []},
]

DEFAULT_FUNDING_SOURCES = [
    {"name": "自筹", "amount": 0, "note": ""},
    {"name": "学校资助", "amount": 0, "note": ""},
    {"name": "企业赞助", "amount": 0, "note": ""},
    {"name": "赛事奖金", "amount": 0, "note": ""},
]

DEFAULT_SCENARIO_MODELS = {
    "conservative": {
        "label": "悲观",
        "revenue_multiplier": 0.75,
        "conversion_multiplier": 0.85,
        "growth_rate_monthly": 0.05,
        "fixed_costs_monthly": 0,
        "variable_cost_per_user": 0,
        "note": "更保守地估计增长与转化，适合答辩时说明风险边界。",
    },
    "baseline": {
        "label": "基准",
        "revenue_multiplier": 1.0,
        "conversion_multiplier": 1.0,
        "growth_rate_monthly": 0.1,
        "fixed_costs_monthly": 0,
        "variable_cost_per_user": 0,
        "note": "当前最可信的执行版本，用于常规预算讨论。",
    },
    "optimistic": {
        "label": "乐观",
        "revenue_multiplier": 1.25,
        "conversion_multiplier": 1.15,
        "growth_rate_monthly": 0.18,
        "fixed_costs_monthly": 0,
        "variable_cost_per_user": 0,
        "note": "假设推广与口碑扩散顺利，用于展示潜在上限。",
    },
}


def _empty_plan(plan_id: str, user_id: str, name: str, purpose: str) -> dict:
    is_full = purpose in ("business", "coursework")
    cats = copy.deepcopy(DEFAULT_COST_CATEGORIES_FULL if is_full else DEFAULT_COST_CATEGORIES_QUICK)
    now = _now_iso()
    return {
        "plan_id": plan_id,
        "user_id": user_id,
        "name": name,
        "purpose": purpose,
        "visible_tabs": PURPOSE_META.get(purpose, PURPOSE_META["business"])["visible_tabs"],
        "version": 1,
        "currency": "CNY",
        "created_at": now,
        "updated_at": now,
        "project_costs": {"categories": cats},
        "business_finance": {
            "revenue_streams": [],
            "fixed_costs_monthly": 0,
            "variable_cost_per_user": 0,
            "growth_rate_monthly": 0.1,
            "months_to_breakeven": None,
            "cash_flow_projection": [],
            "scenario_models": copy.deepcopy(DEFAULT_SCENARIO_MODELS),
            "scenario_results": {},
        },
        "competition_budget": {
            "items": copy.deepcopy(DEFAULT_COMPETITION_ITEMS),
            "stages": copy.deepcopy(DEFAULT_COMP_STAGES),
            "funding_sources": copy.deepcopy(DEFAULT_FUNDING_SOURCES),
        },
        "funding_plan": {
            "startup_capital_needed": 0,
            "sources": [],
            "monthly_gap": [],
            "fundraising_notes": "",
        },
        "ai_suggestions": [],
        "summary": {},
    }


class BudgetStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _user_dir(self, user_id: str) -> Path:
        d = self.root / user_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _file(self, user_id: str, plan_id: str) -> Path:
        return self._user_dir(user_id) / f"{plan_id}.json"

    # ── CRUD ──

    def list_plans(self, user_id: str) -> list[dict]:
        d = self._user_dir(user_id)
        plans = []
        for f in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                plans.append({
                    "plan_id": data.get("plan_id", f.stem),
                    "name": data.get("name", "未命名"),
                    "purpose": data.get("purpose", "business"),
                    "updated_at": data.get("updated_at", ""),
                    "summary": data.get("summary", {}),
                })
            except Exception:
                pass
        return plans

    def create_plan(self, user_id: str, name: str, purpose: str = "business") -> dict:
        plan_id = str(uuid4())[:8]
        data = _empty_plan(plan_id, user_id, name, purpose)
        data = BudgetStorage.compute_cash_flow(data)
        self._file(user_id, plan_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return data

    def load(self, user_id: str, plan_id: str) -> dict | None:
        f = self._file(user_id, plan_id)
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
        return None

    def save(self, user_id: str, plan_id: str, data: dict) -> dict:
        data["updated_at"] = _now_iso()
        data.setdefault("plan_id", plan_id)
        data.setdefault("user_id", user_id)
        self._file(user_id, plan_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return data

    def delete_plan(self, user_id: str, plan_id: str) -> bool:
        f = self._file(user_id, plan_id)
        if f.exists():
            f.unlink()
            return True
        return False

    # ── Legacy compat: load by old project_id (flat file) ──

    def load_legacy(self, project_id: str) -> dict | None:
        f = self.root / f"{project_id}.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
        return None

    # ── Compute ──

    @staticmethod
    def compute_cash_flow(budget: dict) -> dict:
        """Recalculate derived fields: totals, breakeven, 12-month projection."""
        biz = budget.get("business_finance") or {}
        streams = biz.get("revenue_streams") or []
        fixed = float(biz.get("fixed_costs_monthly") or 0)
        var_cost = float(biz.get("variable_cost_per_user") or 0)
        growth = float(biz.get("growth_rate_monthly") or 0.1)
        scenario_models = biz.get("scenario_models") or {}

        base_revenue = 0.0
        base_users = 0
        for s in streams:
            mu = float(s.get("monthly_users") or 0)
            price = float(s.get("price") or 0)
            conv = float(s.get("conversion_rate") or 1)
            mr = mu * price * conv
            s["monthly_revenue"] = round(mr, 2)
            base_revenue += mr
            base_users += int(mu)

        def _simulate(
            revenue_multiplier: float,
            conversion_multiplier: float,
            growth_rate_value: float,
            fixed_cost_value: float,
            variable_cost_value: float,
        ) -> dict:
            projection = []
            cumulative = 0.0
            breakeven_month = None
            revenue_base = base_revenue * revenue_multiplier * conversion_multiplier
            users_base = max(0, int(base_users * conversion_multiplier))
            for m in range(1, 13):
                factor = (1 + growth_rate_value) ** (m - 1) if growth_rate_value else 1
                rev = round(revenue_base * factor, 2)
                users_m = max(0, int(users_base * factor))
                cost = round(fixed_cost_value + variable_cost_value * users_m, 2)
                net = round(rev - cost, 2)
                cumulative = round(cumulative + net, 2)
                projection.append({
                    "month": m, "revenue": rev, "cost": cost,
                    "net": net, "cumulative": cumulative,
                })
                if breakeven_month is None and cumulative >= 0 and m > 1:
                    breakeven_month = m
            annual_revenue = round(sum(p["revenue"] for p in projection), 2)
            annual_cost = round(sum(p["cost"] for p in projection), 2)
            annual_net = round(sum(p["net"] for p in projection), 2)
            return {
                "cash_flow_projection": projection,
                "months_to_breakeven": breakeven_month,
                "annual_revenue": annual_revenue,
                "annual_cost": annual_cost,
                "annual_net": annual_net,
                "monthly_revenue_base": round(revenue_base, 2),
            }

        merged_models: dict[str, dict] = {}
        for key, default in DEFAULT_SCENARIO_MODELS.items():
            incoming = scenario_models.get(key) or {}
            merged_models[key] = {
                **default, **incoming,
                "fixed_costs_monthly": float(
                    incoming.get("fixed_costs_monthly", fixed if key == "baseline" else default["fixed_costs_monthly"]) or 0
                ),
                "variable_cost_per_user": float(
                    incoming.get("variable_cost_per_user", var_cost if key == "baseline" else default["variable_cost_per_user"]) or 0
                ),
                "growth_rate_monthly": float(
                    incoming.get("growth_rate_monthly", growth if key == "baseline" else default["growth_rate_monthly"]) or 0
                ),
                "revenue_multiplier": float(incoming.get("revenue_multiplier", default["revenue_multiplier"]) or 0),
                "conversion_multiplier": float(incoming.get("conversion_multiplier", default["conversion_multiplier"]) or 0),
            }

        scenario_results = {
            key: _simulate(
                revenue_multiplier=model["revenue_multiplier"],
                conversion_multiplier=model["conversion_multiplier"],
                growth_rate_value=model["growth_rate_monthly"],
                fixed_cost_value=model["fixed_costs_monthly"],
                variable_cost_value=model["variable_cost_per_user"],
            )
            for key, model in merged_models.items()
        }

        baseline_result = scenario_results["baseline"]
        biz["cash_flow_projection"] = baseline_result["cash_flow_projection"]
        biz["months_to_breakeven"] = baseline_result["months_to_breakeven"]
        biz["scenario_models"] = merged_models
        biz["scenario_results"] = scenario_results
        budget["business_finance"] = biz

        cats = (budget.get("project_costs") or {}).get("categories") or []
        cost_total = 0.0
        for cat in cats:
            for item in cat.get("items", []):
                item["total"] = round(
                    float(item.get("unit_price") or 0) * float(item.get("quantity") or 0), 2
                )
                cost_total += float(item.get("total") or 0)

        comp_items = (budget.get("competition_budget") or {}).get("items") or []
        competition_total = 0.0
        for item in comp_items:
            item["amount"] = round(float(item.get("amount") or 0), 2)
            competition_total += float(item.get("amount") or 0)

        total_investment = round(cost_total + competition_total, 2)
        baseline_monthly_revenue = baseline_result["monthly_revenue_base"]
        funding_gap = round(max(0.0, total_investment - baseline_result["annual_net"]), 2)
        health_score = 82
        if baseline_monthly_revenue <= 0:
            health_score -= 28
        if baseline_result["months_to_breakeven"] is None:
            health_score -= 18
        elif baseline_result["months_to_breakeven"] > 9:
            health_score -= 10
        if funding_gap > total_investment * 0.6 and total_investment > 0:
            health_score -= 12

        budget["summary"] = {
            "project_cost_total": round(cost_total, 2),
            "competition_cost_total": round(competition_total, 2),
            "total_investment": total_investment,
            "baseline_monthly_revenue": round(baseline_monthly_revenue, 2),
            "baseline_annual_net": baseline_result["annual_net"],
            "funding_gap": funding_gap,
            "health_score": max(0, min(100, int(health_score))),
            "breakeven_fastest": scenario_results["optimistic"]["months_to_breakeven"],
            "breakeven_baseline": baseline_result["months_to_breakeven"],
            "breakeven_slowest": scenario_results["conservative"]["months_to_breakeven"],
        }

        return budget
