from typing import Any

from app.services.case_knowledge import (
    category_patterns,
    infer_category,
    retrieve_cases_by_category,
)
from app.services.diagnosis_engine import run_diagnosis


def student_learning_agent(prompt: str, mode: str = "coursework") -> dict[str, Any]:
    text = prompt.strip()
    if not text:
        text = "请解释什么是创新创业项目中的问题定义，并给出一个可执行练习。"

    return {
        "agent": "student_learning",
        "mode": mode,
        "definition": "问题定义是将抽象想法收敛到具体用户、具体场景和可验证痛点的过程。",
        "example": "目标用户为大一新生，场景为夜间找空教室，痛点是信息分散导致时间浪费。",
        "common_mistakes": ["只谈愿景不谈用户证据", "把功能当痛点", "没有反证样本"],
        "practice_task": "访谈5位目标用户，整理出现频次最高的3个痛点并给出原话证据。",
        "expected_artifact": "访谈记录表 + 痛点频次统计表",
        "evaluation_criteria": ["有真实引用", "痛点可量化", "结论和证据一致"],
    }


def project_coach_agent(input_text: str, mode: str = "coursework") -> dict[str, Any]:
    result = run_diagnosis(input_text=input_text, mode=mode)
    category = infer_category(input_text)
    references = retrieve_cases_by_category(category, limit=3)
    return {
        "agent": "project_coach",
        "category_inference": category,
        "diagnosis": result.diagnosis,
        "next_task": result.next_task,
        "reference_cases": references,
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
                "estimated_score_0_5": round(score / 2, 1),
                "missing_evidence": "需要补充可验证证据链" if row["status"] == "risk" else "证据基础可继续增强",
                "minimal_fix_24h": "补充至少2条数据证据并更新对照表",
                "minimal_fix_72h": "完成一次小规模验证并更新财务假设",
            }
        )
    return {
        "agent": "competition_advisor",
        "category_inference": category,
        "rubric_advice": rubric_rows,
        "benchmark_cases": references,
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

    return {
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
