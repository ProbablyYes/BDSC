"""
LangGraph-based multi-agent workflow for VentureAgent (V2).

Key upgrades over V1:
- RAG: retrieves real case content from 89 structured case JSONs
- KG: reads/writes Neo4j entities, compares student graph with reference
- Hypergraph: risk pattern matching integrated into critic reasoning
- Challenge strategies: structured Socratic probing from strategy library
- LLM-enhanced intent classification when keyword matching is ambiguous
- Diagnosis LLM augmentation on top of rule engine baseline
"""

from __future__ import annotations

import logging
import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph

from app.config import settings
from app.services.llm_client import LlmClient

logger = logging.getLogger(__name__)
_llm = LlmClient()

_rag = None
_graph_service = None
_hypergraph_service = None


def init_workflow_services(rag_engine=None, graph_service=None, hypergraph_service=None):
    """Called once at app startup to inject shared service instances."""
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
    intent_pipeline: list[str]
    intent_engine: str
    intent_keywords: list[str]

    category: str
    diagnosis: dict
    next_task: dict
    references: list
    rag_context: str
    rag_cases: list
    kg_analysis: dict
    kg_neo4j_context: str
    hypergraph_insight: dict
    challenge_strategies: list
    critic: dict
    competition: dict
    learning: dict

    assistant_message: str
    nodes_visited: Annotated[list[str], operator.add]


# ═══════════════════════════════════════════════════════════════════
#  Intent definitions & classification
# ═══════════════════════════════════════════════════════════════════

INTENTS: dict[str, dict] = {
    "idea_brainstorm": {
        "keywords": ["点子", "想法", "灵感", "方向", "做什么好", "有什么好",
                      "不知道做什么", "创业方向", "还没想好"],
        "desc": "学生想要创业点子/方向建议",
        "pipeline": ["diagnosis", "rag_retrieve", "kg_extract", "composer"],
    },
    "project_diagnosis": {
        "keywords": ["我想做", "我的项目", "产品是", "我们做的", "分析一下",
                      "怎么样", "可行吗", "痛点", "商业计划", "帮我看看"],
        "desc": "学生描述项目并希望获得诊断",
        "pipeline": ["diagnosis", "rag_retrieve", "kg_extract", "hypergraph", "critic", "composer"],
    },
    "evidence_check": {
        "keywords": ["访谈", "问卷", "调研", "证据", "用户", "验证",
                      "数据", "样本", "反馈", "需求调研"],
        "desc": "学生讨论证据/调研",
        "pipeline": ["diagnosis", "rag_retrieve", "kg_extract", "composer"],
    },
    "business_model": {
        "keywords": ["商业模式", "盈利", "收入", "成本", "市场规模",
                      "tam", "sam", "som", "cac", "ltv", "定价", "渠道"],
        "desc": "学生讨论商业模式",
        "pipeline": ["diagnosis", "rag_retrieve", "kg_extract", "hypergraph", "critic", "composer"],
    },
    "competition_prep": {
        "keywords": ["路演", "竞赛", "答辩", "比赛", "评委",
                      "ppt", "演讲", "展示", "互联网+", "挑战杯"],
        "desc": "学生准备竞赛/路演",
        "pipeline": ["diagnosis", "rag_retrieve", "competition", "critic", "composer"],
    },
    "pressure_test": {
        "keywords": ["压力测试", "挑战", "反驳", "护城河", "巨头",
                      "如果", "竞争对手", "为什么不"],
        "desc": "学生要求压力测试",
        "pipeline": ["diagnosis", "hypergraph", "critic", "composer"],
    },
    "learning_concept": {
        "keywords": ["什么是", "怎么做", "教我", "学习", "方法", "理论",
                      "概念", "lean canvas", "mvp", "商业画布"],
        "desc": "学生想学创业概念/方法论",
        "pipeline": ["learning", "composer"],
    },
    "general_chat": {
        "keywords": [],
        "desc": "闲聊/问好",
        "pipeline": ["composer"],
    },
}

