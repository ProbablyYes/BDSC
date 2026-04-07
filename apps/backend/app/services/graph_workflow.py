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
    competition_type: str
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
    rag_enrichment_insight: str
    web_search_result: dict
    hypergraph_insight: dict
    hypergraph_student: dict
    hyper_consistency_issues: list
    critic: dict
    challenge_strategies: list
    pressure_test_trace: dict
    competition: dict
    learning: dict
    kb_utilization: dict
    needs_clarification: bool
    clarification_reason: str
    clarification_questions: list[str]
    clarification_missing: list[str]

    # ── V2 dimension-driven fields ──
    dim_activations: dict          # {dim_key: {score, activated, components}}
    dim_results: dict              # {dim_key: {value, confidence, evidence, ...}}
    exploration_state: dict        # {phase, filled_slots, missing_slots, ...}
    execution_trace: dict          # full V2 trace for debug panel
    reply_strategy: str            # selected reply strategy key
    web_facts: list                # extracted facts from web search

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
    "funding_investment": {
        "keywords": ["融资", "投资", "估值", "股权", "BP", "天使轮", "种子轮",
                      "风投", "VC", "商业计划书", "投资人", "股份",
                      "融资计划", "拉投资", "找投资", "估值方法"],
        "desc": "学生咨询融资、投资、估值、股权相关",
        "agents": ["coach"],
        "need_web": True, "web_results": 3,
        "focused": True,
    },
    "company_operations": {
        "keywords": ["开公司", "注册公司", "法务", "股权架构", "税务",
                      "工商注册", "营业执照", "合伙协议", "公司章程",
                      "知识产权", "专利", "商标", "法律风险"],
        "desc": "学生咨询公司注册、法务、股权架构等运营问题",
        "agents": ["tutor"],
        "need_web": True, "web_results": 3,
        "focused": True,
    },
    "startup_execution": {
        "keywords": ["招人", "团队管理", "增长", "上市", "IPO", "并购",
                      "获客", "留存", "用户增长", "运营", "扩张",
                      "规模化", "团队搭建", "合伙人"],
        "desc": "学生咨询创业执行：团队、增长、规模化",
        "agents": ["coach"],
        "need_web": True, "web_results": 3,
        "focused": True,
    },
    "out_of_scope": {
        "keywords": ["写代码", "编程", "python", "java", "c++", "javascript",
                      "天气", "新闻", "八卦", "娱乐",
                      "翻译", "数学题", "作文", "考试答案", "帮我写"],
        "desc": "非创业/项目相关的超范围问题",
        "agents": [],
        "need_web": False,
        "focused": True,
    },
}

_FOCUSED_INTENTS = frozenset(k for k, v in INTENTS.items() if v.get("focused"))

# ═══════════════════════════════════════════════════════════════════
#  Intent × Complexity → base agent set (declarative matrix)
# ═══════════════════════════════════════════════════════════════════

AGENT_MATRIX: dict[str, dict[str, list[str]]] = {
    "learning_concept": {
        "simple": ["tutor"],
        "medium": ["tutor", "coach"],
        "complex": ["tutor", "coach", "analyst"],
    },
    "project_diagnosis": {
        "simple": ["coach"],
        "medium": ["coach", "analyst"],
        "complex": ["coach", "analyst", "tutor", "planner"],
    },
    "business_model": {
        "simple": ["tutor"],
        "medium": ["coach", "tutor"],
        "complex": ["coach", "analyst", "tutor", "planner"],
    },
    "evidence_check": {
        "simple": ["analyst"],
        "medium": ["analyst", "coach"],
        "complex": ["analyst", "coach", "tutor"],
    },
    "market_competitor": {
        "simple": ["tutor"],
        "medium": ["tutor", "analyst"],
        "complex": ["tutor", "analyst", "coach"],
    },
    "competition_prep": {
        "simple": ["advisor"],
        "medium": ["advisor", "coach"],
        "complex": ["advisor", "coach", "analyst", "grader"],
    },
    "pressure_test": {
        "simple": ["analyst"],
        "medium": ["analyst", "coach"],
        "complex": ["analyst", "coach", "advisor"],
    },
    "idea_brainstorm": {
        "simple": ["tutor"],
        "medium": ["tutor", "coach"],
        "complex": ["tutor", "coach", "analyst"],
    },
    "general_chat": {
        "simple": ["coach"],
        "medium": ["coach"],
        "complex": ["coach"],
    },
    "funding_investment": {
        "simple": ["coach"],
        "medium": ["coach", "tutor"],
        "complex": ["coach", "tutor", "analyst", "planner"],
    },
    "company_operations": {
        "simple": ["tutor"],
        "medium": ["tutor", "coach"],
        "complex": ["tutor", "coach", "planner"],
    },
    "startup_execution": {
        "simple": ["coach"],
        "medium": ["coach", "planner"],
        "complex": ["coach", "planner", "analyst", "tutor"],
    },
    "out_of_scope": {
        "simple": [],
        "medium": [],
        "complex": [],
    },
}


# ═══════════════════════════════════════════════════════════════════
#  V2: Dimension-Driven Analysis Framework
# ═══════════════════════════════════════════════════════════════════

ANALYSIS_DIMENSIONS: dict[str, dict] = {
    "status_judgment":     {"label": "项目状态判断",       "required": False, "desc": "判断项目当前处于什么阶段，整体逻辑是否通顺"},
    "core_bottleneck":     {"label": "核心瓶颈识别",       "required": False, "desc": "找到当前最制约项目推进的一到两个瓶颈"},
    "structural_cause":    {"label": "结构层原因",         "required": False, "desc": "解释表层问题背后共同指向的深层结构性断点"},
    "counter_intuitive":   {"label": "反直觉洞察/挑战",    "required": False, "desc": "指出学生可能忽略的盲区、过于乐观的假设、行业反例"},
    "method_bridge":       {"label": "方法论桥接",         "required": False, "desc": "讲清楚一个概念/方法论，并桥接回学生项目"},
    "teacher_criteria":    {"label": "评委/老师判断标准",   "required": False, "desc": "从评审者视角分析项目的优劣势和得分区间"},
    "external_reference":  {"label": "外部案例/竞品/数据",  "required": False, "desc": "引用真实竞品、行业数据、成功/失败案例做对比"},
    "strategy_directions": {"label": "粗粒度策略方向",     "required": False, "desc": "给出可选打法、取舍和切口，不只有唯一答案"},
    "action_plan":         {"label": "细粒度行动方案",     "required": False, "desc": "拆出本周最该做的1-3件事和验收标准"},
    "probing_questions":   {"label": "启发式追问",         "required": True,  "desc": "用苏格拉底式追问帮学生深入思考"},
}

DIM_ACTIVATION_THRESHOLD = 0.5

DIM_OWNERSHIP: dict[str, dict] = {
    "status_judgment":     {"writer": "coach",        "challengers": []},
    "core_bottleneck":     {"writer": "coach",        "challengers": ["analyst"]},
    "structural_cause":    {"writer": "analyst",      "challengers": []},
    "counter_intuitive":   {"writer": "analyst",      "challengers": []},
    "method_bridge":       {"writer": "tutor",        "challengers": []},
    "teacher_criteria":    {"writer": "advisor",      "challengers": ["grader"]},
    "external_reference":  {"writer": "advisor",      "challengers": ["tutor"]},
    "strategy_directions": {"writer": "coach",        "challengers": []},
    "action_plan":         {"writer": "planner",      "challengers": []},
    "probing_questions":   {"writer": "coach",        "challengers": []},
}

def _derive_agent_capabilities() -> dict[str, dict[str, list[str]]]:
    caps: dict[str, dict[str, list[str]]] = {}
    for dim, ownership in DIM_OWNERSHIP.items():
        w = ownership["writer"]
        if w != "orchestrator":
            caps.setdefault(w, {"writes": [], "challenges": []})
            caps[w]["writes"].append(dim)
        for c in ownership.get("challengers", []):
            caps.setdefault(c, {"writes": [], "challenges": []})
            caps[c]["challenges"].append(dim)
    return caps

AGENT_CAPABILITIES: dict[str, dict[str, list[str]]] = _derive_agent_capabilities()

DIM_DEPENDENCIES: dict[str, Any] = {
    "status_judgment":     lambda ctx: [],
    "core_bottleneck":     lambda ctx: [],
    "method_bridge":       lambda ctx: [],
    "external_reference":  lambda ctx: [],
    "counter_intuitive":   lambda ctx: [("core_bottleneck", 1.0)],
    "structural_cause":    lambda ctx: [("core_bottleneck", 1.0)],
    "teacher_criteria":    lambda ctx: [
        ("status_judgment", 0.8),
        ("external_reference", 0.5) if ctx.get("mode") == "competition" else None,
    ],
    "strategy_directions": lambda ctx: [
        ("core_bottleneck", 1.0),
        ("structural_cause", 0.7) if ctx.get("complexity", 0) >= 3 else None,
    ],
    "action_plan":         lambda ctx: [
        ("core_bottleneck", 1.0),
        ("strategy_directions", 0.9),
    ],
    "probing_questions":   lambda ctx: [],
}

REPLY_STRATEGIES: dict[str, dict] = {
    "comprehensive": {"desc": "全面深度分析+多维洞察", "length": "2500-4500字", "tone": "深度透彻，像导师面对面深聊"},
    "deep_dive":     {"desc": "深度单点分析",         "length": "1200-2500字", "tone": "深入剖析"},
    "panorama":      {"desc": "全面多维分析",         "length": "2000-3800字", "tone": "全面覆盖"},
    "progressive":   {"desc": "初步判断+核心追问",    "length": "400-800字",   "tone": "引导探索"},
    "teach_concept": {"desc": "概念讲解+项目应用",    "length": "700-1200字",  "tone": "教学耐心"},
    "challenge":     {"desc": "苏格拉底式追问",       "length": "800-1600字",  "tone": "犀利但建设性"},
    "compare":       {"desc": "结构化对比",           "length": "1000-2000字", "tone": "客观分析"},
    "casual":        {"desc": "自然闲聊",             "length": "100-350字",   "tone": "轻松有温度"},
}

CHALLENGER_SYSTEM_PROMPT = (
    "你是严格的逻辑审计员。你收到了一位分析师对某个维度的结论。\n"
    "你的唯一任务是找出这个结论中可能错误、不完整或过于乐观的地方。\n\n"
    "你必须输出JSON，字段：\n"
    "- weakest_point: 该结论最站不住脚的一个点（即使你总体认同，也必须找出一个，不少于30字）\n"
    "- alternative_explanation: 一种不同的判断或解释\n"
    "- missing_consideration: 该结论忽略了什么\n"
    "- verdict: 'challenge' 或 'endorse'\n"
    "- confidence: 0-1\n\n"
    "规则：\n"
    "- 只有当你找不到任何实质性漏洞时才允许 verdict='endorse'\n"
    "- verdict='endorse' 要求 confidence >= 0.8"
)

ORCHESTRATOR_CONSTRAINTS_PROMPT = (
    "你是编排器。你的职责是把已有的分析结论组织成自然流畅的对话。\n\n"
    "## 绝对禁止\n"
    "- 不能引入维度结论中不存在的新事实、新判断或新数据\n"
    "- 不能推翻任何 Writer 的主结论\n"
    "- 不能提到 Agent、分析师、系统等内部角色\n"
    "- 不能编造竞品名称、市场数字或行业事实\n\n"
    "## 你可以做的\n"
    "- 决定段落顺序和详略比例\n"
    "- 调整措辞风格（基于 reply_strategy）\n"
    "- 使用 Markdown 排版（标题/表格/引用/加粗）\n"
    "- 如果某维度标注 contested=true，呈现双方观点而非自行裁决\n"
    "- 如果某维度 confidence < 0.6，在措辞上体现不确定性\n"
    "- 用第一人称、像导师面对面聊天的语气\n\n"
    "## 输出要求\n"
    "- reply_text: 给学生看的自然语言回复\n"
    "- dim_usage: dict，每个维度是否被引用（可审计）"
)

ANTI_HALLUCINATION_HEADER = (
    "【事实准确性规则】\n"
    "- 引用竞品/公司名时，只引用联网搜索结果或RAG知识库中实际存在的，不要虚构\n"
    "- 引用数字/市场规模时，必须标注来源；没有来源就不要给具体数字\n"
    "- 如果你对某个行业/领域不确定，明确说'这部分我不太确定'，而非编造\n"
    "- 不要为了显得深刻而捏造案例或数据\n\n"
)

def _complexity_tier(complexity: int, intent_shape: str) -> str:
    if intent_shape == "mixed" and complexity >= 3:
        return "complex"
    if complexity >= 4:
        return "complex"
    if complexity >= 2 or intent_shape == "mixed":
        return "medium"
    return "simple"

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
_RICH_CONTENT_SIGNALS = frozenset([
    "商业模式", "盈利", "竞争", "壁垒", "用户画像", "痛点", "场景",
    "技术栈", "架构", "区块链", "AI", "机器学习", "深度学习",
    "数据", "算法", "平台", "生态", "赛道", "市场", "融资",
    "变现", "获客", "留存", "转化", "增长", "规模化",
    "监管", "合规", "门槛", "替代方案", "竞品", "差异化",
    "用户需求", "需求验证", "MVP", "原型", "迭代", "反馈",
])

_DISCOVERY_INTENTS = frozenset([
    "idea_brainstorm", "project_diagnosis", "business_model", "competition_prep",
])

_VAGUE_PROJECT_SIGNALS = frozenset([
    "有个想法", "一个想法", "大概想做", "还没想好", "还不太确定",
    "先聊聊", "还在想", "可能做", "初步想法", "暂时没有", "还没明确","模糊的想法"
])

_CONCRETE_PROJECT_SIGNALS = frozenset([
    "项目叫", "我们做", "现在做了", "目前做了", "已经做了", "想解决",
    "面向", "服务", "用户", "场景", "流程", "痛点", "问题", "方案",
    "系统", "平台", "功能", "验证", "调研", "访谈", "合作社", "商家",
    "农民", "医院", "学校", "企业", "社区", "市场", "收费", "盈利",
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
    "没有好的", "没有渠道", "找不到", "接不到", "不好找", "不信任",
    "不靠谱", "效率低", "门槛高", "赚不到", "不匹配", "信息不对称",
    "缺乏", "浪费", "体验差", "不透明", "没保障",
])


def _signal_hit_count(text: str, signals: set[str] | frozenset[str]) -> int:
    content = str(text or "")
    return sum(1 for sig in signals if sig and sig in content)


def _assess_project_maturity_signals(
    message: str,
    exploration_state: dict | None,
    accumulated_entities: list[dict] | None,
    conversation_messages: list | None,
    intent_shape: str = "single",
) -> dict[str, Any]:
    text = str(message or "").strip()
    exp = exploration_state or {}
    entities = accumulated_entities or []
    conv = conversation_messages or []
    n_chars = len(text)
    n_entities = len(entities)
    n_slots = int(exp.get("n_filled", 0) or 0)
    complexity = _message_complexity(text, conv)
    vague_hits = _signal_hit_count(text, _VAGUE_PROJECT_SIGNALS)
    concrete_hits = _signal_hit_count(text, _CONCRETE_PROJECT_SIGNALS)
    followup_hits = _signal_hit_count(text, _FOLLOW_UP_SIGNALS)

    exploring_score = 0
    mature_score = 0

    if vague_hits:
        exploring_score += 3
    if n_chars <= 120:
        exploring_score += 2
    elif n_chars <= 220:
        exploring_score += 1
    if n_slots <= 1:
        exploring_score += 2
    elif n_slots <= 2:
        exploring_score += 1
    if complexity <= 1:
        exploring_score += 1
    if followup_hits and n_chars <= 180:
        exploring_score += 1

    if n_entities >= 5:
        mature_score += 2
    elif n_entities >= 3:
        mature_score += 1
    if n_slots >= 4:
        mature_score += 3
    elif n_slots >= 3:
        mature_score += 2
    elif n_slots >= 2:
        mature_score += 1
    if complexity >= 4:
        mature_score += 2
    elif complexity >= 2:
        mature_score += 1
    if n_chars >= 280:
        mature_score += 2
    elif n_chars >= 180:
        mature_score += 1
    if concrete_hits >= 5:
        mature_score += 2
    elif concrete_hits >= 3:
        mature_score += 1
    if intent_shape == "mixed":
        mature_score += 1

    label = "exploring" if exploring_score >= mature_score else "mature"
    reasons: list[str] = []
    if label == "exploring":
        if vague_hits:
            reasons.append("语气仍偏探索/试探")
        if n_chars <= 220:
            reasons.append("本轮信息量较少")
        if n_slots <= 2:
            reasons.append("关键项目槽位仍未补全")
    else:
        if n_slots >= 3:
            reasons.append("项目关键信息已经较完整")
        if concrete_hits >= 3:
            reasons.append("已进入具体场景/方案描述")
        if n_chars >= 180 or complexity >= 2:
            reasons.append("表达展开度已支持更深入分析")
        if n_entities >= 5:
            reasons.append("跨轮实体积累较充分")

    return {
        "label": label,
        "reason": "；".join(reasons[:3]) or ("偏探索交流" if label == "exploring" else "信息较完整"),
        "exploring_score": exploring_score,
        "mature_score": mature_score,
        "char_count": n_chars,
        "slot_count": n_slots,
        "entity_count": n_entities,
        "complexity": complexity,
        "vague_hits": vague_hits,
        "concrete_hits": concrete_hits,
    }


def _normalize_intent_shape(shape: Any, default: str = "single") -> str:
    value = str(shape or default).strip().lower()
    return value if value in {"single", "mixed"} else default


