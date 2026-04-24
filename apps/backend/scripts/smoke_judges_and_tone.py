# -*- coding: utf-8 -*-
"""答辩评委 + 追问语气 联合冒烟脚本（final-01 账号，6 轮极简）

- Part 1（3 轮）：分别切到激进型 VC / 技术流专家 / 保守型银行家，断言 active_judge
- Part 2（3 轮）：分别切到 strict / humorous / warm，断言 preferred_tone

输出：控制台简表 + smoke_judges_and_tone.json
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

PART1: list[dict[str, Any]] = [
    {
        "expected_judge": "aggressive_vc",
        "mode": "competition",
        "competition_type": "internet_plus",
        "message": (
            "请扮演一位激进型 VC 来追问我们的项目。我们做的是 LegalScan，"
            "AI 合同审查 SaaS，月费 999，目前 3 家试用、1 家明确续费。请用 VC 视角直接给我最狠的几个问题。"
        ),
    },
    {
        "expected_judge": "tech_lead",
        "mode": "competition",
        "competition_type": "internet_plus",
        "message": (
            "请切到技术流专家视角追问。我们底层用了百万级中文合同语料微调的 7B 模型，自建测试集 F1=0.87。"
            "请重点问技术深度和工程实现。"
        ),
    },
    {
        "expected_judge": "conservative_banker",
        "mode": "competition",
        "competition_type": "internet_plus",
        "message": (
            "请用保守型银行家的口吻追问。我们一年营收预计 60 万，烧钱 100 万，"
            "希望能拿一笔过桥贷。请直接挑刺现金流和还款能力。"
        ),
    },
]

PART2: list[dict[str, Any]] = [
    {
        "expected_tone": "strict",
        "mode": "learning",
        "competition_type": "",
        "message": (
            "我们做 LegalScan AI 合同审查 SaaS，自我感觉没有竞争对手，市场只要 1% 就够活。"
            "请你严肃一点，像审计员那样直接挑刺，把我们最薄的那块前提拎出来追问。"
        ),
    },
    {
        "expected_tone": "humorous",
        "mode": "learning",
        "competition_type": "",
        "message": (
            "现在请你幽默一点，别那么严肃，可以用打比方和反讽，但别伤我自尊。继续追问我们项目的真正薄弱点。"
        ),
    },
    {
        "expected_tone": "warm",
        "mode": "learning",
        "competition_type": "",
        "message": (
            "现在请用温和共情的语气追问，先肯定我们已经做的部分，再帮我们看下一步往哪走。"
        ),
    },
]


def _post(path: str, payload: dict[str, Any], timeout: int = 300) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=API + path, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _short(text: str | None, limit: int = 220) -> str:
    if not text:
        return ""
    t = str(text).replace("\n", " ").strip()
    return t if len(t) <= limit else t[:limit] + "…"


def _run_part(title: str, turns: list[dict[str, Any]], expect_key: str, trace_keys: list[str]) -> tuple[list[dict], int]:
    print(f"\n{'=' * 76}\n{title}\n{'=' * 76}")
    rows: list[dict[str, Any]] = []
    conv_id: str | None = None
    pass_count = 0
    for i, turn in enumerate(turns, 1):
        payload = {
            "project_id": PROJECT_ID,
            "student_id": STUDENT_ID,
            "message": turn["message"],
            "conversation_id": conv_id,
            "mode": turn["mode"],
            "competition_type": turn["competition_type"],
        }
        t0 = time.time()
        try:
            resp = _post("/api/dialogue/turn", payload, timeout=300)
        except urllib.error.URLError as exc:
            print(f"  ! Turn {i} 网络/超时: {exc}")
            return rows, pass_count
        except Exception as exc:
            print(f"  ! Turn {i} 失败: {exc}")
            return rows, pass_count
        dt = time.time() - t0
        if not conv_id:
            conv_id = resp.get("conversation_id")

        trace = resp.get("agent_trace") or {}
        comp = trace.get("competition") or {}
        actual = ""
        for k in trace_keys:
            if "." in k:
                a, b = k.split(".", 1)
                actual = (trace.get(a) or {}).get(b) or actual
            else:
                actual = trace.get(k) or comp.get(k) or actual
            if actual:
                break

        expected = turn[expect_key]
        ok = (actual == expected)
        # 安全闸门：如果 expected=strict 但被高风险/想法期改写，也算通过
        tone_origin = trace.get("tone_origin") or comp.get("tone_origin") or ""
        if not ok and expected == "strict" and tone_origin == "forced_strict":
            ok = True
        if ok:
            pass_count += 1

        excerpt = _short(resp.get("assistant_message"), 200)
        flag = "✓" if ok else "✗"
        print(f"  Turn {i} ({dt:5.1f}s) {flag} expected={expected:<26} actual={actual or '<empty>':<26} origin={tone_origin or '-'}")
        print(f"      回复片段: {excerpt}")
        rows.append({
            "turn": i,
            "expected": expected,
            "actual": actual,
            "tone_origin": tone_origin,
            "passed": ok,
            "latency_s": round(dt, 1),
            "user_text_preview": _short(turn["message"], 80),
            "assistant_excerpt": excerpt,
        })
        time.sleep(1.5)
    return rows, pass_count


def main() -> int:
    overall_t0 = time.time()
    rows1, pass1 = _run_part(
        "Part 1 · 答辩模式 · 评委角色卡库",
        PART1, "expected_judge", ["competition.active_judge", "competition.active_judge_id"],
    )
    rows2, pass2 = _run_part(
        "Part 2 · 追问策略库 · 表达风格层（语气）",
        PART2, "expected_tone", ["preferred_tone", "competition.preferred_tone"],
    )

    out = {
        "judges": {"rows": rows1, "passed": pass1, "total": len(rows1)},
        "tone": {"rows": rows2, "passed": pass2, "total": len(rows2)},
    }
    with open("smoke_judges_and_tone.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    total_dt = time.time() - overall_t0
    print(
        f"\n>>> Part1 评委 {pass1}/{len(rows1)} | Part2 语气 {pass2}/{len(rows2)} | "
        f"总耗时 {total_dt:.1f}s | 详细见 smoke_judges_and_tone.json"
    )
    return 0 if (pass1 == len(rows1) and pass2 == len(rows2)) else 1


if __name__ == "__main__":
    sys.exit(main())
