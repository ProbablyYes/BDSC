from __future__ import annotations

"""Centralized ontology and rubric wiring for the venture KG.

This module does NOT talk to Neo4j directly. It serves as a
single source of truth for:

- Ontology nodes: core concepts, methods, deliverables, metrics
- Rubric → required evidence chains
- Rubric → common error pools
- Rule → linked ontology concepts

The goal is to make every score and every risk finding traceable
back to explicit concepts and artifacts, instead of opaque LLM
heuristics.
"""

from dataclasses import dataclass, field, replace
from typing import Any, Iterable


@dataclass(frozen=True)
class OntologyNode:
    id: str
    # concept | method | deliverable | metric | task | pitfall | evidence
    kind: str
    label: str
    description: str
    # —— 运行时语义骨架字段（向后兼容，默认值都为空集合）——
    # 同义词/口语词/英文别名，用于 OntologyResolver.normalize 文本→canonical_id
    aliases: tuple[str, ...] = field(default_factory=tuple)
    # 上位概念 id，用于推理式覆盖（父命中时其子孙也算覆盖）
    parent: str | None = None
    # 在哪些 stage_v2 阶段属于"期望覆盖"（idea/structured/validated/scale）
    stage_expected: tuple[str, ...] = field(default_factory=tuple)
    # Critic 追问素材：当本节点缺失时可以拼接到追问 prompt 里
    probing_questions: tuple[str, ...] = field(default_factory=tuple)


# NOTE: keep ids stable; they are used as references from rubric and rules.
ONTOLOGY_NODES: dict[str, OntologyNode] = {}


def _add_nodes(nodes: Iterable[tuple[str, str, str, str]]) -> None:
    """旧版接口，仅含 (id, kind, label, description)，aliases/parent/stage/probing 走 _enrich_nodes 补。"""
    for nid, kind, label, desc in nodes:
        if nid in ONTOLOGY_NODES:
            continue
        ONTOLOGY_NODES[nid] = OntologyNode(id=nid, kind=kind, label=label, description=desc)


def _enrich_nodes(meta: dict[str, dict[str, Any]]) -> None:
    """给已注册节点叠加 aliases/parent/stage_expected/probing_questions。

    meta = {
        "C_xxx": {
            "aliases": ("...", "..."),
            "parent": "C_yyy",
            "stage_expected": ("structured", "validated"),
            "probing_questions": ("...", "..."),
        },
        ...
    }
    """
    for nid, payload in meta.items():
        node = ONTOLOGY_NODES.get(nid)
        if not node:
            continue
        ONTOLOGY_NODES[nid] = replace(
            node,
            aliases=tuple(payload.get("aliases") or node.aliases),
            parent=payload.get("parent", node.parent),
            stage_expected=tuple(payload.get("stage_expected") or node.stage_expected),
            probing_questions=tuple(payload.get("probing_questions") or node.probing_questions),
        )


# Core concepts (创业通用)
_add_nodes([
    ("C_problem", "concept", "Problem Definition", "对目标用户的具体问题和场景进行清晰刻画的能力"),
    ("C_user_segment", "concept", "Target User Segment", "可操作的细分客群，而不是泛泛的所有人"),
    ("C_value_proposition", "concept", "Value Proposition", "痛点→收益→产品主张之间的一致性"),
    ("C_solution", "concept", "Solution", "为目标用户设计的产品/服务组合"),
    ("C_business_model", "concept", "Business Model", "价值主张、渠道、收入、成本之间的闭环结构"),
    ("C_market_size", "concept", "Market Size", "TAM/SAM/SOM 分层的市场规模逻辑"),
    ("C_competition", "concept", "Competition Landscape", "直接/间接竞品与替代品构成的竞争格局"),
    ("C_team", "concept", "Founding Team", "团队角色分工与资源匹配度"),
    ("C_roadmap", "concept", "Milestone Roadmap", "阶段性目标与可交付物规划"),
    ("C_risk_control", "concept", "Risk & Compliance", "合规、伦理与数据安全控制"),
])

# Methods
_add_nodes([
    ("M_user_interview", "method", "User Interview", "通过半结构化访谈收集用户原话与场景信息"),
    ("M_survey", "method", "Survey", "通过问卷定量验证需求、支付意愿等假设"),
    ("M_competitor_matrix", "method", "Competitor Matrix", "按关键维度对比直接/间接竞品"),
    ("M_leancanvas", "method", "Lean Canvas", "用一页画布串联核心要素"),
    ("M_mvp", "method", "MVP Experiment", "用最小可行产品验证关键假设"),
    ("M_ab_test", "method", "A/B Test", "比较不同方案在真实环境下的表现"),
    ("M_unit_economics", "method", "Unit Economics Modeling", "围绕单个用户或订单构建收益/成本模型"),
    ("M_tam_sam_som", "method", "TAM/SAM/SOM Modeling", "自下而上量化市场空间"),
    ("M_risk_register", "method", "Risk Register", "系统登记并跟踪关键风险与对策"),
    ("M_competition_mapping", "method", "Competition Mapping", "绘制竞争格局与替代品地图"),
])