INTENT_PROMPTS: dict[str, str] = {
    "idea_brainstorm":   "学生想要创业点子。结合RAG案例给出2-3个有针对性的方向，引导深入探索。",
    "project_diagnosis": "学生描述了项目。基于诊断+RAG案例对比+KG分析，先肯定亮点，指出关键风险，给出下一步，苏格拉底追问收尾。",
    "evidence_check":    "学生讨论证据/调研。基于RAG中优秀案例的证据标准，评估充分性，指出缺失和补证方法。",
    "business_model":    "学生讨论商业模式。结合RAG参考案例的商业模式，分析闭环逻辑，指出漏洞和修正建议。",
    "competition_prep":  "学生准备竞赛/路演。结合RAG中获奖案例，模拟评委视角提问，给答辩技巧和路演结构。",
    "pressure_test":     "学生要求压力测试。使用追问策略库的结构化追问，直击软肋但语气专业。",
    "learning_concept":  "学生想学创业概念。通俗解释，举RAG案例中的实际例子，给练习任务。",
    "general_chat":      "学生闲聊。热情回应，自然引导到项目话题。",
}


def _classify_rule(message: str) -> dict:
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


def _classify_with_llm(message: str) -> dict | None:
    """LLM-enhanced intent classification for ambiguous cases."""
    if not _llm.enabled:
        return None
    intent_list = "\n".join(f"- {k}: {v['desc']}" for k, v in INTENTS.items())
    result = _llm.chat_json(
        system_prompt=(
            "你是意图分类器。根据学生消息，从以下意图中选择最匹配的一个。\n"
            f"可选意图:\n{intent_list}\n\n"
            '输出严格JSON: {"intent": "意图ID", "confidence": 0.0-1.0, "reason": "一句话理由"}'
        ),
        user_prompt=f"学生消息: {message[:500]}",
        temperature=0.05,
    )
    if result and result.get("intent") in INTENTS:
        return {
            "intent": result["intent"],
            "confidence": float(result.get("confidence", 0.8)),
            "pipeline": list(INTENTS[result["intent"]]["pipeline"]),
            "keywords": [],
            "engine": "llm",
        }
    return None


# ═══════════════════════════════════════════════════════════════════
#  Node implementations
# ═══════════════════════════════════════════════════════════════════

def intent_node(state: WorkflowState) -> dict:
    msg = state.get("message", "")
    c = _classify_rule(msg)
    if c["confidence"] < 0.5 and c["engine"] == "rule-fallback":
        llm_result = _classify_with_llm(msg)
        if llm_result and llm_result["confidence"] > c["confidence"]:
            c = llm_result
    return {
        "intent": c["intent"],
        "intent_confidence": c["confidence"],
        "intent_pipeline": c["pipeline"],
        "intent_engine": c["engine"],
        "intent_keywords": c.get("keywords", []),
        "nodes_visited": ["intent"],
    }


def diagnosis_node(state: WorkflowState) -> dict:
    from app.services.case_knowledge import infer_category, retrieve_cases_by_category
    from app.services.diagnosis_engine import run_diagnosis

    msg = state.get("message", "")
    mode = state.get("mode", "coursework")
    diag = run_diagnosis(input_text=msg, mode=mode)
    cat = infer_category(msg)
    refs = retrieve_cases_by_category(cat, limit=3)

    diag_enhanced = diag.diagnosis
    is_file = "[上传文件:" in msg
    if _llm.enabled and (is_file or len(msg) > 100):
        llm_diag = _llm.chat_json(
            system_prompt=(
                "你是创业项目诊断专家。基于规则引擎的初步诊断结果，做更深入的语义分析。\n"
                "输出严格JSON:\n"
                '{"deep_bottleneck": "最核心的一个问题是什么（一句话）",'
                '"evidence_gaps": ["具体缺少什么证据1", "证据2"],'
                '"strength": "项目最大的亮点（如果有的话）",'
                '"stage": "idea|validation|growth|scaling"}'
            ),
            user_prompt=f"规则诊断: {diag.diagnosis.get('bottleneck','')}\n触发规则: {[r.get('name') for r in diag.diagnosis.get('triggered_rules',[])]}\n学生内容: {msg[:1500]}",
            temperature=0.15,
        )
        if llm_diag:
            diag_enhanced = {**diag.diagnosis, "llm_enhancement": llm_diag}

    return {
        "diagnosis": diag_enhanced,
        "next_task": diag.next_task,
        "category": cat,
        "references": refs,
        "nodes_visited": ["diagnosis"],
    }


