# -*- coding: utf-8 -*-
"""测试用例 1：学生学习模式（final-01 账号）

人设
----
大一新生「五一快放假」（学号 1120230236），完全是创新创业大赛小白，
对赛事、选题、组队、商业模式、行动计划一概不熟，希望 AI 既给答案，
又通过反向提问引导思考，并给出对应知识点的案例。

设计目标
--------
1. 走 ``mode="learning"``（项目教练模式）的 6 轮连续对话，且共享同一会话
   ⇒ 验证项目编号 ``P-1120230236-NN`` 在多轮里稳定关联到该学生。
2. 每一轮断言：
   • 关键词命中  → 验证回答覆盖该轮主题；
   • 启发式提问  → 回复中至少出现 N 个问号（含全角"？"），并出现至少一个
     启发式词（"你""怎么看""试想""不妨""思考""为什么"…）；
   • 知识点案例 → 回复里出现"案例 / 例如 / 比如 / 参考 / 借鉴"等示例标识，
     或后端返回的 ``rag_cases`` 非空；
   • 跨图谱语义启发 → ``kg_analysis.entities`` 触发 ≥ 2 个不同实体类型，
     或 ``hypergraph_insight.matched_by.family_distribution`` 覆盖 ≥ 2 个家族。
3. 末尾汇总：
   • 6 轮共享的项目编号；
   • 触发的超图家族集合；
   • 累计返回的 RAG 案例数量。

输出：控制台简表 + ``regression_final01_case1.json``
"""

from __future__ import annotations

import io
import json
import re
import sys
import time
from typing import Any

import urllib.error
import urllib.request

# Windows PowerShell 默认 GBK，强制把 stdout/stderr 切成 UTF-8，避免中文/特殊符号崩溃
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

API = "http://127.0.0.1:8037"
USER_ID = "99fed9ab-486c-4b22-8329-b3c6466e17d2"
PROJECT_ID = f"project-{USER_ID}"
STUDENT_ID = "1120230236"

MODE = "learning"  # 学生学习 / 项目教练
COMPETITION_TYPE = ""  # learning 模式不强绑赛道，留空让后端自适应

PROJECT_PREAMBLE = (
    "我是大一新生（计算机/管理交叉方向），最近想试着报一下创新创业大赛，但完全是小白，"
    "之前没有过任何项目或者比赛经验。"
)

# 启发式提问关键词：用来近似判断"是否反向提问引导学生"
HINT_QUESTION_TERMS = [
    "你", "你怎么看", "你认为", "你的", "你打算", "你能不能",
    "试想", "不妨", "想一想", "思考", "为什么", "假如", "如果",
    "请问自己", "问问自己", "停下来", "倒过来想", "反过来",
]

# 案例 / 知识点示例标识
CASE_TERMS = [
    "案例", "例如", "比如", "举个例子", "举例", "参考", "借鉴",
    "类似", "曾经", "前辈", "师兄", "师姐", "学长", "学姐",
]