# Deliverables
_add_nodes([
    ("D_bp", "deliverable", "Business Plan", "结构化商业计划书文档"),
    ("D_pitch_deck", "deliverable", "Pitch Deck", "用于路演的 PPT/演示文档"),
    ("D_interview_notes", "deliverable", "Interview Notes", "用户访谈记录与痛点频次统计表"),
    ("D_survey_report", "deliverable", "Survey Report", "问卷设计、样本说明与关键结论"),
    ("D_competitor_table", "deliverable", "Competitor Comparison Table", "主流方案的对比矩阵"),
    ("D_financial_model", "deliverable", "Financial Model", "收入、成本、现金流与盈亏平衡测算表"),
    ("D_roadmap", "deliverable", "Roadmap", "阶段里程碑与验收标准清单"),
    ("D_risk_checklist", "deliverable", "Risk & Compliance Checklist", "数据与合规检查清单"),
    ("D_metric_dashboard", "deliverable", "Metric Dashboard", "核心业务指标看板"),
])

# Metrics
_add_nodes([
    ("X_tam", "metric", "TAM", "总体可服务市场总量"),
    ("X_sam", "metric", "SAM", "产品理论可覆盖的细分市场"),
    ("X_som", "metric", "SOM", "在现实约束下可获得的市场份额"),
    ("X_cac", "metric", "CAC", "Customer Acquisition Cost — 获得一个付费用户的全部成本"),
    ("X_ltv", "metric", "LTV", "Lifetime Value — 单个用户在生命周期内贡献的毛利"),
    ("X_payback", "metric", "Payback Period", "收回获客成本所需时间"),
    ("X_retention", "metric", "Retention", "留存率/复购率等粘性指标"),
    ("X_conversion", "metric", "Conversion Rate", "从触达到付费的转化率"),
    ("X_arpu", "metric", "ARPU", "Average Revenue Per User — 用户平均收入"),
    ("X_nps", "metric", "NPS", "Net Promoter Score，净推荐值"),
])

# 额外补足：围绕概念、方法、交付物、指标扩展到 100+ 节点
# 为简洁起见，这里不一一注释，仅保证覆盖度和多样性。
_add_nodes([
    ("C_value_chain", "concept", "Value Chain", "从原材料到用户价值的全链路"),
    ("C_channel", "concept", "Acquisition Channel", "获客与触达用户的路径"),
    ("C_revenue_stream", "concept", "Revenue Stream", "项目收入来源构成"),
    ("C_cost_structure", "concept", "Cost Structure", "固定成本与变动成本结构"),
    ("C_moat", "concept", "Competitive Moat", "难以被复制的竞争壁垒"),
    ("C_positioning", "concept", "Positioning", "在用户心智中的定位"),
    ("C_growth_model", "concept", "Growth Model", "项目增长路径与飞轮机制"),
    ("C_kpi", "concept", "Key KPI", "衡量项目阶段性成效的关键指标"),
    ("C_user_journey", "concept", "User Journey", "用户从认知到复购的完整旅程"),
    ("C_risk_category_market", "concept", "Market Risk", "需求、规模与竞争相关风险"),
    ("C_risk_category_product", "concept", "Product Risk", "方案可行性与体验相关风险"),
    ("C_risk_category_execution", "concept", "Execution Risk", "团队与资源执行相关风险"),
    ("C_risk_category_financial", "concept", "Financial Risk", "现金流与盈利能力风险"),
    ("M_usability_test", "method", "Usability Test", "针对产品可用性的可用性测试"),
    ("M_cohort_analysis", "method", "Cohort Analysis", "分 cohort 追踪用户行为和留存"),
    ("M_growth_experiment", "method", "Growth Experiment", "围绕增长杠杆设计实验"),
    ("M_sensitivity_analysis", "method", "Sensitivity Analysis", "对关键假设做敏感性分析"),
    ("M_risk_workshop", "method", "Risk Workshop", "团队集体识别并排序风险"),
    ("M_storytelling", "method", "Storytelling", "用叙事结构讲清楚项目逻辑"),
    ("D_kpi_report", "deliverable", "KPI Report", "阶段性关键指标达成情况报告"),
    ("D_usability_report", "deliverable", "Usability Test Report", "可用性测试设计与结果"),
    ("D_competition_map", "deliverable", "Competition Map", "竞品与替代品可视化地图"),
    ("D_growth_experiment_log", "deliverable", "Growth Experiment Log", "增长实验记录与结论"),
    ("D_case_study_positive", "deliverable", "Positive Case Study", "正面成功案例分析"),
    ("D_case_study_negative", "deliverable", "Negative Case Study", "反面失败案例分析"),
    ("D_rubric_sheet", "deliverable", "Rubric Sheet", "评审打分表与维度说明"),
    ("X_ctr", "metric", "CTR", "Click-through Rate — 点击率"),
    ("X_churn", "metric", "Churn Rate", "流失率"),
    ("X_gmv", "metric", "GMV", "成交总额"),
    ("X_margin", "metric", "Gross Margin", "毛利率"),
    ("X_cashburn", "metric", "Cash Burn", "现金消耗速度"),
    ("X_runway", "metric", "Runway", "可维持运营的时间"),
])

