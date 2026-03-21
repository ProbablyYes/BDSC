"""
LangGraph role-based multi-agent system for VentureAgent (V4).

Architecture: Router → DataGatherer → ParallelAgents → Orchestrator

V4 improvements over V3:
 - DataGatherer runs ALL tools in parallel (diagnosis, RAG, KG, search,
   hypergraph, critic) before any agent sees the data.
 - Role agents run in parallel via ThreadPoolExecutor — each is a single
   LLM call that consumes the shared gathered context.
 - New Planner agent generates concrete weekly action items.
 - Every intent gets full data (KG/RAG/diagnosis not locked to Coach).
 - Total serial LLM groups: 3  (gather ‖ agents ‖ orchestrator)
   ⇒ expected latency ~60-90s vs V3's ~8-10 min.
"""

from __future__ import annotations

import logging
import operator
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
    intent_pipeline: list[str]
    intent_engine: str

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
        "agents": ["coach", "tutor", "planner"],
    },
    "project_diagnosis": {
        "keywords": ["我想做", "我的项目", "产品是", "我们做的", "分析一下",
                      "怎么样", "可行吗", "痛点", "商业计划", "帮我看看"],
        "desc": "学生描述项目并希望获得诊断",
        "agents": ["coach", "analyst", "grader", "planner"],
    },
    "evidence_check": {
        "keywords": ["访谈", "问卷", "调研", "证据", "用户", "验证",
                      "数据", "样本", "反馈", "需求调研"],
        "desc": "学生讨论证据/调研",
        "agents": ["coach", "analyst", "planner"],
    },
    "business_model": {
        "keywords": ["商业模式", "盈利", "收入", "成本", "市场规模",
                      "tam", "sam", "som", "cac", "ltv", "定价", "渠道"],
        "desc": "学生讨论商业模式",
        "agents": ["coach", "analyst", "tutor", "planner"],
    },
    "competition_prep": {
        "keywords": ["路演", "竞赛", "答辩", "比赛", "评委",
                      "ppt", "演讲", "展示", "互联网+", "挑战杯"],
        "desc": "学生准备竞赛/路演",
        "agents": ["coach", "advisor", "analyst", "planner"],
    },
    "pressure_test": {
        "keywords": ["压力测试", "挑战", "反驳", "护城河", "巨头",
                      "如果", "竞争对手", "为什么不"],
        "desc": "学生要求压力测试",
        "agents": ["coach", "analyst", "advisor"],
    },
    "learning_concept": {
        "keywords": ["什么是", "怎么做", "教我", "学习", "方法", "理论",
                      "概念", "lean canvas", "mvp", "商业画布"],
        "desc": "学生想学创业概念/方法论",
        "agents": ["tutor", "planner"],
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
    best, best_score, _ = scores[0]
    if best_score < 0.15:
        if len(text) > 60:
            best, best_score = "project_diagnosis", 0.5
        else:
            best, best_score = "general_chat", 0.4
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
#  Node 1: Router
# ═══════════════════════════════════════════════════════════════════

def router_agent(state: WorkflowState) -> dict:
    c = _classify(state.get("message", ""))
    return {
        "intent": c["intent"],
        "intent_confidence": c["confidence"],
        "intent_pipeline": c["agents"],
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
    for r in ws.get("results", [])[:3]:
        parts.append(f"- {r.get('title','')}: {r.get('snippet','')}")
    return "\n".join(parts)[:600]


# ═══════════════════════════════════════════════════════════════════
#  Node 2: DataGatherer — runs ALL tools in parallel
# ═══════════════════════════════════════════════════════════════════

def gather_context_node(state: WorkflowState) -> dict:
    intent = state.get("intent", "general_chat")
    if intent == "general_chat":
        return {"nodes_visited": ["gather_context"]}

    msg = state.get("message", "")
    mode = state.get("mode", "coursework")
    is_file = "[上传文件:" in msg

    # ── Phase 1: instant synchronous operations ──
    from app.services.case_knowledge import infer_category
    from app.services.challenge_strategies import format_for_critic, match_strategies
    from app.services.diagnosis_engine import run_diagnosis

    diag_obj = run_diagnosis(input_text=msg, mode=mode)
    diag_data: dict = diag_obj.diagnosis
    next_task: dict = diag_obj.next_task
    cat = infer_category(msg)
    rules = diag_data.get("triggered_rules", []) or []
    rule_ids = [r.get("id", "") for r in rules if isinstance(r, dict)]
    bottleneck = diag_data.get("bottleneck", "")

    strategies = match_strategies(msg, rule_ids, max_results=2)
    strategy_ctx = format_for_critic(strategies)

    # ── Phase 2: parallel I/O-bound operations ──
    collected: dict[str, Any] = {}

    def _task_rag():
        if _rag is None or _rag.case_count == 0:
            return {"rag_cases": [], "rag_context": ""}
        cases = _rag.retrieve(msg[:1000], top_k=3, category_filter=cat or None)
        ctx = _rag.format_for_llm(cases)
        return {"rag_cases": cases, "rag_context": ctx}

    def _task_kg():
        if not _llm.enabled or len(msg) < 15:
            return {"kg_analysis": _default_kg()}
        kg = _llm.chat_json(
            system_prompt=(
                "你是知识图谱抽取模块。从学生内容中提取实体和关系。\n"
                + ("学生上传了文件，请逐段分析。\n" if is_file else "")
                + '输出JSON: {"entities":[{"id":"e1","label":"名","type":"类型"}],'
                '"relationships":[{"source":"e1","target":"e2","relation":"关系"}],'
                '"structural_gaps":["缺失"],"content_strengths":["优势"],'
                '"completeness_score":6,'
                '"section_scores":{"problem_definition":0,"user_evidence":0,'
                '"solution_feasibility":0,"business_model":0,"competitive_advantage":0},'
                '"insight":"总结"}'
            ),
            user_prompt=f"内容:\n{msg[:4000]}",
            model=settings.llm_reason_model if is_file else None,
            temperature=0.15,
        )
        if not kg or not kg.get("entities"):
            return {"kg_analysis": _default_kg()}
        return {"kg_analysis": kg}

    def _task_diag_enhance():
        if not _llm.enabled or (not is_file and len(msg) < 100):
            return {}
        enh = _llm.chat_json(
            system_prompt=(
                "你是诊断增强模块。基于规则引擎结果做深度分析。\n"
                '输出JSON: {"deep_bottleneck":"核心问题",'
                '"evidence_gaps":["缺失1"],"strength":"亮点",'
                '"stage":"idea|validation|growth"}'
            ),
            user_prompt=(
                f"规则瓶颈: {bottleneck}\n"
                f"触发规则: {[r.get('name') for r in rules[:5] if isinstance(r,dict)]}\n"
                f"学生内容: {msg[:1500]}"
            ),
            temperature=0.15,
        )
        return {"_diag_enh": enh} if enh else {}

    def _task_web():
        from app.services.web_search import web_search
        ws = web_search(msg, intent, max_results=3)
        return {"web_search_result": ws}

    def _task_hyper():
        if not _hypergraph_service:
            return {"hypergraph_insight": {}}
        try:
            h = _hypergraph_service.insight(category=cat, rule_ids=rule_ids, limit=3)
            return {"hypergraph_insight": h}
        except Exception as exc:
            logger.warning("Hypergraph insight failed: %s", exc)
            return {"hypergraph_insight": {}}

    def _task_critic():
        if not _llm.enabled:
            return {"critic": _fallback_critic()}
        hyper_note = ""
        if _hypergraph_service:
            try:
                hi = _hypergraph_service.insight(category=cat, rule_ids=rule_ids, limit=2)
                edges = (hi or {}).get("edges", []) or []
                hyper_note = "; ".join(e.get("teaching_note", "") for e in edges[:2])
            except Exception:
                pass
        critic = _llm.chat_json(
            system_prompt=(
                "你是批判思维模块。对学生项目做深度反事实挑战。\n"
                + (f"追问策略库:\n{strategy_ctx}\n\n" if strategy_ctx else "")
                + (f"超图风险模式: {hyper_note}\n\n" if hyper_note else "")
                + '输出JSON: {"challenge_questions":["追问1","追问2","追问3"],'
                '"missing_evidence":["缺失1","缺失2"],"risk_summary":"一句话",'
                '"counterfactual":"反事实","evidence_standard":"优秀标准"}'
            ),
            user_prompt=f"学生:{msg[:800]}\n瓶颈:{bottleneck}\n规则:{rule_ids}",
            temperature=0.25,
        )
        return {"critic": critic} if critic else {"critic": _fallback_critic()}

    def _fallback_critic():
        return {
            "challenge_questions": (
                [s["probing_layers"][0] for s in strategies[:3]] if strategies else ["需要更多信息"]
            ),
            "missing_evidence": [],
            "risk_summary": bottleneck or "暂无",
        }

    # ── Execute parallel phase ──
    tasks: list[Callable] = [_task_rag, _task_kg, _task_diag_enhance,
                             _task_web, _task_hyper, _task_critic]
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        future_map = {pool.submit(fn): fn.__name__ for fn in tasks}
        try:
            for future in as_completed(future_map, timeout=130):
                name = future_map[future]
                try:
                    collected.update(future.result())
                except Exception as exc:
                    logger.warning("gather_context %s error: %s", name, exc)
        except TimeoutError:
            logger.warning("gather_context timed out — some tasks incomplete")

    # ── Post-parallel: merge results ──
    enh = collected.pop("_diag_enh", None)
    if enh:
        diag_data = {**diag_data, "llm_enhancement": enh}

    kg = collected.get("kg_analysis", _default_kg())
    if _graph_service and kg.get("entities"):
        pid = state.get("project_state", {}).get("project_id", "unknown")
        try:
            _graph_service.merge_student_entities(
                pid, kg["entities"], kg.get("relationships", [])
            )
        except Exception as exc:
            logger.warning("Neo4j merge failed: %s", exc)

    return {
        "diagnosis": diag_data,
        "next_task": next_task,
        "category": cat,
        "kg_analysis": kg,
        "rag_cases": collected.get("rag_cases", []),
        "rag_context": collected.get("rag_context", ""),
        "web_search_result": collected.get("web_search_result", {}),
        "hypergraph_insight": collected.get("hypergraph_insight", {}),
        "critic": collected.get("critic", {}),
        "challenge_strategies": strategies,
        "nodes_visited": ["gather_context"],
    }


# ═══════════════════════════════════════════════════════════════════
#  Role-Agent analysis functions (each = 1 LLM call)
# ═══════════════════════════════════════════════════════════════════

def _coach_analyze(state: dict) -> dict:
    msg = state.get("message", "")
    diag = state.get("diagnosis", {})
    rag_ctx = state.get("rag_context", "")
    kg = state.get("kg_analysis", {})
    ws = state.get("web_search_result", {})
    ws_ctx = _fmt_ws(ws)
    llm_enh = diag.get("llm_enhancement", {})

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

    analysis = _llm.chat_text(
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
            f"诊断瓶颈: {diag.get('bottleneck','')}\n"
            + (f"深度分析: {llm_enh.get('deep_bottleneck','')} | 亮点: {llm_enh.get('strength','')} | 阶段: {llm_enh.get('stage','')}\n" if llm_enh else "")
            + f"KG洞察: {kg.get('insight','')}\n结构缺陷: {kg.get('structural_gaps',[])}\n"
            + f"维度评分: {kg.get('section_scores',{})}\n"
            + (f"参考案例:\n{rag_ctx[:800]}\n" if rag_ctx else "")
            + (f"联网搜索:\n{ws_ctx[:500]}\n" if ws_ctx else "")
            + (f"图谱关联: {neo4j_ctx}\n" if neo4j_ctx else "")
        ),
        temperature=0.4,
    )
    return {
        "agent": "项目教练",
        "analysis": analysis or "",
        "tools_used": ["diagnosis", "rag", "kg_extract", "web_search"],
    }


def _analyst_analyze(state: dict) -> dict:
    msg = state.get("message", "")
    diag = state.get("diagnosis", {})
    critic = state.get("critic", {})
    hyper = state.get("hypergraph_insight", {})
    hyper_edges = (hyper or {}).get("edges", []) or []
    hyper_note = "; ".join(e.get("teaching_note", "") for e in hyper_edges[:2])

    analysis = _llm.chat_text(
        system_prompt=(
            "你是一位经验丰富的投资人，正在对这个创业项目做尽职调查式的风险评估。\n"
            "你的分析必须：\n"
            "1. 直接指出最致命的1-2个风险，用具体的反事实情境说明后果\n"
            "2. 提出3个学生必须回答的尖锐问题（针对他们项目的具体追问）\n"
            "3. 说明优秀项目在同一维度通常提供什么证据来证明可行性\n"
            "4. 引用学生内容中的具体表述来指出逻辑漏洞\n"
            "语气专业犀利但建设性。用3-5段话输出。"
        ),
        user_prompt=(
            f"学生说: {msg[:1200]}\n\n"
            f"风险总结: {critic.get('risk_summary','')}\n"
            f"关键追问: {critic.get('challenge_questions',[])}\n"
            f"缺失证据: {critic.get('missing_evidence',[])}\n"
            f"反事实: {critic.get('counterfactual','')}\n"
            f"证据标准: {critic.get('evidence_standard','')}\n"
            + (f"超图风险模式: {hyper_note}\n" if hyper_note else "")
        ),
        temperature=0.35,
    )
    return {
        "agent": "风险分析师",
        "analysis": analysis or "",
        "tools_used": ["hypergraph", "challenge_strategies", "critic_llm"],
    }


def _advisor_analyze(state: dict) -> dict:
    msg = state.get("message", "")
    mode = state.get("mode", "coursework")
    rag_ctx = state.get("rag_context", "")
    critic = state.get("critic", {})

    analysis = _llm.chat_text(
        system_prompt=(
            "你当过20+次互联网+/挑战杯的评审专家，非常了解评委的思维方式。\n"
            "你的分析必须：\n"
            "1. 模拟评委视角，给出3个最可能被问到的尖锐问题，以及应对策略\n"
            "2. 基于项目当前状态，评估竞赛准备度，指出最大差距\n"
            "3. 给出路演/PPT的具体优化建议（具体的结构调整，不是泛泛的'注意逻辑'）\n"
            "4. 引用评审标准中的评分要点来说明为什么这些很重要\n"
            "用3-5段话输出，实操性强。"
        ),
        user_prompt=(
            f"学生说: {msg[:1000]}\n模式: {mode}\n\n"
            + (f"参考获奖案例:\n{rag_ctx[:500]}\n" if rag_ctx else "")
            + (f"项目风险: {critic.get('risk_summary','')}\n" if critic else "")
        ),
        temperature=0.35,
    )
    return {
        "agent": "竞赛顾问",
        "analysis": analysis or "",
        "tools_used": ["competition_llm", "rag_reference"],
    }


def _tutor_analyze(state: dict) -> dict:
    msg = state.get("message", "")
    ws = state.get("web_search_result", {})
    ws_ctx = _fmt_ws(ws)

    analysis = _llm.chat_text(
        system_prompt=(
            "你是大学创新创业课的教授，擅长用通俗的方式讲复杂的商业概念。\n"
            "你的回答必须：\n"
            "1. 用一句话通俗定义概念（避免教科书式定义）\n"
            "2. 举1-2个真实的创业案例来解释（如果有搜索结果，引用具体数据和事实）\n"
            "3. 给学生一个本周就能做的练习任务（非常具体，可执行）\n"
            "4. 指出常见误区（学生最容易踩的坑）\n"
            "用4-6段话输出，生动有趣。"
        ),
        user_prompt=(
            f"学生问: {msg[:1000]}\n\n"
            + (f"联网搜索到的最新资料:\n{ws_ctx[:600]}\n" if ws_ctx else "")
        ),
        temperature=0.4,
    )
    return {
        "agent": "学习导师",
        "analysis": analysis or "",
        "tools_used": ["web_search", "learning_llm"],
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
            "2. 指出得分最低的2个维度，分析为什么低\n"
            "3. 给出提分的具体操作建议（具体到添加什么内容）\n"
            "4. 指出距离优秀（8/10）还差多少，重点补什么\n"
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
    critic = state.get("critic", {})

    plan = _llm.chat_json(
        system_prompt=(
            "你是行动规划师。基于所有分析结果，为学生生成本周具体可执行的行动计划。\n"
            "每个任务必须足够具体（谁、做什么、怎么做、完成标准）。\n"
            '输出JSON: {"this_week":['
            '{"task":"任务名","why":"为什么重要","how":"具体做法(3-5步)","acceptance":"验收标准"}],'
            '"milestone":"本阶段目标"}'
        ),
        user_prompt=(
            f"学生: {msg[:500]}\n"
            f"诊断瓶颈: {diag.get('bottleneck','')}\n"
            f"建议任务: {next_task.get('title','')}: {next_task.get('description','')}\n"
            f"结构缺陷: {kg.get('structural_gaps',[])}\n"
            f"缺失证据: {critic.get('missing_evidence',[])}\n"
        ),
        temperature=0.2,
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
    "tutor": "学习导师",
    "grader": "评分官",
    "planner": "行动规划师",
}


# ═══════════════════════════════════════════════════════════════════
#  Node 3: Parallel Role Agents
# ═══════════════════════════════════════════════════════════════════

def run_role_agents_node(state: WorkflowState) -> dict:
    pipeline = state.get("intent_pipeline", [])
    agents_to_run = [a for a in pipeline if a in AGENT_FNS]

    if not agents_to_run:
        return {"nodes_visited": ["role_agents"]}

    outputs: dict[str, dict] = {}
    state_snapshot = dict(state)
    with ThreadPoolExecutor(max_workers=max(1, len(agents_to_run))) as pool:
        future_map = {pool.submit(AGENT_FNS[a], state_snapshot): a for a in agents_to_run}
        try:
            for future in as_completed(future_map, timeout=130):
                key = future_map[future]
                try:
                    outputs[key] = future.result()
                except Exception as exc:
                    logger.warning("Agent %s failed: %s", key, exc)
                    outputs[key] = {
                        "agent": AGENT_DISPLAY.get(key, key),
                        "analysis": "",
                        "tools_used": [],
                        "error": str(exc),
                    }
        except TimeoutError:
            logger.warning("role_agents timed out — some agents incomplete")

    result: dict[str, Any] = {
        "agents_called": [AGENT_DISPLAY.get(a, a) for a in agents_to_run],
        "nodes_visited": ["role_agents"],
    }
    for key in ("coach", "analyst", "advisor", "tutor", "grader", "planner"):
        if key in outputs:
            result[f"{key}_output"] = outputs[key]

    return result


# ═══════════════════════════════════════════════════════════════════
#  Node 4: Orchestrator — synthesise all agent outputs
# ═══════════════════════════════════════════════════════════════════

def orchestrator(state: WorkflowState) -> dict:
    msg = state.get("message", "")
    intent = state.get("intent", "general_chat")
    conv_msgs = state.get("conversation_messages", [])
    hist = state.get("history_context", "")
    tfb = state.get("teacher_feedback_context", "")
    is_file = "[上传文件:" in msg

    analysis_parts: list[str] = []
    for key in ("coach_output", "analyst_output", "advisor_output",
                "tutor_output", "grader_output", "planner_output"):
        out = state.get(key, {})
        if out and out.get("analysis"):
            analysis_parts.append(str(out["analysis"]))

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
                "- **绝对不要提到任何Agent、分析师、教练、导师、评分官、规划师等角色名称**\n"
                "- 不要说'我们的XX分析师认为'、'XX Agent建议'等暴露系统结构的话\n"
                "- 不要说'根据多维度分析'、'经过系统分析'等套话\n"
                "- 不要用千篇一律的开头和结尾模板\n\n"
                "## 必须做到\n"
                "- **以第一人称'我'来回复**，就像一个真正的导师在面对面和学生聊天\n"
                "- **紧扣学生的具体内容**：引用学生原话、具体数据、项目细节来讨论\n"
                "- **引用参考案例时自然融入**：如'比如XX项目也做了类似的事，他们的做法是...'，不要说'根据知识库'\n"
                "- **追问要有针对性**：基于学生内容的具体漏洞来追问\n"
                "- **如果有行动计划，自然地告诉学生本周该做什么**，不要说'规划师建议'\n"
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
