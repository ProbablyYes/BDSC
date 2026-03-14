"""
Lightweight intent-based multi-agent router inspired by LangGraph.

Each user message is classified into an *intent*, which maps to a specific
agent pipeline (a subgraph of nodes). Only the relevant agents are called,
keeping latency low while preserving depth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.llm_client import LlmClient

llm = LlmClient()

# ── Intent definitions ─────────────────────────────────────────────

INTENTS = {
    "idea_brainstorm": {
        "description": "学生想要创业灵感/点子/方向建议",
        "keywords": ["点子", "想法", "灵感", "方向", "做什么好", "有什么好", "不知道做什么"],
        "pipeline": ["coach", "composer"],
    },
    "project_diagnosis": {
        "description": "学生描述项目并希望获得诊断/风险分析",
        "keywords": ["我想做", "我的项目", "产品是", "我们做的", "分析一下", "怎么样", "可行吗", "痛点"],
        "pipeline": ["diagnosis", "coach", "critic", "composer"],
    },
    "evidence_check": {
        "description": "学生想验证证据充分性/补充证据",
        "keywords": ["访谈", "问卷", "调研", "证据", "用户", "验证", "数据", "样本"],
        "pipeline": ["diagnosis", "coach", "composer"],
    },
    "business_model": {
        "description": "学生讨论商业模式/盈利/市场规模",
        "keywords": ["商业模式", "盈利", "收入", "成本", "市场规模", "tam", "sam", "som", "cac", "ltv", "定价", "渠道"],
        "pipeline": ["diagnosis", "coach", "critic", "composer"],
    },
    "competition_prep": {
        "description": "学生准备路演/竞赛/答辩",
        "keywords": ["路演", "竞赛", "答辩", "比赛", "评委", "ppt", "演讲", "展示"],
        "pipeline": ["diagnosis", "competition", "critic", "composer"],
    },
    "pressure_test": {
        "description": "学生要求压力测试/反驳/挑战",
        "keywords": ["压力测试", "挑战", "反驳", "护城河", "巨头", "如果", "竞争对手"],
        "pipeline": ["diagnosis", "critic", "composer"],
    },
    "learning_concept": {
        "description": "学生想学习创业概念/方法论",
        "keywords": ["什么是", "怎么做", "教我", "学习", "方法", "理论", "概念", "lean canvas", "mvp"],
        "pipeline": ["learning", "composer"],
    },
    "general_chat": {
        "description": "闲聊/问好/不明确意图",
        "keywords": [],
        "pipeline": ["composer"],
    },
}


@dataclass
class IntentResult:
    intent: str
    confidence: float
    pipeline: list[str]
    matched_keywords: list[str] = field(default_factory=list)
    engine: str = "rule"


def classify_intent(message: str) -> IntentResult:
    text = message.lower().strip()
    scores: list[tuple[str, float, list[str]]] = []

    for intent_id, spec in INTENTS.items():
        keywords = spec.get("keywords", [])
        matched = [k for k in keywords if k in text]
        score = len(matched) / max(len(keywords), 1) if keywords else 0.0
        if matched:
            score += 0.3
        scores.append((intent_id, score, matched))

    scores.sort(key=lambda x: x[1], reverse=True)
    best_intent, best_score, best_matched = scores[0]

    if best_score < 0.15:
        if len(text) > 60:
            return IntentResult(
                intent="project_diagnosis",
                confidence=0.5,
                pipeline=INTENTS["project_diagnosis"]["pipeline"],
                engine="rule-fallback",
            )
        return IntentResult(
            intent="general_chat",
            confidence=0.4,
            pipeline=INTENTS["general_chat"]["pipeline"],
            engine="rule-fallback",
        )

    return IntentResult(
        intent=best_intent,
        confidence=min(1.0, best_score),
        pipeline=list(INTENTS[best_intent]["pipeline"]),
        matched_keywords=best_matched,
        engine="rule",
    )


# ── Pipeline executor ──────────────────────────────────────────────

def run_pipeline(
    intent: IntentResult,
    message: str,
    mode: str,
    project_state: dict,
    history_context: str = "",
) -> dict[str, Any]:
    """Execute the agent pipeline for a classified intent."""
    from app.services.diagnosis_engine import run_diagnosis
    from app.services.case_knowledge import infer_category, retrieve_cases_by_category

    result: dict[str, Any] = {
        "intent": intent.intent,
        "confidence": intent.confidence,
        "pipeline": intent.pipeline,
        "engine": intent.engine,
    }

    diagnosis = {}
    next_task = {}
    category = infer_category(message)
    references = []

    if "diagnosis" in intent.pipeline:
        diag = run_diagnosis(input_text=message, mode=mode)
        diagnosis = diag.diagnosis
        next_task = diag.next_task
        result["diagnosis"] = diagnosis
        result["next_task"] = next_task

    if "coach" in intent.pipeline:
        references = retrieve_cases_by_category(category, limit=2)
        result["category"] = category
        result["references"] = references

    critic_data = {}
    if "critic" in intent.pipeline and diagnosis:
        rules = diagnosis.get("triggered_rules", [])
        bottleneck = diagnosis.get("bottleneck", "")
        if llm.enabled:
            critic_data = llm.chat_json(
                system_prompt=(
                    "你是Critic Agent（压力测试官）。请对项目做反事实挑战。输出JSON: "
                    "challenge_questions(list，3个苏格拉底式压力追问), "
                    "missing_evidence(list，缺失的证据), "
                    "risk_summary(string，一句话风险总结)。"
                ),
                user_prompt=f"学生说:{message}\n瓶颈:{bottleneck}\n规则:{rules}",
                temperature=0.25,
            )
        if not critic_data:
            critic_data = {
                "challenge_questions": ["如果用户不花钱也能解决，你的产品意义在哪？"],
                "missing_evidence": [],
                "risk_summary": bottleneck,
            }
        result["critic"] = critic_data

    competition_data = {}
    if "competition" in intent.pipeline:
        if llm.enabled:
            competition_data = llm.chat_json(
                system_prompt=(
                    "你是竞赛评审顾问。输出JSON: "
                    "judge_questions(list，评委可能问的3个尖锐问题), "
                    "defense_tips(list，3个答辩技巧), "
                    "presentation_structure(list，建议的路演结构)。"
                ),
                user_prompt=f"项目描述:{message}\n模式:{mode}",
                temperature=0.25,
            )
        result["competition"] = competition_data

    learning_data = {}
    if "learning" in intent.pipeline:
        if llm.enabled:
            learning_data = llm.chat_json(
                system_prompt=(
                    "你是创新创业课程导师。输出JSON: "
                    "definition(概念解释), example(具体例子), "
                    "practice_task(一个可执行的练习), common_mistakes(list，常见错误)。"
                ),
                user_prompt=f"学生问:{message}",
                temperature=0.3,
            )
        result["learning"] = learning_data

    result["category"] = category
    result["references"] = references
    result["history_context"] = history_context

    return result


# ── Composer system prompts per intent ────────────────────────────

INTENT_PROMPTS: dict[str, str] = {
    "idea_brainstorm": (
        "学生想要创业点子/灵感。请基于诊断上下文，给出2-3个有针对性的创业方向建议，"
        "每个方向用1-2句话说明目标用户和核心价值。最后引导学生选择一个方向深入探索。"
    ),
    "project_diagnosis": (
        "学生描述了项目。请先肯定可取之处，再指出1-2个最关键的风险，"
        "给出明确的下一步唯一任务，用苏格拉底式追问收尾。"
    ),
    "evidence_check": (
        "学生在讨论证据/调研。请评估当前证据的充分性，"
        "指出还缺什么证据，给出具体的补证方法和验收标准。"
    ),
    "business_model": (
        "学生在讨论商业模式。请用通俗语言分析商业逻辑是否闭环，"
        "如有漏洞指出具体问题，给出修正建议。"
    ),
    "competition_prep": (
        "学生在准备竞赛/路演。请模拟评委视角提出尖锐问题，"
        "给出答辩技巧和路演结构建议。"
    ),
    "pressure_test": (
        "学生要求压力测试。请扮演'毒舌评委'，连续追问3个尖锐问题，"
        "每个问题都直击项目软肋，但语气专业不刻薄。"
    ),
    "learning_concept": (
        "学生想学创业概念。请用通俗易懂的方式解释概念，"
        "举一个生动的例子，最后给一个可执行的练习任务。"
    ),
    "general_chat": (
        "学生在闲聊。请热情回应，然后自然引导到项目话题，"
        "可以问学生目前项目进展如何，或推荐一个有趣的创业思考题。"
    ),
}
