"""直接调 finance_guard.scan_message（就是 main.py 里接线的那个），
模拟 5 段学生消息 + 预算面板两种来源，验证卡片产出与漏洞发现能力。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.services.finance_guard import scan_message, detect_triggers


def pretty(res: dict) -> None:
    if not res or not res.get("triggered"):
        hits = res.get("hits") if res else None
        print(f"   → 未触发（hits={hits}）—— 消息不含可抽取的财务假设，guard 静默")
        return
    print(f"   → 触发 ✓  命中类别: {res.get('hits')}  |  行业: {res.get('industry') or '(未指定)'}")
    for i, c in enumerate(res.get("cards") or [], 1):
        v = c.get("verdict") or {}
        mark = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(v.get("level"), "?")
        print(f"   {mark} [{i}] {c.get('title')}: {v.get('reason')}")
        outs = c.get("outputs") or {}
        # 只展示关键 4-6 项
        if outs:
            show = {}
            for k in ["ltv_cac_ratio", "ltv", "cac", "payback_period_months", "arpu",
                      "checks", "cost_per_beneficiary", "industry_range"]:
                if k in outs:
                    show[k] = outs[k]
            if show:
                print(f"        指标: {json.dumps(show, ensure_ascii=False)[:200]}")
        sug = c.get("suggestions") or []
        for s in sug[:2]:
            print(f"        建议 → {s}")
        missing = c.get("missing_inputs") or []
        if missing:
            print(f"        缺字段: {missing}")
    ev = res.get("evidence_for_diagnosis") or {}
    if ev:
        print(f"   [注入诊断的证据 H编号: 权重] {ev}")


def case(label: str, msg: str, history: list | None = None,
         budget: dict | None = None, industry: str = ""):
    print(f"\n━━━ {label}")
    print(f"   学生: {msg}")
    if budget:
        print(f"   预算面板: {budget}")
    print(f"   命中触发词: {detect_triggers(msg)}")
    res = scan_message(msg, history=history, budget_snapshot=budget, industry_hint=industry)
    pretty(res)


def main():
    print("=" * 70)
    print("  真实学生场景 · 财务守望钩子能力体检")
    print("  （相当于用 654321 账号在聊天里逐条发送；guard 是同一段代码）")
    print("=" * 70)

    # ===== 场景 1: 空想，没有数字 =====
    case(
        "场景1 空想（应该不触发）",
        "我想做一个帮大学生找自习搭子的 App，让更多人愿意自律。",
    )

    # ===== 场景 2: 离谱定价 =====
    case(
        "场景2 定价 299/月（教育行业明显偏高）",
        "我打算向大学生收月费 299 元，每月新增用户大概 1000 人，转化率 3%。",
        industry="教育",
    )

    # ===== 场景 3: 加上 CAC + 低留存 =====
    case(
        "场景3 CAC 500 / 留存 40% / 毛利未提（典型亏损）",
        "我们的获客主要靠抖音投流，CAC 大概是 500 元/付费用户。月留存 40% 左右。",
        history=[
            {"role": "user", "content": "之前说过定价 99 元/月"},
        ],
        industry="教育",
    )

    # ===== 场景 4: 只提市场，不含定价 =====
    case(
        "场景4 只说市场（不含价格 → pricing/unit_econ 均不触发）",
        "中国在校大学生 4000 万人，TAM 我觉得超过 1000 亿。",
        industry="教育",
    )

    # ===== 场景 5: 公益项目 =====
    case(
        "场景5 公益（用关键词 + 受益人成本）",
        "我们是公益项目，每服务一个留守儿童的成本是 320 元，想拿到企业捐赠。",
        industry="公益",
    )

    # ===== 场景 6: 预算面板有定价 + 文本没说定价 =====
    case(
        "场景6 文本没说价，但预算面板里填了 39 元 / CAC 800",
        "我们的获客成本太高了。",  # 触发词是 "获客"
        budget={
            "monthly_price": 39,
            "cac": 800,
            "gross_margin": 0.35,
            "monthly_retention": 0.5,
        },
        industry="教育",
    )

    # ===== 场景 7: 预算 vs 文本冲突（预算优先） =====
    case(
        "场景7 文本说 99，但预算面板里是 299（应以预算为准）",
        "我们定价 99 元/月",
        budget={"monthly_price": 299, "cac": 600},
        industry="教育",
    )

    # ===== 场景 8: SaaS 健康场景（全绿应不出卡） =====
    case(
        "场景8 SaaS 健康场景（月费 99, CAC 80, 留存 90%, 毛利 75%, 应全绿不打扰）",
        "我们是 B 端 SaaS，月费 99 元/月，CAC 约 80，月留存 90%，毛利 75%。",
        industry="SaaS",
    )

    print("\n" + "=" * 70)
    print("  结论：")
    print("  - 空想/无数字场景 → 不触发（避免骚扰）")
    print("  - 有可抽取的数字 → 按行业基线比对，红黄卡才出")
    print("  - 预算面板填的数据 优先于 聊天里的数字")
    print("  - 全绿场景 → 不出卡（避免 AI 自夸）")
    print("=" * 70)


if __name__ == "__main__":
    main()