# 继续扩展使总节点数远超 100，覆盖教材、赛事规则、模板等概念占位
_add_nodes([
    ("C_textbook_foundation", "concept", "Entrepreneurship Textbook", "双创教材中的基础概念集合"),
    ("C_competition_rule_internet_plus", "concept", "互联网+ Competition Rules", "互联网+ 大赛评分与规则要点"),
    ("C_competition_rule_challenge_cup", "concept", "挑战杯 Rules", "挑战杯大赛的评审标准与注意事项"),
    ("C_competition_rule_dachuang", "concept", "大创 Rules", "大学生创新创业训练计划的评审标准与注意事项"),
    ("C_iplus_business_innovation", "concept", "互联网+ 商业模式创新", "互联网+评审重点：商业模式的创新性、可持续盈利能力和市场潜力"),
    ("C_iplus_social_impact", "concept", "互联网+ 社会影响力", "互联网+评审重点：项目对社会的积极影响和带动就业能力"),
    ("C_iplus_tam_sam_som", "concept", "互联网+ 市场论证", "互联网+评审重点：TAM/SAM/SOM论证清晰度和市场可进入性分析"),
    ("C_challenge_tech_innovation", "concept", "挑战杯 科技创新含量", "挑战杯评审重点：技术难度、创新含量和原型验证"),
    ("C_challenge_evidence_rigor", "concept", "挑战杯 调研严谨性", "挑战杯评审重点：用户调研和实验数据的严谨性与可重复性"),
    ("C_dachuang_feasibility", "concept", "大创 方案可行性", "大创评审重点：方案的实际动手能力、可落地性和阶段性成果"),
    ("C_dachuang_process_record", "concept", "大创 过程记录", "大创评审重点：训练过程文档化、里程碑追踪和成果展示"),
    ("D_bp_template_standard", "deliverable", "Standard BP Template", "标准化商业计划书模板结构"),
    ("D_pitch_template_competition", "deliverable", "Competition Pitch Template", "面向大赛的标准路演模板"),
    ("D_rule_guide_internet_plus", "deliverable", "互联网+ Rule Guide", "互联网+ 官方规则精读笔记"),
    ("D_rule_guide_challenge_cup", "deliverable", "挑战杯 Rule Guide", "挑战杯规则精读与解读"),
    ("D_rule_guide_dachuang", "deliverable", "大创 Rule Guide", "大创项目申请规则精读与解读"),
    ("D_case_library_positive", "deliverable", "Positive Case Library", "不少于50个正面案例库入口"),
    ("D_case_library_negative", "deliverable", "Negative Case Library", "不少于50个反面案例库入口"),
    ("C_rubric_dimension_problem", "concept", "Rubric: Problem", "评审维度：问题与痛点定义"),
    ("C_rubric_dimension_evidence", "concept", "Rubric: Evidence", "评审维度：证据链完整度"),
    ("C_rubric_dimension_business_model", "concept", "Rubric: Business Model", "评审维度：商业模式一致性"),
    ("C_rubric_dimension_risk", "concept", "Rubric: Risk", "评审维度：风险与合规"),
    ("C_rubric_dimension_team", "concept", "Rubric: Team", "评审维度：团队与执行力"),
    ("C_rubric_dimension_presentation", "concept", "Rubric: Presentation", "评审维度：路演表达与结构"),
])


# Tasks: learning actions that students can execute to close specific gaps.
_add_nodes([
    (
        "T_task_user_evidence_loop",
        "task",
        "完成用户证据闭环",
        "围绕单一用户场景完成至少8份访谈/若干份问卷，并形成痛点频次与反证样本矩阵。",
    ),
    (
        "T_task_value_proposition_consistency",
        "task",
        "重做价值主张一致性表",
        "聚焦一个核心客群，重写价值主张，并校验渠道/收入与之逐项对应。",
    ),
    (
        "T_task_unit_economics",
        "task",
        "补齐单位经济模型",
        "搭建 CAC/LTV/BEP 三表，给出关键假设来源，并检查 LTV>CAC。",
    ),
    (
        "T_task_risk_checklist",
        "task",
        "完成合规与伦理检查清单",
        "梳理数据采集→存储→使用→销毁链路，补齐隐私与合规控制点。",
    ),
])


