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
    hypergraph_student: dict
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
                      "不知道做什么", "创业方向", "还没想好",
                      "什么方向", "推荐", "建议做什么", "有什么项目"],
        "desc": "学生想要创业点子/方向建议",
        "agents": ["coach", "tutor", "planner"],
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
        "agents": ["coach", "analyst", "grader", "planner"],
        "need_web": False,
    },
    "evidence_check": {
        "keywords": ["访谈", "问卷", "调研", "证据", "用户", "验证",
                      "数据", "样本", "反馈", "需求调研",
                      "调查", "测试", "用户研究", "实地", "采访"],
        "desc": "学生讨论证据/调研",
        "agents": ["coach", "analyst", "planner"],
        "need_web": False,
    },
    "business_model": {
        "keywords": ["商业模式", "盈利", "收入", "成本", "市场规模",
                      "tam", "sam", "som", "cac", "ltv", "定价", "渠道",
                      "赚钱", "营收", "变现", "价格", "怎么盈利", "收费"],
        "desc": "学生讨论商业模式",
        "agents": ["coach", "analyst", "tutor", "planner"],
        "need_web": True, "web_results": 2,
    },
    "competition_prep": {
        "keywords": ["路演", "竞赛", "答辩", "比赛", "评委",
                      "ppt", "演讲", "展示", "互联网+", "挑战杯",
                      "备赛", "获奖", "演示", "展板"],
        "desc": "学生准备竞赛/路演",
        "agents": ["coach", "advisor", "analyst", "planner"],
        "need_web": True, "web_results": 3,
    },
    "market_competitor": {
        "keywords": ["竞品", "类似", "对手", "同类", "市面上", "行业",
                      "对标", "参考", "借鉴", "有没有什么", "有哪些",
                      "别人怎么做", "类似的", "替代品", "竞争者",
                      "先行者", "已有的", "现有产品", "同类产品",
                      "有什么软件", "有什么平台", "有什么app"],
        "desc": "学生想了解市场竞品/类似产品",
        "agents": ["coach", "analyst", "tutor"],
        "need_web": True, "web_results": 5,
        "focused": True,
    },
    "pressure_test": {
        "keywords": ["压力测试", "挑战", "反驳", "护城河", "巨头",
                      "如果", "竞争对手", "为什么不",
                      "质疑", "弱点", "风险", "万一"],
        "desc": "学生要求压力测试",
        "agents": ["coach", "analyst", "advisor"],
        "need_web": False,
    },
    "learning_concept": {
        "keywords": ["什么是", "怎么做", "教我", "学习", "方法", "理论",
                      "概念", "lean canvas", "mvp", "商业画布",
                      "解释一下", "是什么意思", "举例", "怎么理解"],
        "desc": "学生想学创业概念/方法论",
        "agents": ["tutor", "planner"],
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


def _infer_prev_intent(conversation_messages: list) -> str | None:
    for msg in reversed(conversation_messages):
        trace = msg.get("agent_trace")
        if trace and isinstance(trace, dict):
            orch = trace.get("orchestration", {})
            prev = orch.get("intent")
            if prev and prev in INTENTS and prev != "general_chat":
                return prev
    return None


def _classify(message: str, conversation_messages: list | None = None) -> dict:
    text = message.lower().strip()
    conv = conversation_messages or []

    # ── Fast path 1: file upload → project_diagnosis ──
    if "[上传文件:" in message:
        return {
            "intent": "project_diagnosis", "confidence": 0.95,
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
                    "agents": list(INTENTS[prev]["agents"]),
                    "engine": "follow_up",
                }

    # ── Keyword scoring ──
    scores: list[tuple[str, float]] = []
    for iid, spec in INTENTS.items():
        kws = spec.get("keywords", [])
        matched = [k for k in kws if k in text]
        score = (len(matched) / max(len(kws), 1) + 0.3) if matched else 0.0
        if matched:
            logger.debug("classify kw: intent=%s matched=%s score=%.3f", iid, matched, score)
        scores.append((iid, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    kw_best, kw_score = scores[0]
    logger.info("classify: msg='%s…' kw_best=%s kw_score=%.3f", text[:40], kw_best, kw_score)

    # Very strong keyword hit → trust it directly
    if kw_score >= 0.65:
        r = {
            "intent": kw_best, "confidence": min(1.0, kw_score),
            "agents": list(INTENTS[kw_best]["agents"]),
            "engine": "rule",
        }
        logger.info("classify → %s (rule, score=%.2f)", kw_best, kw_score)
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
                '输出JSON: {"intent":"ID","confidence":0.0-1.0}'
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
                r = {
                    "intent": llm_r["intent"],
                    "confidence": llm_conf,
                    "agents": list(INTENTS[llm_r["intent"]]["agents"]),
                    "engine": "llm",
                }
                logger.info("classify → %s (llm, conf=%.2f)", llm_r["intent"], llm_conf)
                return r

    # ── Fallback: use keyword result or heuristic ──
    if kw_score >= 0.15:
        r = {
            "intent": kw_best, "confidence": kw_score,
            "agents": list(INTENTS[kw_best]["agents"]),
            "engine": "rule",
        }
        logger.info("classify → %s (rule-fallback, score=%.2f)", kw_best, kw_score)
        return r
    if len(text) > 60:
        r = {
            "intent": "project_diagnosis", "confidence": 0.45,
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
            "agents": list(INTENTS[prev]["agents"]),
            "engine": "context_inherit",
        }
        logger.info("classify → %s (context_inherit)", prev)
        return r

    r = {
        "intent": "general_chat", "confidence": 0.4,
        "agents": list(INTENTS["general_chat"]["agents"]),
        "engine": "heuristic_short",
    }
    logger.info("classify → general_chat (heuristic_short)")
    return r


# ═══════════════════════════════════════════════════════════════════
#  Node 1: Router
# ═══════════════════════════════════════════════════════════════════

def _adjust_pipeline_for_mode(agents: list[str], mode: str, intent: str) -> list[str]:
    """Adjust agent pipeline based on the active mode."""
    if mode == "competition":
        if "advisor" not in agents:
            agents = agents + ["advisor"]
        if "grader" not in agents:
            agents = agents + ["grader"]
    elif mode == "learning":
        if "tutor" not in agents:
            agents = ["tutor"] + agents
        agents = [a for a in agents if a not in ("grader", "advisor")]
        if "planner" not in agents:
            agents = agents + ["planner"]
    return agents


def router_agent(state: WorkflowState) -> dict:
    conv = state.get("conversation_messages", [])
    mode = state.get("mode", "coursework")
    c = _classify(state.get("message", ""), conversation_messages=conv)
    pipeline = _adjust_pipeline_for_mode(c["agents"], mode, c["intent"])
    return {
        "intent": c["intent"],
        "intent_confidence": c["confidence"],
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
    for r in ws.get("results", [])[:3]:
        parts.append(f"- {r.get('title','')}: {r.get('snippet','')}")
    return "\n".join(parts)[:600]


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
    strategies = match_strategies(msg, rule_ids, max_results=2)

    # ────────────────────────────────────────────────────────────────
    # STATIC + CONDITIONAL: Parallel I/O tasks
    # ────────────────────────────────────────────────────────────────
    collected: dict[str, Any] = {}

    # -- STATIC: RAG (always, fast vector search) --
    def _task_rag():
        if _rag is None or _rag.case_count == 0:
            return {"rag_cases": [], "rag_context": ""}
        cases = _rag.retrieve(msg[:1000], top_k=3, category_filter=cat or None)
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
                + "实体type必须从以下选择: stakeholder, pain_point, solution, technology, "
                "market, competitor, resource, business_model, team, evidence\n\n"
                "示例:\n"
                '{"entities":[{"id":"e1","label":"6-12岁儿童","type":"stakeholder"},'
                '{"id":"e2","label":"编程学习枯燥","type":"pain_point"},'
                '{"id":"e3","label":"游戏化编程平台","type":"solution"}],'
                '"relationships":[{"source":"e1","target":"e2","relation":"面临"},'
                '{"source":"e3","target":"e2","relation":"解决"}],'
                '"structural_gaps":["缺少商业模式","缺少竞品分析"],'
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
            h = _hypergraph_service.insight(category=cat, rule_ids=rule_ids, limit=3)
            return {"hypergraph_insight": h}
        except Exception as exc:
            logger.warning("Hypergraph insight failed: %s", exc)
            return {"hypergraph_insight": {}}

    # ── Assemble parallel task list ──
    tasks: list[Callable] = [_task_rag]  # RAG: always

    # KG: for all project-related content (ensures section_scores consistency)
    is_project_intent = intent not in _FOCUSED_INTENTS
    run_kg = is_file or len(msg) > 30 or (is_project_intent and len(msg) > 12)
    if run_kg:
        tasks.append(_task_kg)

    # Web search: conditional on intent config + message keywords
    intent_spec = INTENTS.get(intent, {})
    msg_wants_web = any(w in msg for w in _WEB_SIGNAL_WORDS)
    need_web = msg_wants_web or intent_spec.get("need_web", False)
    if need_web:
        web_n = intent_spec.get("web_results", 3)
        if intent == "market_competitor":
            web_n = max(web_n, 5)
        tasks.append(lambda n=web_n: _task_web(n))

    # Hypergraph teaching: conditional on file or diagnostic intents
    if is_file or intent in ("project_diagnosis", "evidence_check", "competition_prep"):
        tasks.append(_task_hyper_teaching)

    logger.info(
        "gather[static+cond]: intent=%s tasks=%d (kg=%s web=%s)",
        intent, len(tasks), run_kg, need_web,
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
    # STATIC: Post-parallel — KG merge + Hypergraph student analysis
    #   Hypergraph analysis always runs when KG found entities.
    #   Neo4j merge is a side-effect (conditional on service availability).
    # ────────────────────────────────────────────────────────────────
    kg = collected.get("kg_analysis", _default_kg())
    if _graph_service and kg.get("entities"):
        pid = state.get("project_state", {}).get("project_id", "unknown")
        try:
            _graph_service.merge_student_entities(
                pid, kg["entities"], kg.get("relationships", [])
            )
        except Exception as exc:
            logger.warning("Neo4j merge failed: %s", exc)

    hyper_student: dict = {}
    if len(kg.get("entities", [])) > 0:
        try:
            hyper_student = _standalone_hypergraph_analysis(
                entities=kg.get("entities", []),
                relationships=kg.get("relationships", []),
                structural_gaps=kg.get("structural_gaps"),
            )
        except Exception as exc:
            logger.warning("Hypergraph student analysis failed: %s", exc)

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


def _coach_analyze(state: dict) -> dict:
    msg = state.get("message", "")
    mode = state.get("mode", "coursework")
    diag = state.get("diagnosis", {})
    rag_ctx = state.get("rag_context", "")
    kg = state.get("kg_analysis", {})
    ws = state.get("web_search_result", {})
    ws_ctx = _fmt_ws(ws)
    conv_ctx = _build_conv_ctx(state)
    hs = state.get("hypergraph_student", {})
    hs_ctx = _fmt_hyper_student(hs)

    mode_hint = {
        "coursework": "当前是课程辅导模式，侧重帮学生完成作业，注重逻辑完整性和方法论。",
        "competition": "当前是竞赛冲刺模式，以获奖为目标，标准要严格，侧重竞争力和评委视角。",
        "learning": "当前是个人学习模式，侧重启发式引导，多用类比和案例解释概念，鼓励探索。",
    }.get(mode, "")

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

    n_rules = len((diag.get("triggered_rules") or []))
    quality_ctx = ""
    if n_rules <= 2:
        quality_ctx = (
            "\n**项目评估提示：诊断引擎只触发了很少的风险规则，说明这个项目的基础逻辑比较完善。**\n"
            "请客观评价，先肯定做得好的地方，再给出提升性建议。"
            "不要为了显得专业而硬找问题。\n"
        )

    analysis = _llm.chat_text(
        system_prompt=(
            "你是一位有10年双创辅导经验的导师，正在为学生的项目做深度分析。\n"
            + (f"**模式**: {mode_hint}\n" if mode_hint else "")
            + quality_ctx
            + "你的分析结构必须是**先总后分**：\n"
            "1. 先用1-2句话总结你对整个项目的总体判断（方向对不对、核心逻辑通不通）\n"
            "2. 简要梳理项目的逻辑链路：用户是谁→他们的痛点→你的方案→如何变现→竞争壁垒\n"
            "3. 然后聚焦最关键的1-2个问题深入分析，引用学生原话来讨论\n"
            "4. 如果有参考案例，自然引用对比\n"
            "5. 给出具体的下一步行动\n"
            "6. 结合前面对话延伸，不重复已讲过的点\n"
            "用4-6段话输出，**深度远比广度重要**。"
        ),
        user_prompt=(
            f"学生说: {msg[:2000]}\n\n"
            + (f"对话上下文:\n{conv_ctx}\n\n" if conv_ctx else "")
            + f"诊断瓶颈: {diag.get('bottleneck','')}\n"
            + f"触发规则: {[r.get('name') for r in (diag.get('triggered_rules') or [])[:4] if isinstance(r,dict)]}\n"
            + f"KG洞察: {kg.get('insight','')}\n结构缺陷: {kg.get('structural_gaps',[])}\n"
            + f"维度评分: {kg.get('section_scores',{})}\n"
            + (f"超图跨维度分析:\n{hs_ctx}\n" if hs_ctx else "")
            + (f"参考案例:\n{rag_ctx[:800]}\n" if rag_ctx else "")
            + (f"联网搜索:\n{ws_ctx[:500]}\n" if ws_ctx else "")
            + (f"图谱关联: {neo4j_ctx}\n" if neo4j_ctx else "")
        ),
        temperature=0.4,
    )
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
            "6. 如果前面的教练分析已经指出某些问题，你聚焦补充而不重复\n"
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
        ),
        temperature=0.35,
    )
    return {
        "agent": "风险分析师",
        "analysis": analysis or "",
        "tools_used": ["diagnosis", "kg_analysis", "hypergraph_student"],
    }


def _advisor_analyze(state: dict) -> dict:
    msg = state.get("message", "")
    mode = state.get("mode", "coursework")
    rag_ctx = state.get("rag_context", "")
    diag = state.get("diagnosis", {})
    conv_ctx = _build_conv_ctx(state)
    coach_out = state.get("coach_output", {})

    comp_urgency = "竞赛冲刺模式——学生正在备赛，请以获奖为最高目标来分析。" if mode == "competition" else ""

    n_rules = len(diag.get("triggered_rules", []) or [])
    quality_hint = ""
    if n_rules <= 2:
        quality_hint = (
            "\n**注意：这个项目的规则诊断只触发了少量风险，说明逻辑较为完善。**\n"
            "不要硬凑问题。对于好项目，重点给出提升性建议（如何从85分提到95分），"
            "而不是当成问题项目来严厉批评。\n"
        )

    analysis = _llm.chat_text(
        system_prompt=(
            "你当过20+次互联网+/挑战杯的评审专家，非常了解评委的思维方式。\n"
            + (f"**{comp_urgency}**\n" if comp_urgency else "")
            + quality_hint
            + "你的分析必须：\n"
            "1. 模拟评委视角，给出2-3个最可能被问到的问题，以及应对策略"
            "（问题难度应匹配项目质量——好项目问深度问题，差项目问基础问题）\n"
            "2. 基于项目当前状态，评估竞赛准备度\n"
            "3. 给出路演/PPT的具体优化建议（具体的结构调整，不是泛泛的'注意逻辑'）\n"
            "4. 引用评审标准中的评分要点来说明为什么这些很重要\n"
            "5. 不要重复教练已指出的问题，补充竞赛特有的视角\n"
            "用3-5段话输出，实操性强。"
        ),
        user_prompt=(
            f"学生说: {msg[:1000]}\n模式: {mode}\n\n"
            + (f"对话上下文:\n{conv_ctx}\n\n" if conv_ctx else "")
            + (f"参考获奖案例:\n{rag_ctx[:500]}\n" if rag_ctx else "")
            + (f"诊断瓶颈: {diag.get('bottleneck','')}\n" if diag.get("bottleneck") else "")
            + (f"教练分析摘要: {str(coach_out.get('analysis',''))[:300]}\n" if coach_out.get("analysis") else "")
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
    mode = state.get("mode", "coursework")
    ws = state.get("web_search_result", {})
    ws_ctx = _fmt_ws(ws)
    rag_ctx = state.get("rag_context", "")
    conv_ctx = _build_conv_ctx(state)

    learning_extra = ""
    if mode == "learning":
        learning_extra = (
            "当前是**个人学习模式**，学生的目的是学习创业知识，不是交作业。\n"
            "请更详细地讲解概念，多用比喻和故事，增加趣味性。\n"
            "可以推荐相关的延伸阅读或学习资源。\n"
        )

    analysis = _llm.chat_text(
        system_prompt=(
            "你是大学创新创业课的教授，擅长用通俗的方式讲复杂的商业概念。\n"
            + (learning_extra if learning_extra else "")
            + "你的回答必须：\n"
            "1. 用一句话通俗定义概念（避免教科书式定义）\n"
            "2. 举1-2个真实的创业案例来解释（如果有搜索结果，引用具体数据和事实）\n"
            "3. 给学生一个本周就能做的练习任务（非常具体，可执行）\n"
            "4. 指出常见误区（学生最容易踩的坑）\n"
            "5. 如果对话中学生提到了自己的项目，把概念和他的项目关联起来解释\n"
            + ("6. 推荐1-2个延伸学习资源（书籍/文章/视频）\n" if mode == "learning" else "")
            + "用4-6段话输出，生动有趣。"
        ),
        user_prompt=(
            f"学生问: {msg[:1000]}\n\n"
            + (f"对话上下文:\n{conv_ctx}\n\n" if conv_ctx else "")
            + (f"联网搜索到的最新资料:\n{ws_ctx[:600]}\n" if ws_ctx else "")
            + (f"参考案例:\n{rag_ctx[:400]}\n" if rag_ctx else "")
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
    "tutor": "学习导师",
    "grader": "评分官",
    "planner": "行动规划师",
}


# ═══════════════════════════════════════════════════════════════════
#  Node 3: Hybrid Agent Selection (Static Rules + Dynamic Heuristics)
#           + Serial Execution
# ═══════════════════════════════════════════════════════════════════

_SCORING_SIGNALS = frozenset(["评分", "打分", "得分", "几分", "怎么评", "多少分", "分数"])

_AGENT_ORDER = ("coach", "analyst", "advisor", "tutor", "grader", "planner")


def _decide_agents(state: WorkflowState) -> list[str]:
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
    msg = state.get("message", "")
    is_file = "[上传文件:" in msg
    diag = state.get("diagnosis", {})
    kg = state.get("kg_analysis", {})
    rules = diag.get("triggered_rules", []) or []
    kg_entity_count = len(kg.get("entities", []))
    high_risk = sum(1 for r in rules if isinstance(r, dict) and r.get("severity") == "high")

    selected: set[str] = set()

    # ═══ STATIC RULES (guaranteed, non-negotiable) ═══

    if is_file:
        selected.update(("coach", "grader", "planner"))

    if mode == "competition" or intent == "competition_prep":
        selected.add("advisor")

    if any(w in msg for w in _SCORING_SIGNALS):
        selected.add("grader")

    # ═══ DYNAMIC HEURISTICS (data-driven) ═══

    # Coach: primary analyst — needs project substance
    if "coach" not in selected:
        if len(rules) > 0 or kg_entity_count >= 2:
            selected.add("coach")
        elif intent in ("project_diagnosis", "business_model", "evidence_check"):
            selected.add("coach")

    # Analyst: risk assessment — only when risks are real
    if intent == "pressure_test":
        selected.add("analyst")
    elif high_risk >= 1 or len(rules) >= 3:
        selected.add("analyst")
    elif intent == "evidence_check" and len(rules) >= 2:
        selected.add("analyst")

    # Tutor: learning guidance — in learning mode for complex contexts
    if mode == "learning" and intent not in _FOCUSED_INTENTS:
        selected.add("tutor")

    # Planner: action items — only when there's enough context to plan
    if "planner" not in selected:
        has_planning_context = (
            kg_entity_count >= 3
            and intent in ("project_diagnosis", "evidence_check", "business_model")
        ) or (len(rules) >= 2 and "coach" in selected)
        if has_planning_context:
            selected.add("planner")

    # ═══ Return in canonical execution order ═══
    return [a for a in _AGENT_ORDER if a in selected]


def run_role_agents_node(state: WorkflowState) -> dict:
    intent = state.get("intent", "general_chat")

    # ── PATH A: Focused intents → orchestrator handles alone ──
    if intent in _FOCUSED_INTENTS and "[上传文件:" not in state.get("message", ""):
        logger.info("intent '%s' → focused mode, no agents", intent)
        return {
            "agents_called": [f"[聚焦模式: {intent}]"],
            "nodes_visited": ["role_agents"],
        }

    # ── PATH B: Static + dynamic selection → serial execution ──
    agents_to_run = _decide_agents(state)

    if not agents_to_run:
        logger.info("_decide_agents returned empty → orchestrator-only")
        return {
            "agents_called": ["[数据不足，直接回复]"],
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
        "你是一位有10年双创辅导经验的资深课程导师。"
        "你的目标是帮助学生完成课程作业，侧重逻辑完整性、可行性分析和创新点。"
        "语气耐心温和，像老师带学生做毕设。"
    ),
    "competition": (
        "你是一位资深创业竞赛教练，对互联网+、挑战杯等赛事非常熟悉。"
        "你的目标是帮助学生冲刺获奖，侧重评委视角、路演打磨和竞争力提升。"
        "语气更有冲劲和紧迫感，像教练赛前冲刺指导。"
    ),
    "learning": (
        "你是一位善于启发式教学的创新创业导师。"
        "你的目标是帮助学生理解创业思维和方法论，不急于评判项目好坏。"
        "侧重概念讲解、案例类比、启发式提问。语气鼓励探索，像一位引路人。"
    ),
}


# ── Intent-specific prompts for focused (single-call) mode ──
_FOCUSED_PROMPTS: dict[str, str] = {
    "market_competitor": (
        "学生在问竞品/同类产品/市场情况。你的任务：\n"
        "1. 基于搜索结果列出3-5个真实的同类产品/竞品，每个用1-2句介绍核心卖点\n"
        "2. 做一个对比表格（产品名、核心功能、目标用户、定价、优劣势）\n"
        "3. 分析学生项目和这些竞品的差异化在哪里\n"
        "4. 推荐2-3个最值得学习的产品，具体说明学什么\n"
        "5. 如果搜索结果不够，基于你的知识补充\n"
        "用600-1000字回复。必须有具体产品名和对比表格。"
    ),
    "learning_concept": (
        "学生想学习一个概念或方法论。你的任务：\n"
        "1. 用一句话通俗定义这个概念（不要教科书式定义）\n"
        "2. 举2-3个真实的创业案例来解释（具体公司名、做了什么、结果如何）\n"
        "3. 如果搜索结果有最新信息，引用具体数据和事实\n"
        "4. 给学生一个本周就能做的练习任务（非常具体，可执行）\n"
        "5. 指出学生最容易踩的坑\n"
        "6. 如果学生的项目上下文已知，把概念和他的项目关联起来解释\n"
        "用500-900字回复。生动有趣，多用类比。"
    ),
    "idea_brainstorm": (
        "学生想要创业方向建议。你的任务：\n"
        "1. 基于搜索到的趋势和学生的兴趣/背景，给出3-5个具体的方向\n"
        "2. 每个方向说清楚：目标用户是谁、解决什么痛点、变现方式\n"
        "3. 简要分析每个方向的难度和资源要求\n"
        "4. 推荐一个最适合学生现状的方向，说明理由\n"
        "5. 给出这个方向的第一步行动\n"
        "用500-800字回复。具体、可行、有启发性。"
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
            analysis_parts.append(str(out["analysis"]))

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
            length_guide = "1500-3000字。逐段分析文件内容，引用原文，对比案例，给出具体修改建议。"
        elif n_analyses >= 3:
            length_guide = "1200-2500字。充分整合所有分析维度，每个重要发现都要展开讨论。"
        elif n_analyses >= 2:
            length_guide = "800-1800字。深入分析关键问题，引用案例和证据，不遗漏重要发现。"
        elif msg_len > 200:
            length_guide = "600-1200字。针对学生具体内容深入展开。"
        else:
            length_guide = "400-800字。聚焦问题给出有深度的建议。"

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
                "- 每个发现都要结合学生的具体内容深入展开，给出数据、案例或逻辑推演\n"
                "- 宁可回复长一点内容扎实，也不要为了简短而丢掉好的分析洞察\n\n"
                "## 回复逻辑结构\n"
                "1. **总览**（1-2句）：概括你对项目的整体判断\n"
                "2. **逻辑链路**：用户是谁→痛点→方案→变现→壁垒，哪些通哪些断\n"
                "3. **逐一展开核心问题**：将分析中发现的每个重要问题都展开讨论，"
                "引用学生原话，给具体例子或数据说明为什么这是问题、怎么改\n"
                "4. **追问**：提出2-3个有深度的苏格拉底式问题引导学生思考\n\n"
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

        if focused_prompt:
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
        length_guide = "1200-2500字"
    elif intent == "general_chat" or msg_len < 20:
        length_guide = "100-250字"
    elif n_analyses >= 3:
        length_guide = "900-1500字"
    else:
        length_guide = "500-900字"

    analyses_ctx = "\n\n---\n\n".join(analysis_parts)
    persona = _MODE_PERSONA.get(mode, _MODE_PERSONA["coursework"])

    if not _llm.enabled:
        yield "你好！告诉我你的项目想法，我来帮你诊断和分析。"
        return

    if not analyses_ctx:
        # ── Focused intent path (no agents ran) ──
        gathered = _build_gathered_context(state)
        focused_prompt = _FOCUSED_PROMPTS.get(intent, "")
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
        "3. 聚焦核心问题（最多2-3个深入分析）\n"
        "4. 具体行动建议\n"
        "5. 引导性追问\n\n"
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
