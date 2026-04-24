# -*- coding: utf-8 -*-
"""追问策略库 · 表达风格层（语气变奏）回归脚本（可选执行）

目标
----
以 final-01 账号在「项目教练」模式下连发 4 轮，前两轮要求"严肃一点"、
后两轮要求"幽默一点"，断言：
  1) 后端 ``agent_trace.preferred_tone`` 在每一轮真的随消息切换；
  2) ``agent_trace.tone_origin`` 标明这一轮 tone 是 explicit / sticky / forced_*；
  3) 同一个项目在不同 tone 下，``guiding_questions`` 文本风格肉眼可见地不同。

使用方式
    python -u apps/backend/scripts/test_final01_tone_library.py

输出
    控制台简表 + 详细 JSON 写入 regression_final01_tone.json
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

MODE = "learning"
COMPETITION_TYPE = ""

PROJECT_BRIEF = (
    "我们做的是 LegalScan，AI 合同审查 SaaS，月费 999/月，目前 3 家试用、1 家明确续费意向。"
    "我们觉得没有真正的竞争对手，市场只要 1% 就够我们活下去。"
)

# 4 轮：前两轮 strict，后两轮 humorous
TURNS: list[dict[str, Any]] = [
    {
        "expected_tone": "strict",
        "message": (
            f"{PROJECT_BRIEF}\n\n"
            "请你严肃一点，像审计员那样直接挑刺，把我们最薄的那块前提拎出来追问。"
        ),
    },
    {
        "expected_tone": "strict",
        "message": (
            "继续保持严肃口吻。我们刚说了「只要拿到 1% 市场就够我们活下去」，请你按这个语气追问。"
        ),
    },
    {
        "expected_tone": "humorous",
        "message": (
            "现在请你幽默一点，别那么严肃，可以用打比方和反讽，但别伤我自尊。"
            "继续追问我们项目的真正薄弱点。"
        ),
    },
    {
        "expected_tone": "humorous",
        "message": (
            "保持幽默风格再问一轮。我们还说了「没有竞争对手」，你怎么吐槽这句话？"
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


def _short(text: str | None, limit: int = 240) -> str:
    if not text:
        return ""
    t = str(text).replace("\n", " ").strip()
    return t if len(t) <= limit else t[:limit] + "…"


def _extract_guiding_questions(resp: dict[str, Any]) -> list[str]:
    """从 agent_trace 里挖出 coach 的 guiding_questions（兼容多种字段命名）。"""
    trace = resp.get("agent_trace") or {}
    # 1) 直接挂在 trace 上
    direct = trace.get("guiding_questions")
    if isinstance(direct, list):
        return [str(x).strip() for x in direct if str(x).strip()]
    # 2) coach.coach_json
    for key in ("coach", "coach_response", "advisor"):
        c = trace.get(key)
        if isinstance(c, dict):
            gq = c.get("guiding_questions")
            if isinstance(gq, list) and gq:
                return [str(x).strip() for x in gq if str(x).strip()]
    # 3) 从 agent_responses 里找
    for ag in trace.get("agent_responses") or []:
        if isinstance(ag, dict):
            gq = ag.get("guiding_questions")
            if isinstance(gq, list) and gq:
                return [str(x).strip() for x in gq if str(x).strip()]
    # 4) pressure_test_trace.generated_question 也可作为兜底信号
    pt = trace.get("pressure_test_trace") or {}
    gq = pt.get("generated_question")
    return [str(gq).strip()] if gq else []


def main() -> int:
    rows: list[dict[str, Any]] = []
    conv_id: str | None = None
    pass_count = 0
    overall_t0 = time.time()
    print(f"\n{'=' * 76}\n追问策略库 · 表达风格层回归（mode={MODE}）\n{'=' * 76}")
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
        active_tone = (
            trace.get("preferred_tone")
            or (trace.get("competition") or {}).get("preferred_tone")
            or ""
        )
        tone_origin = (
            trace.get("tone_origin")
            or (trace.get("competition") or {}).get("tone_origin")
            or ""
        )

        # forced_strict / forced_warm 也算"实际生效 tone"对齐成功（安全闸门覆盖）
        ok = (active_tone == turn["expected_tone"]) or (
            turn["expected_tone"] == "strict" and tone_origin == "forced_strict"
        )
        if ok:
            pass_count += 1

        guiding_questions = _extract_guiding_questions(resp)

        row = {
            "turn": i,
            "expected_tone": turn["expected_tone"],
            "active_tone": active_tone,
            "tone_origin": tone_origin,
            "passed": ok,
            "latency_s": round(dt, 1),
            "user_text_preview": _short(turn["message"], 80),
            "assistant_excerpt": _short(resp.get("assistant_message"), 240),
            "guiding_questions": guiding_questions[:4],
        }
        rows.append(row)
        flag = "✓" if ok else "✗"
        print(
            f"  Turn {i} ({dt:5.1f}s) {flag} expected={turn['expected_tone']:<9} "
            f"active={active_tone or '<empty>':<9} origin={tone_origin or '<empty>'}"
        )
        for q in guiding_questions[:2]:
            print(f"      Q: {_short(q, 120)}")
        time.sleep(1.5)

    out_path = "regression_final01_tone.json"
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