# Pitfalls: common failure patterns captured as ontology nodes for traceability.
_add_nodes([
    (
        "P_no_competitor_claim",
        "pitfall",
        "声称没有竞争对手",
        "典型误区：认为市场中没有任何竞品或替代方案，忽视隐形替代品与机会成本。",
    ),
    (
        "P_market_size_fallacy",
        "pitfall",
        "1% 市场规模幻觉",
        "典型误区：用 TAM×1% 直接推算营收，自上而下估算缺乏自下而上的可达路径。",
    ),
    (
        "P_weak_user_evidence",
        "pitfall",
        "需求证据不足",
        "典型误区：只凭主观感觉或少量非目标用户反馈，就下结论认为需求强烈。",
    ),
    (
        "P_compliance_not_covered",
        "pitfall",
        "合规与伦理缺口",
        "典型误区：在涉及隐私/医疗/未成年人等场景时，未给出任何合规与伦理控制说明。",
    ),
])


# Evidence atoms: frequently referenced evidence artifacts.
_add_nodes([
    (
        "E_user_interview_raw",
        "evidence",
        "用户访谈原始记录",
        "包含时间、对象、场景与用户原话的访谈记录，用于支撑痛点与需求分析。",
    ),
    (
        "E_survey_dataset",
        "evidence",
        "问卷数据集",
        "包含样本量、问卷设计与关键统计结果的原始数据，用于验证需求与支付意愿。",
    ),
    (
        "E_financial_assumption_sheet",
        "evidence",
        "财务假设说明表",
        "列出营收、成本、转化率等关键假设及其数据来源，支撑财务模型合理性。",
    ),
])


# ────────────────────────────────────────────────────────────────
# 运行时语义骨架元数据
# ────────────────────────────────────────────────────────────────
# 给已注册节点叠加 aliases / parent / stage_expected / probing_questions。
# 命名约定:
#   - aliases: 同义词/口语词/英文别名（OntologyResolver 文本归一时使用）
#   - parent: 上位概念 id（推理式覆盖：父命中=子孙也覆盖）
#   - stage_expected: idea / structured / validated / scale 中应当覆盖的阶段
#   - probing_questions: 节点缺失时 Critic 可拼接的追问问题
# 没有列出的节点会保持空集合，行为等同"不参与归一/推理/追问"。