def _assess_project_maturity(
    message: str,
    exploration_state: dict | None,
    entity_count: int,
    conversation_messages: list | None = None,
    intent_shape: str = "single",
    is_file: bool = False,
) -> dict[str, Any]:
    text = (message or "").strip()
    exp = exploration_state or {}
    conv = conversation_messages or []
    signal_info = _assess_project_maturity_signals(
        message=message,
        exploration_state=exploration_state,
        accumulated_entities=[{}] * max(entity_count, 0),
        conversation_messages=conversation_messages,
        intent_shape=intent_shape,
    )
    n_filled = int(exp.get("n_filled", 0) or 0)
    char_len = len(text)
    complexity = _message_complexity(text, conv)
    vague_hits = int(signal_info.get("vague_hits", 0) or 0)
    concrete_hits = int(signal_info.get("concrete_hits", 0) or 0)
    label = str(signal_info.get("label") or "exploring")

    if re.search(r"(项目|产品|方案|系统|平台).{0,10}(叫|是|做)", text):
        concrete_hits += 1
    if re.search(r"(用户|面向|服务).{0,18}(学生|老师|农民|企业|商家|家长|医院|合作社|村民)", text):
        concrete_hits += 1
    if re.search(r"(痛点|问题|困难|低效|成本|效率|场景|流程|环节|替代方案)", text):
        concrete_hits += 1

    score = 0
    if is_file:
        score += 4
    if char_len >= 220:
        score += 2
    elif char_len >= 120:
        score += 1
    if intent_shape == "mixed":
        score += 1
    score += min(n_filled, 4)
    score += min(entity_count // 2, 3)
    score += min(concrete_hits, 3)
    score -= min(vague_hits, 2)
    if complexity >= 3:
        score += 1
    if char_len < 80 and n_filled <= 1:
        score -= 1
    if label == "mature":
        score += 1

    phase = str(exp.get("phase") or "")
    maturity = "mature" if (
        label == "mature"
        or score >= 6
        or (phase in ("validation", "full_analysis") and score >= 5)
        or (n_filled >= 3 and char_len >= 120)
    ) else "exploring"

    return {
        "project_maturity": maturity,
        "readiness_score": score,
        "char_len": char_len,
        "filled_slots": n_filled,
        "entity_count": entity_count,
        "vague_hits": vague_hits,
        "concrete_hits": concrete_hits,
        "history_turns": len(conv),
        "complexity": complexity,
        "maturity_reason": str(signal_info.get("reason") or ""),
        "exploring_score": signal_info.get("exploring_score", 0),
        "mature_score": signal_info.get("mature_score", 0),
    }


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
    if len(text) >= 400:
        score += 1
    if text.count("?") + text.count("？") >= 2:
        score += 1
    if text.count("\n") >= 2:
        score += 1
    if any(sig in text for sig in _COMPLEX_QUERY_SIGNALS):
        score += 1
    rich_hits = sum(1 for sig in _RICH_CONTENT_SIGNALS if sig in text)
    if rich_hits >= 2:
        score += 1
    if rich_hits >= 5:
        score += 1
    if "[上传文件:" in text:
        score += 2
    if conv and _infer_prev_intent(conv):
        score += 1
    return score


def _should_use_focused_mode(state: WorkflowState) -> bool:
    """Only general_chat uses focused mode; everything else goes through multi-agent."""
    intent = state.get("intent", "general_chat")
    msg = state.get("message", "")
    if "[上传文件:" in msg:
        return False
    return intent == "general_chat"


def _should_shallow_gather(state: WorkflowState) -> bool:
    """Only trigger shallow gather for truly vague FIRST messages with no context."""
    intent = state.get("intent", "general_chat")
    intent_shape = _normalize_intent_shape(state.get("intent_shape", "single"))
    msg = state.get("message", "")
    conv = state.get("conversation_messages", [])
    if "[上传文件:" in msg or intent not in _DISCOVERY_INTENTS:
        return False
    if intent == "learning_concept":
        return False
    if _is_generic_learning_question(msg) or _is_coursework_professional_question(msg):
        return False
    if any(sig in msg for sig in _ADVICE_SEEKING_SIGNALS):
        return False
    if intent_shape == "mixed":
        return False
    if len(msg) >= 180:
        return False
    if conv:
        return False
    has_vague = any(sig in msg for sig in _VAGUE_PROJECT_SIGNALS)
    is_very_short = len(msg) < 60 and not any(sig in msg for sig in _SOLUTION_SLOT_HINTS)
    return has_vague and is_very_short


_ADVICE_SEEKING_SIGNALS = frozenset([
    "你觉得怎么样", "你觉得", "帮我看看", "怎么样", "可行吗", "有没有问题",
    "第一步", "应该干什么", "应该做什么", "先做什么", "怎么做", "怎么推进",
    "怎么改", "能不能做", "有戏吗", "靠谱吗", "你怎么看", "帮我分析",
])

_BUSINESS_SLOT_HINTS = frozenset([
    "盈利", "变现", "收费", "商业模式", "成本", "收入", "渠道",
    "赚钱", "抽成", "佣金", "会员", "订阅", "广告", "付费",
    "定价", "客单价", "毛利", "营收", "接单", "副业",
])

# V2: Exploration slots/phases (placed here because they reference the hint frozensets above)
EXPLORATION_SLOTS: dict[str, dict] = {
    "target_user":    {"label": "目标用户", "hints": _USER_SLOT_HINTS},
    "pain_point":     {"label": "核心痛点", "hints": _PAIN_SLOT_HINTS},
    "solution":       {"label": "解决方案", "hints": _SOLUTION_SLOT_HINTS},
    "business_model": {"label": "商业模式", "hints": _BUSINESS_SLOT_HINTS},
    "competition":    {"label": "竞争格局", "hints": frozenset(["竞品", "对手", "替代", "类似", "同类"])},
}

EXPLORATION_PHASES: dict[str, dict] = {
    "direction":     {"min_slots": 0, "max_slots": 1, "reply_strategy": "progressive"},
    "convergence":   {"min_slots": 2, "max_slots": 3, "reply_strategy": "progressive"},
    "validation":    {"min_slots": 3, "max_slots": 4, "reply_strategy": "deep_dive"},
    "full_analysis": {"min_slots": 4, "max_slots": 5, "reply_strategy": None},
}


# ═══════════════════════════════════════════════════════════════════
#  V2: Dimension Activation Engine
# ═══════════════════════════════════════════════════════════════════

_DIM_RELEVANCE_MAP: dict[str, dict[str, float]] = {
    "status_judgment":     {"project_diagnosis": 0.95, "evidence_check": 0.7, "business_model": 0.7, "competition_prep": 0.6, "pressure_test": 0.5, "idea_brainstorm": 0.3, "learning_concept": 0.1, "market_competitor": 0.2, "general_chat": 0.0},
    "core_bottleneck":     {"project_diagnosis": 0.95, "evidence_check": 0.8, "business_model": 0.8, "pressure_test": 0.7, "competition_prep": 0.6, "idea_brainstorm": 0.3, "learning_concept": 0.1, "market_competitor": 0.2, "general_chat": 0.0},
    "structural_cause":    {"project_diagnosis": 0.8,  "evidence_check": 0.6, "business_model": 0.6, "pressure_test": 0.7, "competition_prep": 0.5, "idea_brainstorm": 0.1, "learning_concept": 0.05, "market_competitor": 0.1, "general_chat": 0.0},
    "counter_intuitive":   {"project_diagnosis": 0.5,  "pressure_test": 0.9, "business_model": 0.5, "evidence_check": 0.4, "competition_prep": 0.3, "idea_brainstorm": 0.3, "learning_concept": 0.1, "market_competitor": 0.2, "general_chat": 0.0},
    "method_bridge":       {"learning_concept": 0.95, "project_diagnosis": 0.15, "business_model": 0.4, "evidence_check": 0.3, "idea_brainstorm": 0.2, "competition_prep": 0.1, "pressure_test": 0.1, "market_competitor": 0.1, "general_chat": 0.0},
    "teacher_criteria":    {"competition_prep": 0.95, "project_diagnosis": 0.4, "evidence_check": 0.3, "business_model": 0.2, "pressure_test": 0.2, "idea_brainstorm": 0.05, "learning_concept": 0.05, "market_competitor": 0.1, "general_chat": 0.0},
    "external_reference":  {"market_competitor": 0.95, "competition_prep": 0.6, "project_diagnosis": 0.4, "business_model": 0.5, "idea_brainstorm": 0.5, "evidence_check": 0.3, "pressure_test": 0.3, "learning_concept": 0.2, "general_chat": 0.0},
    "strategy_directions": {"project_diagnosis": 0.7,  "business_model": 0.7, "idea_brainstorm": 0.6, "evidence_check": 0.5, "competition_prep": 0.5, "pressure_test": 0.4, "learning_concept": 0.1, "market_competitor": 0.2, "general_chat": 0.0},
    "action_plan":         {"project_diagnosis": 0.5,  "business_model": 0.4, "evidence_check": 0.5, "competition_prep": 0.6, "idea_brainstorm": 0.3, "pressure_test": 0.2, "learning_concept": 0.05, "market_competitor": 0.1, "general_chat": 0.0},
    "probing_questions":   {"project_diagnosis": 0.9,  "business_model": 0.8, "evidence_check": 0.8, "pressure_test": 0.8, "competition_prep": 0.7, "idea_brainstorm": 0.7, "learning_concept": 0.5, "market_competitor": 0.4, "general_chat": 0.1},
}

_OVER_OPTIMISTIC_SIGNALS = frozenset([
    "没有竞争对手", "独一无二", "肯定能", "一定会", "绝对", "所有人都需要",
    "市场很大", "没人做过", "蓝海", "全网第一", "100%", "必赢", "刚需",
])


def _dim_relevance(dim: str, intent: str, message: str, mode: str) -> float:
    base = _DIM_RELEVANCE_MAP.get(dim, {}).get(intent, 0.3)
    if mode == "competition" and dim == "teacher_criteria":
        base = max(base, 0.7)
    if mode == "learning" and dim == "method_bridge":
        base = max(base, 0.5)
    if "[上传文件:" in message:
        if dim in ("status_judgment", "core_bottleneck", "structural_cause"):
            base = max(base, 0.8)
    return min(base, 1.0)


def _dim_uncertainty(dim: str, message: str) -> float:
    text = (message or "").strip()
    if dim == "counter_intuitive":
        if any(sig in text for sig in _OVER_OPTIMISTIC_SIGNALS):
            return 0.9
        return 0.4
    if dim == "core_bottleneck":
        return 0.8 if len(text) < 120 else 0.5
    if dim == "structural_cause":
        return 0.6
    if dim == "method_bridge":
        return 0.7 if any(w in text for w in ("什么是", "怎么做", "教我", "不懂", "不理解")) else 0.3
    if dim == "external_reference":
        return 0.7 if any(w in text for w in ("竞品", "类似", "对标", "市面上", "别人")) else 0.4
    return 0.5


def _dim_impact(dim: str, intent: str, mode: str, complexity: int) -> float:
    if dim in ("status_judgment", "core_bottleneck", "probing_questions"):
        return 0.9
    if dim == "teacher_criteria":
        return 0.9 if mode == "competition" else 0.3
    if dim == "action_plan":
        return 0.7 if complexity >= 3 else 0.35
    if dim == "structural_cause":
        return 0.8 if complexity >= 3 else 0.45
    if dim == "strategy_directions":
        return 0.7
    if dim == "method_bridge":
        return 0.85 if intent == "learning_concept" else 0.3
    if dim == "counter_intuitive":
        return 0.65
    if dim == "external_reference":
        return 0.7 if intent in ("market_competitor", "competition_prep") else 0.45
    return 0.5


def _compute_all_dim_activations(
    intent: str, message: str, mode: str, complexity: int,
) -> dict[str, dict]:
    activations: dict[str, dict] = {}
    for dim in ANALYSIS_DIMENSIONS:
        rel = _dim_relevance(dim, intent, message, mode)
        unc = _dim_uncertainty(dim, message)
        imp = _dim_impact(dim, intent, mode, complexity)
        score = rel * unc * imp
        activations[dim] = {
            "score": round(score, 3),
            "activated": score > DIM_ACTIVATION_THRESHOLD or ANALYSIS_DIMENSIONS[dim].get("required", False),
            "components": {"relevance": round(rel, 2), "uncertainty": round(unc, 2), "impact": round(imp, 2)},
        }
    return activations


def _refine_dim_activations(
    activations: dict[str, dict],
    diag: dict, kg: dict,
    rag_cases: list | None,
    hyper_student: dict | None,
) -> dict[str, dict]:
    rules = diag.get("triggered_rules", []) or []
    high_risk_count = sum(1 for r in rules if isinstance(r, dict) and r.get("severity") == "high")

    if high_risk_count >= 2:
        activations["structural_cause"]["score"] = max(activations["structural_cause"]["score"], 0.8)
        activations["structural_cause"]["activated"] = True

    if isinstance(hyper_student, dict) and hyper_student.get("ok"):
        cov = hyper_student.get("coverage_score", 10)
        if isinstance(cov, (int, float)) and cov < 4:
            activations["structural_cause"]["score"] = max(activations["structural_cause"]["score"], 0.75)
            activations["structural_cause"]["activated"] = True

    if rag_cases and any(isinstance(c, dict) and c.get("neo4j_enriched") for c in rag_cases):
        activations["external_reference"]["score"] = max(activations["external_reference"]["score"], 0.6)
        activations["external_reference"]["activated"] = True

    entities = kg.get("entities", []) if isinstance(kg.get("entities"), list) else []
    entity_types = {str(e.get("type", "")) for e in entities if isinstance(e, dict)}
    if "competitor" not in entity_types and len(rules) >= 2:
        activations["counter_intuitive"]["score"] = max(activations["counter_intuitive"]["score"], 0.7)
        activations["counter_intuitive"]["activated"] = True

    if any(w in str(diag.get("bottleneck", "")) for w in ("获客", "推广", "渠道", "留存", "付费")):
        activations["strategy_directions"]["score"] = max(activations["strategy_directions"]["score"], 0.65)
        activations["strategy_directions"]["activated"] = True

    for dim, act in activations.items():
        if not ANALYSIS_DIMENSIONS[dim].get("required"):
            act["activated"] = act["score"] > DIM_ACTIVATION_THRESHOLD
        else:
            act["activated"] = True

    return activations


# ═══════════════════════════════════════════════════════════════════
#  V2: Dimension-Driven Agent Selection
# ═══════════════════════════════════════════════════════════════════

def _select_agents_from_dims(activations: dict[str, dict]) -> tuple[set[str], str]:
    needed: set[str] = set()
    reasons: list[str] = []
    for dim, act in activations.items():
        if not act.get("activated"):
            continue
        ownership = DIM_OWNERSHIP.get(dim, {})
        writer = ownership.get("writer", "")
        if writer and writer != "orchestrator":
            needed.add(writer)
        for challenger in ownership.get("challengers", []):
            needed.add(challenger)
            reasons.append(f"{dim}需要{challenger}挑战")
    if not needed:
        needed = {"coach"}
        reasons.append("无激活维度，保底选coach")
    return needed, "维度驱动：" + "；".join(reasons[:5]) if reasons else "维度驱动选择"


def _should_use_deterministic_fallback(activations: dict[str, dict], intent_confidence: float) -> bool:
    activated = [a for a in activations.values() if a.get("activated")]
    if not activated:
        return True
    avg_score = sum(a["score"] for a in activated) / len(activated)
    return len(activated) <= 1 or avg_score < 0.35 or intent_confidence < 0.4


def _decide_agents_v2(state: dict) -> tuple[list[str], str]:
    activations = state.get("dim_activations", {})
    intent_confidence = state.get("intent_confidence", 0.5)
    intent = state.get("intent", "general_chat")
    mode = state.get("mode", "coursework")
    msg = state.get("message", "")
    conv = state.get("conversation_messages", [])
    intent_shape = _normalize_intent_shape(state.get("intent_shape", "single"))
    complexity = _message_complexity(msg, conv)
    tier = _complexity_tier(complexity, intent_shape)

    if not activations or _should_use_deterministic_fallback(activations, intent_confidence):
        agents, reason = _decide_agents(state)
        return agents, f"[兜底矩阵] {reason}"

    dim_agents, dim_reason = _select_agents_from_dims(activations)

    # Mode boost (same logic as v1, additive)
    if mode == "competition" and intent not in ("general_chat", "learning_concept"):
        dim_agents.add("advisor")
    if "[上传文件:" in msg:
        dim_agents.add("coach")

    # Static rules that must always hold
    if _is_score_request_message(msg) or _is_eval_followup_message(msg):
        dim_agents.add("grader")
    if any(w in msg for w in _PLANNING_SIGNALS) and intent in _DISCOVERY_INTENTS:
        dim_agents.add("planner")

    ordered = [a for a in _AGENT_ORDER if a in dim_agents]
    if not ordered:
        ordered = ["coach"]

    max_agents = 6 if tier == "complex" else (4 if tier == "medium" else 2)
    ordered = ordered[:max_agents]

    return ordered, dim_reason


# ═══════════════════════════════════════════════════════════════════
#  V2: Topological Sort → Execution Phases
# ═══════════════════════════════════════════════════════════════════

def _derive_execution_phases(
    selected_agents: list[str],
    activations: dict[str, dict],
    context: dict,
) -> list[list[str]]:
    agents_set = set(selected_agents)
    agent_dims: dict[str, dict[str, list[str]]] = {}
    for agent in agents_set:
        caps = AGENT_CAPABILITIES.get(agent, {"writes": [], "challenges": []})
        writes = [d for d in caps["writes"] if activations.get(d, {}).get("activated")]
        challenges = [d for d in caps["challenges"] if activations.get(d, {}).get("activated")]
        agent_dims[agent] = {"writes": writes, "challenges": challenges}

    agent_hard_deps: dict[str, set[str]] = {}
    for agent, dims in agent_dims.items():
        hard = set()
        for d in dims["writes"] + dims["challenges"]:
            dep_fn = DIM_DEPENDENCIES.get(d, lambda c: [])
            deps = dep_fn(context)
            for dep in deps:
                if dep is None:
                    continue
                dep_dim, weight = dep
                if weight >= 0.8 and activations.get(dep_dim, {}).get("activated"):
                    hard.add(dep_dim)
        agent_hard_deps[agent] = hard

    dim_to_writer: dict[str, str] = {}
    for agent, dims in agent_dims.items():
        for d in dims["writes"]:
            dim_to_writer[d] = agent

    phases: list[list[str]] = []
    remaining = set(agents_set)
    completed_dims: set[str] = set()
    max_iter = len(remaining) + 2
    for _ in range(max_iter):
        if not remaining:
            break
        ready = set()
        for agent in remaining:
            if agent_hard_deps[agent].issubset(completed_dims):
                ready.add(agent)
        if not ready:
            ready = set(remaining)
        phase = sorted(ready)
        phases.append(phase)
        for agent in ready:
            completed_dims.update(agent_dims[agent]["writes"])
            remaining.discard(agent)

    return phases


# ═══════════════════════════════════════════════════════════════════
#  V2: Challenger Execution + Conflict Resolution
# ═══════════════════════════════════════════════════════════════════

def _run_challenger(dim: str, writer_result: dict, state: dict) -> dict | None:
    if not _llm.enabled:
        return None
    writer_value = str(writer_result.get("value", ""))
    if not writer_value or len(writer_value) < 20:
        return None

    dim_label = ANALYSIS_DIMENSIONS.get(dim, {}).get("label", dim)
    msg_excerpt = str(state.get("message", ""))[:400]

    result = _llm.chat_json(
        system_prompt=CHALLENGER_SYSTEM_PROMPT,
        user_prompt=(
            f"维度: {dim_label}\n"
            f"分析师结论: {writer_value[:600]}\n"
            f"学生原文: {msg_excerpt}"
        ),
        model=settings.llm_fast_model,
        temperature=0.3,
    )
    if not isinstance(result, dict):
        return None
    result.setdefault("verdict", "endorse")
    result.setdefault("confidence", 0.5)
    return result


def _resolve_dimension_conflicts(dim_results: dict[str, dict]) -> dict[str, dict]:
    for dim, result in dim_results.items():
        challenges = result.get("challenges", [])
        if not challenges:
            result.setdefault("contested", False)
            continue
        has_real = any(
            c.get("verdict") == "challenge"
            or (c.get("verdict") == "endorse" and float(c.get("confidence", 1)) < 0.7)
            for c in challenges if isinstance(c, dict)
        )
        if has_real:
            result["contested"] = True
            result["amendments"] = [
                str(c.get("weakest_point", "")) for c in challenges
                if isinstance(c, dict) and c.get("weakest_point")
            ]
            result["confidence"] = min(float(result.get("confidence", 0.8)), 0.6)
        else:
            result["contested"] = False
    return dim_results


# ═══════════════════════════════════════════════════════════════════
#  V2: Confidence Patch Phase
# ═══════════════════════════════════════════════════════════════════

def _patch_low_confidence_dims(dim_results: dict[str, dict], state: dict) -> tuple[dict, list[str]]:
    patched: list[str] = []
    if not _llm.enabled:
        return dim_results, patched
    for dim, result in dim_results.items():
        conf = float(result.get("confidence", 1.0))
        if conf >= 0.55 or not result.get("contested"):
            continue
        dim_label = ANALYSIS_DIMENSIONS.get(dim, {}).get("label", dim)
        resolved = _llm.chat_json(
            system_prompt=(
                "两位分析师对同一问题有不同判断。\n"
                "请基于学生原文和双方论据，给出最终结论。\n"
                "输出JSON: {\"conclusion\": \"...\", \"confidence\": 0.0-1.0, \"reasoning\": \"...\"}"
            ),
            user_prompt=(
                f"维度: {dim_label}\n"
                f"主判断: {str(result.get('value', ''))[:400]}\n"
                f"挑战意见: {result.get('amendments', [])}\n"
                f"学生原文: {str(state.get('message', ''))[:400]}"
            ),
            model=settings.llm_fast_model,
            temperature=0.1,
        )
        if isinstance(resolved, dict) and resolved.get("conclusion"):
            result["value"] = resolved["conclusion"]
            result["confidence"] = float(resolved.get("confidence", 0.6))
            result["contested"] = False
            result["patched"] = True
            patched.append(dim)
    return dim_results, patched


# ═══════════════════════════════════════════════════════════════════
#  V2: Reply Strategy Selection
# ═══════════════════════════════════════════════════════════════════

def _select_reply_strategy(
    activations: dict[str, dict],
    intent: str,
    dim_results: dict[str, dict],
    exploration_phase: str | None,
    complexity_tier: str = "simple",
    is_file: bool = False,
    project_maturity: str | None = None,
) -> str:
    activated_dims = [d for d, a in activations.items() if a.get("activated")]
    has_contested = any(r.get("contested") for r in dim_results.values())
    n_active = len(activated_dims)
    avg_confidence = (
        sum(r.get("confidence", 0.5) for r in dim_results.values()) / max(len(dim_results), 1)
        if dim_results else 0.5
    )
    _complex_intents = ("project_diagnosis", "business_model", "competition_prep",
                        "pressure_test", "evidence_check", "market_competitor")

    if project_maturity == "exploring" and intent in _DISCOVERY_INTENTS and not is_file:
        return "progressive"
    if exploration_phase in ("direction", "convergence"):
        return "progressive"
    # 即使 slot ≥3，如果实体极少（信息不足）也走 progressive
    total_ents = sum(1 for r in dim_results.values() if r.get("value"))
    if total_ents <= 2 and n_active <= 2 and not is_file:
        return "progressive"
    if intent == "learning_concept" and "method_bridge" in activated_dims:
        return "teach_concept"
    if intent == "general_chat":
        return "casual"

    # Comprehensive: complex tier + project intent + multiple dimensions
    if (
        (complexity_tier == "complex" or is_file)
        and intent in _complex_intents
        and n_active >= 3
    ):
        return "comprehensive"
    # Panorama: medium complexity with broad activation
    if (
        n_active >= 5
        or (complexity_tier == "medium" and intent in _complex_intents and n_active >= 3)
    ):
        return "panorama"
    if has_contested or "counter_intuitive" in activated_dims:
        return "challenge"
    if intent == "market_competitor":
        return "compare"
    # Deep dive: for focused but non-trivial analysis
    if intent in _complex_intents and n_active >= 2:
        return "deep_dive"
    return "deep_dive"


# ═══════════════════════════════════════════════════════════════════
#  V2: Exploration State Tracking
# ═══════════════════════════════════════════════════════════════════

def _update_exploration_state(
    current_state: dict | None,
    message: str,
    kg_entities: list | None,
    conv: list | None,
) -> dict:
    current_state = current_state or {}
    filled = dict(current_state.get("filled_slots", {}))
    text = (message or "").strip()

    _entity_type_map = {
        "target_user": "stakeholder",
        "pain_point": "pain_point",
        "solution": "solution",
        "business_model": "business_model",
        "competition": "competitor",
    }

    for slot_key, spec in EXPLORATION_SLOTS.items():
        if filled.get(slot_key):
            continue
        if any(hint in text for hint in spec["hints"]):
            filled[slot_key] = True
            continue
        etype = _entity_type_map.get(slot_key)
        if etype and kg_entities:
            if any(isinstance(e, dict) and e.get("type") == etype for e in kg_entities):
                filled[slot_key] = True

    if conv:
        for m in conv:
            if m.get("role") != "user":
                continue
            c = str(m.get("content", ""))
            for slot_key, spec in EXPLORATION_SLOTS.items():
                if filled.get(slot_key):
                    continue
                if any(hint in c for hint in spec["hints"]):
                    filled[slot_key] = True

    n_filled = sum(1 for v in filled.values() if v)
    if n_filled >= 4:
        phase = "full_analysis"
    elif n_filled >= 3:
        phase = "validation"
    elif n_filled >= 2:
        phase = "convergence"
    else:
        phase = "direction"

    priority_order = ["target_user", "pain_point", "solution", "business_model", "competition"]
    missing = [s for s in priority_order if not filled.get(s)]
    next_q = missing[0] if missing else None

    return {
        "phase": phase,
        "filled_slots": filled,
        "missing_slots": missing,
        "next_question_slot": next_q,
        "n_filled": n_filled,
    }


# ═══════════════════════════════════════════════════════════════════
#  V2: Execution Trace Builder
# ═══════════════════════════════════════════════════════════════════

def _build_execution_trace(
    activations: dict, selected_agents: list, phases: list,
    dim_results: dict, patched_dims: list, reply_strategy: str,
    intent: str, intent_confidence: float,
    fallback_used: bool = False,
    complexity_tier: str = "",
) -> dict:
    return {
        "version": "v2_dim_driven",
        "intent": intent,
        "intent_confidence": round(intent_confidence, 2),
        "dim_activation": {
            dim: {
                "score": act.get("score", 0),
                "activated": act.get("activated", False),
                "components": act.get("components", {}),
            }
            for dim, act in activations.items()
        },
        "selected_agents": list(selected_agents),
        "execution_phases": [
            {"phase": i + 1, "agents": pa}
            for i, pa in enumerate(phases)
        ],
        "dim_results_summary": {
            dim: {
                "writer": DIM_OWNERSHIP.get(dim, {}).get("writer", "?"),
                "confidence": round(float(r.get("confidence", 0)), 2),
                "contested": r.get("contested", False),
                "patched": r.get("patched", False),
                "value_preview": str(r.get("value", ""))[:120],
            }
            for dim, r in dim_results.items()
            if activations.get(dim, {}).get("activated")
        },
        "patched_dims": patched_dims,
        "reply_strategy": reply_strategy,
        "complexity_tier": complexity_tier,
        "deterministic_fallback_used": fallback_used,
    }


# ═══════════════════════════════════════════════════════════════════
#  V2: Insight Engine — fact extraction, hypergraph narrative, case transfer
# ═══════════════════════════════════════════════════════════════════

def _extract_facts_from_web(web_result: dict, message: str) -> list[dict]:
    if not _llm.enabled:
        return []
    if not web_result.get("searched") or not web_result.get("results"):
        return []
    raw_text = "\n".join(
        f"标题: {r.get('title', '')}\n内容: {r.get('snippet', '')}\n链接: {r.get('url', '')}"
        for r in web_result.get("results", [])[:5]
    )
    if len(raw_text) < 50:
        return []
    try:
        facts = _llm.chat_json(
            system_prompt=(
                "从搜索结果中提取可在分析中引用的具体事实。\n"
                "输出JSON: {\"facts\": [{\"fact\": \"...\", \"source_title\": \"...\", \"url\": \"...\", \"fact_type\": \"...\"}]}\n"
                "fact_type 必须是: number/company/trend/policy/comparison 之一\n"
                "只提取有具体来源的事实，不要推测。最多6条。"
            ),
            user_prompt=f"学生问题: {message[:200]}\n\n搜索结果:\n{raw_text[:2000]}",
            model=settings.llm_fast_model,
            temperature=0.05,
        )
        return (facts or {}).get("facts", [])[:6]
    except Exception as exc:
        logger.warning("fact extraction failed: %s", exc)
        return []


def _narrativize_hypergraph(hyper_result: dict) -> str:
    if not _llm.enabled:
        return ""
    if not isinstance(hyper_result, dict) or not hyper_result.get("ok"):
        return ""
    value_loops = hyper_result.get("value_loops", [])
    complete = [v for v in value_loops if isinstance(v, dict) and v.get("complete")]
    broken = [v for v in value_loops if isinstance(v, dict) and not v.get("complete")]
    missing = hyper_result.get("missing_dimensions", [])
    if not (complete or broken or missing):
        return ""
    try:
        narrative = _llm.chat_text(
            system_prompt=(
                "你是项目逻辑链路分析师。基于维度覆盖和价值链路数据，"
                "用2-3句自然语言说明项目当前的逻辑链通断情况。\n"
                "要求：不要罗列数据，要像导师对学生说话一样解释'你的链路从哪里断了、这意味着什么'。"
            ),
            user_prompt=(
                f"完整链路: {[v.get('chain', '') for v in complete[:3]]}\n"
                f"断裂链路: {[v.get('chain', '') for v in broken[:3]]}\n"
                f"关键缺失: {[m.get('dimension', '') if isinstance(m, dict) else str(m) for m in missing[:3]]}\n"
            ),
            model=settings.llm_fast_model,
            temperature=0.3,
        )
        return (narrative or "").strip()
    except Exception as exc:
        logger.warning("hypergraph narrative failed: %s", exc)
        return ""


def _generate_case_transfer_insights(rag_cases: list | None, student_message: str) -> str:
    if not _llm.enabled:
        return ""
    enriched = [c for c in (rag_cases or []) if isinstance(c, dict) and c.get("neo4j_enriched")]
    if not enriched:
        return ""
    case_summaries = "\n".join(
        f"- {c.get('project_name', '未知项目')}: "
        f"痛点={c.get('graph_pains', [])}; "
        f"方案={c.get('graph_solutions', [])}; "
        f"模式={c.get('graph_biz_models', [])}"
        for c in enriched[:3]
    )
    try:
        insight = _llm.chat_text(
            system_prompt=(
                "你是跨行业案例迁移分析师。找出案例库中哪些策略或经验教训"
                "可以迁移到学生的项目中。\n"
                "要求：不要泛泛类比，要指出具体的可迁移策略和迁移条件。2-3句话。"
            ),
            user_prompt=(
                f"学生项目: {student_message[:300]}\n\n"
                f"相关案例:\n{case_summaries}"
            ),
            model=settings.llm_fast_model,
            temperature=0.25,
        )
        return (insight or "").strip()
    except Exception as exc:
        logger.warning("case transfer insight failed: %s", exc)
        return ""


def _accumulate_conv_slots(conv: list[dict]) -> dict[str, bool]:
    """Scan conversation history to find slots already mentioned in prior turns."""
    acc_user = False
    acc_pain = False
    acc_solution = False
    acc_business = False
    for m in conv:
        if m.get("role") != "user":
            continue
        c = str(m.get("content", ""))
        c_lower = c.lower()
        if any(t in c for t in _USER_SLOT_HINTS):
            acc_user = True
        if any(t in c for t in _PAIN_SLOT_HINTS) or "解决" in c:
            acc_pain = True
        if any(t in c_lower for t in _SOLUTION_SLOT_HINTS) or "做了个" in c:
            acc_solution = True
        if any(t in c_lower for t in _BUSINESS_SLOT_HINTS):
            acc_business = True
    return {"user": acc_user, "pain": acc_pain, "solution": acc_solution, "business": acc_business}


def _assess_clarification_need(state: WorkflowState) -> dict[str, Any]:
    _NO_NEED = {"needs_clarification": False, "clarification_reason": "", "clarification_questions": [], "clarification_missing": []}
    intent = state.get("intent", "general_chat")
    msg = state.get("message", "")
    diag = state.get("diagnosis", {}) if isinstance(state.get("diagnosis"), dict) else {}
    kg = state.get("kg_analysis", {}) if isinstance(state.get("kg_analysis"), dict) else {}
    conv = state.get("conversation_messages", [])
    if "[上传文件:" in msg or intent not in _DISCOVERY_INTENTS:
        return _NO_NEED

    # If the student is actively seeking advice/evaluation, never block with clarification
    if any(sig in msg for sig in _ADVICE_SEEKING_SIGNALS):
        logger.info("assess_clarification: advice-seeking detected, skip clarification")
        return _NO_NEED
    if any(sig in msg for sig in _EVALUATION_FOLLOWUP_SIGNALS):
        return _NO_NEED

    # Accumulate slots from current message + conversation history
    acc = _accumulate_conv_slots(conv)
    entities = kg.get("entities", []) if isinstance(kg.get("entities"), list) else []
    entity_types = {str(e.get("type", "")) for e in entities if isinstance(e, dict)}
    text_lower = msg.lower()
    cur_has_user = any(term in msg for term in _USER_SLOT_HINTS)
    cur_has_solution = any(term in text_lower for term in _SOLUTION_SLOT_HINTS) or "做了个" in msg
    cur_has_pain = any(term in msg for term in _PAIN_SLOT_HINTS) or "解决" in msg
    cur_has_business = any(term in text_lower for term in _BUSINESS_SLOT_HINTS)

    has_user = cur_has_user or acc["user"] or "stakeholder" in entity_types
    has_pain = cur_has_pain or acc["pain"] or "pain_point" in entity_types
    has_solution = cur_has_solution or acc["solution"] or "solution" in entity_types
    has_business = cur_has_business or acc["business"] or "business_model" in entity_types

    slot_hits = sum(1 for flag in (has_user, has_pain, has_solution, has_business) if flag)
    missing: list[str] = []
    if not has_user:
        missing.append("目标用户")
    if not has_pain:
        missing.append("核心痛点")
    if not has_solution:
        missing.append("解决方案")
    if intent in ("business_model", "competition_prep") and not has_business:
        missing.append("商业模式")

    # Multi-turn conversations: much higher bar for clarification
    n_user_turns = sum(1 for m in conv if m.get("role") == "user")
    if n_user_turns >= 2:
        if len(missing) <= 2:
            logger.info("assess_clarification: multi-turn (%d user turns), missing=%d <=2, skip", n_user_turns, len(missing))
            return _NO_NEED
    if n_user_turns >= 1 and slot_hits >= 2:
        logger.info("assess_clarification: has prior context + %d slots filled, skip", slot_hits)
        return _NO_NEED

    vague_signal = any(sig in msg for sig in _VAGUE_PROJECT_SIGNALS)
    direction_exploration = (
        any(sig in msg for sig in ("方向", "赛道", "领域"))
        and len(missing) >= 3
        and len(msg) < 420
    )
    info_sufficient = bool(diag.get("info_sufficient", True))
    need = (
        (not info_sufficient and len(missing) >= 2)
        or len(missing) >= 3
        or (vague_signal and len(missing) >= 2)
        or direction_exploration
    )

    if len(msg) >= 180 and slot_hits >= 2:
        need = False
    if len(msg) >= 100 and slot_hits >= 1 and len(missing) <= 1:
        need = False

    question_bank = {
        "目标用户": "你现在最想服务的是哪一类具体人群？最好具体到年龄、身份、场景，而不是\u201c所有人\u201d。",
        "核心痛点": "这类人在什么场景下会遇到什么具体痛点？这个问题现在通常怎么被凑合解决？",
        "解决方案": "你的产品或服务到底准备怎么解决这个问题？用户第一次使用时会经历什么流程？",
        "商业模式": "如果这个方向成立，你准备靠什么赚钱或形成可持续模式？哪怕只是初步设想也可以。",
    }
    questions = [question_bank[item] for item in missing if item in question_bank][:6]
    if len(questions) < 5:
        questions.append("你为什么觉得这个方向值得做？是看到过真实现象、身边案例，还是你自己遇到过这个问题？")

    reason = ""
    if need:
        if direction_exploration:
            reason = "你现在更像是在讨论一个方向，而不是一个已经收敛好的项目，所以我更适合先帮你把问题范围缩小，再进入实质分析。"
        elif missing:
            reason = "你已经给了我一个不错的起点，但现在还不够支撑深入诊断，我先帮你把关键骨架补齐会更有帮助。"
        else:
            reason = "你的想法还处在早期阶段，我先帮你把项目描述框架补完整，再进入深度分析。"
    return {
        "needs_clarification": need,
        "clarification_reason": reason,
        "clarification_questions": questions[:6],
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
        observations.append("既然你主动提到商业逻辑不太踏实，那我会优先看几条主线：**用户为什么愿意持续用、为什么愿意付费、以及成本结构会不会把你们拖住**。")

    if not observations:
        observations.append("这个想法可以先继续往下聊，但现在更适合先做一轮粗判断，把项目的关键骨架补齐，再进入完整诊断。")

    parts = ["## 先粗聊一下", observations[0]]
    for extra in observations[1:4]:
        parts.append(extra)
    if missing:
        parts.append(f"不过我现在还缺少一些关键信息，主要是：**{'、'.join(missing)}**。")
    if questions:
        parts.append("## 我想先抓一个最关键的问题")
        parts.append(questions[0])
    if len(questions) > 1:
        parts.append("如果你愿意，也可以顺手再补这几项：")
        for idx, q in enumerate(questions[1:5], 1):
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
            "1. 先基于学生已经给出的信息，做**若干点粗略但有价值的讨论**，数量由材料复杂度决定，不要固定成三点\n"
            "2. 明确告诉学生这些只是初步判断，不要假装已经知道他没说过的细节\n"
            "3. 然后从最值得深挖的地方切入，只追问1个主问题\n"
            "4. 最后再附带若干补充信息点，而不是一上来像问卷一样连发很多问题\n\n"
            "严格要求：\n"
            "- 不要用“先别急着做复杂诊断”这种生硬说法\n"
            "- 不要只给 checklist，要像老师先聊两句，再顺势追问\n"
            "- 可以提出基于项目类型的常见风险，例如 AI 工具常见的替代性、留存、付费逻辑、获客执行问题\n"
            "- 但不要编造学生没有提供过的具体数字、渠道、功能细节\n"
            "- 如果学生还只是提出一个大方向或赛道，禁止使用过重的否定性开场，比如“脚下是空的”“致命问题”等\n"
            "- 在方向探索阶段，你要做的是帮助学生收敛问题空间，而不是像已经读完BP一样下完整诊断\n"
            "- 语气自然、专业、像真正指导项目\n"
            "- 输出 4-7 段，350-850 字"
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
        model=settings.llm_fast_model,
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


_MODE_CHAT_FLAVOR: dict[str, str] = {
    "coursework": (
        "你当前的身份是**课程导师**。闲聊时你的风格是：耐心、温和、像办公室里一对一辅导。"
        "引导方向偏向'学习方法、概念理解、如何把课堂知识用到项目里'。"
    ),
    "competition": (
        "你当前的身份是**竞赛教练**。闲聊时你的风格是：专业、克制、偶尔犀利。"
        "引导方向偏向'比赛准备、路演打磨、评委会怎么看'。"
    ),
    "learning": (
        "你当前的身份是**项目教练**。闲聊时你的风格是：务实、推动、像创业合伙人。"
        "引导方向偏向'项目进展、下一步验证、用户反馈、资源约束'。"
    ),
}


def _build_chat_system_prompt(state: dict) -> str:
    mode = str(state.get("mode") or "coursework")
    persona = _MODE_PERSONA.get(mode, _MODE_PERSONA["coursework"])
    flavor = _MODE_CHAT_FLAVOR.get(mode, _MODE_CHAT_FLAVOR["coursework"])

    return (
        f"{persona}\n\n"
        f"## 当前模式特征\n{flavor}\n\n"
        "## 当前情境\n"
        "学生这条消息看起来不是在做深度项目分析——可能是打招呼、闲聊、开玩笑、"
        "吐槽、发表情、或者只是简短回应。\n\n"
        "## 绝对禁止\n"
        "- **禁止输出括号内的舞台指令**，比如'(如果学生没有继续项目相关内容，可以...)'。"
        "你的输出就是你说的话本身，没有旁白、没有括号注释。\n"
        "- **禁止假装有人类体验**：你是 AI，不会吃饭、睡觉、有心情。"
        "如果学生问'吃了吗''中午吃什么'，坦然说自己是 AI 不吃饭，"
        "但可以用幽默方式接住，比如'我不吃饭，不过如果你请我选，我可能会好奇你们食堂最火的是哪个窗口'。\n"
        "- **禁止用 emoji 开头或结尾**。可以偶尔在句中用一个，但不要变成 emoji 堆砌。\n"
        "- **禁止机械重复**：仔细看上下文里你之前说过什么，绝对不能再说一遍类似的话。\n\n"
        "## 你的原则\n"
        "1. **自然对话**：像一个真人导师那样接住学生说的任何话。"
        "该幽默就幽默，该认真就认真，该吐槽就吐槽。\n"
        "2. **前后一致**：仔细看对话上下文。如果你上一句说了A，这一句不要矛盾。\n"
        "3. **多轮感知**：如果上下文里已经聊过项目或某个话题，"
        "自然地衔接而不是从头开始。\n"
        "4. **温和引导**：在自然对话中找到机会，顺势把话题带向项目、"
        "创业、课程、竞赛等双创话题。"
        "不要生硬地说'请发送项目描述'，而是用好奇心或自然过渡来引导。\n"
        "5. **有内容**：如果能联系到创业、行业、商业世界的小知识点或趣事，"
        "可以顺手分享一句，让对话有信息增量而不是空转寒暄。\n"
        "6. **长度灵活**：学生说的话越短，你的回复 2-4 句就够；"
        "如果学生的话有内容，可以展开到 4-8 句。\n"
        "7. 第一人称回复。不要在末尾输出'⚠ AI生成，仅供参考'之类的免责声明，前端已经有了。\n"
    )


def _build_chat_user_prompt(state: dict) -> str:
    msg = str(state.get("message") or "").strip()
    conv = state.get("conversation_messages", []) or []
    conv_ctx = "\n".join(
        f"{'学生' if m.get('role') == 'user' else 'AI'}: {str(m.get('content') or '')[:200]}"
        for m in conv[-8:]
        if isinstance(m, dict) and m.get("content")
    )
    return (
        f"学生说：{msg[:500]}\n\n"
        + (f"最近的对话上下文：\n{conv_ctx}\n" if conv_ctx else "这是新对话的第一条消息。\n")
    )


def _general_chat_reply(state: dict) -> str:
    if not _llm.enabled:
        return "你好！有什么项目想法可以聊聊吗？"
    try:
        reply = _llm.chat_text(
            system_prompt=_build_chat_system_prompt(state),
            user_prompt=_build_chat_user_prompt(state),
            model=settings.llm_fast_model,
            temperature=0.7,
        )
        if reply and len(reply.strip()) >= 8:
            return reply.strip()
    except Exception as e:
        logger.warning("general_chat LLM call failed: %s", e)
    return "你好！最近有什么项目想法在推进吗？可以和我聊聊。"


def _general_chat_reply_stream(state: dict):
    if not _llm.enabled:
        yield "你好！有什么项目想法可以聊聊吗？"
        return
    try:
        for chunk in _llm.chat_text_stream(
            system_prompt=_build_chat_system_prompt(state),
            user_prompt=_build_chat_user_prompt(state),
            model=settings.llm_fast_model,
            temperature=0.7,
        ):
            yield chunk
    except Exception as e:
        logger.warning("general_chat stream failed: %s", e)
        yield "你好！最近有什么项目想法在推进吗？可以和我聊聊。"


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
    consistency_issues: list[dict[str, Any]] | None = None,
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

    # Merge consistency-rule pressure questions as fallback/supplement
    consistency_questions = []
    for ci in (consistency_issues or [])[:4]:
        for pq in (ci.get("pressure_questions") or [])[:1]:
            q = str(pq).strip()
            if q and q != generated_question:
                consistency_questions.append(q)

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
        "consistency_pressure_questions": consistency_questions[:3],
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

    competition_direct = any(k in message for k in ("互联网+", "挑战杯", "评委", "路演", "答辩", "备赛", "获奖"))
    if competition_direct:
        return {
            "intent": "competition_prep",
            "confidence": 0.86,
            "intent_shape": "mixed" if len(message) >= 180 else "single",
            "intent_reason": _intent_reason_text("rule", "competition_prep", matched=["竞赛/评委"], shape="mixed" if len(message) >= 180 else "single"),
            "agents": list(INTENTS["competition_prep"]["agents"]),
            "engine": "rule",
        }

    # ── Rule-based concept detection (fast, accurate) ──
    if _is_generic_learning_question(message) or _is_coursework_professional_question(message):
        return {
            "intent": "learning_concept",
            "confidence": 0.9,
            "intent_shape": "single",
            "intent_reason": _intent_reason_text("rule", "learning_concept", matched=["专业概念辅导/通俗讲解"], shape="single"),
            "agents": list(INTENTS["learning_concept"]["agents"]),
            "engine": "rule",
        }

    # ── PRIMARY: LLM classification ──
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
                "你是一个精准的意图分类器。根据学生最新消息和对话上下文，判断学生的核心意图。\n\n"
                f"可选意图:\n{intent_list}\n\n"
                "## 分类原则（按优先级排序）\n"
                "1. **learning_concept**: 学生在问某个概念怎么理解、怎么做、有什么区别、某个方法论怎么用等。"
                "即使消息中提到了'我的项目'，只要核心是在问概念/方法论而不是要求诊断项目，就选这个。"
                "例: '什么是价值主张'、'TAM怎么算'、'有用和有商业价值的区别'、'MVP怎么做'、'怎么判断需求是否真实'\n"
                "2. **project_diagnosis**: 学生在描述一个具体项目（包含功能、用户、商业模式等多个方面的实质信息），希望获得综合诊断或评价。"
                "例: '我们做了一个AI论文工具，功能包括...'、'帮我看看这个项目方案'\n"
                "3. **business_model**: 学生在讨论具体项目的定价、收入来源、盈利方式等商业模式问题。\n"
                "4. **market_competitor**: 学生在问市面上有没有类似的产品、竞品、替代品。\n"
                "5. **evidence_check**: 学生在讨论用户访谈、问卷、调研数据等证据。\n"
                "6. **competition_prep**: 学生在讨论竞赛备赛、答辩技巧、路演方法等。\n"
                "7. **pressure_test**: 学生在测试项目薄弱环节或挑战自己的假设。\n"
                "8. **idea_brainstorm**: 学生还没有具体方向，在寻求创业灵感或方向建议。\n"
                "9. **funding_investment**: 学生在问融资、投资、估值、股权、写BP等问题。\n"
                "10. **company_operations**: 学生在问开公司、注册、法务、股权架构、知识产权等。\n"
                "11. **startup_execution**: 学生在问招人、团队管理、增长策略、规模化、上市等执行层面。\n"
                "12. **general_chat**: 完全与创业/项目无关的日常对话或寒暄。\n\n"
                "## intent_shape 判断\n"
                "- single: 消息围绕一个主题\n"
                "- mixed: 消息同时涉及多个不同主题（如项目介绍+商业模式+推广+竞争）\n\n"
                '输出JSON: {"intent":"ID","confidence":0.0-1.0,"intent_shape":"single|mixed","reason":"一句话理由"}'
            ),
            user_prompt=(
                (f"对话上下文:\n{conv_ctx}\n\n" if conv_ctx else "")
                + f"学生最新消息: {message[:500]}"
            ),
            model=settings.llm_fast_model,
            temperature=0.05,
        )
        logger.info("classify LLM: %s", llm_r)
        if llm_r and llm_r.get("intent") in INTENTS:
            llm_conf = float(llm_r.get("confidence", 0))
            if llm_conf > 0.4:
                llm_shape = _normalize_intent_shape(llm_r.get("intent_shape", "single"), default="single")
                r = {
                    "intent": llm_r["intent"],
                    "confidence": llm_conf,
                    "intent_shape": llm_shape,
                    "intent_reason": _intent_reason_text("llm", llm_r["intent"], shape=llm_shape, llm_reason=str(llm_r.get("reason", "") or "")),
                    "agents": list(INTENTS[llm_r["intent"]]["agents"]),
                    "engine": "llm",
                }
                logger.info("classify → %s (llm, conf=%.2f)", llm_r["intent"], llm_conf)
                return r

    # ── FALLBACK: Keyword scoring (when LLM unavailable or low confidence) ──
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
    logger.info("classify fallback: msg='%s…' kw_best=%s kw_score=%.3f", text[:40], kw_best, kw_score)

    if kw_score >= 0.35:
        r = {
            "intent": kw_best,
            "confidence": min(0.88, max(0.5, kw_score)),
            "intent_shape": shape,
            "intent_reason": _intent_reason_text("rule-fallback", kw_best, matched=kw_matched, shape=shape, shape_reasons=shape_reasons),
            "agents": list(INTENTS[kw_best]["agents"]),
            "engine": "rule-fallback",
        }
        logger.info("classify → %s (rule-fallback, score=%.2f)", kw_best, kw_score)
        return r

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

    short_project_signals = (
        "项目", "创业", "双创", "商业模式", "盈利", "收费", "用户", "痛点",
        "竞品", "竞争", "推广", "流量", "获客", "评委", "答辩", "路演", "计划书",
    )
    if any(sig in message for sig in short_project_signals):
        r = {
            "intent": "project_diagnosis",
            "confidence": 0.52,
            "intent_shape": "single",
            "intent_reason": _intent_reason_text("heuristic_short_project", "project_diagnosis", matched=["短消息但仍在双创语境内"], shape="single"),
            "agents": list(INTENTS["project_diagnosis"]["agents"]),
            "engine": "heuristic_short_project",
        }
        logger.info("classify → project_diagnosis (heuristic_short_project)")
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
    """Pass through classifier-suggested agents — mode no longer locks primary agent.

    _decide_agents handles the real selection via AGENT_MATRIX + mode_boost.
    """
    return [a for a in agents if a in AGENT_FNS][:2] or ["coach"]


