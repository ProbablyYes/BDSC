from typing import Any

from app.services.case_knowledge import (
    category_patterns,
    infer_category,
    retrieve_cases_by_category,
)
from app.services.diagnosis_engine import run_diagnosis
from app.services.llm_client import LlmClient

llm = LlmClient()

_GHOSTWRITE_PATTERNS = [
    "直接帮我写", "帮我写完整", "直接写完", "可直接提交", "直接提交的文本", "代写", "你替我写",
]


def _json_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x) for x in value if x is not None][:6]


def student_learning_agent(prompt: str, mode: str = "coursework") -> dict[str, Any]:
    text = prompt.strip()
    if not text:
        text = "请解释什么是创新创业项目中的问题定义，并给出一个可执行练习。"

    if any(p in text for p in _GHOSTWRITE_PATTERNS):
        return {
            "agent": "student_learning",
            "mode": mode,
            "definition": "我不能直接替你代写可直接提交的课程内容，因为学习辅导的目标是帮你学会推理和表达。",
            "example": "如果你在写商业计划书，我可以帮你拆结构、补逻辑、改表达，但不会直接生成整段可提交正文。",
            "common_mistakes": ["把学习辅导当代写工具", "直接要成稿而不先想核心判断", "没有先整理已有证据和要点"],
            "practice_task": "先用3句话写出你这一段最想表达的核心判断、支撑证据和你最没把握的地方。",
            "expected_artifact": "3句话的段落提纲 + 你已有的2条证据或例子",
            "evaluation_criteria": ["能看出你的核心判断", "能指出证据是否足够", "能据此继续进行苏格拉底式追问"],
            "socratic_questions": [
                "这一段你最想说服老师接受的核心判断到底是什么？",
                "你现在手里已经有哪些数据、案例或用户原话能支持这个判断？",
                "如果只能保留两个小标题，你觉得应该保留哪两个，为什么？",
            ],
            "engine": "guardrail",
        }

    if llm.enabled:
        llm_resp = llm.chat_json(
            system_prompt=(
                "你是创新创业课程学习导师。请输出JSON，字段为"
                "definition, example, common_mistakes(list), practice_task, expected_artifact, evaluation_criteria(list)。"
                "要求：practice_task 只能有一个，而且必须可执行、可验收；"
                "如果学生问如何写，优先解释思路和结构，不要替他直接代写成稿。"
            ),
            user_prompt=f"模式:{mode}\n学生问题:\n{text}",
            temperature=0.3,
        )
        if llm_resp:
            return {
                "agent": "student_learning",
                "mode": mode,
                "definition": str(llm_resp.get("definition") or ""),
                "example": str(llm_resp.get("example") or ""),
                "common_mistakes": _json_list(llm_resp.get("common_mistakes")),
                "practice_task": str(llm_resp.get("practice_task") or ""),
                "expected_artifact": str(llm_resp.get("expected_artifact") or ""),
                "evaluation_criteria": _json_list(llm_resp.get("evaluation_criteria")),
                "engine": "llm",
            }

    return {
        "agent": "student_learning",
        "mode": mode,
        "definition": "问题定义是将抽象想法收敛到具体用户、具体场景和可验证痛点的过程。",
        "example": "目标用户为大一新生，场景为夜间找空教室，痛点是信息分散导致时间浪费。",
        "common_mistakes": ["只谈愿景不谈用户证据", "把功能当痛点", "没有反证样本"],
        "practice_task": "访谈5位目标用户，整理出现频次最高的3个痛点并给出原话证据。",
        "expected_artifact": "访谈记录表 + 痛点频次统计表",
        "evaluation_criteria": ["有真实引用", "痛点可量化", "结论和证据一致"],
        "engine": "rule",
    }


def project_coach_agent(input_text: str, mode: str = "coursework") -> dict[str, Any]:
    result = run_diagnosis(input_text=input_text, mode=mode)
    category = infer_category(input_text)
    references = retrieve_cases_by_category(category, limit=3)
    diagnosis = result.diagnosis
    next_task = result.next_task

    if llm.enabled:
        llm_patch = llm.chat_json(
            system_prompt=(
                "你是双创项目教练（Socratic）。基于给定诊断，输出JSON字段："
                "bottleneck_refined, socratic_questions(list), next_task_title, next_task_description, acceptance_criteria(list)。"
            ),
            user_prompt=(
                f"模式:{mode}\n类别:{category}\n"
                f"输入文本:\n{input_text}\n"
                f"现有诊断:\n{diagnosis}\n"
                f"参考案例:\n{references}"
            ),
            model=None,
            temperature=0.3,
        )
        if llm_patch:
            if llm_patch.get("bottleneck_refined"):
                diagnosis["bottleneck"] = str(llm_patch["bottleneck_refined"])
            if llm_patch.get("socratic_questions"):
                diagnosis["socratic_questions"] = _json_list(llm_patch.get("socratic_questions"))
            # 浅合并：保留原 next_task 的 template_guideline / rationale / linked rule，
            # 只覆盖 LLM 明确给出的字段。
            merged_next_task: dict[str, Any] = dict(next_task or {})
            llm_title = str(llm_patch.get("next_task_title") or "").strip()
            llm_desc = str(llm_patch.get("next_task_description") or "").strip()
            llm_ac = _json_list(llm_patch.get("acceptance_criteria"))
            if llm_title:
                merged_next_task["title"] = llm_title
            if llm_desc:
                merged_next_task["description"] = llm_desc
            if llm_ac:
                merged_next_task["acceptance_criteria"] = llm_ac
            # 若 LLM 同时给了 steps（兼容旧 JSON schema），映射为 template_guideline
            llm_steps = _json_list(llm_patch.get("steps"))
            if llm_steps:
                merged_next_task["template_guideline"] = llm_steps[:6]
            # 更新 rationale：把 LLM 教练的产出作为新的推理链步骤
            base_rat = merged_next_task.get("rationale") if isinstance(merged_next_task.get("rationale"), dict) else None
            if base_rat and (llm_title or llm_desc):
                steps_acc = list(base_rat.get("reasoning_steps") or [])
                steps_acc.append({
                    "kind": "evidence",
                    "label": f"项目教练智能体细化任务 → {merged_next_task.get('title', '')}",
                    "detail": (merged_next_task.get("description") or "")[:120],
                    "agent_name": "项目教练 Coach",
                })
                for st in (llm_ac or [])[:4]:
                    steps_acc.append({
                        "kind": "evidence",
                        "label": f"验收标准：{str(st)[:80]}",
                        "agent_name": "项目教练 Coach",
                    })
                base_rat["reasoning_steps"] = steps_acc
                base_rat["value"] = merged_next_task.get("title", base_rat.get("value", ""))
                merged_next_task["rationale"] = base_rat
            next_task = merged_next_task

    return {
        "agent": "project_coach",
        "category_inference": category,
        "diagnosis": diagnosis,
        "next_task": next_task,
        "reference_cases": references,
        "engine": "llm+rule" if llm.enabled else "rule",
    }


