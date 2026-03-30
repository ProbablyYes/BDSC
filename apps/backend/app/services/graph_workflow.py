"""
LangGraph multi-agent system for VentureAgent (V5).

Architecture: Static Foundation + Dynamic Agents
═══════════════════════════════════════════════════

Layer 0 — Router
  Classify user intent via keyword scoring + LLM fallback.

Layer 1 — Static Foundation (ALWAYS runs, ensures data consistency)
  Parallel I/O tasks that produce deterministic, reproducible data:
   • Diagnosis Engine  (rule-based)  → rubric scores, risk rules, bottleneck
   • KG Extraction     (structured LLM) → entities, relationships, section_scores
   • RAG Retrieval     (vector search)  → similar cases
   • Hypergraph Analysis (rules + LLM insight) → coverage, value loops, patterns
  Conditionally enhanced:
   • Web Search → when intent or message keywords suggest external info

Layer 2 — Agent Selection (hybrid: static rules + dynamic heuristics)
  STATIC RULES (non-negotiable, guarantee consistency):
   • File upload            → Coach + Grader + Planner
   • competition mode/intent → + Advisor
   • Explicit scoring request → + Grader
  DYNAMIC HEURISTICS (data-driven, provide flexibility):
   • Coach   : diagnosis risks > 0 OR KG entities ≥ 2 OR project intent
   • Analyst : high-severity risks OR pressure_test intent
   • Tutor   : learning mode inside complex context
   • Planner : sufficient KG context AND project intent
  FOCUSED INTENTS (skip agents, orchestrator single-call):
   • market_competitor, learning_concept, idea_brainstorm, general_chat
  Selected agents execute serially; each sees output of preceding agents.

Layer 3 — Orchestrator
  Multi-agent synthesis (complex) or focused single-call (simple).

Total serial LLM groups: 3  (foundation ‖ agents → orchestrator)
"""

from __future__ import annotations

import logging
import operator
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, StateGraph

from app.config import settings
from app.services.llm_client import LlmClient

logger = logging.getLogger(__name__)
_llm = LlmClient()

_rag = None
_graph_service = None
_hypergraph_service = None


def init_workflow_services(rag_engine=None, graph_service=None, hypergraph_service=None):
    global _rag, _graph_service, _hypergraph_service
    _rag = rag_engine
    _graph_service = graph_service
    _hypergraph_service = hypergraph_service


# ═══════════════════════════════════════════════════════════════════
#  Workflow State
# ═══════════════════════════════════════════════════════════════════

class WorkflowState(TypedDict, total=False):
    message: str
    mode: str
    project_state: dict
    history_context: str
    conversation_messages: list
    teacher_feedback_context: str

    intent: str
    intent_confidence: float
    intent_shape: str
    intent_reason: str
    intent_pipeline: list[str]
    intent_engine: str
    resolved_agents: list[str]
    agent_reasoning: str

    coach_output: dict
    analyst_output: dict
    advisor_output: dict
    tutor_output: dict
    grader_output: dict
    planner_output: dict

    category: str
    diagnosis: dict
    next_task: dict
    kg_analysis: dict
    rag_cases: list
    rag_context: str
    web_search_result: dict
    hypergraph_insight: dict
    hypergraph_student: dict
    critic: dict
    challenge_strategies: list
    pressure_test_trace: dict
    competition: dict
    learning: dict
    needs_clarification: bool
    clarification_reason: str
    clarification_questions: list[str]
    clarification_missing: list[str]

    assistant_message: str
    agents_called: Annotated[list[str], operator.add]
    nodes_visited: Annotated[list[str], operator.add]


# ═══════════════════════════════════════════════════════════════════
#  Intent → Agent mapping
# ═══════════════════════════════════════════════════════════════════

INTENTS: dict[str, dict] = {
    "idea_brainstorm": {
        "keywords": ["点子", "想法", "灵感", "方向", "做什么好", "有什么好",
                      "不知道做什么", "创业方向", "还没想好",
                      "什么方向", "推荐", "建议做什么", "有什么项目"],
        "desc": "学生想要创业点子/方向建议",
        "agents": ["coach"],
        "need_web": True, "web_results": 3,
        "focused": True,
    },
    "project_diagnosis": {
        "keywords": ["我想做", "我的项目", "产品是", "我们做的", "分析一下",
                      "怎么样", "可行吗", "痛点", "商业计划", "帮我看看",
                      "打算做", "项目是", "我们的产品", "想做一个",
                      "可以吗", "有没有问题", "帮我分析", "评价一下",
                      "打分", "评分", "得分", "几分"],
        "desc": "学生描述项目并希望获得诊断",
        "agents": ["coach"],
        "need_web": False,
    },
    "evidence_check": {
        "keywords": ["访谈", "问卷", "调研", "证据", "用户", "验证",
                      "数据", "样本", "反馈", "需求调研",
                      "调查", "测试", "用户研究", "实地", "采访"],
        "desc": "学生讨论证据/调研",
        "agents": ["analyst"],
        "need_web": False,
    },
    "business_model": {
        "keywords": ["商业模式", "盈利", "收入", "成本", "市场规模",
                      "tam", "sam", "som", "cac", "ltv", "定价", "渠道",
                      "赚钱", "营收", "变现", "价格", "怎么盈利", "收费"],
        "desc": "学生讨论商业模式",
        "agents": ["coach"],
        "need_web": True, "web_results": 2,
    },
    "competition_prep": {
        "keywords": ["路演", "竞赛", "答辩", "比赛", "评委",
                      "ppt", "演讲", "展示", "互联网+", "挑战杯",
                      "备赛", "获奖", "演示", "展板"],
        "desc": "学生准备竞赛/路演",
        "agents": ["advisor"],
        "need_web": True, "web_results": 3,
    },
    "market_competitor": {
        "keywords": ["竞品", "类似", "对手", "同类", "市面上", "行业",
                      "对标", "参考", "借鉴", "有没有什么", "有哪些",
                      "别人怎么做", "类似的", "替代品", "竞争者",
                      "先行者", "已有的", "现有产品", "同类产品",
                      "有什么软件", "有什么平台", "有什么app"],
        "desc": "学生想了解市场竞品/类似产品",
        "agents": ["tutor"],
        "need_web": True, "web_results": 5,
        "focused": True,
    },
    "pressure_test": {
        "keywords": ["压力测试", "挑战", "反驳", "护城河", "巨头",
                      "如果", "竞争对手", "为什么不",
                      "质疑", "弱点", "风险", "万一"],
        "desc": "学生要求压力测试",
        "agents": ["analyst"],
        "need_web": False,
    },
    "learning_concept": {
        "keywords": ["什么是", "怎么做", "教我", "学习", "方法", "理论",
                      "概念", "lean canvas", "mvp", "商业画布",
                      "解释一下", "是什么意思", "举例", "怎么理解"],
        "desc": "学生想学创业概念/方法论",
        "agents": ["tutor"],
        "need_web": True, "web_results": 3,
        "focused": True,
    },
    "general_chat": {
        "keywords": [],
        "desc": "闲聊/问好",
        "agents": ["coach"],
        "need_web": False,
        "focused": True,
    },
}

_FOCUSED_INTENTS = frozenset(k for k, v in INTENTS.items() if v.get("focused"))

_FOLLOW_UP_SIGNALS = frozenset([
    "继续", "然后呢", "详细说说", "还有呢", "接着说", "展开讲讲",
    "怎么办", "具体怎么做", "再说说", "举个例子", "好的然后",
    "下一步", "还有吗", "具体一点", "深入讲讲", "更详细",
    "好的", "明白了", "收到", "ok", "嗯",
])

_COMPLEX_QUERY_SIGNALS = frozenset([
    "1.", "2.", "3.", "一是", "二是", "三是", "第一", "第二", "第三",
    "另外", "还有", "以及", "同时", "分别", "各自", "多个", "几个问题",
])

_DISCOVERY_INTENTS = frozenset([
    "idea_brainstorm", "project_diagnosis", "business_model", "competition_prep",
])

_VAGUE_PROJECT_SIGNALS = frozenset([
    "有个想法", "一个想法", "想做一个", "大概想做", "还没想好", "还不太确定",
    "先聊聊", "还在想", "可能做", "初步想法", "雏形", "暂时没有", "还没明确",
])

_USER_SLOT_HINTS = frozenset([
    "学生", "老师", "研究生", "本科生", "博士", "程序员", "开发者", "用户",
    "商家", "农民", "家长", "企业", "创业者", "医院", "医生", "患者",
])

_SOLUTION_SLOT_HINTS = frozenset([
    "工具", "平台", "系统", "助手", "产品", "服务", "app", "应用", "插件",
    "模型", "机器人", "小程序", "网站", "功能", "软件",
])

_PAIN_SLOT_HINTS = frozenset([
    "问题", "痛点", "麻烦", "低效", "困难", "不方便", "太慢", "成本高",
    "耗时", "费劲", "负担", "不知道", "难以", "不踏实",
])


def _normalize_intent_shape(shape: Any, default: str = "single") -> str:
    value = str(shape or default).strip().lower()
    return value if value in {"single", "mixed"} else default


def _keyword_score_table(text: str) -> dict[str, dict[str, Any]]:
    table: dict[str, dict[str, Any]] = {}
    for iid, spec in INTENTS.items():
        kws = spec.get("keywords", [])
        matched = [k for k in kws if k in text]
        score = (len(matched) / max(len(kws), 1) + 0.3) if matched else 0.0
        table[iid] = {
            "matched": matched,
            "score": score,
        }
    return table


def _infer_intent_shape(message: str, score_table: dict[str, dict[str, Any]], conversation_messages: list | None = None) -> tuple[str, list[str]]:
    conv = conversation_messages or []
    complexity = _message_complexity(message, conv)
    text = (message or "").strip()
    strong = [
        iid for iid, row in score_table.items()
        if iid != "general_chat" and float(row.get("score", 0) or 0) >= 0.45
    ]
    any_hits = [
        iid for iid, row in score_table.items()
        if iid != "general_chat" and float(row.get("score", 0) or 0) > 0
    ]
    reasons: list[str] = []
    theme_hits = 0
    theme_groups = [
        ("竞品", "对手", "类似", "替代"),
        ("盈利", "收费", "商业模式", "收入", "变现", "付费"),
        ("用户", "访谈", "验证", "证据", "调研"),
        ("推广", "渠道", "小红书", "知乎", "获客"),
        ("评委", "竞赛", "答辩", "路演", "互联网+"),
        ("功能", "产品", "方案", "核心", "系统", "工具"),
    ]
    for group in theme_groups:
        if any(term in text for term in group):
            theme_hits += 1
    if len(strong) >= 2 and complexity >= 2:
        reasons.append(f"同时命中多个主题：{', '.join(strong[:3])}")
    if complexity >= 4 and len(any_hits) >= 2:
        reasons.append("消息结构复杂，包含多个问题或多个分析维度")
    if theme_hits >= 3 and len(text) >= 180:
        reasons.append("同一条消息覆盖了多个创业分析主题")
    if len(text) >= 260 and any(sig in text for sig in ("另外", "还有", "同时", "以及", "一方面", "另一方面")):
        reasons.append("长消息中出现明显的多主题连接词")
    return ("mixed" if reasons else "single"), reasons


def _intent_reason_text(
    engine: str,
    intent: str,
    matched: list[str] | None = None,
    shape: str = "single",
    shape_reasons: list[str] | None = None,
    llm_reason: str = "",
) -> str:
    parts: list[str] = []
    if engine in {"rule", "rule-fallback"} and matched:
        parts.append(f"关键词命中 {', '.join(matched[:4])}")
    elif engine == "follow_up":
        parts.append("短追问继承了上一轮对话主题")
    elif engine == "file_detect":
        parts.append("检测到文件上传，优先按项目诊断处理")
    elif engine == "llm" and llm_reason:
        parts.append(llm_reason.strip())
    elif engine == "heuristic_long":
        parts.append("长项目描述默认先进入综合项目诊断")
    elif engine == "context_inherit":
        parts.append("当前消息较短，继承了对话中的主问题")
    if shape == "mixed" and shape_reasons:
        parts.append("判定为混合问题：" + "；".join(shape_reasons[:2]))
    elif shape == "single":
        parts.append("判定为单一主问题")
    parts.append(f"主意图归类为 {intent}")
    return "；".join([p for p in parts if p])


def _infer_prev_intent(conversation_messages: list) -> str | None:
    for msg in reversed(conversation_messages):
        trace = msg.get("agent_trace")
        if trace and isinstance(trace, dict):
            orch = trace.get("orchestration", {})
            prev = orch.get("intent")
            if prev and prev in INTENTS and prev != "general_chat":
                return prev
    return None


def _message_complexity(message: str, conversation_messages: list | None = None) -> int:
    text = (message or "").strip()
    conv = conversation_messages or []
    score = 0
    if len(text) >= 120:
        score += 1
    if len(text) >= 220:
        score += 1
    if text.count("?") + text.count("？") >= 2:
        score += 1
    if text.count("\n") >= 2:
        score += 1
    if any(sig in text for sig in _COMPLEX_QUERY_SIGNALS):
        score += 1
    if conv and _infer_prev_intent(conv):
        score += 1
    return score


def _should_use_focused_mode(state: WorkflowState) -> bool:
    intent = state.get("intent", "general_chat")
    intent_shape = _normalize_intent_shape(state.get("intent_shape", "single"))
    msg = state.get("message", "")
    conv = state.get("conversation_messages", [])
    if "[上传文件:" in msg:
        return False
    if intent == "general_chat":
        return True
    if intent not in _FOCUSED_INTENTS:
        return False
    if intent_shape == "mixed":
        return False
    complexity = _message_complexity(msg, conv)
    if intent == "learning_concept" and state.get("mode") in ("coursework", "learning"):
        return complexity <= 1 and len(msg) < 130
    return complexity <= 1 and len(msg) < 90


def _should_shallow_gather(state: WorkflowState) -> bool:
    intent = state.get("intent", "general_chat")
    intent_shape = _normalize_intent_shape(state.get("intent_shape", "single"))
    msg = state.get("message", "")
    conv = state.get("conversation_messages", [])
    if "[上传文件:" in msg or intent not in _DISCOVERY_INTENTS:
        return False
    if intent_shape == "mixed":
        return False
    if len(msg) >= 220:
        return False
    if conv and _infer_prev_intent(conv) == intent and _message_complexity(msg, conv) >= 2:
        return False
    return any(sig in msg for sig in _VAGUE_PROJECT_SIGNALS) or len(msg) < 120