def rag_retrieve_node(state: WorkflowState) -> dict:
    """Retrieve relevant cases from the knowledge base using RAG."""
    msg = state.get("message", "")
    cat = state.get("category", "")
    rag_context = ""
    rag_cases: list[dict] = []

    if _rag and _rag.case_count > 0:
        rag_cases = _rag.retrieve(msg[:1000], top_k=3, category_filter=cat if cat else None)
        rag_context = _rag.format_for_llm(rag_cases)

    return {
        "rag_context": rag_context,
        "rag_cases": rag_cases,
        "nodes_visited": ["rag_retrieve"],
    }


def kg_extract_node(state: WorkflowState) -> dict:
    """Extract entities via LLM, write to Neo4j, read related entities for comparison."""
    msg = state.get("message", "")
    rag_ctx = state.get("rag_context", "")
    kg: dict[str, Any] = {}
    neo4j_ctx = ""
    is_file = "[上传文件:" in msg

    if _llm.enabled and len(msg) > 15:
        ref_block = ""
        if rag_ctx:
            ref_block = f"\n\n## 参考案例（来自知识库RAG检索）\n{rag_ctx[:600]}\n请对比学生内容与参考案例的差距。"

        kg = _llm.chat_json(
            system_prompt=(
                "你是创业项目分析专家，擅长从文本中提取结构化知识图谱。\n"
                + ("这是学生上传的文件，请逐段深入分析。\n" if is_file else "")
                + "输出严格JSON:\n"
                "{\n"
                '  "entities": [{"id":"e1","label":"实体名","type":"stakeholder|product|market|technology|pain_point|solution|competitor|resource"}],\n'
                '  "relationships": [{"source":"e1","target":"e2","relation":"关系描述"}],\n'
                '  "structural_gaps": ["具体缺少什么"],\n'
                '  "content_strengths": ["做得好的地方"],\n'
                '  "completeness_score": 6,\n'
                '  "section_scores": {"problem_definition":0,"user_evidence":0,"solution_feasibility":0,"business_model":0,"competitive_advantage":0},\n'
                '  "insight": "2-3句总结"\n'
                "}"
                + ref_block
            ),
            user_prompt=f"项目内容：\n{msg[:4000]}",
            model=settings.llm_reason_model if is_file else None,
            temperature=0.15,
        )

    if not kg or not kg.get("entities"):
        kg = {
            "entities": [], "relationships": [],
            "structural_gaps": ["文本过短，无法提取有效实体"],
            "content_strengths": [], "completeness_score": 0,
            "section_scores": {}, "insight": "请提供更详细的项目描述",
        }

    if _graph_service and kg.get("entities"):
        project_id = state.get("project_state", {}).get("project_id", "unknown")
        _graph_service.merge_student_entities(project_id, kg["entities"], kg.get("relationships", []))

        top_labels = [e["label"] for e in kg["entities"][:5] if e.get("label")]
        related = _graph_service.find_similar_entities(top_labels, limit=5)
        if related:
            neo4j_ctx = "图谱关联发现：" + "; ".join(
                f"{r.get('entity','')}({r.get('type','')}) → {r.get('related_entity','')}"
                for r in related[:5] if r.get("entity")
            )

    return {"kg_analysis": kg, "kg_neo4j_context": neo4j_ctx, "nodes_visited": ["kg_extract"]}


def hypergraph_node(state: WorkflowState) -> dict:
    """Query hypergraph for risk pattern matching."""
    cat = state.get("category", "")
    diag = state.get("diagnosis", {})
    rule_ids = [str(r.get("id")) for r in (diag.get("triggered_rules", []) or []) if isinstance(r, dict)]

    insight: dict[str, Any] = {}
    if _hypergraph_service:
        insight = _hypergraph_service.insight(category=cat, rule_ids=rule_ids, limit=3)

    return {"hypergraph_insight": insight, "nodes_visited": ["hypergraph"]}


