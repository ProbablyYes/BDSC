# -*- coding: utf-8 -*-
"""端到端测试脚本：用 final-01 账号跑多个不同性质的项目，每个项目一轮完整丰富的多轮对话。

设计目标
1. 验证“项目编号”：每个项目使用独立 conversation_id → 后端应分别生成
   不同的 logical_project_id（P-1120230236-NN）。
2. 验证“项目认知引擎”双光谱（innov_venture / biz_public）能否随对话内容
   正确漂移到对应象限。
3. 验证 project_stage_v2 是否随成熟度推进。
4. 验证 ability_subgraphs / ontology_grounding / 多智能体回答中是否真的引用了
   超图、知识图谱、本体节点等。
5. 验证财务（商业模型）讨论时系统能否结合项目本身做合理引导。

使用方式
    python -u apps/backend/scripts/test_final01_dialogue.py

输出
    控制台简表 + 详细 JSON 写入 regression_final01.json
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

import urllib.request
import urllib.error

API = "http://127.0.0.1:8037"
USER_ID = "99fed9ab-486c-4b22-8329-b3c6466e17d2"   # final-01
PROJECT_ID = f"project-{USER_ID}"
STUDENT_ID = "1120230236"

# 全部使用「项目教练」模式，不指定竞赛类型 —— 完全靠认知引擎自己识别
COMMON_MODE = "learning"
COMMON_COMPETITION = ""

CASES = [
    {
        "tag": "case-A 商业+创业（SaaS 法务工具，目标象限：右上）",
        "expected_quadrant": "(+innov_venture, +biz_public)",
        "expected_signals": ["商业可持续", "PMF", "客户付费意愿", "渠道获客", "单客经济"],
        "turns": [
            (
                "我们团队最近在做一款叫 LegalScan 的 AI 合同审查工具，目标用户是中小企业里的法务"
                "或行政岗。我们前期访谈了 14 家公司，其中 9 家明确告诉我们：他们没有预算请律师事务所"
                "做日常合同审查，但每月又会有 5–20 份合同需要被人盯着改，比如保密协议、采购合同、用工"
                "合同。这件事让我们觉得这是个真实存在的市场缺口。\n\n"
                "我们的初步方案是做一个 Web 端工具，用户上传 docx/pdf，系统在 30 秒内输出风险条款"
                "高亮 + 修改建议 + 类似案例的判例引用。重点不是替代律师，而是让法务在 1 小时内完成"
                "原本要 4 小时的初审。\n\n"
                "想先听听你的看法：这种切入方式有没有什么我们自己看不到的盲点？"
            ),
            (
                "技术上我们用了百万级中文合同语料微调了一个 7B 模型，目前在自建测试集上 F1 = 0.87，"
                "在风险条款识别这一项上比 GPT-4 直接 prompt 高 6 个百分点。我们没有把模型作为壁垒，"
                "因为我们知道大模型迭代很快，护城河更应该是数据闭环和行业知识图谱。\n\n"
                "商业化上准备走 SaaS 订阅：基础版 299 元/月，企业版 999 元/月（带审计追踪、多人协作、"
                "私有化部署）。已经有 3 家公司在试用免费版，其中 1 家明确说愿意按 999/月续费。\n\n"
                "我们对自己的判断是：这是一个标准的 B2B SaaS 商业项目，不是为了改变世界，而是想做成"
                "一个能稳定赚钱的工具型产品。你觉得我们这个判断准确吗？"
            ),
            (
                "获客渠道上我们打算分两步走：先做内容获客，在「智合」「无讼」这类法律垂类社群发布"
                "「常见合同 10 大坑」之类的实操干货，吸引法务关注；然后通过 LinkedIn + 行业活动做"
                "B 端拓展。我们算了一下 CAC 大约 600 元，按 999 元/月 + 12 个月平均生命周期算 LTV"
                "约 8000 元，LTV/CAC ≈ 13，理论上跑得通。\n\n"
                "团队 4 个人，2 个技术（其中 1 个有 5 年法律科技经验）、1 个产品、1 个 BD。前期天使"
                "投资 80 万已经到账，预计可以撑 8–10 个月。我们希望 6 个月跑到 50 个付费客户、月营收"
                "5 万这个里程碑，然后开始 Pre-A。\n\n"
                "请帮我分析一下：现在这个阶段最该担心的是什么？"
            ),
            (
                "好的，那我把我们的财务模型说得更细一点你帮我看看合不合理：\n\n"
                "收入端：基础版 299/月，假设按月付，平均生命周期 12 个月（订阅）；企业版 999/月，"
                "12 个月 + 25% 的客户会升级到 1999 的旗舰版。我们假设第 6 个月时基础版 30 家、"
                "企业版 20 家，月营收 = 30×299 + 20×999 ≈ 28,950 元，离我们的 5 万目标还有差距，所以"
                "我们认为需要拉高企业版占比。\n\n"
                "成本端：每月 LLM 调用费用预估 8000（用国产大模型走 API），人力 4 人 × 18000 = "
                "72000，办公 + 服务器 ≈ 5000，合计 85,000/月。\n\n"
                "这意味着我们短期至少要做到 10 万 ARR 才能勉强打平。请你重点帮我看：这个商业模型里，"
                "最容易被高估的假设是什么？以及订阅这种模式下，你觉得我们应该把核心精力放在拉新还是"
                "降低 churn 上？"
            ),
            (
                "再问一个比较具体的：我们准备参加一些创新创业竞赛，但又有点犹豫——我们这个项目"
                "本质上是个「正经做生意」的 SaaS，不是那种特别炫酷的 deeptech 或者改变社会的故事。"
                "评委会不会更喜欢有故事性的项目？我们这种偏务实的商业项目，在路演时应该怎么呈现"
                "才比较合适？\n\n"
                "另外，能否帮我列一下：如果我们要把这个项目做成一个比较完整的 BP，下一步还需要"
                "补哪些关键证据/数据？比如 retention 曲线、单位经济模型、什么 cohort 之类的，越具体越好。"
            ),
        ],
    },
    {
        "tag": "case-B 创新+公益（实验室技术做适老化研究，目标象限：左下）",
        "expected_quadrant": "(-innov_venture, -biz_public)",
        "expected_signals": ["技术创新", "学术", "弱势群体", "公共卫生", "社会效益"],
        "turns": [
            (
                "我们是学校生物医学工程实验室的本科生团队，导师是做无感监测方向的。我们做的项目叫"
                "「夜守」，用毫米波雷达 + 深度学习实现非接触式呼吸/心率监测，专门面向独居老人夜间"
                "猝死/呼吸暂停场景。\n\n"
                "项目起源是我们看到一份卫健委的数据：60 岁以上独居老人在夜间发生猝死后被发现的"
                "平均时间是 11 小时，错过了急救黄金期。现有方案要么需要老人佩戴手环（依从性很差），"
                "要么是摄像头（隐私问题大），所以我们想做无接触的方案。\n\n"
                "我们目前还没考虑商业化，更想先把这件事的技术和社会价值做扎实。你怎么看这个方向？"
            ),
            (
                "技术上我们做了几件事：\n"
                "1. 自研了一套基于 60GHz 毫米波 IF 信号的微动检测算法，可以从胸腔起伏中分离呼吸+心率，"
                "在 2.5 米内精度 RMSE = 1.2 次/分（呼吸）、3.8 次/分（心率）。\n"
                "2. 跟北医三院呼吸科合作做了 200 例临床对比测试（金标准为接触式监护仪），整体一致性"
                "Pearson r = 0.93，论文初稿在改，准备投 IEEE Sensors Journal。\n"
                "3. 申请了 1 项发明专利（已受理）。\n\n"
                "我们觉得这个方向最大的难点不是技术，而是怎么真正把它送到独居老人手里。这部分我们"
                "完全没有经验。能不能帮我们想一下，从「研究」走到「真正用起来」之间，我们差了哪些"
                "环节？"
            ),
            (
                "我们最近联系了民政局和两个街道办，他们的反馈是：街道层面非常需要这种东西，但完全"
                "没有预算让老人自费 1000+ 元的设备。如果想推广，路径只能是：1）申请政府购买服务、"
                "2）公益基金会资助、3）跟养老机构合作做团购。\n\n"
                "我们做了一个粗略的估算：一个街道大概 200 位独居老人是高危人群，按设备 + 一年服务费"
                "1500 元/人计算，每个街道一年 30 万；如果能进入「居家养老服务清单」由政府兜底，会"
                "更可持续。\n\n"
                "我们的初心是希望这套东西能真的护住一群人，而不是先想怎么挣钱。你觉得在这种公共服务"
                "属性比较强的项目里，我们应该怎么去构建可持续性，而不是变成一锤子买卖？"
            ),
            (
                "再具体一点：我们现在在试点的 1 个街道（覆盖 80 位老人），半年内已经触发过 3 次有效"
                "预警（其中 1 例确认是夜间呼吸暂停综合征，转介到了医院）。志愿者团队是周边高校的"
                "学生 + 退休党员，已经有 14 位长期值守。我们没有向老人或家属收一分钱。\n\n"
                "资金上：街道办给了 6 万年度购买服务费、一家本地药店 CSR 赞助了 2 万、学校创新创业"
                "学院的种子基金 3 万，合计 11 万，刚好够维持现有规模 1 年。要扩展到 5 个街道就完全"
                "不够了。\n\n"
                "我想请教一个问题：在我们这种「不收用户钱」的项目里，所谓的「财务可持续性」到底"
                "应该怎么算？你能否帮我画一下这种项目的资金来源结构和它对应的关键变量？比起 SaaS"
                "那种 ARR 模型，我们这种应该看什么？"
            ),
            (
                "最后一个问题，关于影响力评估：\n"
                "我们打算把项目推到「挑战杯」/「互联网+」之类的比赛里，但我心里有点没底——评委会"
                "怎么评一个不挣钱的项目？我们应该用什么样的指标去证明它「值得做」？\n\n"
                "目前我们能拿出来的东西包括：覆盖人数（80 → 计划 600）、预警准确率、有效干预次数、"
                "志愿者参与人时数、合作街道/医院数、论文/专利。还有什么是我们可能漏掉的、对评委更"
                "有说服力的证据维度？\n\n"
                "顺带帮我看一下：如果我们要把这个项目写成一份完整的 BP，跟那种纯创业的 BP 比，我们"
                "结构上应该有哪些不一样的章节？"
            ),
        ],
    },
    {
        "tag": "case-C 创业+公益（社会企业，乡村女性卫生，目标象限：右下）",
        "expected_quadrant": "(+innov_venture, -biz_public)",
        "expected_signals": ["社会企业", "公益创业", "受益人", "可持续模式", "影响力"],
        "turns": [
            (
                "我们的项目叫 BlossomBox，目标人群是乡镇寄宿制中学的青春期女生。我们做了 6 所学校"
                "的入校调研（贵州、云南、甘肃各 2 所，覆盖约 1800 名女生），发现两个核心问题：\n"
                "1. 经期物资获取不畅 —— 30% 的女生表示「每次都要等家长寄」，12% 在过去半年用过"
                "替代物（如纸巾、布条）；\n"
                "2. 经期知识严重匮乏 —— 76% 的女生没有上过任何经期教育课，对经期紊乱、痛经管理"
                "几乎无概念。\n\n"
                "我们的方案是把项目设计成一个「社会企业」：在学校里部署低价/免费物资取用点（含"
                "卫生巾、暖宝宝、止痛参考卡），同时配套一个轻量小程序，里面是经期百科 + 匿名问诊"
                "+ 同伴陪伴功能。\n\n"
                "我希望这个项目既能真的帮到这些女生，又能跑出一套可复制、可持续的运营模式。能不能"
                "先帮我判断一下：我们这个「社企」的定位合不合理？"
            ),
            (
                "运营方面我们目前是这么想的：\n\n"
                "**物资端（免费/低价）**：和一家国产卫生巾品牌（已在谈）合作，按出厂价 + 公益折扣"
                "给我们供货，平均成本 ≈ 0.8 元/片；学校设固定取用柜，每位女生每月可免费取 20 片，"
                "超出按 0.5 元/片象征性收费（用来缓解「无成本拿走过多」的问题，同时让学生有「选择权」"
                "感受）。\n\n"
                "**资金端（多元）**：\n"
                "- 政府/教育主管部门：申请「妇女儿童公益专项」，每校每年 2–3 万；\n"
                "- 企业 CSR：跟卫生巾品牌、保险公司、互联网公司谈赞助包；\n"
                "- C 端众筹：我们做了一个「为远方的她送一片月光」的产品化众筹包（49 元 = 100 片），"
                "走小红书、B 站；\n"
                "- 数据/咨询服务：把脱敏后的「乡村青春期健康洞察报告」卖给做相关产品的品牌方。\n\n"
                "请帮我分析：在这种「混合资金 + 不向受益人收主要费用」的模式里，最核心的财务风险"
                "在哪里？我们应该关注哪些指标？"
            ),
            (
                "影响力侧我们规划了三层指标：\n"
                "1. 输出（output）：覆盖学校数、覆盖女生数、发放卫生巾片数、教育课时数；\n"
                "2. 成果（outcome）：女生「曾经使用替代物」比例下降、「经期不缺课」比例提升、"
                "知识测验得分提升；\n"
                "3. 影响（impact）：女生学业完成率（毕业率/中考通过率）的中长期变化。\n\n"
                "采集方式上：物资发放可以从取用柜数据自动统计；态度/认知靠学期前后的匿名问卷；"
                "学业数据需要跟学校教务签数据共享备忘录。\n\n"
                "团队这边 5 个人：1 人做项目运营（曾在公益机构工作 3 年）、1 人做产品技术、"
                "1 人做品牌内容、1 人做政府/校方关系、1 人做财务/合规。\n\n"
                "我比较想知道两件事：（a）这种公益创业项目通常会被评委挑战哪些点？（b）我们的"
                "「不挣钱也跑得起来」的故事，要怎么用财务数据讲清楚？"
            ),
            (
                "我把财务模型展开一下，请你重点看是不是过于乐观或者结构上有问题：\n\n"
                "假设第 12 个月稳定运营 20 所学校：\n"
                "- 物资成本：20 校 × 300 女生/校 × 20 片/月 × 0.8 元 ≈ 9.6 万/月\n"
                "- 物资低价收入：20 × 300 × 6 片（超额平均） × 0.5 元 ≈ 1.8 万/月\n"
                "- 净物资支出 ≈ 7.8 万/月\n"
                "- 政府/教育专项：20 × 2.5 万/年 = 50 万/年 ≈ 4.2 万/月\n"
                "- 企业 CSR 包：4 个品牌 × 30 万/年 = 120 万/年 ≈ 10 万/月\n"
                "- 众筹 + 咨询服务：合计 30 万/年 ≈ 2.5 万/月\n"
                "- 人力 + 运营 + 内容：5 人 × 1.4 万 + 行政 1.5 万 ≈ 8.5 万/月\n"
                "- 净现金流（月）≈ -7.8 + 4.2 + 10 + 2.5 - 8.5 ≈ +0.4 万/月\n\n"
                "也就是说我们紧巴巴维持收支平衡。我担心的是：CSR 这一项波动很大，去年有今年没的"
                "情况很常见。你觉得在这种结构里，我们应该怎么设计「财务护栏」？"
            ),
            (
                "最后我想跟你聊一下我们参赛和长期发展的策略：\n"
                "我们打算同时报名「挑战杯」（公益赛道）和「互联网+」（公益创业赛道）。我了解到"
                "「挑战杯」更看重学术性 + 社会效益的逻辑链条；「互联网+」更看重模式可复制 + "
                "可持续性。\n\n"
                "针对这两个比赛，你觉得我们应该分别突出什么？另外我们这个项目本身是创业项目，"
                "但我们做的事情又有强公益属性，所以在写 BP 的时候，「商业模式」这一章应该怎么写"
                "才不显得违和？比如要不要专门写一章「双底线模型」？\n\n"
                "顺便希望你能给我一份「下一步关键任务清单」，按优先级排，1–8 条都行，越具体越好。"
            ),
        ],
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


def _summarize_turn(idx: int, turn_text: str, resp: dict[str, Any]) -> dict[str, Any]:
    track_vec = resp.get("track_vector") or {}
    diag = resp.get("diagnosis") or {}
    rubric = diag.get("rubric") or []
    triggered = diag.get("triggered_rules") or []
    trace = resp.get("agent_trace") or {}
    subs = trace.get("ability_subgraphs") or []
    ground = trace.get("ontology_grounding") or {}
    kg_hits = trace.get("neo4j_graph_hits") or []
    hyper = trace.get("hypergraph_student") or {}
    hyper_node_count = len((hyper.get("nodes") or []))
    hyper_edge_count = len((hyper.get("edges") or []))

    agent_responses: list[dict[str, str]] = []
    for ag in (trace.get("agent_responses") or []):
        if isinstance(ag, dict):
            agent_responses.append({
                "name": str(ag.get("agent_name") or ag.get("role") or ""),
                "snippet": _short(ag.get("content"), 200),
            })

    return {
        "turn": idx,
        "user_text_preview": _short(turn_text, 80),
        "logical_project_id": resp.get("logical_project_id"),
        "conversation_id": resp.get("conversation_id"),
        "track_vector": {
            "innov_venture": round(float(track_vec.get("innov_venture") or 0.0), 3),
            "biz_public": round(float(track_vec.get("biz_public") or 0.0), 3),
        },
        "project_stage_v2": resp.get("project_stage_v2"),
        "overall_score": diag.get("overall_score"),
        "rubric_top3": [
            {
                "item": r.get("item"),
                "score": r.get("score"),
                "weight": r.get("weight"),
                "evidence_chain_len": len(r.get("evidence_chain") or []),
            }
            for r in rubric[:3]
        ],
        "triggered_rules": [r.get("id") for r in triggered[:5]],
        "ability_subgraphs": [
            (s.get("id"), round(float(s.get("score") or 0), 2)) for s in subs
        ],
        "ontology_summary": _short(ground.get("summary_text"), 220),
        "ontology_coverage_ratio": ground.get("coverage_ratio"),
        "ontology_missing_count": len(ground.get("missing_concepts") or []),
        "kg_hits": len(kg_hits),
        "hypergraph_size": (hyper_node_count, hyper_edge_count),
        "assistant_excerpt": _short(resp.get("assistant_message"), 280),
        "agent_responses_preview": agent_responses[:3],
        "analysis_refresh": trace.get("analysis_refresh"),
    }


def run_case(case: dict[str, Any]) -> list[dict[str, Any]]:
    print(f"\n{'=' * 76}\n{case['tag']}\n  期望象限: {case['expected_quadrant']}\n{'=' * 76}")
    conv_id: str | None = None
    rows: list[dict[str, Any]] = []
    for i, turn_text in enumerate(case["turns"], 1):
        payload = {
            "project_id": PROJECT_ID,
            "student_id": STUDENT_ID,
            "message": turn_text,
            "conversation_id": conv_id,
            "mode": COMMON_MODE,
            "competition_type": COMMON_COMPETITION,
        }
        t0 = time.time()
        try:
            resp = _post("/api/dialogue/turn", payload, timeout=300)
        except urllib.error.URLError as exc:
            print(f"  ! Turn {i} 网络/超时: {exc}")
            return rows
        except Exception as exc:
            print(f"  ! Turn {i} 失败: {exc}")
            return rows
        dt = time.time() - t0
        if not conv_id:
            conv_id = resp.get("conversation_id")
        row = _summarize_turn(i, turn_text, resp)
        row["latency_s"] = round(dt, 1)
        rows.append(row)
        print(
            f"  Turn {i} ({dt:5.1f}s) pid={row['logical_project_id']} "
            f"track={row['track_vector']} stage={row['project_stage_v2']} "
            f"score={row['overall_score']} subs={[s[0] for s in row['ability_subgraphs']]} "
            f"cov={row['ontology_coverage_ratio']} kg={row['kg_hits']} "
            f"hyper={row['hypergraph_size']}"
        )
        # 短停顿避免对后端瞬时压力
        time.sleep(1.5)
    return rows


def main() -> int:
    all_rows: dict[str, list[dict[str, Any]]] = {}
    overall_t0 = time.time()
    for case in CASES:
        all_rows[case["tag"]] = run_case(case)

    out_path = "regression_final01.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, ensure_ascii=False, indent=2)
    total_dt = time.time() - overall_t0
    print(f"\n>>> 总耗时 {total_dt:.1f}s, 详细结果已写入 {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