CASES: list[dict[str, Any]] = [
    {
        "tag": "破冰·完全小白入门指引",
        "expected_keywords": ["大赛", "起步", "目标", "选题", "团队"],
        "min_hit": 2,
        "min_questions": 2,
        "message": (
            f"{PROJECT_PREAMBLE}\n\n"
            "我现在的状态是：知道学校有「互联网+」「挑战杯」「大创」这几个比赛，但完全分不清"
            "它们的区别，也不知道自己是该先想 idea、先组队、还是先去找老师。"
            "请把我当作一个零经验的新手，告诉我从今天开始第一周到第一个月分别要做什么；"
            "另外，能不能在过程里反过来问我几个问题，帮我自己把方向想清楚？"
        ),
    },
    {
        "tag": "选赛·互联网+/挑战杯/大创差异",
        "expected_keywords": ["互联网+", "挑战杯", "大创", "商业", "学术", "评审"],
        "min_hit": 3,
        "min_questions": 1,
        "message": (
            "继续我刚才的问题。三个比赛我应该优先选哪个？我个人偏理科，对 AI / 数据有兴趣，"
            "但我还没法判断我的想法是『偏商业的产品』还是『偏学术的研究』。请你从评审口味、"
            "对作品成熟度的要求、对团队结构的要求三方面帮我对比，并举一个真实大学生项目作为例子。"
            "顺便给我抛 1-2 个问题，让我能自己判断我的项目更像哪一类。"
        ),
    },
    {
        "tag": "找idea·灵感方法与避坑",
        "expected_keywords": ["灵感", "需求", "用户", "痛点", "调研", "场景"],
        "min_hit": 3,
        "min_questions": 2,
        "message": (
            "我现在最大的卡点是没有 idea。能不能给我 2-3 种『大一新生也能用』的找题方法，"
            "比如从身边痛点出发、从课程作业出发、从老师课题组出发？每种方法配一个真实学生案例，"
            "并告诉我『一个看起来很酷但其实很危险』的常见坑（比如不加调研直接做 App）。"
            "最后，反过来问我两个问题，帮我从这些方法里挑出一条最适合我自己的。"
        ),
    },
    {
        "tag": "组队·团队结构与角色互补",
        "expected_keywords": ["团队", "角色", "技术", "运营", "互补", "分工"],
        "min_hit": 3,
        "min_questions": 1,
        "message": (
            "假设我现在已经有了一个粗糙的 idea：『面向大学生的二手教材匹配小程序』。"
            "我想问：单兵作战还是必须组队？如果组队，最经典的『技术+运营+设计』三角是怎么分工的？"
            "我作为一个写代码还行、但商业经验为零的大一，到底应该承担哪个角色？"
            "如果你是教练，会反问我哪些问题来检验我能不能做好这个角色？"
        ),
    },
    {
        "tag": "商业模式·BMC入门与第一版",
        "expected_keywords": ["商业模式", "BMC", "客户", "价值", "渠道", "收入"],
        "min_hit": 3,
        "min_questions": 1,
        "message": (
            "评审老师好像很在意『商业模式画布』(BMC)。请用最白话的方式解释 BMC 的 9 个格子，"
            "尤其是『价值主张』『客户细分』『收入来源』这三块小白最容易写空。"
            "用我刚才说的『二手教材匹配小程序』当例子，帮我写一个最朴素的第一版 BMC，"
            "并指出这个第一版里至少 2 个『等你做用户访谈后必然要改』的格子。"
        ),
    },
    {
        "tag": "复盘·四周学习路线图",
        "expected_keywords": ["路线图", "周", "目标", "调研", "原型", "答辩"],
        "min_hit": 3,
        "min_questions": 1,
        "message": (
            "最后，请你帮我把今天聊到的所有东西，浓缩成一份『大一新手 4 周创新创业入门路线图』。"
            "格式是：每周 1 个核心目标 + 2-3 个可交付物（例如『5 份用户访谈纪要』『1 张 BMC』）"
            "+ 1 个易错提醒。结尾再反问我 1 个问题，让我承诺下一步要做什么。"
        ),
    },
]


def _post(path: str, payload: dict[str, Any], timeout: int = 360) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=API + path, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _short(text: str | None, limit: int = 320) -> str:
    if not text:
        return ""
    t = str(text).replace("\n", " ").strip()
    return t if len(t) <= limit else t[:limit] + "…"


_QUESTION_RE = re.compile(r"[?？]")


def _count_questions(text: str) -> int:
    return len(_QUESTION_RE.findall(text or ""))


def _has_any(text: str, terms: list[str]) -> list[str]:
    low = (text or "").lower()
    return [t for t in terms if t.lower() in low]


def _entity_type_set(kg: dict | None) -> set[str]:
    if not isinstance(kg, dict):
        return set()
    types: set[str] = set()
    for ent in kg.get("entities", []) or []:
        if not isinstance(ent, dict):
            continue
        t = str(ent.get("type") or ent.get("entity_type") or "").strip()
        if t:
            types.add(t)
    return types