def router_agent(state: WorkflowState) -> dict:
    conv = state.get("conversation_messages", [])
    mode = state.get("mode", "coursework")
    message = state.get("message", "")
    c = _classify(state.get("message", ""), conversation_messages=conv)
    pipeline = _adjust_pipeline_for_mode(c["agents"], mode, c["intent"])

    # V2: compute initial dimension activations (rule-only, no LLM)
    complexity = _message_complexity(message, conv)
    dim_activations = _compute_all_dim_activations(c["intent"], message, mode, complexity)

    # V2: compute initial exploration state
    kg_entities = None
    exploration_state = _update_exploration_state(
        state.get("exploration_state"), message, kg_entities, conv,
    )

    return {
        "intent": c["intent"],
        "intent_confidence": c["confidence"],
        "intent_shape": c.get("intent_shape", "single"),
        "intent_reason": c.get("intent_reason", ""),
        "intent_pipeline": pipeline,
        "intent_engine": c["engine"],
        "score_request_detected": _is_score_request_message(message),
        "eval_followup_detected": _is_eval_followup_message(message),
        "conversation_continuation_mode": _conversation_continuation_mode(state),
        "dim_activations": dim_activations,
        "exploration_state": exploration_state,
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

    # ── Synthesize template_matches from value_loops (fallback for HypergraphService) ──
    template_matches = []
    for vl in value_loops:
        missing_t = [d for d in vl["dims"] if not dim_entities.get(d)]
        status = "complete" if vl["complete"] else ("partial" if len(missing_t) < len(vl["dims"]) else "missing")
        template_matches.append({
            "id": f"VL_{vl['chain'].replace('→', '_')}",
            "name": vl["chain"],
            "description": vl["chain"],
            "dimensions": vl["dims"],
            "missing_dimensions": missing_t,
            "status": status,
            "pattern_type": "neutral",
            "linked_rules": [],
        })

    # ── Synthesize consistency_issues from warnings ──
    consistency_issues = []
    for wi, w in enumerate(warnings):
        consistency_issues.append({
            "id": f"W{wi + 1}",
            "description": w.get("warning", ""),
            "message": w.get("warning", ""),
            "pressure_questions": [],
        })

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
        "template_matches": template_matches,
        "consistency_issues": consistency_issues,
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

_PROJECT_FACT_GROUNDING_SIGNALS = frozenset([
    "ai", "人工智能", "论文", "伴读", "工具", "平台", "小红书", "知乎",
    "推广", "获客", "收费", "定价", "竞争", "竞品", "替代", "留存",
    "notion", "obsidian", "zotero", "chatpdf", "scispace",
])


def _merge_historical_entities(
    current_entities: list[dict],
    current_rels: list[dict],
    conversation_messages: list[dict],
) -> tuple[list[dict], list[dict], int]:
    """Accumulate KG entities across conversation turns.

    Deduplicates by (type, normalized_label) and assigns stable IDs so
    relationships from different turns connect correctly.
    Returns (merged_entities, merged_rels, new_count_this_turn).
    """
    seen: dict[tuple[str, str], dict] = {}
    stable_id_counter = 0

    def _norm(label: str) -> str:
        return label.strip().lower().replace(" ", "")

    def _get_stable_id(etype: str, label: str) -> str:
        nonlocal stable_id_counter
        key = (etype, _norm(label))
        if key not in seen:
            stable_id_counter += 1
            return f"s{stable_id_counter}"
        return seen[key]["id"]

    def _process_turn(entities: list[dict], rels: list[dict]) -> dict[str, str]:
        """Process one turn's entities+rels. Returns orig_id → stable_id map."""
        nonlocal stable_id_counter
        id_map: dict[str, str] = {}
        for ent in entities:
            if not isinstance(ent, dict) or not ent.get("label"):
                continue
            etype = str(ent.get("type", ""))
            label = str(ent["label"])
            key = (etype, _norm(label))
            orig_id = str(ent.get("id", ""))
            if key not in seen:
                stable_id_counter += 1
                sid = f"s{stable_id_counter}"
                seen[key] = {**ent, "id": sid}
            else:
                sid = seen[key]["id"]
                seen[key] = {**seen[key], **{k: v for k, v in ent.items() if k != "id" and v}}
            id_map[orig_id] = sid
        return id_map

    seen_rels: dict[tuple[str, str, str], dict] = {}

    for hm in conversation_messages:
        trace = hm.get("agent_trace") if isinstance(hm, dict) else None
        if not isinstance(trace, dict):
            continue
        kg = trace.get("kg_analysis")
        if not isinstance(kg, dict):
            continue
        id_map = _process_turn(kg.get("entities", []), kg.get("relationships", []))
        for rel in kg.get("relationships", []):
            if not isinstance(rel, dict):
                continue
            src = id_map.get(str(rel.get("source", "")), str(rel.get("source", "")))
            tgt = id_map.get(str(rel.get("target", "")), str(rel.get("target", "")))
            rk = (src, tgt, str(rel.get("relation", "")))
            if rk not in seen_rels:
                seen_rels[rk] = {**rel, "source": src, "target": tgt}

    prev_count = len(seen)
    cur_id_map = _process_turn(current_entities, current_rels)
    new_count = len(seen) - prev_count
    for rel in current_rels:
        if not isinstance(rel, dict):
            continue
        src = cur_id_map.get(str(rel.get("source", "")), str(rel.get("source", "")))
        tgt = cur_id_map.get(str(rel.get("target", "")), str(rel.get("target", "")))
        rk = (src, tgt, str(rel.get("relation", "")))
        seen_rels[rk] = {**rel, "source": src, "target": tgt}

    return list(seen.values()), list(seen_rels.values()), new_count


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

    comp_type = state.get("competition_type", "")
    diag_obj = run_diagnosis(input_text=msg, mode=mode, competition_type=comp_type)
    diag_data: dict = diag_obj.diagnosis
    next_task: dict = diag_obj.next_task
    cat = infer_category(msg)
    rules = diag_data.get("triggered_rules", []) or []
    rule_ids = [r.get("id", "") for r in rules if isinstance(r, dict)]
    top_rule = _top_triggered_rule(diag_data, msg)
    top_fallacy = str(top_rule.get("fallacy_label") or "")
    preferred_edge_types = list(top_rule.get("preferred_edge_types") or [])

    # Cross-turn context reuse: collect case knowledge from earlier turns
    _history_case_ids: set[str] = set()
    _history_rag_insights: list[str] = []
    _history_graph_insights: list[str] = []
    for _hm in state.get("conversation_messages", []):
        _trace = _hm.get("agent_trace") if isinstance(_hm, dict) else None
        if not isinstance(_trace, dict):
            continue
        _orch = _trace.get("orchestration") or _trace
        for _cid in (_orch.get("rag_case_ids") or []):
            if _cid:
                _history_case_ids.add(str(_cid))
        # Carry forward RAG enrichment insights from previous turns
        _prev_enrich = str(_trace.get("rag_enrichment_insight") or "").strip()
        if _prev_enrich and len(_prev_enrich) > 20:
            _history_rag_insights.append(_prev_enrich[:300])
        # Carry forward graph search hits as context
        for _gh in (_trace.get("neo4j_graph_hits") or [])[:3]:
            if isinstance(_gh, dict) and _gh.get("project_name"):
                _dims = ", ".join(_gh.get("matched_dimensions", [])[:3])
                _history_graph_insights.append(
                    f"{_gh['project_name']}(维度:{_dims})"
                )
    _history_knowledge_ctx = ""
    if _history_rag_insights or _history_graph_insights:
        _parts = []
        if _history_rag_insights:
            _parts.append("前几轮搜到的案例启发: " + "; ".join(_history_rag_insights[-3:]))
        if _history_graph_insights:
            _dedup = list(dict.fromkeys(_history_graph_insights))[:5]
            _parts.append("前几轮图谱搜到的相关项目: " + ", ".join(_dedup))
        _history_knowledge_ctx = "\n".join(_parts)

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
            "rag_enrichment_insight": "",
            "web_search_result": {},
            "hypergraph_insight": {},
            "hypergraph_student": {},
            "hyper_consistency_issues": [],
            "challenge_strategies": strategies,
            "pressure_test_trace": pressure_trace,
            **clarify,
            "nodes_visited": ["gather_context"],
        }

    # ── Lightweight gather for concept/learning questions ──
    _is_concept_lightweight = (
        intent == "learning_concept"
        and not is_file
        and not _has_explicit_project_context(msg)
        and len(msg) < 250
    )
    if _is_concept_lightweight:
        from app.services.rag_engine import RagEngine
        logger.info("gather_context: lightweight path for learning_concept")
        rag_cases: list = []
        rag_ctx = ""
        rag_ei = ""
        _lw_kb_util: dict = {}
        if _rag is not None and _rag.case_count > 0:
            try:
                rag_cases = _rag.retrieve(
                    msg[:500], top_k=3, category_filter=cat or None,
                    exclude_ids=_history_case_ids or None,
                )
                # Neo4j enrichment for lightweight path too
                if _graph_service and rag_cases:
                    try:
                        hit_ids = [c["case_id"] for c in rag_cases if c.get("case_id")]
                        _sr = [r.get("id", "") for r in (diag_data.get("triggered_rules") or [])
                               if isinstance(r, dict) and r.get("id")]
                        enriched = _graph_service.enrich_rag_hits(hit_ids, _sr)
                        if enriched:
                            for c in rag_cases:
                                extra = enriched.get(c.get("case_id", ""))
                                if extra:
                                    c.update(extra)
                    except Exception:
                        pass
                rag_ctx = _rag.format_for_llm(rag_cases)
                rag_ei = RagEngine.format_enrichment_insight(rag_cases)
                _lw_kb_util = {
                    "retrieval_mode": rag_cases[0].get("retrieval_mode", "auto") if rag_cases else "auto",
                    "total_kb_cases": _rag.case_count,
                    "excluded_history_count": len(_history_case_ids),
                    "hits_count": len(rag_cases),
                    "neo4j_enriched": any(c.get("neo4j_enriched") for c in rag_cases),
                    "neo4j_enriched_count": sum(1 for c in rag_cases if c.get("neo4j_enriched")),
                    "category_filter": cat or "",
                    "top_k_requested": 3,
                }
            except Exception:
                pass
        kg_result = _default_kg()
        if _graph_service:
            try:
                keywords = [w for w in re.findall(r"[\u4e00-\u9fff]{2,}", msg[:200]) if len(w) >= 2][:4]
                if keywords:
                    kg_nodes = _graph_service.search_nodes(keywords, limit_per_keyword=2)
                    if kg_nodes:
                        kg_result["kg_grounding"] = kg_nodes
            except Exception:
                pass
        return {
            "diagnosis": diag_data,
            "next_task": next_task,
            "category": cat,
            "kg_analysis": kg_result,
            "rag_cases": rag_cases,
            "rag_context": rag_ctx,
            "rag_enrichment_insight": rag_ei,
            "kb_utilization": _lw_kb_util,
            "web_search_result": {},
            "hypergraph_insight": {},
            "hypergraph_student": {},
            "hyper_consistency_issues": [],
            "challenge_strategies": strategies,
            "pressure_test_trace": {},
            "needs_clarification": False,
            "nodes_visited": ["gather_context"],
        }

    # ────────────────────────────────────────────────────────────────
    # LAYERED ON-DEMAND GATHER
    # ────────────────────────────────────────────────────────────────
    collected: dict[str, Any] = {}

    # -- Task definitions (unchanged) --
    def _task_rag():
        from app.services.rag_engine import RagEngine
        if _rag is None or _rag.case_count == 0:
            return {"rag_cases": [], "rag_context": "", "rag_enrichment_insight": "", "kb_utilization": {}}
        tag_filter: list[str] = []
        if cat:
            tag_filter.append(f"category:{cat}")
        rag_top_k = 5 if intent in ("market_competitor", "competition_prep", "learning_concept", "idea_brainstorm") else 4
        cases = _rag.retrieve(
            msg[:1000], top_k=rag_top_k, category_filter=cat or None,
            tags=tag_filter or None, exclude_ids=_history_case_ids or None,
            competition_type=comp_type or None,
        )
        retrieval_mode = cases[0].get("retrieval_mode", "auto") if cases else "auto"
        complementary_ids: list[str] = []
        if _graph_service:
            try:
                rubric = diag_data.get("rubric", []) or []
                weak_dims = [str(r.get("item", "")) for r in rubric if isinstance(r, dict) and float(r.get("score", 10)) < 5]
                if weak_dims:
                    existing_ids = [c.get("case_id", "") for c in cases]
                    complementary_ids = _graph_service.find_complementary_cases(weak_dims, exclude_ids=existing_ids, limit=2)
                    if complementary_ids:
                        extra_cases = _rag.retrieve(msg[:500], top_k=len(complementary_ids) + 2, exclude_ids=set(existing_ids) | _history_case_ids)
                        for ec in extra_cases:
                            if ec.get("case_id") in complementary_ids and len(cases) < rag_top_k + 2:
                                ec["complementary"] = True
                                cases.append(ec)
            except Exception as exc:
                logger.warning("Complementary search failed: %s", exc)
        neo4j_enriched = False
        enrichment_count = 0
        logger.info(
            "RAG dual-channel: graph_service=%s cases=%d retrieval_mode=%s",
            _graph_service is not None, len(cases), retrieval_mode,
        )
        if _graph_service and cases:
            try:
                hit_ids = [c["case_id"] for c in cases if c.get("case_id")]
                _student_rules = [r.get("id", "") for r in (diag_data.get("triggered_rules") or []) if isinstance(r, dict) and r.get("id")]
                logger.info("RAG→Neo4j enrichment: hit_ids=%s student_rules=%s", hit_ids[:4], _student_rules[:4])
                enriched = _graph_service.enrich_rag_hits(hit_ids, _student_rules)
                if enriched:
                    neo4j_enriched = True
                    for c in cases:
                        extra = enriched.get(c.get("case_id", ""))
                        if extra:
                            c.update(extra)
                            enrichment_count += 1
                    logger.info("RAG→Neo4j enrichment success: %d/%d cases enriched", enrichment_count, len(cases))
                else:
                    logger.warning("RAG→Neo4j enrichment returned empty (case_ids may not exist as Project.id in Neo4j)")
            except Exception as exc:
                logger.warning("Neo4j RAG enrichment failed: %s", exc)
        elif not _graph_service:
            logger.warning("RAG dual-channel: graph_service is None, skipping Neo4j enrichment")
        ctx = _rag.format_for_llm(cases)
        enrichment_insight = RagEngine.format_enrichment_insight(cases)
        search_trace = [{
            "case_id": str(c.get("case_id") or c.get("project_name") or "")[:60],
            "score": round(float(c.get("score") or c.get("similarity", 0) or 0), 3),
            "category": str(c.get("category") or "")[:30],
            "neo4j_enriched": bool(c.get("neo4j_enriched")),
            "complementary": bool(c.get("complementary")),
            "hyper_driven": bool(c.get("hyper_driven")),
            "snippet": str(c.get("project_name") or c.get("case_id") or "")[:40],
        } for c in cases]
        weak_dims_searched = [str(r.get("item", "")) for r in (diag_data.get("rubric", []) or []) if isinstance(r, dict) and float(r.get("score", 10)) < 5]
        kb_util = {
            "retrieval_mode": retrieval_mode, "total_kb_cases": _rag.case_count,
            "excluded_history_count": len(_history_case_ids), "hits_count": len(cases),
            "neo4j_enriched": neo4j_enriched, "neo4j_enriched_count": enrichment_count,
            "complementary_count": len(complementary_ids), "category_filter": cat or "",
            "top_k_requested": rag_top_k, "search_trace": search_trace,
            "query_preview": msg[:120], "weak_dims_for_complementary": weak_dims_searched[:4],
        }
        return {"rag_cases": cases, "rag_context": ctx, "rag_enrichment_insight": enrichment_insight, "kb_utilization": kb_util}

    def _task_kg():
        if not _llm.enabled or len(msg) < 10:
            return {"kg_analysis": _default_kg()}

        # 构建历史上下文：最近3轮对话 + 已知实体列表
        _conv = state.get("conversation_messages") or []
        _hist_ctx_parts: list[str] = []
        _known_entities: list[dict] = []
        _known_rels: list[dict] = []
        for _hm in _conv[-6:]:
            if not isinstance(_hm, dict):
                continue
            _role = "学生" if _hm.get("role") == "user" else "AI"
            _content = str(_hm.get("content", ""))[:300]
            if _content.strip():
                _hist_ctx_parts.append(f"{_role}: {_content}")
            _htrace = _hm.get("agent_trace") if isinstance(_hm, dict) else None
            if isinstance(_htrace, dict):
                _hkg = _htrace.get("kg_analysis")
                if isinstance(_hkg, dict):
                    _known_entities.extend(_hkg.get("entities", []))
                    _known_rels.extend(_hkg.get("relationships", []))

        _known_summary = ""
        if _known_entities:
            _known_labels = [f"{e.get('label','')}({e.get('type','')})" for e in _known_entities if isinstance(e, dict) and e.get("label")]
            _dedup = list(dict.fromkeys(_known_labels))[:20]
            _known_summary = f"\n\n已从前几轮提取的实体({len(_dedup)}个): {', '.join(_dedup)}\n请不要重复这些，只提取本轮新出现的实体。如果学生修正了之前的说法，可以用新实体替代。"

        _hist_block = ""
        if _hist_ctx_parts:
            _hist_block = "\n\n前几轮对话摘要:\n" + "\n".join(_hist_ctx_parts[-6:])

        kg = _llm.chat_json(
            system_prompt=(
                "你是知识图谱抽取引擎。从学生的创业项目描述中**尽可能全面地**提取实体和关系。\n"
                + ("学生上传了文件，请逐段仔细分析，不要遗漏任何关键信息。\n" if is_file else "")
                + "实体type必须从以下选择: stakeholder, pain_point, solution, innovation, "
                "technology, market, competitor, resource, business_model, execution_step, risk_control, team, evidence\n\n"
                "**提取原则**:\n"
                "1. 宁多勿少：一句话里可能包含多个实体，每个都要提取\n"
                "2. 具体化：'大学生' 比 '用户' 好，'AI智能分拣' 比 '技术' 好\n"
                "3. 关系要完整：每对有逻辑关联的实体都建立关系\n"
                "4. structural_gaps 要基于13维度检查缺什么：stakeholder/pain_point/solution/innovation/technology/market/competitor/resource/business_model/execution_step/risk_control/team/evidence\n"
                "5. completeness_score(0-10)：覆盖维度越多分越高\n"
                "6. section_scores: 对每个已出现的维度打分(0-10)\n\n"
                "示例(实际应提取更多):\n"
                '{"entities":[{"id":"e1","label":"6-12岁儿童家长","type":"stakeholder"},'
                '{"id":"e2","label":"编程学习枯燥无反馈","type":"pain_point"},'
                '{"id":"e3","label":"游戏化编程闯关平台","type":"solution"},'
                '{"id":"e4","label":"Scratch积木式编程","type":"technology"},'
                '{"id":"e5","label":"编程猫","type":"competitor"},'
                '{"id":"e6","label":"K12编程教育市场","type":"market"},'
                '{"id":"e7","label":"教师访谈记录","type":"evidence"},'
                '{"id":"e8","label":"订阅制+学校采购","type":"business_model"}],'
                '"relationships":[{"source":"e1","target":"e2","relation":"面临"},'
                '{"source":"e3","target":"e2","relation":"解决"},'
                '{"source":"e3","target":"e4","relation":"基于"},'
                '{"source":"e5","target":"e3","relation":"竞争"},'
                '{"source":"e7","target":"e2","relation":"验证"}],'
                '"structural_gaps":["缺少执行步骤","缺少风控措施","缺少团队介绍"],'
                '"content_strengths":["目标用户清晰","痛点有证据支撑"],'
                '"completeness_score":5,'
                '"section_scores":{"stakeholder":8,"pain_point":7,"solution":6,"technology":5,"competitor":4,"market":3,"evidence":6,"business_model":4},'
                '"insight":"项目方向明确，用户-痛点-方案链条清晰，但缺少执行路径和风控"}\n\n'
                "要求：尽力提取，目标是完整描绘学生项目的知识图谱。即使信息模糊也要提取，用'(待明确)'标注。"
                + _known_summary
            ),
            user_prompt=(
                f"学生本轮内容:\n{msg[:4000]}"
                + _hist_block
            ),
            model=settings.llm_fast_model,
            temperature=0.15,
        )
        if not kg or not kg.get("entities"):
            return {"kg_analysis": _default_kg()}
        return {"kg_analysis": kg}

    def _task_web(n_results: int = 3):
        from app.services.web_search import web_search
        ws = web_search(msg, intent, max_results=n_results)
        return {"web_search_result": ws}

    def _task_hyper_teaching():
        if not _hypergraph_service:
            logger.info("hyper_teaching: skipped — no hypergraph_service")
            return {"hypergraph_insight": {}}
        try:
            h = _hypergraph_service.insight(
                category=cat, rule_ids=rule_ids,
                preferred_edge_types=preferred_edge_types,
                limit=12 if intent == "pressure_test" else 10,
            )
            _n_edges = len(h.get("edges", [])) if isinstance(h, dict) else 0
            logger.info("hyper_teaching: ok=%s edges=%d cat=%s rules=%s",
                        h.get("ok"), _n_edges, cat, rule_ids[:5])
            return {"hypergraph_insight": h}
        except Exception as exc:
            logger.warning("Hypergraph insight failed: %s", exc)
            return {"hypergraph_insight": {}}

    # ── Data maturity assessment (from conversation history, BEFORE any tasks) ──
    is_project_intent = intent != "general_chat" and not _should_use_focused_mode(state)
    run_kg = is_file or len(msg) > 30 or (is_project_intent and len(msg) > 12)

    _prev_entity_count = 0
    _prev_rule_count = len(rules)
    for _hm in state.get("conversation_messages", []):
        _ht = _hm.get("agent_trace") if isinstance(_hm, dict) else None
        if isinstance(_ht, dict):
            _hkg = _ht.get("kg_analysis")
            if isinstance(_hkg, dict):
                _prev_entity_count += len(_hkg.get("entities", []))

    _DATA_MATURITY_ENTITY_THRESHOLD = 5
    _DATA_MATURITY_RULE_THRESHOLD = 2
    _data_maturity = (
        "hot" if _prev_entity_count >= 12 and _prev_rule_count >= 3
        else "warm" if _prev_entity_count >= _DATA_MATURITY_ENTITY_THRESHOLD or _prev_rule_count >= _DATA_MATURITY_RULE_THRESHOLD
        else "cold"
    )

    # Web search decision (same logic as before)
    intent_spec = INTENTS.get(intent, {})
    msg_wants_web = any(w in msg for w in _WEB_SIGNAL_WORDS)
    fact_check_needed = any(w in msg for w in _FACT_CHECK_SIGNALS)
    need_web = msg_wants_web or fact_check_needed or intent_spec.get("need_web", False)
    if mode == "coursework":
        if intent in ("market_competitor", "idea_brainstorm"):
            need_web = True
        elif intent in ("learning_concept", "business_model"):
            if _has_explicit_project_context(msg) or msg_wants_web or fact_check_needed:
                need_web = True
    if mode == "learning" and intent in ("project_diagnosis", "business_model", "pressure_test", "market_competitor"):
        if fact_check_needed or any(w in msg.lower() for w in _PROJECT_FACT_GROUNDING_SIGNALS):
            need_web = True
    if mode == "competition":
        if intent in ("competition_prep", "market_competitor"):
            need_web = True
        elif intent == "project_diagnosis" and (
            fact_check_needed or msg_wants_web
            or any(w in msg.lower() for w in _PROJECT_FACT_GROUNDING_SIGNALS)
        ):
            need_web = True

    # ════════════════════════════════════════════════════════════════
    # LAYER 0: Foundation (always fast — RAG + KG)   timeout: 25s
    # ════════════════════════════════════════════════════════════════
    l0_tasks: list[Callable] = [_task_rag]
    if run_kg:
        l0_tasks.append(_task_kg)
    if need_web:
        web_n = intent_spec.get("web_results", 3)
        if intent == "market_competitor":
            web_n = max(web_n, 5)
        l0_tasks.append(lambda n=web_n: _task_web(n))

    logger.info(
        "gather L0[foundation]: intent=%s maturity=%s prev_entities=%d prev_rules=%d tasks=%s",
        intent, _data_maturity, _prev_entity_count, _prev_rule_count,
        [fn.__name__ for fn in l0_tasks],
    )

    with ThreadPoolExecutor(max_workers=max(1, len(l0_tasks))) as pool:
        future_map = {pool.submit(fn): fn.__name__ for fn in l0_tasks}
        try:
            for future in as_completed(future_map, timeout=55):
                name = future_map[future]
                try:
                    collected.update(future.result())
                except Exception as exc:
                    logger.warning("gather L0 %s error: %s", name, exc)
        except TimeoutError:
            done_names = [future_map[f] for f in future_map if f.done()]
            pending_names = [future_map[f] for f in future_map if not f.done()]
            logger.warning("gather L0 timed out (55s) — done=%s pending=%s", done_names, pending_names)
            for f in future_map:
                if not f.done():
                    f.cancel()

    # ════════════════════════════════════════════════════════════════
    # INTER-LAYER: Entity merge + maturity refinement (sync, <5ms)
    # ════════════════════════════════════════════════════════════════
    kg = collected.get("kg_analysis", _default_kg())
    conv_messages = state.get("conversation_messages") or []
    accumulated_entities, accumulated_rels, new_entity_count = _merge_historical_entities(
        current_entities=kg.get("entities", []),
        current_rels=kg.get("relationships", []),
        conversation_messages=conv_messages,
    )
    _maturity_info = _assess_project_maturity(
        message=state.get("message", ""),
        exploration_state=state.get("exploration_state"),
        entity_count=len(accumulated_entities),
        conversation_messages=conv_messages,
        intent_shape=_normalize_intent_shape(state.get("intent_shape", "single")),
        is_file=is_file,
    )
    incremental_stats = {
        "total_accumulated": len(accumulated_entities),
        "new_this_turn": new_entity_count,
        "total_rels": len(accumulated_rels),
        "project_maturity": _maturity_info.get("project_maturity", "exploring"),
        "readiness_score": _maturity_info.get("readiness_score", 0),
        "message_chars": _maturity_info.get("char_len", 0),
        "filled_slots": _maturity_info.get("filled_slots", 0),
        "vague_hits": _maturity_info.get("vague_hits", 0),
        "concrete_hits": _maturity_info.get("concrete_hits", 0),
    }
    logger.info(
        "incremental KG: %d total entities (%d new), %d rels, maturity=%s, readiness=%s",
        len(accumulated_entities), new_entity_count, len(accumulated_rels),
        incremental_stats.get("project_maturity"), incremental_stats.get("readiness_score"),
    )

    _actual_entity_count = len(accumulated_entities)
    _actual_rule_count = len(rules)

    # ── Progressive complexity: 渐进式引入复杂工具 ──
    # 超图教学洞察 (hyper_teaching): 只需有规则触发即可 → 基于规则的案例启发
    # 超图学生分析 (hyper_student):  需要 ≥5 实体 → 需要足够的结构化信息
    # Neo4j 图搜索:                需要 ≥2 实体 → 早期也能搜到案例启发
    _PROJECT_MATURITY_THRESHOLD = 5

    _hyper_teaching_intents = (
        "project_diagnosis", "evidence_check", "competition_prep",
        "pressure_test", "business_model", "idea_brainstorm",
        "market_competitor", "team_execution", "growth_strategy",
        "funding_investment", "company_operations", "startup_execution",
    )

    # 超图教学洞察：只要是项目相关intent就运行——insight()本身用category+rules搜索
    _need_hyper_teaching = bool(
        _hypergraph_service
        and (is_file or is_project_intent or intent in _hyper_teaching_intents)
    )
    _need_hyper_student = bool(
        _hypergraph_service
        and is_project_intent
        and (
            incremental_stats.get("project_maturity") == "mature"
            or _actual_entity_count >= 5
            or (
                _actual_entity_count >= 3
                and int(incremental_stats.get("filled_slots", 0) or 0) >= 3
                and int(incremental_stats.get("concrete_hits", 0) or 0) >= 2
            )
        )
    )
    # Neo4j 图搜索门槛更低：只要有2个实体就触发，不用等成熟期
    # 探索期也能从案例库的结构化图谱中得到启发
    _need_neo4j_graph = (
        _graph_service is not None
        and len(kg.get("entities", [])) >= 1
        and is_project_intent
        and _actual_entity_count >= 2
    )

    # ════════════════════════════════════════════════════════════════
    # LAYER 1: Conditional heavy ops (parallel, only when mature ≥5 entities)
    #   探索期: 只用 KG+RAG 轻量引导
    #   成熟期: 加入超图+Neo4j深度图搜索
    # ════════════════════════════════════════════════════════════════
    _maturity_label = str(incremental_stats.get("project_maturity") or "exploring")
    logger.info(
        "gather progressive: entities=%d rules=%d maturity=%s → hyper_teaching=%s hyper_student=%s neo4j_graph=%s",
        _actual_entity_count, _actual_rule_count, _maturity_label,
        _need_hyper_teaching, _need_hyper_student, _need_neo4j_graph,
    )

    l1_tasks: dict[str, Callable] = {}
    if _need_hyper_teaching:
        l1_tasks["hyper_teaching"] = _task_hyper_teaching
    if _need_hyper_student:
        def _task_hyper_student():
            try:
                if _hypergraph_service is not None:
                    return {"hypergraph_student": _hypergraph_service.analyze_student_content(
                        entities=accumulated_entities, relationships=accumulated_rels,
                        structural_gaps=kg.get("structural_gaps"), category=cat,
                    )}
                else:
                    return {"hypergraph_student": _standalone_hypergraph_analysis(
                        entities=accumulated_entities, relationships=accumulated_rels,
                        structural_gaps=kg.get("structural_gaps"),
                    )}
            except Exception as exc:
                logger.warning("Hypergraph student analysis failed: %s", exc)
                return {"hypergraph_student": {}}
        l1_tasks["hyper_student"] = _task_hyper_student
    if _need_neo4j_graph:
        def _task_neo4j_graph():
            try:
                ents = kg.get("entities", [])
                labels = [str(e.get("label", "")) for e in ents if isinstance(e, dict)][:12]
                types = [str(e.get("type", "")) for e in ents if isinstance(e, dict)][:12]
                existing_ids = {c.get("case_id", "") for c in (collected.get("rag_cases") or [])}
                logger.info(
                    "Neo4j graph search: labels=%s types=%s exclude=%d",
                    labels[:5], types[:5], len(existing_ids),
                )
                hits = _graph_service.search_by_dimension_entities(
                    entity_labels=labels, entity_types=types,
                    exclude_ids=list(existing_ids | (_history_case_ids or set())), limit=4,
                )
                logger.info("Neo4j graph search result: %d hits", len(hits))
                return {"neo4j_graph_hits": hits}
            except Exception as exc:
                logger.warning("Neo4j graph search failed: %s", exc)
                return {"neo4j_graph_hits": []}
        l1_tasks["neo4j_graph"] = _task_neo4j_graph

    hyper_student: dict = {}
    neo4j_graph_hits: list[dict] = []

    if l1_tasks:
        logger.info(
            "gather L1[conditional]: tasks=%s (entities=%d rules=%d)",
            list(l1_tasks.keys()), _actual_entity_count, _actual_rule_count,
        )
        with ThreadPoolExecutor(max_workers=max(1, len(l1_tasks))) as pool:
            future_map_l1 = {pool.submit(fn): name for name, fn in l1_tasks.items()}
            try:
                for future in as_completed(future_map_l1, timeout=45):
                    name = future_map_l1[future]
                    try:
                        result = future.result()
                        if name == "hyper_student":
                            hyper_student = result.get("hypergraph_student", {})
                        elif name == "neo4j_graph":
                            neo4j_graph_hits = result.get("neo4j_graph_hits", [])
                        else:
                            collected.update(result)
                    except Exception as exc:
                        logger.warning("gather L1 %s error: %s", name, exc)
            except TimeoutError:
                done_names = [future_map_l1[f] for f in future_map_l1 if f.done()]
                pending_names = [future_map_l1[f] for f in future_map_l1 if not f.done()]
                logger.warning("gather L1 timed out (45s) — done=%s pending=%s", done_names, pending_names)
                for f in future_map_l1:
                    if not f.done():
                        f.cancel()
    else:
        logger.info(
            "gather L1[skipped]: data not mature (entities=%d rules=%d) — fast path",
            _actual_entity_count, _actual_rule_count,
        )

    # ── Graph→RAG bridge (only when L1 graph search returned hits) ──
    if neo4j_graph_hits and _rag is not None and _rag.case_count > 0:
        try:
            rag_cases_list = list(collected.get("rag_cases") or [])
            existing_case_ids = {c.get("case_id", "") for c in rag_cases_list}
            graph_pids = [
                h["project_id"] for h in neo4j_graph_hits
                if h.get("project_id") and h["project_id"] not in existing_case_ids
            ]
            if graph_pids:
                for gpid in graph_pids[:3]:
                    matched = _rag.retrieve(gpid, top_k=1)
                    for mc in matched:
                        if mc.get("case_id") == gpid or gpid.lower() in str(mc.get("project_name", "")).lower():
                            gh_meta = next((h for h in neo4j_graph_hits if h["project_id"] == gpid), {})
                            mc["graph_retrieved"] = True
                            mc["matched_dimensions"] = gh_meta.get("matched_dimensions", [])
                            mc["matched_nodes"] = gh_meta.get("matched_nodes", [])
                            mc["match_sources"] = gh_meta.get("match_sources", [])
                            rag_cases_list.append(mc)
                            existing_case_ids.add(mc.get("case_id", ""))
                            break
                if any(c.get("graph_retrieved") for c in rag_cases_list):
                    collected["rag_cases"] = rag_cases_list
                    collected["rag_context"] = _rag.format_for_llm(rag_cases_list)
                    logger.info("Graph→RAG bridge: merged %d graph cases",
                                sum(1 for c in rag_cases_list if c.get("graph_retrieved")))
        except Exception as exc:
            logger.warning("Graph→RAG bridge failed: %s", exc)

    # ── RAG-Hypergraph bridge: if coverage is low, do supplementary RAG search ──
    _hyper_driven = False
    if (
        _rag is not None
        and _rag.case_count > 0
        and isinstance(hyper_student, dict)
        and hyper_student.get("ok")
        and hyper_student.get("coverage_score", 10) < 5
    ):
        _DIM_KEYWORD_MAP = {
            "evidence": "证据 验证 数据支撑",
            "competitor": "竞品 替代方案 竞争",
            "market": "市场规模 TAM 目标市场",
            "business_model": "商业模式 盈利 收费",
            "stakeholder": "目标用户 用户画像",
            "risk": "风险 合规",
            "channel": "获客 渠道 推广",
        }
        hyper_missing_dims = [
            str(m.get("dimension", "")) for m in hyper_student.get("missing_dimensions", [])
            if isinstance(m, dict) and m.get("importance") in ("极高", "高")
        ]
        boost_keywords: list[str] = []
        for md in hyper_missing_dims[:3]:
            for dim_key, kws in _DIM_KEYWORD_MAP.items():
                if dim_key in md or md in kws:
                    boost_keywords.append(kws.split()[0])
                    break
        if boost_keywords:
            try:
                existing_ids = {c.get("case_id", "") for c in (collected.get("rag_cases") or [])}
                boost_query = msg[:300] + " " + " ".join(boost_keywords)
                extra_cases = _rag.retrieve(boost_query, top_k=2, exclude_ids=existing_ids | (_history_case_ids or set()))
                rag_cases_list = list(collected.get("rag_cases") or [])
                for ec in extra_cases:
                    if ec.get("case_id") not in existing_ids and len(rag_cases_list) < 7:
                        ec["hyper_driven"] = True
                        rag_cases_list.append(ec)
                        _hyper_driven = True
                if _hyper_driven:
                    from app.services.rag_engine import RagEngine
                    collected["rag_cases"] = rag_cases_list
                    collected["rag_context"] = _rag.format_for_llm(rag_cases_list)
                    collected["rag_enrichment_insight"] = RagEngine.format_enrichment_insight(rag_cases_list)
                    logger.info("Hyper-driven RAG boost: added %d cases for missing dims %s",
                                sum(1 for c in rag_cases_list if c.get("hyper_driven")), hyper_missing_dims)
            except Exception as exc:
                logger.warning("Hyper-driven RAG boost failed: %s", exc)

    if _hyper_driven:
        kb_util = collected.get("kb_utilization", {})
        if isinstance(kb_util, dict):
            kb_util["hyper_driven_search"] = True
            kb_util["hyper_driven_dims"] = hyper_missing_dims[:3]
            collected["kb_utilization"] = kb_util

    # ── Merge dual-channel info into kb_utilization ──
    kb_util_final = collected.get("kb_utilization", {})
    if isinstance(kb_util_final, dict):
        rag_cases_for_trace = collected.get("rag_cases") or []
        kb_util_final["dual_channel"] = {
            "vector_hits": len(rag_cases_for_trace),
            "graph_hits": len(neo4j_graph_hits),
            "graph_details": [
                {
                    "project_id": h.get("project_id", ""),
                    "project_name": h.get("project_name", ""),
                    "category": h.get("category", ""),
                    "matched_dimensions": h.get("matched_dimensions", []),
                    "matched_nodes": h.get("matched_nodes", []),
                    "match_sources": h.get("match_sources", []),
                    "context": h.get("context", {}),
                }
                for h in neo4j_graph_hits[:4]
            ],
        }
        kb_util_final["incremental_stats"] = incremental_stats
        collected["kb_utilization"] = kb_util_final

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
    pressure_trace = _build_pressure_test_trace(
        diag_data, strategies, collected.get("hypergraph_insight", {}), msg,
        consistency_issues=hyper_student.get("consistency_issues", []) if isinstance(hyper_student, dict) else [],
    )

    # V2: refine dimension activations with actual data
    dim_activations = dict(state.get("dim_activations", {}))
    if dim_activations:
        dim_activations = _refine_dim_activations(
            dim_activations, diag_data, kg,
            collected.get("rag_cases"),
            hyper_student if isinstance(hyper_student, dict) else None,
        )

    # V2: update exploration state with KG entities
    exploration_state = _update_exploration_state(
        state.get("exploration_state"),
        msg,
        kg.get("entities") if isinstance(kg, dict) else None,
        state.get("conversation_messages"),
    )

    # V2: Insight Engine — run in parallel, skip for trivial intents
    web_facts: list = []
    hyper_narrative = ""
    case_transfer_insight = ""
    _insight_tasks: list[tuple[str, Callable]] = []
    _intent = state.get("intent", "")
    _skip_insight = _intent in ("general_chat", "out_of_scope", "learning_concept")
    if not _skip_insight:
        ws_result = collected.get("web_search_result", {})
        if ws_result.get("searched"):
            _insight_tasks.append(("web_facts", lambda: _extract_facts_from_web(ws_result, msg)))
        if isinstance(hyper_student, dict) and hyper_student.get("ok"):
            _insight_tasks.append(("hyper_narrative", lambda: _narrativize_hypergraph(hyper_student)))
        enriched_cases = collected.get("rag_cases")
        if enriched_cases and any(isinstance(c, dict) and c.get("neo4j_enriched") for c in enriched_cases):
            _insight_tasks.append(("case_transfer", lambda: _generate_case_transfer_insights(enriched_cases, msg)))

    if _insight_tasks:
        with ThreadPoolExecutor(max_workers=len(_insight_tasks)) as _ipool:
            _ifutures = {_ipool.submit(fn): label for label, fn in _insight_tasks}
            try:
                for _if in as_completed(_ifutures, timeout=20):
                    _label = _ifutures[_if]
                    try:
                        _ires = _if.result()
                        if _label == "web_facts" and isinstance(_ires, list):
                            web_facts = _ires
                        elif _label == "hyper_narrative" and isinstance(_ires, str):
                            hyper_narrative = _ires
                        elif _label == "case_transfer" and isinstance(_ires, str):
                            case_transfer_insight = _ires
                    except Exception as _iexc:
                        logger.warning("insight %s failed: %s", _label, _iexc)
            except TimeoutError:
                logger.warning("insight engine timed out (20s), skipping remaining")

    return {
        "diagnosis": diag_data,
        "next_task": next_task,
        "category": cat,
        "kg_analysis": kg,
        "rag_cases": collected.get("rag_cases", []),
        "rag_context": collected.get("rag_context", ""),
        "rag_enrichment_insight": collected.get("rag_enrichment_insight", ""),
        "kb_utilization": collected.get("kb_utilization", {}),
        "neo4j_graph_hits": neo4j_graph_hits,
        "incremental_stats": incremental_stats,
        "web_search_result": collected.get("web_search_result", {}),
        "hypergraph_insight": collected.get("hypergraph_insight", {}),
        "hypergraph_student": hyper_student,
        "hyper_consistency_issues": hyper_student.get("consistency_issues", []) if isinstance(hyper_student, dict) else [],
        "challenge_strategies": strategies,
        "pressure_test_trace": pressure_trace,
        "dim_activations": dim_activations,
        "exploration_state": exploration_state,
        "web_facts": web_facts,
        "hyper_narrative": hyper_narrative,
        "case_transfer_insight": case_transfer_insight,
        "history_knowledge_ctx": _history_knowledge_ctx,
        "_data_maturity": _data_maturity,
        "_l1_hyper_teaching_ran": _need_hyper_teaching,
        "_l1_hyper_student_ran": _need_hyper_student,
        "_l1_neo4j_graph_ran": _need_neo4j_graph,
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


def _truncate_text(text: str, limit: int = 220) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + "…"


def _is_eval_followup_message(text: str) -> bool:
    return any(sig in str(text or "") for sig in _EVALUATION_FOLLOWUP_SIGNALS)


def _is_score_request_message(text: str) -> bool:
    msg = str(text or "")
    return any(sig in msg for sig in _SCORING_SIGNALS) or any(
        sig in msg for sig in ("打多少分", "能打多少分", "多少分", "几分", "扣分", "最致命", "优先改哪里")
    )


def _conversation_continuation_mode(state: dict) -> str:
    msg = str(state.get("message") or "")
    conv = state.get("conversation_messages", []) or []
    prev_intent = _infer_prev_intent(conv) if conv else None
    if not conv:
        return "new_analysis"
    if _is_score_request_message(msg) or _is_eval_followup_message(msg):
        return "followup_scoring"
    if any(sig in msg for sig in ("改哪里", "怎么改", "改成", "重写", "补哪里", "先补")):
        return "followup_revision"
    if prev_intent and len(msg) < 140:
        return "followup_deepening"
    return "new_analysis"


def _build_conversation_state_summary(state: dict) -> str:
    conv = state.get("conversation_messages", []) or []
    hist = str(state.get("history_context") or "").strip()
    mode = _conversation_continuation_mode(state)
    recent_users = [
        _truncate_text(str(m.get("content") or ""), 140)
        for m in conv
        if isinstance(m, dict) and m.get("role") == "user" and str(m.get("content") or "").strip()
    ]
    recent_assistants = [
        _truncate_text(str(m.get("content") or ""), 220)
        for m in conv
        if isinstance(m, dict) and m.get("role") == "assistant" and str(m.get("content") or "").strip()
    ]
    parts: list[str] = [f"continuation_mode={mode}"]
    assistant_traces = [
        m.get("agent_trace")
        for m in conv
        if isinstance(m, dict) and m.get("role") == "assistant" and isinstance(m.get("agent_trace"), dict)
    ]
    if recent_users:
        parts.append(f"上一轮学生问题: {recent_users[-1]}")
    if recent_assistants:
        parts.append(f"上一轮AI回复摘要: {recent_assistants[-1]}")
    if len(recent_assistants) >= 2:
        parts.append(f"再上一轮AI回复摘要: {recent_assistants[-2]}")
    if assistant_traces:
        last_trace = assistant_traces[-1]
        last_diag = last_trace.get("diagnosis", {}) if isinstance(last_trace.get("diagnosis"), dict) else {}
        last_next = last_trace.get("next_task", {}) if isinstance(last_trace.get("next_task"), dict) else {}
        last_orch = last_trace.get("orchestration", {}) if isinstance(last_trace.get("orchestration"), dict) else {}
        if last_diag.get("bottleneck"):
            parts.append(f"上一轮核心判断: {_truncate_text(str(last_diag.get('bottleneck')), 160)}")
        if last_orch.get("resolved_agents"):
            parts.append("上一轮调用角色: " + " / ".join(str(x) for x in (last_orch.get("resolved_agents") or [])[:5]))
        grader_trace = last_trace.get("role_agents", {}).get("grader", {}) if isinstance(last_trace.get("role_agents"), dict) else {}
        advisor_trace = last_trace.get("role_agents", {}).get("advisor", {}) if isinstance(last_trace.get("role_agents"), dict) else {}
        if grader_trace.get("analysis"):
            parts.append(f"上一轮评分官摘要: {_truncate_text(str(grader_trace.get('analysis')), 160)}")
        elif advisor_trace.get("analysis"):
            parts.append(f"上一轮竞赛顾问摘要: {_truncate_text(str(advisor_trace.get('analysis')), 160)}")
        if last_next.get("title") or last_next.get("description"):
            parts.append(
                "上一轮焦点任务: "
                + _truncate_text(str(last_next.get("title") or last_next.get("description") or ""), 140)
            )
    if hist:
        parts.append(f"历史摘要: {_truncate_text(hist, 220)}")
    return "\n".join(parts)


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
    tm = hs.get("template_matches", [])
    incomplete = [t for t in tm if t.get("status") != "complete"]
    if incomplete:
        first = incomplete[0]
        parts.append(
            f"未完成的逻辑闭环: {first.get('name','')} 缺少 {', '.join(first.get('missing_dimensions', [])[:3])}"
        )
    warnings = hs.get("pattern_warnings", [])
    if warnings:
        parts.append(f"风险模式匹配: {warnings[0].get('warning','')}")
    strengths = hs.get("pattern_strengths", [])
    if strengths:
        parts.append(f"优势模式: {strengths[0].get('note','')}")
    issues = hs.get("consistency_issues", [])
    if issues:
        parts.append(f"一致性诊断: {issues[0].get('message','')}")
    return "\n".join(parts)


def _fmt_graph_hits_ctx(hits: list[dict]) -> str:
    """Format neo4j_graph_hits into a concise LLM-readable context string."""
    if not hits:
        return ""
    _SRC_LABELS = {"shared_node": "共享节点", "complement": "互补结构", "keyword": "关键词"}
    parts = []
    for gh in hits[:4]:
        dims = ", ".join(gh.get("matched_dimensions", [])[:4])
        nodes = "; ".join(gh.get("matched_nodes", [])[:4])
        sources = gh.get("match_sources", [])
        src_str = "+".join(_SRC_LABELS.get(s, s) for s in sources) if sources else ""
        line = f"- {gh.get('project_name', '')}  维度:[{dims}]  节点:[{nodes}]"
        if src_str:
            line += f"  来源:{src_str}"
        parts.append(line)
    return "知识图谱跨项目关联(图遍历):\n" + "\n".join(parts) + "\n"


def _fmt_hyper_for_agent(
    hs: dict,
    hyper_insight: dict,
    role: str,
    incremental_stats: dict | None = None,
) -> str:
    """Build a targeted hypergraph context string for a specific agent role.

    Each agent only receives the hypergraph signals relevant to its function,
    keeping prompts focused and avoiding information overload.
    """
    edges = (hyper_insight or {}).get("edges", []) if isinstance(hyper_insight, dict) else []
    hi_summary = str((hyper_insight or {}).get("summary", "")).strip() if isinstance(hyper_insight, dict) else ""
    hi_top_signals = (hyper_insight or {}).get("top_signals", []) if isinstance(hyper_insight, dict) else []
    hi_key_dims = (hyper_insight or {}).get("key_dimensions", []) if isinstance(hyper_insight, dict) else []

    has_student = hs and hs.get("ok")
    has_insight = bool(edges) or bool(hi_summary)

    if not has_student and not has_insight:
        return ""

    # 探索期：只有 hyper_insight 没有 hyper_student → 给出纯教学超边启发
    if not has_student and has_insight:
        parts: list[str] = ["[超图教学洞察·探索期]"]
        if incremental_stats and incremental_stats.get("total_accumulated", 0) > 0:
            parts.append(f"[累积{incremental_stats['total_accumulated']}个实体]")
        if hi_summary:
            parts.append(f"超图摘要: {hi_summary[:180]}")
        for sig in hi_top_signals[:3]:
            parts.append(f"关键信号: {str(sig)[:100]}")
        for edge in edges[:4]:
            if isinstance(edge, dict):
                note = str(edge.get("teaching_note", "") or "")[:80]
                family = edge.get("family_label", "") or edge.get("type", "")
                parts.append(f"教学超边[{family}]: {note}")
        for dim in hi_key_dims[:3]:
            parts.append(f"关键维度: {str(dim)[:80]}")
        return "\n".join(parts)

    parts: list[str] = []
    if incremental_stats and incremental_stats.get("total_accumulated", 0) > 0:
        total = incremental_stats["total_accumulated"]
        new = incremental_stats.get("new_this_turn", 0)
        parts.append(f"[累积{total}个实体分析" + (f", 本轮+{new}新" if new else "") + "]")
    cov = hs.get("coverage_score", 0)
    tm = hs.get("template_matches", [])
    complete_count = sum(1 for t in tm if t.get("status") == "complete")
    total_tm = len(tm) or 20
    issues = hs.get("consistency_issues", [])
    warnings = hs.get("pattern_warnings", [])
    missing = hs.get("missing_dimensions", [])

    value_loops = hs.get("value_loops", [])
    llm_insight_text = str(hs.get("llm_insight", "") or "").strip()

    if role == "coach":
        parts.append(f"超图维度覆盖: {cov}/10")
        incomplete = [t for t in tm if t.get("status") != "complete"][:2]
        for t in incomplete:
            miss = ", ".join(t.get("missing_dimensions", [])[:3])
            parts.append(f"未闭合逻辑环「{t.get('name','')}」缺: {miss}")
        for ci in issues[:2]:
            parts.append(f"一致性问题: {ci.get('message','')}")
            pqs = ci.get("pressure_questions", [])
            if pqs:
                parts.append(f"  → 可追问: {pqs[0]}")
        if value_loops:
            loop_summary = "; ".join(
                f"{'✓' if vl.get('complete') else '✗'}{vl.get('chain','')}"
                for vl in value_loops
            )
            parts.append(f"价值链路: {loop_summary}")
        if llm_insight_text:
            parts.append(f"超图拓扑洞察: {llm_insight_text[:150]}")

    elif role == "analyst":
        _risk_rules = {"G1", "G3", "G5", "G8", "G9", "G18", "G12", "G20"}
        for w in warnings[:3]:
            parts.append(f"超图风险模式: {w.get('warning','')}")
        risk_issues = [ci for ci in issues if ci.get("id", "").split("_")[0] in _risk_rules]
        for ci in (risk_issues or issues)[:3]:
            parts.append(f"一致性风险({ci.get('id','')}): {ci.get('message','')}")
        for edge in edges[:3]:
            if isinstance(edge, dict):
                note = str(edge.get("teaching_note", "") or "")[:60]
                parts.append(f"教学超边: {edge.get('type','')}: {note}")
        if (hyper_insight or {}).get("summary"):
            parts.append(f"超图摘要: {str(hyper_insight['summary'])[:120]}")
        crit_missing = [m for m in missing if m.get("importance") in ("极高", "高")]
        if crit_missing:
            parts.append("关键缺失: " + "; ".join(
                f"{m['dimension']}—{m['recommendation']}" for m in crit_missing[:3]
            ))
        broken_loops = [vl for vl in value_loops if not vl.get("complete")]
        if broken_loops:
            parts.append("断裂链路: " + "; ".join(vl.get("chain", "") for vl in broken_loops[:3]))
        if llm_insight_text:
            parts.append(f"拓扑洞察: {llm_insight_text[:120]}")

    elif role == "advisor":
        parts.append(f"超图闭环完成度: {complete_count}/{total_tm}")
        parts.append(f"维度覆盖: {cov}/10" + (" (低于竞赛基准8/10)" if cov < 8 else " (达标)"))
        critical_templates = {"T1_user_pain_solution_bm", "T10_user_pain_solution_evidence", "T19_loop_full"}
        for t in tm:
            if t.get("id") in critical_templates and t.get("status") != "complete":
                miss = ", ".join(t.get("missing_dimensions", [])[:3])
                parts.append(f"竞赛关键闭环缺失「{t.get('name','')}」: 缺 {miss}")
        if warnings:
            parts.append(f"风险模式: {warnings[0].get('warning','')[:80]}")

    elif role == "grader":
        parts.append(f"超图维度覆盖: {cov}/10, 一致性问题{len(issues)}项, 闭环{complete_count}/{total_tm}")

    elif role == "planner":
        for m in missing[:3]:
            parts.append(f"待补维度: {m.get('dimension','')}({m.get('importance','')}) — {m.get('recommendation','')}")
        for ci in issues[:3]:
            pqs = ci.get("pressure_questions", [])
            if pqs:
                parts.append(f"行动线索({ci.get('id','')}): {pqs[0]}")
        incomplete = [t for t in tm if t.get("status") == "partial"][:2]
        for t in incomplete:
            miss = ", ".join(t.get("missing_dimensions", [])[:2])
            parts.append(f"可推进闭环「{t.get('name','')}」: 补充 {miss}")

    elif role == "tutor":
        if cov > 0:
            parts.append(f"学生当前项目维度覆盖: {cov}/10")

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


def _has_explicit_project_context(text: str) -> bool:
    content = str(text or "")
    return any(
        sig in content
        for sig in (
            "我们做", "我们的项目", "我们项目", "项目叫", "项目是",
            "目标用户", "核心功能", "推广", "收费", "竞品", "路演",
            "答辩", "团队", "产品", "场景", "痛点", "解决方案",
        )
    )


def _is_generic_learning_question(text: str) -> bool:
    content = str(text or "").strip()
    lowered = content.lower()
    if not content or len(content) > 200:
        return False
    explain_signals = (
        "什么是", "什么叫", "是什么意思", "不太理解", "不理解", "有点不懂",
        "讲清楚", "解释一下", "怎么理解", "怎么判断", "怎么算", "怎么做",
        "举个例子", "简单例子", "通俗", "区别", "到底",
    )
    topic_signals = (
        "商业模式", "商业价值", "价值主张", "盈利模式",
        "tam", "sam", "som", "mvp", "股权",
        "用户画像", "护城河", "单位经济", "cac", "ltv",
        "需求验证", "用户验证", "产品原型",
    )
    project_signals = (
        "我们做", "我们的项目", "我们项目", "项目叫", "项目是",
        "目标用户", "核心功能", "推广", "收费", "竞品", "路演", "答辩",
    )
    return (
        any(sig in content for sig in explain_signals)
        and any(sig in lowered for sig in topic_signals)
        and not any(sig in content for sig in project_signals)
    )


def _is_coursework_professional_question(text: str) -> bool:
    content = str(text or "").strip()
    lowered = content.lower()
    if not content or len(content) > 250 or _has_explicit_project_context(content):
        return False
    ask_signals = (
        "什么是", "什么叫", "是什么意思", "不太理解", "不理解", "有点不懂",
        "讲清楚", "解释一下", "怎么理解", "怎么判断", "怎么算", "怎么做",
        "举个例子", "简单例子", "通俗", "区别", "有什么区别", "为什么",
        "到底", "怎么用", "判断框架", "怎么验证",
    )
    topic_signals = (
        "商业模式", "商业价值", "价值主张", "盈利模式", "用户画像",
        "mvp", "商业画布", "lean canvas",
        "tam", "sam", "som", "cac", "ltv", "单位经济", "护城河", "定价", "股权",
        "增长飞轮", "留存", "转化", "北极星指标", "需求验证", "竞品分析",
        "用户验证", "产品原型", "最小可行", "价值闭环",
    )
    return any(sig in content for sig in ask_signals) and any(sig in lowered for sig in topic_signals)


def _extract_learning_keywords(text: str) -> list[str]:
    candidates = [
        "tam", "sam", "som", "mvp", "股权", "互联网+", "挑战杯", "商业模式",
        "用户画像", "价值主张", "定价", "路演", "团队", "融资", "护城河",
        "单位经济", "cac", "ltv", "需求验证", "竞品分析", "北极星指标",
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
    generic_learning = _is_generic_learning_question(msg) or _is_coursework_professional_question(msg)
    explicit_project_context = _has_explicit_project_context(msg)
    use_project_grounding = explicit_project_context or not generic_learning
    conv_ctx = _build_conv_ctx(state, limit=4) if use_project_grounding else ""
    rag_ctx = state.get("rag_context", "") if use_project_grounding else ""
    ws_ctx = _fmt_ws(state.get("web_search_result", {})) if use_project_grounding else ""
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

    if _graph_service and use_project_grounding:
        keywords = _extract_learning_keywords(msg)
        kg_nodes = _graph_service.search_nodes(keywords, limit_per_keyword=2) if keywords else []
        logger.info("learning_tutor retrieved_kg_nodes=%s", kg_nodes)

    kg_ctx = _fmt_learning_kg_nodes(kg_nodes)
    _tutor_mode_hint = {
        "competition": "你现在还需要帮学生理解这个概念在竞赛评审中的权重和评委判断标准。",
        "learning": "你现在还需要帮学生理解这个概念在项目实操中如何验证，做完后该看什么信号判断自己学会了。",
    }.get(mode, "")
    tutor_comp_hint = _get_competition_hint(state.get("competition_type", ""), "tutor")
    if tutor_comp_hint:
        _tutor_mode_hint += f"\n{tutor_comp_hint}"

    llm_resp = _llm.chat_json(
        system_prompt=(
            "你是课程辅导模式下的真实导师。你的重点不是机械下诊断，而是结合学生当前项目教他怎么想、怎么做。\n"
            + (f"{_tutor_mode_hint}\n" if _tutor_mode_hint else "")
            + "如果学生是在问概念、方法、赛事规则、项目思路或写法，请输出JSON，字段必须包含："
            "current_judgment, method_explanation, teacher_criteria, project_application, common_pitfalls(list), practice_task, observation_point, source_note。\n"
            "要求：\n"
            "- current_judgment 先直接回应学生眼前这个具体困惑，不要一上来背定义或写成报告摘要\n"
            "- method_explanation 解释背后的方法论，要说清楚为什么这样看；必要时补一个反例、边界条件或老师常见追问\n"
            "- teacher_criteria 说明老师/评委通常会用什么标准判断这件事有没有想清楚，帮学生建立判断尺子\n"
            "- project_application 必须把方法落回学生项目；如果信息不够，就说明还差哪块信息会影响判断，不要空讲\n"
            "- 如果学生没有提供明确项目背景，就不要假设“你的项目”“你的产品”是什么；请先用一个公开、简单、人人能懂的创业例子讲清楚，再补一句以后放到项目里时该怎么判断\n"
            "- common_pitfalls 给 2-4 条，必须贴近学生这种场景\n"
            "- practice_task 必须只有一个，且它是“理解方法的小练习”，不是完整项目推进计划；除非学生明确在问验证设计，否则不要泛泛要求做问卷\n"
            "- observation_point 说明学生做这个练习时最该观察什么信号\n"
            "- source_note 用一句话交代你主要参考了案例、联网资料还是本地KG；没有就写“本轮主要依据学生材料判断”\n"
            "- 如果给了本地KG、案例或联网信息，优先使用，不要编造所谓“最新规则”\n"
            "- 对于纯概念题，如果没有明确项目背景，不要硬套本地KG项目案例，更不要编造学生的行业、产品或商业设定\n"
            "- 整体语气像老师在带学生把一道题想透，而不是在宣判项目好坏\n"
        ),
        user_prompt=(
            f"模式: {mode}\n学生问题:\n{msg}\n\n"
            + (f"最近对话:\n{conv_ctx}\n\n" if conv_ctx else "")
            + (f"参考案例:\n{rag_ctx[:500]}\n\n" if rag_ctx else "")
            + (f"联网资料:\n{ws_ctx[:500]}\n\n" if ws_ctx else "")
            + (f"{kg_ctx}\n\n" if kg_ctx else "")
            + "请按要求输出JSON。"
        ),
        model=settings.llm_structured_model,
        temperature=0.25,
    ) if _llm.enabled else None

    if not isinstance(llm_resp, dict):
        llm_resp = {
            "current_judgment": "你现在最需要的，通常不是再多记几个术语，而是先把这个概念放回自己的项目里，看看它究竟在帮你判断哪一个关键环节。",
            "method_explanation": "一个方法论真正有用，不在于定义多完整，而在于它能不能帮你缩小问题范围、识别证据缺口，并指导下一步验证。",
            "teacher_criteria": "真正想清楚的标准，不是你能把名词背出来，而是你能说明它为什么会改变你的判断，并指出你项目里对应的证据或缺口。",
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
            f"## 老师通常会怎么判断你有没有想清楚\n{str(llm_resp.get('teacher_criteria') or '').strip()}\n\n"
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
        f"## 老师通常会怎么判断你有没有想清楚\n{str(llm_resp.get('teacher_criteria') or '').strip()}",
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


_COMP_ONTOLOGY_IDS: dict[str, list[str]] = {
    "internet_plus": [
        "C_competition_rule_internet_plus",
        "C_iplus_business_innovation",
        "C_iplus_social_impact",
        "C_iplus_tam_sam_som",
    ],
    "challenge_cup": [
        "C_competition_rule_challenge_cup",
        "C_challenge_tech_innovation",
        "C_challenge_evidence_rigor",
    ],
    "dachuang": [
        "C_competition_rule_dachuang",
        "C_dachuang_feasibility",
        "C_dachuang_process_record",
    ],
}


def _get_competition_ontology_context(comp_type: str) -> str:
    """Pull competition-specific evaluation criteria from the ontology."""
    from app.services.kg_ontology import ONTOLOGY_NODES
    ids = _COMP_ONTOLOGY_IDS.get(comp_type, [])
    lines: list[str] = []
    for nid in ids:
        node = ONTOLOGY_NODES.get(nid)
        if node:
            lines.append(f"- [{node.label}] {node.description}")
    if not lines:
        return ""
    return "本赛事评审要点：\n" + "\n".join(lines)


_COMPETITION_AGENT_HINTS: dict[str, dict[str, str]] = {
    "internet_plus": {
        "coach": "「互联网+」赛道侧重商业模式创新与盈利可持续性，辅导时引导学生重点论证市场规模(TAM/SAM/SOM)和差异化竞争力。",
        "analyst": "「互联网+」评审关注数据可信度和用户调研质量，分析时着重检验用户数据的采集方法和样本代表性。",
        "advisor": "",
        "grader": "「互联网+」评分标准中商业模式(30%)和市场分析(20%)权重最高，按此侧重评分。",
        "planner": "「互联网+」备赛需准备商业计划书PPT(12-15页)、路演(8分钟+5分钟答辩)、Demo演示，规划时突出里程碑。",
        "tutor": "「互联网+」赛道下讲解概念时优先关联商业模式、市场策略、盈利模式等实战场景。",
    },
    "challenge_cup": {
        "coach": "「挑战杯」侧重科技创新含量与学术深度，辅导时引导学生强调技术难度、学术贡献和原型验证。",
        "analyst": "「挑战杯」评审要求证据链严谨(实验/访谈/数据)，分析时关注方法论的科学性和数据可重复性。",
        "advisor": "",
        "grader": "「挑战杯」评分中科技创新(40%)和调研质量(25%)权重最高，按此侧重评分。",
        "planner": "「挑战杯」需准备详细技术报告、实验记录和原型Demo，规划时突出研究方法和验证步骤。",
        "tutor": "「挑战杯」赛道下讲解概念时优先关联科研方法论、实验设计、技术可行性分析。",
    },
    "dachuang": {
        "coach": "「大创」侧重方案可行性和实际执行能力，辅导时引导学生做小步快跑的MVP验证。",
        "analyst": "「大创」评审关注动手能力和阶段性成果，分析时检查是否有实际原型或用户测试数据。",
        "advisor": "",
        "grader": "「大创」评分中可行性(30%)和创新性(25%)权重最高，按此侧重评分。",
        "planner": "「大创」需要完整的训练计划、分工表和阶段性里程碑，规划时注重可操作性。",
        "tutor": "「大创」赛道下讲解概念时优先关联精益创业、MVP方法论、用户验证等实操技能。",
    },
}


def _get_competition_hint(comp_type: str, agent_role: str) -> str:
    """Get competition-type specific hint for a given agent role."""
    if not comp_type:
        return ""
    hints = _COMPETITION_AGENT_HINTS.get(comp_type, {})
    return hints.get(agent_role, "")


# ═══════════════════════════════════════════════════════════════════
#  V3: Per-dimension LLM call + hyper injection
# ═══════════════════════════════════════════════════════════════════

_DIM_PROMPT_HINTS: dict[str, str] = {
    "status_judgment": "判断项目处于什么阶段、整体逻辑是否通顺。简洁直说，不要写报告。",
    "core_bottleneck": "找到当前最制约项目推进的一到两个瓶颈，解释为什么是瓶颈。",
    "structural_cause": "解释表层问题背后的深层结构性原因，不要只停在表面。",
    "counter_intuitive": "指出学生可能忽略的盲区或过于乐观的假设，用反例或数据支撑。",
    "method_bridge": "讲清楚一个概念或方法论，并桥接回学生的具体项目。",
    "teacher_criteria": "从评审者/老师的视角说明会怎么判断这部分，给出得分区间参考。",
    "external_reference": "引用真实竞品、行业数据或案例来做对比分析。",
    "strategy_directions": "给出2-3条可选策略方向或打法，不要只有一种答案。",
    "action_plan": "拆出本周最该做的1-3件可执行的事和验收标准。",
    "probing_questions": "给出2-4个苏格拉底式追问，帮学生深入思考。",
}


def _fmt_hyper_for_dim(dim: str, hyper_insight: dict | None) -> str:
    """从超图教学超边中筛选与该维度相关的边，返回格式化文本。"""
    if not isinstance(hyper_insight, dict):
        return ""
    edges = hyper_insight.get("edges") or []
    if not edges:
        return ""
    _dim_keywords: dict[str, list[str]] = {
        "status_judgment": ["阶段", "成熟度", "完整度", "覆盖"],
        "core_bottleneck": ["瓶颈", "风险", "缺陷", "不足", "薄弱"],
        "structural_cause": ["结构", "根因", "深层", "系统性"],
        "counter_intuitive": ["盲区", "假设", "反例", "反直觉", "乐观"],
        "method_bridge": ["方法", "框架", "模型", "概念", "理论"],
        "teacher_criteria": ["评分", "评委", "评审", "标准", "得分"],
        "external_reference": ["案例", "竞品", "行业", "数据", "对比"],
        "strategy_directions": ["策略", "方向", "路径", "选择", "打法"],
        "action_plan": ["行动", "执行", "计划", "步骤", "验证"],
        "probing_questions": ["追问", "思考", "深入", "验证"],
    }
    keywords = _dim_keywords.get(dim, [])
    matched = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        note = str(edge.get("teaching_note") or "")
        family = str(edge.get("family_label") or edge.get("type") or "")
        text = f"{family} {note}".lower()
        if any(kw in text for kw in keywords) or len(matched) < 2:
            matched.append(f"[{family}] {note[:100]}")
        if len(matched) >= 3:
            break
    if not matched:
        for edge in edges[:2]:
            if isinstance(edge, dict) and edge.get("teaching_note"):
                matched.append(f"[{edge.get('family_label', '')}] {str(edge['teaching_note'])[:100]}")
    if not matched:
        return ""
    return "超图教学启发:\n" + "\n".join(f"- {m}" for m in matched)


def _build_dim_context(dim: str, state: dict) -> str:
    """为单个维度构建丰富的上下文，确保分析有理有据。"""
    parts: list[str] = []
    kg = state.get("kg_analysis", {}) if isinstance(state.get("kg_analysis"), dict) else {}
    diag = state.get("diagnosis", {}) if isinstance(state.get("diagnosis"), dict) else {}

    # ── 通用上下文（所有维度都能看到）──
    if kg.get("insight"):
        parts.append(f"KG洞察: {kg['insight'][:300]}")
    if diag.get("bottleneck"):
        parts.append(f"诊断瓶颈: {diag['bottleneck'][:200]}")
    gaps = kg.get("structural_gaps", [])
    if gaps:
        parts.append(f"结构缺口: {', '.join(str(g) for g in gaps[:5])}")
    strengths = kg.get("content_strengths", [])
    if strengths:
        parts.append(f"项目优势: {', '.join(str(s) for s in strengths[:4])}")

    # ── RAG案例上下文（所有维度都能参考）──
    rag_ctx = state.get("rag_context", "")
    if rag_ctx:
        parts.append(f"相似案例参考:\n{rag_ctx[:600]}")
    rag_insight = state.get("rag_enrichment_insight", "")
    if rag_insight:
        parts.append(f"案例迁移洞察: {rag_insight[:300]}")

    # ── Neo4j 跨项目图谱启发 ──
    neo4j_hits = state.get("neo4j_graph_hits", [])
    if neo4j_hits:
        neo_parts = []
        for gh in neo4j_hits[:3]:
            if isinstance(gh, dict):
                pname = gh.get("project_name", "")
                dims = ", ".join(gh.get("matched_dimensions", [])[:3])
                ctx_obj = gh.get("context", {})
                solutions = ctx_obj.get("solutions", [])[:2] if isinstance(ctx_obj, dict) else []
                sol_text = f" 方案:{', '.join(solutions)}" if solutions else ""
                neo_parts.append(f"  - {pname}(维度:{dims}{sol_text})")
        if neo_parts:
            parts.append("图谱跨项目启发:\n" + "\n".join(neo_parts))

    # ── 维度专项上下文 ──
    if dim in ("teacher_criteria",):
        rules = diag.get("triggered_rules", []) or []
        if rules:
            rule_summary = "; ".join(
                f"{r.get('name', '')}({r.get('severity', '')})" for r in rules[:5] if isinstance(r, dict)
            )
            parts.append(f"触发规则: {rule_summary}")

    if dim in ("external_reference", "counter_intuitive"):
        web_facts = state.get("web_facts", []) or state.get("web_search_result", {}).get("facts", [])
        if isinstance(web_facts, list):
            for wf in web_facts[:3]:
                if isinstance(wf, dict):
                    parts.append(f"网络数据: {wf.get('fact', str(wf))[:150]}")

    # ── 对话历史 ──
    conv = state.get("conversation_messages", [])
    if conv:
        recent = conv[-4:]
        conv_ctx = "\n".join(
            f"{'学生' if m.get('role') == 'user' else 'AI'}: {str(m.get('content', ''))[:200]}"
            for m in recent if isinstance(m, dict)
        )
        parts.append(f"近期对话:\n{conv_ctx}")

    # ── 超图教学启发 ──
    hyper_ctx = _fmt_hyper_for_dim(dim, state.get("hypergraph_insight"))
    if hyper_ctx:
        parts.append(hyper_ctx)

    return "\n".join(parts)


def _write_dimension(dim: str, state: dict) -> dict:
    """为单个维度生成有深度的分析内容。"""
    dim_info = ANALYSIS_DIMENSIONS.get(dim, {})
    hint = _DIM_PROMPT_HINTS.get(dim, dim_info.get("desc", ""))
    ctx = _build_dim_context(dim, state)
    msg = state.get("message", "")
    mode = state.get("mode", "coursework")

    mode_note = {
        "coursework": "教学引导视角",
        "competition": "评委/竞赛视角",
        "learning": "实操推进视角",
    }.get(mode, "")

    result = _llm.chat_text(
        system_prompt=(
            f"你是「{dim_info.get('label', dim)}」分析专家。{mode_note}\n"
            f"任务：{hint}\n\n"
            "## 分析要求\n"
            "- 200-600字的深度分析，有理有据\n"
            "- 如果上下文中有案例参考或图谱启发，必须引用并对比（'类似项目XX的做法是…'）\n"
            "- 如果有超图教学启发，自然融入分析\n"
            "- 给出具体判断，不要泛泛而谈（不要'需要考虑'、'可以尝试'，要说'你的XX存在YY问题，因为ZZ'）\n"
            "- 不要写标题，不要重复学生原话，不要说'以下是我的分析'\n"
            "- 直接开始分析内容\n"
        ),
        user_prompt=(
            f"学生说：{msg[:1500]}\n\n"
            + (f"背景信息：\n{ctx}\n" if ctx else "")
        ),
        model=settings.llm_synthesis_model,
        temperature=0.3,
    )
    hyper_ctx_sent = _fmt_hyper_for_dim(dim, state.get("hypergraph_insight"))
    return {
        "dim": dim,
        "value": result or "",
        "confidence": 0.75 if result else 0.2,
        "evidence_source": "dim_analysis",
        "writer": DIM_OWNERSHIP.get(dim, {}).get("writer", "coach"),
        "challenges": [],
        "hyper_context_sent": hyper_ctx_sent,
    }


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
    history_knowledge = state.get("history_knowledge_ctx", "")
    hs = state.get("hypergraph_student", {})
    hyper_insight = state.get("hypergraph_insight", {})
    hs_ctx = _fmt_hyper_for_agent(hs, hyper_insight, "coach", incremental_stats=state.get("incremental_stats"))

    mode_hint = {
        "coursework": "当前是课程辅导模式，侧重把方法讲透，帮学生理解判断标准，再落回项目。",
        "competition": "当前是竞赛教练模式，侧重评委视角、证据链完整度和得分影响，语气专业克制。",
        "learning": "当前是项目教练模式，侧重识别当前阶段最关键的瓶颈，用启发式追问推动思考。",
    }.get(mode, "")
    comp_type = state.get("competition_type", "")
    coach_comp_hint = _get_competition_hint(comp_type, "coach")
    if coach_comp_hint:
        mode_hint += f"\n{coach_comp_hint}"

    if mode == "learning" and _is_direct_solution_request(msg):
        return {
            "agent": "项目教练",
            "analysis": _coach_guardrail_reply(state),
            "tools_used": ["diagnosis", "challenge_strategies", "next_task"],
            "hyper_context_sent": hs_ctx,
        }

    # Build neo4j_ctx from enriched RAG cases (unified pipeline)
    neo4j_ctx = ""
    rag_insight = state.get("rag_enrichment_insight", "")
    enriched_cases = [c for c in (state.get("rag_cases") or []) if c.get("neo4j_enriched")]
    if enriched_cases:
        parts_neo = []
        for ec in enriched_cases[:3]:
            name = ec.get("project_name", "")
            cov = ec.get("graph_rubric_covered", [])
            uncov = ec.get("graph_rubric_uncovered", [])
            shared_rules = (ec.get("rule_overlap") or {}).get("shared", [])
            only_student = (ec.get("rule_overlap") or {}).get("only_in_student", [])
            parts_neo.append(
                f"{name}(覆盖{len(cov)}维度/缺{len(uncov)}维度"
                + (f",共同风险:{','.join(shared_rules[:3])}" if shared_rules else "")
                + (f",你独有风险:{','.join(only_student[:2])}" if only_student else "")
                + ")"
            )
        neo4j_ctx = "知识库案例深度对比: " + "; ".join(parts_neo)
        if rag_insight:
            neo4j_ctx += "\n" + rag_insight
    elif _graph_service and kg.get("entities"):
        top_labels = [e["label"] for e in kg["entities"][:5] if e.get("label")]
        try:
            related = _graph_service.find_similar_entities(top_labels, limit=5)
            if related:
                _inc = state.get("incremental_stats", {})
                _is_exploring = _inc.get("project_maturity") == "exploring"
                if _is_exploring:
                    neo4j_ctx = "知识库中与学生想法相关的线索(用于启发引导): " + "; ".join(
                        f"「{r.get('entity','')}」在其他项目中与「{r.get('related_entity','')}」有关联"
                        for r in related[:4] if r.get("entity")
                    )
                else:
                    neo4j_ctx = "知识库案例关联: " + "; ".join(
                        f"{r.get('entity','')}→{r.get('related_entity','')}"
                        for r in related[:5] if r.get("entity")
                    )
        except Exception:
            pass

    # Append dimension-level graph traversal hits (dual-channel #2, only when mature)
    graph_hits = state.get("neo4j_graph_hits") or []
    if graph_hits:
        gh_parts = []
        for gh in graph_hits[:4]:
            dims = ", ".join(gh.get("matched_dimensions", [])[:4])
            nodes = "; ".join(gh.get("matched_nodes", [])[:3])
            gh_parts.append(f"{gh.get('project_name', '')}(维度命中:{dims}; 节点:{nodes})")
        neo4j_ctx += ("\n" if neo4j_ctx else "") + "维度级跨项目启发: " + " | ".join(gh_parts)

    cross_project_hints: list[str] = []
    for ec in enriched_cases[:2]:
        name = str(ec.get("project_name") or ec.get("case_id") or "相似项目").strip()
        cov = ec.get("graph_rubric_covered", []) or []
        uncov = ec.get("graph_rubric_uncovered", []) or []
        shared_rules = (ec.get("rule_overlap") or {}).get("shared", []) or []
        if cov:
            cross_project_hints.append(f"像「{name}」这类案例，通常会先把 {','.join(map(str, cov[:2]))} 讲实，再往后扩展。")
        elif shared_rules:
            cross_project_hints.append(f"「{name}」和你碰到过相似追问，说明 {','.join(map(str, shared_rules[:2]))} 这类问题值得你更早补证据。")
        elif uncov:
            cross_project_hints.append(f"从「{name}」的经验看，{','.join(map(str, uncov[:2]))} 这些部分如果一直空着，后续会反复被追问。")
    for gh in graph_hits[:2]:
        gname = str(gh.get("project_name") or "相关项目").strip()
        dims = [str(x).strip() for x in (gh.get("matched_dimensions") or []) if str(x).strip()]
        nodes = [str(x).strip() for x in (gh.get("matched_nodes") or []) if str(x).strip()]
        if dims:
            cross_project_hints.append(f"图谱里和你最接近的「{gname}」重点落在 {', '.join(dims[:2])}，你也可以先把这两块说具体。")
        elif nodes:
            cross_project_hints.append(f"跨项目图谱显示「{gname}」常把 {', '.join(nodes[:2])} 连起来讲，这对你梳理项目主线也有帮助。")
    cross_project_hints = list(dict.fromkeys([h for h in cross_project_hints if h]))[:3]

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
    default_questions = [
        "如果你把这个项目里最容易被现有替代方案替掉的一步删掉，用户还会因为什么理由留下来？",
        "你现在最想说服的那类用户，究竟会在哪个具体场景下第一次决定要不要继续用你？",
        "如果你现在不急着想完整方案，只先选一个最值得切进去的场景，你觉得应该从哪里切，为什么？",
        "除了你们最先想到的那类用户之外，还有谁会更早感受到这个痛点，或者更愿意先试？",
        "如果半年内拿不到医疗核心数据或医院合作，你们这个方向还能不能先从低监管、低资源的切口跑起来？",
        "你们手里的技术能力里，哪一部分是真正能形成优势的，哪一部分其实别人也能很快补上？",
    ]
    structural_gaps = [str(x).strip() for x in (kg.get("structural_gaps") or []) if str(x).strip()]
    question_limit = 2
    if len(rules) >= 2 or len(structural_gaps) >= 2:
        question_limit = 3
    if len(rules) >= 4 or len(structural_gaps) >= 3:
        question_limit = 4
    if len(rules) >= 6:
        question_limit = 5
    if len(rules) >= 8:
        question_limit = 6

    _inc_stats = state.get("incremental_stats", {})
    _is_exploring = _inc_stats.get("project_maturity") == "exploring"
    _entity_total = _inc_stats.get("total_accumulated", 0)

    if mode == "coursework":
        _exploring_hint = ""
        if _is_exploring:
            _exploring_hint = (
                f"\n**当前项目处于探索期（综合信号判定：实体{_entity_total}个，准备度{_inc_stats.get('readiness_score', 0)}）。**\n"
                "你的首要任务是引导学生把想法说清楚、想透彻，而不是急于做全面诊断。\n"
                "策略：\n"
                "- 先肯定学生的方向感觉，找到他想法中有意思的地方，具体说明为什么有意思\n"
                "- 用追问帮学生把模糊的部分具体化，而不是直接给结论或框架\n"
                "- 重点帮学生厘清：目标用户是谁、核心痛点是什么、为什么你来做这件事有优势\n"
                "- 如果知识图谱搜到了相关线索，用'你有没有想过XX方向'的方式启发，而不是直接断言\n"
                "- 如果有跨项目启示，至少把1-2条转成对当前项目有用的启发，不要只说'找到了相似案例'\n"
                "- 不要过早引入商业模式、竞品矩阵、财务测算等复杂框架\n"
                "- structural_gaps不要在回答中全部列出，探索期缺东西是正常的\n"
                "- guiding_questions 应侧重帮学生补全基本信息，用'你觉得'、'你有没有想过'开头\n"
                "- opening_assessment 不要写成'项目缺少XX、XX、XX'这种批评清单，而是说'你提到了XX这个方向，我觉得有意思的地方是...'这种引导开场\n"
                "- secondary_insights 不要多于2条，探索期不需要大量洞察\n"
            )

        coach_json = _llm.chat_json(
            system_prompt=(
                "你是课程辅导模式下的项目导师。请输出 JSON，字段必须包含："
                "opening_assessment, why_this_matters, method_bridge, teacher_criteria, secondary_insights(list), knowledge_extensions(list), next_focus, guiding_questions(list), source_note。\n"
                "要求：\n"
                "- opening_assessment 先就事论事回应学生项目当前状态，不要套模板，也不要一上来宣布项目整体失败\n"
                "- why_this_matters 解释为什么这个问题值得先想清楚，尽量说清它会影响后面哪一步判断\n"
                "- method_bridge 要把问题上升为学生以后也能复用的方法，像老师在讲'以后你遇到类似问题也可以这样看'\n"
                "- teacher_criteria 说明老师通常会用什么标准判断这部分有没有写清、想清、证据是否够\n"
                "- secondary_insights 给出按材料复杂度展开的2-6条补充洞察，不要固定三个；可以包含疑点、盲区、替代方案、迁移成本、跨学科视角\n"
                "- knowledge_extensions 给出0-4条外部延伸视角，可来自案例知识库、行业公开事实、跨学科方法或可借用框架\n"
                "- 如果输入里已经提供了案例对比、图谱关联、跨项目启示，至少把其中1条改写进 knowledge_extensions 或 secondary_insights，不要只在 source_note 里提到\n"
                "- next_focus 只给一个最值得先观察的切入点，不要展开成任务清单\n"
                "- guiding_questions 按材料复杂度给2-6个贴合学生项目的启发式追问；问题少就少给，问题多就多给，不要固定成两个或三个\n"
                "- 如果你建议验证、调研或查资料，必须说清楚具体该验证什么判断、找哪类人、看什么行为信号；不要泛泛说“做问卷”\n"
                "- 如果学生问的是概念、写法或框架，不要把回答写成大诊断报告，优先讲清楚这一题\n"
                "- 如果有案例、联网或图谱依据，可在 source_note 里自然交代\n"
                + _exploring_hint
            ),
            user_prompt=(
                f"模式提示: {mode_hint}\n"
                + (
                    f"项目成熟度: 探索期(实体{_entity_total}个, 准备度{_inc_stats.get('readiness_score', 0)}), 以引导为主\n"
                    if _is_exploring else
                    f"项目成熟度: 成熟期(实体{_entity_total}个, 准备度{_inc_stats.get('readiness_score', 0)}), 可深入分析\n"
                )
                + f"学生材料: {msg[:1400]}\n"
                + (f"对话上下文:\n{conv_ctx}\n\n" if conv_ctx else "")
                + f"项目阶段: {stage_label}\n"
                + f"当前瓶颈: {bottleneck}\n"
                + (f"KG洞察: {kg.get('insight','')}\n" if kg.get("insight") else "")
                + (f"内容优势: {', '.join(kg.get('content_strengths', [])[:3])}\n" if kg.get("content_strengths") else "")
                + (f"超图诊断:\n{hs_ctx}\n" if hs_ctx else "")
                + (f"案例参考: {rag_ctx[:800]}\n" if rag_ctx else "")
                + (f"案例对比洞察: {rag_insight}\n" if rag_insight else "")
                + (f"联网搜索: {ws_ctx[:300]}\n" if ws_ctx else "")
                + (f"图谱关联: {neo4j_ctx}\n" if neo4j_ctx else "")
                + (f"前几轮积累的知识: {history_knowledge}\n" if history_knowledge else "")
            ),
            model=settings.llm_fast_model if _is_exploring else settings.llm_reason_model,
            temperature=0.35,
        ) if _llm.enabled else {}
        if not isinstance(coach_json, dict):
            coach_json = {}
        coach_questions = [str(item).strip() for item in (coach_json.get("guiding_questions") or []) if str(item).strip()]
        if not coach_questions:
            coach_questions = default_questions[:question_limit]
        secondary_insights = [str(item).strip() for item in (coach_json.get("secondary_insights") or []) if str(item).strip()]
        knowledge_extensions = [str(item).strip() for item in (coach_json.get("knowledge_extensions") or []) if str(item).strip()]
        if cross_project_hints:
            existing_norm = {item.replace(" ", "") for item in knowledge_extensions}
            for hint in cross_project_hints:
                if hint.replace(" ", "") not in existing_norm:
                    knowledge_extensions.append(hint)
                if len(knowledge_extensions) >= 4:
                    break
        if _is_exploring:
            analysis = (
                f"{str(coach_json.get('opening_assessment') or bottleneck).strip()}\n\n"
                f"{str(coach_json.get('why_this_matters') or impact_if_unfixed).strip()}\n\n"
                "如果把这一步放到以后也能复用的方法里看，"
                f"{str(coach_json.get('method_bridge') or '你可以先把想法拆成“谁会先用、为什么现在就会用、你凭什么先做出来”这三个问题。').strip()}\n"
            )
        else:
            analysis = (
                "## 我先说判断\n"
                f"{str(coach_json.get('opening_assessment') or bottleneck).strip()}\n\n"
                "## 为什么这一步值得先想清楚\n"
                f"{str(coach_json.get('why_this_matters') or impact_if_unfixed).strip()}\n\n"
                "## 把它变成你以后也能复用的方法\n"
                f"{str(coach_json.get('method_bridge') or '你可以把当前问题拆回“用户-场景-证据-动作”四层，先确认自己到底卡在判断、证据还是执行。').strip()}\n\n"
            )
        teacher_criteria = str(coach_json.get("teacher_criteria") or "").strip()
        if teacher_criteria and not _is_exploring:
            analysis += f"## 老师通常会怎么判断这一块有没有想清楚\n{teacher_criteria}\n\n"
        if secondary_insights:
            analysis += (
                ("继续往下想，你还可以顺手补看这几件事：\n" if _is_exploring else "## 继续往下拆，还会冒出来这些问题\n")
                + "\n".join(f"- {item}" for item in secondary_insights[:max(question_limit, 3)])
                + "\n\n"
            )
        if knowledge_extensions:
            analysis += (
                ("如果把外部经验借过来，可以先参考这些启发：\n" if _is_exploring else "## 你可以顺手借用的外部视角\n")
                + "\n".join(f"- {item}" for item in knowledge_extensions[:4])
                + "\n\n"
            )
        analysis += (
            ("你现在最该先盯住的一个点是：\n" if _is_exploring else "## 你现在最该盯住的一个观察点\n")
            + f"{str(coach_json.get('next_focus') or '先盯住最可能决定成败的那个判断，不要急着同时推进所有模块。').strip()}\n\n"
            + ("你可以先顺着这些问题往下想：\n" if _is_exploring else "## 你可以先追着自己问的几个问题\n")
            + "\n".join(f"- {item}" for item in coach_questions[:question_limit])
        )
        source_note = str(coach_json.get("source_note") or "").strip()
        if source_note:
            analysis += f"\n\n{'这次我主要参考了：' if _is_exploring else '## 这次主要依据\n'}{source_note}"
    else:
        _comp_ontology_ctx = _get_competition_ontology_context(state.get("competition_type", "")) if mode == "competition" else ""
        _comp_coach_extra = (
            "- 你现在还需要兼顾评委视角：在 structural_layers 和 strategy_space 中指出哪些结构问题最容易被评委追问、哪些策略选择直接影响得分\n"
            "- 如果材料里缺少评委必看的证据链（如用户验证、财务推演、竞争壁垒），请明确指出缺失对评分的影响\n"
            + (f"- 以下是当前赛事的评审侧重点，请在分析中体现这些侧重：\n{_comp_ontology_ctx}\n" if _comp_ontology_ctx else "")
        ) if mode == "competition" else ""
        coach_json = _llm.chat_json(
            system_prompt=(
                "你是一位真正带项目推进的项目教练。请输出 JSON，字段必须包含："
                "opening_assessment, deep_reasoning, structural_layers(list), strategy_space(list), secondary_insights(list), knowledge_extensions(list), evidence_used(list), consequence, next_task_intro, guiding_questions(list), source_note。\n"
                "要求：\n"
                "- opening_assessment 第一段就说明项目处于什么状态、真正卡在哪，不要写成报告标题堆砌\n"
                "- deep_reasoning 要把瓶颈和用户行为、替代方案、竞争、成本、执行条件或行业约束讲透，尽量覆盖材料里真正重要的疑点，不要只挑三个最明显的点\n"
                "- structural_layers 给出2-5条结构层原因，不要只停在表面现象，要解释这些问题为什么会同时出现、它们共同指向什么底层断点\n"
                "- strategy_space 给出2-5条可选择的策略空间，不是周任务，而是方向层面的可选路径、取舍或打法\n"
                "- secondary_insights 给出2-6条继续深挖会浮现的疑点/改进点/结构断点，不要固定三个\n"
                "- knowledge_extensions 给出0-4条外部延伸视角，可来自案例知识库、行业事实、监管常识、跨学科框架或历史项目教训\n"
                "- 如果学生低估竞争、替代方案或行业门槛，优先给出反直觉洞察：用具体公司、行业案例、公开数据或历史类比来打破学生的直觉\n"
                "- 例子不要停在抽象类比，要尽量带背景：例如企业规模、市场份额、行业习惯、迁移成本、监管门槛、真实用户行为\n"
                "- evidence_used 需要引用学生原文或已有分析依据，2-3条即可\n"
                "- consequence 说明如果这个瓶颈继续不处理，会卡住什么\n"
                + _comp_coach_extra
                + "- next_task_intro 只自然指出“最该先攻的一点”，不要展开成步骤、清单、验收标准；整段回复里分析应明显多于行动，行动最多占最后一小节\n"
                "- guiding_questions 按材料复杂度给2-6个真正能把学生往下逼近的追问，必须紧贴他的项目，不要空问“你商业模式是什么”；不要固定成三个\n"
                "- source_note 可自然说明本轮有没有参考案例、联网资料、知识图谱或超图\n"
                "- 语气像导师面对面讨论，不要机械复述“Project Stage / Current Diagnosis”这些英文标题\n"
                "- 如果学生声称没有竞争对手、市场一定很大、巨头不会进入，请优先结合联网信息或公开事实讨论，而不是只给空泛提醒\n"
                "- 如果你建议做验证、访谈、搜索或比较，请明确：验证哪一个判断、找哪类人、看哪个行为信号；不要泛泛说“做问卷”\n"
                "- 你不是行动规划师，不要输出详细执行方案\n"
                "- 如果学生目前还只是提出一个大方向或大赛道，先帮他收敛场景、用户和切口，不要一上来就像成熟项目一样宣布“最大瓶颈”\n"
            ),
            user_prompt=(
                f"模式提示: {mode_hint}\n"
                f"学生材料: {msg[:1600]}\n"
                + (f"对话上下文:\n{conv_ctx}\n\n" if conv_ctx else "")
                + f"项目阶段: {stage_label}\n"
                + f"当前瓶颈: {bottleneck}\n"
                + (f"KG洞察: {kg.get('insight','')}\n" if kg.get("insight") else "")
                + (f"超图诊断:\n{hs_ctx}\n" if hs_ctx else "")
                + (f"案例参考: {rag_ctx[:800]}\n" if rag_ctx else "")
                + (f"案例对比洞察: {rag_insight}\n" if rag_insight else "")
                + (f"联网搜索: {ws_ctx[:350]}\n" if ws_ctx else "")
                + (f"图谱关联: {neo4j_ctx}\n" if neo4j_ctx else "")
                + (f"前几轮积累的知识: {history_knowledge}\n" if history_knowledge else "")
                + "已有证据:\n"
                + "\n".join(f"- {item}" for item in evidence_used[:3])
                + f"\n影响提示: {impact_if_unfixed}\n"
            ),
            model=settings.llm_fast_model if _is_exploring else settings.llm_reason_model,
            temperature=0.38,
        ) if _llm.enabled else {}
        if not isinstance(coach_json, dict):
            coach_json = {}
        coach_evidence = [str(item).strip() for item in (coach_json.get("evidence_used") or []) if str(item).strip()]
        if not coach_evidence:
            coach_evidence = evidence_used[:4]
        structural_layers = [str(item).strip() for item in (coach_json.get("structural_layers") or []) if str(item).strip()]
        strategy_space = [str(item).strip() for item in (coach_json.get("strategy_space") or []) if str(item).strip()]
        coach_questions = [str(item).strip() for item in (coach_json.get("guiding_questions") or []) if str(item).strip()]
        if not coach_questions:
            coach_questions = default_questions[:question_limit]
        secondary_insights = [str(item).strip() for item in (coach_json.get("secondary_insights") or []) if str(item).strip()]
        knowledge_extensions = [str(item).strip() for item in (coach_json.get("knowledge_extensions") or []) if str(item).strip()]
        analysis = (
            f"你这个项目现在处在**{stage_label}**。"
            f"{str(coach_json.get('opening_assessment') or bottleneck).strip()}\n\n"
            f"{str(coach_json.get('deep_reasoning') or impact_if_unfixed).strip()}\n\n"
            "## 我主要是根据这些信息做这个判断\n"
            + "\n".join(f"- {item}" for item in coach_evidence[:4])
            + "\n\n## 如果这一点继续不处理\n"
            + f"{str(coach_json.get('consequence') or impact_if_unfixed).strip()}"
        )
        if structural_layers:
            analysis += "\n\n## 再往下看，真正卡住你的结构层原因\n" + "\n".join(f"- {item}" for item in structural_layers[:5])
        if strategy_space:
            analysis += "\n\n## 从策略空间看，你并不只有一种走法\n" + "\n".join(f"- {item}" for item in strategy_space[:5])
        if secondary_insights:
            analysis += "\n\n## 如果继续往下拆，我还会重点看这些地方\n" + "\n".join(f"- {item}" for item in secondary_insights[:max(question_limit, 3)])
        if knowledge_extensions:
            analysis += "\n\n## 可以顺手借用的外部视角\n" + "\n".join(f"- {item}" for item in knowledge_extensions[:4])
        analysis += (
            "\n\n## 你下一步最该先盯住的一点\n"
            + f"{str(coach_json.get('next_task_intro') or '先把最关键的那个判断想透，而不是同时展开多条执行线。').strip()}"
            + "\n\n## 我建议你先追问自己这几个问题\n"
            + "\n".join(f"- {item}" for item in coach_questions[:question_limit])
        )
        source_note = str(coach_json.get("source_note") or "").strip()
        if source_note:
            analysis += f"\n\n## 这次主要依据\n{source_note}"
    return {
        "agent": "项目教练",
        "analysis": analysis or "",
        "tools_used": ["diagnosis", "rag", "kg_extract", "web_search", "hypergraph"],
        "hyper_context_sent": hs_ctx,
    }


def _analyst_analyze(state: dict) -> dict:
    msg = state.get("message", "")
    mode = state.get("mode", "coursework")
    diag = state.get("diagnosis", {})
    kg = state.get("kg_analysis", {})
    hs = state.get("hypergraph_student", {})
    hyper_insight = state.get("hypergraph_insight", {})
    ws = state.get("web_search_result", {})
    conv_ctx = _build_conv_ctx(state)
    coach_out = state.get("coach_output", {})
    ws_ctx = _fmt_ws(ws)
    rag_ctx = state.get("rag_context", "")
    rag_insight = state.get("rag_enrichment_insight", "")

    rules = diag.get("triggered_rules", []) or []
    bottleneck = diag.get("bottleneck", "")
    rule_summary = "; ".join(
        f"{r.get('id','')}:{r.get('name','')}" for r in rules[:5] if isinstance(r, dict)
    )

    hyper_analyst_ctx = _fmt_hyper_for_agent(hs, hyper_insight, "analyst", incremental_stats=state.get("incremental_stats"))

    neo4j_similar_ctx = ""
    if _graph_service and kg.get("entities"):
        top_labels = [e["label"] for e in kg["entities"][:5] if e.get("label")]
        try:
            related = _graph_service.find_similar_entities(top_labels, limit=5)
            if related:
                _a_inc = state.get("incremental_stats", {})
                if _a_inc.get("project_maturity") == "exploring":
                    neo4j_similar_ctx = "知识库相关线索(供引导参考): " + "; ".join(
                        f"「{r.get('entity','')}」在其他项目中与「{r.get('related_entity','')}」有关联"
                        for r in related[:3] if r.get("entity")
                    )
                else:
                    neo4j_similar_ctx = "Neo4j相似实体启发: " + "; ".join(
                        f"{r.get('entity','')}→{r.get('related_entity','')}"
                        for r in related[:5] if r.get("entity")
                    )
        except Exception:
            pass

    _analyst_mode_hint = {
        "competition": "你同时兼顾评委视角：重点分析风险对获奖概率的影响，指出评委最可能追问的薄弱环节。",
        "coursework": "你同时兼顾教学视角：解释每个风险为什么算风险，帮学生建立风险判断的思维框架。",
        "learning": "你同时兼顾推进视角：按紧迫度排序风险，指出最小可行修复路径。",
    }.get(mode, "")
    analyst_comp_hint = _get_competition_hint(state.get("competition_type", ""), "analyst")
    if analyst_comp_hint:
        _analyst_mode_hint += f"\n{analyst_comp_hint}"

    _analyst_inc = state.get("incremental_stats", {})
    _analyst_exploring = _analyst_inc.get("project_maturity") == "exploring"
    _analyst_exploring_hint = ""
    if _analyst_exploring:
        _analyst_exploring_hint = (
            "\n**注意：学生项目仍在探索期，信息量较少。**\n"
            "你应该：用温和的方式指出1-2个最值得思考的风险方向，而不是列出大量风险。\n"
            "帮学生看清'现在最该先搞清楚什么'，而不是批判项目不完善。\n"
            "严禁说'缺少XX分析'、'该项目是空想'之类的措辞，学生还在构思阶段。\n"
        )

    analysis = _llm.chat_text(
        system_prompt=(
            "你是一位经验丰富的投资人，正在对这个创业项目做尽职调查式的风险评估。\n"
            + _analyst_exploring_hint
            + (f"{_analyst_mode_hint}\n" if _analyst_mode_hint else "")
            + "你的分析必须：\n"
            "1. **先客观评估项目整体质量**：如果项目逻辑基本通顺、商业模式合理，"
            "你应该先肯定做得好的部分，然后指出可以改进的细节，而非硬找致命问题\n"
            "2. 只有在逻辑确实存在明显漏洞时（如获客渠道与用户完全不匹配、财务数据明显不合理），"
            "才指出致命风险，用具体的反事实情境说明后果\n"
            "3. 提出按复杂度给出的若干个学生应该思考的追问（针对他们项目的具体内容，难度匹配项目质量），不要固定三个\n"
            "4. 引用学生内容中的具体表述来讨论\n"
            "5. 如果超图分析发现了缺失维度或风险模式，评估其严重程度再决定是否重点提出\n"
            "6. 如果教学超边给出了历史案例中的风险闭环或价值闭环，请把它当作补充论据，而不是忽略\n"
            "7. 如果有外部事实、行业案例或公开数据能帮助判断，请优先使用这些具体事实，而不是空泛提醒学生去调研\n"
            "8. 如果前面的教练分析已经指出某些问题，你聚焦补充而不重复\n"
            "9. 你的职责是解释风险为何成立，不要替学生制定详细执行计划、步骤或验收标准；分析应明显多于行动\n"
            "10. 如果你认为需要验证、比较或补证据，必须具体说明验证哪个判断、比较哪类替代方案、看什么信号，禁止泛泛说“做问卷”“做调研”\n"
            "11. 除了主风险，还要把材料里值得进一步深挖的次级疑点尽量讲出来，不要只停在最明显的三点\n"
            "12. 请尽量把分析推进到结构层和策略空间：既要解释表层问题，也要解释这些表层问题背后的共同结构原因，以及学生还有哪些可选打法\n"
            "13. 如果学生的直觉明显过于乐观或过于简单，请给出反直觉案例、公开数据或历史类比来纠偏，不要只说“有风险”\n"
            "**重要：不要对一个逻辑基本完善的项目硬凑大量问题。好项目只需要给出提升建议即可。**\n"
            "语气专业犀利但建设性。用4-7段话输出。"
        ),
        user_prompt=(
            f"学生说: {msg[:1200]}\n\n"
            + (f"对话上下文:\n{conv_ctx}\n\n" if conv_ctx else "")
            + f"诊断瓶颈: {bottleneck}\n"
            + f"触发风险规则: {rule_summary}\n"
            + f"KG结构缺陷: {kg.get('structural_gaps', [])}\n"
            + (f"内容优势: {', '.join(kg.get('content_strengths', [])[:3])}\n" if kg.get("content_strengths") else "")
            + (f"教练分析摘要: {str(coach_out.get('analysis',''))[:300]}\n" if coach_out.get("analysis") else "")
            + (f"案例对比参考:\n{rag_ctx[:600]}\n" if rag_ctx else "")
            + (f"案例对比洞察: {rag_insight}\n" if rag_insight else "")
            + (f"超图风险诊断:\n{hyper_analyst_ctx}\n" if hyper_analyst_ctx else "")
            + (f"联网事实:\n{ws_ctx[:350]}\n" if ws_ctx else "")
            + (_fmt_graph_hits_ctx(state.get("neo4j_graph_hits") or []))
            + (f"\n{neo4j_similar_ctx}\n" if neo4j_similar_ctx else "")
        ),
        model=settings.llm_reason_model,
        temperature=0.35,
    )
    tools = ["diagnosis", "kg_analysis", "hypergraph_student", "hypergraph"]
    if neo4j_similar_ctx:
        tools.append("neo4j_similar")
    if ws_ctx:
        tools.append("web_search")
    if rag_ctx:
        tools.append("rag_reference")
    return {
        "agent": "风险分析师",
        "analysis": analysis or "",
        "tools_used": tools,
        "hyper_context_sent": hyper_analyst_ctx,
    }


def _advisor_analyze(state: dict) -> dict:
    msg = state.get("message", "")
    mode = state.get("mode", "coursework")
    rag_ctx = state.get("rag_context", "")
    rag_insight = state.get("rag_enrichment_insight", "")
    diag = state.get("diagnosis", {})
    kg = state.get("kg_analysis", {})
    conv_ctx = _build_conv_ctx(state)
    coach_out = state.get("coach_output", {})
    hs = state.get("hypergraph_student", {})
    hyper_insight = state.get("hypergraph_insight", {})
    hyper_advisor_ctx = _fmt_hyper_for_agent(hs, hyper_insight, "advisor", incremental_stats=state.get("incremental_stats"))

    comp_type = state.get("competition_type", "") or diag.get("competition_type", "")
    comp_urgency = "竞赛教练模式——学生正在备赛，请以专业评委和教练的标准帮助他提升获奖概率，但保持克制、严谨、基于证据。" if mode == "competition" else ""

    _COMP_ADVISOR_HINTS = {
        "internet_plus": (
            "你当前辅导的是「互联网+」赛道项目。评审特别看重：\n"
            "- 商业模式创新性与可持续盈利能力（权重最高）\n"
            "- 市场规模论证（TAM/SAM/SOM）与竞品差异化\n"
            "- 路演表达的完整性、数据可信度和团队协作展示\n"
            "- 社会价值与带动就业能力\n"
            "请以这些侧重点来评判项目并给出针对性建议。"
        ),
        "challenge_cup": (
            "你当前辅导的是「挑战杯」赛道项目。评审特别看重：\n"
            "- 科技创新含量与技术难度（权重最高）\n"
            "- 用户调研的严谨性和证据链（访谈/实验/数据）\n"
            "- 方案的技术可行性和原型验证\n"
            "- 团队科研能力与实际执行记录\n"
            "请以这些侧重点来评判项目并给出针对性建议。"
        ),
        "dachuang": (
            "你当前辅导的是「大创（大学生创新创业训练计划）」项目。评审特别看重：\n"
            "- 方案可行性和实际动手能力（权重最高）\n"
            "- 创新性：是否有新视角、新方法或新应用\n"
            "- 团队执行力：分工明确、有里程碑规划\n"
            "- 训练过程记录与阶段性成果展示\n"
            "请以这些侧重点来评判项目并给出针对性建议。"
        ),
    }
    comp_hint = _COMP_ADVISOR_HINTS.get(comp_type, "")
    _comp_adv_ontology = _get_competition_ontology_context(comp_type)
    if _comp_adv_ontology:
        comp_hint += f"\n\n{_comp_adv_ontology}"

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
            + (f"\n{comp_hint}\n\n" if comp_hint else "")
            + "要求：\n"
            "- 语气专业、克制、严谨，不要咄咄逼人\n"
            "- 风险要和逐项评分保持一致，不要另起炉灶\n"
            "- 按材料复杂度指出最影响竞赛说服力的2-5个扣分点，不要固定成三个\n"
            "- judge_questions 要像真实评委会问的问题\n"
            "- 你负责的是竞赛说服力判断，不要给出完整项目执行计划或周任务分配；分析主体要明显多于行动\n"
            "- 如果你指出需要补证据或补材料，必须说清楚缺的是哪类证据、支撑哪一个评委判断；不要泛泛说“再去调研”“再做问卷”\n"
            "- 如果学生提到竞品、市场、收费、渠道或替代方案，优先结合已有联网事实和具体案例来讲\n"
        ),
        user_prompt=(
            f"学生说:\n{msg[:1200]}\n模式:{mode}\n\n"
            + (f"对话上下文:\n{conv_ctx}\n\n" if conv_ctx else "")
            + (f"参考案例:\n{rag_ctx[:900]}\n\n" if rag_ctx else "")
            + (f"案例对比洞察: {rag_insight}\n\n" if rag_insight else "")
            + (f"教练分析摘要:\n{str(coach_out.get('analysis',''))[:400]}\n\n" if coach_out.get('analysis') else "")
            + (f"诊断瓶颈:{diag.get('bottleneck','')}\n\n" if diag.get("bottleneck") else "")
            + (f"超图竞赛准备度:\n{hyper_advisor_ctx}\n\n" if hyper_advisor_ctx else "")
            + f"Rubric逐项评分:\n{breakdown_md}"
        ),
        model=settings.llm_reason_model,
        temperature=0.25,
    ) if _llm.enabled else {}

    overview = str((llm_json or {}).get("overview") or "")
    top_risks = [str(x) for x in ((llm_json or {}).get("top_risks") or []) if x][:5]
    judge_questions = [str(x) for x in ((llm_json or {}).get("judge_questions") or []) if x][:5]
    defense_tips = [str(x) for x in ((llm_json or {}).get("defense_tips") or []) if x][:4]
    ppt_adjustments = [str(x) for x in ((llm_json or {}).get("ppt_adjustments") or []) if x][:4]
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
        "hyper_context_sent": hyper_advisor_ctx,
    }