_enrich_nodes({
    # ── 核心概念 ──
    "C_problem": {
        "aliases": ("问题定义", "痛点", "用户痛点", "problem", "pain point"),
        "stage_expected": ("idea", "structured", "validated", "scale"),
        "probing_questions": (
            "目标用户在什么场景下遇到了这个问题？",
            "他们目前用什么方式解决，付出的代价是什么？",
        ),
    },
    "C_user_segment": {
        "aliases": ("目标用户", "细分客群", "客群", "user segment", "target user"),
        "stage_expected": ("idea", "structured", "validated", "scale"),
        "probing_questions": (
            "你描述的用户是不是足够具体？比如年龄、地域、岗位、消费能力？",
            "这群人为什么是你最先服务的，而不是其他相邻人群？",
        ),
    },
    "C_value_proposition": {
        "aliases": ("价值主张", "价值定位", "value prop", "value proposition", "卖点逻辑"),
        "stage_expected": ("structured", "validated", "scale"),
        "probing_questions": (
            "用一句话说出'为什么用户要选你而不是替代方案'？",
            "这个价值能不能被一个具体的指标量化？",
        ),
    },
    "C_solution": {
        "aliases": ("解决方案", "产品方案", "solution", "产品形态"),
        "stage_expected": ("structured", "validated", "scale"),
        "probing_questions": (
            "方案的核心步骤有几步？哪些是你最有把握做好的？",
            "如果只能保留一个功能，你会留哪个，为什么？",
        ),
    },
    "C_business_model": {
        "aliases": ("商业模式", "盈利模式", "business model", "BM"),
        "stage_expected": ("structured", "validated", "scale"),
        "probing_questions": (
            "你向谁收费？为什么是他们而不是用户本身？",
            "成本结构里最大的一块是什么，能不能被规模摊薄？",
        ),
    },
    "C_market_size": {
        "aliases": ("市场规模", "市场容量", "TAM/SAM/SOM", "市场空间"),
        "stage_expected": ("structured", "validated", "scale"),
        "probing_questions": (
            "你估算市场规模的口径是自下而上还是自上而下？",
            "三年内你最有把握拿到的 SOM 是多少？",
        ),
    },
    "C_competition": {
        "aliases": ("竞品", "竞争格局", "替代方案", "竞争对手", "competition"),
        "stage_expected": ("structured", "validated", "scale"),
        "probing_questions": (
            "用户当前最常用的替代方案是什么？为什么它还没解决问题？",
            "和直接竞品相比，你最难被复制的优势是什么？",
        ),
    },
    "C_team": {
        "aliases": ("团队", "创始团队", "team", "founding team"),
        "stage_expected": ("structured", "validated", "scale"),
        "probing_questions": (
            "团队里谁负责哪一块？关键岗位有没有缺口？",
            "你们之前一起完成过什么项目，能证明协作能力？",
        ),
    },
    "C_roadmap": {
        "aliases": ("里程碑", "路线图", "roadmap", "产品节奏"),
        "stage_expected": ("structured", "validated", "scale"),
        "probing_questions": (
            "未来 6/12 个月最关键的 3 个里程碑是什么？",
            "每个里程碑的验收标准能不能写成一句话？",
        ),
    },
    "C_risk_control": {
        "aliases": ("风险控制", "合规", "伦理", "risk control", "compliance"),
        "stage_expected": ("validated", "scale"),
        "probing_questions": (
            "项目涉及隐私/医疗/未成年人/资金等敏感场景吗？",
            "你目前对这些风险有什么具体的控制措施？",
        ),
    },
    "C_value_chain": {
        "aliases": ("价值链", "value chain"),
        "parent": "C_business_model",
    },
    "C_channel": {
        "aliases": ("渠道", "获客渠道", "channel", "GTM"),
        "parent": "C_business_model",
        "stage_expected": ("structured", "validated", "scale"),
        "probing_questions": (
            "你打算用哪条渠道触达目标用户？这条渠道的成本和转化大概是多少？",
        ),
    },
    "C_revenue_stream": {
        "aliases": ("收入来源", "营收结构", "revenue stream"),
        "parent": "C_business_model",
        "stage_expected": ("structured", "validated", "scale"),
    },
    "C_cost_structure": {
        "aliases": ("成本结构", "cost structure"),
        "parent": "C_business_model",
        "stage_expected": ("structured", "validated", "scale"),
    },
    "C_moat": {
        "aliases": ("壁垒", "护城河", "moat", "差异化"),
        "parent": "C_competition",
        "stage_expected": ("validated", "scale"),
    },
    "C_positioning": {
        "aliases": ("定位", "市场定位", "positioning"),
        "parent": "C_competition",
    },
    "C_growth_model": {
        "aliases": ("增长模式", "增长飞轮", "growth model", "growth loop"),
        "parent": "C_business_model",
        "stage_expected": ("validated", "scale"),
    },
    "C_kpi": {
        "aliases": ("关键指标", "KPI", "key metric"),
        "parent": "C_business_model",
    },
    "C_user_journey": {
        "aliases": ("用户旅程", "user journey", "用户路径"),
        "parent": "C_user_segment",
    },
    "C_risk_category_market": {
        "aliases": ("市场风险", "需求风险", "market risk"),
        "parent": "C_risk_control",
    },
    "C_risk_category_product": {
        "aliases": ("产品风险", "技术风险", "product risk"),
        "parent": "C_risk_control",
    },
    "C_risk_category_execution": {
        "aliases": ("执行风险", "团队风险", "execution risk"),
        "parent": "C_risk_control",
    },
    "C_risk_category_financial": {
        "aliases": ("财务风险", "现金流风险", "financial risk"),
        "parent": "C_risk_control",
    },
    # ── 方法 ──
    "M_user_interview": {
        "aliases": ("用户访谈", "深访", "user interview", "1v1 访谈"),
        "stage_expected": ("idea", "structured", "validated"),
        "probing_questions": ("你完成过几次访谈？被访谈者是不是真的目标用户？",),
    },
    "M_survey": {
        "aliases": ("问卷", "survey", "调查"),
        "stage_expected": ("structured", "validated"),
        "probing_questions": ("问卷样本量多少？是怎么筛选的？",),
    },
    "M_competitor_matrix": {
        "aliases": ("竞品矩阵", "竞品对比表", "competitor matrix"),
        "parent": "C_competition",
    },
    "M_leancanvas": {
        "aliases": ("精益画布", "Lean Canvas"),
        "parent": "C_business_model",
    },
    "M_mvp": {
        "aliases": ("MVP", "最小可行产品", "minimum viable product"),
        "parent": "C_solution",
        "stage_expected": ("structured", "validated"),
        "probing_questions": ("有没有跑过 MVP？最小验证目标是什么？",),
    },
    "M_ab_test": {
        "aliases": ("A/B 测试", "AB test"),
        "parent": "M_mvp",
    },
    "M_unit_economics": {
        "aliases": ("单位经济", "unit economics", "单笔经济模型"),
        "parent": "C_business_model",
        "stage_expected": ("validated", "scale"),
        "probing_questions": (
            "LTV/CAC 比值是多少？",
            "Payback 周期超过 12 个月吗？",
        ),
    },
    "M_tam_sam_som": {
        "aliases": ("TAM/SAM/SOM", "市场拆分", "TAM"),
        "parent": "C_market_size",
        "stage_expected": ("structured", "validated", "scale"),
    },
    "M_risk_register": {
        "aliases": ("风险登记表", "risk register"),
        "parent": "C_risk_control",
    },
    "M_competition_mapping": {
        "aliases": ("竞争地图", "competition mapping"),
        "parent": "C_competition",
    },
    "M_usability_test": {
        "aliases": ("可用性测试", "usability test"),
        "parent": "M_mvp",
    },
    "M_cohort_analysis": {
        "aliases": ("cohort 分析", "队列分析"),
        "parent": "C_growth_model",
    },
    "M_growth_experiment": {
        "aliases": ("增长实验", "growth experiment"),
        "parent": "C_growth_model",
    },
    "M_sensitivity_analysis": {
        "aliases": ("敏感性分析", "sensitivity analysis"),
        "parent": "M_unit_economics",
    },
    "M_risk_workshop": {
        "aliases": ("风险工作坊", "risk workshop"),
        "parent": "C_risk_control",
    },
    "M_storytelling": {
        "aliases": ("叙事", "故事化", "storytelling", "讲故事"),
        "parent": "D_pitch_deck",
    },
    # ── 交付物 ──
    "D_bp": {
        "aliases": ("商业计划书", "BP", "business plan"),
        "stage_expected": ("structured", "validated", "scale"),
    },
    "D_pitch_deck": {
        "aliases": ("路演 PPT", "Pitch Deck", "路演文档"),
        "stage_expected": ("validated", "scale"),
    },
    "D_interview_notes": {
        "aliases": ("访谈记录", "interview notes", "访谈纪要"),
        "parent": "M_user_interview",
    },
    "D_survey_report": {
        "aliases": ("问卷报告", "survey report"),
        "parent": "M_survey",
    },
    "D_competitor_table": {
        "aliases": ("竞品对比表", "competitor table"),
        "parent": "M_competitor_matrix",
    },
    "D_financial_model": {
        "aliases": ("财务模型", "financial model", "财务测算"),
        "parent": "C_business_model",
        "stage_expected": ("validated", "scale"),
    },
    "D_roadmap": {
        "aliases": ("路线图文档", "roadmap doc"),
        "parent": "C_roadmap",
    },
    "D_risk_checklist": {
        "aliases": ("风险检查清单", "compliance checklist", "合规清单"),
        "parent": "C_risk_control",
    },
    "D_metric_dashboard": {
        "aliases": ("指标看板", "metric dashboard"),
        "parent": "C_kpi",
    },
    "D_kpi_report": {
        "aliases": ("KPI 报告", "KPI report"),
        "parent": "C_kpi",
    },
    "D_usability_report": {
        "aliases": ("可用性测试报告",),
        "parent": "M_usability_test",
    },
    "D_competition_map": {
        "aliases": ("竞品地图",),
        "parent": "C_competition",
    },
    "D_growth_experiment_log": {
        "aliases": ("增长实验记录",),
        "parent": "M_growth_experiment",
    },
    # ── 指标 ──
    "X_tam": {"aliases": ("TAM", "总可服务市场"), "parent": "C_market_size"},
    "X_sam": {"aliases": ("SAM", "可触达市场"), "parent": "C_market_size"},
    "X_som": {"aliases": ("SOM", "可获得市场"), "parent": "C_market_size"},
    "X_cac": {
        "aliases": ("CAC", "获客成本", "客户获取成本", "拉新成本", "新客成本", "单客成本"),
        "parent": "C_risk_category_financial",
    },
    "X_ltv": {
        "aliases": ("LTV", "客户生命周期价值"),
        "parent": "C_risk_category_financial",
    },
    "X_payback": {
        "aliases": ("回本周期", "Payback", "Payback Period"),
        "parent": "C_risk_category_financial",
    },
    "X_retention": {"aliases": ("留存", "留存率", "retention", "复购率", "用户留存"), "parent": "C_growth_model"},
    "X_conversion": {"aliases": ("转化率", "conversion", "CVR"), "parent": "C_growth_model"},
    "X_arpu": {"aliases": ("ARPU", "用户平均收入"), "parent": "C_revenue_stream"},
    "X_nps": {"aliases": ("NPS", "净推荐值"), "parent": "C_kpi"},
    "X_ctr": {"aliases": ("CTR", "点击率"), "parent": "C_growth_model"},
    "X_churn": {"aliases": ("Churn", "流失率"), "parent": "C_growth_model"},
    "X_gmv": {"aliases": ("GMV", "成交总额"), "parent": "C_revenue_stream"},
    "X_margin": {"aliases": ("毛利率", "Gross Margin", "margin"), "parent": "C_cost_structure"},
    "X_cashburn": {"aliases": ("现金消耗", "burn rate"), "parent": "C_risk_category_financial"},
    "X_runway": {"aliases": ("Runway", "现金跑道"), "parent": "C_risk_category_financial"},
    # ── 任务 ──
    "T_task_user_evidence_loop": {
        "stage_expected": ("idea", "structured"),
    },
    "T_task_value_proposition_consistency": {
        "stage_expected": ("structured", "validated"),
    },
    "T_task_unit_economics": {
        "stage_expected": ("validated", "scale"),
    },
    "T_task_risk_checklist": {
        "stage_expected": ("validated", "scale"),
    },
    # ── 误区 ──
    "P_no_competitor_claim": {
        "aliases": ("没有竞争对手", "无竞品", "市场没有人在做"),
        "parent": "C_competition",
    },
    "P_market_size_fallacy": {
        "aliases": ("1% 市场幻觉", "拍脑袋市场规模"),
        "parent": "C_market_size",
    },
    "P_weak_user_evidence": {
        "aliases": ("证据不足", "我觉得", "拍脑袋"),
        "parent": "C_user_segment",
    },
    "P_compliance_not_covered": {
        "aliases": ("合规缺口", "未涉及合规"),
        "parent": "C_risk_control",
    },
})