def critic_node(state: WorkflowState) -> dict:
    from app.services.challenge_strategies import format_for_critic, match_strategies

    msg = state.get("message", "")
    diag = state.get("diagnosis", {})
    bottleneck = diag.get("bottleneck", "")
    llm_enh = diag.get("llm_enhancement", {})
    rules = diag.get("triggered_rules", [])
    hyper = state.get("hypergraph_insight", {})
    rag_ctx = state.get("rag_context", "")

    rule_ids = [r.get("id", "") for r in rules if isinstance(r, dict)]
    strategies = match_strategies(msg, rule_ids, max_results=2)
    strategy_ctx = format_for_critic(strategies)

    hyper_edges = (hyper or {}).get("edges", []) or []
    hyper_note = "; ".join(e.get("teaching_note", "") for e in hyper_edges[:2]) if hyper_edges else ""

    data: dict[str, Any] = {}
    if _llm.enabled:
        data = _llm.chat_json(
            system_prompt=(
                "你是Critic Agent（压力测试官）。你的任务是对创业项目做深度反事实挑战。\n\n"
                "你有以下信息来源：\n"
                + (f"追问策略库:\n{strategy_ctx}\n\n" if strategy_ctx else "")
                + (f"超图风险模式: {hyper_note}\n\n" if hyper_note else "")
                + (f"LLM深度诊断: {llm_enh.get('deep_bottleneck','')} | 证据缺口: {llm_enh.get('evidence_gaps',[])}\n\n" if llm_enh else "")
                + (f"参考案例对比:\n{rag_ctx[:400]}\n\n" if rag_ctx else "")
                + "输出严格JSON:\n"
                '{"challenge_questions":["基于策略库的精准追问1","追问2","追问3"],'
                '"missing_evidence":["缺失证据1","缺失证据2"],'
                '"risk_summary":"一句话风险总结",'
                '"counterfactual":"如果XX假设不成立，项目会怎样",'
                '"evidence_standard":"优秀项目在这个维度通常提供什么证据"}'
            ),
            user_prompt=f"学生说:{msg[:800]}\n瓶颈:{bottleneck}\n触发规则:{rule_ids}",
            temperature=0.25,
        )
    if not data:
        cf = strategies[0]["counterfactual"] if strategies else "需要更多信息来做压力测试"
        data = {
            "challenge_questions": [s["probing_layers"][0] for s in strategies[:3]] if strategies
                else ["如果用户不花钱也能解决，你的产品意义在哪？"],
            "missing_evidence": llm_enh.get("evidence_gaps", []) if llm_enh else [],
            "risk_summary": bottleneck or "需要更多信息",
            "counterfactual": cf,
            "evidence_standard": "",
        }
    return {"critic": data, "challenge_strategies": strategies, "nodes_visited": ["critic"]}


def competition_node(state: WorkflowState) -> dict:
    msg = state.get("message", "")
    mode = state.get("mode", "coursework")
    rag_ctx = state.get("rag_context", "")

    data: dict[str, Any] = {}
    if _llm.enabled:
        data = _llm.chat_json(
            system_prompt=(
                "你是竞赛评审顾问，拥有丰富的互联网+/挑战杯评审经验。\n"
                + (f"参考获奖案例:\n{rag_ctx[:500]}\n\n" if rag_ctx else "")
                + '输出严格JSON:\n'
                '{"judge_questions":["评委尖锐问题1","问题2","问题3"],'
                '"defense_tips":["答辩技巧1","技巧2","技巧3"],'
                '"presentation_structure":["路演环节1","环节2","环节3","环节4"],'
                '"prize_readiness":50,'
                '"key_improvement":"最关键的一个提升点"}'
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
                '{"definition":"概念解释","example":"具体真实例子",'
                '"practice_task":"一个可执行练习","common_mistakes":["错误1","错误2"],'
                '"recommended_reading":"推荐阅读资源"}'
            ),
            user_prompt=f"学生问:{msg[:800]}",
            temperature=0.3,
        )
    return {"learning": data or {}, "nodes_visited": ["learning"]}