def _assess_clarification_need(state: WorkflowState) -> dict[str, Any]:
    intent = state.get("intent", "general_chat")
    msg = state.get("message", "")
    diag = state.get("diagnosis", {}) if isinstance(state.get("diagnosis"), dict) else {}
    kg = state.get("kg_analysis", {}) if isinstance(state.get("kg_analysis"), dict) else {}
    conv = state.get("conversation_messages", [])
    if "[上传文件:" in msg or intent not in _DISCOVERY_INTENTS:
        return {"needs_clarification": False, "clarification_reason": "", "clarification_questions": [], "clarification_missing": []}

    entities = kg.get("entities", []) if isinstance(kg.get("entities"), list) else []
    entity_types = {str(e.get("type", "")) for e in entities if isinstance(e, dict)}
    text_lower = msg.lower()
    inferred_has_user = any(term in msg for term in _USER_SLOT_HINTS)
    inferred_has_solution = any(term in text_lower for term in _SOLUTION_SLOT_HINTS) or "做了个" in msg or "想做" in msg
    inferred_has_pain = any(term in msg for term in _PAIN_SLOT_HINTS) or "解决" in msg or "帮助" in msg
    inferred_has_business = any(term in text_lower for term in ("盈利", "变现", "收费", "商业模式", "成本", "收入", "渠道"))
    missing: list[str] = []
    if "stakeholder" not in entity_types and not inferred_has_user:
        missing.append("目标用户")
    if "pain_point" not in entity_types and not inferred_has_pain:
        missing.append("核心痛点")
    if "solution" not in entity_types and not inferred_has_solution:
        missing.append("解决方案")
    if intent in ("business_model", "competition_prep") and "business_model" not in entity_types and not inferred_has_business:
        missing.append("商业模式")

    vague_signal = any(sig in msg for sig in _VAGUE_PROJECT_SIGNALS)
    brief_project = len(msg) < 180 and _message_complexity(msg, conv) <= 2
    info_sufficient = bool(diag.get("info_sufficient", True))
    need = (not info_sufficient) or len(missing) >= 2 or (brief_project and len(missing) >= 1) or vague_signal

    if conv and _infer_prev_intent(conv) == intent and len(msg) >= 90 and len(missing) <= 1:
        need = False

    question_bank = {
        "目标用户": "你现在最想服务的是哪一类具体人群？最好具体到年龄、身份、场景，而不是“所有人”。",
        "核心痛点": "这类人在什么场景下会遇到什么具体痛点？这个问题现在通常怎么被凑合解决？",
        "解决方案": "你的产品或服务到底准备怎么解决这个问题？用户第一次使用时会经历什么流程？",
        "商业模式": "如果这个方向成立，你准备靠什么赚钱或形成可持续模式？哪怕只是初步设想也可以。",
    }
    questions = [question_bank[item] for item in missing if item in question_bank][:4]
    if len(questions) < 4:
        questions.append("你为什么觉得这个方向值得做？是看到过真实现象、身边案例，还是你自己遇到过这个问题？")

    reason = ""
    if need:
        if missing:
            reason = "当前信息还不足以做高质量复杂诊断，先把几个核心信息补齐会更有帮助。"
        else:
            reason = "你的想法还处在早期阶段，我先帮你把项目描述框架补完整，再进入深度分析。"
    return {
        "needs_clarification": need,
        "clarification_reason": reason,
        "clarification_questions": questions[:4],
        "clarification_missing": missing[:4],
    }


def _clarification_fallback_reply(state: WorkflowState) -> str:
    reason = str(state.get("clarification_reason") or "当前信息还不够完整，我先帮你把项目关键要素补齐。")
    msg = str(state.get("message") or "")
    missing = state.get("clarification_missing", []) or []
    questions = state.get("clarification_questions", []) or []
    observations: list[str] = []
    msg_lower = msg.lower()

    if "ai" in msg_lower and any(k in msg for k in ("工具", "平台", "助手", "系统")):
        observations.append("这个方向本身是有潜力的，但 AI 工具类项目最先会被追问的通常不是功能能不能做出来，而是**为什么用户要持续用你，而不是顺手用通用工具**。")
    if any(k in msg for k in ("功能跑通", "demo", "原型", "做出来")):
        observations.append("你们现在已经把功能做出来，这很好，但创业课和比赛里，评委下一步会更在意**从“能跑”到“能留下用户、能形成商业闭环”之间还差什么**。")
    if any(k in msg for k in ("商业逻辑", "盈利", "变现", "收费", "成本")):
        observations.append("既然你主动提到商业逻辑不太踏实，那我会优先看三个问题：**用户为什么愿意持续用、为什么愿意付费、以及成本结构会不会把你们拖住**。")

    if not observations:
        observations.append("这个想法可以先继续往下聊，但现在更适合先做一轮粗判断，把项目的关键骨架补齐，再进入完整诊断。")

    parts = ["## 先粗聊一下", observations[0]]
    for extra in observations[1:3]:
        parts.append(extra)
    if missing:
        parts.append(f"不过我现在还缺少一些关键信息，主要是：**{'、'.join(missing)}**。")
    if questions:
        parts.append("## 我想先抓一个最关键的问题")
        parts.append(questions[0])
    if len(questions) > 1:
        parts.append("如果你愿意，也可以顺手再补这两项：")
        for idx, q in enumerate(questions[1:3], 1):
            parts.append(f"{idx}. {q}")
    parts.append("## 为什么我先这样问")
    parts.append(reason + " 这样我下一轮给你的建议会更像真正的项目讨论，而不是空泛地列清单。")
    return "\n\n".join(parts)


def _build_clarification_reply(state: WorkflowState) -> str:
    if not _llm.enabled:
        return _clarification_fallback_reply(state)

    msg = str(state.get("message") or "")
    mode = str(state.get("mode") or "coursework")
    intent = str(state.get("intent") or "project_diagnosis")
    missing = state.get("clarification_missing", []) or []
    questions = state.get("clarification_questions", []) or []
    reason = str(state.get("clarification_reason") or "")
    conv = state.get("conversation_messages", []) or []
    conv_ctx = ""
    if conv:
        recent = conv[-4:]
        conv_ctx = "\n".join(
            f"{'学生' if m.get('role')=='user' else 'AI'}: {str(m.get('content',''))[:120]}"
            for m in recent
        )

    reply = _llm.chat_text(
        system_prompt=(
            "你是经验丰富的双创导师，现在处于“信息补全阶段”。\n"
            "你的目标不是立刻做完整诊断，而是：\n"
            "1. 先基于学生已经给出的信息，做**2-3点粗略但有价值的讨论**\n"
            "2. 明确告诉学生这些只是初步判断，不要假装已经知道他没说过的细节\n"
            "3. 然后从最值得深挖的地方切入，只追问1个主问题\n"
            "4. 最后再附带2-3个补充信息点，而不是一上来像问卷一样连发很多问题\n\n"
            "严格要求：\n"
            "- 不要用“先别急着做复杂诊断”这种生硬说法\n"
            "- 不要只给 checklist，要像老师先聊两句，再顺势追问\n"
            "- 可以提出基于项目类型的常见风险，例如 AI 工具常见的替代性、留存、付费逻辑、获客执行问题\n"
            "- 但不要编造学生没有提供过的具体数字、渠道、功能细节\n"
            "- 语气自然、专业、像真正指导项目\n"
            "- 输出 4-6 段，300-700 字"
        ),
        user_prompt=(
            f"模式: {mode}\n"
            f"意图: {intent}\n"
            f"学生最新消息:\n{msg}\n\n"
            + (f"最近对话:\n{conv_ctx}\n\n" if conv_ctx else "")
            + f"当前主要缺失信息: {missing}\n"
            + f"可追问候选: {questions}\n"
            + f"追问原因: {reason}\n\n"
            + "请直接生成一段自然回复：先粗略点评，再聚焦一个问题追问。"
        ),
        model=settings.llm_reason_model,
        temperature=0.45,
    )
    return (reply or "").strip() or _clarification_fallback_reply(state)


_DIRECT_ANSWER_PATTERNS = [
    r"直接帮我写", r"直接给我", r"直接写三个", r"帮我写三个盈利点",
    r"最好能写全怎么收费", r"把.*写完", r"给我现成答案", r"直接列出盈利点",
]


def _is_direct_solution_request(text: str) -> bool:
    content = (text or "").strip().lower()
    return any(re.search(p, content) for p in _DIRECT_ANSWER_PATTERNS)


def _project_stage_label(stage: str) -> str:
    return {
        "idea": "想法期",
        "structured": "原型期",
        "validated": "验证期",
        "document": "验证期",
    }.get(stage, "原型期")


def _coach_evidence_used(diag: dict, max_items: int = 2) -> list[str]:
    rules = diag.get("triggered_rules", []) or []
    items: list[str] = []
    for rule in rules[:max_items]:
        if not isinstance(rule, dict):
            continue
        trigger_message = str(rule.get("trigger_message") or "").strip()
        if trigger_message:
            items.append(trigger_message)
        elif rule.get("quote"):
            items.append(f"原文片段：“{rule['quote']}”")
    return items


def _coach_guardrail_reply(state: dict) -> str:
    diag = state.get("diagnosis", {}) if isinstance(state.get("diagnosis"), dict) else {}
    stage = _project_stage_label(str(diag.get("project_stage", "")))
    bottleneck = str(diag.get("bottleneck") or "当前最大的风险还没有被拆清楚。")
    return (
        "## 我先不直接替你写盈利点\n\n"
        "如果我现在直接给你列 3 个现成收费方案，看起来很省事，但这会跳过最关键的一步："
        "你们的用户到底为什么愿意掏钱，以及这笔钱够不够让项目活下去。对项目教练来说，这一步不能替你代答。\n\n"
        f"## 目前我的判断\n\n"
        f"- **项目阶段**：{stage}\n"
        f"- **当前最大缺口**：{bottleneck}\n\n"
        "## 我想先用一个场景把问题拆开\n\n"
        "如果你们接下来 6 个月拿不到外部融资，账上只靠现在能收回来的钱继续跑，"
        "你们最先想保住的是哪一项：模型/API成本、获客成本，还是团队运营成本？\n\n"
        "## 再回答我这 3 个问题\n\n"
        "1. 你们现在最可能付费的那类用户，是谁？他为什么现在就愿意掏钱，而不是继续用免费替代方案？\n"
        "2. 如果每来一个用户，你们都要付出真实成本，这个成本大概落在哪几项？哪一项最可能失控？\n"
        "3. 假设第一个付费版本只能卖一个收费点，你觉得最可能卖的是效率、结果质量，还是服务保障？为什么？\n\n"
        "你先回答这几个问题，我再陪你把盈利逻辑一步步推出来，而不是直接替你编一个看起来完整、其实经不起追问的答案。"
    )


_PRESSURE_PRIORITY_RULES = ("H6", "H16", "H17", "H4", "H9", "H19", "H3", "H8", "H11", "H22")


def _top_triggered_rule(diag: dict, message: str = "") -> dict[str, Any]:
    rules = [r for r in (diag.get("triggered_rules") or []) if isinstance(r, dict)]
    if not rules:
        return {}
    msg = str(message or "")
    if any(k in msg for k in ("竞争", "对手", "替代", "1%", "市场", "收费", "盈利", "获客", "合规", "风控")):
        for rid in _PRESSURE_PRIORITY_RULES:
            hit = next((r for r in rules if str(r.get("id")) == rid), None)
            if hit:
                return hit
    high = [r for r in rules if str(r.get("severity")) == "high"]
    return high[0] if high else rules[0]


def _compose_pressure_question(
    message: str,
    rule: dict[str, Any],
    strategy: dict[str, Any],
    retrieved_edges: list[dict[str, Any]],
) -> str:
    quote = str(rule.get("quote") or "").strip()
    strategy_id = str(strategy.get("strategy_id") or "")
    edge_types = [str(edge.get("edge_type") or edge.get("type") or "") for edge in retrieved_edges if isinstance(edge, dict)]

    if strategy_id == "CS01":
        return (
            f"你提到“{quote or '没有竞争对手'}”。如果用户今天不用你们，他会先用什么办法把这件事凑合做完？"
            "那个方案虽然笨，但为什么他们还愿意继续用？如果你们想让他切过来，最大的迁移成本是什么？"
        )
    if strategy_id == "CS02":
        return (
            f"你提到“{quote or '只要拿到1%市场'}”。这批人具体散落在哪些渠道里？"
            "你打算花多少钱找到第一个100个用户？请给我一个单人获客成本 CAC 的估算，而不是只讲总体市场有多大。"
        )
    if strategy_id == "CS05":
        return (
            "如果未来 6 个月没有外部融资，你们账上的现金最先会被哪一项成本吃掉？"
            "这条价值链里，谁先付钱、为什么现在就付、以及这笔钱能不能覆盖持续服务成本？"
        )
    if strategy_id == "CS08":
        return (
            f"你提到“{quote or '准备收费'}”。用户现在已经有哪些免费或更便宜的替代方案？"
            "你凭什么判断他会为你多付这笔钱？如果价格上调 50%，你预计谁会先流失？"
        )
    if strategy_id == "CS07":
        return (
            "你说已经考虑了风险控制。那如果明天真的发生一次数据滥用或合规抽查，"
            "你们具体靠哪一个流程、哪一个责任人、哪一份记录去应对，而不是只靠原则性表述？"
        )

    layer = ""
    probing_layers = strategy.get("probing_layers") or []
    if probing_layers:
        layer = str(probing_layers[0]).split(":", 1)[-1].strip()
    if layer:
        return layer
    if edge_types:
        return f"你现在的说法主要依赖 {edge_types[0]}。如果把这个逻辑拆开，最先需要你补证明的那个环节到底是什么？"
    return "如果把你现在这句话拆开来看，哪一个前提其实还没有被真正证明？你准备用什么证据补上它？"


def _build_pressure_test_trace(
    diag: dict,
    strategies: list[dict[str, Any]],
    hypergraph_insight: dict,
    message: str = "",
) -> dict:
    top_rule = _top_triggered_rule(diag, message)
    top_strategy = strategies[0] if strategies and isinstance(strategies[0], dict) else {}
    edge_items = []
    for edge in (hypergraph_insight or {}).get("edges", [])[:3]:
        if not isinstance(edge, dict):
            continue
        edge_items.append({
            "edge_type": edge.get("type") or edge.get("edge_type") or "unknown",
            "hyperedge_id": edge.get("hyperedge_id") or edge.get("edge_id") or "",
            "support": edge.get("support") or 0,
            "teaching_note": edge.get("teaching_note") or edge.get("summary") or "",
            "nodes": edge.get("nodes") or [],
            "evidence_quotes": edge.get("evidence_quotes") or [],
        })
    generated_question = _compose_pressure_question(message, top_rule, top_strategy, edge_items)
    evidence_quotes = []
    if top_rule.get("quote"):
        evidence_quotes.append(str(top_rule.get("quote")))
    for edge in edge_items:
        for quote in edge.get("evidence_quotes") or []:
            text = str(quote).strip()
            if text and text not in evidence_quotes:
                evidence_quotes.append(text)
    return {
        "fallacy_label": top_rule.get("fallacy_label") or top_rule.get("name") or "",
        "fallacy_rule_id": top_rule.get("id") or "",
        "retrieved_heterogeneous_subgraph": edge_items,
        "selected_strategy": top_strategy.get("name") or "",
        "selected_strategy_id": top_strategy.get("strategy_id") or "",
        "strategy_logic": top_strategy.get("strategy_logic") or "",
        "generated_question": generated_question,
        "evidence_quotes": evidence_quotes[:3],
    }