# ────────────────────────────────────────────────────────────────
# Rubric wiring
# ────────────────────────────────────────────────────────────────

# Map rubric item label → required ontology nodes (as ids) that form the
# "evidence chain" for this dimension.
RUBRIC_EVIDENCE_CHAIN: dict[str, list[str]] = {
    "Problem Definition": [
        "C_problem", "C_user_segment", "C_user_journey", "D_interview_notes",
    ],
    "User Evidence Strength": [
        "C_rubric_dimension_evidence", "M_user_interview", "M_survey",
        "D_interview_notes", "D_survey_report",
    ],
    "Solution Feasibility": [
        "C_solution", "M_mvp", "M_usability_test", "D_usability_report",
    ],
    "Business Model Consistency": [
        "C_business_model", "C_value_proposition", "C_channel",
        "C_revenue_stream", "C_cost_structure", "M_unit_economics",
        "D_financial_model",
    ],
    "Market & Competition": [
        "C_market_size", "M_tam_sam_som", "C_competition",
        "M_competition_mapping", "D_competitor_table",
    ],
    "Financial Logic": [
        "C_risk_category_financial", "M_unit_economics", "M_sensitivity_analysis",
        "X_cac", "X_ltv", "X_payback", "X_margin", "D_financial_model",
    ],
    "Innovation & Differentiation": [
        "C_moat", "C_positioning", "M_competitor_matrix",
        "D_competition_map", "D_case_study_positive",
    ],
    "Team & Execution": [
        "C_team", "C_risk_category_execution", "D_roadmap", "D_kpi_report",
    ],
    "Presentation Quality": [
        "C_rubric_dimension_presentation", "M_storytelling", "D_pitch_deck",
    ],
}