def _hyper_family_set(hi: dict | None) -> set[str]:
    if not isinstance(hi, dict):
        return set()
    fam = ((hi.get("matched_by") or {}).get("family_distribution") or {})
    return {str(k) for k, v in fam.items() if v}


def main() -> int:
    print(f"\n{'=' * 80}\n测试用例 1：学生学习模式（mode={MODE}, 大一新生 + 创新创业大赛入门）\n{'=' * 80}")
    print(f"  账号：USER_ID={USER_ID}")
    print(f"  学号：STUDENT_ID={STUDENT_ID}（后端将据此生成 P-{STUDENT_ID}-NN 项目编号）")

    rows: list[dict[str, Any]] = []
    conv_id: str | None = None
    logical_pid_seen: set[str] = set()
    family_union: set[str] = set()
    entity_type_union: set[str] = set()
    rag_case_total = 0
    pass_count = 0
    overall_t0 = time.time()

    for i, case in enumerate(CASES, 1):
        payload = {
            "project_id": PROJECT_ID,
            "student_id": STUDENT_ID,
            "message": case["message"],
            "conversation_id": conv_id,
            "mode": MODE,
            "competition_type": COMPETITION_TYPE,
        }
        t0 = time.time()
        try:
            resp = _post("/api/dialogue/turn", payload, timeout=360)
        except urllib.error.URLError as exc:
            print(f"  ! Turn {i} 网络/超时: {exc}")
            return 1
        except Exception as exc:
            print(f"  ! Turn {i} 失败: {exc}")
            return 1
        dt = time.time() - t0
        if not conv_id:
            conv_id = resp.get("conversation_id")

        assistant_msg = str(resp.get("assistant_message") or "")
        diag = resp.get("diagnosis") or {}
        trace = resp.get("agent_trace") or {}
        kg = resp.get("kg_analysis") or {}
        hi = resp.get("hypergraph_insight") or {}
        hs = resp.get("hypergraph_student") or {}
        rag_cases = resp.get("rag_cases") or []
        triggered = [r.get("id") for r in (diag.get("triggered_rules") or [])[:5]]

        # ── 项目编号
        logical_pid = str(resp.get("logical_project_id") or "").strip()
        if logical_pid:
            logical_pid_seen.add(logical_pid)
        is_standard_pid = bool(logical_pid) and logical_pid.startswith(f"P-{STUDENT_ID}-")

        # ── 关键词命中
        keywords = case["expected_keywords"]
        hits = [kw for kw in keywords if kw.lower() in assistant_msg.lower()]
        ok_kw = len(hits) >= case["min_hit"]

        # ── 启发式提问检测
        q_count = _count_questions(assistant_msg)
        hint_terms_hit = _has_any(assistant_msg, HINT_QUESTION_TERMS)
        ok_q = q_count >= case["min_questions"] and len(hint_terms_hit) >= 1

        # ── 案例 / 知识点示例
        case_terms_hit = _has_any(assistant_msg, CASE_TERMS)
        ok_case = bool(case_terms_hit) or len(rag_cases) > 0
        rag_case_total += len(rag_cases)

        # ── 跨图谱语义启发：实体类型≥2 或 超图家族≥2
        ent_types = _entity_type_set(kg)
        fam_set = _hyper_family_set(hi)
        entity_type_union |= ent_types
        family_union |= fam_set
        ok_cross = (len(ent_types) >= 2) or (len(fam_set) >= 2)

        all_ok = ok_kw and ok_q and ok_case and ok_cross
        if all_ok:
            pass_count += 1

        flag = "[OK]" if all_ok else "[NG]"
        pid_label = (
            f"{logical_pid}（规范 OK，已绑定 {STUDENT_ID}）"
            if is_standard_pid
            else (f"{logical_pid}（非规范）" if logical_pid else "<空>")
        )
        print(f"\n  Turn {i} ({dt:5.1f}s) {flag} [{case['tag']}]")
        print(f"      项目编号 : {pid_label}")
        print(f"      会话ID   : {conv_id or '<none>'}")
        print(f"      关键词   : {hits}  (要求 ≥ {case['min_hit']})  -> {'OK' if ok_kw else 'FAIL'}")
        print(f"      启发提问 : 问号数={q_count}（要求 ≥ {case['min_questions']}）, 启发词命中={hint_terms_hit[:5]}  -> {'OK' if ok_q else 'FAIL'}")
        print(f"      案例引用 : 文本命中={case_terms_hit[:5]}, RAG案例={len(rag_cases)}  -> {'OK' if ok_case else 'FAIL'}")
        print(f"      跨图谱   : 实体类型={sorted(ent_types)[:6]}（{len(ent_types)}）, 超图家族={sorted(fam_set)[:6]}（{len(fam_set)}）  -> {'OK' if ok_cross else 'FAIL'}")
        print(f"      触发规则 : {triggered or '<none>'}")
        print(f"      回复片段 : {_short(assistant_msg, 320)}")

        rows.append({
            "turn": i,
            "tag": case["tag"],
            "logical_project_id": logical_pid,
            "logical_project_id_is_standard": is_standard_pid,
            "conversation_id": conv_id or "",
            "student_id": STUDENT_ID,
            "latency_s": round(dt, 1),
            "passed": all_ok,
            "checks": {
                "keywords_ok": ok_kw,
                "hit_keywords": hits,
                "min_hit": case["min_hit"],
                "questions_ok": ok_q,
                "question_marks": q_count,
                "min_questions": case["min_questions"],
                "hint_terms_hit": hint_terms_hit[:8],
                "case_ok": ok_case,
                "case_terms_hit": case_terms_hit[:8],
                "rag_case_count": len(rag_cases),
                "cross_graph_ok": ok_cross,
                "kg_entity_types": sorted(ent_types),
                "hyper_families": sorted(fam_set),
                "hyper_student_edge_count": len((hs or {}).get("edges", []) or []),
            },
            "triggered_rules": triggered,
            "user_text_preview": _short(case["message"], 110),
            "assistant_excerpt": _short(assistant_msg, 600),
        })
        time.sleep(2.0)

    out_path = "regression_final01_case1.json"
    summary = {
        "student_id": STUDENT_ID,
        "user_id": USER_ID,
        "conversation_id": conv_id or "",
        "logical_project_ids": sorted(logical_pid_seen),
        "kg_entity_type_union": sorted(entity_type_union),
        "hyper_family_union": sorted(family_union),
        "rag_case_total": rag_case_total,
        "rows": rows,
        "passed": pass_count,
        "total": len(rows),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    total_dt = time.time() - overall_t0

    pid_list = sorted(logical_pid_seen)
    if not pid_list:
        pid_summary = "<空>，请检查 final-01 用户的 student_id 是否已写入"
    elif len(pid_list) == 1 and pid_list[0].startswith(f"P-{STUDENT_ID}-"):
        pid_summary = f"{pid_list[0]} (OK) 6 轮共享同一项目编号，已绑定学号 {STUDENT_ID}"
    else:
        pid_summary = " / ".join(pid_list) + "（>1 个，部分轮次被识别为新项目）"

    print(f"\n>>> 通过 {pass_count}/{len(rows)} | 总耗时 {total_dt:.1f}s | 详细见 {out_path}")
    print(f">>> 项目编号       : {pid_summary}")
    print(f">>> 会话ID         : {conv_id or '<none>'}")
    print(f">>> KG 实体类型聚合: {sorted(entity_type_union)}  ({len(entity_type_union)} 类)")
    print(f">>> 超图家族聚合   : {sorted(family_union)}  ({len(family_union)} 族)")
    print(f">>> 累计 RAG 案例  : {rag_case_total}")
    if len(family_union) >= 2:
        print(">>> [OK] 至少 2 个超图家族被触发 → 出现了跨图谱语义启发")
    elif len(entity_type_union) >= 3:
        print(">>> [OK-soft] 超图家族未跨多族，但 KG 实体类型 ≥ 3，仍属于跨语义维度")
    else:
        print(">>> [WARN] 未观察到明显的跨图谱语义启发，建议人工抽查 hypergraph_insight")

    return 0 if pass_count == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
