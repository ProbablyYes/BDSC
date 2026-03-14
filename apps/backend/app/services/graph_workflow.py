"""
LangGraph role-based multi-agent system for VentureAgent (V3).

Architecture: 5 role-based agents + Router + Orchestrator
┌─────────────────────────────────────────────────────┐
│  Router Agent          — intent classification      │
│  ↓ dispatches to one or more:                       │
│  Coach Agent    (项目教练) — diagnosis + KG + RAG   │
│  Analyst Agent  (风险分析) — rules + hypergraph      │
│  Advisor Agent  (竞赛顾问) — competition + critic    │
│  Tutor Agent    (学习导师) — concepts + web search   │
│  Grader Agent   (评分官)   — rubric scoring          │
│  ↓ all results flow to:                             │
│  Orchestrator   — synthesises final Markdown reply  │
└─────────────────────────────────────────────────────┘
Each agent has its own LLM call, persona, and tool access.
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

    # role-agent outputs (each is a self-contained analysis dict)
    coach_output: dict
    analyst_output: dict
    advisor_output: dict
    tutor_output: dict
    grader_output: dict

    # shared data populated by agents
    category: str
    diagnosis: dict
    next_task: dict
    kg_analysis: dict
    rag_cases: list
    rag_context: str
    web_search_result: dict
    hypergraph_insight: dict
    critic: dict
    challenge_strategies: list
    competition: dict
    learning: dict

    assistant_message: str
    agents_called: Annotated[list[str], operator.add]
    nodes_visited: Annotated[list[str], operator.add]


# ═══════════════════════════════════════════════════════════════════
#  Intent → Agent mapping
# ═══════════════════════════════════════════════════════════════════

INTENTS: dict[str, dict] = {
    "idea_brainstorm": {
        "keywords": ["点子", "想法", "灵感", "方向", "做什么好", "有什么好",
                      "不知道做什么", "创业方向", "还没想好"],
        "desc": "学生想要创业点子/方向建议",
        "agents": ["coach", "tutor"],
    },
    "project_diagnosis": {
        "keywords": ["我想做", "我的项目", "产品是", "我们做的", "分析一下",
                      "怎么样", "可行吗", "痛点", "商业计划", "帮我看看"],
        "desc": "学生描述项目并希望获得诊断",
        "agents": ["coach", "analyst", "grader"],
    },
    "evidence_check": {
        "keywords": ["访谈", "问卷", "调研", "证据", "用户", "验证",
                      "数据", "样本", "反馈", "需求调研"],
        "desc": "学生讨论证据/调研",
        "agents": ["coach", "analyst"],
    },
    "business_model": {
        "keywords": ["商业模式", "盈利", "收入", "成本", "市场规模",
                      "tam", "sam", "som", "cac", "ltv", "定价", "渠道"],
        "desc": "学生讨论商业模式",
        "agents": ["coach", "analyst", "tutor"],
    },
    "competition_prep": {
        "keywords": ["路演", "竞赛", "答辩", "比赛", "评委",
                      "ppt", "演讲", "展示", "互联网+", "挑战杯"],
        "desc": "学生准备竞赛/路演",
        "agents": ["advisor", "analyst"],
    },
    "pressure_test": {
        "keywords": ["压力测试", "挑战", "反驳", "护城河", "巨头",
                      "如果", "竞争对手", "为什么不"],
        "desc": "学生要求压力测试",
        "agents": ["analyst", "advisor"],
    },
    "learning_concept": {
        "keywords": ["什么是", "怎么做", "教我", "学习", "方法", "理论",
                      "概念", "lean canvas", "mvp", "商业画布"],
        "desc": "学生想学创业概念/方法论",
        "agents": ["tutor"],
    },
    "general_chat": {
        "keywords": [],
        "desc": "闲聊/问好",
        "agents": [],
    },
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
            best = "project_diagnosis"
            best_score = 0.5
        else:
            best = "general_chat"
            best_score = 0.4
    engine = "rule"
    if best_score < 0.5 and _llm.enabled:
        intent_list = "\n".join(f"- {k}: {v['desc']}" for k, v in INTENTS.items())
        llm_r = _llm.chat_json(
            system_prompt=f"意图分类器。选一个最匹配的意图。\n{intent_list}\n输出JSON: {{\"intent\":\"ID\",\"confidence\":0.0-1.0}}",
            user_prompt=f"学生: {message[:500]}",
            temperature=0.05,
        )
        if llm_r and llm_r.get("intent") in INTENTS and float(llm_r.get("confidence", 0)) > best_score:
            best = llm_r["intent"]
            best_score = float(llm_r["confidence"])
            engine = "llm"
    return {
        "intent": best,
        "confidence": min(1.0, best_score),
        "agents": list(INTENTS[best]["agents"]),
        "engine": engine,
    }


# ═══════════════════════════════════════════════════════════════════
#  Router Agent
# ═══════════════════════════════════════════════════════════════════

def router_agent(state: WorkflowState) -> dict:
    c = _classify(state.get("message", ""))
    agents = c["agents"]
    pipeline: list[str] = []
    for a in agents:
        pipeline.append(a)
    pipeline.append("orchestrator")
    return {
        "intent": c["intent"],
        "intent_confidence": c["confidence"],
        "intent_pipeline": pipeline,
        "intent_engine": c["engine"],
        "agents_called": ["router"],
        "nodes_visited": ["router"],
    }


# ═══════════════════════════════════════════════════════════════════
#  Coach Agent (项目教练)
#  Tools: Diagnosis Engine + RAG + KG Extract + Web Search
# ═══════════════════════════════════════════════════════════════════

def coach_agent(state: WorkflowState) -> dict:
    from app.services.case_knowledge import infer_category, retrieve_cases_by_category
    from app.services.diagnosis_engine import run_diagnosis
    from app.services.web_search import web_search, format_for_llm as ws_fmt

    msg = state.get("message", "")
    mode = state.get("mode", "coursework")
    is_file = "[上传文件:" in msg

    # Tool 1: Diagnosis
    diag = run_diagnosis(input_text=msg, mode=mode)
    cat = infer_category(msg)
    refs = retrieve_cases_by_category(cat, limit=3)

    diag_data = diag.diagnosis
    if _llm.enabled and (is_file or len(msg) > 100):
        llm_diag = _llm.chat_json(
            system_prompt=(
                "你是【项目教练Agent】的诊断模块。基于规则引擎结果做深度分析。\n"
                '输出JSON: {"deep_bottleneck":"核心问题","evidence_gaps":["缺失1"],"strength":"亮点","stage":"idea|validation|growth"}'
            ),
            user_prompt=f"规则: {diag.diagnosis.get('bottleneck','')}\n触发: {[r.get('name') for r in diag.diagnosis.get('triggered_rules',[])]}\n内容: {msg[:1500]}",
            temperature=0.15,
        )
        if llm_diag:
            diag_data = {**diag.diagnosis, "llm_enhancement": llm_diag}

    # Tool 2: RAG
    rag_ctx = ""
    rag_cases: list[dict] = []
    if _rag and _rag.case_count > 0:
        rag_cases = _rag.retrieve(msg[:1000], top_k=3, category_filter=cat if cat else None)
        rag_ctx = _rag.format_for_llm(rag_cases)

    # Tool 3: KG Extract
    kg: dict[str, Any] = {}
    neo4j_ctx = ""
    if _llm.enabled and len(msg) > 15:
        ref_block = f"\n参考案例:\n{rag_ctx[:500]}" if rag_ctx else ""
        kg = _llm.chat_json(
            system_prompt=(
                "你是【项目教练Agent】的知识图谱模块。提取实体和关系。\n"
                + ("学生上传了文件，逐段分析。\n" if is_file else "")
                + '输出JSON: {"entities":[{"id":"e1","label":"名","type":"类型"}],'
                '"relationships":[{"source":"e1","target":"e2","relation":"关系"}],'
                '"structural_gaps":["缺失"],"content_strengths":["优势"],'
                '"completeness_score":6,"section_scores":{"problem_definition":0,"user_evidence":0,"solution_feasibility":0,"business_model":0,"competitive_advantage":0},'
                '"insight":"总结"}'
                + ref_block
            ),
            user_prompt=f"内容:\n{msg[:4000]}",
            model=settings.llm_reason_model if is_file else None,
            temperature=0.15,
        )
    if not kg or not kg.get("entities"):
        kg = {"entities": [], "relationships": [], "structural_gaps": ["文本过短"], "content_strengths": [], "completeness_score": 0, "section_scores": {}, "insight": "请提供更详细描述"}

    if _graph_service and kg.get("entities"):
        pid = state.get("project_state", {}).get("project_id", "unknown")
        _graph_service.merge_student_entities(pid, kg["entities"], kg.get("relationships", []))
        top_labels = [e["label"] for e in kg["entities"][:5] if e.get("label")]
        related = _graph_service.find_similar_entities(top_labels, limit=5)
        if related:
            neo4j_ctx = "; ".join(f"{r.get('entity','')}→{r.get('related_entity','')}" for r in related[:5] if r.get("entity"))

    # Tool 4: Web Search
    ws = web_search(msg, state.get("intent", ""), max_results=3)
    ws_ctx = ws_fmt(ws)

    # Compose coach's analysis
    coach_analysis = ""
    if _llm.enabled:
        llm_enh = diag_data.get("llm_enhancement", {})
        coach_analysis = _llm.chat_text(
            system_prompt=(
                "你是一位有10年双创辅导经验的导师，正在为学生的项目做深度分析。\n"
                "你的分析必须：\n"
                "1. 紧扣学生的具体内容，引用学生原话或具体细节来讨论\n"
                "2. 如果有参考案例，用'比如XX项目的做法是...'来自然引用\n"
                "3. 如果有联网搜索结果，引用具体的行业数据或市场信息\n"
                "4. 指出项目最核心的1-2个问题，而不是列一堆\n"
                "5. 给出非常具体的下一步行动（具体到这周该做什么）\n"
                "用4-6段话输出，深入而具体。"
            ),
            user_prompt=(
                f"学生说: {msg[:2000]}\n\n"
                f"诊断瓶颈: {diag_data.get('bottleneck','')}\n"
                + (f"深度分析: {llm_enh.get('deep_bottleneck','')} | 亮点: {llm_enh.get('strength','')} | 阶段: {llm_enh.get('stage','')}\n" if llm_enh else "")
                + f"KG洞察: {kg.get('insight','')}\n结构缺陷: {kg.get('structural_gaps',[])}\n内容优势: {kg.get('content_strengths',[])}\n"
                + f"维度评分: {kg.get('section_scores',{})}\n"
                + (f"参考案例:\n{rag_ctx[:800]}\n" if rag_ctx else "")
                + (f"联网搜索:\n{ws_ctx[:500]}\n" if ws_ctx else "")
                + (f"图谱关联: {neo4j_ctx}\n" if neo4j_ctx else "")
            ),
            temperature=0.4,
        )

    return {
        "coach_output": {
            "agent": "项目教练",
            "analysis": coach_analysis,
            "tools_used": ["diagnosis", "rag", "kg_extract", "web_search"],
        },
        "diagnosis": diag_data,
        "next_task": diag.next_task,
        "category": cat,
        "kg_analysis": kg,
        "rag_cases": rag_cases,
        "rag_context": rag_ctx,
        "web_search_result": ws,
        "agents_called": ["项目教练"],
        "nodes_visited": ["coach"],
    }


# ═══════════════════════════════════════════════════════════════════
#  Analyst Agent (风险分析师)
#  Tools: Hypergraph + Challenge Strategies + Critic LLM
# ═══════════════════════════════════════════════════════════════════

def analyst_agent(state: WorkflowState) -> dict:
    from app.services.challenge_strategies import format_for_critic, match_strategies

    msg = state.get("message", "")
    diag = state.get("diagnosis", {})
    cat = state.get("category", "")
    rag_ctx = state.get("rag_context", "")
    bottleneck = diag.get("bottleneck", "")
    llm_enh = diag.get("llm_enhancement", {})
    rules = diag.get("triggered_rules", []) or []
    rule_ids = [r.get("id", "") for r in rules if isinstance(r, dict)]

    # Tool 1: Hypergraph risk patterns
    hyper: dict[str, Any] = {}
    if _hypergraph_service:
        hyper = _hypergraph_service.insight(category=cat, rule_ids=rule_ids, limit=3)
    hyper_edges = (hyper or {}).get("edges", []) or []
    hyper_note = "; ".join(e.get("teaching_note", "") for e in hyper_edges[:2]) if hyper_edges else ""

    # Tool 2: Challenge strategies
    strategies = match_strategies(msg, rule_ids, max_results=2)
    strategy_ctx = format_for_critic(strategies)

    # Tool 3: Critic LLM
    critic_data: dict[str, Any] = {}
    if _llm.enabled:
        critic_data = _llm.chat_json(
            system_prompt=(
                "你是【风险分析Agent】的批判思维模块。做深度反事实挑战。\n"
                + (f"追问策略库:\n{strategy_ctx}\n\n" if strategy_ctx else "")
                + (f"超图风险模式: {hyper_note}\n\n" if hyper_note else "")
                + (f"深度诊断: {llm_enh.get('deep_bottleneck','')} | 缺口: {llm_enh.get('evidence_gaps',[])}\n\n" if llm_enh else "")
                + '输出JSON: {"challenge_questions":["追问1","追问2","追问3"],'
                '"missing_evidence":["缺失1","缺失2"],"risk_summary":"一句话",'
                '"counterfactual":"反事实","evidence_standard":"优秀标准"}'
            ),
            user_prompt=f"学生:{msg[:800]}\n瓶颈:{bottleneck}\n规则:{rule_ids}",
            temperature=0.25,
        )
    if not critic_data:
        critic_data = {
            "challenge_questions": [s["probing_layers"][0] for s in strategies[:3]] if strategies else ["需要更多信息"],
            "missing_evidence": llm_enh.get("evidence_gaps", []) if llm_enh else [],
            "risk_summary": bottleneck or "暂无",
            "counterfactual": strategies[0]["counterfactual"] if strategies else "",
        }

    # Compose analyst's summary
    analyst_analysis = ""
    if _llm.enabled:
        analyst_analysis = _llm.chat_text(
            system_prompt=(
                "你是一位经验丰富的投资人，正在对这个创业项目做尽职调查式的风险评估。\n"
                "你的分析必须：\n"
                "1. 直接指出最致命的1-2个风险，用具体的反事实情境说明后果\n"
                "2. 提出3个学生必须回答的尖锐问题（不是泛泛的问题，而是针对他们项目的具体追问）\n"
                "3. 说明优秀项目在同一维度通常提供什么证据来证明可行性\n"
                "4. 引用学生内容中的具体表述来指出逻辑漏洞\n"
                "语气专业犀利但建设性。用3-5段话输出。"
            ),
            user_prompt=(
                f"学生说: {msg[:1200]}\n\n"
                f"风险总结: {critic_data.get('risk_summary','')}\n"
                f"关键追问: {critic_data.get('challenge_questions',[])}\n"
                f"缺失证据: {critic_data.get('missing_evidence',[])}\n"
                f"反事实: {critic_data.get('counterfactual','')}\n"
                f"证据标准: {critic_data.get('evidence_standard','')}\n"
                + (f"超图风险模式: {hyper_note}\n" if hyper_note else "")
            ),
            temperature=0.35,
        )

    return {
        "analyst_output": {
            "agent": "风险分析师",
            "analysis": analyst_analysis,
            "tools_used": ["hypergraph", "challenge_strategies", "critic_llm"],
        },
        "hypergraph_insight": hyper,
        "critic": critic_data,
        "challenge_strategies": strategies,
        "agents_called": ["风险分析师"],
        "nodes_visited": ["analyst"],
    }


# ═══════════════════════════════════════════════════════════════════
#  Advisor Agent (竞赛顾问)
#  Tools: Competition LLM + Critic (evaluation perspective)
# ═══════════════════════════════════════════════════════════════════

def advisor_agent(state: WorkflowState) -> dict:
    msg = state.get("message", "")
    mode = state.get("mode", "coursework")
    rag_ctx = state.get("rag_context", "")
    critic = state.get("critic", {})

    comp_data: dict[str, Any] = {}
    if _llm.enabled:
        comp_data = _llm.chat_json(
            system_prompt=(
                "你是【竞赛顾问Agent】，互联网+/挑战杯资深评审。\n"
                + (f"参考获奖案例:\n{rag_ctx[:500]}\n\n" if rag_ctx else "")
                + '输出JSON: {"judge_questions":["问题1","问题2","问题3"],'
                '"defense_tips":["技巧1","技巧2","技巧3"],'
                '"presentation_structure":["环节1","环节2","环节3","环节4"],'
                '"prize_readiness":50,"key_improvement":"一个提升点"}'
            ),
            user_prompt=f"项目:{msg[:800]}\n模式:{mode}",
            temperature=0.25,
        )

    advisor_analysis = ""
    if _llm.enabled:
        advisor_analysis = _llm.chat_text(
            system_prompt=(
                "你当过20+次互联网+/挑战杯的评审专家，非常了解评委的思维方式。\n"
                "你的分析必须：\n"
                "1. 模拟评委视角，给出3个最可能被问到的尖锐问题，以及应对策略\n"
                "2. 基于项目当前状态，评估竞赛准备度，指出最大差距\n"
                "3. 给出路演/PPT的具体优化建议（不是泛泛的'注意逻辑'，而是具体的结构调整）\n"
                "4. 引用评审标准中的评分要点来说明为什么这些很重要\n"
                "用3-5段话输出，实操性强。"
            ),
            user_prompt=(
                f"学生说: {msg[:1000]}\n\n"
                f"评委可能问: {comp_data.get('judge_questions',[])}\n"
                f"竞赛准备度: {comp_data.get('prize_readiness',0)}%\n"
                f"关键提升点: {comp_data.get('key_improvement','')}\n"
                f"答辩技巧: {comp_data.get('defense_tips',[])}\n"
                + (f"项目风险: {critic.get('risk_summary','')}\n" if critic else "")
            ),
            temperature=0.35,
        )

    return {
        "advisor_output": {
            "agent": "竞赛顾问",
            "analysis": advisor_analysis,
            "tools_used": ["competition_llm", "rag_reference"],
        },
        "competition": comp_data or {},
        "agents_called": ["竞赛顾问"],
        "nodes_visited": ["advisor"],
    }


# ═══════════════════════════════════════════════════════════════════
#  Tutor Agent (学习导师)
#  Tools: Web Search + Learning LLM
# ═══════════════════════════════════════════════════════════════════

def tutor_agent(state: WorkflowState) -> dict:
    from app.services.web_search import web_search, format_for_llm as ws_fmt

    msg = state.get("message", "")
    intent = state.get("intent", "")

    # Tool 1: Web search
    ws = state.get("web_search_result") or {}
    ws_ctx = ""
    if not ws.get("searched"):
        ws = web_search(msg, intent, max_results=3)
        ws_ctx = ws_fmt(ws)
    else:
        ws_ctx = ws_fmt(ws) if ws.get("results") else ""

    # Tool 2: Learning LLM
    learn_data: dict[str, Any] = {}
    if _llm.enabled:
        learn_data = _llm.chat_json(
            system_prompt=(
                "你是【学习导师Agent】，创新创业课程教授。\n"
                + (f"联网搜索补充:\n{ws_ctx[:400]}\n\n" if ws_ctx else "")
                + '输出JSON: {"definition":"概念解释","example":"真实案例",'
                '"practice_task":"练习任务","common_mistakes":["误区1","误区2"],'
                '"recommended_reading":"推荐资源"}'
            ),
            user_prompt=f"学生问: {msg[:800]}",
            temperature=0.3,
        )

    tutor_analysis = ""
    if _llm.enabled:
        tutor_analysis = _llm.chat_text(
            system_prompt=(
                "你是大学创新创业课的教授，擅长用通俗的方式讲复杂的商业概念。\n"
                "你的回答必须：\n"
                "1. 用一句话通俗定义概念（避免教科书式定义）\n"
                "2. 举1-2个真实的创业案例来解释（如果有搜索结果，引用具体的数据和事实）\n"
                "3. 给学生一个本周就能做的练习任务（非常具体，可执行）\n"
                "4. 指出常见误区（学生最容易踩的坑）\n"
                "用4-6段话输出，生动有趣。"
            ),
            user_prompt=(
                f"学生问: {msg[:1000]}\n\n"
                f"概念解释: {learn_data.get('definition','')}\n"
                f"真实案例: {learn_data.get('example','')}\n"
                f"练习任务: {learn_data.get('practice_task','')}\n"
                f"常见误区: {learn_data.get('common_mistakes',[])}\n"
                + (f"联网搜索到的最新资料:\n{ws_ctx[:600]}\n" if ws_ctx else "")
            ),
            temperature=0.4,
        )

    return {
        "tutor_output": {
            "agent": "学习导师",
            "analysis": tutor_analysis,
            "tools_used": ["web_search", "learning_llm"],
        },
        "learning": learn_data or {},
        "web_search_result": ws,
        "agents_called": ["学习导师"],
        "nodes_visited": ["tutor"],
    }


# ═══════════════════════════════════════════════════════════════════
#  Grader Agent (评分官)
#  Tools: Rubric from Diagnosis + KG section scores
# ═══════════════════════════════════════════════════════════════════

def grader_agent(state: WorkflowState) -> dict:
    diag = state.get("diagnosis", {})
    kg = state.get("kg_analysis", {})
    rubric = diag.get("rubric", [])
    overall = diag.get("overall_score")
    sec_scores = kg.get("section_scores", {})

    grader_analysis = ""
    if rubric and overall is not None:
        lines = []
        for r in rubric:
            status = "✅" if r.get("status") == "ok" else "⚠️"
            lines.append(f"{status} {r['item']}: {r['score']}/10")
        score_text = "\n".join(lines)

        if _llm.enabled:
            grader_analysis = _llm.chat_text(
                system_prompt=(
                    "你负责按照创业竞赛评审标准给项目打分。\n"
                    "你的评估必须：\n"
                    "1. 总结当前总分和各维度得分情况\n"
                    "2. 指出得分最低的2个维度，分析为什么低\n"
                    "3. 给出提分的具体操作建议（具体到添加什么内容）\n"
                    "4. 指出距离优秀（8/10）还差多少，重点补什么\n"
                    "用3-4段话输出，像一份评审反馈报告。"
                ),
                user_prompt=f"Rubric评分:\n{score_text}\n总分: {overall}/10\nKG维度评分: {sec_scores}",
                temperature=0.2,
            )
    else:
        grader_analysis = "信息不足，暂无法给出完整评分。请提供更详细的项目描述或上传计划书。"

    return {
        "grader_output": {
            "agent": "评分官",
            "analysis": grader_analysis,
            "tools_used": ["rubric_engine", "kg_scores"],
        },
        "agents_called": ["评分官"],
        "nodes_visited": ["grader"],
    }


# ═══════════════════════════════════════════════════════════════════
#  Orchestrator — synthesise all agent outputs into final reply
# ═══════════════════════════════════════════════════════════════════

def orchestrator(state: WorkflowState) -> dict:
    msg = state.get("message", "")
    intent = state.get("intent", "general_chat")
    conv_msgs = state.get("conversation_messages", [])
    hist = state.get("history_context", "")
    tfb = state.get("teacher_feedback_context", "")
    is_file = "[上传文件:" in msg

    # Collect all agent analyses as anonymous sections
    analysis_parts: list[str] = []
    for key in ("coach_output", "analyst_output", "advisor_output", "tutor_output", "grader_output"):
        out = state.get(key, {})
        if out and out.get("analysis"):
            analysis_parts.append(out["analysis"])

    conv_ctx = ""
    if conv_msgs:
        recent = conv_msgs[-6:]
        conv_ctx = "\n".join(
            f"{'学生' if m.get('role')=='user' else '教练'}: {str(m.get('content',''))[:200]}"
            for m in recent
        )

    # Length guidance — significantly increased
    msg_len = len(msg)
    n_analyses = len(analysis_parts)
    if is_file:
        length_guide = "1200-2500字。必须逐段分析文件内容，引用原文，对比案例，给出具体修改建议。用标题/表格/引用块组织。"
    elif intent == "general_chat" or msg_len < 20:
        length_guide = "100-250字。热情友好，自然引导到项目话题。"
    elif intent == "learning_concept":
        length_guide = "500-900字。通俗解释概念→真实案例→练习任务→常见误区。用标题分层。"
    elif n_analyses >= 3:
        length_guide = "900-1500字。多维度深入分析，引用具体案例和数据对比。用标题、表格、引用块丰富排版。"
    elif n_analyses >= 2:
        length_guide = "600-1100字。深入分析关键问题，引用案例和证据。"
    elif msg_len > 200:
        length_guide = "500-800字。针对学生具体内容深入展开。"
    else:
        length_guide = "350-600字。聚焦问题给出有深度的建议。"

    analyses_ctx = "\n\n---\n\n".join(analysis_parts)

    reply = ""
    if _llm.enabled and analyses_ctx:
        reply = _llm.chat_text(
            system_prompt=(
                "你是一位有10年双创辅导经验的资深导师。你已经从多个专业角度对学生的问题进行了深入分析，"
                "现在需要将这些分析整合成一份自然、连贯、有深度的回复。\n\n"
                "## 绝对禁止\n"
                "- **绝对不要提到任何Agent、分析师、教练、导师、评分官等角色名称**\n"
                "- 不要说'我们的XX分析师认为'、'XX Agent建议'等暴露系统结构的话\n"
                "- 不要说'根据多维度分析'、'经过系统分析'等套话\n"
                "- 不要用千篇一律的开头和结尾模板\n\n"
                "## 必须做到\n"
                "- **以第一人称'我'来回复**，就像一个真正的导师在面对面和学生聊天\n"
                "- **紧扣学生的具体内容**：引用学生原话、具体数据、项目细节来讨论\n"
                "- **引用参考案例时自然融入**：如'比如XX项目也做了类似的事，他们的做法是...'，不要说'根据知识库'\n"
                "- **追问要有针对性**：不是泛泛地问'你想过XX吗'，而是基于学生内容的具体漏洞来追问\n"
                "- **给出可执行的下一步**：不是'建议你做市场调研'，而是'下周找5个XX专业的同学，问他们这3个问题：...'\n"
                "- 灵活使用Markdown：标题层级体现思路结构，加粗突出关键点，表格对比信息，引用块引述证据\n"
                "- **每次回复的结构要不同**：根据内容自然组织，不要套公式\n"
                f"- **回复长度**: {length_guide}\n"
                "- 深度优于广度：宁可讲透一个核心问题，也不要浮皮潦草地列10个要点\n"
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
        reply = _llm.chat_text(
            system_prompt=(
                "你是一位友好的创业辅导导师。用第一人称自然回复学生，引导到项目话题。"
                "不要暴露任何系统内部结构。"
            ),
            user_prompt=f"学生说: {msg[:500]}" + (f"\n上下文: {conv_ctx}" if conv_ctx else ""),
            temperature=0.55,
        )

    if not reply or len(reply.strip()) < 20:
        diag = state.get("diagnosis", {})
        bn = str(diag.get("bottleneck") or "")
        nt = state.get("next_task", {})
        reply = f"**{bn}**\n\n> 下一步：{nt.get('title','')}" if bn else "你好！告诉我你的项目想法，我来帮你诊断和分析。"

    return {"assistant_message": reply.strip(), "nodes_visited": ["orchestrator"]}


# ═══════════════════════════════════════════════════════════════════
#  Conditional routing
# ═══════════════════════════════════════════════════════════════════

def _route_from_router(state: WorkflowState) -> str:
    pl = state.get("intent_pipeline", [])
    if not pl:
        return "orchestrator"
    first = pl[0]
    return first if first in {"coach", "analyst", "advisor", "tutor", "grader", "orchestrator"} else "orchestrator"


def _next_agent(state: WorkflowState, current: str) -> str:
    pl = state.get("intent_pipeline", [])
    try:
        idx = pl.index(current)
        if idx + 1 < len(pl):
            return pl[idx + 1]
    except ValueError:
        pass
    return "orchestrator"


def _after_coach(s: WorkflowState) -> str: return _next_agent(s, "coach")
def _after_analyst(s: WorkflowState) -> str: return _next_agent(s, "analyst")
def _after_advisor(s: WorkflowState) -> str: return _next_agent(s, "advisor")
def _after_tutor(s: WorkflowState) -> str: return _next_agent(s, "tutor")
def _after_grader(s: WorkflowState) -> str: return _next_agent(s, "grader")


AGENT_NODES = {"coach", "analyst", "advisor", "tutor", "grader", "orchestrator"}


def _build() -> Any:
    g = StateGraph(WorkflowState)

    g.add_node("router",       router_agent)
    g.add_node("coach",        coach_agent)
    g.add_node("analyst",      analyst_agent)
    g.add_node("advisor",      advisor_agent)
    g.add_node("tutor",        tutor_agent)
    g.add_node("grader",       grader_agent)
    g.add_node("orchestrator", orchestrator)

    g.set_entry_point("router")

    g.add_conditional_edges("router",  _route_from_router, {n: n for n in AGENT_NODES})
    g.add_conditional_edges("coach",   _after_coach,       {n: n for n in AGENT_NODES})
    g.add_conditional_edges("analyst", _after_analyst,      {n: n for n in AGENT_NODES})
    g.add_conditional_edges("advisor", _after_advisor,      {n: n for n in AGENT_NODES})
    g.add_conditional_edges("tutor",   _after_tutor,        {n: n for n in AGENT_NODES})
    g.add_conditional_edges("grader",  _after_grader,       {n: n for n in AGENT_NODES})
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