def _tutor_analyze(state: dict) -> dict:
    mode = state.get("mode", "coursework")
    analysis, kg_nodes = _build_learning_tutor_reply(state, structured=True)
    hs = state.get("hypergraph_student", {})
    hyper_tutor_ctx = _fmt_hyper_for_agent(hs, state.get("hypergraph_insight", {}), "tutor", incremental_stats=state.get("incremental_stats"))
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
        "hyper_context_sent": hyper_tutor_ctx,
    }


def _grader_analyze(state: dict) -> dict:
    msg = state.get("message", "")
    diag = state.get("diagnosis", {})
    kg = state.get("kg_analysis", {})
    rubric = diag.get("rubric", [])
    overall = diag.get("overall_score")
    sec_scores = kg.get("section_scores", {})
    conv_ctx = _build_conv_ctx(state, limit=4)
    advisor_out = state.get("advisor_output", {})
    hs = state.get("hypergraph_student", {})
    hyper_grader_ctx = _fmt_hyper_for_agent(hs, state.get("hypergraph_insight", {}), "grader", incremental_stats=state.get("incremental_stats"))
    grader_comp_hint = _get_competition_hint(state.get("competition_type", ""), "grader")

    if not rubric or overall is None:
        return {
            "agent": "评分官",
            "analysis": "信息不足，暂无法给出完整评分。请提供更详细的项目描述或上传计划书。",
            "tools_used": ["rubric_engine"],
        }

    rows = []
    for r in rubric:
        status = "✅" if r.get("status") == "ok" else "⚠️"
        rows.append({
            "status": status,
            "item": str(r.get("item", "")),
            "score": float(r.get("score", 0) or 0),
            "reason": str(r.get("reason", "")),
        })
    rows.sort(key=lambda item: item["score"])
    score_text = "\n".join(f"{r['status']} {r['item']}: {r['score']}/10" for r in rows)
    low_rows = rows[:2]
    score_gap = max(0.0, round(8.0 - float(overall or 0), 1))
    advisor_summary = _truncate_text(str(advisor_out.get("analysis") or ""), 360)

    analysis = _llm.chat_text(
        system_prompt=(
            "你负责按照创业竞赛评审标准给项目打分，是一位评分官，不是竞赛教练。\n"
            + (f"{grader_comp_hint}\n" if grader_comp_hint else "")
            + "你的评估必须：\n"
            "1. 用评审口吻先给出当前分数区间和总体判断\n"
            "2. 指出最伤分的1-2个维度，解释为什么这些地方会拖低整体分数\n"
            "3. 给出可快速补分的优先项，但不要展开成详细执行步骤或任务清单\n"
            "4. 如果同轮已经有竞赛顾问意见，不要重复答辩建议或PPT建议；你只负责分数、扣分机制、补分优先级\n"
            "5. 评分要考虑项目阶段：初步规划但逻辑基本成立的项目，不应被写成接近零分或一无是处\n"
            "6. 输出尽量像一份简明评审摘要，而不是重复项目全量分析\n"
            "建议结构：当前分数区间 / 最伤分项 / 快速补分项。"
        ),
        user_prompt=(
            f"学生本轮提问: {msg[:600]}\n\n"
            + (f"对话上下文:\n{conv_ctx}\n\n" if conv_ctx else "")
            + f"Rubric评分:\n{score_text}\n\n"
            + f"总分: {overall}/10\n"
            + f"距离优秀(8/10)还差: {score_gap}\n"
            + (("最低分维度: " + ", ".join("{}({}/10)".format(r["item"], r["score"]) for r in low_rows) + "\n") if low_rows else "")
            + f"KG维度评分: {sec_scores}\n"
            + (f"超图评分信号: {hyper_grader_ctx}\n" if hyper_grader_ctx else "")
            + (f"同轮竞赛顾问摘要: {advisor_summary}\n" if advisor_summary else "")
        ),
        model=settings.llm_fast_model,
        temperature=0.2,
    )
    return {
        "agent": "评分官",
        "analysis": analysis or "",
        "tools_used": ["rubric_engine", "kg_scores"],
        "hyper_context_sent": hyper_grader_ctx,
    }


