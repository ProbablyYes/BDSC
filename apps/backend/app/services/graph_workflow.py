"""
LangGraph-based multi-agent workflow for VentureAgent.

Uses StateGraph to orchestrate: intent classification → rule diagnosis →
KG entity extraction → critic / competition / learning → composer.
Each node is a self-contained agent that reads shared state and writes results.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph

from app.config import settings
from app.services.llm_client import LlmClient

_llm = LlmClient()

# ═══════════════════════════════════════════════════════════════════
#  Workflow State
# ═══════════════════════════════════════════════════════════════════

class WorkflowState(TypedDict, total=False):
    # ── inputs (set once by caller) ──
    message: str
    mode: str
    project_state: dict
    history_context: str
    conversation_messages: list
    teacher_feedback_context: str

    # ── intent (set by intent node) ──
    intent: str
    intent_confidence: float
    intent_pipeline: list[str]
    intent_engine: str
    intent_keywords: list[str]

    # ── intermediate agent results ──
    category: str
    diagnosis: dict
    next_task: dict
    references: list
    kg_analysis: dict
    critic: dict
    competition: dict
    learning: dict

    # ── output ──
    assistant_message: str
    nodes_visited: Annotated[list[str], operator.add]


# ═══════════════════════════════════════════════════════════════════
#  Intent definitions
# ═══════════════════════════════════════════════════════════════════

INTENTS: dict[str, dict] = {
    "idea_brainstorm": {
        "keywords": ["点子", "想法", "灵感", "方向", "做什么好", "有什么好",
                      "不知道做什么", "创业方向", "还没想好"],
        "pipeline": ["diagnosis", "kg_extract", "composer"],
    },
    "project_diagnosis": {
        "keywords": ["我想做", "我的项目", "产品是", "我们做的", "分析一下",
                      "怎么样", "可行吗", "痛点", "商业计划", "帮我看看"],
        "pipeline": ["diagnosis", "kg_extract", "critic", "composer"],
    },
    "evidence_check": {
        "keywords": ["访谈", "问卷", "调研", "证据", "用户", "验证",
                      "数据", "样本", "反馈", "需求调研"],
        "pipeline": ["diagnosis", "kg_extract", "composer"],
    },
    "business_model": {
        "keywords": ["商业模式", "盈利", "收入", "成本", "市场规模",
                      "tam", "sam", "som", "cac", "ltv", "定价", "渠道"],
        "pipeline": ["diagnosis", "kg_extract", "critic", "composer"],
    },
    "competition_prep": {
        "keywords": ["路演", "竞赛", "答辩", "比赛", "评委",
                      "ppt", "演讲", "展示", "互联网+", "挑战杯"],
        "pipeline": ["diagnosis", "competition", "critic", "composer"],
    },
    "pressure_test": {
        "keywords": ["压力测试", "挑战", "反驳", "护城河", "巨头",
                      "如果", "竞争对手", "为什么不"],
        "pipeline": ["diagnosis", "critic", "composer"],
    },
    "learning_concept": {
        "keywords": ["什么是", "怎么做", "教我", "学习", "方法", "理论",
                      "概念", "lean canvas", "mvp", "商业画布"],
        "pipeline": ["learning", "composer"],
    },
    "general_chat": {
        "keywords": [],
        "pipeline": ["composer"],
    },
}

INTENT_PROMPTS: dict[str, str] = {
    "idea_brainstorm":   "学生想要创业点子。给出2-3个有针对性的方向，引导深入探索。",
    "project_diagnosis": "学生描述了项目。先肯定亮点，指出关键风险，给出下一步，苏格拉底追问收尾。",
    "evidence_check":    "学生讨论证据/调研。评估充分性，指出缺失证据和具体补证方法。",
    "business_model":    "学生讨论商业模式。分析闭环逻辑，指出漏洞和修正建议。",
    "competition_prep":  "学生准备竞赛/路演。模拟评委视角提问，给答辩技巧和路演结构。",
    "pressure_test":     "学生要求压力测试。扮演'毒舌评委'追问，直击软肋但语气专业。",
    "learning_concept":  "学生想学创业概念。通俗解释概念，举例，给练习任务。",
    "general_chat":      "学生闲聊。热情回应，自然引导到项目话题。",
}


def _classify(message: str) -> dict:
    text = message.lower().strip()
    scores: list[tuple[str, float, list[str]]] = []
    for iid, spec in INTENTS.items():
        kws = spec.get("keywords", [])
        matched = [k for k in kws if k in text]
        score = (len(matched) / max(len(kws), 1) + 0.3) if matched else 0.0
        scores.append((iid, score, matched))
    scores.sort(key=lambda x: x[1], reverse=True)
    best, best_score, best_kws = scores[0]
    if best_score < 0.15:
        if len(text) > 60:
            return {"intent": "project_diagnosis", "confidence": 0.5,
                    "pipeline": list(INTENTS["project_diagnosis"]["pipeline"]),
                    "keywords": [], "engine": "rule-fallback"}
        return {"intent": "general_chat", "confidence": 0.4,
                "pipeline": list(INTENTS["general_chat"]["pipeline"]),
                "keywords": [], "engine": "rule-fallback"}
    return {"intent": best, "confidence": min(1.0, best_score),
            "pipeline": list(INTENTS[best]["pipeline"]),
            "keywords": best_kws, "engine": "rule"}


# ═══════════════════════════════════════════════════════════════════
#  Node implementations
# ═══════════════════════════════════════════════════════════════════

def intent_node(state: WorkflowState) -> dict:
    c = _classify(state.get("message", ""))
    return {
        "intent": c["intent"],
        "intent_confidence": c["confidence"],
        "intent_pipeline": c["pipeline"],
        "intent_engine": c["engine"],
        "intent_keywords": c["keywords"],
        "nodes_visited": ["intent"],
    }


def diagnosis_node(state: WorkflowState) -> dict:
    from app.services.case_knowledge import infer_category, retrieve_cases_by_category
    from app.services.diagnosis_engine import run_diagnosis

    msg = state.get("message", "")
    mode = state.get("mode", "coursework")
    diag = run_diagnosis(input_text=msg, mode=mode)
    cat = infer_category(msg)
    refs = retrieve_cases_by_category(cat, limit=2)
    return {
        "diagnosis": diag.diagnosis,
        "next_task": diag.next_task,
        "category": cat,
        "references": refs,
        "nodes_visited": ["diagnosis"],
    }


def kg_extract_node(state: WorkflowState) -> dict:
    """Use LLM to extract entities & relationships → structural gap analysis."""
    msg = state.get("message", "")
    kg: dict[str, Any] = {}

    if _llm.enabled and len(msg) > 15:
        kg = _llm.chat_json(
            system_prompt=(
                "你是知识图谱分析专家。从学生的创业项目描述中提取关键实体和关系。\n"
                "输出严格JSON:\n"
                "{\n"
                '  "entities": [\n'
                '    {"id":"e1","label":"名称","type":"stakeholder|product|market|technology|pain_point|solution|competitor|resource"}\n'
                "  ],\n"
                '  "relationships": [\n'
                '    {"source":"e1","target":"e2","relation":"关系描述"}\n'
                "  ],\n"
                '  "structural_gaps": ["缺少XX类型实体","XX和XX之间缺少关联"],\n'
                '  "completeness_score": 6,\n'
                '  "insight": "一句话总结图谱结构完整性"\n'
                "}"
            ),
            user_prompt=f"项目描述：{msg[:2000]}",
            temperature=0.15,
        )

    if not kg or not kg.get("entities"):
        kg = {
            "entities": [],
            "relationships": [],
            "structural_gaps": ["文本过短或过于模糊，无法提取有效实体"],
            "completeness_score": 0,
            "insight": "请提供更详细的项目描述以获得图谱分析",
        }
    return {"kg_analysis": kg, "nodes_visited": ["kg_extract"]}


def critic_node(state: WorkflowState) -> dict:
    msg = state.get("message", "")
    diag = state.get("diagnosis", {})
    bottleneck = diag.get("bottleneck", "")
    rules = diag.get("triggered_rules", [])

    data: dict[str, Any] = {}
    if _llm.enabled:
        data = _llm.chat_json(
            system_prompt=(
                "你是Critic Agent（压力测试官）。对创业项目做反事实挑战。\n"
                "输出严格JSON:\n"
                '{"challenge_questions":["苏格拉底式追问1","追问2","追问3"],'
                '"missing_evidence":["缺失证据1","缺失证据2"],'
                '"risk_summary":"一句话风险总结",'
                '"counterfactual":"如果XX假设不成立，项目会怎样"}'
            ),
            user_prompt=f"学生说:{msg[:800]}\n瓶颈:{bottleneck}\n规则:{rules[:5]}",
            temperature=0.25,
        )
    if not data:
        data = {
            "challenge_questions": ["如果用户不花钱也能解决，你的产品意义在哪？"],
            "missing_evidence": [],
            "risk_summary": bottleneck or "需要更多信息",
            "counterfactual": "",
        }
    return {"critic": data, "nodes_visited": ["critic"]}


def competition_node(state: WorkflowState) -> dict:
    msg = state.get("message", "")
    mode = state.get("mode", "coursework")

    data: dict[str, Any] = {}
    if _llm.enabled:
        data = _llm.chat_json(
            system_prompt=(
                "你是竞赛评审顾问。输出严格JSON:\n"
                '{"judge_questions":["评委尖锐问题1","问题2","问题3"],'
                '"defense_tips":["答辩技巧1","技巧2","技巧3"],'
                '"presentation_structure":["路演环节1","环节2","环节3","环节4"],'
                '"prize_readiness":50}'
            ),
            user_prompt=f"项目描述:{msg[:800]}\n模式:{mode}",
            temperature=0.25,
        )
    return {"competition": data or {}, "nodes_visited": ["competition"]}


def learning_node(state: WorkflowState) -> dict:
    msg = state.get("message", "")
    data: dict[str, Any] = {}
    if _llm.enabled:
        data = _llm.chat_json(
            system_prompt=(
                "你是创新创业课程导师。输出严格JSON:\n"
                '{"definition":"概念解释","example":"具体例子",'
                '"practice_task":"一个可执行练习","common_mistakes":["错误1","错误2"],'
                '"recommended_reading":"推荐阅读资源"}'
            ),
            user_prompt=f"学生问:{msg[:800]}",
            temperature=0.3,
        )
    return {"learning": data or {}, "nodes_visited": ["learning"]}


def composer_node(state: WorkflowState) -> dict:
    """Generate final Markdown-formatted response from all agent results."""
    msg = state.get("message", "")
    intent = state.get("intent", "general_chat")
    diag = state.get("diagnosis", {})
    ntask = state.get("next_task", {})
    kg = state.get("kg_analysis", {})
    critic = state.get("critic", {})
    comp = state.get("competition", {})
    learn = state.get("learning", {})
    hist = state.get("history_context", "")
    tfb = state.get("teacher_feedback_context", "")
    conv_msgs = state.get("conversation_messages", [])

    parts: list[str] = []
    if diag:
        rules = diag.get("triggered_rules", []) or []
        rtxt = "；".join(
            f"{r.get('id')}:{r.get('name')}"
            for r in rules[:5] if isinstance(r, dict)
        ) or "暂无"
        parts.append(
            f"## 规则诊断\n瓶颈: {diag.get('bottleneck','')}\n"
            f"触发风险: {rtxt}\n综合评分: {diag.get('overall_score',0)}/10"
        )
    if ntask:
        parts.append(
            f"## 下一步任务\n标题: {ntask.get('title','')}\n"
            f"描述: {ntask.get('description','')}\n"
            f"验收标准: {ntask.get('acceptance_criteria',[])}"
        )
    if kg and kg.get("entities"):
        gaps = kg.get("structural_gaps", [])
        parts.append(
            f"## 知识图谱分析\n实体数: {len(kg['entities'])}\n"
            f"关系数: {len(kg.get('relationships', []))}\n"
            f"结构缺陷: {gaps}\n图谱洞察: {kg.get('insight','')}"
        )
    if critic:
        parts.append(
            f"## Critic压力追问\n{critic.get('challenge_questions',[])}\n"
            f"缺失证据: {critic.get('missing_evidence',[])}"
        )
    if comp:
        parts.append(
            f"## 竞赛顾问\n评委问题: {comp.get('judge_questions',[])}\n"
            f"答辩技巧: {comp.get('defense_tips',[])}"
        )
    if learn:
        parts.append(
            f"## 学习导师\n定义: {learn.get('definition','')}\n"
            f"练习: {learn.get('practice_task','')}"
        )
    if hist:
        parts.append(f"## 对话历史\n{hist}")
    if tfb:
        parts.append(f"## 教师批注\n{tfb}")

    ctx = "\n\n".join(parts)

    conv_ctx = ""
    if conv_msgs:
        recent = conv_msgs[-8:]
        conv_ctx = "\n".join(
            f"{'学生' if m.get('role')=='user' else '教练'}: "
            f"{str(m.get('content',''))[:200]}"
            for m in recent
        )

    ip = INTENT_PROMPTS.get(intent, INTENT_PROMPTS["general_chat"])

    reply = ""
    if _llm.enabled:
        reply = _llm.chat_text(
            system_prompt=(
                "你是一位经验丰富、温和但严格的双创项目教练（创新创业导师）。\n"
                f"当前对话意图：{intent}。{ip}\n\n"
                "## 格式规范（Markdown）\n"
                "- 使用 **加粗** 突出关键概念和风险名称\n"
                "- 用 ### 小标题 分隔不同话题段落\n"
                "- 要点多于3个时使用有序/无序列表\n"
                "- 涉及对比或数据时用表格\n"
                "- 重要警告或风险用 > 引用块\n"
                "- 代码或专业术语用 `行内代码`\n\n"
                "## 内容要求\n"
                "1. 先简要回应学生的话，体现认真倾听\n"
                "2. 语气像资深导师聊天，亲切专业\n"
                "3. 如果有知识图谱分析结果，提及结构性缺陷\n"
                "4. 用苏格拉底式追问收尾\n"
                "5. 控制在200-600字\n"
            ),
            user_prompt=(
                f"学生说：{msg}\n\n"
                + (f"近期对话：\n{conv_ctx}\n\n" if conv_ctx else "")
                + f"多智能体分析上下文：\n{ctx}"
            ),
            model=settings.llm_reason_model,
            temperature=0.4,
        )

    if not reply or len(reply.strip()) < 20:
        bn = str(diag.get("bottleneck") or "")
        tt = str(ntask.get("title") or "")
        reply = (
            f"**{bn}**\n\n> 下一步：{tt}" if bn
            else "你好！告诉我你的项目想法，我来帮你诊断和分析。"
        )

    return {"assistant_message": reply.strip(), "nodes_visited": ["composer"]}


# ═══════════════════════════════════════════════════════════════════
#  Conditional routing
# ═══════════════════════════════════════════════════════════════════

def _route_from_intent(state: WorkflowState) -> str:
    pl = state.get("intent_pipeline", [])
    if "diagnosis" in pl:
        return "diagnosis"
    if "learning" in pl:
        return "learning"
    return "composer"


def _route_after_diagnosis(state: WorkflowState) -> str:
    pl = state.get("intent_pipeline", [])
    if "kg_extract" in pl:
        return "kg_extract"
    if "critic" in pl:
        return "critic"
    if "competition" in pl:
        return "competition"
    return "composer"


def _route_after_kg(state: WorkflowState) -> str:
    pl = state.get("intent_pipeline", [])
    if "critic" in pl:
        return "critic"
    if "competition" in pl:
        return "competition"
    return "composer"


def _route_after_critic(state: WorkflowState) -> str:
    pl = state.get("intent_pipeline", [])
    if "competition" in pl:
        return "competition"
    return "composer"


# ═══════════════════════════════════════════════════════════════════
#  Build & compile graph
# ═══════════════════════════════════════════════════════════════════

def _build() -> Any:
    g = StateGraph(WorkflowState)

    g.add_node("intent",      intent_node)
    g.add_node("diagnosis",   diagnosis_node)
    g.add_node("kg_extract",  kg_extract_node)
    g.add_node("critic",      critic_node)
    g.add_node("competition", competition_node)
    g.add_node("learning",    learning_node)
    g.add_node("composer",    composer_node)

    g.set_entry_point("intent")

    g.add_conditional_edges("intent", _route_from_intent, {
        "diagnosis": "diagnosis",
        "learning":  "learning",
        "composer":  "composer",
    })
    g.add_conditional_edges("diagnosis", _route_after_diagnosis, {
        "kg_extract":  "kg_extract",
        "critic":      "critic",
        "competition": "competition",
        "composer":    "composer",
    })
    g.add_conditional_edges("kg_extract", _route_after_kg, {
        "critic":      "critic",
        "competition": "competition",
        "composer":    "composer",
    })
    g.add_conditional_edges("critic", _route_after_critic, {
        "competition": "competition",
        "composer":    "composer",
    })
    g.add_edge("competition", "composer")
    g.add_edge("learning",    "composer")
    g.add_edge("composer",    END)

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
    """Execute the full LangGraph agent workflow and return final state."""
    initial: WorkflowState = {
        "message": message,
        "mode": mode,
        "project_state": project_state or {},
        "history_context": history_context,
        "conversation_messages": conversation_messages or [],
        "teacher_feedback_context": teacher_feedback_context,
    }
    return workflow.invoke(initial)