def composer_node(state: WorkflowState) -> dict:
    """Generate response with full knowledge context: RAG + KG + Hypergraph + Strategies."""
    msg = state.get("message", "")
    intent = state.get("intent", "general_chat")
    diag = state.get("diagnosis", {})
    ntask = state.get("next_task", {})
    kg = state.get("kg_analysis", {})
    neo4j_ctx = state.get("kg_neo4j_context", "")
    rag_ctx = state.get("rag_context", "")
    rag_cases = state.get("rag_cases", [])
    hyper = state.get("hypergraph_insight", {})
    critic = state.get("critic", {})
    strategies = state.get("challenge_strategies", [])
    comp = state.get("competition", {})
    learn = state.get("learning", {})
    hist = state.get("history_context", "")
    tfb = state.get("teacher_feedback_context", "")
    conv_msgs = state.get("conversation_messages", [])

    is_file = "[上传文件:" in msg

    ctx_parts: list[str] = []

    if rag_ctx:
        ctx_parts.append(f"## 知识库参考案例（RAG检索）\n{rag_ctx}")

    if diag:
        rules = diag.get("triggered_rules", []) or []
        rtxt = "、".join(r.get("name", "") for r in rules[:4] if isinstance(r, dict))
        llm_enh = diag.get("llm_enhancement", {})
        diag_text = f"诊断瓶颈: {diag.get('bottleneck','')}\n风险: {rtxt}\n评分: {diag.get('overall_score',0)}/10"
        if llm_enh:
            diag_text += f"\n深度分析: {llm_enh.get('deep_bottleneck','')}\n项目亮点: {llm_enh.get('strength','')}\n阶段: {llm_enh.get('stage','')}"
        ctx_parts.append(diag_text)

    if ntask:
        ctx_parts.append(f"建议任务: {ntask.get('title','')} — {ntask.get('description','')}")

    if kg:
        strengths = kg.get("content_strengths", [])
        gaps = kg.get("structural_gaps", [])
        sec = kg.get("section_scores", {})
        sec_text = " | ".join(f"{k}:{v}" for k, v in sec.items()) if sec else ""
        kg_text = f"图谱洞察: {kg.get('insight','')}\n优势: {strengths}\n缺陷: {gaps}"
        if sec_text:
            kg_text += f"\n各维度: {sec_text}"
        if neo4j_ctx:
            kg_text += f"\n{neo4j_ctx}"
        ctx_parts.append(kg_text)

    hyper_edges = (hyper or {}).get("edges", []) or []
    if hyper_edges:
        hyper_notes = [e.get("teaching_note", "") for e in hyper_edges[:2] if e.get("teaching_note")]
        if hyper_notes:
            ctx_parts.append(f"超图风险模式: {'; '.join(hyper_notes)}")

    if critic:
        ctx_parts.append(f"压力追问: {critic.get('challenge_questions',[][:2])}\n缺失证据: {critic.get('missing_evidence',[])}\n证据标准: {critic.get('evidence_standard','')}")

    if comp:
        ctx_parts.append(f"评委问题: {comp.get('judge_questions',[])}\n答辩技巧: {comp.get('defense_tips',[])}")
    if learn:
        ctx_parts.append(f"概念: {learn.get('definition','')}\n练习: {learn.get('practice_task','')}")
    if tfb:
        ctx_parts.append(f"教师批注: {tfb}")
    if hist:
        ctx_parts.append(f"历史: {hist[:300]}")

    ctx = "\n---\n".join(ctx_parts)

    conv_ctx = ""
    if conv_msgs:
        recent = conv_msgs[-6:]
        conv_ctx = "\n".join(
            f"{'学生' if m.get('role')=='user' else '教练'}: {str(m.get('content',''))[:150]}"
            for m in recent
        )

    file_instruction = ""
    if is_file:
        file_instruction = (
            "\n\n## 文件分析专项指令\n"
            "学生上传了文件。你必须：\n"
            "- 先概括文件主题和核心观点\n"
            "- 具体引用文件中的段落或数据进行点评\n"
            "- 与RAG检索到的优秀案例做对比，指出差距和学习方向\n"
            "- 给出具体修改建议\n"
        )

    ip = INTENT_PROMPTS.get(intent, INTENT_PROMPTS["general_chat"])

    msg_len = len(msg)
    has_diag = bool(diag and diag.get("bottleneck"))
    has_kg = bool(kg and kg.get("entities"))
    has_rag = bool(rag_cases)
    has_critic_data = bool(critic and critic.get("challenge_questions"))

    if is_file:
        length_guide = "800-1500字。文件分析需详细、引用原文、对比案例。用标题/表格/引用块组织。"
    elif intent == "general_chat" or msg_len < 30:
        length_guide = "80-200字。简短热情。"
    elif intent == "learning_concept":
        length_guide = "300-500字。概念清晰，配真实案例。"
    elif has_critic_data and has_rag:
        length_guide = "500-900字。多维分析，引用参考案例做对比。"
    elif has_diag:
        length_guide = "300-600字。聚焦关键问题深入分析。"
    else:
        length_guide = "200-400字。适度展开。"

    reply = ""
    if _llm.enabled:
        reply = _llm.chat_text(
            system_prompt=(
                "你是一位有10年双创辅导经验的导师，背后有强大的知识库支撑。\n\n"
                f"## 当前场景\n意图: {intent}\n任务: {ip}\n"
                f"{file_instruction}\n"
                "## 回复原则\n"
                "- **引用知识库**：当RAG检索到了参考案例时，要具体引用案例名称和做法，说明'优秀项目通常怎么做'\n"
                "- **内容为王**：回复紧扣学生具体内容，引用原话或数据\n"
                "- **不要套公式**：每次回复结构不同，根据内容自然组织\n"
                "- **深度优于广度**：宁可讲透一个问题\n"
                "- **知识图谱视角**：如果分析发现了结构缺陷，解释为什么这个缺失是致命的\n"
                "- **追问策略**：如果Critic有追问，自然融入回复中\n"
                "- 灵活使用Markdown：简单回复用加粗和列表；复杂分析用标题、表格、引用块、分割线\n"
                f"- **回复长度**: {length_guide}\n"
            ),
            user_prompt=(
                f"学生说：\n{msg[:3000]}\n\n"
                + (f"对话上下文：\n{conv_ctx}\n\n" if conv_ctx else "")
                + f"多智能体分析结果：\n{ctx}"
            ),
            model=settings.llm_reason_model,
            temperature=0.5,
        )

    if not reply or len(reply.strip()) < 20:
        bn = str(diag.get("bottleneck") or "")
        tt = str(ntask.get("title") or "")
        reply = f"**{bn}**\n\n> 下一步：{tt}" if bn else "你好！告诉我你的项目想法，我来帮你诊断和分析。"

    return {"assistant_message": reply.strip(), "nodes_visited": ["composer"]}