# Map rubric item label → common error pools (as short textual labels).
RUBRIC_ERROR_POOL: dict[str, list[str]] = {
    "Problem Definition": [
        "目标用户过于宽泛（所有人/大学生/上班族）",
        "场景描述抽象，缺少具体时空与行为",
        "痛点只是抱怨而非具体代价",
    ],
    "User Evidence Strength": [
        "只凭个人直觉，没有任何访谈或问卷",
        "样本量过小且无目标客群筛选",
        "没有记录用户原话，仅有总结性描述",
    ],
    "Solution Feasibility": [
        "方案停留在口号，缺少可执行步骤",
        "没有任何原型/MVP 演示或测试记录",
        "技术路线与团队能力/资源不匹配",
    ],
    "Business Model Consistency": [
        "价值主张与收费对象不一致",
        "渠道不可达目标用户，仅依赖自然裂变",
        "收入来源与成本结构无对应关系",
    ],
    "Market & Competition": [
        "声称没有竞争对手或只有巨头",
        "TAM/SAM/SOM 口径混乱，自上而下拍脑袋",
        "只罗列产品功能，不分析替代方案",
    ],
    "Financial Logic": [
        "未计算 CAC/LTV，仅口头说能赚钱",
        "现金流与资金需求缺乏测算",
        "依赖不现实的转化率或增长假设",
    ],
    "Innovation & Differentiation": [
        "只说创新，不给出可验证的对比依据",
        "差异化停留在宣传语层面",
        "忽视用户现有解决方案的满意度",
    ],
    "Team & Execution": [
        "团队履历与项目领域完全不相关",
        "里程碑时间表过于激进且无验收标准",
        "关键岗位缺失或一人身兼数职",
    ],
    "Presentation Quality": [
        "路演结构混乱，缺少问题→方案→市场→模式→团队→里程碑的基本顺序",
        "大量堆砌概念与行话，缺少以用户故事开场",
        "数据与图表无来源说明或与口头表述矛盾",
    ],
}