def _classify(message: str, conversation_messages: list | None = None) -> dict:
    text = message.lower().strip()
    conv = conversation_messages or []

    # ── Fast path 1: file upload → project_diagnosis ──
    if "[上传文件:" in message:
        return {
            "intent": "project_diagnosis", "confidence": 0.95,
            "intent_shape": "mixed" if len(message) >= 260 else "single",
            "intent_reason": _intent_reason_text("file_detect", "project_diagnosis", shape="mixed" if len(message) >= 260 else "single"),
            "agents": list(INTENTS["project_diagnosis"]["agents"]),
            "engine": "file_detect",
        }

    # ── Fast path 2: short follow-up → inherit previous intent ──
    if len(text) < 40 and conv:
        if any(s in text for s in _FOLLOW_UP_SIGNALS):
            prev = _infer_prev_intent(conv)
            if prev:
                return {
                    "intent": prev, "confidence": 0.8,
                    "intent_shape": "single",
                    "intent_reason": _intent_reason_text("follow_up", prev, shape="single"),
                    "agents": list(INTENTS[prev]["agents"]),
                    "engine": "follow_up",
                }

    # ── Keyword scoring ──
    score_table = _keyword_score_table(text)
    scores: list[tuple[str, float]] = []
    for iid, row in score_table.items():
        matched = row.get("matched", [])
        score = float(row.get("score", 0) or 0)
        if matched:
            logger.debug("classify kw: intent=%s matched=%s score=%.3f", iid, matched, score)
        scores.append((iid, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    kw_best, kw_score = scores[0]
    kw_matched = list(score_table.get(kw_best, {}).get("matched", []))
    shape, shape_reasons = _infer_intent_shape(message, score_table, conv)
    logger.info("classify: msg='%s…' kw_best=%s kw_score=%.3f", text[:40], kw_best, kw_score)

    # Very strong keyword hit → trust it directly
    if kw_score >= 0.65:
        r = {
            "intent": kw_best, "confidence": min(1.0, kw_score),
            "intent_shape": shape,
            "intent_reason": _intent_reason_text("rule", kw_best, matched=kw_matched, shape=shape, shape_reasons=shape_reasons),
            "agents": list(INTENTS[kw_best]["agents"]),
            "engine": "rule",
        }
        logger.info("classify → %s (rule, score=%.2f)", kw_best, kw_score)
        return r

    distinctive_intents = {"market_competitor", "competition_prep", "learning_concept", "evidence_check", "pressure_test", "business_model"}
    if kw_best in distinctive_intents and kw_score >= 0.35:
        r = {
            "intent": kw_best,
            "confidence": min(0.88, max(0.5, kw_score)),
            "intent_shape": shape,
            "intent_reason": _intent_reason_text("rule", kw_best, matched=kw_matched, shape=shape, shape_reasons=shape_reasons),
            "agents": list(INTENTS[kw_best]["agents"]),
            "engine": "rule",
        }
        logger.info("classify → %s (distinctive-rule, score=%.2f)", kw_best, kw_score)
        return r

    project_like = (
        len(text) >= 120
        and any(sig in text for sig in ("我们做", "项目叫", "项目是", "功能", "核心", "产品", "推广", "用户", "商业模式"))
    )
    if project_like and kw_best not in {"competition_prep", "learning_concept"}:
        inferred_shape = "mixed" if shape == "mixed" or len(text) >= 220 else "single"
        r = {
            "intent": "project_diagnosis",
            "confidence": max(0.5, kw_score),
            "intent_shape": inferred_shape,
            "intent_reason": _intent_reason_text("heuristic_long", "project_diagnosis", matched=kw_matched, shape=inferred_shape, shape_reasons=shape_reasons),
            "agents": list(INTENTS["project_diagnosis"]["agents"]),
            "engine": "heuristic_long",
        }
        logger.info("classify → project_diagnosis (project-like)")
        return r

    # ── LLM classification (primary for anything not obvious) ──
    if _llm.enabled:
        conv_ctx = ""
        if conv:
            recent = conv[-4:]
            conv_ctx = "\n".join(
                f"{'学生' if m.get('role')=='user' else 'AI'}: "
                f"{str(m.get('content',''))[:120]}"
                for m in recent
            )

        intent_list = "\n".join(f"- {k}: {v['desc']}" for k, v in INTENTS.items())
        llm_r = _llm.chat_json(
            system_prompt=(
                f"意图分类器。根据学生最新消息和对话上下文，选一个最匹配的意图。\n"
                f"可选意图:\n{intent_list}\n\n"
                "分类原则:\n"
                "- 学生问'有没有类似的/竞品/市面上'等→选market_competitor\n"
                "- 学生在描述一个项目想法(哪怕很模糊)就选project_diagnosis\n"
                "- 学生追问前面的话题，根据话题选对应意图\n"
                "- 只有完全无关创业/项目的寒暄才选general_chat\n"
                "- 学生上传了文件一定选project_diagnosis\n"
                "- 如果学生一条消息里同时在说项目介绍、商业模式、推广、竞争、验证等多个主题，则 intent_shape 选 mixed，否则选 single\n"
                '输出JSON: {"intent":"ID","confidence":0.0-1.0,"intent_shape":"single|mixed","reason":"一句话理由"}'
            ),
            user_prompt=(
                (f"对话上下文:\n{conv_ctx}\n\n" if conv_ctx else "")
                + f"学生最新消息: {message[:500]}"
            ),
            temperature=0.05,
        )
        logger.info("classify LLM: %s", llm_r)
        if llm_r and llm_r.get("intent") in INTENTS:
            llm_conf = float(llm_r.get("confidence", 0))
            if llm_conf > 0.3:
                llm_shape = _normalize_intent_shape(llm_r.get("intent_shape", shape), default=shape)
                r = {
                    "intent": llm_r["intent"],
                    "confidence": llm_conf,
                    "intent_shape": llm_shape,
                    "intent_reason": _intent_reason_text("llm", llm_r["intent"], shape=llm_shape, shape_reasons=shape_reasons, llm_reason=str(llm_r.get("reason", "") or "")),
                    "agents": list(INTENTS[llm_r["intent"]]["agents"]),
                    "engine": "llm",
                }
                logger.info("classify → %s (llm, conf=%.2f)", llm_r["intent"], llm_conf)
                return r

    # ── Fallback: use keyword result or heuristic ──
    if kw_score >= 0.15:
        r = {
            "intent": kw_best, "confidence": kw_score,
            "intent_shape": shape,
            "intent_reason": _intent_reason_text("rule-fallback", kw_best, matched=kw_matched, shape=shape, shape_reasons=shape_reasons),
            "agents": list(INTENTS[kw_best]["agents"]),
            "engine": "rule",
        }
        logger.info("classify → %s (rule-fallback, score=%.2f)", kw_best, kw_score)
        return r
    if len(text) > 60:
        r = {
            "intent": "project_diagnosis", "confidence": 0.45,
            "intent_shape": "mixed" if _message_complexity(message, conv) >= 3 else "single",
            "intent_reason": _intent_reason_text("heuristic_long", "project_diagnosis", shape="mixed" if _message_complexity(message, conv) >= 3 else "single", shape_reasons=shape_reasons),
            "agents": list(INTENTS["project_diagnosis"]["agents"]),
            "engine": "heuristic_long",
        }
        logger.info("classify → project_diagnosis (heuristic_long)")
        return r

    # For any message about a project (even short), use project_diagnosis
    if conv and _infer_prev_intent(conv):
        prev = _infer_prev_intent(conv)
        r = {
            "intent": prev, "confidence": 0.5,
            "intent_shape": "single",
            "intent_reason": _intent_reason_text("context_inherit", prev, shape="single"),
            "agents": list(INTENTS[prev]["agents"]),
            "engine": "context_inherit",
        }
        logger.info("classify → %s (context_inherit)", prev)
        return r

    r = {
        "intent": "general_chat", "confidence": 0.4,
        "intent_shape": "single",
        "intent_reason": _intent_reason_text("heuristic_short", "general_chat", shape="single"),
        "agents": list(INTENTS["general_chat"]["agents"]),
        "engine": "heuristic_short",
    }
    logger.info("classify → general_chat (heuristic_short)")
    return r


# ═══════════════════════════════════════════════════════════════════
#  Node 1: Router
# ═══════════════════════════════════════════════════════════════════

def _adjust_pipeline_for_mode(agents: list[str], mode: str, intent: str) -> list[str]:
    """Keep routing-stage pipeline to the primary agent for this mode."""
    primary = [a for a in agents if a in AGENT_FNS][:1]
    if mode == "competition" and intent != "general_chat":
        return ["advisor"]
    if mode == "learning" and intent != "general_chat":
        return ["coach"]
    if mode == "coursework":
        if intent in ("learning_concept", "market_competitor"):
            return ["tutor"]
        if primary:
            return primary
    return primary or [a for a in agents if a in AGENT_FNS][:1]


def router_agent(state: WorkflowState) -> dict:
    conv = state.get("conversation_messages", [])
    mode = state.get("mode", "coursework")
    c = _classify(state.get("message", ""), conversation_messages=conv)
    pipeline = _adjust_pipeline_for_mode(c["agents"], mode, c["intent"])
    return {
        "intent": c["intent"],
        "intent_confidence": c["confidence"],
        "intent_shape": c.get("intent_shape", "single"),
        "intent_reason": c.get("intent_reason", ""),
        "intent_pipeline": pipeline,
        "intent_engine": c["engine"],
        "agents_called": ["router"],
        "nodes_visited": ["router"],
    }


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def _default_kg() -> dict:
    return {
        "entities": [], "relationships": [],
        "structural_gaps": ["文本过短"], "content_strengths": [],
        "completeness_score": 0, "section_scores": {},
        "insight": "请提供更详细描述",
    }


def _fmt_ws(ws: dict) -> str:
    if not ws.get("searched") or not ws.get("results"):
        return ""
    parts = [f"联网搜索（{ws.get('query', '')}）:"]
    for r in ws.get("results", [])[:4]:
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        url = r.get("url", "")
        parts.append(f"- {title}: {snippet}" + (f" | 链接: {url}" if url else ""))
    return "\n".join(parts)[:900]


def _standalone_hypergraph_analysis(
    entities: list[dict],
    relationships: list[dict],
    structural_gaps: list[str] | None = None,
) -> dict:
    """Hypergraph-style analysis that works without Neo4j, purely from KG entities."""
    DIMS = {
        "stakeholder": "目标用户", "pain_point": "痛点问题",
        "solution": "解决方案", "technology": "技术路线",
        "market": "市场环境", "competitor": "竞品对手",
        "resource": "关键资源", "business_model": "商业模式",
        "team": "团队能力", "evidence": "验证证据",
    }
    dim_entities: dict[str, list[str]] = {k: [] for k in DIMS}
    for e in entities:
        etype = str(e.get("type", "")).lower().replace(" ", "_")
        label = e.get("label", "")
        if etype in dim_entities:
            dim_entities[etype].append(label)
        elif "user" in etype or "customer" in etype:
            dim_entities["stakeholder"].append(label)
        elif "pain" in etype or "problem" in etype:
            dim_entities["pain_point"].append(label)
        elif "tech" in etype:
            dim_entities["technology"].append(label)
        elif "market" in etype:
            dim_entities["market"].append(label)
        elif "compet" in etype:
            dim_entities["competitor"].append(label)

    dimensions = {}
    covered = 0
    for k, name in DIMS.items():
        ents = dim_entities[k]
        is_covered = len(ents) > 0
        if is_covered:
            covered += 1
        dimensions[k] = {"name": name, "covered": is_covered, "count": len(ents), "entities": ents[:3]}

    cross_links = []
    for r in relationships:
        src_type = next((e.get("type", "") for e in entities if e.get("id") == r.get("source")), "")
        tgt_type = next((e.get("type", "") for e in entities if e.get("id") == r.get("target")), "")
        if src_type != tgt_type and src_type and tgt_type:
            src_dim = DIMS.get(src_type.lower(), src_type)
            tgt_dim = DIMS.get(tgt_type.lower(), tgt_type)
            cross_links.append({"from_dim": src_dim, "relation": r.get("relation", ""), "to_dim": tgt_dim})

    IMPORTANCE = {"stakeholder": "极高", "pain_point": "极高", "solution": "高", "technology": "高",
                  "market": "高", "business_model": "高", "competitor": "中", "resource": "中",
                  "team": "中", "evidence": "极高"}
    missing = []
    for k, name in DIMS.items():
        if not dim_entities[k]:
            missing.append({"dimension": name, "importance": IMPORTANCE.get(k, "中"),
                            "recommendation": f"请补充{name}相关的描述"})
    missing.sort(key=lambda x: {"极高": 0, "高": 1, "中": 2}.get(x["importance"], 3))

    hub_entities = []
    entity_connections: dict[str, int] = {}
    for r in relationships:
        for key in ["source", "target"]:
            eid = r.get(key, "")
            entity_connections[eid] = entity_connections.get(eid, 0) + 1
    for e in entities:
        count = entity_connections.get(e.get("id", ""), 0)
        if count >= 2:
            hub_entities.append({"entity": e.get("label", ""), "connections": count})
    hub_entities.sort(key=lambda x: -x["connections"])

    # ── Rule-based pattern detection ──
    warnings = []
    strengths = []
    if not dim_entities["evidence"] and not dim_entities["stakeholder"]:
        warnings.append({"warning": "缺少用户证据和目标用户定义——这是评审中最容易被质疑的部分"})
    if dim_entities["solution"] and not dim_entities["pain_point"]:
        warnings.append({"warning": "有方案但缺少痛点分析——方案可能无的放矢"})
    if dim_entities["stakeholder"] and dim_entities["pain_point"] and dim_entities["solution"]:
        strengths.append({"note": "用户-痛点-方案三角关系完整，项目逻辑基础扎实"})
    if dim_entities["technology"] and dim_entities["market"]:
        strengths.append({"note": "技术路线与市场定位都有涉及，项目可行性有基础"})
    if len(cross_links) >= 3:
        strengths.append({"note": f"跨维度联动较多({len(cross_links)}条)，说明项目内在逻辑串联较好"})

    # ── Value loop detection ──
    _LOOP_CHAINS = [
        (["stakeholder", "pain_point", "solution"], "用户→痛点→方案"),
        (["solution", "business_model"], "方案→商业模式"),
        (["stakeholder", "pain_point", "solution", "business_model"], "完整价值环路"),
        (["pain_point", "evidence"], "痛点→证据验证"),
        (["solution", "technology"], "方案→技术实现"),
    ]
    value_loops = []
    for chain, label in _LOOP_CHAINS:
        present = all(len(dim_entities.get(d, [])) > 0 for d in chain)
        value_loops.append({"chain": label, "complete": present, "dims": chain})
    complete_loops = sum(1 for v in value_loops if v["complete"])

    if complete_loops == 0:
        warnings.append({"warning": "没有完整的价值环路——项目逻辑链存在断点，评委会直接追问"})
    elif complete_loops >= 3:
        strengths.append({"note": f"有{complete_loops}条完整价值链路，项目逻辑闭环性强"})

    # ── LLM-driven cross-dimensional insight (if available) ──
    llm_insight = ""
    if _llm.enabled and len(entities) >= 3:
        dim_summary = "; ".join(
            f"{name}: {', '.join(dim_entities[k][:2]) if dim_entities[k] else '缺失'}"
            for k, name in DIMS.items()
        )
        missing_str = ", ".join(m["dimension"] for m in missing[:3])
        loop_str = "; ".join(
            f"{'✓' if v['complete'] else '✗'} {v['chain']}" for v in value_loops
        )

        llm_insight = _llm.chat_text(
            system_prompt=(
                "你是超图拓扑分析引擎。基于项目的维度覆盖和价值链路，用2-3句话给出最关键的结构性洞察。\n"
                "要求：不要泛泛而谈，必须指出具体的断裂点和最紧迫的补强方向。直接输出分析文字。"
            ),
            user_prompt=(
                f"维度覆盖({covered}/10): {dim_summary}\n"
                f"缺失维度: {missing_str or '无'}\n"
                f"价值链路: {loop_str}\n"
                f"跨维度连接: {len(cross_links)}条\n"
                f"枢纽实体: {', '.join(h['entity'] for h in hub_entities[:3]) if hub_entities else '无'}"
            ),
            temperature=0.3,
        )

    return {
        "ok": True,
        "coverage_score": covered,
        "covered_count": covered,
        "total_dimensions": len(DIMS),
        "dimensions": dimensions,
        "cross_links": cross_links[:8],
        "missing_dimensions": missing,
        "hub_entities": hub_entities[:5],
        "pattern_warnings": warnings,
        "pattern_strengths": strengths,
        "value_loops": value_loops,
        "complete_loops": complete_loops,
        "llm_insight": llm_insight,
    }


# ═══════════════════════════════════════════════════════════════════
#  Node 2: Static Foundation + Conditional Enhancement
# ═══════════════════════════════════════════════════════════════════

_WEB_SIGNAL_WORDS = frozenset([
    "类似", "竞品", "市面上", "有哪些", "行业", "趋势", "最新",
    "别人怎么做", "什么是", "怎么理解", "解释", "方法", "怎么做",
    "报告", "白皮书", "新闻", "数据", "社交媒体", "小红书", "抖音",
    "微博", "知乎", "公众号", "网址", "链接",
])

_FACT_CHECK_SIGNALS = frozenset([
    "没有竞争对手", "没有对手", "没什么竞品", "我们是首个", "行业里没有",
    "只要1%", "只要拿到1%", "市场很大", "肯定有人买", "巨头不会做",
])


def gather_context_node(state: WorkflowState) -> dict:
    """Layer 1: Static Foundation + Conditional Enhancement.

    STATIC (always runs — guarantees scoring consistency & knowledge accumulation):
      • Diagnosis engine (rule-based rubric, <50ms, deterministic)
      • KG extraction   (structured LLM, runs for any project-related content)
      • RAG retrieval   (vector search, always)
      • Hypergraph      (from KG entities, rules + LLM insight)

    CONDITIONAL (intent/signal driven — avoids wasteful calls):
      • Web search      → only when intent or keywords suggest external info
      • Hyper-teaching  → only when file uploaded or diagnosis-type intent
      • Neo4j merge     → only when KG produces entities (side-effect)
    """
    intent = state.get("intent", "general_chat")
    msg = state.get("message", "")
    mode = state.get("mode", "coursework")
    is_file = "[上传文件:" in msg

    if intent == "general_chat" and len(msg) < 25 and not is_file:
        return {"nodes_visited": ["gather_context"]}

    # ────────────────────────────────────────────────────────────────
    # STATIC: Diagnosis Engine (rule-based, deterministic, <50ms)
    #   Produces rubric scores, triggered rules, bottleneck.
    #   Runs for EVERY non-trivial message to ensure scoring consistency.
    # ────────────────────────────────────────────────────────────────
    from app.services.case_knowledge import infer_category
    from app.services.challenge_strategies import match_strategies
    from app.services.diagnosis_engine import run_diagnosis

    diag_obj = run_diagnosis(input_text=msg, mode=mode)
    diag_data: dict = diag_obj.diagnosis
    next_task: dict = diag_obj.next_task
    cat = infer_category(msg)
    rules = diag_data.get("triggered_rules", []) or []
    rule_ids = [r.get("id", "") for r in rules if isinstance(r, dict)]
    top_rule = _top_triggered_rule(diag_data, msg)
    top_fallacy = str(top_rule.get("fallacy_label") or "")
    preferred_edge_types = list(top_rule.get("preferred_edge_types") or [])
    strategies = match_strategies(
        msg,
        rule_ids,
        max_results=3,
        fallacy_label=top_fallacy,
        edge_types=preferred_edge_types,
    )

    if _should_shallow_gather(state):
        clarify = _assess_clarification_need({
            **state,
            "diagnosis": diag_data,
            "kg_analysis": _default_kg(),
        })
        pressure_trace = _build_pressure_test_trace(diag_data, strategies, {}, msg)
        return {
            "diagnosis": diag_data,
            "next_task": next_task,
            "category": cat,
            "kg_analysis": _default_kg(),
            "rag_cases": [],
            "rag_context": "",
            "web_search_result": {},
            "hypergraph_insight": {},
            "hypergraph_student": {},
            "challenge_strategies": strategies,
            "pressure_test_trace": pressure_trace,
            **clarify,
            "nodes_visited": ["gather_context"],
        }

    # ────────────────────────────────────────────────────────────────
    # STATIC + CONDITIONAL: Parallel I/O tasks
    # ────────────────────────────────────────────────────────────────
    collected: dict[str, Any] = {}

    # -- STATIC: RAG (always, fast vector search) --
    def _task_rag():
        if _rag is None or _rag.case_count == 0:
            return {"rag_cases": [], "rag_context": ""}
        rag_top_k = 5 if intent in ("market_competitor", "competition_prep", "learning_concept", "idea_brainstorm") else 3
        cases = _rag.retrieve(msg[:1000], top_k=rag_top_k, category_filter=cat or None)
        ctx = _rag.format_for_llm(cases)
        return {"rag_cases": cases, "rag_context": ctx}

    # -- STATIC: KG Extraction (structured LLM, produces section_scores) --
    def _task_kg():
        if not _llm.enabled or len(msg) < 10:
            return {"kg_analysis": _default_kg()}
        kg = _llm.chat_json(
            system_prompt=(
                "你是知识图谱抽取引擎。从学生的创业项目描述中提取所有关键实体和关系。\n"
                + ("学生上传了文件，请逐段分析。\n" if is_file else "")
                + "实体type必须从以下选择: stakeholder, pain_point, solution, innovation, "
                "technology, market, competitor, resource, business_model, execution_step, risk_control, team, evidence\n\n"
                "示例:\n"
                '{"entities":[{"id":"e1","label":"6-12岁儿童","type":"stakeholder"},'
                '{"id":"e2","label":"编程学习枯燥","type":"pain_point"},'
                '{"id":"e3","label":"游戏化编程平台","type":"solution"},'
                '{"id":"e4","label":"教师访谈原话","type":"evidence"}],'
                '"relationships":[{"source":"e1","target":"e2","relation":"面临"},'
                '{"source":"e3","target":"e2","relation":"解决"},'
                '{"source":"e4","target":"e2","relation":"证明"}],'
                '"structural_gaps":["缺少商业模式","缺少竞品分析","缺少迁移成本说明"],'
                '"content_strengths":["目标用户清晰"],'
                '"completeness_score":4,'
                '"section_scores":{"problem_definition":6,"user_evidence":2,'
                '"solution_feasibility":5,"business_model":1,"competitive_advantage":1},'
                '"insight":"项目方向明确但缺少证据支撑"}\n\n'
                "要求：即使信息很少也要尽力提取，至少提取2-3个实体。"
            ),
            user_prompt=f"学生内容:\n{msg[:4000]}",
            model=settings.llm_reason_model if is_file else None,
            temperature=0.15,
        )
        if not kg or not kg.get("entities"):
            return {"kg_analysis": _default_kg()}
        return {"kg_analysis": kg}

    # -- CONDITIONAL: Web Search --
    def _task_web(n_results: int = 3):
        from app.services.web_search import web_search
        ws = web_search(msg, intent, max_results=n_results)
        return {"web_search_result": ws}

    # -- CONDITIONAL: Hypergraph teaching insight (Neo4j DB query) --
    def _task_hyper_teaching():
        if not _hypergraph_service:
            return {"hypergraph_insight": {}}
        try:
            h = _hypergraph_service.insight(
                category=cat,
                rule_ids=rule_ids,
                preferred_edge_types=preferred_edge_types,
                limit=5 if intent == "pressure_test" else 4,
            )
            return {"hypergraph_insight": h}
        except Exception as exc:
            logger.warning("Hypergraph insight failed: %s", exc)
            return {"hypergraph_insight": {}}

    # ── Assemble parallel task list ──
    tasks: list[Callable] = [_task_rag]  # RAG: always

    # KG: for all project-related content (ensures section_scores consistency)
    is_project_intent = intent != "general_chat" and not _should_use_focused_mode(state)
    run_kg = is_file or len(msg) > 30 or (is_project_intent and len(msg) > 12)
    if run_kg:
        tasks.append(_task_kg)

    # Web search: conditional on intent config + message keywords
    intent_spec = INTENTS.get(intent, {})
    msg_wants_web = any(w in msg for w in _WEB_SIGNAL_WORDS)
    fact_check_needed = any(w in msg for w in _FACT_CHECK_SIGNALS)
    need_web = msg_wants_web or fact_check_needed or intent_spec.get("need_web", False)
    if mode == "coursework" and intent in ("learning_concept", "market_competitor", "idea_brainstorm", "business_model"):
        need_web = True
    if need_web:
        web_n = intent_spec.get("web_results", 3)
        if intent == "market_competitor":
            web_n = max(web_n, 5)
        tasks.append(lambda n=web_n: _task_web(n))

    # Hypergraph teaching: conditional on file or diagnostic intents
    if is_file or intent in ("project_diagnosis", "evidence_check", "competition_prep", "pressure_test", "business_model"):
        tasks.append(_task_hyper_teaching)

    logger.info(
        "gather[static+cond]: intent=%s tasks=%d (kg=%s web=%s fact_check=%s)",
        intent, len(tasks), run_kg, need_web, fact_check_needed,
    )

    with ThreadPoolExecutor(max_workers=max(1, len(tasks))) as pool:
        future_map = {pool.submit(fn): fn.__name__ for fn in tasks}
        try:
            for future in as_completed(future_map, timeout=200):
                name = future_map[future]
                try:
                    collected.update(future.result())
                except Exception as exc:
                    logger.warning("gather_context %s error: %s", name, exc)
        except TimeoutError:
            logger.warning("gather_context timed out — some tasks incomplete")

    # ────────────────────────────────────────────────────────────────
    # STATIC: Post-parallel — Session KG cache + Hypergraph student analysis
    #   Student entities stay in-session only and are NOT written to Neo4j.
    #   Neo4j is reserved for the read-only standard case knowledge base.
    # ────────────────────────────────────────────────────────────────
    kg = collected.get("kg_analysis", _default_kg())

    hyper_student: dict = {}
    if len(kg.get("entities", [])) > 0:
        try:
            if _hypergraph_service:
                hyper_student = _hypergraph_service.analyze_student_content(
                    entities=kg.get("entities", []),
                    relationships=kg.get("relationships", []),
                    structural_gaps=kg.get("structural_gaps"),
                    category=cat,
                )
            else:
                hyper_student = _standalone_hypergraph_analysis(
                    entities=kg.get("entities", []),
                    relationships=kg.get("relationships", []),
                    structural_gaps=kg.get("structural_gaps"),
                )
        except Exception as exc:
            logger.warning("Hypergraph student analysis failed: %s", exc)

    selected_edge_types = list(preferred_edge_types)
    selected_edge_types.extend([str(x) for x in (hyper_student.get("projected_edge_types") or []) if x])
    selected_edge_types.extend([
        str(edge.get("type") or "")
        for edge in (collected.get("hypergraph_insight", {}).get("edges") or [])
        if isinstance(edge, dict)
    ])
    selected_edge_types = list(dict.fromkeys([x for x in selected_edge_types if x]))
    strategies = match_strategies(
        msg,
        rule_ids,
        max_results=3,
        fallacy_label=top_fallacy,
        edge_types=selected_edge_types,
    )

    clarify = _assess_clarification_need({
        **state,
        "diagnosis": diag_data,
        "kg_analysis": kg,
    })
    pressure_trace = _build_pressure_test_trace(diag_data, strategies, collected.get("hypergraph_insight", {}), msg)

    return {
        "diagnosis": diag_data,
        "next_task": next_task,
        "category": cat,
        "kg_analysis": kg,
        "rag_cases": collected.get("rag_cases", []),
        "rag_context": collected.get("rag_context", ""),
        "web_search_result": collected.get("web_search_result", {}),
        "hypergraph_insight": collected.get("hypergraph_insight", {}),
        "hypergraph_student": hyper_student,
        "challenge_strategies": strategies,
        "pressure_test_trace": pressure_trace,
        **clarify,
        "nodes_visited": ["gather_context"],
    }


# ═══════════════════════════════════════════════════════════════════
#  Role-Agent analysis functions (each = 1 LLM call)
# ═══════════════════════════════════════════════════════════════════

def _build_conv_ctx(state: dict, limit: int = 3) -> str:
    conv = state.get("conversation_messages", [])
    if not conv:
        return ""
    recent = conv[-limit:]
    lines = []
    for m in recent:
        role = "学生" if m.get("role") == "user" else "AI"
        lines.append(f"{role}: {str(m.get('content',''))[:150]}")
    return "\n".join(lines)


def _fmt_hyper_student(hs: dict) -> str:
    if not hs or not hs.get("ok"):
        return ""
    parts = []
    cov = hs.get("coverage_score", 0)
    parts.append(f"维度覆盖: {cov}/10 ({hs.get('covered_count',0)}/{hs.get('total_dimensions',10)}个维度)")
    missing = hs.get("missing_dimensions", [])
    if missing:
        top = [f"{m['dimension']}({m['importance']})" for m in missing[:3]]
        parts.append(f"缺失维度: {', '.join(top)}")
    hubs = hs.get("hub_entities", [])
    if hubs:
        parts.append(f"核心实体: {', '.join(h['entity'] for h in hubs[:3])}")
    warnings = hs.get("pattern_warnings", [])
    if warnings:
        parts.append(f"风险模式匹配: {warnings[0].get('warning','')}")
    strengths = hs.get("pattern_strengths", [])
    if strengths:
        parts.append(f"优势模式: {strengths[0].get('note','')}")
    return "\n".join(parts)


_GHOSTWRITE_PATTERNS = [
    r"直接帮我写",
    r"帮我写完整",
    r"直接写完",
    r"直接生成",
    r"可直接提交",
    r"直接提交的文本",
    r"\d+\s*字.*商业计划书",
    r"代写",
    r"你替我写",
]


def _is_ghostwriting_request(text: str) -> bool:
    content = (text or "").strip().lower()
    return any(re.search(p, content) for p in _GHOSTWRITE_PATTERNS)


def _extract_learning_keywords(text: str) -> list[str]:
    candidates = [
        "tam", "sam", "som", "mvp", "股权", "互联网+", "挑战杯", "商业模式",
        "用户画像", "价值主张", "定价", "路演", "团队", "融资",
    ]
    lowered = (text or "").lower()
    hits = [kw for kw in candidates if kw.lower() in lowered]
    if hits:
        return hits[:4]
    words = re.findall(r"[A-Za-z][A-Za-z\+\-]{1,20}|[\u4e00-\u9fff]{2,8}", text or "")
    fallback = []
    for word in words:
        if word in ("什么是", "怎么做", "应该怎么写", "示例", "项目"):
            continue
        fallback.append(word)
        if len(fallback) >= 4:
            break
    return fallback


def _fmt_learning_kg_nodes(nodes: list[dict[str, Any]], max_chars: int = 1000) -> str:
    if not nodes:
        return ""
    parts = ["本地KG检索结果："]
    for idx, node in enumerate(nodes[:6], 1):
        label_text = "/".join(node.get("labels") or [])
        matched = ",".join(node.get("matched_keys") or [])
        props = node.get("props") or {}
        prop_text = "; ".join(f"{k}={v}" for k, v in list(props.items())[:4])
        parts.append(f"{idx}. [{label_text}] 命中字段: {matched}; {prop_text}")
    return "\n".join(parts)[:max_chars]


def _build_learning_tutor_reply(state: dict, structured: bool = True) -> tuple[str, list[dict[str, Any]]]:
    msg = str(state.get("message", ""))
    mode = str(state.get("mode", "coursework"))
    conv_ctx = _build_conv_ctx(state, limit=4)
    rag_ctx = state.get("rag_context", "")
    ws_ctx = _fmt_ws(state.get("web_search_result", {}))
    kg_nodes: list[dict[str, Any]] = []

    if _is_ghostwriting_request(msg):
        refusal = (
            "## 我不能直接替你代写可提交内容\n\n"
            "这样会绕开课程学习辅导的目的，也会让你失去真正把商业逻辑想清楚的过程。我可以帮你把这一部分拆开、梳理结构、指出漏洞，但不会直接生成一份你可以原样提交的正文。\n\n"
            "## 我建议你先回答这 3 个问题\n\n"
            "1. 这一段你最想说服老师或评委接受的核心判断到底是什么？\n"
            "2. 你手上已经有哪些事实、数据、访谈原话或案例可以支撑这个判断？\n"
            "3. 如果我只允许你保留 2 个最关键的小标题，你觉得应该保留哪两个，为什么？\n\n"
            "## 我可以怎么帮你\n\n"
            "你把你已经想到的要点、草稿提纲或一句话判断发给我，我可以继续帮你改成更清晰的结构、补逻辑、补追问。"
        )
        return refusal, []

    if _graph_service:
        keywords = _extract_learning_keywords(msg)
        kg_nodes = _graph_service.search_nodes(keywords, limit_per_keyword=2) if keywords else []
        logger.info("learning_tutor retrieved_kg_nodes=%s", kg_nodes)

    kg_ctx = _fmt_learning_kg_nodes(kg_nodes)
    llm_resp = _llm.chat_json(
        system_prompt=(
            "你是课程辅导模式下的真实导师。你的重点不是机械下诊断，而是结合学生当前项目教他怎么想、怎么做。\n"
            "如果学生是在问概念、方法、赛事规则、项目思路或写法，请输出JSON，字段必须包含："
            "current_judgment, method_explanation, project_application, common_pitfalls(list), practice_task, observation_point, source_note。\n"
            "要求：\n"
            "- current_judgment 先回应学生当前项目或问题，不要一上来背定义\n"
            "- method_explanation 解释背后的方法论，要说清楚为什么这样看\n"
            "- project_application 必须把方法落回学生项目，指出应该先看什么、再看什么\n"
            "- common_pitfalls 给 2-4 条，必须贴近学生这种场景\n"
            "- practice_task 必须只有一个，且足够小，学生这一轮就能开始做\n"
            "- observation_point 说明学生做这个练习时最该观察什么信号\n"
            "- source_note 用一句话交代你主要参考了案例、联网资料还是本地KG；没有就写“本轮主要依据学生材料判断”\n"
            "- 如果给了本地KG信息，优先使用，不要编造所谓“最新规则”\n"
        ),
        user_prompt=(
            f"模式: {mode}\n学生问题:\n{msg}\n\n"
            + (f"最近对话:\n{conv_ctx}\n\n" if conv_ctx else "")
            + (f"参考案例:\n{rag_ctx[:500]}\n\n" if rag_ctx else "")
            + (f"联网资料:\n{ws_ctx[:500]}\n\n" if ws_ctx else "")
            + (f"{kg_ctx}\n\n" if kg_ctx else "")
            + "请按要求输出JSON。"
        ),
        model=settings.llm_reason_model,
        temperature=0.25,
    ) if _llm.enabled else None

    if not isinstance(llm_resp, dict):
        llm_resp = {
            "current_judgment": "你现在最需要的，通常不是再多记几个术语，而是先把这个概念放回自己的项目里，看看它究竟在帮你判断哪一个关键环节。",
            "method_explanation": "一个方法论真正有用，不在于定义多完整，而在于它能不能帮你缩小问题范围、识别证据缺口，并指导下一步验证。",
            "project_application": "先把你的项目拆成用户、场景、价值、验证四个层次，看看这个概念到底是在解释哪个层次；如果落不回项目，说明你还没有真正理解它。",
            "common_pitfalls": ["只会背定义，不会落到项目里", "写成空话，没有证据或边界", "一次给自己布置太多任务"],
            "practice_task": "围绕你的项目，把这个概念写成 1 段项目化解释，再补 1 个它会影响你决策的具体场景。",
            "observation_point": "重点观察：当你不用套话、只讲自己项目时，是否还能说清这个概念为什么重要。",
            "source_note": "本轮主要依据学生材料判断",
        }

    if not structured:
        text = (
            f"## 先看你现在这个问题\n{str(llm_resp.get('current_judgment') or '').strip()}\n\n"
            f"## 背后的方法\n{str(llm_resp.get('method_explanation') or '').strip()}\n\n"
            f"## 放回你的项目怎么用\n{str(llm_resp.get('project_application') or '').strip()}\n\n"
            "## 你最容易踩的坑\n"
            + "\n".join(f"- {item}" for item in (llm_resp.get("common_pitfalls") or [])[:4])
            + f"\n\n## 现在就能做的小练习\n{str(llm_resp.get('practice_task') or '').strip()}\n\n"
            f"## 做的时候重点观察什么\n{str(llm_resp.get('observation_point') or '').strip()}\n\n"
            f"## 这次主要依据\n{str(llm_resp.get('source_note') or '').strip()}"
        )
        return text.strip(), kg_nodes

    parts = [
        f"## 先看你现在这个问题\n{str(llm_resp.get('current_judgment') or '').strip()}",
        f"## 背后的方法\n{str(llm_resp.get('method_explanation') or '').strip()}",
        f"## 放回你的项目怎么用\n{str(llm_resp.get('project_application') or '').strip()}",
        "## 你最容易踩的坑\n" + "\n".join(f"- {item}" for item in (llm_resp.get("common_pitfalls") or [])[:4]),
        f"## 现在就能做的小练习\n{str(llm_resp.get('practice_task') or '').strip()}",
        f"## 做的时候重点观察什么\n{str(llm_resp.get('observation_point') or '').strip()}",
        f"## 这次主要依据\n{str(llm_resp.get('source_note') or '').strip()}",
    ]
    if kg_nodes:
        parts.append("## KG Baseline\n我这次回答参考了本地知识图谱检索结果，不是只靠通用模型自由发挥。")
    return "\n\n".join(parts).strip(), kg_nodes


_COMPETITION_ITEM_LABELS = {
    "Problem Definition": "问题定义",
    "User Evidence Strength": "用户证据强度",
    "Solution Feasibility": "方案可行性",
    "Business Model Consistency": "商业模式一致性",
    "Market & Competition": "市场与竞争",
    "Financial Logic": "财务逻辑",
    "Innovation & Differentiation": "创新与差异化",
    "Team & Execution": "团队与执行",
    "Presentation Quality": "路演表达与材料",
}

_COMPETITION_FIX_LIBRARY = {
    "Problem Definition": {
        "missing": "缺少明确的目标用户、场景边界或痛点频次证据",
        "fix_24h": "补一页“目标用户-场景-痛点”对照表，至少写清1类核心用户、1个高频场景、3条真实痛点表述。",
        "fix_72h": "完成8份深访或等价证据收集，形成痛点频次统计，并据此重写问题定义页。",
    },
    "User Evidence Strength": {
        "missing": "缺少访谈原话、问卷样本、使用数据或行为证据",
        "fix_24h": "整理现有用户反馈，至少补3条原话或3组行为数据，做成证据页。",
        "fix_72h": "完成一轮结构化访谈/测试，形成样本说明、结论和反证样本。",
    },
    "Solution Feasibility": {
        "missing": "缺少技术路线、MVP验证结果、资源匹配或交付路径",
        "fix_24h": "补一页“当前能做什么/不能做什么”的MVP边界和技术实现路径。",
        "fix_72h": "拿出一轮真实测试结果，说明功能可用性、成本或效果指标。",
    },
    "Business Model Consistency": {
        "missing": "缺少价值主张、付费对象、渠道与收入逻辑的一致性说明",
        "fix_24h": "画出简版商业闭环：谁付费、为什么付费、通过什么渠道触达、钱怎么回来。",
        "fix_72h": "补一版更完整的商业模式画布，并用小样本验证至少一个付费或转化假设。",
    },
    "Market & Competition": {
        "missing": "缺少竞品矩阵、市场口径拆分或差异化论证",
        "fix_24h": "补3个直接/间接竞品，做一个功能-用户-价格-差异矩阵。",
        "fix_72h": "重做TAM/SAM/SOM，并说明你第一阶段真正能切到哪一小块市场。",
    },
    "Financial Logic": {
        "missing": "缺少成本、定价、单位经济或现金流假设",
        "fix_24h": "补最小财务表：单次服务成本、定价、毛利和一个月运营假设。",
        "fix_72h": "完成CAC/LTV/BEP三表，并解释关键参数是如何估出来的。",
    },
    "Innovation & Differentiation": {
        "missing": "缺少可验证创新点、技术壁垒或替代性说明",
        "fix_24h": "用1页明确回答：相比现有方案，你们到底多了什么不可替代价值。",
        "fix_72h": "补实验、对照、专利/算法/数据壁垒或产品留存机制的证明材料。",
    },
    "Team & Execution": {
        "missing": "缺少团队分工、关键能力匹配或阶段里程碑",
        "fix_24h": "补团队分工页，明确谁负责产品、技术、运营、答辩。",
        "fix_72h": "给出未来12周里程碑表，每阶段对应可交付物和负责人。",
    },
    "Presentation Quality": {
        "missing": "缺少有说服力的叙事结构、关键数据页或评委友好的表达",
        "fix_24h": "重排路演目录，确保“问题-方案-证据-市场-模式-团队”顺序清楚。",
        "fix_72h": "做一次模拟路演录屏，按问答反馈重写开场页、证据页和结尾页。",
    },
}


def _match_competition_missing(item: str, diag: dict, kg: dict) -> list[str]:
    rules = diag.get("triggered_rules", []) or []
    rule_names = [str(r.get("name", "")) for r in rules if isinstance(r, dict)]
    structural_gaps = [str(x) for x in (kg.get("structural_gaps", []) or [])[:4]]
    library = _COMPETITION_FIX_LIBRARY.get(item, {})
    missing: list[str] = []
    if library.get("missing"):
        missing.append(str(library["missing"]))

    item_rule_map = {
        "Problem Definition": ("客户-价值主张错位", "需求证据不足"),
        "User Evidence Strength": ("需求证据不足", "实验设计不合格"),
        "Solution Feasibility": ("创新点不可验证", "技术路线与资源不匹配"),
        "Business Model Consistency": ("客户-价值主张错位", "渠道不可达", "定价无支付意愿证据"),
        "Market & Competition": ("TAM/SAM/SOM口径混乱", "竞品对比不可比"),
        "Financial Logic": ("单位经济不成立", "增长逻辑跳跃"),
        "Innovation & Differentiation": ("创新点不可验证", "竞品对比不可比"),
        "Team & Execution": ("里程碑不可交付", "技术路线与资源不匹配"),
        "Presentation Quality": ("路演叙事断裂", "评分项证据覆盖不足"),
    }
    for name in item_rule_map.get(item, ()):
        if name in rule_names:
            missing.append(f"当前已触发“{name}”，说明这项证据链还不够扎实。")

    for gap in structural_gaps[:2]:
        if gap not in missing:
            missing.append(gap)

    deduped: list[str] = []
    for text in missing:
        if text and text not in deduped:
            deduped.append(text)
    return deduped[:3]


def _build_competition_rubric_breakdown(diag: dict, kg: dict) -> list[dict[str, Any]]:
    rubric = diag.get("rubric", []) or []
    rows: list[dict[str, Any]] = []
    for row in rubric:
        if not isinstance(row, dict):
            continue
        item = str(row.get("item", ""))
        score_10 = float(row.get("score", 0) or 0)
        score_5 = round(max(0.0, min(5.0, score_10 / 2)), 1)
        weight = float(row.get("weight", 0) or 0)
        missing = _match_competition_missing(item, diag, kg)
        fix_cfg = _COMPETITION_FIX_LIBRARY.get(item, {})
        fix_24h = str(fix_cfg.get("fix_24h", "补一页能被评委快速理解的核心证据。"))
        fix_72h = str(fix_cfg.get("fix_72h", "补一轮更完整的验证材料，并重写对应展示页。"))
        if score_5 <= 2.0 and not missing:
            missing = ["当前该维度证据不足，无法支撑竞赛场景下的说服力。"]
        rows.append({
            "item": item,
            "item_label": _COMPETITION_ITEM_LABELS.get(item, item),
            "weight": weight,
            "estimated_score_0_5": score_5,
            "missing_evidence": missing,
            "minimal_fix_24h": fix_24h,
            "minimal_fix_72h": fix_72h,
        })
    return rows


def _format_competition_breakdown_md(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    parts = ["## Rubric 逐项评分"]
    for row in rows:
        parts.append(
            f"### {row['item_label']}（权重 {round(float(row.get('weight', 0)) * 100)}%）\n"
            f"- **Estimated Score**: {row['estimated_score_0_5']}/5\n"
            + ("- **Missing Evidence**: " + "；".join(row.get("missing_evidence", [])) + "\n" if row.get("missing_evidence") else "")
            + f"- **24h Fix**: {row['minimal_fix_24h']}\n"
            + f"- **72h Fix**: {row['minimal_fix_72h']}"
        )
    return "\n\n".join(parts)


def _coach_analyze(state: dict) -> dict:
    msg = state.get("message", "")
    mode = state.get("mode", "coursework")
    diag = state.get("diagnosis", {})
    rag_ctx = state.get("rag_context", "")
    kg = state.get("kg_analysis", {})
    ws = state.get("web_search_result", {})
    next_task = state.get("next_task", {}) if isinstance(state.get("next_task"), dict) else {}
    ws_ctx = _fmt_ws(ws)
    conv_ctx = _build_conv_ctx(state)
    hs = state.get("hypergraph_student", {})
    hs_ctx = _fmt_hyper_student(hs)

    mode_hint = {
        "coursework": "当前是课程辅导模式，侧重帮学生完成作业，注重逻辑完整性和方法论。",
        "competition": "当前是竞赛教练模式，以专业、严谨、有证据的方式帮助学生提升竞争力，不要咄咄逼人。",
        "learning": "当前是项目教练模式，重点是识别当前阶段最关键的瓶颈，并把下一步任务收敛成一个可执行动作。",
    }.get(mode, "")

    if mode == "learning" and _is_direct_solution_request(msg):
        return {
            "agent": "项目教练",
            "analysis": _coach_guardrail_reply(state),
            "tools_used": ["diagnosis", "challenge_strategies", "next_task"],
        }

    neo4j_ctx = ""
    if _graph_service and kg.get("entities"):
        top_labels = [e["label"] for e in kg["entities"][:5] if e.get("label")]
        try:
            related = _graph_service.find_similar_entities(top_labels, limit=5)
            if related:
                neo4j_ctx = "; ".join(
                    f"{r.get('entity','')}→{r.get('related_entity','')}"
                    for r in related[:5] if r.get("entity")
                )
        except Exception:
            pass

    stage_label = _project_stage_label(str(diag.get("project_stage", "")))
    bottleneck = str(diag.get("bottleneck") or "当前材料里最核心的缺口还没有被充分证明。")
    msg_snippet = " ".join(str(msg).split())[:120]
    evidence_used = _coach_evidence_used(diag) or [f"原文整体片段：“{msg_snippet}”"]
    primary_rule = ""
    rules = diag.get("triggered_rules", []) or []
    if rules and isinstance(rules[0], dict):
        primary_rule = str(rules[0].get("impact") or rules[0].get("name") or "")
    impact_if_unfixed = primary_rule or "如果不先修复这个缺口，后续商业模式、路演和评分都会建立在不稳定前提上。"
    task_title = str(next_task.get("title") or "补齐当前最高风险点")
    task_description = str(next_task.get("description") or "围绕当前最关键瓶颈，先完成一项能显著降低不确定性的任务。")
    task_template = next_task.get("template_guideline") or ["先明确问题", "补关键证据", "按验收标准复核"]
    task_acceptance = next_task.get("acceptance_criteria") or ["有明确交付物", "能支撑当前诊断", "可被复核"]

    if mode == "coursework":
        coach_json = _llm.chat_json(
            system_prompt=(
                "你是课程辅导模式下的项目导师。请输出 JSON，字段必须包含："
                "opening_assessment, why_this_matters, method_bridge, next_focus, source_note。\n"
                "要求：\n"
                "- opening_assessment 先就事论事回应学生项目当前状态，不要套模板\n"
                "- why_this_matters 解释为什么这个问题值得先想清楚\n"
                "- method_bridge 要把问题上升为学生以后也能复用的方法\n"
                "- next_focus 只给一个最值得先观察的切入点，不要展开成任务清单\n"
                "- 如果有案例、联网或图谱依据，可在 source_note 里自然交代\n"
            ),
            user_prompt=(
                f"模式提示: {mode_hint}\n"
                f"学生材料: {msg[:1400]}\n"
                + (f"对话上下文:\n{conv_ctx}\n\n" if conv_ctx else "")
                + f"项目阶段: {stage_label}\n"
                + f"当前瓶颈: {bottleneck}\n"
                + (f"KG洞察: {kg.get('insight','')}\n" if kg.get("insight") else "")
                + (f"超图分析: {hs_ctx[:300]}\n" if hs_ctx else "")
                + (f"案例参考: {rag_ctx[:400]}\n" if rag_ctx else "")
                + (f"联网搜索: {ws_ctx[:300]}\n" if ws_ctx else "")
                + (f"图谱关联: {neo4j_ctx}\n" if neo4j_ctx else "")
            ),
            temperature=0.35,
        ) if _llm.enabled else {}
        if not isinstance(coach_json, dict):
            coach_json = {}
        analysis = (
            "## 我先说判断\n"
            f"{str(coach_json.get('opening_assessment') or bottleneck).strip()}\n\n"
            "## 为什么这一步值得先想清楚\n"
            f"{str(coach_json.get('why_this_matters') or impact_if_unfixed).strip()}\n\n"
            "## 把它变成你以后也能复用的方法\n"
            f"{str(coach_json.get('method_bridge') or '你可以把当前问题拆回“用户-场景-证据-动作”四层，先确认自己到底卡在判断、证据还是执行。').strip()}\n\n"
            "## 你现在最该盯住的一个观察点\n"
            f"{str(coach_json.get('next_focus') or task_description).strip()}"
        )
        source_note = str(coach_json.get("source_note") or "").strip()
        if source_note:
            analysis += f"\n\n## 这次主要依据\n{source_note}"
    else:
        coach_json = _llm.chat_json(
            system_prompt=(
                "你是一位真正带项目推进的项目教练。请输出 JSON，字段必须包含："
                "opening_assessment, deep_reasoning, evidence_used(list), consequence, next_task_intro, source_note。\n"
                "要求：\n"
                "- opening_assessment 第一段就说明项目处于什么状态、真正卡在哪，不要写成报告标题堆砌\n"
                "- deep_reasoning 要把瓶颈和用户行为、替代方案、竞争、成本或执行条件讲透\n"
                "- evidence_used 需要引用学生原文或已有分析依据，2-3条即可\n"
                "- consequence 说明如果这个瓶颈继续不处理，会卡住什么\n"
                "- next_task_intro 只自然指出“最该先攻的一点”，不要展开成步骤、清单、验收标准\n"
                "- source_note 可自然说明本轮有没有参考案例、联网资料、知识图谱或超图\n"
                "- 语气像导师面对面讨论，不要机械复述“Project Stage / Current Diagnosis”这些英文标题\n"
                "- 如果学生声称没有竞争对手、市场一定很大、巨头不会进入，请优先结合联网信息或公开事实讨论，而不是只给空泛提醒\n"
                "- 你不是行动规划师，不要输出详细执行方案\n"
            ),
            user_prompt=(
                f"模式提示: {mode_hint}\n"
                f"学生材料: {msg[:1600]}\n"
                + (f"对话上下文:\n{conv_ctx}\n\n" if conv_ctx else "")
                + f"项目阶段: {stage_label}\n"
                + f"当前瓶颈: {bottleneck}\n"
                + (f"KG洞察: {kg.get('insight','')}\n" if kg.get("insight") else "")
                + (f"超图分析: {hs_ctx[:400]}\n" if hs_ctx else "")
                + (f"案例参考: {rag_ctx[:500]}\n" if rag_ctx else "")
                + (f"联网搜索: {ws_ctx[:350]}\n" if ws_ctx else "")
                + (f"图谱关联: {neo4j_ctx}\n" if neo4j_ctx else "")
                + "已有证据:\n"
                + "\n".join(f"- {item}" for item in evidence_used[:3])
                + f"\n影响提示: {impact_if_unfixed}\n"
            ),
            temperature=0.38,
        ) if _llm.enabled else {}
        if not isinstance(coach_json, dict):
            coach_json = {}
        coach_evidence = [str(item).strip() for item in (coach_json.get("evidence_used") or []) if str(item).strip()]
        if not coach_evidence:
            coach_evidence = evidence_used[:3]
        analysis = (
            f"你这个项目现在处在**{stage_label}**。"
            f"{str(coach_json.get('opening_assessment') or bottleneck).strip()}\n\n"
            f"{str(coach_json.get('deep_reasoning') or impact_if_unfixed).strip()}\n\n"
            "## 我主要是根据这些信息做这个判断\n"
            + "\n".join(f"- {item}" for item in coach_evidence[:3])
            + "\n\n## 如果这一点继续不处理\n"
            + f"{str(coach_json.get('consequence') or impact_if_unfixed).strip()}"
            + "\n\n## 你下一步最该先盯住的一点\n"
            + f"{str(coach_json.get('next_task_intro') or task_title).strip()}"
        )
        source_note = str(coach_json.get("source_note") or "").strip()
        if source_note:
            analysis += f"\n\n## 这次主要依据\n{source_note}"
    return {
        "agent": "项目教练",
        "analysis": analysis or "",
        "tools_used": ["diagnosis", "rag", "kg_extract", "web_search", "hypergraph"],
    }


def _analyst_analyze(state: dict) -> dict:
    msg = state.get("message", "")
    diag = state.get("diagnosis", {})
    kg = state.get("kg_analysis", {})
    hs = state.get("hypergraph_student", {})
    hyper_insight = state.get("hypergraph_insight", {})
    conv_ctx = _build_conv_ctx(state)
    coach_out = state.get("coach_output", {})

    rules = diag.get("triggered_rules", []) or []
    bottleneck = diag.get("bottleneck", "")
    rule_summary = "; ".join(
        f"{r.get('id','')}:{r.get('name','')}" for r in rules[:5] if isinstance(r, dict)
    )

    hyper_risk_ctx = ""
    if hs.get("ok"):
        warnings = hs.get("pattern_warnings", [])
        missing = hs.get("missing_dimensions", [])
        if warnings:
            hyper_risk_ctx += "超图风险预警: " + "; ".join(w["warning"] for w in warnings[:2]) + "\n"
        if missing:
            critical = [m for m in missing if m.get("importance") in ("极高", "高")]
            if critical:
                hyper_risk_ctx += "关键缺失维度: " + "; ".join(
                    f"{m['dimension']}—{m['recommendation']}" for m in critical[:3]
                ) + "\n"

    teaching_edge_ctx = ""
    edges = hyper_insight.get("edges", []) if isinstance(hyper_insight, dict) else []
    if edges:
        teaching_edge_ctx = "教学超边命中: " + "; ".join(
            f"{str(edge.get('type', ''))}:{str(edge.get('teaching_note', '') or edge.get('summary', ''))[:60]}"
            for edge in edges[:3] if isinstance(edge, dict)
        )

    analysis = _llm.chat_text(
        system_prompt=(
            "你是一位经验丰富的投资人，正在对这个创业项目做尽职调查式的风险评估。\n"
            "你的分析必须：\n"
            "1. **先客观评估项目整体质量**：如果项目逻辑基本通顺、商业模式合理，"
            "你应该先肯定做得好的部分，然后指出可以改进的细节，而非硬找致命问题\n"
            "2. 只有在逻辑确实存在明显漏洞时（如获客渠道与用户完全不匹配、财务数据明显不合理），"
            "才指出致命风险，用具体的反事实情境说明后果\n"
            "3. 提出2-3个学生应该思考的追问（针对他们项目的具体内容，难度匹配项目质量）\n"
            "4. 引用学生内容中的具体表述来讨论\n"
            "5. 如果超图分析发现了缺失维度或风险模式，评估其严重程度再决定是否重点提出\n"
            "6. 如果教学超边给出了历史案例中的风险闭环或价值闭环，请把它当作补充论据，而不是忽略\n"
            "7. 如果有外部事实、行业案例或公开数据能帮助判断，请优先使用这些具体事实，而不是空泛提醒学生去调研\n"
            "8. 如果前面的教练分析已经指出某些问题，你聚焦补充而不重复\n"
            "**重要：不要对一个逻辑基本完善的项目硬凑大量问题。好项目只需要给出提升建议即可。**\n"
            "语气专业犀利但建设性。用3-5段话输出。"
        ),
        user_prompt=(
            f"学生说: {msg[:1200]}\n\n"
            + (f"对话上下文:\n{conv_ctx}\n\n" if conv_ctx else "")
            + f"诊断瓶颈: {bottleneck}\n"
            + f"触发风险规则: {rule_summary}\n"
            + f"KG结构缺陷: {kg.get('structural_gaps', [])}\n"
            + (f"教练分析摘要: {str(coach_out.get('analysis',''))[:300]}\n" if coach_out.get("analysis") else "")
            + (f"{hyper_risk_ctx}" if hyper_risk_ctx else "")
            + (f"{teaching_edge_ctx}\n" if teaching_edge_ctx else "")
        ),
        temperature=0.35,
    )
    return {
        "agent": "风险分析师",
        "analysis": analysis or "",
        "tools_used": ["diagnosis", "kg_analysis", "hypergraph_student", "hypergraph"],
    }


def _advisor_analyze(state: dict) -> dict:
    msg = state.get("message", "")
    mode = state.get("mode", "coursework")
    rag_ctx = state.get("rag_context", "")
    diag = state.get("diagnosis", {})
    kg = state.get("kg_analysis", {})
    conv_ctx = _build_conv_ctx(state)
    coach_out = state.get("coach_output", {})

    comp_urgency = "竞赛教练模式——学生正在备赛，请以专业评委和教练的标准帮助他提升获奖概率，但保持克制、严谨、基于证据。" if mode == "competition" else ""

    n_rules = len(diag.get("triggered_rules", []) or [])
    quality_hint = ""
    if n_rules <= 2:
        quality_hint = (
            "\n**注意：这个项目的规则诊断只触发了少量风险，说明逻辑较为完善。**\n"
            "不要硬凑问题。对于好项目，重点给出提升性建议（如何从85分提到95分），"
            "而不是当成问题项目来严厉批评。\n"
        )

    breakdown = _build_competition_rubric_breakdown(diag, kg)
    breakdown_md = _format_competition_breakdown_md(breakdown)

    llm_json = _llm.chat_json(
        system_prompt=(
            "你是一位专业的创业竞赛教练与评委顾问。请基于给定的逐项评分结果，输出JSON字段："
            "overview, top_risks(list), judge_questions(list), defense_tips(list), ppt_adjustments(list), prize_readiness(0-100)。\n"
            "要求：\n"
            "- 语气专业、克制、严谨，不要咄咄逼人\n"
            "- 风险要和逐项评分保持一致，不要另起炉灶\n"
            "- 优先指出最影响竞赛说服力的2-3个扣分点\n"
            "- judge_questions 要像真实评委会问的问题\n"
        ),
        user_prompt=(
            f"学生说:\n{msg[:1200]}\n模式:{mode}\n\n"
            + (f"对话上下文:\n{conv_ctx}\n\n" if conv_ctx else "")
            + (f"参考案例:\n{rag_ctx[:600]}\n\n" if rag_ctx else "")
            + (f"教练分析摘要:\n{str(coach_out.get('analysis',''))[:400]}\n\n" if coach_out.get('analysis') else "")
            + (f"诊断瓶颈:{diag.get('bottleneck','')}\n\n" if diag.get("bottleneck") else "")
            + f"Rubric逐项评分:\n{breakdown_md}"
        ),
        model=settings.llm_reason_model,
        temperature=0.25,
    ) if _llm.enabled else {}

    overview = str((llm_json or {}).get("overview") or "")
    top_risks = [str(x) for x in ((llm_json or {}).get("top_risks") or []) if x][:3]
    judge_questions = [str(x) for x in ((llm_json or {}).get("judge_questions") or []) if x][:3]
    defense_tips = [str(x) for x in ((llm_json or {}).get("defense_tips") or []) if x][:3]
    ppt_adjustments = [str(x) for x in ((llm_json or {}).get("ppt_adjustments") or []) if x][:3]
    prize_readiness = int((llm_json or {}).get("prize_readiness") or 0)

    if not overview:
        overview = (
            "我会优先看评委最容易扣分的地方：证据链是否扎实、商业逻辑是否闭环、以及你在路演现场能否经得住追问。"
        )

    sections = [
        "## 竞赛评估总览",
        overview,
    ]
    if top_risks:
        sections.append("## 当前最影响得分的风险\n" + "\n".join(f"- {item}" for item in top_risks))
    sections.append(breakdown_md)
    if judge_questions:
        sections.append("## 评委可能会追问\n" + "\n".join(f"- {item}" for item in judge_questions))
    if defense_tips:
        sections.append("## 答辩应对建议\n" + "\n".join(f"- {item}" for item in defense_tips))
    if ppt_adjustments:
        sections.append("## 路演材料优化\n" + "\n".join(f"- {item}" for item in ppt_adjustments))
    if prize_readiness:
        sections.append(f"## 当前竞赛准备度\n{prize_readiness}/100")

    analysis = "\n\n".join(section for section in sections if section.strip())
    return {
        "agent": "竞赛顾问",
        "analysis": analysis or "",
        "tools_used": ["competition_llm", "rubric_engine", "rag_reference"],
        "rubric_breakdown": breakdown,
        "judge_questions": judge_questions,
        "defense_tips": defense_tips,
        "ppt_adjustments": ppt_adjustments,
        "prize_readiness": prize_readiness,
    }


def _tutor_analyze(state: dict) -> dict:
    mode = state.get("mode", "coursework")
    analysis, kg_nodes = _build_learning_tutor_reply(state, structured=True)
    tools = ["learning_llm"]
    if state.get("rag_context"):
        tools.append("rag_reference")
    if state.get("web_search_result", {}).get("searched"):
        tools.append("web_search")
    if kg_nodes:
        tools.append("kg_baseline")
    return {
        "agent": "课程导师" if mode == "coursework" else "学习导师",
        "analysis": analysis or "",
        "tools_used": tools,
        "retrieved_kg_nodes": kg_nodes,
        "mode": mode,
    }


def _grader_analyze(state: dict) -> dict:
    diag = state.get("diagnosis", {})
    kg = state.get("kg_analysis", {})
    rubric = diag.get("rubric", [])
    overall = diag.get("overall_score")
    sec_scores = kg.get("section_scores", {})

    if not rubric or overall is None:
        return {
            "agent": "评分官",
            "analysis": "信息不足，暂无法给出完整评分。请提供更详细的项目描述或上传计划书。",
            "tools_used": ["rubric_engine"],
        }

    lines = []
    for r in rubric:
        status = "✅" if r.get("status") == "ok" else "⚠️"
        lines.append(f"{status} {r['item']}: {r['score']}/10")
    score_text = "\n".join(lines)

    analysis = _llm.chat_text(
        system_prompt=(
            "你负责按照创业竞赛评审标准给项目打分。\n"
            "你的评估必须：\n"
            "1. 总结当前总分和各维度得分情况\n"
            "2. 评分要考虑项目阶段：初步规划但逻辑基本成立的项目，不应被写成接近零分或一无是处\n"
            "3. 指出得分最低的2个维度，分析为什么低\n"
            "4. 给出提分的具体操作建议（具体到添加什么内容）\n"
            "5. 指出距离优秀（8/10）还差多少，重点补什么\n"
            "用3-4段话输出，像一份评审反馈报告。"
        ),
        user_prompt=f"Rubric评分:\n{score_text}\n总分: {overall}/10\nKG维度评分: {sec_scores}",
        temperature=0.2,
    )
    return {
        "agent": "评分官",
        "analysis": analysis or "",
        "tools_used": ["rubric_engine", "kg_scores"],
    }


def _planner_analyze(state: dict) -> dict:
    msg = state.get("message", "")
    diag = state.get("diagnosis", {})
    next_task = state.get("next_task", {})
    kg = state.get("kg_analysis", {})
    hs = state.get("hypergraph_student", {})
    conv_ctx = _build_conv_ctx(state, limit=4)
    coach_out = state.get("coach_output", {})

    hs_missing_ctx = ""
    if hs.get("ok"):
        missing = hs.get("missing_dimensions", [])
        if missing:
            hs_missing_ctx = "超图缺失维度(按紧急度): " + "; ".join(
                f"{m['dimension']}({m['importance']})" for m in missing[:4]
            )

    kg_entities = kg.get("entities", [])
    entity_ctx = ""
    if kg_entities:
        entity_ctx = "已识别的核心实体: " + "; ".join(
            f"{e.get('label','')}({e.get('type','')})" for e in kg_entities[:8]
        )

    plan = _llm.chat_json(
        system_prompt=(
            "你是行动规划师。基于学生具体内容的分析结果，为学生生成具体可执行的行动任务。\n\n"
            "**核心原则**：\n"
            "- 每个任务必须紧密结合学生实际描述的内容，引用学生提到的具体产品/人群/技术\n"
            "- 不要给出泛泛的建议如'做调研'，而是'针对你提到的XX用户群，在XX场景下做8份深度访谈'\n"
            "- 如果学生上传了文件，任务应该针对文件中具体薄弱的部分给出修改建议\n"
            "- 如果对话上下文显示之前已建议过某些任务，不要重复，给出递进的新任务\n"
            "- 任务数量1-3个即可，宁精勿多\n\n"
            '输出JSON: {"this_week":['
            '{"task":"针对XX的具体任务名","why":"为什么这对你的项目关键",'
            '"how":"具体做法(3-5步，引用学生内容)","acceptance":"可衡量的验收标准"}],'
            '"milestone":"本阶段目标(用学生的项目语言描述)"}'
        ),
        user_prompt=(
            f"学生说: {msg[:800]}\n\n"
            + (f"对话上下文:\n{conv_ctx}\n\n" if conv_ctx else "")
            + f"诊断瓶颈: {diag.get('bottleneck','')}\n"
            + (f"{entity_ctx}\n" if entity_ctx else "")
            + f"结构缺陷: {kg.get('structural_gaps',[])}\n"
            + f"内容优势: {kg.get('content_strengths',[][:2])}\n"
            + (f"教练核心发现: {str(coach_out.get('analysis',''))[:300]}\n" if coach_out.get("analysis") else "")
            + (f"{hs_missing_ctx}\n" if hs_missing_ctx else "")
        ),
        temperature=0.25,
    )

    analysis_text = ""
    if plan:
        tasks = plan.get("this_week", [])
        if tasks:
            parts = []
            for t in tasks[:3]:
                parts.append(f"- **{t.get('task','')}**: {t.get('how','')}")
                if t.get("acceptance"):
                    parts.append(f"  验收标准: {t['acceptance']}")
            analysis_text = "本周建议行动:\n" + "\n".join(parts)
        if plan.get("milestone"):
            analysis_text += f"\n\n阶段目标: {plan['milestone']}"

    return {
        "agent": "行动规划师",
        "analysis": analysis_text,
        "tools_used": ["diagnosis", "next_task", "critic"],
        "plan_data": plan or {},
    }


AGENT_FNS: dict[str, Callable] = {
    "coach": _coach_analyze,
    "analyst": _analyst_analyze,
    "advisor": _advisor_analyze,
    "tutor": _tutor_analyze,
    "grader": _grader_analyze,
    "planner": _planner_analyze,
}

AGENT_DISPLAY: dict[str, str] = {
    "coach": "项目教练",
    "analyst": "风险分析师",
    "advisor": "竞赛顾问",
    "tutor": "课程导师",
    "grader": "评分官",
    "planner": "行动规划师",
}


# ═══════════════════════════════════════════════════════════════════
#  Node 3: Hybrid Agent Selection (Static Rules + Dynamic Heuristics)
#           + Serial Execution
# ═══════════════════════════════════════════════════════════════════

_SCORING_SIGNALS = frozenset(["评分", "打分", "得分", "几分", "怎么评", "多少分", "分数"])
_PLANNING_SIGNALS = frozenset(["下一步", "怎么办", "怎么推进", "行动", "计划", "路线", "优先级", "先做什么", "任务"])

_AGENT_ORDER = ("coach", "analyst", "advisor", "tutor", "grader", "planner")


def _decide_agents(state: WorkflowState) -> tuple[list[str], str]:
    """Hybrid agent selection: static guarantees + dynamic heuristics.

    STATIC RULES — non-negotiable, ensure consistent behaviour:
      • File upload (any intent)            → Coach + Grader + Planner
      • competition mode OR intent          → + Advisor
      • Explicit scoring keywords in msg    → + Grader

    DYNAMIC HEURISTICS — data-driven, provide flexibility:
      • Coach   : diagnosis triggered rules > 0 OR KG entities ≥ 2
                   OR intent is a project-analysis type
      • Analyst : high-severity risks detected OR pressure_test intent
                   OR evidence_check intent with multiple rules
      • Tutor   : learning mode AND intent is not a focused-type
      • Planner : KG entities ≥ 3 with project intent,
                   OR coach is running AND diagnosis rules ≥ 2

    Returns agents in canonical order (Coach → Analyst → Advisor →
    Tutor → Grader → Planner) so later agents can reference earlier output.
    """
    intent = state.get("intent", "general_chat")
    mode = state.get("mode", "coursework")
    intent_shape = _normalize_intent_shape(state.get("intent_shape", "single"))
    msg = state.get("message", "")
    conv = state.get("conversation_messages", [])
    is_file = "[上传文件:" in msg
    diag = state.get("diagnosis", {})
    kg = state.get("kg_analysis", {})
    intent_pipeline = [a for a in (state.get("intent_pipeline", []) or []) if a in AGENT_FNS]
    intent_confidence = float(state.get("intent_confidence", 0) or 0)
    rules = diag.get("triggered_rules", []) or []
    kg_entity_count = len(kg.get("entities", []))
    high_risk = sum(1 for r in rules if isinstance(r, dict) and r.get("severity") == "high")
    complexity = _message_complexity(msg, conv)
    asks_for_plan = any(w in msg for w in _PLANNING_SIGNALS)
    asks_for_score = any(w in msg for w in _SCORING_SIGNALS)

    selected: set[str] = set()
    reasons: list[str] = []

    if intent_confidence >= 0.35:
        selected.update(intent_pipeline)
        if intent_pipeline:
            reasons.append(f"路由阶段先给出主 agent：{' / '.join(intent_pipeline[:2])}")

    # ═══ STATIC RULES (guaranteed, non-negotiable) ═══

    if is_file:
        selected.add("coach")
        reasons.append("上传文件后至少保留项目教练做主线分析")
        if asks_for_plan or complexity >= 3:
            selected.add("planner")
        if asks_for_score or mode == "competition":
            selected.add("grader")

    if mode == "competition" or intent == "competition_prep":
        selected.add("advisor")
        reasons.append("竞赛模式或竞赛意图优先引入竞赛顾问")

    if asks_for_score:
        selected.add("grader")
        reasons.append("学生明确问到评分/得分，因此加入评分官")

    # ═══ DYNAMIC HEURISTICS (data-driven) ═══

    if not selected and intent in AGENT_FNS:
        selected.add(intent)

    if intent_shape == "single":
        if intent == "learning_concept":
            selected = {"coach"} if mode == "learning" else {"tutor"}
            reasons.append("单一概念问题保持单导师回复")
        elif intent == "market_competitor":
            if mode == "competition":
                selected = {"advisor"}
            elif mode == "learning":
                selected = {"coach"}
            else:
                selected = {"tutor"}
            reasons.append("单一竞品/同类问题保持单主线检索解答")
        elif intent == "business_model":
            selected.add("coach")
            if high_risk >= 1 or len(rules) >= 2:
                selected.add("analyst")
                reasons.append("商业模式问题触发明显风险，因此补风险分析师")
        elif intent == "evidence_check":
            selected.add("analyst")
            if asks_for_plan:
                selected.add("planner")
        elif intent == "pressure_test":
            selected.update(("analyst", "coach"))
            reasons.append("压力测试至少需要风险分析与教练追问配合")
        elif intent == "project_diagnosis":
            selected.add("coach")
            if high_risk >= 1 or len(rules) >= 2:
                selected.add("analyst")
        elif intent == "idea_brainstorm":
            selected = {"coach"} if mode != "coursework" else {"tutor"}
    else:
        if intent == "project_diagnosis":
            selected.update(("coach", "analyst"))
            if mode == "coursework":
                selected.add("tutor")
        elif intent == "business_model":
            selected.update(("coach", "analyst"))
        elif intent == "evidence_check":
            selected.update(("analyst", "coach"))
        elif intent == "market_competitor":
            if mode == "competition":
                selected.update(("advisor", "analyst"))
            else:
                selected.update(("tutor", "analyst", "coach"))
        elif intent == "competition_prep":
            selected.update(("advisor", "coach"))
            if high_risk >= 1 or len(rules) >= 2:
                selected.add("analyst")
        elif intent == "pressure_test":
            selected.update(("analyst", "coach"))
            if mode == "competition" or complexity >= 4:
                selected.add("advisor")
        elif intent == "learning_concept":
            selected.update(("coach", "tutor") if mode == "coursework" else ("coach",))
        elif intent == "idea_brainstorm":
            selected.update(("coach", "tutor"))
        reasons.append("混合问题允许多 agent 协同，但保持主线清晰")

    if mode == "learning":
        selected.discard("tutor")
        selected.discard("advisor")
        selected.discard("grader")
        selected.add("coach")
        if asks_for_plan or is_file:
            selected.add("planner")
        reasons.append("项目教练模式收敛为教练主导")

    if mode == "coursework" and intent in ("learning_concept", "market_competitor") and intent_shape == "single":
        selected.discard("coach")
        selected.discard("analyst")
        selected.discard("planner")
        reasons.append("课程辅导下的单一知识型问题尽量保持单导师")

    if asks_for_plan and intent in ("project_diagnosis", "business_model", "evidence_check", "idea_brainstorm", "competition_prep"):
        selected.add("planner")
        reasons.append("学生明确在问下一步/行动方案，因此补行动规划师")

    if (high_risk >= 1 or len(rules) >= 3) and intent not in ("learning_concept", "general_chat"):
        selected.add("analyst")

    # Cap complex paths to avoid runaway fan-out.
    ordered = [a for a in _AGENT_ORDER if a in selected]
    max_agents = 6 if intent_shape == "mixed" else 3
    ordered = ordered[:max_agents]
    if len(ordered) == 0:
        ordered = ["coach"]
    reasoning = "；".join(dict.fromkeys(reasons)) or "按主意图选择最小必要 agent 集合"
    return ordered, reasoning


def run_role_agents_node(state: WorkflowState) -> dict:
    intent = state.get("intent", "general_chat")

    if state.get("needs_clarification"):
        logger.info("intent '%s' → clarification mode, skip role agents", intent)
        return {
            "agents_called": ["[信息补全]"],
            "resolved_agents": [],
            "agent_reasoning": "当前进入信息补全阶段，先不调用角色智能体。",
            "nodes_visited": ["role_agents"],
        }

    # ── PATH A: Focused intents → orchestrator handles alone ──
    if _should_use_focused_mode(state):
        logger.info("intent '%s' → focused mode, no agents", intent)
        return {
            "agents_called": [f"[聚焦模式: {intent}]"],
            "resolved_agents": [],
            "agent_reasoning": "当前问题足够聚焦，由编排器直接生成回答，不额外拆分角色智能体。",
            "nodes_visited": ["role_agents"],
        }

    # ── PATH B: Static + dynamic selection → serial execution ──
    agents_to_run, agent_reasoning = _decide_agents(state)

    if not agents_to_run:
        logger.info("_decide_agents returned empty → orchestrator-only")
        return {
            "agents_called": ["[数据不足，直接回复]"],
            "resolved_agents": [],
            "agent_reasoning": "当前可用上下文不足，未拆分额外角色智能体。",
            "nodes_visited": ["role_agents"],
        }

    logger.info("Dynamic agent selection: %s (intent=%s)", agents_to_run, intent)
    outputs: dict[str, dict] = {}
    state_snapshot = dict(state)

    for agent_key in agents_to_run:
        fn = AGENT_FNS.get(agent_key)
        if not fn:
            continue
        try:
            result = fn(state_snapshot)
            outputs[agent_key] = result
            state_snapshot[f"{agent_key}_output"] = result
        except Exception as exc:
            logger.warning("Agent %s failed: %s", agent_key, exc)
            outputs[agent_key] = {
                "agent": AGENT_DISPLAY.get(agent_key, agent_key),
                "analysis": "",
                "tools_used": [],
                "error": str(exc),
            }

    result_dict: dict[str, Any] = {
        "agents_called": [AGENT_DISPLAY.get(a, a) for a in agents_to_run],
        "resolved_agents": list(agents_to_run),
        "agent_reasoning": agent_reasoning,
        "nodes_visited": ["role_agents"],
    }
    for key in ("coach", "analyst", "advisor", "tutor", "grader", "planner"):
        if key in outputs:
            result_dict[f"{key}_output"] = outputs[key]

    return result_dict


# ═══════════════════════════════════════════════════════════════════
#  Node 4: Orchestrator — synthesise all agent outputs
# ═══════════════════════════════════════════════════════════════════

_MODE_PERSONA: dict[str, str] = {
    "coursework": (
        "你是一位会带学生学会做项目的课程导师。"
        "你的目标不是急着判分，而是结合学生当前项目讲清方法、概念、判断依据和下一步观察点。"
        "你会优先把抽象方法落回学生项目，必要时结合案例、公开事实、RAG 和本地知识图谱辅助讲解。"
        "语气耐心、具体、像老师在办公室里一对一辅导。"
    ),
    "competition": (
        "你是一位资深创业竞赛教练，对互联网+、挑战杯等赛事非常熟悉。"
        "你的目标是帮助学生提高获奖概率，侧重评委视角、证据链、路演打磨和竞争力提升。"
        "语气专业、克制、严谨，像有依据的高水平教练。"
    ),
    "learning": (
        "你是一位真正负责推进项目的项目教练。"
        "你的目标是识别项目当前阶段最关键的瓶颈，解释为什么它才是瓶颈，并把下一步动作收敛成一个最关键、可验收的任务。"
        "你坚持启发式提问，不替学生代写答案；更关注推进顺序、验证逻辑、替代方案、竞争约束和资源约束。"
    ),
}


# ── Intent-specific prompts for focused (single-call) mode ──
_FOCUSED_PROMPTS: dict[str, str] = {
    "market_competitor": (
        "学生在问竞品/同类产品/市场情况。你的任务：\n"
        "1. 基于搜索结果列出3-5个真实的同类产品/竞品，每个用1-2句介绍核心卖点\n"
        "2. 做一个对比表格（产品名、核心功能、目标用户、定价、优劣势、来源链接）\n"
        "3. 分析学生项目和这些竞品的差异化在哪里\n"
        "4. 推荐2-3个最值得学习的产品，具体说明学什么\n"
        "5. 如果搜索结果不够，基于你的知识补充，但要明确哪些是搜索得到的\n"
        "用800-1400字回复。必须有具体产品名、差异化分析和来源链接。"
    ),
    "learning_concept": (
        "学生想学习一个概念或方法论。你的任务：\n"
        "1. 先结合学生当前项目，说明他为什么现在需要理解这个概念\n"
        "2. 再用一句话通俗定义这个概念（不要教科书式定义）\n"
        "3. 举2-3个真实的创业案例来解释（具体公司名、做了什么、结果如何）\n"
        "4. 如果搜索结果有最新信息，引用具体数据、事实和链接\n"
        "5. 给学生一个本周就能做的练习任务（非常具体，可执行）\n"
        "6. 指出学生最容易踩的坑\n"
        "7. 如果学生的项目上下文已知，把概念和他的项目关联起来解释，并告诉他先观察什么信号\n"
        "用700-1200字回复。像真实导师，不要像百科词条。"
    ),
    "idea_brainstorm": (
        "学生想要创业方向建议。你的任务：\n"
        "1. 基于搜索到的趋势和学生的兴趣/背景，给出3-5个具体的方向\n"
        "2. 每个方向说清楚：目标用户是谁、解决什么痛点、变现方式\n"
        "3. 简要分析每个方向的难度和资源要求\n"
        "4. 推荐一个最适合学生现状的方向，说明理由\n"
        "5. 给出这个方向的第一步行动\n"
        "6. 如果用了搜索结果，补充1-2条外部趋势依据或案例链接\n"
        "用700-1100字回复。具体、可行、有启发性。"
    ),
    "general_chat": (
        "学生在闲聊或打招呼。你的任务：\n"
        "1. 热情友好地回复\n"
        "2. 如果有对话上下文（之前讨论过项目），自然地衔接：'上次你提到的XX项目，现在进展如何？'\n"
        "3. 如果完全是新对话，引导学生聊他的项目想法\n"
        "用100-250字回复。自然、亲切。"
    ),
}


def _build_gathered_context(state: WorkflowState) -> str:
    """Build context string from all gathered data for focused single-call mode."""
    parts: list[str] = []

    # Web search results (primary for market/learning questions)
    ws = state.get("web_search_result", {})
    if ws.get("searched") and ws.get("results"):
        parts.append(f"## 联网搜索结果（关键词: {ws.get('query', '')}）")
        for r in ws.get("results", [])[:5]:
            parts.append(f"- **{r.get('title','')}**: {r.get('snippet','')}")
            if r.get("url"):
                parts.append(f"  链接: {r['url']}")

    # KG analysis
    kg = state.get("kg_analysis", {})
    if kg.get("entities"):
        entities_str = "; ".join(f"{e.get('label','')}({e.get('type','')})" for e in kg["entities"][:10])
        parts.append(f"\n## 已识别实体\n{entities_str}")
        if kg.get("insight"):
            parts.append(f"KG洞察: {kg['insight']}")
        if kg.get("structural_gaps"):
            parts.append(f"结构缺陷: {', '.join(kg['structural_gaps'][:3])}")

    # RAG cases
    rag_ctx = state.get("rag_context", "")
    if rag_ctx:
        parts.append(f"\n## 参考案例\n{rag_ctx[:600]}")

    # Hypergraph
    hs = state.get("hypergraph_student", {})
    if hs.get("ok"):
        parts.append(f"\n## 超图分析\n维度覆盖: {hs.get('coverage_score', 0)}/10")
        missing = hs.get("missing_dimensions", [])
        if missing:
            parts.append(f"缺失维度: {', '.join(m['dimension'] for m in missing[:3])}")

    # Diagnosis
    diag = state.get("diagnosis", {})
    if diag.get("bottleneck"):
        parts.append(f"\n## 诊断\n瓶颈: {diag['bottleneck']}")

    return "\n".join(parts)


def orchestrator(state: WorkflowState) -> dict:
    msg = state.get("message", "")
    intent = state.get("intent", "general_chat")
    mode = state.get("mode", "coursework")
    conv_msgs = state.get("conversation_messages", [])
    hist = state.get("history_context", "")
    tfb = state.get("teacher_feedback_context", "")
    is_file = "[上传文件:" in msg

    # Collect multi-agent analyses (only present for complex intents)
    analysis_parts: list[str] = []
    for key in ("coach_output", "analyst_output", "advisor_output",
                "tutor_output", "grader_output", "planner_output"):
        out = state.get(key, {})
        if out and out.get("analysis"):
            analysis_parts.append(f"### {out.get('agent', key)}\n{str(out['analysis'])}")

    conv_ctx = ""
    if conv_msgs:
        recent = conv_msgs[-6:]
        conv_ctx = "\n".join(
            f"{'学生' if m.get('role')=='user' else '教练'}: {str(m.get('content',''))[:200]}"
            for m in recent
        )

    persona = _MODE_PERSONA.get(mode, _MODE_PERSONA["coursework"])
    analyses_ctx = "\n\n---\n\n".join(analysis_parts)

    reply = ""

    if state.get("needs_clarification"):
        return {"assistant_message": _build_clarification_reply(state), "nodes_visited": ["orchestrator"]}

    diag = state.get("diagnosis", {})
    n_triggered = len(diag.get("triggered_rules", []) or [])
    quality_tone = ""
    if n_triggered <= 2:
        quality_tone = (
            "\n## 项目质量提示\n"
            "诊断引擎只触发了极少风险规则，说明该项目基础逻辑较为完善。\n"
            "你的回复应该**以肯定和提升为主**，而非以批评和挑刺为主：\n"
            "- 先明确肯定项目做得好的维度（如逻辑通顺、数据扎实、用户清晰等）\n"
            "- 然后给出**锦上添花**的优化建议（如何从85分提到95分），而非基础性问题\n"
            "- 追问也应该是有深度的、帮助项目更上一层楼的问题\n\n"
        )
    elif n_triggered >= 5:
        quality_tone = (
            "\n## 项目质量提示\n"
            "诊断引擎触发了较多风险规则，说明项目存在多个基础性问题。\n"
            "请优先聚焦最关键的2-3个问题深入分析，不要面面俱到。\n\n"
        )

    if _llm.enabled and analyses_ctx:
        # ── PATH A: Multi-agent synthesis (complex intents) ──
        msg_len = len(msg)
        n_analyses = len(analysis_parts)
        if is_file:
            length_guide = "1800-3600字。逐段分析文件内容，引用原文，对比案例，给出具体修改建议。"
        elif n_analyses >= 4:
            length_guide = "1500-3200字。充分整合所有分析维度，逐一覆盖每个重要发现和子问题。"
        elif n_analyses >= 3:
            length_guide = "1200-2800字。充分整合所有分析维度，每个重要发现都要展开讨论。"
        elif n_analyses >= 2:
            length_guide = "900-2000字。深入分析关键问题，引用案例和证据，不遗漏重要发现。"
        elif msg_len > 200:
            length_guide = "700-1400字。针对学生具体内容深入展开。"
        else:
            length_guide = "450-900字。聚焦问题给出有深度的建议。"

        reply = _llm.chat_text(
            system_prompt=(
                f"{persona}\n"
                "你已经从多个专业角度对学生的问题进行了深入分析，"
                "现在需要将这些分析**完整**整合成一份自然、连贯、有深度的回复。\n\n"
                "## 绝对禁止\n"
                "- **绝对不要提到Agent、分析师、教练等角色名称**\n"
                "- 不要说'根据分析'、'经过系统分析'等套话\n"
                "- **严禁万金油建议**：不许动不动就建议'做用户访谈''发放问卷''做市场调研'。"
                "  如果确实需要调研，必须说清楚：调研什么假设、找什么人、问什么问题。\n\n"
                + quality_tone
                + "## 核心原则：完整整合，不遗漏精华\n"
                "- **你必须完整覆盖所有分析中提到的重要发现**，不要只挑1-2个点\n"
                "- 如果分析中提出了3-4个有价值的质疑或发现，你应该全部展开讨论\n"
                "- 如果学生在一条消息里问了多个子问题、多个场景或多个产品方向，要逐项回应，不要只答前三点\n"
                "- 每个发现都要结合学生的具体内容深入展开，给出数据、案例或逻辑推演\n"
                "- 如果上下文里出现了联网搜索结果，请在合适位置引用来源名称，并在结尾整理1-3条可点击链接\n"
                "- 宁可回复长一点内容扎实，也不要为了简短而丢掉好的分析洞察\n\n"
                "## 回复逻辑结构\n"
                "1. **总览**（1-2句）：概括你对项目的整体判断\n"
                "2. **逻辑链路**：用户是谁→痛点→方案→变现→壁垒，哪些通哪些断\n"
                "3. **逐一展开核心问题**：将分析中发现的每个重要问题都展开讨论，"
                "引用学生原话，给具体例子或数据说明为什么这是问题、怎么改\n"
                "4. **下一步行动**：给出按优先级排序的具体动作\n"
                "5. **追问**：提出2-3个有深度的苏格拉底式问题引导学生思考\n"
                "6. **外部参考**：如果已提供联网结果，列出1-3个来源链接\n\n"
                "## 必须做到\n"
                "- 第一人称回复，像导师面对面聊天\n"
                "- 紧扣学生具体内容，引用原话讨论\n"
                "- 排版清晰：## 标题分块、> 引用突出、**加粗**关键词、表格呈现对比\n"
                "- 回复末尾附上：⚠ AI生成，仅供参考\n"
                f"- **回复长度**: {length_guide}\n"
            ),
            user_prompt=(
                f"学生说：\n{msg[:3000]}\n\n"
                + (f"对话上下文：\n{conv_ctx}\n\n" if conv_ctx else "")
                + (f"教师批注: {tfb}\n\n" if tfb else "")
                + (f"历史: {hist[:300]}\n\n" if hist else "")
                + f"以下是已完成的深入分析结果，请整合为自然的回复：\n\n{analyses_ctx}"
            ),
            model=settings.llm_reason_model,
            temperature=0.55,
        )

    elif _llm.enabled:
        # ── PATH B: Focused single-call (simple/focused intents) ──
        gathered = _build_gathered_context(state)
        focused_prompt = _FOCUSED_PROMPTS.get(intent, "")

        if intent == "learning_concept":
            reply, _ = _build_learning_tutor_reply(state, structured=True)
        elif focused_prompt:
            logger.info("Orchestrator: focused mode for intent '%s'", intent)
            reply = _llm.chat_text(
                system_prompt=(
                    f"{persona}\n{focused_prompt}\n\n"
                    "## 通用要求\n"
                    "- 第一人称回复，像导师面对面聊天\n"
                    "- 不要提到任何系统内部结构（Agent、模块等）\n"
                    "- 排版清晰：## 标题、> 引用、**加粗**、表格\n"
                    "- 紧扣学生的实际项目和上下文\n"
                ),
                user_prompt=(
                    f"学生说：{msg[:2000]}\n\n"
                    + (f"对话上下文：\n{conv_ctx}\n\n" if conv_ctx else "")
                    + (f"已收集的信息：\n{gathered}\n" if gathered else "")
                ),
                model=settings.llm_reason_model,
                temperature=0.5,
            )
        else:
            reply = _llm.chat_text(
                system_prompt=(
                    f"{persona}\n"
                    "用第一人称自然回复学生。不要暴露任何系统内部结构。"
                ),
                user_prompt=(
                    f"学生说: {msg[:500]}"
                    + (f"\n上下文: {conv_ctx}" if conv_ctx else "")
                ),
                temperature=0.55,
            )

    if not reply or len(reply.strip()) < 20:
        diag = state.get("diagnosis", {})
        bn = str(diag.get("bottleneck") or "")
        nt = state.get("next_task", {})
        reply = (
            f"**{bn}**\n\n> 下一步：{nt.get('title','')}"
            if bn
            else "你好！告诉我你的项目想法，我来帮你诊断和分析。"
        )

    return {"assistant_message": reply.strip(), "nodes_visited": ["orchestrator"]}


# ═══════════════════════════════════════════════════════════════════
#  Graph definition  (4 nodes, fixed pipeline)
# ═══════════════════════════════════════════════════════════════════

def _build() -> Any:
    g = StateGraph(WorkflowState)

    g.add_node("router", router_agent)
    g.add_node("gather", gather_context_node)
    g.add_node("agents", run_role_agents_node)
    g.add_node("orchestrator", orchestrator)

    g.set_entry_point("router")
    g.add_edge("router", "gather")
    g.add_edge("gather", "agents")
    g.add_edge("agents", "orchestrator")
    g.add_edge("orchestrator", END)

    return g.compile()


workflow = _build()


# ═══════════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════════

def run_workflow(
    message: str,
    mode: str = "coursework",
    project_state: dict | None = None,
    history_context: str = "",
    conversation_messages: list | None = None,
    teacher_feedback_context: str = "",
) -> dict[str, Any]:
    initial: WorkflowState = {
        "message": message,
        "mode": mode,
        "project_state": project_state or {},
        "history_context": history_context,
        "conversation_messages": conversation_messages or [],
        "teacher_feedback_context": teacher_feedback_context,
    }
    return workflow.invoke(initial)


def run_workflow_pre_orchestrate(
    message: str,
    mode: str = "coursework",
    project_state: dict | None = None,
    history_context: str = "",
    conversation_messages: list | None = None,
    teacher_feedback_context: str = "",
) -> dict[str, Any]:
    """Run router + gather + agents but NOT orchestrator. Returns state for streaming."""
    initial: WorkflowState = {
        "message": message,
        "mode": mode,
        "project_state": project_state or {},
        "history_context": history_context,
        "conversation_messages": conversation_messages or [],
        "teacher_feedback_context": teacher_feedback_context,
    }
    state = dict(initial)
    state.update(router_agent(state))
    state.update(gather_context_node(state))
    state.update(run_role_agents_node(state))
    return state


def stream_orchestrator(state: dict):
    """Generator that yields text chunks from the orchestrator LLM call."""
    msg = state.get("message", "")
    intent = state.get("intent", "general_chat")
    mode = state.get("mode", "coursework")
    conv_msgs = state.get("conversation_messages", [])
    hist = state.get("history_context", "")
    tfb = state.get("teacher_feedback_context", "")
    is_file = "[" + "\u4e0a\u4f20\u6587\u4ef6:" in msg

    analysis_parts: list[str] = []
    for key in ("coach_output", "analyst_output", "advisor_output",
                "tutor_output", "grader_output", "planner_output"):
        out = state.get(key, {})
        if out and out.get("analysis"):
            analysis_parts.append(f"### {out.get('agent', key)}\n{str(out['analysis'])}")

    conv_ctx = ""
    if conv_msgs:
        recent = conv_msgs[-6:]
        conv_ctx = "\n".join(
            f"{'学生' if m.get('role')=='user' else '教练'}: {str(m.get('content',''))[:200]}"
            for m in recent
        )

    msg_len = len(msg)
    n_analyses = len(analysis_parts)
    if is_file:
        length_guide = "1800-3200字"
    elif intent == "general_chat" or msg_len < 20:
        length_guide = "100-250字"
    elif n_analyses >= 4:
        length_guide = "1400-2600字"
    elif n_analyses >= 3:
        length_guide = "1200-2200字"
    elif n_analyses >= 2:
        length_guide = "900-1600字"
    else:
        length_guide = "500-1000字"

    analyses_ctx = "\n\n---\n\n".join(analysis_parts)
    persona = _MODE_PERSONA.get(mode, _MODE_PERSONA["coursework"])

    if not _llm.enabled:
        yield "你好！告诉我你的项目想法，我来帮你诊断和分析。"
        return

    if state.get("needs_clarification"):
        yield _build_clarification_reply(state)
        return

    if not analyses_ctx:
        # ── Focused intent path (no agents ran) ──
        gathered = _build_gathered_context(state)
        focused_prompt = _FOCUSED_PROMPTS.get(intent, "")
        if intent == "learning_concept":
            reply, _ = _build_learning_tutor_reply(state, structured=True)
            yield reply
            return
        if focused_prompt and gathered:
            _sys = (
                f"{persona}\n{focused_prompt}\n\n"
                "## 通用要求\n"
                "- 第一人称回复，像导师面对面聊天\n"
                "- 不要提到任何系统内部结构（Agent、模块等）\n"
                "- 排版清晰：## 标题、> 引用、**加粗**、表格\n"
                "- 紧扣学生的实际项目和上下文\n"
            )
            _usr = (
                f"学生说：{msg[:2000]}\n\n"
                + (f"对话上下文：\n{conv_ctx}\n\n" if conv_ctx else "")
                + f"已收集的信息：\n{gathered}\n"
            )
            for chunk in _llm.chat_text_stream(
                system_prompt=_sys, user_prompt=_usr,
                model=settings.llm_reason_model, temperature=0.5,
            ):
                yield chunk
            return
        else:
            diag = state.get("diagnosis", {})
            bn = str(diag.get("bottleneck") or "")
            yield bn if bn else "你好！告诉我你的项目想法，我来帮你诊断和分析。"
            return

    # ── Multi-agent synthesis path ──
    system_prompt = (
        f"{persona}\n"
        "你已经从多个专业角度对学生的问题进行了深入分析，"
        "现在需要将这些分析整合成一份自然、连贯、有深度的回复。\n\n"
        "## 绝对禁止\n"
        "- 不要提到任何Agent、分析师等角色名称\n"
        "- 不要说'根据多维度分析'等套话\n"
        "- **严禁万金油建议**：不许动不动就建议'做用户访谈''发放问卷''做市场调研'。"
        "  如果确实需要调研，必须说清楚：调研什么假设、找什么人、问什么问题。\n\n"
        "## 回复逻辑结构\n"
        "1. 总览定位（1-2句话概括整体判断）\n"
        "2. 宏观框架梳理（用户→痛点→方案→变现逻辑链）\n"
        "3. 逐项展开所有重要问题或子问题，不要只选前两点\n"
        "4. 具体行动建议\n"
        "5. 引导性追问\n"
        "6. 如果有联网资料，补充来源链接\n\n"
        "## 必须做到\n"
        "- 以第一人称'我'回复\n"
        "- 紧扣学生具体内容，引用原话\n"
        "- 排版美观：## ### 标题、表格、> 引用块、**加粗**\n"
        f"- 回复长度: {length_guide}\n"
    )

    user_prompt = (
        f"学生说：\n{msg[:3000]}\n\n"
        + (f"对话上下文：\n{conv_ctx}\n\n" if conv_ctx else "")
        + (f"教师批注: {tfb}\n\n" if tfb else "")
        + (f"历史: {hist[:300]}\n\n" if hist else "")
        + f"以下是已完成的深入分析结果，请整合为自然的回复：\n\n{analyses_ctx}"
    )

    for chunk in _llm.chat_text_stream(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=settings.llm_reason_model,
        temperature=0.55,
    ):
        yield chunk