def _planner_analyze(state: dict) -> dict:
    msg = state.get("message", "")
    diag = state.get("diagnosis", {})
    next_task = state.get("next_task", {})
    kg = state.get("kg_analysis", {})
    hs = state.get("hypergraph_student", {})
    conv_ctx = _build_conv_ctx(state, limit=4)
    coach_out = state.get("coach_output", {})

    hyper_insight = state.get("hypergraph_insight", {})
    hs_missing_ctx = _fmt_hyper_for_agent(hs, hyper_insight, "planner", incremental_stats=state.get("incremental_stats"))
    planner_comp_hint = _get_competition_hint(state.get("competition_type", ""), "planner")

    neo4j_planner_ctx = ""
    if _graph_service and kg.get("entities"):
        top_labels = [e["label"] for e in kg["entities"][:5] if e.get("label")]
        try:
            related = _graph_service.find_similar_entities(top_labels, limit=4)
            if related:
                neo4j_planner_ctx = "图谱类似项目参考: " + "; ".join(
                    f"{r.get('entity','')}→{r.get('related_entity','')}"
                    for r in related[:4] if r.get("entity")
                )
        except Exception:
            pass

    kg_entities = kg.get("entities", [])
    entity_ctx = ""
    if kg_entities:
        entity_ctx = "已识别的核心实体: " + "; ".join(
            f"{e.get('label','')}({e.get('type','')})" for e in kg_entities[:8]
        )

    plan = _llm.chat_json(
        system_prompt=(
            "你是行动规划师。基于学生具体内容的分析结果，为学生生成具体可执行的行动任务。\n\n"
            + (f"{planner_comp_hint}\n\n" if planner_comp_hint else "")
            + "**核心原则**：\n"
            "- 每个任务必须紧密结合学生实际描述的内容，引用学生提到的具体产品/人群/技术\n"
            "- 不要给出泛泛的建议如'做调研'，更不要机械重复'访谈/问卷'\n"
            "- 只有当瓶颈真的是“用户痛点未知/支付意愿未知”时，才考虑访谈、问卷或价格对话\n"
            "- 如果瓶颈是竞争、替代方案、迁移成本，就优先给竞品矩阵/替代方案拆解/迁移成本分析\n"
            "- 如果瓶颈是渠道与增长，就优先给渠道测试、落地页、留资、加群、点击等动作\n"
            "- 如果瓶颈是商业模式或财务，就优先给定价假设表、漏斗拆解、CAC/LTV/BEP测算\n"
            "- 如果瓶颈是执行，就优先给负责人、时间表、交付物拆分\n"
            "- 如果瓶颈是技术或创新可信度，就优先给demo验证、对照实验、关键指标观测\n"
            "- 如果学生上传了文件，任务应该针对文件中具体薄弱的部分给出修改建议\n"
            "- 如果对话上下文显示之前已建议过某些任务，不要重复，给出递进的新任务\n"
            "- 给出1-3个任务，按优先级排序，第1个最紧急；如果瓶颈单一就只给1个\n"
            "- 必须明确告诉学生：这周先做什么，哪些事暂时不要做\n\n"
            "- 输出尽量短，不要写很长的解释句，尤其不要把 how 写成大段长文\n\n"
            '输出JSON: {"this_week":['
            '{"task":"针对XX的具体任务名","why":"为什么这对你的项目关键",'
            '"how":["步骤1","步骤2","步骤3"],"acceptance":"可衡量的验收标准",'
            '"priority":"urgent|important|nice_to_have"}],'
            '"not_now":["本周先不要做的事1","本周先不要做的事2"],'
            '"milestone":"本阶段目标(用学生的项目语言描述)"}'
        ),
        user_prompt=(
            f"学生说: {msg[:800]}\n\n"
            + (f"对话上下文:\n{conv_ctx}\n\n" if conv_ctx else "")
            + f"诊断瓶颈: {diag.get('bottleneck','')}\n"
            + f"诊断给出的默认下一步: {next_task.get('title','')} / {next_task.get('description','')}\n"
            + (f"{entity_ctx}\n" if entity_ctx else "")
            + f"结构缺陷: {kg.get('structural_gaps',[])}\n"
            + f"内容优势: {kg.get('content_strengths', [])[:2]}\n"
            + (f"教练核心发现: {str(coach_out.get('analysis',''))[:300]}\n" if coach_out.get("analysis") else "")
            + (f"超图行动线索:\n{hs_missing_ctx}\n" if hs_missing_ctx else "")
            + (f"{neo4j_planner_ctx}\n" if neo4j_planner_ctx else "")
            + (f"赛事规划提示: {planner_comp_hint}\n" if planner_comp_hint else "")
        ),
        model=settings.llm_structured_model,
        temperature=0.25,
    )

    analysis_text = ""
    if plan:
        tasks = plan.get("this_week", [])
        not_now = [str(x).strip() for x in (plan.get("not_now") or []) if str(x).strip()]
        if tasks:
            _pri_label = {"urgent": "紧急", "important": "重要", "nice_to_have": "建议"}
            parts = []
            for t in tasks[:3]:
                how_value = t.get("how", "")
                if isinstance(how_value, list):
                    how_text = "；".join(str(item).strip() for item in how_value if str(item).strip())
                else:
                    how_text = str(how_value or "").strip()
                pri = _pri_label.get(str(t.get("priority", "")), "")
                label = f"[{pri}] " if pri else ""
                parts.append(f"- {label}**{t.get('task','')}**: {how_text}")
                if t.get("acceptance"):
                    parts.append(f"  验收标准: {t['acceptance']}")
            analysis_text = "本周建议行动:\n" + "\n".join(parts)
        if not_now:
            analysis_text += ("\n\n本周先不要做：\n" if analysis_text else "本周先不要做：\n") + "\n".join(f"- {item}" for item in not_now[:3])
        if plan.get("milestone"):
            analysis_text += f"\n\n阶段目标: {plan['milestone']}"

    return {
        "agent": "行动规划师",
        "analysis": analysis_text,
        "tools_used": ["diagnosis", "next_task", "critic"],
        "plan_data": plan or {},
        "hyper_context_sent": hs_missing_ctx,
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


def _collect_analysis_context(state: dict) -> tuple[list[str], str]:
    analysis_parts: list[str] = []
    planner_block = ""
    for key in ("coach_output", "analyst_output", "advisor_output", "tutor_output", "grader_output"):
        out = state.get(key, {})
        if out and out.get("analysis"):
            analysis_parts.append(f"### {out.get('agent', key)}\n{str(out['analysis'])}")
    planner_out = state.get("planner_output", {})
    if planner_out and planner_out.get("analysis"):
        planner_block = f"### {planner_out.get('agent', 'planner')}\n{str(planner_out['analysis'])}"
    return analysis_parts, planner_block


# ═══════════════════════════════════════════════════════════════════
#  Node 3: Hybrid Agent Selection (Static Rules + Dynamic Heuristics)
#           + Serial Execution
# ═══════════════════════════════════════════════════════════════════

_SCORING_SIGNALS = frozenset(["评分", "打分", "得分", "几分", "怎么评", "多少分", "分数"])
_PLANNING_SIGNALS = frozenset(["下一步", "怎么办", "怎么推进", "行动", "计划", "路线", "优先级", "先做什么", "任务"])
_EVALUATION_FOLLOWUP_SIGNALS = frozenset([
    "评委", "怎么评价", "会怎么评价", "打多少分", "大概能打多少分", "能打多少分",
    "评分", "打分", "几分", "多少分", "扣分", "最致命", "致命", "优先改哪里", "先改哪里",
    "如果只能改几处", "优先应该改哪里",
])

_AGENT_ORDER = ("coach", "analyst", "advisor", "tutor", "grader", "planner")


def _decide_agents(state: WorkflowState) -> tuple[list[str], str]:
    """Four-phase agent selection: Matrix → Mode-boost → Static-rules → Cap.

    Phase 1 — AGENT_MATRIX lookup
      Base agents from intent × complexity tier.

    Phase 2 — Mode boost (additive only, never removes)
      competition → + advisor   learning → + coach   coursework → + tutor

    Phase 3 — Static rules (non-negotiable guarantees)
      File upload → + coach;  scoring request → + grader;
      planning request → + planner;  high risk → + analyst

    Phase 4 — Cap to max_agents (simple 1-2, medium 2-4, complex 3-6)

    Returns agents in canonical order so later agents can reference earlier output.
    """
    intent = state.get("intent", "general_chat")
    mode = state.get("mode", "coursework")
    intent_shape = _normalize_intent_shape(state.get("intent_shape", "single"))
    msg = state.get("message", "")
    conv = state.get("conversation_messages", [])
    is_file = "[上传文件:" in msg
    diag = state.get("diagnosis", {})
    rules = diag.get("triggered_rules", []) or []
    high_risk = sum(1 for r in rules if isinstance(r, dict) and r.get("severity") == "high")
    complexity = _message_complexity(msg, conv)
    tier = _complexity_tier(complexity, intent_shape)
    asks_for_plan = any(w in msg for w in _PLANNING_SIGNALS)
    asks_for_score = _is_score_request_message(msg)
    asks_for_eval = _is_eval_followup_message(msg)

    selected: set[str] = set()
    reasons: list[str] = []

    # ═══ Phase 1: AGENT_MATRIX lookup ═══
    matrix_row = AGENT_MATRIX.get(intent, AGENT_MATRIX["general_chat"])
    base = list(matrix_row.get(tier, matrix_row.get("simple", ["coach"])))

    if intent == "business_model" and tier == "simple" and _has_explicit_project_context(msg):
        base = ["coach"]
        reasons.append("商业模式问题带项目背景，由教练主导")

    selected.update(base)
    reasons.append(f"MATRIX[{intent}][{tier}] -> {' / '.join(base)}")

    # ═══ Phase 2: Mode boost (additive, never removes) ═══
    if mode == "competition" and intent not in ("general_chat", "learning_concept"):
        if "advisor" not in selected:
            selected.add("advisor")
            reasons.append("竞赛模式补竞赛顾问")
    elif mode == "learning":
        if "coach" not in selected:
            selected.add("coach")
            reasons.append("项目教练模式补教练")
    elif mode == "coursework":
        if "tutor" not in selected and intent != "general_chat":
            selected.add("tutor")
            reasons.append("课程辅导模式补课程导师")

    # ═══ Phase 3: Static rules (non-negotiable guarantees) ═══
    if is_file:
        selected.add("coach")
        if asks_for_plan or complexity >= 3:
            selected.add("planner")
        if asks_for_score or mode == "competition":
            selected.add("grader")
        reasons.append("上传文件触发静态规则")

    if asks_for_score:
        selected.add("grader")
        reasons.append("学生明确问评分，加入评分官")
    elif asks_for_eval:
        selected.add("grader")
        reasons.append("学生追问评委视角，加入评分官")

    needs_competition_review = asks_for_eval or intent == "competition_prep" or mode == "competition"
    if needs_competition_review:
        selected.add("advisor")

    if asks_for_plan and intent in ("project_diagnosis", "business_model", "evidence_check", "idea_brainstorm", "competition_prep"):
        selected.add("planner")
        reasons.append("学生问下一步行动，补行动规划师")

    if (high_risk >= 1 or len(rules) >= 3) and intent not in ("learning_concept", "general_chat"):
        selected.add("analyst")
        reasons.append("检测到高风险规则，补风险分析师")

    # ═══ Phase 4: Order + Cap ═══
    order_basis = _AGENT_ORDER
    if asks_for_score or asks_for_eval:
        order_basis = ("coach", "advisor", "grader", "analyst", "planner", "tutor")

    ordered = [a for a in order_basis if a in selected]

    if asks_for_score or asks_for_eval:
        max_agents = 5
    elif tier == "complex":
        max_agents = 6
    elif tier == "medium":
        max_agents = 4
    else:
        max_agents = 2

    ordered = ordered[:max_agents]
    if not ordered:
        ordered = ["coach"]

    reasoning = "；".join(dict.fromkeys(reasons)) or "按主意图选择最小必要 agent 集合"
    return ordered, reasoning


def _dim_results_to_agent_outputs(dim_results: dict[str, dict]) -> dict:
    """Convert V3 dim_results to legacy agent output format for frontend display."""
    writer_groups: dict[str, list[str]] = {}
    for dim, dr in dim_results.items():
        writer = dr.get("writer", "coach")
        text = str(dr.get("value") or "").strip()
        if not text:
            continue
        dim_label = ANALYSIS_DIMENSIONS.get(dim, {}).get("label", dim)
        writer_groups.setdefault(writer, []).append(f"【{dim_label}】\n{text}")

    outputs: dict[str, dict] = {}
    for writer, sections in writer_groups.items():
        display_name = AGENT_DISPLAY.get(writer, writer)
        analysis = "\n\n".join(sections)
        hyper_sent = ""
        for dim, dr in dim_results.items():
            if dr.get("writer") == writer and dr.get("hyper_context_sent"):
                hyper_sent += dr["hyper_context_sent"] + "\n"
        outputs[f"{writer}_output"] = {
            "agent": display_name,
            "analysis": analysis,
            "tools_used": ["dim_analysis"],
            "hyper_context_sent": hyper_sent.strip(),
        }
    return outputs


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

    if _should_use_focused_mode(state):
        logger.info("intent '%s' → focused mode, no agents", intent)
        return {
            "agents_called": [f"[聚焦模式: {intent}]"],
            "resolved_agents": [],
            "agent_reasoning": "当前问题足够聚焦，由编排器直接生成回答，不额外拆分角色智能体。",
            "nodes_visited": ["role_agents"],
        }

    # ── V3: Dimension-driven execution ──
    activations = state.get("dim_activations", {})
    activated_dims = [d for d, a in activations.items() if a.get("activated")]
    n_activated = len(activated_dims)

    logger.info(
        "V3 dim check: n_activated=%d dims=%s intent=%s",
        n_activated, activated_dims, intent,
    )

    # ── Decide Path A vs Path B based on dims + message complexity ──
    _GUIDE_DIMS = ["status_judgment", "probing_questions", "strategy_directions"]
    is_file = "[上传文件:" in state.get("message", "")
    _msg_for_complexity = state.get("message", "")
    _conv_for_complexity = state.get("conversation_messages", [])
    _complexity_score = _message_complexity(_msg_for_complexity, _conv_for_complexity)
    _tier_for_path = _complexity_tier(_complexity_score, _normalize_intent_shape(state.get("intent_shape", "single")))

    use_path_a = (
        n_activated <= 2
        and not is_file
        and _tier_for_path != "complex"
        and len(_msg_for_complexity) < 500
    )

    # ── Path A: Guiding mode with auto-added dimensions ──
    if use_path_a:
        effective_dims = list(dict.fromkeys(activated_dims + [
            d for d in _GUIDE_DIMS if d not in activated_dims
        ]))

        dim_results: dict[str, dict] = {}
        agent_hyper_details: list[dict] = []

        with ThreadPoolExecutor(max_workers=min(len(effective_dims), 4)) as pool:
            future_map = {
                pool.submit(_write_dimension, dim, dict(state)): dim
                for dim in effective_dims
            }
            try:
                for future in as_completed(future_map, timeout=45):
                    dim = future_map[future]
                    try:
                        dr = future.result()
                        dim_results[dim] = dr
                        if dr.get("hyper_context_sent"):
                            agent_hyper_details.append({"dim": dim, "hyper": dr["hyper_context_sent"]})
                    except Exception as exc:
                        logger.warning("write_dimension %s failed: %s", dim, exc)
                        dim_results[dim] = {"value": "", "confidence": 0.2, "writer": "coach", "challenges": []}
            except TimeoutError:
                logger.warning("path A dim writes timed out (45s)")
                for f in future_map:
                    if f.done() and future_map[f] not in dim_results:
                        try:
                            dim_results[future_map[f]] = f.result()
                        except Exception:
                            pass

        all_missing = [d for d in ANALYSIS_DIMENSIONS
                       if d not in effective_dims and d != "probing_questions"]
        missing_labels = [ANALYSIS_DIMENSIONS[d]["label"] for d in all_missing[:4]]

        exploration_phase = (state.get("exploration_state") or {}).get("phase")
        reply_strategy = "progressive" if exploration_phase in ("direction", "convergence") else "deep_dive"

        agent_outputs = _dim_results_to_agent_outputs(dim_results)
        logger.info("V3 path A: guiding, effective_dims=%s, missing_hints=%s, strategy=%s, agent_outputs=%s",
                     effective_dims, missing_labels, reply_strategy, list(agent_outputs.keys()))
        result_a: dict = {
            "agents_called": ["coach"],
            "resolved_agents": [],
            "agent_reasoning": f"激活{n_activated}个维度+自动补充引导维度→共{len(effective_dims)}个({', '.join(effective_dims)})。缺失方向: {', '.join(missing_labels)}",
            "dim_results": dim_results,
            "reply_strategy": reply_strategy,
            "missing_dim_hints": missing_labels,
            "agent_hyper_details": agent_hyper_details,
            "nodes_visited": ["role_agents"],
        }
        result_a.update(agent_outputs)
        return result_a

    # ── Path B: Many dimensions (3+) → per-dim parallel LLM calls ──
    dim_results = {}
    agent_hyper_details = []

    with ThreadPoolExecutor(max_workers=min(n_activated, 5)) as pool:
        future_map = {
            pool.submit(_write_dimension, dim, dict(state)): dim
            for dim in activated_dims
        }
        try:
            for future in as_completed(future_map, timeout=60):
                dim = future_map[future]
                try:
                    dr = future.result()
                    dim_results[dim] = dr
                    if dr.get("hyper_context_sent"):
                        agent_hyper_details.append({"dim": dim, "hyper": dr["hyper_context_sent"]})
                except Exception as exc:
                    logger.warning("write_dimension %s failed: %s", dim, exc)
                    dim_results[dim] = {"value": "", "confidence": 0.2, "writer": "coach", "challenges": []}
        except TimeoutError:
            done_dims = [future_map[f] for f in future_map if f.done()]
            pending_dims = [future_map[f] for f in future_map if not f.done()]
            logger.warning("dim writes timed out (60s) — done=%s pending=%s", done_dims, pending_dims)
            for f in future_map:
                if f.done():
                    dim = future_map[f]
                    if dim not in dim_results:
                        try:
                            dim_results[dim] = f.result()
                        except Exception:
                            pass

    # Run challengers for high-risk dims (parallel)
    challenge_tasks: list[tuple[str, dict]] = []
    for dim in activated_dims:
        if dim not in dim_results:
            continue
        challengers = DIM_OWNERSHIP.get(dim, {}).get("challengers", [])
        if challengers and dim_results[dim].get("value"):
            challenge_tasks.append((dim, dim_results[dim]))

    if challenge_tasks:
        def _do_challenge(item: tuple[str, dict]) -> tuple[str, dict | None]:
            d, wr = item
            return d, _run_challenger(d, wr, state)
        with ThreadPoolExecutor(max_workers=min(len(challenge_tasks), 3)) as ch_pool:
            ch_futures = {ch_pool.submit(_do_challenge, t): t[0] for t in challenge_tasks}
            try:
                for cf in as_completed(ch_futures, timeout=20):
                    try:
                        d, ch_res = cf.result()
                        if ch_res and d in dim_results:
                            dim_results[d].setdefault("challenges", []).append(ch_res)
                    except Exception as _ce:
                        logger.warning("challenger failed: %s", _ce)
            except TimeoutError:
                logger.warning("challenger phase timed out")

    dim_results = _resolve_dimension_conflicts(dim_results)

    # Select reply strategy
    exploration_phase = (state.get("exploration_state") or {}).get("phase")
    _msg = state.get("message", "")
    _conv = state.get("conversation_messages", [])
    _complexity = _message_complexity(_msg, _conv)
    _tier = _complexity_tier(_complexity, _normalize_intent_shape(state.get("intent_shape", "single")))
    _is_file = "[上传文件:" in _msg
    _maturity = (state.get("incremental_stats") or {}).get("project_maturity")

    reply_strategy = _select_reply_strategy(
        activations or {}, intent, dim_results, exploration_phase,
        complexity_tier=_tier, is_file=_is_file, project_maturity=_maturity,
    )

    agents_involved = list({dim_results[d].get("writer", "coach") for d in dim_results if dim_results[d].get("value")})

    agent_outputs = _dim_results_to_agent_outputs(dim_results)
    logger.info("V3 path B: %d dims parallel, agents=%s, strategy=%s, challengers=%d, agent_outputs=%s",
                n_activated, agents_involved, reply_strategy, len(challenge_tasks), list(agent_outputs.keys()))

    result_b: dict = {
        "agents_called": agents_involved,
        "resolved_agents": [],
        "agent_reasoning": f"V3维度驱动: {n_activated}个维度并行分析，涉及{', '.join(agents_involved)}",
        "dim_results": dim_results,
        "reply_strategy": reply_strategy,
        "agent_hyper_details": agent_hyper_details,
        "nodes_visited": ["role_agents"],
    }
    result_b.update(agent_outputs)
    return result_b

    # (V2 legacy code removed — V3 dim-driven paths above handle all cases)


# ═══════════════════════════════════════════════════════════════════
#  Node 4: Orchestrator — synthesise all agent outputs
# ═══════════════════════════════════════════════════════════════════

_MODE_PERSONA: dict[str, str] = {
    "coursework": (
        "你是一位真正懂创新创业课程教学的课程导师。"
        "你擅长把商业模式、价值主张、市场分析、验证方法、竞品分析、单位经济等创业专业问题讲清楚。"
        "你的目标不是急着判分，而是先帮助学生听懂、想通、会判断，再把抽象方法落回项目。"
        "当学生没有给项目背景时，你会先用简单、真实、公开可理解的创业例子解释；当学生带着项目来问时，你再把方法落回他的项目。"
        "语气耐心、专业、具体，像老师在办公室里一对一辅导，而不是像百科或评审报告。"
    ),
    "competition": (
        "你是一位资深创业竞赛教练，对互联网+、挑战杯等赛事非常熟悉。"
        "你的目标是帮助学生提高获奖概率，侧重评委视角、证据链、路演打磨和竞争力提升。"
        "语气专业、克制、严谨，像有依据的高水平教练。"
    ),
    "learning": (
        "你是一位真正负责推进项目的项目教练。"
        "你的目标不是急着挑错，而是先判断学生现在处于方向探索、项目成形还是验证推进阶段。"
        "如果学生还只有一个想法，你要带着他把用户、场景、痛点、切口、替代方案和约束慢慢想清楚；"
        "如果项目已经成形，再识别关键瓶颈、拆出结构层原因与策略空间，深入全面地分析学生项目，并把下一步动作收敛成一个最关键的焦点。"
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
        "1. 如果学生给了项目背景，先结合他的项目说明为什么现在需要理解这个概念；如果没给项目背景，就不要硬套项目\n"
        "2. 用一句话通俗定义这个概念（不要教科书式定义）\n"
        "3. 解释老师通常会怎么判断学生是不是真的理解了这个概念\n"
        "4. 用1-2个简单、真实、公开可理解的创业例子来讲清楚，优先用咖啡店、外卖平台、打车平台、会员制产品、SaaS 等普通人能听懂的场景\n"
        "5. 如果搜索结果有最新信息，引用具体数据、事实和链接；如果没有，也可以只靠成熟常识讲清楚，不要为了联网而硬凑\n"
        "6. 给学生一个非常小、非常具体的练习，用来验证他是否真的理解了这个概念\n"
        "7. 指出学生最容易踩的坑，最好点出一个常见误解\n"
        "8. 如果学生的项目上下文已知，最后再补一句放回他的项目时应该先看什么信号\n"
        "用700-1200字回复。像真实导师，不要像百科词条，也不要写成项目诊断报告。"
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
        "学生这条消息看起来不是在做深度项目分析。\n"
        "你的任务：\n"
        "1. 自然地接住学生说的话——该接梗接梗，该幽默幽默\n"
        "2. 你是AI，不会吃饭睡觉。如果学生问生活类问题，坦然说自己是AI但用幽默方式接住\n"
        "3. 如果有对话上下文（之前讨论过项目），自然衔接，顺势追问进展\n"
        "4. 如果完全是新对话，用好奇心驱动的方式引导学生聊想法\n"
        "5. 绝对不要输出括号内的舞台指令或旁白\n"
        "6. 绝对不要重复上一条自己说过的话\n"
        "7. 如果能联系到创业/商业世界的小知识点或趣事，顺手分享一句\n"
        "用100-350字回复。自然、有温度。"
    ),
    "funding_investment": (
        "学生在问融资/投资/估值/股权相关问题。你的任务：\n"
        "1. 判断学生项目所处阶段(想法/MVP/增长)，给出对应的融资策略\n"
        "2. 讲清楚常见融资轮次(种子/天使/Pre-A/A轮)的金额范围和对应里程碑\n"
        "3. 如果学生问估值，用2-3种常见估值方法(可比交易/DCF/收入倍数)结合学生项目说明\n"
        "4. 给出BP(商业计划书)核心要包含的8-10个要素\n"
        "5. 如果搜索到最新融资案例，结合说明；否则用知名创业案例(如拼多多种子轮/字节早期)类比\n"
        "6. 提醒常见坑：估值过高、股权稀释过快、对赌条款风险\n"
        "用700-1200字回复。实用、有阶段感、有具体数字参考。"
    ),
    "company_operations": (
        "学生在问公司注册/法务/股权架构等运营问题。你的任务：\n"
        "1. 根据学生具体问题(注册/股权/知识产权/税务)给出针对性建议\n"
        "2. 如果是注册公司：说明个体户/有限公司/合伙企业的区别和适用场景\n"
        "3. 如果是股权：说明创始人股权分配原则、期权池设计、退出机制\n"
        "4. 如果是知识产权：区分专利/商标/著作权，说明大学生项目最需优先保护的\n"
        "5. 推荐1-2个可操作的下一步(如用创业工商一站通注册、咨询学校创业孵化器法律顾问)\n"
        "6. 提醒学生阶段匹配：早期别过度纠结法务细节，但股权要提前约定\n"
        "用600-1000字回复。务实、有操作步骤、避免过于法律术语化。"
    ),
    "startup_execution": (
        "学生在问创业执行层面的问题(团队/增长/规模化/上市等)。你的任务：\n"
        "1. 根据学生具体问题给出对应阶段的执行建议\n"
        "2. 如果是团队搭建：说明早期核心团队3-5人的角色分配、找合伙人的渠道和原则\n"
        "3. 如果是增长：区分冷启动/PMF验证/规模化三个阶段的不同策略\n"
        "4. 如果是运营：给出具体的获客渠道、留存策略、核心指标(DAU/MAU/留存率/转化率)\n"
        "5. 如果问上市/并购：诚实说明这是远期目标，当前应聚焦什么\n"
        "6. 给出1-2个同类创业公司的执行路径参考\n"
        "用700-1200字回复。阶段感强、有具体指标、避免空泛建议。"
    ),
    "out_of_scope": (
        "学生问了一个超出你专长范围的问题（如写代码、数学题、翻译等）。\n"
        "你的任务：\n"
        "1. 友好但明确地说明这不在你的能力范围内\n"
        "2. 简单说明你最擅长的是创业项目分析、商业模式、竞赛准备等\n"
        "3. 用一句话引导学生回到项目话题\n"
        "用80-200字回复。不要勉强回答超范围问题，以免给出错误信息。"
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

    # RAG cases + enrichment insight
    rag_ctx = state.get("rag_context", "")
    if rag_ctx:
        parts.append(f"\n## 参考案例\n{rag_ctx[:600]}")
    rag_ei = state.get("rag_enrichment_insight", "")
    if rag_ei:
        parts.append(f"案例对比洞察: {rag_ei}")

    # Neo4j graph traversal hits (dimension-level cross-project inspiration)
    graph_hits_ctx = _fmt_graph_hits_ctx(state.get("neo4j_graph_hits") or [])
    if graph_hits_ctx:
        parts.append(f"\n## 跨项目维度启发\n{graph_hits_ctx}")

    # Enriched RAG case comparison
    enriched_cases = [c for c in (state.get("rag_cases") or []) if c.get("neo4j_enriched")]
    if enriched_cases:
        ec_parts = []
        for ec in enriched_cases[:3]:
            name = ec.get("project_name", "")
            shared = (ec.get("rule_overlap") or {}).get("shared", [])
            only_s = (ec.get("rule_overlap") or {}).get("only_in_student", [])
            ec_parts.append(
                f"- {name}" + (f" 共同风险:{','.join(shared[:3])}" if shared else "")
                + (f" 你独有:{','.join(only_s[:2])}" if only_s else "")
            )
        parts.append("\n## 案例图谱深度对比\n" + "\n".join(ec_parts))

    # Hypergraph
    hs = state.get("hypergraph_student", {})
    if hs.get("ok"):
        hyper_insight = state.get("hypergraph_insight", {})
        hs_full = _fmt_hyper_for_agent(hs, hyper_insight, "coach", incremental_stats=state.get("incremental_stats"))
        if hs_full:
            parts.append(f"\n## 超图分析\n{hs_full}")

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
    continuation_mode = _conversation_continuation_mode(state)
    conv_state_summary = _build_conversation_state_summary(state)

    # Collect multi-agent analyses (only present for complex intents)
    analysis_parts, planner_block = _collect_analysis_context(state)

    conv_ctx = ""
    if conv_msgs:
        recent = conv_msgs[-6:]
        conv_ctx = "\n".join(
            f"{'学生' if m.get('role')=='user' else '教练'}: {str(m.get('content',''))[:200]}"
            for m in recent
        )

    persona = _MODE_PERSONA.get(mode, _MODE_PERSONA["coursework"])
    analyses_ctx = "\n\n---\n\n".join(analysis_parts)
    has_planner = bool(planner_block.strip())

    reply = ""

    if state.get("needs_clarification"):
        return {"assistant_message": _build_clarification_reply(state), "nodes_visited": ["orchestrator"]}

    diag = state.get("diagnosis", {})
    kg = state.get("kg_analysis", {}) if isinstance(state.get("kg_analysis"), dict) else {}
    n_triggered = len(diag.get("triggered_rules", []) or [])
    triggered_rules = [
        str(item.get("name") or item.get("id") or "").strip()
        for item in (diag.get("triggered_rules") or [])
        if isinstance(item, dict) and str(item.get("name") or item.get("id") or "").strip()
    ]
    structural_gaps = [str(x).strip() for x in (kg.get("structural_gaps") or []) if str(x).strip()]
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
            "请把关键问题尽量讲全，至少覆盖主链路上所有会影响判断的缺口，不要只挑两三点草草带过。\n"
            "对于每个关键问题，不要只说'这是个问题'，要解释：\n"
            "- 为什么这是问题（根因分析）\n"
            "- 不解决会卡住什么（后果链）\n"
            "- 有什么反直觉的切入角度\n\n"
        )

    # V2: retrieve dim_results and reply_strategy for dynamic orchestration
    dim_results = state.get("dim_results", {})
    v2_reply_strategy = state.get("reply_strategy", "")
    v2_strategy_spec = REPLY_STRATEGIES.get(v2_reply_strategy, {})

    if _llm.enabled and analyses_ctx:
        # ── PATH A: Multi-agent synthesis (complex intents) ──
        # V2: use reply_strategy for length guidance instead of fixed rules
        if v2_strategy_spec:
            length_guide = v2_strategy_spec.get("length", "800-1800字")
            tone_guide = v2_strategy_spec.get("tone", "")
        else:
            msg_len = len(msg)
            n_analyses = len(analysis_parts)
            if is_file:
                length_guide = "2200-4200字"
            elif n_analyses >= 4:
                length_guide = "1800-3800字"
            elif n_analyses >= 3:
                length_guide = "1500-3200字"
            elif n_analyses >= 2:
                length_guide = "1200-2600字"
            elif msg_len > 200:
                length_guide = "900-1800字"
            else:
                length_guide = "600-1200字"
            tone_guide = ""

        # V2: build dim_results context for orchestrator
        dim_ctx_parts: list[str] = []
        for dim_key, dr in dim_results.items():
            dim_label = ANALYSIS_DIMENSIONS.get(dim_key, {}).get("label", dim_key)
            conf = round(float(dr.get("confidence", 0)), 2)
            contested = dr.get("contested", False)
            val_preview = str(dr.get("value", ""))[:400]
            marker = ""
            if contested:
                marker = " [有争议]"
                amendments = dr.get("amendments", [])
                if amendments:
                    marker += f" 挑战意见: {amendments[0][:80]}"
            elif conf < 0.6:
                marker = " [低置信]"
            dim_ctx_parts.append(f"- {dim_label}(置信度{conf}{marker}): {val_preview}")
        dim_results_ctx = "\n".join(dim_ctx_parts) if dim_ctx_parts else ""

        # V2: strategy-aware structure guidance (replaces rigid 8-step template)
        if v2_reply_strategy == "comprehensive":
            structure_guide = (
                "## 回复结构（全面深度分析模式——这是复杂问题，请充分展开）\n"
                "你需要覆盖以下分析切面（不必用固定标题，但每个切面都要有充分讨论）：\n"
                "1. **现状判断**：先就事论事回应学生项目当前处于什么阶段，真正卡在哪里\n"
                "2. **核心问题深挖**：把瓶颈和用户行为、替代方案、竞争格局、执行条件讲透\n"
                "   - 不要停在表面现象，要解释这些问题为什么会同时出现\n"
                "   - 如果学生低估竞争或替代方案，用具体的公司名、数据、行业案例来打破直觉\n"
                "3. **结构性原因**：分析问题的底层结构——为什么这些问题互相关联，共同指向什么断点\n"
                "4. **可复用的方法/判断框架**：把本次问题上升为学生以后也能用的方法论\n"
                "5. **多维洞察**：展开 3-6 条补充洞察，包括盲区、替代方案、迁移成本、跨学科视角、行业约束\n"
                "6. **外部参考**：案例对比、行业事实、跨领域借鉴（如果有 RAG 案例或联网数据，在此引用）\n"
                "7. **策略空间**：给出 2-4 条方向层面的可选路径，而不是具体任务清单\n"
                "8. **聚焦追问**：3-5 个真正贴合学生项目的深度追问，推动下一步思考\n\n"
                "深度要求：\n"
                "- 每个切面不要只写一两句，要有展开论证\n"
                "- 涉及流程/步骤时用 mermaid 流程图\n"
                "- 涉及对比时用表格\n"
                "- 分析与解释至少占八成篇幅；行动放最后且要具体\n"
                f"- {'行动规划放最后一节' if has_planner else '最后给一个最值得先盯住的观察点'}\n\n"
            )
        elif v2_reply_strategy == "panorama":
            structure_guide = (
                "## 回复结构（全面多维分析模式）\n"
                "覆盖以下分析切面（灵活组织，不必死板跟顺序）：\n"
                "1. 现状判断与核心瓶颈\n"
                "2. 深层原因分析（为什么会卡在这里，结构性原因是什么）\n"
                "3. 多维洞察（2-5 条补充观察，覆盖盲区、替代方案、行业对标）\n"
                "4. 可借鉴的外部视角或案例\n"
                "5. 策略方向（2-3 条可选路径）\n"
                "6. 深度追问（2-4 个推动思考的问题）\n\n"
                "深度要求：每个切面充分展开，不要一笔带过。\n"
                f"- {'行动规划放最后一节' if has_planner else '最后给一个聚焦点'}\n\n"
            )
        elif v2_reply_strategy == "deep_dive":
            structure_guide = (
                "## 回复结构（深度单点分析模式）\n"
                "1. 精准定位核心问题\n"
                "2. 深度剖析这个问题的根因（不要停在表面，要讲透为什么）\n"
                "3. 给出反直觉洞察或被忽视的角度\n"
                "4. 如果有案例参考或行业数据，充分利用\n"
                "5. 1-2 条策略方向 + 2-3 个深度追问\n\n"
                "深度要求：宁可把一个点讲透，也不要蜻蜓点水覆盖多个。\n\n"
            )
        elif v2_reply_strategy == "progressive":
            structure_guide = (
                "## 回复结构（探索引导模式）\n"
                "1. 先基于学生已说的内容做1-2个有价值的粗判断\n"
                "2. 指出当前最需要想清楚的一个核心问题\n"
                "3. 用一个具体的追问帮学生往下推\n"
                "不要铺开做完整诊断，先帮学生把方向收敛下来。\n\n"
            )
        elif v2_reply_strategy == "challenge":
            structure_guide = (
                "## 回复结构（挑战追问模式）\n"
                "1. 先承认学生想法中合理的部分\n"
                "2. 用具体数据/案例/逻辑指出最站不住脚的假设\n"
                "3. 给出另一种可能的解释或判断\n"
                "4. 深入讨论为什么学生的假设可能是错的（不要泛泛而谈）\n"
                "5. 用犀利但建设性的追问收尾\n\n"
            )
        elif v2_reply_strategy == "teach_concept":
            structure_guide = (
                "## 回复结构（概念教学模式）\n"
                "1. 用一句话通俗定义这个概念\n"
                "2. 用1-2个真实案例讲清楚\n"
                "3. 如果学生有项目背景，落回项目\n"
                "4. 给一个小练习验证理解\n\n"
            )
        elif v2_reply_strategy == "compare":
            structure_guide = (
                "## 回复结构（对比分析模式）\n"
                "1. 列出对比维度和对象\n"
                "2. 用表格呈现核心对比\n"
                "3. 给出差异化分析和深度解读\n\n"
            )
        else:
            structure_guide = (
                "## 回复结构（自适应——根据内容自行组织，不要套固定模板）\n"
                "- 如果有多个重要发现，逐一展开讨论，每个发现充分论证\n"
                "- 如果有争议维度，呈现双方观点\n"
                "- 结尾给出有深度的追问\n"
                f"- {'仅在最后一节引用行动规划素材' if has_planner else '最多给一个简短的下一步聚焦点'}\n\n"
            )

        reply = _llm.chat_text(
            system_prompt=(
                f"{persona}\n"
                + ANTI_HALLUCINATION_HEADER
                + "你的职责是把已有的分析结论组织成自然流畅的对话。\n\n"
                "## 绝对禁止\n"
                "- 不能引入分析结论中不存在的新事实、新判断或新数据\n"
                "- 不能推翻任何分析师的主结论\n"
                "- 不要提到Agent、分析师、教练等角色名称\n"
                "- 不要说'根据分析'、'经过系统分析'等套话\n"
                "- 严禁万金油建议：如果确实需要调研，必须说清调研什么假设、找什么人、问什么问题\n\n"
                "## 你可以做的\n"
                "- 决定段落顺序和详略比例\n"
                "- 如果某维度标注[有争议]，呈现双方观点而非自行裁决\n"
                "- 如果某维度标注[低置信]，在措辞上体现不确定性\n"
                "- 联网搜索结果在合适位置引用来源，结尾整理可点击链接\n\n"
                "- 如果已有案例对比、图谱关联或跨项目启示，必须把其中1-2条转成对当前项目有用的判断或追问，不能只说'找到了相似项目'\n"
                + quality_tone
                + "- 如果这是继续追问，先用1-2句承接上轮，只回答新增问题\n"
                "- 分析与解释至少占七成篇幅；行动最多放在最后一小节\n\n"
                + (
                    "## 课程辅导模式额外要求\n"
                    "- 先把学生当前这一题讲明白，保留教学性内容\n"
                    "- 语气像老师面对面讲解\n\n"
                    if mode == "coursework"
                    else "## 竞赛教练模式额外要求\n"
                    "- 保持评委视角，体现证据链强弱和获奖可能性判断\n"
                    "- 整合评分区间和扣分点\n"
                    + (
                        ("- 赛道：" + {"internet_plus": "互联网+", "challenge_cup": "挑战杯", "dachuang": "大创"}.get(state.get("competition_type", ""), "通用") + "\n\n")
                        if state.get("competition_type") else "\n"
                    )
                    if mode == "competition"
                    else "## 项目教练模式额外要求\n"
                    "- 先判断项目阶段，聚焦最关键瓶颈\n"
                    "- 启发式追问优先于直接给答案\n\n"
                )
                + structure_guide
                + "## 必须做到\n"
                "- 第一人称回复，像导师面对面聊天\n"
                "- 紧扣学生具体内容，引用原话讨论\n"
                "- 排版丰富且清晰，灵活使用以下 Markdown 元素：\n"
                "  - `## 标题` 分隔主要讨论板块（但不要每段都加标题，自然过渡也可以）\n"
                "  - `> 引用` 引用学生原话或关键观点\n"
                "  - `**加粗**` 强调关键判断、核心概念\n"
                "  - Markdown 表格：适合对比分析（如竞品、方案对比、维度打分）\n"
                "  - `- 列表`：适合枚举要点、步骤\n"
                "  - ` ```mermaid ` 流程图：当讨论涉及流程、步骤、决策路径、用户旅程、商业闭环时，\n"
                "    主动用 mermaid flowchart/graph 来可视化（支持 graph TD, graph LR, flowchart 语法）\n"
                "    例：验证步骤、用户转化漏斗、商业模式闭环、MVP 路线图、决策树等\n"
                "  - `---` 分隔线：分隔大的讨论转折\n"
                + (f"- 语气风格: {tone_guide}\n" if tone_guide else "")
                + f"- **回复长度**: {length_guide}\n"
            ),
            user_prompt=(
                f"学生说：\n{msg[:3000]}\n\n"
                + (f"对话上下文：\n{conv_ctx}\n\n" if conv_ctx else "")
                + f"多轮连续状态：\n{conv_state_summary}\n\n"
                + (f"教师批注: {tfb}\n\n" if tfb else "")
                + (f"历史: {hist[:300]}\n\n" if hist else "")
                + f"continuation_mode={continuation_mode}\n"
                + (f"reply_strategy={v2_reply_strategy}\n\n" if v2_reply_strategy else "\n")
                + (f"本轮触发规则：{'; '.join(triggered_rules)}\n\n" if triggered_rules else "")
                + (f"本轮结构缺口：{'; '.join(structural_gaps)}\n\n" if structural_gaps else "")
                + (f"## 维度分析结果（置信度+争议标记）\n{dim_results_ctx}\n\n" if dim_results_ctx else "")
                + (
                    "## 深度分析要求\n"
                    "这是一个复杂问题，你的分析素材非常丰富。请务必：\n"
                    "1. 充分利用下面所有分析素材，不要浪费任何有价值的洞察\n"
                    "2. 每个重要观点都要有展开论证，不要一句话带过\n"
                    "3. 如果分析素材中有具体的公司名、数据、案例、行业事实，全部引用\n"
                    "4. 如果不同分析之间有互补视角，要交叉引用\n"
                    "5. 宁可写长一点也不要遗漏关键洞察\n\n"
                    if v2_reply_strategy in ("comprehensive", "panorama")
                    else ""
                )
                + f"以下是问题分析素材：\n\n{analyses_ctx}\n\n"
                + (f"以下是行动规划素材（只能在最后一节使用）：\n\n{planner_block}" if has_planner else "本轮没有行动规划素材；重点放在分析本身。")
            ),
            model=settings.llm_synthesis_model,
            temperature=0.55,
        )

    elif _llm.enabled:
        # ── PATH B: Focused single-call (simple/focused intents) ──
        gathered = _build_gathered_context(state)
        focused_prompt = _FOCUSED_PROMPTS.get(intent, "")

        if intent == "general_chat":
            reply = _general_chat_reply(state)
        elif intent == "learning_concept":
            reply, _ = _build_learning_tutor_reply(state, structured=True)
        elif focused_prompt:
            logger.info("Orchestrator: focused mode for intent '%s'", intent)
            _nsr_inc = state.get("incremental_stats", {})
            _nsr_exploring = _nsr_inc.get("project_maturity") == "exploring"
            focused_model = settings.llm_fast_model if (intent == "general_chat" or _nsr_exploring) else settings.llm_reason_model
            reply = _llm.chat_text(
                system_prompt=(
                    f"{persona}\n{focused_prompt}\n\n"
                    "## 通用要求\n"
                    "- 第一人称回复，像导师面对面聊天\n"
                    "- 不要提到任何系统内部结构（Agent、模块等）\n"
                    "- 排版清晰：## 标题、> 引用、**加粗**、表格\n"
                    "- 紧扣学生的实际项目和上下文\n"
                    "- 如果已收集到多个事实或线索，不要只挑最明显的三点，要尽量把主链路讲完整\n"
                    "- 适合比较时优先使用 Markdown 表格；适合流程或因果链时可输出 mermaid 代码块\n"
                ),
                user_prompt=(
                    f"学生说：{msg[:2000]}\n\n"
                    + (f"对话上下文：\n{conv_ctx}\n\n" if conv_ctx else "")
                    + (f"已收集的信息：\n{gathered}\n" if gathered else "")
                ),
                model=focused_model,
                temperature=0.45,
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

    return {
        "assistant_message": reply.strip(),
        "conversation_continuation_mode": continuation_mode,
        "conversation_state_summary": conv_state_summary,
        "reply_strategy": v2_reply_strategy or state.get("reply_strategy", ""),
        "execution_trace": state.get("execution_trace", {}),
        "exploration_state": state.get("exploration_state", {}),
        "nodes_visited": ["orchestrator"],
    }


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
    competition_type: str = "",
) -> dict[str, Any]:
    initial: WorkflowState = {
        "message": message,
        "mode": mode,
        "competition_type": competition_type,
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
    competition_type: str = "",
) -> dict[str, Any]:
    """Run router + gather + agents but NOT orchestrator. Returns state for streaming."""
    initial: WorkflowState = {
        "message": message,
        "mode": mode,
        "competition_type": competition_type,
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
    continuation_mode = _conversation_continuation_mode(state)
    conv_state_summary = _build_conversation_state_summary(state)

    analysis_parts, planner_block = _collect_analysis_context(state)

    conv_ctx = ""
    if conv_msgs:
        recent = conv_msgs[-6:]
        conv_ctx = "\n".join(
            f"{'学生' if m.get('role')=='user' else '教练'}: {str(m.get('content',''))[:200]}"
            for m in recent
        )

    msg_len = len(msg)
    n_analyses = len(analysis_parts)
    diag = state.get("diagnosis", {}) if isinstance(state.get("diagnosis"), dict) else {}
    kg = state.get("kg_analysis", {}) if isinstance(state.get("kg_analysis"), dict) else {}
    triggered_rules = [
        str(item.get("name") or item.get("id") or "").strip()
        for item in (diag.get("triggered_rules") or [])
        if isinstance(item, dict) and str(item.get("name") or item.get("id") or "").strip()
    ]
    structural_gaps = [str(x).strip() for x in (kg.get("structural_gaps") or []) if str(x).strip()]
    if is_file:
        length_guide = "2200-4200字"
    elif intent == "general_chat":
        length_guide = "150-400字"
    elif n_analyses >= 4:
        length_guide = "1800-3600字"
    elif n_analyses >= 3:
        length_guide = "1500-3000字"
    elif n_analyses >= 2:
        length_guide = "1200-2400字"
    else:
        length_guide = "700-1400字"

    analyses_ctx = "\n\n---\n\n".join(analysis_parts)
    has_planner = bool(planner_block.strip())
    persona = _MODE_PERSONA.get(mode, _MODE_PERSONA["coursework"])

    if not _llm.enabled:
        yield "你好！告诉我你的项目想法，我来帮你诊断和分析。"
        return

    if state.get("needs_clarification"):
        yield _build_clarification_reply(state)
        return

    # ── V3: Dimension-driven orchestration ──
    dim_results = state.get("dim_results", {})
    if dim_results and not analyses_ctx:
        v3_strategy = state.get("reply_strategy", "progressive")
        missing_hints = state.get("missing_dim_hints", [])
        n_dims = len([d for d, r in dim_results.items() if r.get("value")])

        dim_content_parts: list[str] = []
        for dim_key, dr in dim_results.items():
            val = str(dr.get("value") or "").strip()
            if not val:
                continue
            dim_label = ANALYSIS_DIMENSIONS.get(dim_key, {}).get("label", dim_key)
            contested = dr.get("contested", False)
            marker = " [有争议]" if contested else ""
            dim_content_parts.append(f"**{dim_label}{marker}**:\n{val}")

        dim_content = "\n\n".join(dim_content_parts) if dim_content_parts else ""

        _orch_hyper_insight = state.get("hypergraph_insight", {})
        _hyper_summary = ""
        if isinstance(_orch_hyper_insight, dict):
            _hs = str(_orch_hyper_insight.get("summary", "")).strip()
            if _hs:
                _hyper_summary = f"\n超图摘要: {_hs[:200]}"
            for _he in (_orch_hyper_insight.get("edges") or [])[:3]:
                if isinstance(_he, dict) and _he.get("teaching_note"):
                    _hyper_summary += f"\n超图启发[{_he.get('family_label', '')}]: {str(_he['teaching_note'])[:80]}"

        _is_guiding = bool(missing_hints)
        if _is_guiding:
            _v3_sys = (
                f"{persona}\n"
                "你是一位经验丰富的项目导师，正在和学生一对一聊项目想法。\n"
                "学生目前还在项目早期/探索阶段，你的核心任务是**带着学生一步步完善想法**，而不是批评。\n\n"
                "## 回复原则\n"
                "- 先肯定学生已有想法中值得认可的部分\n"
                "- 综合下面的多维度分析，帮学生看清当前处在什么阶段、最该先想清楚什么\n"
                "- 不要把所有维度都堆上去，选最重要的2-3个展开，其余留做追问\n"
                "- 如果有超图教学启发或案例线索，自然融入（'你有没有想过XX'、'之前有个类似的项目XX'）\n"
                "- 结尾给出2-3个具体追问，引导学生往缺失方向深入\n"
                "- 追问要具体、可回答的（不是'你怎么看用户需求'，而是'你身边有多少同学会为这个功能付费？'）\n\n"
                "## 格式要求\n"
                "- 像导师面对面聊天的语气（600-1400字）\n"
                "- 不要套报告模板（现状→策略空间→聚焦→多维洞察）\n"
                "- 不要列举'缺少XX维度'来批评学生\n"
                "- 不要提到Agent、分析师等角色\n"
                "- 可以用 **加粗**、> 引用、```mermaid 流程图\n"
            )
            _v3_usr = (
                f"学生说：{msg[:2000]}\n\n"
                + (f"对话上下文：\n{conv_ctx}\n\n" if conv_ctx else "")
                + (f"## 多维度分析结果\n{dim_content}\n\n" if dim_content else "")
                + (f"学生还没聊到的方向（用追问引导，不要直接列出来批评）：{', '.join(missing_hints)}\n" if missing_hints else "")
                + (_hyper_summary + "\n" if _hyper_summary else "")
            )
        else:
            _v3_sys = (
                f"{persona}\n"
                "你拿到了多个维度的深度分析结果，请综合成一份有层次的回复。\n\n"
                "## 回复要求\n"
                "- 用你自己的判断决定先说什么、后说什么，不要按固定模板\n"
                "- 从最重要的发现说起\n"
                "- 如果某维度标注[有争议]，呈现双方观点\n"
                "- 有案例/数据支撑的观点充分展开\n"
                "- 涉及流程/决策时用 ```mermaid 流程图\n"
                "- 用 **加粗** 强调、> 引用学生原话、表格做对比\n"
                "- 结尾给2-4个推进追问\n"
                "- 不要提到Agent、分析师等角色\n"
                f"- 回复长度：{length_guide}\n"
            )
            _v3_usr = (
                f"学生说：{msg[:3000]}\n\n"
                + (f"对话上下文：\n{conv_ctx}\n\n" if conv_ctx else "")
                + (f"教师批注: {tfb}\n\n" if tfb else "")
                + f"## 各维度分析结果\n\n{dim_content}\n\n"
                + (f"本轮触发规则：{'; '.join(triggered_rules)}\n" if triggered_rules else "")
                + (_hyper_summary + "\n" if _hyper_summary else "")
            )

        for chunk in _llm.chat_text_stream(
            system_prompt=_v3_sys,
            user_prompt=_v3_usr,
            model=settings.llm_synthesis_model,
            temperature=0.5,
        ):
            yield chunk
        return

    if not analyses_ctx:
        # ── Focused intent path (no agents ran) ──
        gathered = _build_gathered_context(state)
        focused_prompt = _FOCUSED_PROMPTS.get(intent, "")
        if intent == "general_chat":
            for chunk in _general_chat_reply_stream(state):
                yield chunk
            return
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
                "- 排版丰富：## 标题、> 引用、**加粗**、表格、`- 列表`\n"
                "- 涉及流程/步骤/决策时，用 ```mermaid 流程图可视化\n"
                "- 紧扣学生的实际项目和上下文\n"
            )
            _usr = (
                f"学生说：{msg[:2000]}\n\n"
                + (f"对话上下文：\n{conv_ctx}\n\n" if conv_ctx else "")
                + f"已收集的信息：\n{gathered}\n"
            )
            _foc_inc = state.get("incremental_stats", {})
            _foc_exploring = _foc_inc.get("project_maturity") == "exploring"
            focused_model = settings.llm_fast_model if (intent == "general_chat" or _foc_exploring) else settings.llm_reason_model
            for chunk in _llm.chat_text_stream(
                system_prompt=_sys, user_prompt=_usr,
                model=focused_model, temperature=0.45,
            ):
                yield chunk
            return
        else:
            diag = state.get("diagnosis", {})
            bn = str(diag.get("bottleneck") or "")
            yield bn if bn else "你好！告诉我你的项目想法，我来帮你诊断和分析。"
            return

    # ── V2: Multi-agent synthesis path with dynamic strategy ──
    dim_results = state.get("dim_results", {})
    v2_reply_strategy = state.get("reply_strategy", "")
    v2_spec = REPLY_STRATEGIES.get(v2_reply_strategy, {})

    if v2_spec:
        length_guide = v2_spec.get("length", length_guide)
        tone_guide = v2_spec.get("tone", "")
    else:
        tone_guide = ""

    dim_ctx_parts: list[str] = []
    for dim_key, dr in dim_results.items():
        dim_label = ANALYSIS_DIMENSIONS.get(dim_key, {}).get("label", dim_key)
        conf = round(float(dr.get("confidence", 0)), 2)
        contested = dr.get("contested", False)
        val_preview = str(dr.get("value", ""))[:400]
        marker = ""
        if contested:
            marker = " [有争议]"
            amendments = dr.get("amendments", [])
            if amendments:
                marker += f" 挑战: {amendments[0][:80]}"
        elif conf < 0.6:
            marker = " [低置信]"
        dim_ctx_parts.append(f"- {dim_label}(置信度{conf}{marker}): {val_preview}")
    dim_results_ctx = "\n".join(dim_ctx_parts) if dim_ctx_parts else ""

    if v2_reply_strategy == "comprehensive":
        structure_guide = (
            "## 回复结构（全面深度分析——复杂问题，请充分展开）\n"
            "你有丰富的分析素材，请用**你自己的判断**决定组织方式，以下是可选的切面（不必全用，按相关性选择）：\n"
            "- 核心判断：项目目前真正卡在哪，为什么卡\n"
            "- 深层原因：表面问题背后的结构性原因\n"
            "- 盲区/反直觉洞察：学生可能没想到的角度\n"
            "- 外部参考：案例对比、行业事实（有就引用，没有不编）\n"
            "- 策略方向：2-3条可选路径\n"
            "- 推进追问：3-5个帮学生往前走的问题\n\n"
            "**要求**：用自然的叙述推进逻辑，不要每段都加一级标题变成报告；该用表格用表格，该用流程图用 mermaid\n"
            "**禁止**：不要按固定模板（现状→策略空间→聚焦→多维洞察）输出\n\n"
        )
    elif v2_reply_strategy == "panorama":
        structure_guide = (
            "## 回复结构（多维分析——灵活组织）\n"
            "用你自己的判断决定哪些维度值得展开、哪些一笔带过：\n"
            "- 从最重要的发现说起，不要按模板顺序\n"
            "- 有数据/案例支撑的观点充分展开\n"
            "- 结尾给推进追问\n"
            "**禁止**：不要机械按'现状→原因→洞察→案例→策略'固定顺序\n\n"
        )
    elif v2_reply_strategy == "deep_dive":
        structure_guide = (
            "## 回复结构（深度分析——请灵活组织，不要用固定模板）\n"
            "根据学生的具体问题自然展开，可能的切入角度：\n"
            "- 如果学生在问方向：帮他理清核心逻辑，给出你的判断和理由\n"
            "- 如果学生在问执行：聚焦最关键的1-2个执行瓶颈，讲透\n"
            "- 如果学生给了详细材料：找到最值得深挖的点展开\n"
            "- 用你自己的判断决定先说什么、后说什么\n"
            "- 结尾给1-2个推进性追问\n\n"
            "**禁止**：不要机械按'现状→策略空间→聚焦→多维洞察'这种固定顺序输出\n\n"
        )
    elif v2_reply_strategy == "progressive":
        structure_guide = (
            "## 回复结构（探索引导模式——学生还在初步构思阶段）\n"
            "**核心原则：引导 > 诊断，启发 > 批评**\n"
            "1. 先肯定学生已有的方向感觉或思考亮点（具体说哪里有意思）\n"
            "2. 帮学生把最模糊的那个点具体化（用追问而非断言）\n"
            "3. 如果搜到了相关案例或知识库线索，用'你有没有想过XX'的方式自然引入\n"
            "4. 结尾一个推进性追问，帮学生往下走一步\n\n"
            "**严禁做的事**：\n"
            "- 不要列举'缺少XX维度'、'缺少XX分析'，学生还在想，缺东西是正常的\n"
            "- 不要一次给全套框架（商业模式画布、SWOT、竞品矩阵等）\n"
            "- 不要用'空想'、'不切实际'之类的措辞\n"
            "- 不要输出超过800字，保持对话感\n\n"
        )
    elif v2_reply_strategy == "challenge":
        structure_guide = (
            "## 回复结构（挑战追问模式）\n"
            "1. 承认合理部分\n2. 指出最弱假设\n3. 深入讨论为什么可能是错的\n4. 替代解释\n5. 犀利追问收尾\n\n"
        )
    elif v2_reply_strategy == "teach_concept":
        structure_guide = "## 回复结构（概念教学模式）\n1. 通俗定义\n2. 真实案例\n3. 落回项目\n4. 小练习\n\n"
    elif v2_reply_strategy == "compare":
        structure_guide = (
            "## 回复结构（对比分析模式）\n"
            "1. 列出对比维度和对象\n2. 用表格呈现核心对比\n3. 差异化分析和深度解读\n\n"
        )
    else:
        structure_guide = (
            "## 回复结构（自适应——请像真人导师一样自然对话）\n"
            "- 根据学生问的具体事情自行组织回复，不套任何固定模板\n"
            "- 先回应学生最关心的点，再展开你认为重要的补充\n"
            "- 该深入的深入，该简短的简短\n"
            "- 结尾给1-2个推进追问\n\n"
        )

    system_prompt = (
        f"{persona}\n"
        + ANTI_HALLUCINATION_HEADER
        + "你的职责是把已有的分析结论组织成自然流畅的对话。\n\n"
        "## 绝对禁止\n"
        "- 不能引入分析结论中不存在的新事实\n"
        "- 不要提到Agent、分析师等角色名称\n"
        "- 严禁万金油建议\n\n"
        "## 你可以做的\n"
        "- 决定段落顺序和详略比例\n"
        "- 如果某维度[有争议]，呈现双方观点\n"
        "- 如果某维度[低置信]，措辞体现不确定性\n"
        "- 联网结果引用来源\n\n"
        "- 继续追问场景只回答新增问题\n"
        "- 分析占七成篇幅，行动放最后\n\n"
        + (
            "## 课程辅导模式\n- 先把这一题讲明白，语气像老师面对面讲解\n\n"
            if mode == "coursework"
            else "## 竞赛教练模式\n- 评委视角，整合评分区间和扣分点\n\n"
            if mode == "competition"
            else "## 项目教练模式\n- 聚焦最关键瓶颈，启发式追问优先\n\n"
        )
        + structure_guide
        + "## 必须做到\n"
        "- 第一人称'我'回复，紧扣学生原话\n"
        "- 排版丰富且清晰，灵活使用以下 Markdown 元素：\n"
        "  - `## 标题` 分隔主要板块（不要机械每段加标题，自然过渡也行）\n"
        "  - `> 引用` 引用学生原话或关键观点\n"
        "  - `**加粗**` 强调关键判断和核心概念\n"
        "  - Markdown 表格：适合对比分析（竞品、方案对比、维度打分）\n"
        "  - `- 列表`：枚举要点、步骤\n"
        "  - ` ```mermaid ` 流程图：当讨论涉及流程、步骤、决策路径、用户旅程、商业闭环时，\n"
        "    主动用 mermaid flowchart 来可视化（graph TD/LR 语法）。\n"
        "    适用场景：验证步骤、用户转化漏斗、商业模式闭环、MVP路线图、决策树等\n"
        "  - `---` 分隔线：分隔大的讨论转折\n"
        "- 如果已有案例对比、图谱关联或跨项目启示，必须把其中1-2条转成对当前项目有用的判断或追问，不能停留在“找到了相似案例”\n"
        + (f"- 语气风格: {tone_guide}\n" if tone_guide else "")
        + f"- 回复长度: {length_guide}\n"
    )

    # Build orchestrator-level hypergraph context
    _orch_hyper_insight = state.get("hypergraph_insight", {})
    _orch_hyper_student = state.get("hypergraph_student", {})
    _orch_hyper_parts: list[str] = []
    _hi_edges = (_orch_hyper_insight.get("edges") or []) if isinstance(_orch_hyper_insight, dict) else []
    _hi_summary_text = str(_orch_hyper_insight.get("summary", "")).strip() if isinstance(_orch_hyper_insight, dict) else ""
    if _hi_edges or _hi_summary_text:
        if _hi_summary_text:
            _orch_hyper_parts.append(f"超图摘要: {_hi_summary_text[:200]}")
        for _he in _hi_edges[:6]:
            if isinstance(_he, dict) and _he.get("teaching_note"):
                _fam = _he.get("family_label", "") or _he.get("type", "")
                _orch_hyper_parts.append(f"教学超边[{_fam}]: {str(_he['teaching_note'])[:80]}")
    if isinstance(_orch_hyper_student, dict) and _orch_hyper_student.get("ok"):
        _cov = _orch_hyper_student.get("coverage_score", 0)
        _orch_hyper_parts.append(f"维度覆盖度: {_cov}/10")
        for _pw in (_orch_hyper_student.get("pattern_warnings") or [])[:2]:
            if isinstance(_pw, dict):
                _orch_hyper_parts.append(f"风险模式: {str(_pw.get('warning',''))[:80]}")
    _orch_hyper_ctx = "\n".join(_orch_hyper_parts) if _orch_hyper_parts else ""
    _orch_hist_knowledge = state.get("history_knowledge_ctx", "")

    user_prompt = (
        f"学生说：\n{msg[:3000]}\n\n"
        + (f"对话上下文：\n{conv_ctx}\n\n" if conv_ctx else "")
        + f"多轮连续状态：\n{conv_state_summary}\n\n"
        + (f"教师批注: {tfb}\n\n" if tfb else "")
        + (f"历史: {hist[:300]}\n\n" if hist else "")
        + f"continuation_mode={continuation_mode}\n"
        + (f"reply_strategy={v2_reply_strategy}\n\n" if v2_reply_strategy else "\n")
        + (f"本轮触发规则：{'; '.join(triggered_rules)}\n\n" if triggered_rules else "")
        + (f"本轮结构缺口：{'; '.join(structural_gaps)}\n\n" if structural_gaps else "")
        + (f"## 超图分析\n{_orch_hyper_ctx}\n\n" if _orch_hyper_ctx else "")
        + (f"## 前几轮知识积累\n{_orch_hist_knowledge}\n\n" if _orch_hist_knowledge else "")
        + (f"## 维度分析结果\n{dim_results_ctx}\n\n" if dim_results_ctx else "")
        + (
            "## 深度分析要求\n"
            "这是一个复杂问题，分析素材非常丰富。请务必：\n"
            "1. 充分利用所有分析素材（包括超图洞察），不要浪费有价值的洞察\n"
            "2. 每个重要观点充分展开论证\n"
            "3. 具体公司名、数据、案例、行业事实全部引用\n"
            "4. 如果超图提供了教学超边或风险模式，将其自然融入你的回复中\n"
            "5. 宁可写长也不遗漏关键洞察\n\n"
            if v2_reply_strategy in ("comprehensive", "panorama")
            else ""
        )
        + f"以下是问题分析素材：\n\n{analyses_ctx}\n\n"
        + (f"以下是行动规划素材（只能在最后一节使用）：\n\n{planner_block}" if has_planner else "本轮没有行动规划素材。")
    )

    _orch_inc = state.get("incremental_stats", {})
    _orch_exploring = _orch_inc.get("project_maturity") == "exploring"
    _orch_model = settings.llm_fast_model if _orch_exploring else settings.llm_synthesis_model

    for chunk in _llm.chat_text_stream(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=_orch_model,
        temperature=0.55,
    ):
        yield chunk