# Map risk rule id (H1-H15, ...) → related ontology concepts/deliverables.
RULE_ONTOLOGY_MAP: dict[str, list[str]] = {
    "H1": ["C_value_proposition", "C_user_segment", "C_channel"],
    "H2": ["C_channel", "C_user_journey"],
    "H3": ["X_ltv", "M_survey", "D_survey_report"],
    "H4": ["C_market_size", "M_tam_sam_som", "X_tam", "X_sam", "X_som"],
    "H5": ["C_rubric_dimension_evidence", "M_user_interview", "D_interview_notes"],
    "H6": ["C_competition", "M_competitor_matrix", "D_competitor_table"],
    "H7": ["C_moat", "M_mvp", "M_usability_test"],
    "H8": ["M_unit_economics", "X_cac", "X_ltv", "X_payback"],
    "H9": ["C_growth_model", "M_growth_experiment"],
    "H10": ["C_roadmap", "D_roadmap"],
    "H11": ["C_risk_control", "D_risk_checklist"],
    "H12": ["C_risk_category_execution", "M_sensitivity_analysis"],
    "H13": ["M_ab_test", "X_conversion"],
    "H14": ["M_storytelling", "D_pitch_deck"],
    "H15": ["C_rubric_dimension_evidence", "D_rubric_sheet"],
}


# Map risk rule id → recommended task nodes (learning actions).
RULE_TASK_MAP: dict[str, list[str]] = {
    "H1": ["T_task_value_proposition_consistency"],
    "H5": ["T_task_user_evidence_loop"],
    "H8": ["T_task_unit_economics"],
    "H11": ["T_task_risk_checklist"],
}


def serialize_node(node: OntologyNode) -> dict[str, Any]:
    """Serialize OntologyNode to a JSON-safe dict including new runtime fields."""
    return {
        "id": node.id,
        "kind": node.kind,
        "label": node.label,
        "description": node.description,
        "aliases": list(node.aliases),
        "parent": node.parent,
        "stage_expected": list(node.stage_expected),
        "probing_questions": list(node.probing_questions),
    }


def get_rubric_evidence_chain(item: str) -> list[dict[str, Any]]:
    """Return ontology-backed evidence chain for a rubric dimension.

    Each element includes minimal info so that frontend/LLM can present
    human-readable traceability without needing to know ontology ids.
    """
    node_ids = RUBRIC_EVIDENCE_CHAIN.get(item, [])
    out: list[dict[str, Any]] = []
    for nid in node_ids:
        node = ONTOLOGY_NODES.get(nid)
        if not node:
            continue
        out.append(serialize_node(node))
    return out


def get_rubric_error_pool(item: str) -> list[str]:
    return list(RUBRIC_ERROR_POOL.get(item, []))


def get_rule_ontology_nodes(rule_id: str) -> list[dict[str, Any]]:
    node_ids = RULE_ONTOLOGY_MAP.get(rule_id, [])
    out: list[dict[str, Any]] = []
    for nid in node_ids:
        node = ONTOLOGY_NODES.get(nid)
        if not node:
            continue
        out.append({
            "id": node.id,
            "kind": node.kind,
            "label": node.label,
            "description": node.description,
        })
    return out


def get_rule_tasks(rule_id: str) -> list[dict[str, Any]]:
    """Return ontology-backed task nodes associated with a risk rule.

    This allows the diagnosis engine to surface not only what is wrong
    (rule hit), but also which learning tasks可以帮助学生补齐短板。
    """
    node_ids = RULE_TASK_MAP.get(rule_id, [])
    out: list[dict[str, Any]] = []
    for nid in node_ids:
        node = ONTOLOGY_NODES.get(nid)
        if not node:
            continue
        out.append(
            {
                "id": node.id,
                "kind": node.kind,
                "label": node.label,
                "description": node.description,
            }
        )
    return out
