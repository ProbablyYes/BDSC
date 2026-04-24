# -*- coding: utf-8 -*-
"""final-01 财务测算专项对话回归脚本（走 /api/dialogue/turn 重量主链）。

6 轮覆盖：盈利模式 → 单位经济 → Runway → 敏感性 → 融资节奏 → 测算定稿
输出：regression_final01_finance_dialogue.json
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

API = "http://127.0.0.1:8037"
USER_ID = "99fed9ab-486c-4b22-8329-b3c6466e17d2"
PROJECT_ID = f"project-{USER_ID}"
STUDENT_ID = "1120230236"
MODE = "learning"
COMPETITION = ""

TURNS = [
    (
        "我想专门跟你聊一下我们项目的财务测算，把整个口径从头梳一遍。\n\n"
        "项目还是面向中小企业法务的 AI 合同审查 SaaS（LegalScan）。"
        "目标客户 20–300 人企业，纯订阅，定价基础版 299/月、企业版 999/月、旗舰版 1999/月。\n\n"
        "请你直接告诉我：纯订阅 SaaS 在我们这个体量下，财务测算应该从哪几条主线展开？"
        "我希望最后能产出一个能放进 BP 的『可校验』测算，不只是拍一个数字。"
    ),
    (
        "好，我先把单位经济的关键假设说出来，请你算并指出哪条最不靠谱：\n"
        "- ARPU：480 元/月（基础版 60% + 企业版 30% + 旗舰 10%）\n"
        "- 毛利率：78%\n"
        "- 月留存率：87%（样本只有 3 家试用客户 2 个月，样本很小）\n"
        "- CAC：650 元（按已花 3.9 万 / 60 lead × 转化 0.1 反推）\n"
        "- 目标第 6 个月稳定 50 个付费客户、月营收 5 万\n\n"
        "请：(1) 算 LTV、Payback、LTV/CAC；(2) 给 SaaS 行业基准对照；"
        "(3) 明确说哪条假设最经不起检验，需要补什么证据。"
    ),
    (
        "再看现金流和盈亏平衡：\n"
        "- 起始资金：天使 80 万已到账\n"
        "- 月固定成本：人力 7.2 万 + 办公服务器 0.5 万 + LLM API 0.8 万 ≈ 8.5 万/月\n"
        "- 单付费客户月变动成本：约 35 元\n"
        "- 月净增付费客户 8 家（新增 12 流失 4），月增长率 ~8%\n\n"
        "(1) 给我 24–36 个月现金流推演结论：什么时候用完钱、什么时候盈亏平衡？\n"
        "(2) 留出多少 runway 才算安全？现在最该改哪一条把 runway 拉长？\n"
        "(3) 直接给『结论 + 一句话原因』，不要只罗列公式。"
    ),
    (
        "现在做敏感性分析，跑三个情景并告诉我哪个变量是杠杆点：\n"
        "- 悲观：留存 80%、CAC 1100、月增长 4%\n"
        "- 现实：留存 87%、CAC 650、月增长 8%\n"
        "- 乐观：留存 92%、CAC 500、月增长 12%\n\n"
        "(a) 悲观情景下大概什么时候撑不住？\n"
        "(b) 留存、CAC、增长哪个对结果影响最大？\n"
        "(c) 据此给运营/产品团队设 2–3 条『财务护栏』KPI 红线。"
    ),
    (
        "再看融资节奏，请直接给判断：\n"
        "(1) 我们什么时候启动 Pre-A 合适？按 runway、月营收里程碑还是用户数？\n"
        "(2) 早期 SaaS 常见估值口径有几种？我们这个阶段 VC 大概用哪一种？给一个合理估值区间和它的假设。\n"
        "(3) 想把估值从 X 推到 1.5×X，Pre-A 之前最该做出哪 2–3 件事？\n\n"
        "提醒：我们是『正经做生意』的 B2B SaaS，不要把估值故事吹成 deeptech，请保持口径务实。"
    ),
    (
        "最后请帮我做一次『财务测算定稿』：\n"
        "(1) 把前 5 轮关键结论（LTV/CAC、Payback、Runway、盈亏平衡月、敏感性、融资时点、估值区间）"
        "整理成一张 8–12 行的『一页纸财务摘要』，能直接放进 BP 第 5 章。\n"
        "(2) 列一张『财务风险地图』：3–5 个最关键风险，每个写清楚"
        "『触发条件 / 早期信号 / 应对动作 / 责任人』。\n"
        "(3) 一句话『总编辑判断』：作为教练，你认为这个项目当前的财务结构能不能撑过 18 个月？"
        "如果不能，最致命的洞是什么？"
    ),
]

KEYWORDS = [
    "LTV", "CAC", "Payback", "回本", "毛利", "ARR", "ARPU",
    "Runway", "现金跑道", "盈亏平衡", "Breakeven",
    "敏感", "churn", "流失", "护栏", "融资", "估值",
]


def _post(path: str, payload: dict[str, Any], timeout: int = 360) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=API + path, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _short(text: str | None, limit: int = 260) -> str:
    if not text:
        return ""
    t = str(text).replace("\n", " ").strip()
    return t if len(t) <= limit else t[:limit] + "…"


def _summarize(idx: int, user_text: str, resp: dict[str, Any]) -> dict[str, Any]:
    diag = resp.get("diagnosis") or {}
    trace = resp.get("agent_trace") or {}
    fin_adv = trace.get("finance_advisory") or {}
    fin_auto = trace.get("finance_auto_apply") or {}
    msg = resp.get("assistant_message") or ""
    hits = [k for k in KEYWORDS if k.lower() in msg.lower()]

    return {
        "turn": idx,
        "user_preview": _short(user_text, 90),
        "assistant_excerpt": _short(msg, 380),
        "assistant_full": msg,
        "assistant_full_len": len(msg),
        "logical_project_id": resp.get("logical_project_id"),
        "conversation_id": resp.get("conversation_id"),
        "project_stage_v2": resp.get("project_stage_v2"),
        "overall_score": diag.get("overall_score"),
        "bottleneck": _short(diag.get("bottleneck"), 140),
        "triggered_rules": [r.get("id") for r in (diag.get("triggered_rules") or [])[:5]],
        "finance_advisory": {
            "triggered": fin_adv.get("triggered"),
            "primary_pattern": fin_adv.get("primary_pattern_label") or fin_adv.get("primary_pattern"),
            "tips": [_short(t.get("title") or t.get("message"), 120)
                     for t in (fin_adv.get("tips") or [])[:3]],
            "evidence_keys": list((fin_adv.get("evidence_for_diagnosis") or {}).keys()),
        } if fin_adv else None,
        "finance_auto_apply": {
            "applied_count": len(fin_auto.get("applied") or []),
            "stream_added": fin_auto.get("stream_added"),
            "primary_pattern": (fin_auto.get("signals") or {}).get("primary_pattern_label"),
            "summary": (fin_auto.get("signals") or {}).get("summary"),
        } if fin_auto else None,
        "finance_keywords_in_reply": hits,
    }


def main() -> int:
    print("=" * 80)
    print("finance-deep-dive  企业法务 SaaS · 财务测算专项 (6 轮)")
    print("=" * 80)
    conv_id: str | None = None
    rows: list[dict[str, Any]] = []
    t0 = time.time()
    for i, msg in enumerate(TURNS, 1):
        payload = {
            "project_id": PROJECT_ID,
            "student_id": STUDENT_ID,
            "message": msg,
            "conversation_id": conv_id,
            "mode": MODE,
            "competition_type": COMPETITION,
        }
        ts = time.time()
        try:
            resp = _post("/api/dialogue/turn", payload, timeout=360)
        except Exception as exc:
            print(f"  ! Turn {i} failed: {exc}")
            break
        dt = time.time() - ts
        if not conv_id:
            conv_id = resp.get("conversation_id")
        row = _summarize(i, msg, resp)
        row["latency_s"] = round(dt, 1)
        rows.append(row)
        adv = row["finance_advisory"]
        auto = row["finance_auto_apply"]
        adv_brief = f"adv=[{adv.get('primary_pattern')}, tips={len(adv.get('tips') or [])}]" if adv else "adv=None"
        auto_brief = f"auto=[applied={auto.get('applied_count')}, stream_added={auto.get('stream_added')}]" if auto else "auto=None"
        print(
            f"  Turn {i} ({dt:5.1f}s) len={row['assistant_full_len']:5d} score={row['overall_score']} "
            f"kw={len(row['finance_keywords_in_reply']):2d}/{len(KEYWORDS)}  {adv_brief}  {auto_brief}"
        )
        time.sleep(1.2)

    out = "regression_final01_finance_dialogue.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"finance-deep-dive": rows, "conversation_id": conv_id}, f, ensure_ascii=False, indent=2)
    print(f"\n>>> total {time.time() - t0:.1f}s, written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
