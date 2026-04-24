"""收入模式模板库（Revenue Pattern Library）。

替代旧的"用户数 × 单价 × 转化率"单一公式。每个项目的收入流可以挂任意一种
模板，每种模板有自己的字段集与计算公式，让"商务模型测算"真正贴合项目本身。

设计要点：
- 每个 Pattern 只描述"一条收入流"。一个项目可以同时挂多条不同模板的收入流
  （比如公益项目同时有"学校项目制收入" + "CSR 资助" + "C 端低价订阅"）。
- Pattern 字段使用动态 schema，前端按 schema 自动渲染输入控件。
- compute_monthly 永远返回月度营收（人民币元）；active_users 返回该流的"活跃载体数"
  （订阅是用户数，硬件是月销量，公益资助是受助人数），用于估算 variable_cost。
- 兼容老数据：老 stream 没有 pattern_key 时按 "subscription" 处理，老的
  monthly_users / price / conversion_rate 三个字段会自动映射到 inputs。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


def _f(x: Any, default: float = 0.0) -> float:
    """容错 float 转换。"""
    try:
        v = float(x or 0)
        return v if v == v else default  # NaN → default
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    field_type: str  # number | percent | integer | text
    default: float | str = 0.0
    unit: str = ""
    help: str = ""
    min_value: float | None = None
    max_value: float | None = None


@dataclass(frozen=True)
class RevenuePattern:
    key: str
    label: str
    description: str
    fields: tuple[FieldSpec, ...]
    key_levers: tuple[str, ...]                   # 决定胜负的 1-3 个字段 key
    compute_monthly: Callable[[dict[str, Any]], float]
    active_users: Callable[[dict[str, Any]], float]
    suit_for: tuple[str, ...] = field(default_factory=tuple)  # 适合什么类型项目（人话标签）
    track_hint: str = ""  # track_vector 推荐说明
    formula_explain: str = ""  # 公式人话解释，用于前端 tooltip


# ───────────────────── 模板定义 ─────────────────────

PATTERNS: dict[str, RevenuePattern] = {
    "subscription": RevenuePattern(
        key="subscription",
        label="C 端订阅 / 会员",
        description="用户按月/年付费，关键看付费用户规模与留存。",
        fields=(
            FieldSpec("monthly_users", "总注册或月活用户", "integer", 0, "人", "进入漏斗的总用户数（含未付费）"),
            FieldSpec("conversion_rate", "付费转化率", "percent", 0.05, "%", "活跃用户中转为付费的比例", 0, 1),
            FieldSpec("price", "月费 / ARPU", "number", 49, "元/月", "付费用户的月均收入"),
        ),
        key_levers=("conversion_rate", "monthly_users"),
        compute_monthly=lambda i: _f(i.get("monthly_users")) * _f(i.get("conversion_rate"), 1) * _f(i.get("price")),
        active_users=lambda i: _f(i.get("monthly_users")) * _f(i.get("conversion_rate"), 1),
        suit_for=("SaaS", "在线课程", "工具应用", "知识付费"),
        track_hint="偏商业（biz_public<0）+ 创业（innov_venture>0）的 C 端项目",
        formula_explain="月营收 = 月活用户 × 付费转化率 × 月费",
    ),

    "transaction": RevenuePattern(
        key="transaction",
        label="C 端交易 / 一次性消费",
        description="单次成交即结清，关键看单价与复购频次（也含一次性硬件销售）。",
        fields=(
            FieldSpec("monthly_buyers", "月购买人数", "integer", 0, "人"),
            FieldSpec("avg_order_value", "客单价", "number", 99, "元/单"),
            FieldSpec("orders_per_buyer", "人均月订单数", "number", 1.2, "单/人/月", "复购频次，1 表示无复购"),
        ),
        key_levers=("avg_order_value", "orders_per_buyer"),
        compute_monthly=lambda i: _f(i.get("monthly_buyers")) * _f(i.get("avg_order_value")) * _f(i.get("orders_per_buyer"), 1),
        active_users=lambda i: _f(i.get("monthly_buyers")),
        suit_for=("电商", "餐饮", "线下零售", "快消品", "一次性体验"),
        track_hint="商业 C 端、复购驱动的项目",
        formula_explain="月营收 = 月买家数 × 客单价 × 人均月订单数",
    ),

    "project_b2b": RevenuePattern(
        key="project_b2b",
        label="B 端项目制 / 服务采购",
        description="一份合同金额较大，按项目周期摊分。关键看新签合同数与续约率。",
        fields=(
            FieldSpec("contracts_per_month", "月新签合同数", "number", 0, "份/月", "可填 0.5 表示两月签 1 份"),
            FieldSpec("contract_value", "单合同金额", "number", 50000, "元/份"),
            FieldSpec("contract_duration_months", "服务周期", "integer", 6, "月", "合同金额按这么多个月摊分"),
            FieldSpec("renewal_rate", "续约率", "percent", 0.5, "%", "周期结束时续约比例"),
        ),
        key_levers=("contracts_per_month", "contract_value"),
        compute_monthly=lambda i: (
            _f(i.get("contracts_per_month")) * _f(i.get("contract_value"))
            / max(1.0, _f(i.get("contract_duration_months"), 1))
            * (1 + _f(i.get("renewal_rate"), 0))
        ),
        active_users=lambda i: _f(i.get("contracts_per_month")) * max(1.0, _f(i.get("contract_duration_months"), 1)),
        suit_for=("企业 SaaS 定制", "教育机构合作", "咨询服务", "政府采购"),
        track_hint="商业 B 端、合同驱动的项目（公益项目里的'学校采购'也走这里）",
        formula_explain="月营收 ≈ 月新签数 × 合同金额 ÷ 服务月数 × (1 + 续约率)",
    ),

    "platform_commission": RevenuePattern(
        key="platform_commission",
        label="平台撮合 / 佣金抽成",
        description="不直接售卖商品，靠 GMV 抽成。关键看 GMV 增速与佣金率。",
        fields=(
            FieldSpec("monthly_gmv", "月 GMV (成交额)", "number", 0, "元/月"),
            FieldSpec("commission_rate", "佣金率", "percent", 0.10, "%", "对成交额的抽成比例", 0, 1),
            FieldSpec("active_sellers", "活跃供给方数量", "integer", 0, "家", "用于变动成本估算"),
        ),
        key_levers=("monthly_gmv", "commission_rate"),
        compute_monthly=lambda i: _f(i.get("monthly_gmv")) * _f(i.get("commission_rate")),
        active_users=lambda i: _f(i.get("active_sellers")),
        suit_for=("交易平台", "二手撮合", "外卖配送", "技能匹配"),
        track_hint="平台型项目（多边市场）",
        formula_explain="月营收 = 月 GMV × 佣金率",
    ),

    "hardware_sales": RevenuePattern(
        key="hardware_sales",
        label="硬件 / 实体销售",
        description="销售有形产品，营收减去单位成本即毛利。关键看销量与毛利率。",
        fields=(
            FieldSpec("monthly_units", "月销量", "integer", 0, "台/件"),
            FieldSpec("unit_price", "出厂 / 零售价", "number", 999, "元/件"),
            FieldSpec("unit_cost", "单位 BOM 成本", "number", 600, "元/件", "原材料 + 制造成本"),
        ),
        key_levers=("monthly_units", "unit_price", "unit_cost"),
        compute_monthly=lambda i: _f(i.get("monthly_units")) * _f(i.get("unit_price")),
        active_users=lambda i: _f(i.get("monthly_units")),
        suit_for=("智能硬件", "消费电子", "实体产品", "材料销售"),
        track_hint="硬件创业，毛利率是命门（要同时把 unit_cost 填够）",
        formula_explain="月营收 = 月销量 × 单价（毛利 = 单价 - 单位成本，影响净利不影响营收）",
    ),

    "grant_funded": RevenuePattern(
        key="grant_funded",
        label="公益 · 政府/基金资助",
        description="不向受助方收费，资金来自专项资助或政府购买服务。关键看资助方留存与覆盖人数。",
        fields=(
            FieldSpec("active_grants", "在期资助项目数", "integer", 1, "个"),
            FieldSpec("grant_value_yearly", "单项目年度金额", "number", 100000, "元/年/项"),
            FieldSpec("renewal_rate", "年度续期概率", "percent", 0.6, "%", "影响 12 个月内是否还有这笔钱", 0, 1),
            FieldSpec("beneficiaries_served", "月触达受益人数", "integer", 0, "人/月", "用于变动成本估算与 SROI"),
        ),
        key_levers=("active_grants", "grant_value_yearly"),
        compute_monthly=lambda i: _f(i.get("active_grants")) * _f(i.get("grant_value_yearly")) / 12.0 * (0.5 + 0.5 * _f(i.get("renewal_rate"), 1)),
        active_users=lambda i: _f(i.get("beneficiaries_served")),
        suit_for=("公益项目", "社会创新", "政府购买服务", "教育公益"),
        track_hint="公益偏向（biz_public>0）+ 早期的项目",
        formula_explain="月营收 ≈ 在期项目数 × 年度金额 ÷ 12 × (0.5 + 0.5 × 续期概率)",
    ),

    "donation": RevenuePattern(
        key="donation",
        label="公益 · 捐赠 / CSR 赞助",
        description="来自企业 CSR 或个人捐赠的不固定收入，关键看月活捐赠人 × 平均金额。",
        fields=(
            FieldSpec("monthly_donors", "月活捐赠方", "integer", 0, "个"),
            FieldSpec("avg_donation", "平均捐赠金额", "number", 5000, "元/次/方"),
            FieldSpec("donor_retention", "捐赠方留存率", "percent", 0.4, "%", "下月还会捐的比例", 0, 1),
        ),
        key_levers=("monthly_donors", "avg_donation"),
        compute_monthly=lambda i: _f(i.get("monthly_donors")) * _f(i.get("avg_donation")),
        active_users=lambda i: _f(i.get("monthly_donors")),
        suit_for=("公益众筹", "CSR 合作", "公益商品义卖"),
        track_hint="公益偏向、需要持续维护捐赠方关系的项目",
        formula_explain="月营收 = 月活捐赠方 × 平均捐赠金额（留存率影响后续月数）",
    ),
}


# ───────────────────── 兼容老数据 ─────────────────────

def _legacy_to_subscription(s: dict[str, Any]) -> dict[str, Any]:
    """老 stream（只有 monthly_users / price / conversion_rate）补齐成 subscription pattern。"""
    inputs = dict(s.get("inputs") or {})
    if "monthly_users" not in inputs and "monthly_users" in s:
        inputs["monthly_users"] = s.get("monthly_users")
    if "price" not in inputs and "price" in s:
        inputs["price"] = s.get("price")
    if "conversion_rate" not in inputs and "conversion_rate" in s:
        inputs["conversion_rate"] = s.get("conversion_rate")
    return inputs


def normalize_stream(stream: dict[str, Any]) -> dict[str, Any]:
    """归一化一条 revenue_stream：补齐 pattern_key + inputs，且不破坏老字段。"""
    if not isinstance(stream, dict):
        return {"name": "", "pattern_key": "subscription", "inputs": {}, "monthly_revenue": 0}
    pattern_key = stream.get("pattern_key") or "subscription"
    if pattern_key not in PATTERNS:
        pattern_key = "subscription"
    if pattern_key == "subscription":
        inputs = _legacy_to_subscription(stream)
    else:
        inputs = dict(stream.get("inputs") or {})
    stream["pattern_key"] = pattern_key
    stream["inputs"] = inputs
    return stream


def compute_stream_monthly_revenue(stream: dict[str, Any]) -> tuple[float, float]:
    """根据 pattern 计算单条流的 (月营收, 该流的活跃载体数)。失败兜底为 (0, 0)。"""
    stream = normalize_stream(stream)
    pattern = PATTERNS.get(stream["pattern_key"], PATTERNS["subscription"])
    inputs = stream["inputs"]
    try:
        revenue = max(0.0, pattern.compute_monthly(inputs))
    except Exception:
        revenue = 0.0
    try:
        users = max(0.0, pattern.active_users(inputs))
    except Exception:
        users = 0.0
    return revenue, users


def list_pattern_metadata() -> list[dict[str, Any]]:
    """前端 GET 接口需要的模板元信息。"""
    out: list[dict[str, Any]] = []
    for p in PATTERNS.values():
        out.append({
            "key": p.key,
            "label": p.label,
            "description": p.description,
            "fields": [
                {
                    "key": fs.key,
                    "label": fs.label,
                    "type": fs.field_type,
                    "default": fs.default,
                    "unit": fs.unit,
                    "help": fs.help,
                    "min": fs.min_value,
                    "max": fs.max_value,
                }
                for fs in p.fields
            ],
            "key_levers": list(p.key_levers),
            "suit_for": list(p.suit_for),
            "track_hint": p.track_hint,
            "formula_explain": p.formula_explain,
        })
    return out


def recommend_patterns(track_vector: dict[str, Any] | None) -> list[str]:
    """根据 track_vector 推荐 1-3 个最合适的 pattern key。"""
    tv = track_vector if isinstance(track_vector, dict) else {}
    iv = _f(tv.get("innov_venture"))   # >0 偏创业；<0 偏创新（往往是 To B/技术驱动）
    bp = _f(tv.get("biz_public"))      # >0 偏公益；<0 偏商业

    recs: list[str] = []
    if bp >= 0.25:        # 公益偏向
        recs.extend(["grant_funded", "donation"])
        if iv >= 0.0:
            recs.append("project_b2b")  # 公益创业项目通常配合学校采购
    elif bp <= -0.25:    # 商业偏向
        if iv >= 0.2:
            recs.extend(["subscription", "transaction"])
        elif iv <= -0.2:
            recs.extend(["project_b2b", "subscription"])
        else:
            recs.extend(["subscription", "transaction", "project_b2b"])
    else:                 # 中性
        recs.extend(["subscription", "project_b2b"])

    # 去重保序
    seen = set()
    uniq = []
    for k in recs:
        if k not in seen and k in PATTERNS:
            seen.add(k)
            uniq.append(k)
    return uniq[:3]


def derive_key_levers_summary(streams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从已有 streams 反推"项目命门"，给学生一个高亮提示。"""
    if not streams:
        return []
    stats: dict[str, dict[str, Any]] = {}
    for s in streams:
        s = normalize_stream(s)
        pattern = PATTERNS.get(s["pattern_key"]) or PATTERNS["subscription"]
        revenue, _ = compute_stream_monthly_revenue(s)
        for lever in pattern.key_levers:
            stats.setdefault(lever, {
                "field": lever,
                "label": next((fs.label for fs in pattern.fields if fs.key == lever), lever),
                "patterns": set(),
                "weighted_revenue": 0.0,
            })
            stats[lever]["patterns"].add(pattern.label)
            stats[lever]["weighted_revenue"] += revenue
    out = []
    for v in stats.values():
        out.append({
            "field": v["field"],
            "label": v["label"],
            "from_patterns": sorted(v["patterns"]),
            "weighted_revenue": round(v["weighted_revenue"], 2),
        })
    out.sort(key=lambda x: -x["weighted_revenue"])
    return out[:5]


__all__ = [
    "PATTERNS",
    "normalize_stream",
    "compute_stream_monthly_revenue",
    "list_pattern_metadata",
    "recommend_patterns",
    "derive_key_levers_summary",
]