# ═══════════════════════════════════════════════════════════════════
#  Conditional routing
# ═══════════════════════════════════════════════════════════════════

def _next_in_pipeline(state: WorkflowState, current: str) -> str:
    """Generic router: find the next step in the pipeline after `current`."""
    pl = state.get("intent_pipeline", [])
    try:
        idx = pl.index(current)
        if idx + 1 < len(pl):
            return pl[idx + 1]
    except ValueError:
        pass
    return "composer"


def _route_from_intent(state: WorkflowState) -> str:
    pl = state.get("intent_pipeline", [])
    if not pl:
        return "composer"
    first = pl[0]
    valid = {"diagnosis", "rag_retrieve", "kg_extract", "hypergraph", "critic", "competition", "learning", "composer"}
    return first if first in valid else "composer"


def _route_after_diagnosis(state: WorkflowState) -> str:
    return _next_in_pipeline(state, "diagnosis")

def _route_after_rag(state: WorkflowState) -> str:
    return _next_in_pipeline(state, "rag_retrieve")

def _route_after_kg(state: WorkflowState) -> str:
    return _next_in_pipeline(state, "kg_extract")

def _route_after_hypergraph(state: WorkflowState) -> str:
    return _next_in_pipeline(state, "hypergraph")

def _route_after_critic(state: WorkflowState) -> str:
    return _next_in_pipeline(state, "critic")

def _route_after_competition(state: WorkflowState) -> str:
    return _next_in_pipeline(state, "competition")


ALL_NODES = {"diagnosis", "rag_retrieve", "kg_extract", "hypergraph", "critic", "competition", "learning", "composer"}

def _build() -> Any:
    g = StateGraph(WorkflowState)

    g.add_node("intent",       intent_node)
    g.add_node("diagnosis",    diagnosis_node)
    g.add_node("rag_retrieve", rag_retrieve_node)
    g.add_node("kg_extract",   kg_extract_node)
    g.add_node("hypergraph",   hypergraph_node)
    g.add_node("critic",       critic_node)
    g.add_node("competition",  competition_node)
    g.add_node("learning",     learning_node)
    g.add_node("composer",     composer_node)

    g.set_entry_point("intent")

    g.add_conditional_edges("intent", _route_from_intent, {n: n for n in ALL_NODES})
    g.add_conditional_edges("diagnosis", _route_after_diagnosis, {n: n for n in ALL_NODES})
    g.add_conditional_edges("rag_retrieve", _route_after_rag, {n: n for n in ALL_NODES})
    g.add_conditional_edges("kg_extract", _route_after_kg, {n: n for n in ALL_NODES})
    g.add_conditional_edges("hypergraph", _route_after_hypergraph, {n: n for n in ALL_NODES})
    g.add_conditional_edges("critic", _route_after_critic, {n: n for n in ALL_NODES})
    g.add_conditional_edges("competition", _route_after_competition, {n: n for n in ALL_NODES})
    g.add_edge("learning", "composer")
    g.add_edge("composer", END)

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