def competition_advisor_agent(input_text: str, mode: str = "coursework") -> dict[str, Any]:
    diagnosis = run_diagnosis(input_text=input_text, mode=mode).diagnosis
    category = infer_category(input_text)
    references = retrieve_cases_by_category(category, limit=3)
    rubric_rows = []
    for row in diagnosis.get("rubric", []):
        score = row["score"]
        rubric_rows.append(
            {
                "item": row["item"],
                "estimated_score_0_10": round(score, 2),
                "estimated_score_0_5": round(score / 2, 1),
                "missing_evidence": "需要补充可验证证据链" if row["status"] == "risk" else "证据基础可继续增强",
                "minimal_fix_24h": "补充至少2条数据证据并更新对照表",
                "minimal_fix_72h": "完成一次小规模验证并更新财务假设",
            }
        )

    if llm.enabled:
        llm_advice = llm.chat_json(
            system_prompt=(
                "你是竞赛评审顾问。输出JSON字段：judge_questions(list), defense_tips(list), prize_readiness(0-100)。"
            ),
            user_prompt=f"输入:\n{input_text}\nrubric:\n{rubric_rows}",
            model=None,
            temperature=0.2,
        )
    else:
        llm_advice = {}

    return {
        "agent": "competition_advisor",
        "category_inference": category,
        "rubric_advice": rubric_rows,
        "benchmark_cases": references,
        "judge_questions": _json_list(llm_advice.get("judge_questions")),
        "defense_tips": _json_list(llm_advice.get("defense_tips")),
        "prize_readiness": int(llm_advice.get("prize_readiness") or 0),
        "engine": "llm+rule" if llm.enabled else "rule",
    }


def instructor_assistant_agent(project_state: dict[str, Any]) -> dict[str, Any]:
    submissions = project_state.get("submissions", [])
    feedback = project_state.get("teacher_feedback", [])
    high_risk = 0
    total_rules = 0
    rule_count: dict[str, int] = {}

    for sub in submissions:
        diagnosis = sub.get("diagnosis", {})
        triggered = diagnosis.get("triggered_rules", [])
        if any(item.get("severity") == "high" for item in triggered):
            high_risk += 1
        for item in triggered:
            rid = item.get("id", "UNKNOWN")
            rule_count[rid] = rule_count.get(rid, 0) + 1
            total_rules += 1

    top_rules = sorted(rule_count.items(), key=lambda x: x[1], reverse=True)[:5]
    top_rule_names = [f"{rid}: {count}" for rid, count in top_rules]
    base_result = {
        "agent": "instructor_assistant",
        "class_coverage_summary": {
            "submission_count": len(submissions),
            "feedback_count": len(feedback),
            "high_risk_ratio": 0 if not submissions else round(high_risk / len(submissions), 2),
            "triggered_rule_total": total_rules,
        },
        "top_common_mistakes": top_rule_names,
        "reference_category_patterns": category_patterns(),
        "suggested_interventions": [
            "下周先讲客户-价值主张一致性，并要求提交证据对照表。",
            "设置一次15分钟课堂压力测试，重点挑战无竞争与伪市场规模论证。",
        ],
    }

    if llm.enabled:
        llm_rec = llm.chat_json(
            system_prompt=(
                "你是教师助教Agent。根据班级数据生成JSON字段："
                "class_warning(list), interventions(list), next_week_focus(list)。"
            ),
            user_prompt=f"project_state={project_state}\nbase={base_result}",
            temperature=0.2,
        )
        if llm_rec:
            base_result["class_warning"] = _json_list(llm_rec.get("class_warning"))
            base_result["suggested_interventions"] = _json_list(llm_rec.get("interventions")) or base_result[
                "suggested_interventions"
            ]
            base_result["next_week_focus"] = _json_list(llm_rec.get("next_week_focus"))

    base_result["engine"] = "llm+rule" if llm.enabled else "rule"
    return base_result
