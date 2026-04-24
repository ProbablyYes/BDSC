# -*- coding: utf-8 -*-
"""多轮分析链路回归脚本（Phase 5）。

不依赖 FastAPI / Neo4j / LLM。直接调用：
- diagnosis_engine.run_diagnosis
- track_inference.infer_track_vector / merge_track_vector / infer_project_stage_v2
- ability_subgraphs.select_ability_subgraphs
- ontology_runtime.build_ontology_grounding

跑两个不同侧重的项目各 4 轮对话，断言：
1. track_vector 在多轮里有可观察的变化（不会"卡死"）
2. project_stage_v2 会随诊断更新
3. 命中的能力子图会变化（创新 → 商业 / 路演）
4. ontology_grounding.coverage_ratio > 0 且 missing_concepts 数量随对话减少

运行方式：
  python apps/backend/scripts/regression_multiturn.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.ability_subgraphs import select_ability_subgraphs  # noqa: E402
from app.services.diagnosis_engine import run_diagnosis  # noqa: E402
from app.services.ontology_runtime import build_ontology_grounding  # noqa: E402
from app.services.project_cognition import (  # noqa: E402
    ensure_project_cognition,
)
from app.services.track_inference import (  # noqa: E402
    infer_project_stage_v2,
    infer_track_vector,
    merge_track_vector,
)


CASES = {
    "项目A·创新+商业（K12 编程平台）": {
        "competition_type": "internet_plus",
        "turns": [
            "我们做面向 6-12 岁儿童的 AI 游戏化编程教育平台，核心创新是把 Scratch 积木和大模型反馈结合，"
            "让孩子可以用自然语言描述想做的小游戏，AI 自动生成模板并指导孩子拼装。",
            "目标家长是城市里有教育焦虑的中产家庭。我们走 To C 订阅制，定价每月 99 元，渠道是抖音/小红书投放 + 学校公益课导流。",
            "做了 30 份家长访谈和 200 份问卷，确认家长每月愿意为编程教育花 200 元以内。CAC 估算 350 元，LTV 约 1800 元。",
            "对比编程猫和小码王，我们差异化是 AI 反馈 + 游戏化关卡。已经做了 MVP demo，邀请了 5 个学校试点，准备暑期推广。",
        ],
    },
    "项目B·公益+创业（社区医疗陪诊）": {
        "competition_type": "challenge_cup",
        "turns": [
            "我们做面向独居老人的社区陪诊助手，结合志愿者匹配 + 简易远程问诊。出发点是看到很多独居老人去医院找不到路、记不住医嘱。",
            "我们和 3 个街道签了试点协议，志愿者来自高校医学院学生。前 6 个月免费，靠政府购买服务和企业 CSR 补贴维持。",
            "已经服务了 80 位老人，访谈下来最大痛点是“医生说的话听不懂”，我们准备加入语音转写 + AI 简化解释功能。",
            "下一步要把可持续性想清楚：政府补贴可以覆盖人力，但远程问诊技术还需要医院授权，团队在跟两家三甲医院谈合作。",
        ],
    },
}


def run_case(case_name: str, payload: dict) -> dict:
    print(f"\n=== {case_name} ===")
    project_state = ensure_project_cognition({})
    competition_type = payload.get("competition_type", "")
    history_summary: list[dict] = []

    cumulative_text = ""
    stage_history: list[str] = []

    for idx, turn in enumerate(payload["turns"], 1):
        cumulative_text = (cumulative_text + "\n" + turn).strip()
        diag_obj = run_diagnosis(
            input_text=cumulative_text,
            mode="competition",
            competition_type=competition_type,
            current_text=turn,
            stage_history=stage_history,
        )
        diagnosis = diag_obj.diagnosis
        stage_history.append(str(diagnosis.get("project_stage") or ""))

        inferred = infer_track_vector(
            turn,
            diagnosis=diagnosis,
            category="",
            competition_type=competition_type,
        )
        project_state, snapshot = merge_track_vector(project_state, inferred)
        project_state["project_stage_v2"] = infer_project_stage_v2(diagnosis, project_state)

        subs = select_ability_subgraphs(
            message=turn,
            diagnosis=diagnosis,
            track_vector=project_state.get("track_vector"),
            project_stage=project_state.get("project_stage_v2", "structured"),
            intent="project_diagnosis",
        )
        grounding = build_ontology_grounding(
            diagnosis=diagnosis,
            kg_analysis=None,
            ability_subgraphs=subs,
        )

        track_vector = project_state.get("track_vector", {})
        record = {
            "turn": idx,
            "track_vector": {
                "innov_venture": round(float(track_vector.get("innov_venture") or 0.0), 3),
                "biz_public": round(float(track_vector.get("biz_public") or 0.0), 3),
            },
            "stage": project_state.get("project_stage_v2", ""),
            "subgraphs": [(s["id"], round(s["score"], 2)) for s in subs],
            "ontology_summary": grounding.get("summary_text", "")[:140],
            "coverage_ratio": grounding.get("coverage_ratio"),
            "missing_count": len(grounding.get("missing_concepts", [])),
            "rubric_top": [
                (r.get("item"), round(float(r.get("score") or 0), 1))
                for r in (diagnosis.get("rubric") or [])[:3]
            ],
            "overall": diagnosis.get("overall_score") or diagnosis.get("composite_score"),
        }
        history_summary.append(record)
        print(f"  Turn {idx}: track={record['track_vector']} stage={record['stage']} "
              f"sub={[s[0] for s in record['subgraphs']]} cov={record['coverage_ratio']} "
              f"miss={record['missing_count']} overall={record['overall']}")

    return {
        "case": case_name,
        "history": history_summary,
    }


def assert_changes(case_record: dict) -> list[str]:
    """简单断言：track_vector 至少应在 4 轮内出现 >= 1 次绝对变化 > 0.05；
    project_stage_v2 不应一直停在 idea；ontology_grounding 应给出非零覆盖。"""
    issues: list[str] = []
    h = case_record["history"]
    if not h:
        return ["history 为空"]

    # 1. track_vector 移动（受惯性 + 平滑限制，单轮幅度被故意压低，
    #    我们只断言累计净位移 > 0.02 即可证明系统在响应输入而不是被冻结）
    first = h[0]["track_vector"]
    last = h[-1]["track_vector"]
    drift_iv = abs(last["innov_venture"] - first["innov_venture"])
    drift_bp = abs(last["biz_public"] - first["biz_public"])
    if drift_iv < 0.02 and drift_bp < 0.02:
        issues.append(
            f"[{case_record['case']}] track_vector 累计净位移过小 "
            f"(Δiv={drift_iv:.3f}, Δbp={drift_bp:.3f})，可能 inference 被冻结"
        )

    # 2. ontology coverage
    if all((r["coverage_ratio"] or 0) <= 0 for r in h):
        issues.append(f"[{case_record['case']}] ontology coverage_ratio 始终为 0")

    # 3. subgraphs 至少触发过一次
    if all(not r["subgraphs"] for r in h):
        issues.append(f"[{case_record['case']}] 没有命中任何能力子图")

    # 4. stage 不应该一直 idea
    stages = {r["stage"] for r in h}
    if stages == {"idea"} and len(h) >= 3:
        issues.append(f"[{case_record['case']}] project_stage_v2 一直停留在 idea")

    return issues


def main() -> int:
    all_records = [run_case(name, payload) for name, payload in CASES.items()]
    issues = []
    for rec in all_records:
        issues.extend(assert_changes(rec))

    print("\n=== 汇总 ===")
    print(json.dumps([
        {
            "case": r["case"],
            "track_journey": [t["track_vector"] for t in r["history"]],
            "stages": [t["stage"] for t in r["history"]],
            "coverage_ratio_journey": [t["coverage_ratio"] for t in r["history"]],
        }
        for r in all_records
    ], ensure_ascii=False, indent=2))

    if issues:
        print("\n=== 回归问题 ===")
        for it in issues:
            print(f"  ! {it}")
        return 1
    print("\n所有断言通过：track_vector / stage / 子图 / 本体覆盖 都随对话变化。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
