# -*- coding: utf-8 -*-
"""测试用例 9：合规与伦理 / 国际化视野 / 学术深度（final-01 账号）

设计思路
--------
- 用同一个项目主题（LegalScan 法务 AI）在一个会话里连发 6 轮，避免被识别为新项目重置上下文。
- Part 1 合规与伦理（4 轮，重点深挖）：
    1) AI 伦理 / 模型幻觉的法律责任
    2) 数据隐私 / 跨境数据传输 / GDPR
    3) 行业准入 / 律师法 / 经营许可门槛
    4) 算法歧视 / 可解释性 / 审计可追溯
- Part 2 国际化视野（1 轮）：北美 vs 东南亚两个市场的迁移可行性
- Part 3 学术深度（1 轮）：最新论文（ACL / KDD / NeurIPS）能否支撑算法优越性

每轮断言：assistant_message 里出现至少 N 个相关关键词，作为"系统是否真的覆盖了该维度"的弱信号。
输出：控制台简表 + regression_final01_case9.json
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

import urllib.request
import urllib.error

API = "http://127.0.0.1:8037"
USER_ID = "99fed9ab-486c-4b22-8329-b3c6466e17d2"
PROJECT_ID = f"project-{USER_ID}"
STUDENT_ID = "1120230236"

MODE = "competition"
COMPETITION_TYPE = "internet_plus"

PROJECT_PREAMBLE = (
    "项目背景：我们做的是 LegalScan，一款面向中小企业法务岗的 AI 合同审查 SaaS。"
    "底层是百万级中文合同语料微调的 7B 大模型，处理保密协议 / 采购合同 / 用工合同等敏感文本。"
)

CASES: list[dict[str, Any]] = [
    {
        "tag": "合规·AI伦理与模型幻觉责任",
        "expected_keywords": ["责任", "幻觉", "免责", "审核", "误判"],
        "min_hit": 2,
        "message": (
            f"{PROJECT_PREAMBLE}\n\n"
            "想请你帮我严肃评估一下 AI 伦理这一块：如果我们的模型在合同审查里漏掉了一条对客户致命的"
            "条款，导致客户后续打官司败诉，损失几百万——按照目前 AI 法务工具的责任划分惯例，我们"
            "是『工具提供方』可以免责，还是会被法院认定为『专业服务提供方』要承担连带责任？"
            "我们的产品里现在只在登录页底部写了一行『仅供参考，不构成法律意见』的免责声明，够吗？"
            "我们应该在产品设计、合同条款、用户教育上分别补哪些动作？"
        ),
    },
    {
        "tag": "合规·数据隐私与跨境传输",
        "expected_keywords": ["隐私", "数据", "GDPR", "本地化", "跨境", "授权", "脱敏", "个保法"],
        "min_hit": 3,
        "message": (
            "继续这个项目，再问数据隐私这一块。我们的客户上传的合同里包含大量个人信息（员工身份证号、"
            "客户联系方式）和企业商业秘密（采购报价、技术方案）。我们目前是把文件传到自建的 GPU 服务器"
            "处理，但模型训练阶段确实用了客户脱敏后的合同文本做 SFT。\n\n"
            "请帮我从《个人信息保护法》《数据安全法》和欧盟 GDPR 三个维度分别梳理一下：\n"
            "1) 我们目前的做法有哪些**已经踩线**的合规风险？\n"
            "2) 如果未来想拓展到欧盟客户，跨境数据传输需要满足什么前置条件？\n"
            "3) 我们的 SFT 数据如果未来被监管要求『撤回某客户的训练贡献』，技术上做不到怎么办？"
        ),
    },
    {
        "tag": "合规·行业准入与执业牌照",
        "expected_keywords": ["律师", "执业", "许可", "法律服务", "司法部", "律师法", "牌照"],
        "min_hit": 2,
        "message": (
            "再问行业准入。中国《律师法》明确规定『非律师不得以律师名义从事法律服务』，我们这种"
            "AI 合同审查产品，本质上提供的是不是法律服务？\n\n"
            "目前业内有几种打法：①只做『风险标注』不出『法律意见』、②跟正规律所做白标合作、"
            "③申请『法律科技服务』的特殊资质。请帮我对比这三种路径的合规成本和商业天花板，"
            "以及——如果未来司法部出台 AI 法律服务的负面清单，我们最容易被打的是哪一条？"
        ),
    },
    {
        "tag": "合规·算法歧视与可审计性",
        "expected_keywords": ["歧视", "偏见", "可解释", "审计", "公平", "黑箱"],
        "min_hit": 2,
        "message": (
            "再问一个角度：算法公平性。我们的训练语料 70% 来自一线城市的大型合同，三四线城市和小微"
            "企业的合同样本只占 10%。这意味着模型对小微企业的『行业惯例性条款』识别精度可能显著低于"
            "大企业合同——这算不算一种隐形的算法歧视？\n\n"
            "另外『生成式 AI 服务管理暂行办法』要求服务提供者『提供安全、稳定、持续的服务』并保留"
            "日志至少 6 个月，我们目前的可解释性方案只是给每个高亮条款配了一句『为什么风险高』的"
            "自然语言说明，没有可追溯的注意力权重或对照判例链路——这对监管审计够不够？"
        ),
    },
    {
        "tag": "国际化·北美/东南亚市场迁移",
        "expected_keywords": ["北美", "东南亚", "本地化", "司法体系", "英美法", "成文法", "市场"],
        "min_hit": 2,
        "message": (
            "切换一个角度：国际化视野。如果我们想把 LegalScan 复制到（a）北美市场和（b）东南亚（新加坡 / "
            "印尼 / 越南）市场，请你分两块帮我评估迁移可行性。\n\n"
            "重点想看：①法律体系差异（英美判例法 vs 大陆成文法）对模型重训练成本的影响；"
            "②本地竞争对手（北美的 LegalSifter / Kira Systems、东南亚的本地律所联盟）我们要怎么差异化；"
            "③合规层面，北美需要 SOC2 / 东南亚有没有数据本地化要求；"
            "④哪个市场的优先级更高，为什么？"
        ),
    },
    {
        "tag": "学术深度·最新论文支撑算法优越性",
        "expected_keywords": ["论文", "ACL", "EMNLP", "NeurIPS", "KDD", "微调", "benchmark", "SOTA"],
        "min_hit": 2,
        "message": (
            "最后一块：学术深度。如果我们要把『7B 模型在合同审查任务 F1=0.87，比 GPT-4 直接 prompt 高 6 个"
            "百分点』这个核心技术亮点写进答辩 PPT，评委大概率会问：『你引用了哪些最新论文支撑你这个"
            "算法路径？』。\n\n"
            "请帮我列：①ACL / EMNLP / NeurIPS / KDD 近 2 年里，跟『法律文本理解 / 合同抽取 / 长文本"
            "RAG』直接相关的代表性论文（不需要列全，列你最有信心的 3-5 篇）；②我们这个 7B + SFT 路线，"
            "相比 LegalBERT、Legal-Pilot 这类已有工作，技术贡献到底在哪里？③如果评委追问『你的 F1=0.87 "
            "是在哪个公开 benchmark 上跑的、有没有可复现的实验设置』，我们应该怎么回答更扎实？"
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


def main() -> int:
    print(f"\n{'=' * 80}\n测试用例 9：合规与伦理 / 国际化 / 学术深度（mode={MODE}, comp={COMPETITION_TYPE}）\n{'=' * 80}")
    print(f"  账号：USER_ID={USER_ID}")
    print(f"  学号：STUDENT_ID={STUDENT_ID}（后端将据此生成 P-{STUDENT_ID}-NN 项目编号）")
    rows: list[dict[str, Any]] = []
    conv_id: str | None = None
    logical_pid_seen: set[str] = set()
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
        keywords = case["expected_keywords"]
        hits = [kw for kw in keywords if kw.lower() in assistant_msg.lower()]
        ok = len(hits) >= case["min_hit"]
        if ok:
            pass_count += 1

        trace = resp.get("agent_trace") or {}
        diag = resp.get("diagnosis") or {}
        comp = trace.get("competition") or {}
        triggered = [r.get("id") for r in (diag.get("triggered_rules") or [])[:5]]
        # 项目编号（后端在 /api/dialogue/turn 响应里直接返回，对应 P-学号-NN）
        logical_pid = str(resp.get("logical_project_id") or "").strip()
        if logical_pid:
            logical_pid_seen.add(logical_pid)
        is_standard_pid = bool(logical_pid) and logical_pid.startswith(f"P-{STUDENT_ID}-")
        pid_label = (
            f"{logical_pid}（规范编号 ✓ 已绑定学号 {STUDENT_ID}）"
            if is_standard_pid
            else (f"{logical_pid}（非规范，回退值）" if logical_pid else "<空>（后端未返回，请检查用户学号是否已写入）")
        )

        flag = "✓" if ok else "✗"
        print(f"\n  Turn {i} ({dt:5.1f}s) {flag} [{case['tag']}]")
        print(f"      项目编号: {pid_label}")
        print(f"      会话ID:   {conv_id or '<none>'}")
        print(f"      命中关键词: {hits}  (要求 ≥ {case['min_hit']})")
        print(f"      触发规则: {triggered or '<none>'}")
        print(f"      tone_origin={trace.get('tone_origin') or comp.get('tone_origin') or '-'}, "
              f"active_judge={comp.get('active_judge') or '-'}")
        print(f"      回复片段: {_short(assistant_msg, 320)}")

        rows.append({
            "turn": i,
            "tag": case["tag"],
            "expected_keywords": keywords,
            "min_hit": case["min_hit"],
            "hit_keywords": hits,
            "passed": ok,
            "latency_s": round(dt, 1),
            "logical_project_id": logical_pid,
            "logical_project_id_is_standard": is_standard_pid,
            "conversation_id": conv_id or "",
            "student_id": STUDENT_ID,
            "user_text_preview": _short(case["message"], 100),
            "assistant_excerpt": _short(assistant_msg, 600),
            "triggered_rules": triggered,
            "tone_origin": trace.get("tone_origin") or comp.get("tone_origin") or "",
            "active_judge": comp.get("active_judge") or "",
            "preferred_tone": trace.get("preferred_tone") or comp.get("preferred_tone") or "",
        })
        time.sleep(2.0)

    out_path = "regression_final01_case9.json"
    summary = {
        "student_id": STUDENT_ID,
        "user_id": USER_ID,
        "conversation_id": conv_id or "",
        "logical_project_ids": sorted(logical_pid_seen),
        "rows": rows,
        "passed": pass_count,
        "total": len(rows),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    total_dt = time.time() - overall_t0

    # 汇总：本次会话覆盖到的项目编号（理想状态：6 轮共享同一个 P-学号-NN）
    pid_list = sorted(logical_pid_seen)
    if not pid_list:
        pid_summary = "<空>，请确认 final-01 用户已在个人中心填写学号"
    elif len(pid_list) == 1 and pid_list[0].startswith(f"P-{STUDENT_ID}-"):
        pid_summary = f"{pid_list[0]} ✓ 6 轮共享同一项目编号，已绑定学号 {STUDENT_ID}"
    else:
        pid_summary = " / ".join(pid_list) + "（多于 1 个，说明有部分轮次被识别为新项目）"

    print(f"\n>>> 通过 {pass_count}/{len(rows)} | 总耗时 {total_dt:.1f}s | 详细见 {out_path}")
    print(f">>> 项目编号: {pid_summary}")
    print(f">>> 会话ID:   {conv_id or '<none>'}")
    return 0 if pass_count == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
