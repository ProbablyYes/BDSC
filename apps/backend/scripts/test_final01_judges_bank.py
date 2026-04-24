# -*- coding: utf-8 -*-
"""答辩模式 · 评委角色卡库回归脚本（可选执行）

目标
----
以 final-01 账号在「项目教练 / 竞赛模式」下连发 4 轮，每轮显式切换评委角色，
断言后端 ``agent_trace.competition.active_judge`` 在每一轮真的随消息切换到了期望角色。

使用方式
    python -u apps/backend/scripts/test_final01_judges_bank.py

输出
    控制台简表 + 详细 JSON 写入 regression_final01_judges.json
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

import urllib.request
import urllib.error

API = "http://127.0.0.1:8037"
USER_ID = "99fed9ab-486c-4b22-8329-b3c6466e17d2"  # final-01
PROJECT_ID = f"project-{USER_ID}"
STUDENT_ID = "1120230236"

MODE = "competition"
COMPETITION_TYPE = "互联网+"

# 4 轮，每轮显式切到一个评委
TURNS: list[dict[str, Any]] = [
    {
        "expected_judge": "aggressive_vc",
        "message": (
            "请扮演一位激进型 VC 来追问我们的项目。我们做的是 LegalScan，"
            "AI 合同审查 SaaS，月费 999，目前有 3 家试用、1 家明确续费意向。"
            "请按 VC 视角直接给我最狠的几个问题。"
        ),
    },
    {
        "expected_judge": "tech_lead",
        "message": (
            "现在请切到技术流专家的视角追问我们。我们底层用了百万级中文合同语料"
            "微调的 7B 模型，在自建测试集上 F1=0.87。请重点问技术深度和工程实现。"
        ),
    },
    {
        "expected_judge": "conservative_banker",
        "message": (
            "现在请用保守型银行家的口吻追问。我们目前一年营收预计 60 万，烧钱 100 万，"
            "希望能拿一笔过桥贷。请直接挑刺现金流和还款能力。"
        ),
    },
    {
        "expected_judge": "policy_compliance_officer",
        "message": (
            "最后请切换到政策合规官视角。我们处理的是企业合同，里面会涉及保密协议、"
            "用工合同等敏感数据。请按合规视角直接追问。"
        ),
    },
]


def _post(path: str, payload: dict[str, Any], timeout: int = 300) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=API + path,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _short(text: str | None, limit: int = 220) -> str:
    if not text:
        return ""
    t = str(text).replace("\n", " ").strip()
    return t if len(t) <= limit else t[:limit] + "…"


def main() -> int:
    rows: list[dict[str, Any]] = []
    conv_id: str | None = None
    pass_count = 0
    overall_t0 = time.time()
    print(f"\n{'=' * 76}\n答辩模式 · 评委角色卡库回归（mode={MODE}, comp={COMPETITION_TYPE}）\n{'=' * 76}")
    for i, turn in enumerate(TURNS, 1):
        payload = {
            "project_id": PROJECT_ID,
            "student_id": STUDENT_ID,
            "message": turn["message"],
            "conversation_id": conv_id,
            "mode": MODE,
            "competition_type": COMPETITION_TYPE,
        }
        t0 = time.time()
        try:
            resp = _post("/api/dialogue/turn", payload, timeout=300)
        except urllib.error.URLError as exc:
            print(f"  ! Turn {i} 网络/超时: {exc}")
            return 1
        except Exception as exc:
            print(f"  ! Turn {i} 失败: {exc}")
            return 1
        dt = time.time() - t0
        if not conv_id:
            conv_id = resp.get("conversation_id")

        trace = resp.get("agent_trace") or {}
        comp = trace.get("competition") or {}
        active_judge = comp.get("active_judge") or comp.get("active_judge_id") or ""
        ok = active_judge == turn["expected_judge"]
        if ok:
            pass_count += 1

        row = {
            "turn": i,
            "expected_judge": turn["expected_judge"],
            "active_judge": active_judge,
            "passed": ok,
            "latency_s": round(dt, 1),
            "user_text_preview": _short(turn["message"], 80),
            "assistant_excerpt": _short(resp.get("assistant_message"), 220),
        }
        rows.append(row)
        flag = "✓" if ok else "✗"
        print(
            f"  Turn {i} ({dt:5.1f}s) {flag} expected={turn['expected_judge']:<26} "
            f"active={active_judge or '<empty>'}"
        )
        time.sleep(1.5)

    out_path = "regression_final01_judges.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"rows": rows, "summary": {"total": len(rows), "passed": pass_count}}, f, ensure_ascii=False, indent=2)
    total_dt = time.time() - overall_t0
    print(
        f"\n>>> 通过 {pass_count}/{len(rows)} | 总耗时 {total_dt:.1f}s | "
        f"详细结果已写入 {out_path}"
    )
    return 0 if pass_count == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
