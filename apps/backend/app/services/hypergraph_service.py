"""HyperNetX-based hypergraph service for teaching & student analysis.

This service focuses on **logical consistency diagnosis** rather than
storage. It exposes three layers that correspond directly to the
requirements:

1. Hyperedge templates (>=20 types)
     - Declarative patterns over KG dimensions, e.g.
         "痛点-人群-解决方案-商业模式闭环"、"问题-方案-证据三角" 等。
2. Consistency rules (>=20 rules)
     - G1–G20 operate on dimension coverage + text signals to检测
         “无竞争对手”、“1% 市场份额”、“CAC 与渠道不匹配”等逻辑幻觉。
3. Student dynamic analysis
     - Builds a temporary HyperNetX hypergraph from extracted entities
         and applies the above templates/rules to produce可追溯的诊断结果。

It does **not** parse raw files itself; all文件解析与分段由
``HypergraphDocument`` 完成，本服务只消费结构化后的 KG 实体。"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import hypernetx as hnx

from app.config import settings
from app.services.graph_service import GraphService
from app.services.kg_ontology import ONTOLOGY_NODES

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────
#  Data classes
# ─────────────────────────────────────────────────────

@dataclass
class HyperedgeRecord:
    hyperedge_id: str
    type: str
    support: int
    teaching_note: str
    category: str | None
    rules: list[str] = field(default_factory=list)
    rubrics: list[str] = field(default_factory=list)
    evidence_quotes: list[str] = field(default_factory=list)
    retrieval_reason: str = ""
    node_set: set[str] | None = None
    source_project_ids: list[str] = field(default_factory=list)
    member_nodes: list[dict[str, str]] = field(default_factory=list)
    confidence: float = 0.0
    severity: str = ""
    score_impact: float = 0.0
    stage_scope: str = ""


# ─────────────────────────────────────────────────────
#  Hyperedge templates & diagnostic rules (declarative)
# ─────────────────────────────────────────────────────

# Each template describes an ideal or diagnostic hyperedge pattern
# across dimensions (stakeholder, pain_point, solution, etc.).
_HYPEREDGE_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "T1_user_pain_solution_bm",
        "name": "痛点-人群-解决方案-商业模式闭环",
        "dimensions": ["stakeholder", "pain_point", "solution", "business_model"],
        "description": "用户→痛点→方案→商业模式形成完整闭环",
        "pattern_type": "ideal",
        "linked_rules": ["H1", "H2", "H3"],
    },
    {
        "id": "T2_user_pain_evidence",
        "name": "痛点证据链",
        "dimensions": ["stakeholder", "pain_point", "evidence"],
        "description": "针对核心痛点提供用户证据",
        "pattern_type": "ideal",
        "linked_rules": ["H5"],
    },
    {
        "id": "T3_solution_tech_market",
        "name": "方案-技术-市场匹配",
        "dimensions": ["solution", "technology", "market"],
        "description": "技术路线与目标市场匹配",
    },
    {
        "id": "T4_market_competition_solution",
        "name": "市场-竞品-方案定位",
        "dimensions": ["market", "competitor", "solution"],
        "description": "在既有竞争格局中清晰定位方案",
    },
    {
        "id": "T5_business_model_finance",
        "name": "商业模式-财务逻辑",
        "dimensions": ["business_model", "resource", "team"],
        "description": "商业模式与资源/团队可行性匹配",
    },
    {
        "id": "T6_unit_economics",
        "name": "单位经济模型闭环",
        "dimensions": ["business_model", "market", "resource"],
        "description": "单位经济与市场/资源约束一致",
        "pattern_type": "ideal",
        "linked_rules": ["H8", "H9"],
    },
    {
        "id": "T7_growth_path",
        "name": "增长路径",
        "dimensions": ["stakeholder", "channel", "market"],
        "description": "获客渠道与目标用户/市场相匹配",
    },
    {
        "id": "T8_team_execution",
        "name": "团队-里程碑-资源",
        "dimensions": ["team", "resource", "market"],
        "description": "团队能力与关键资源支撑里程碑达成",
    },
    {
        "id": "T9_risk_control",
        "name": "风险与合规",
        "dimensions": ["risk", "evidence", "market"],
        "description": "涉及数据/合规场景时给出控制措施",
        "pattern_type": "ideal",
        "linked_rules": ["H11"],
    },
    {
        "id": "T10_user_pain_solution_evidence",
        "name": "问题-方案-证据三角",
        "dimensions": ["stakeholder", "pain_point", "solution", "evidence"],
        "description": "核心方案有用户与实验双重证据支持",
        "pattern_type": "ideal",
        "linked_rules": ["H5", "H7"],
    },
    # 占位模板用于覆盖更多变体，便于后续细化
    {
        "id": "T11_market_size_growth",
        "name": "市场规模-增长假设",
        "dimensions": ["market", "business_model"],
        "description": "市场规模与增长路径假设一致",
        "pattern_type": "risk",
        "linked_rules": ["H4", "H9"],
    },
    {
        "id": "T12_competition_moat",
        "name": "竞品-护城河",
        "dimensions": ["competitor", "resource", "business_model"],
        "description": "在竞争格局中说明护城河与资源壁垒",
        "pattern_type": "ideal",
        "linked_rules": ["H6", "H7"],
    },
    {
        "id": "T13_tech_feasibility",
        "name": "技术可行性",
        "dimensions": ["technology", "team", "resource"],
        "description": "技术方案与团队/资源能力匹配",
    },
    {
        "id": "T14_evidence_financial",
        "name": "证据-财务",
        "dimensions": ["evidence", "business_model"],
        "description": "财务模型关键参数有数据或实验支撑",
        "pattern_type": "risk",
        "linked_rules": ["H8"],
    },
    {
        "id": "T15_evidence_market",
        "name": "证据-市场规模",
        "dimensions": ["evidence", "market"],
        "description": "市场规模假设有公开数据或调研支撑",
        "pattern_type": "risk",
        "linked_rules": ["H4"],
    },
    {
        "id": "T16_user_channel",
        "name": "用户-渠道匹配",
        "dimensions": ["stakeholder", "channel"],
        "description": "获客渠道与用户行为习惯匹配",
        "pattern_type": "ideal",
        "linked_rules": ["H2"],
    },
    {
        "id": "T17_pain_solution_pricing",
        "name": "痛点-方案-定价",
        "dimensions": ["pain_point", "solution", "business_model"],
        "description": "定价与痛点强度/替代方案价格一致",
        "pattern_type": "risk",
        "linked_rules": ["H3"],
    },
    {
        "id": "T18_team_risk",
        "name": "团队-风险",
        "dimensions": ["team", "risk"],
        "description": "关键风险有明确负责人与缓解计划",
        "pattern_type": "ideal",
        "linked_rules": ["H10", "H11"],
    },
    {
        "id": "T19_loop_full",
        "name": "完整商业闭环",
        "dimensions": [
            "stakeholder", "pain_point", "solution",
            "market", "competitor", "business_model",
        ],
        "description": "从用户到商业模式的完整闭环",
        "pattern_type": "ideal",
        "linked_rules": ["H1", "H2", "H3", "H4", "H6", "H8"],
    },
    {
        "id": "T20_growth_defensibility",
        "name": "增长-护城河",
        "dimensions": ["market", "business_model", "resource"],
        "description": "增长路径与护城河相互支撑",
        "pattern_type": "ideal",
        "linked_rules": ["H6", "H9", "H12"],
    },
    {
        "id": "T21_team_capability_gap",
        "name": "团队能力缺口",
        "dimensions": ["team", "technology", "execution_step"],
        "description": "团队现有能力与技术/执行要求之间的差距",
        "pattern_type": "risk",
        "linked_rules": ["H9", "H10"],
    },
    {
        "id": "T22_user_journey",
        "name": "用户旅程闭环",
        "dimensions": ["stakeholder", "channel", "pain_point", "solution"],
        "description": "从触达到留存的完整用户旅程",
        "pattern_type": "ideal",
        "linked_rules": ["H1", "H2"],
    },
    {
        "id": "T23_social_impact",
        "name": "社会价值链",
        "dimensions": ["stakeholder", "pain_point", "evidence", "market"],
        "description": "公益/ESG维度的社会影响评估",
        "pattern_type": "ideal",
        "linked_rules": ["H5"],
    },
    {
        "id": "T24_data_flywheel",
        "name": "数据飞轮",
        "dimensions": ["solution", "stakeholder", "technology", "business_model"],
        "description": "数据积累驱动产品壁垒和用户价值提升",
        "pattern_type": "ideal",
        "linked_rules": ["H7", "H12"],
    },
    {
        "id": "T25_scalability_bottleneck",
        "name": "规模化瓶颈",
        "dimensions": ["market", "resource", "team", "risk"],
        "description": "从MVP到规模化的关键约束分析",
        "pattern_type": "risk",
        "linked_rules": ["H9", "H14"],
    },
    {
        "id": "T26_ip_moat",
        "name": "知识产权护城河",
        "dimensions": ["technology", "resource", "competitor"],
        "description": "专利/算法/数据等不可复制壁垒",
        "pattern_type": "ideal",
        "linked_rules": ["H7", "H12"],
    },
    {
        "id": "T27_pivot_signal",
        "name": "转型信号",
        "dimensions": ["evidence", "stakeholder", "pain_point", "market"],
        "description": "用户反馈与市场信号暗示需要调整方向",
        "pattern_type": "risk",
        "linked_rules": ["H1", "H5"],
    },
    {
        "id": "T28_cost_structure",
        "name": "成本结构",
        "dimensions": ["business_model", "resource", "technology"],
        "description": "固定成本、变动成本与技术基础设施的关系",
        "pattern_type": "risk",
        "linked_rules": ["H8", "H10"],
    },
    {
        "id": "T29_ecosystem_dependency",
        "name": "生态依赖",
        "dimensions": ["solution", "technology", "risk"],
        "description": "对平台/供应商/API的依赖与锁定风险",
        "pattern_type": "risk",
        "linked_rules": ["H11", "H14"],
    },
    {
        "id": "T30_mvp_scope",
        "name": "MVP边界",
        "dimensions": ["solution", "stakeholder", "execution_step", "evidence"],
        "description": "最小可行产品的范围划定与验证策略",
        "pattern_type": "ideal",
        "linked_rules": ["H5", "H10"],
    },
    {
        "id": "T31_stakeholder_conflict",
        "name": "利益相关方冲突",
        "dimensions": ["stakeholder", "business_model", "risk"],
        "description": "多方利益不一致时的平衡机制",
        "pattern_type": "risk",
        "linked_rules": ["H1", "H3"],
    },
    {
        "id": "T32_channel_conversion",
        "name": "渠道转化漏斗",
        "dimensions": ["channel", "stakeholder", "evidence", "business_model"],
        "description": "获客渠道的转化率、成本与LTV关系",
        "pattern_type": "ideal",
        "linked_rules": ["H2", "H8"],
    },
    {
        "id": "T33_regulatory_landscape",
        "name": "政策法规环境",
        "dimensions": ["risk", "market", "evidence"],
        "description": "行业法规对商业模式和市场准入的影响",
        "pattern_type": "risk",
        "linked_rules": ["H11", "H15"],
    },
    {
        "id": "T34_presentation_narrative",
        "name": "路演叙事线",
        "dimensions": ["stakeholder", "pain_point", "solution", "evidence"],
        "description": "从故事到数据再到方案的路演逻辑链",
        "pattern_type": "ideal",
        "linked_rules": ["H13"],
    },
    {
        "id": "T35_resource_leverage",
        "name": "资源杠杆",
        "dimensions": ["resource", "team", "business_model"],
        "description": "用有限资源撬动最大价值的策略",
        "pattern_type": "ideal",
        "linked_rules": ["H9", "H14"],
    },
    {
        "id": "T36_timing_window",
        "name": "时机窗口",
        "dimensions": ["market", "technology", "competitor"],
        "description": "市场时机与技术成熟度的匹配判断",
        "pattern_type": "risk",
        "linked_rules": ["H4", "H6"],
    },
    {
        "id": "T37_revenue_sustainability",
        "name": "收入可持续性",
        "dimensions": ["business_model", "market", "evidence"],
        "description": "收入模型是否可持续而非一次性",
        "pattern_type": "risk",
        "linked_rules": ["H8", "H26"],
    },
    {
        "id": "T38_demand_supply_match",
        "name": "供需匹配",
        "dimensions": ["stakeholder", "pain_point", "market", "solution"],
        "description": "用户需求与产品供给是否真正匹配",
        "pattern_type": "ideal",
        "linked_rules": ["H1", "H5"],
    },
    {
        "id": "T39_founder_risk",
        "name": "创始人风险",
        "dimensions": ["team", "execution_step", "risk"],
        "description": "关键人物依赖与单点故障风险",
        "pattern_type": "risk",
        "linked_rules": ["H10", "H21", "H25"],
    },
    {
        "id": "T40_ethical_bias",
        "name": "伦理偏见",
        "dimensions": ["solution", "stakeholder", "risk"],
        "description": "AI/算法类项目的公平性与伦理风险",
        "pattern_type": "risk",
        "linked_rules": ["H11", "H22"],
    },
    {
        "id": "T41_assumption_stack",
        "name": "假设堆叠",
        "dimensions": ["pain_point", "solution", "evidence", "business_model"],
        "description": "项目建立在多少层未验证假设之上",
        "pattern_type": "risk",
        "linked_rules": ["H5", "H7", "H20"],
    },
    {
        "id": "T42_metric_definition",
        "name": "指标定义",
        "dimensions": ["evidence", "solution", "business_model"],
        "description": "成功指标是否清晰可衡量",
        "pattern_type": "ideal",
        "linked_rules": ["H13", "H20"],
    },
    {
        "id": "T43_market_segmentation",
        "name": "市场细分",
        "dimensions": ["stakeholder", "market", "pain_point"],
        "description": "目标市场是否过于笼统缺乏聚焦",
        "pattern_type": "risk",
        "linked_rules": ["H1", "H4", "H19"],
    },
    {
        "id": "T44_competitive_response",
        "name": "竞品反应",
        "dimensions": ["innovation", "market", "solution"],
        "description": "竞品或巨头的模仿与反制风险",
        "pattern_type": "risk",
        "linked_rules": ["H6", "H7", "H16"],
    },
    {
        "id": "T45_milestone_dependency",
        "name": "里程碑依赖",
        "dimensions": ["execution_step", "solution", "business_model"],
        "description": "里程碑之间的依赖关系与容错空间",
        "pattern_type": "risk",
        "linked_rules": ["H10", "H21"],
    },
    {
        "id": "T46_funding_stage_fit",
        "name": "融资阶段匹配",
        "dimensions": ["business_model", "market", "evidence"],
        "description": "融资节奏与业务阶段是否匹配",
        "pattern_type": "risk",
        "linked_rules": ["H9", "H24"],
    },
    {
        "id": "T47_switching_cost",
        "name": "用户切换成本",
        "dimensions": ["stakeholder", "solution", "innovation"],
        "description": "用户从现有方案迁移到新方案的成本",
        "pattern_type": "risk",
        "linked_rules": ["H16", "H17"],
    },
    {
        "id": "T48_network_effect",
        "name": "网络效应",
        "dimensions": ["stakeholder", "solution", "market", "business_model"],
        "description": "产品是否具备真正的网络效应增长逻辑",
        "pattern_type": "ideal",
        "linked_rules": ["H7", "H9"],
    },
    {
        "id": "T49_cross_dimension_coherence",
        "name": "跨维度一致性",
        "dimensions": ["stakeholder", "solution", "business_model", "market"],
        "description": "项目各维度之间叙述是否自洽连贯",
        "pattern_type": "ideal",
        "linked_rules": ["H14"],
    },
    {
        "id": "T50_esg_measurability",
        "name": "ESG可量化",
        "dimensions": ["stakeholder", "pain_point", "evidence"],
        "description": "社会影响是否可量化可验证",
        "pattern_type": "ideal",
        "linked_rules": ["H5", "H13"],
    },
    {
        "id": "T51_narrative_evidence_chain",
        "name": "叙事证据链",
        "dimensions": ["stakeholder", "pain_point", "evidence", "solution"],
        "description": "叙事逻辑有证据支撑",
        "pattern_type": "ideal",
        "linked_rules": ["H5", "H13"],
    },
    {
        "id": "T52_stage_narrative_fit",
        "name": "阶段叙事匹配",
        "dimensions": ["execution_step", "stakeholder", "evidence", "business_model"],
        "description": "当前阶段叙事与目标一致",
        "pattern_type": "ideal",
        "linked_rules": ["H14"],
    },
    {
        "id": "T53_pmf_validation",
        "name": "产品市场匹配验证",
        "dimensions": ["stakeholder", "pain_point", "solution", "evidence"],
        "description": "通过证据验证PMF",
        "pattern_type": "ideal",
        "linked_rules": ["H1", "H5"],
    },
    {
        "id": "T54_user_segmentation_evidence",
        "name": "用户分层证据",
        "dimensions": ["stakeholder", "market", "evidence", "channel"],
        "description": "用户细分有数据支撑",
        "pattern_type": "risk",
        "linked_rules": ["H4", "H5"],
    },
    {
        "id": "T55_assumption_evidence_gap",
        "name": "假设证据缺口",
        "dimensions": ["pain_point", "solution", "evidence", "risk"],
        "description": "关键假设缺少验证证据",
        "pattern_type": "risk",
        "linked_rules": ["H5", "H7"],
    },
    {
        "id": "T56_risk_cascade_chain",
        "name": "风险级联链",
        "dimensions": ["risk", "risk_control", "business_model", "execution_step"],
        "description": "风险可能级联影响商业逻辑",
        "pattern_type": "risk",
        "linked_rules": ["H11", "H14"],
    },
    {
        "id": "T57_resource_milestone_fit",
        "name": "资源里程碑匹配",
        "dimensions": ["resource", "team", "execution_step", "evidence"],
        "description": "资源配置与里程碑节点对齐",
        "pattern_type": "ideal",
        "linked_rules": ["H10", "H12"],
    },
    {
        "id": "T58_execution_feedback",
        "name": "执行反馈闭环",
        "dimensions": ["execution_step", "evidence", "solution", "stakeholder"],
        "description": "执行结果反馈至方案迭代",
        "pattern_type": "ideal",
        "linked_rules": ["H5", "H10"],
    },
    {
        "id": "T59_data_privacy_chain",
        "name": "数据隐私链",
        "dimensions": ["stakeholder", "technology", "risk_control", "evidence"],
        "description": "涉及用户数据时的隐私合规链路",
        "pattern_type": "risk",
        "linked_rules": ["H11"],
    },
    {
        "id": "T60_industry_compliance_path",
        "name": "行业合规路径",
        "dimensions": ["risk_control", "market", "execution_step", "evidence"],
        "description": "行业法规遵从的执行路径",
        "pattern_type": "risk",
        "linked_rules": ["H11", "H15"],
    },
    {
        "id": "T61_ethical_impact_assessment",
        "name": "伦理影响评估",
        "dimensions": ["stakeholder", "solution", "risk", "evidence"],
        "description": "方案对用户的伦理影响评估",
        "pattern_type": "risk",
        "linked_rules": ["H11"],
    },
    {
        "id": "T62_cashflow_sustainability",
        "name": "现金流可持续性",
        "dimensions": ["business_model", "resource", "market", "evidence"],
        "description": "现金流模型可持续性验证",
        "pattern_type": "risk",
        "linked_rules": ["H8", "H9"],
    },
    {
        "id": "T63_unit_economics_evidence",
        "name": "单位经济验证",
        "dimensions": ["business_model", "evidence", "stakeholder", "channel"],
        "description": "单位经济模型有数据支撑",
        "pattern_type": "ideal",
        "linked_rules": ["H8"],
    },
    {
        "id": "T64_competitive_defense",
        "name": "竞争防御策略",
        "dimensions": ["competitor", "innovation", "resource", "business_model"],
        "description": "面对竞品的防御壁垒策略",
        "pattern_type": "ideal",
        "linked_rules": ["H6", "H7"],
    },
    {
        "id": "T65_innovation_moat",
        "name": "创新护城河",
        "dimensions": ["innovation", "technology", "evidence", "competitor"],
        "description": "创新构建的技术护城河",
        "pattern_type": "ideal",
        "linked_rules": ["H7", "H12"],
    },
    {
        "id": "T66_community_driven_growth",
        "name": "社区驱动增长",
        "dimensions": ["stakeholder", "channel", "evidence", "solution"],
        "description": "通过社区运营驱动用户增长",
        "pattern_type": "ideal",
        "linked_rules": ["H2", "H9"],
    },
    {
        "id": "T67_retention_evidence",
        "name": "留存证据链",
        "dimensions": ["stakeholder", "solution", "evidence", "channel"],
        "description": "用户留存有数据证据支撑",
        "pattern_type": "ideal",
        "linked_rules": ["H5", "H8"],
    },
    {
        "id": "T68_partnership_value",
        "name": "合作价值网络",
        "dimensions": ["resource", "team", "business_model", "market"],
        "description": "多方合作形成价值网络",
        "pattern_type": "ideal",
        "linked_rules": ["H10", "H12"],
    },
    {
        "id": "T69_supply_chain_resilience",
        "name": "供应链韧性",
        "dimensions": ["resource", "solution", "technology", "risk_control"],
        "description": "供应链抗风险能力评估",
        "pattern_type": "risk",
        "linked_rules": ["H11", "H14"],
    },
    {
        "id": "T70_platform_ecosystem",
        "name": "平台生态动态",
        "dimensions": ["stakeholder", "solution", "channel", "business_model"],
        "description": "平台多边生态的动态平衡",
        "pattern_type": "ideal",
        "linked_rules": ["H2", "H7"],
    },
    {
        "id": "T71_environmental_measurability",
        "name": "环境可量化",
        "dimensions": ["evidence", "stakeholder", "market", "risk"],
        "description": "环境影响可量化可追踪",
        "pattern_type": "ideal",
        "linked_rules": ["H5", "H13"],
    },
    {
        "id": "T72_governance_structure",
        "name": "治理结构",
        "dimensions": ["team", "risk_control", "execution_step", "evidence"],
        "description": "治理结构透明可问责",
        "pattern_type": "ideal",
        "linked_rules": ["H10", "H11"],
    },
    {
        "id": "T73_community_impact_loop",
        "name": "社区影响闭环",
        "dimensions": ["stakeholder", "pain_point", "evidence", "channel"],
        "description": "社区影响可衡量可闭环",
        "pattern_type": "ideal",
        "linked_rules": ["H5", "H13"],
    },
    {
        "id": "T74_pain_discovery_method",
        "name": "痛点发现方法论",
        "dimensions": ["stakeholder", "pain_point", "evidence"],
        "description": "有系统化的痛点发现方法",
        "pattern_type": "ideal",
        "linked_rules": ["H1", "H5"],
    },
    {
        "id": "T75_scenario_decomposition",
        "name": "场景拆解链",
        "dimensions": ["stakeholder", "pain_point", "solution", "market"],
        "description": "使用场景被系统拆解分析",
        "pattern_type": "ideal",
        "linked_rules": ["H1"],
    },
    {
        "id": "T76_need_priority_matrix",
        "name": "需求优先级矩阵",
        "dimensions": ["pain_point", "market", "evidence", "stakeholder"],
        "description": "多个需求按优先级排列有据",
        "pattern_type": "risk",
        "linked_rules": ["H1", "H5"],
    },
    {
        "id": "T77_empathy_insight",
        "name": "共情洞察闭环",
        "dimensions": ["stakeholder", "pain_point", "evidence", "solution"],
        "description": "通过共情获得深层用户洞察",
        "pattern_type": "ideal",
        "linked_rules": ["H1", "H5"],
    },
    {
        "id": "T78_problem_reframe",
        "name": "问题重构链",
        "dimensions": ["pain_point", "innovation", "stakeholder", "evidence"],
        "description": "重新定义问题带来创新视角",
        "pattern_type": "risk",
        "linked_rules": ["H1", "H7"],
    },
    {
        "id": "T79_ideation_evaluation",
        "name": "创意评估矩阵",
        "dimensions": ["innovation", "solution", "stakeholder", "evidence"],
        "description": "创意方案有评估框架",
        "pattern_type": "ideal",
        "linked_rules": ["H7"],
    },
    {
        "id": "T80_concept_feasibility",
        "name": "概念可行性筛选",
        "dimensions": ["solution", "technology", "resource", "risk"],
        "description": "概念阶段做可行性筛选",
        "pattern_type": "risk",
        "linked_rules": ["H7", "H12"],
    },
    {
        "id": "T81_design_thinking_loop",
        "name": "设计思维迭代",
        "dimensions": ["stakeholder", "pain_point", "solution", "evidence"],
        "description": "遵循设计思维的迭代流程",
        "pattern_type": "ideal",
        "linked_rules": ["H1", "H5"],
    },
    {
        "id": "T82_solution_architecture",
        "name": "方案架构匹配",
        "dimensions": ["solution", "technology", "stakeholder", "business_model"],
        "description": "方案架构与商业目标匹配",
        "pattern_type": "ideal",
        "linked_rules": ["H7", "H3"],
    },
    {
        "id": "T83_creative_pivot",
        "name": "创意方向调整",
        "dimensions": ["innovation", "evidence", "stakeholder", "market"],
        "description": "基于反馈调整创意方向",
        "pattern_type": "risk",
        "linked_rules": ["H1", "H5"],
    },
    {
        "id": "T84_academic_to_market",
        "name": "学术成果市场化",
        "dimensions": ["technology", "innovation", "market", "evidence"],
        "description": "学术成果有市场化路径",
        "pattern_type": "ideal",
        "linked_rules": ["H4", "H7"],
    },
    {
        "id": "T85_industry_academia_collab",
        "name": "产学研协同",
        "dimensions": ["team", "technology", "resource", "innovation"],
        "description": "产学研合作机制完善",
        "pattern_type": "ideal",
        "linked_rules": ["H10", "H12"],
    },
    {
        "id": "T86_ip_commercialization",
        "name": "知识产权商业化",
        "dimensions": ["innovation", "technology", "business_model", "competitor"],
        "description": "知识产权有商业化策略",
        "pattern_type": "ideal",
        "linked_rules": ["H7", "H6"],
    },
    {
        "id": "T87_research_application_bridge",
        "name": "研究应用桥接",
        "dimensions": ["technology", "evidence", "solution", "stakeholder"],
        "description": "研究成果桥接到实际应用",
        "pattern_type": "ideal",
        "linked_rules": ["H5", "H7"],
    },
    {
        "id": "T88_tech_readiness_assessment",
        "name": "技术成熟度评估",
        "dimensions": ["technology", "evidence", "execution_step", "risk"],
        "description": "技术成熟度有评估框架",
        "pattern_type": "risk",
        "linked_rules": ["H7", "H11"],
    },
    {
        "id": "T89_data_driven_decision",
        "name": "数据驱动决策",
        "dimensions": ["technology", "evidence", "business_model", "solution"],
        "description": "决策基于数据而非直觉",
        "pattern_type": "ideal",
        "linked_rules": ["H5", "H8"],
    },
    {
        "id": "T90_prototype_user_validation",
        "name": "原型用户验证",
        "dimensions": ["solution", "stakeholder", "evidence", "execution_step"],
        "description": "原型经过真实用户验证",
        "pattern_type": "ideal",
        "linked_rules": ["H5", "H10"],
    },
    {
        "id": "T91_tech_debt_risk",
        "name": "技术债务风险",
        "dimensions": ["technology", "risk", "execution_step", "resource"],
        "description": "技术债务对执行的风险评估",
        "pattern_type": "risk",
        "linked_rules": ["H11", "H14"],
    },
    {
        "id": "T92_ux_pain_solution",
        "name": "用户体验痛点链",
        "dimensions": ["stakeholder", "pain_point", "solution", "evidence"],
        "description": "从用户体验角度发现并解决痛点",
        "pattern_type": "ideal",
        "linked_rules": ["H1", "H5"],
    },
    {
        "id": "T93_design_iteration",
        "name": "设计迭代闭环",
        "dimensions": ["solution", "stakeholder", "evidence", "execution_step"],
        "description": "设计经过多轮迭代验证",
        "pattern_type": "ideal",
        "linked_rules": ["H5", "H10"],
    },
    {
        "id": "T94_accessibility_inclusion",
        "name": "可达性与包容性",
        "dimensions": ["stakeholder", "solution", "risk", "evidence"],
        "description": "产品考虑可达性和包容性",
        "pattern_type": "risk",
        "linked_rules": ["H1", "H11"],
    },
    {
        "id": "T95_user_education_adoption",
        "name": "用户教育与采纳",
        "dimensions": ["stakeholder", "channel", "solution", "evidence"],
        "description": "有用户教育策略促进采纳",
        "pattern_type": "ideal",
        "linked_rules": ["H2", "H5"],
    },
]


def _load_teacher_overrides() -> dict:
    """Load optional teacher override configuration for hypergraph layer."""
    try:
        cfg_dir = settings.workspace_root / "config"
        overrides_path = cfg_dir / "teacher_overrides.json"
        if not overrides_path.exists():
            return {}
        data = json.loads(overrides_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _apply_template_overrides(templates: list[dict[str, Any]], overrides: list[dict] | None) -> list[dict[str, Any]]:
    if not overrides:
        return templates
    by_id: dict[str, dict[str, Any]] = {str(t.get("id")): t for t in templates if t.get("id")}
    for ov in overrides:
        tid = str(ov.get("id") or "").strip()
        if not tid:
            continue
        base = by_id.get(tid, {"id": tid})
        patch = {k: v for k, v in ov.items() if k != "id"}
        base.update(patch)
        by_id[tid] = base
    return list(by_id.values())


# Hypergraph-level consistency rules (>=20) operating on dimension
# coverage and simple text signals. Each rule returns a warning and
# optional pressure-test questions.
_CONSISTENCY_RULES: list[dict[str, Any]] = [
    {
        "id": "G1_no_competitor",
        "description": "未识别竞品或替代品时触发",
        "predicate": lambda dims, ents: not dims.get("competitor"),
        "message": "未给出任何直接或间接竞品，建议补充替代方案分析。",
        "pressure": [
            "请列出至少3个用户当前可能在用的替代方案（包括线下/手工方案）？",
            "如果明天某个互联网巨头免费提供类似服务，你的差异化在哪里？",
        ],
    },
    {
        "id": "G2_user_without_evidence",
        "description": "有目标用户与痛点，但缺少证据维度",
        "predicate": lambda dims, ents: dims.get("stakeholder") and dims.get("pain_point") and not dims.get("evidence"),
        "message": "已描述用户与痛点，但缺少任何访谈或问卷等证据。",
        "pressure": [
            "你是否进行过至少8次深度访谈？请给出1-2条用户原话。",
            "如果评委质疑这是你想象出来的痛点，你会拿出哪份材料？",
        ],
    },
    {
        "id": "G3_solution_without_pain",
        "description": "有方案与技术但没有清晰痛点",
        "predicate": lambda dims, ents: dims.get("solution") and not dims.get("pain_point"),
        "message": "描述了方案但缺少明确的用户痛点，可能是解无问题。",
        "pressure": [
            "请用一句话说清楚：哪一类用户，在什么具体场景下，被什么事情折磨？",
        ],
    },
    {
        "id": "G4_cac_without_channel",
        "description": "提到 CAC/投放预算但缺少渠道与转化逻辑",
        "predicate": lambda dims, ents: any("cac" in e.lower() for e in ents.get("text", [])) and not dims.get("channel"),
        "message": "涉及 CAC/投放，却未说明具体渠道与转化率假设。",
        "pressure": [
            "你的获客渠道具体是什么？请给出每个渠道的转化率假设。",
            "如果渠道成本上涨50%，你的 CAC 是否仍然可接受？",
        ],
    },
    {
        "id": "G5_growth_jump",
        "description": "出现1%市场/指数增长等跳跃式假设",
        "predicate": lambda dims, ents: any("1%" in e or "百分之一" in e for e in ents.get("text", [])),
        "message": "包含自上而下的1%市场假设，缺少自下而上的增长路径。",
        "pressure": [
            "请从一个具体渠道开始，自下而上估算第一年你能获得多少付费用户？",
        ],
    },
    {
        "id": "G6_no_market",
        "description": "缺少市场维度",
        "predicate": lambda dims, ents: not dims.get("market"),
        "message": "尚未说明市场规模或目标市场，无法评估商业空间。",
        "pressure": [
            "请给出目标市场的大致规模以及主要数据来源（行业报告/公开数据等）。",
        ],
    },
    {
        "id": "G7_no_business_model",
        "description": "没有商业模式描述",
        "predicate": lambda dims, ents: dims.get("solution") and not dims.get("business_model"),
        "message": "已有方案，但尚未说明谁为此付费以及如何收钱。",
        "pressure": [
            "谁在什么场景下，为你的方案实际掏钱？一次多少钱？",
        ],
    },
    {
        "id": "G8_finance_without_evidence",
        "description": "有财务/盈利表述但缺少数据来源",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])).lower() for k in ["营收", "利润", "盈利"]) and not dims.get("evidence"),
        "message": "谈到营收/盈利，但缺少任何数据来源或测算过程。",
        "pressure": [
            "你的收入与成本假设分别来自哪些数据或实验？",
        ],
    },
    {
        "id": "G9_risk_without_control",
        "description": "涉及隐私/数据/医疗等高风险场景但无控制措施",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])).lower() for k in ["隐私", "数据", "医疗", "未成年人"]) and not dims.get("risk"),
        "message": "涉及高敏感场景但缺少合规与风险控制说明。",
        "pressure": [
            "请画出一张数据流图，并标出每一步采用的合规措施？",
        ],
    },
    {
        "id": "G10_team_mismatch",
        "description": "技术/行业复杂而团队维度缺失",
        "predicate": lambda dims, ents: dims.get("technology") and not dims.get("team"),
        "message": "技术路线较重，但未说明团队能力与分工。",
        "pressure": [
            "谁来负责核心技术实现？他/她过往有哪些相关经验？",
        ],
    },
    # 额外规则占位，保证数量充足且覆盖逻辑幻觉场景
    {
        "id": "G11_no_channel_detail",
        "description": "只有模糊的线上推广/自媒体说法",
        "predicate": lambda dims, ents: dims.get("stakeholder") and not dims.get("channel"),
        "message": "获客方式仅停留在模糊的线上推广，缺少可执行渠道。",
        "pressure": [
            "请列出3个最有可能触达目标用户的具体渠道，并估算每个渠道的 CAC。",
        ],
    },
    {
        "id": "G12_solution_overengineered",
        "description": "技术堆叠过多而痛点不明确",
        "predicate": lambda dims, ents: dims.get("technology") and not dims.get("pain_point"),
        "message": "技术方案复杂，但看不出是为了解决哪个具体痛点。",
        "pressure": [
            "请删除80%的技术描述，只保留与核心痛点直接相关的部分。",
        ],
    },
    {
        "id": "G13_no_evidence_for_competition",
        "description": "声称有护城河但无竞品/替代品对比",
        "predicate": lambda dims, ents: dims.get("business_model") and not dims.get("competitor"),
        "message": "谈到优势/护城河，但缺少与竞品或替代方案的对比。",
        "pressure": [
            "请完成一张至少包含3个竞品/替代品的对比表，并标出你的2-3个关键差异。",
        ],
    },
    {
        "id": "G14_no_growth_logic",
        "description": "没有给出从0到1的增长路径",
        "predicate": lambda dims, ents: dims.get("business_model") and not dims.get("market"),
        "message": "尚未说明从冷启动到规模化的增长路径。",
        "pressure": [
            "用3-5步描述你从第一个付费用户到前100个用户的获取路径。",
        ],
    },
    {
        "id": "G15_resource_gap",
        "description": "依赖关键资源但未说明获取方式",
        "predicate": lambda dims, ents: dims.get("resource") and not dims.get("evidence"),
        "message": "提到重要资源，但没有说明如何获取与成本。",
        "pressure": [
            "这些关键资源目前掌握在谁手里？你如何以可接受的成本获得？",
        ],
    },
    {
        "id": "G16_team_no_roadmap",
        "description": "团队存在但缺少里程碑规划",
        "predicate": lambda dims, ents: dims.get("team") and not dims.get("resource"),
        "message": "团队已介绍，但缺少阶段性里程碑与分工。",
        "pressure": [
            "未来3个月内你们各自要完成哪些可验收的里程碑？",
        ],
    },
    {
        "id": "G17_evidence_scattered",
        "description": "有零散数据但未形成证据链",
        "predicate": lambda dims, ents: dims.get("evidence") and not (dims.get("stakeholder") and dims.get("pain_point")),
        "message": "存在零散数据，但未围绕核心用户与痛点形成闭环证据链。",
        "pressure": [
            "请将现有证据按“用户-痛点-方案效果”三个维度重新整理。",
        ],
    },
    {
        "id": "G18_overclaim_no_metric",
        "description": "存在“颠覆/革命性”等强表述但无指标",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])).lower() for k in ["颠覆", "革命", "改变行业"]) and not dims.get("evidence"),
        "message": "存在强烈主观判断，但缺少任何可量化指标。",
        "pressure": [
            "请给出3个可以量化的指标，用来证明你所谓的“颠覆性”。",
        ],
    },
    {
        "id": "G19_no_metric_focus",
        "description": "没有明确单一北极星指标",
        "predicate": lambda dims, ents: not any(k in " ".join(ents.get("text", [])).lower() for k in ["留存", "转化", "复购", "活跃"]),
        "message": "缺少聚焦的核心业务指标，难以评估项目进展。",
        "pressure": [
            "如果只能选一个指标衡量项目成败，你会选什么？为什么？",
        ],
    },
    {
        "id": "G20_no_risk_section",
        "description": "商业计划中完全没有风险章节",
        "predicate": lambda dims, ents: not dims.get("risk"),
        "message": "商业计划中缺少风险与对策章节，评委难以信任预期。",
        "pressure": [
            "请列出3个最可能让项目失败的风险，并给出各自的一条缓解措施。",
        ],
    },
    {
        "id": "G21_revenue_not_sustainable",
        "description": "有商业模式但无持续收入逻辑",
        "predicate": lambda dims, ents: dims.get("business_model") and not any(k in " ".join(ents.get("text", [])) for k in ["复购", "续费", "订阅", "持续", "年费", "月费", "续约"]),
        "message": "商业模式中未提及用户如何持续付费，收入可能是一次性的。",
        "pressure": [
            "用户第一次付费之后，什么机制能让他们持续付费或再次购买？",
            "如果用户只用一次就走了，你的LTV能覆盖CAC吗？",
        ],
    },
    {
        "id": "G22_demand_supply_mismatch",
        "description": "痛点与方案之间存在错位迹象",
        "predicate": lambda dims, ents: dims.get("pain_point") and dims.get("solution") and not dims.get("evidence"),
        "message": "有痛点有方案但缺少验证两者匹配的证据，可能存在需求-供给错位。",
        "pressure": [
            "你的用户真的需要你提供的这种解决方式吗？有没有直接问过他们？",
            "如果用户的核心诉求是省钱，但你的方案是省时间，这算匹配吗？",
        ],
    },
    {
        "id": "G23_founder_dependency",
        "description": "执行步骤中只出现单一角色",
        "predicate": lambda dims, ents: dims.get("team") and not any(k in " ".join(ents.get("text", [])) for k in ["分工", "负责人", "谁来", "各自", "团队成员"]),
        "message": "执行计划中缺少明确的分工，可能存在创始人单点依赖风险。",
        "pressure": [
            "如果你（创始人）明天生病住院一周，项目还能按计划推进吗？",
            "请画出团队分工图，标出每个里程碑的负责人。",
        ],
    },
    {
        "id": "G24_ai_ethics_missing",
        "description": "使用AI/算法但未讨论伦理公平性",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])).lower() for k in ["ai", "算法", "推荐", "机器学习", "深度学习"]) and not any(k in " ".join(ents.get("text", [])) for k in ["公平", "偏见", "伦理", "歧视", "透明"]),
        "message": "项目使用AI/算法决策但未讨论公平性与伦理风险。",
        "pressure": [
            "你的算法对不同用户群体（性别、年龄、地域）是否同等公平？",
            "如果算法出错导致用户利益受损，责任归谁？有什么纠错机制？",
        ],
    },
    {
        "id": "G25_assumption_unverified",
        "description": "有方案和商业模式但缺少验证证据",
        "predicate": lambda dims, ents: dims.get("solution") and dims.get("business_model") and not dims.get("evidence"),
        "message": "方案和商业模式都有了但建立在未验证的假设之上，评委会追问依据。",
        "pressure": [
            "从'用户有这个痛点'到'他们愿意为你的方案付钱'，中间有几个假设？每个验证了吗？",
            "请列出你项目的前三个核心假设，并说明各自的验证状态。",
        ],
    },
    {
        "id": "G26_no_success_metric",
        "description": "声称效果好但缺少具体量化指标",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])) for k in ["效果好", "提升了", "改善了", "显著", "大幅"]) and not any(k in " ".join(ents.get("text", [])) for k in ["%", "倍", "分钟", "小时", "元", "人次", "万"]),
        "message": "存在定性描述但缺少量化指标，评委无法判断效果。",
        "pressure": [
            "你说'效果好'，请给出一个具体数字：好多少？跟谁比？怎么测量的？",
        ],
    },
    {
        "id": "G27_market_too_broad",
        "description": "目标市场描述过于笼统",
        "predicate": lambda dims, ents: dims.get("market") and dims.get("stakeholder") and any(k in " ".join(ents.get("text", [])) for k in ["所有", "全国", "千万", "亿", "大学生", "所有人", "白领"]) and not any(k in " ".join(ents.get("text", [])) for k in ["细分", "聚焦", "首批", "种子用户", "第一批"]),
        "message": "目标市场描述过于笼统，缺少细分聚焦策略。",
        "pressure": [
            "如果只能服务100个人，你会选哪100个？为什么是他们？",
            "请把'面向大学生'具体到：什么大学、什么专业、什么年级、什么场景。",
        ],
    },
    {
        "id": "G28_no_competitive_defense",
        "description": "有创新点但未考虑竞品模仿风险",
        "predicate": lambda dims, ents: dims.get("innovation") and not dims.get("competitor"),
        "message": "有创新主张但未分析竞品可能的模仿或反制策略。",
        "pressure": [
            "如果字节跳动/腾讯明天决定做同样的事，你的应对方案是什么？",
            "你的创新点能撑多久不被抄？6个月？1年？依据是什么？",
        ],
    },
    {
        "id": "G29_milestone_no_dependency",
        "description": "有执行步骤但未说明依赖关系",
        "predicate": lambda dims, ents: dims.get("execution_step") and not any(k in " ".join(ents.get("text", [])) for k in ["依赖", "前置", "之后才", "完成后", "基于上一步"]),
        "message": "列出了里程碑但未说明相互依赖关系和容错路径。",
        "pressure": [
            "你的第二步是否依赖第一步的结果？如果第一步失败了怎么办？",
        ],
    },
    {
        "id": "G30_funding_without_evidence",
        "description": "提到融资但缺少业务验证",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])) for k in ["融资", "天使轮", "A轮", "投资", "风投"]) and not dims.get("evidence"),
        "message": "谈到融资计划但缺少产品市场匹配(PMF)的验证证据。",
        "pressure": [
            "在种子期就谈融资，投资人第一个问题会是：你有多少付费用户？",
            "你的产品有PMF的证据吗？如果没有，融资计划就是空中楼阁。",
        ],
    },
    {
        "id": "G31_no_switching_cost_analysis",
        "description": "有方案但未分析用户切换成本",
        "predicate": lambda dims, ents: dims.get("solution") and dims.get("stakeholder") and not any(k in " ".join(ents.get("text", [])) for k in ["替代", "迁移", "切换", "改用", "取代", "习惯"]),
        "message": "提出了新方案但未分析用户从现有方案切换过来的成本。",
        "pressure": [
            "用户现在用什么解决这个问题？虽然不完美但免费/习惯了。你凭什么让他们换？",
        ],
    },
    {
        "id": "G32_network_effect_unproven",
        "description": "声称网络效应但缺少增长数据",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])) for k in ["网络效应", "飞轮", "越多越好", "规模效应"]) and not dims.get("evidence"),
        "message": "声称存在网络效应但缺少实际增长数据支撑。",
        "pressure": [
            "真正的网络效应是'用户越多产品越好用'。你的产品是这样吗？还是只是'数据越多'？",
        ],
    },
    {
        "id": "G33_cross_dim_incoherence",
        "description": "多维度齐全但叙事不一致",
        "predicate": lambda dims, ents: sum(1 for v in dims.values() if v) >= 4 and dims.get("business_model") and dims.get("stakeholder") and not dims.get("evidence"),
        "message": "项目维度较全但缺少贯穿各维度的证据链，叙事一致性可能不足。",
        "pressure": [
            "你的目标用户、解决方案、商业模式和市场定位讲的是同一个故事吗？",
            "请用一句话串起你的'用户→痛点→方案→收费→增长'逻辑链。",
        ],
    },
    {
        "id": "G34_esg_not_measurable",
        "description": "涉及社会影响但未量化",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])) for k in ["公益", "社会", "ESG", "乡村", "扶贫", "助农", "环保"]) and not any(k in " ".join(ents.get("text", [])) for k in ["%", "人次", "万", "覆盖", "减少", "降低"]),
        "message": "涉及社会影响但缺少可量化指标，评委无法评估实际效果。",
        "pressure": [
            "你说'帮助了很多人'——具体帮助了多少人？改善了多少？用什么指标衡量？",
            "请给出一个社会影响的量化目标，比如'第一年覆盖XX个村/XX户'。",
        ],
    },
    {
        "id": "G35_no_pain_validation",
        "description": "有痛点描述但缺少验证方法",
        "predicate": lambda dims, ents: dims.get("pain_point") and not dims.get("evidence"),
        "message": "提到了痛点但缺少验证方法或证据，痛点可能是主观臆断。",
        "pressure": [
            "你是通过什么方法发现这个痛点的？做过用户访谈或问卷吗？",
            "有多少目标用户真正反馈过这个痛点？",
        ],
    },
    {
        "id": "G36_scenario_without_user",
        "description": "有场景描述但缺少目标用户画像",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])) for k in ["场景", "情境", "应用场景"]) and not dims.get("stakeholder"),
        "message": "描述了应用场景但缺少明确的目标用户画像。",
        "pressure": [
            "这个场景里的用户具体是谁？年龄、职业、行为习惯是什么？",
        ],
    },
    {
        "id": "G37_need_no_priority",
        "description": "列举多个需求但未排列优先级",
        "predicate": lambda dims, ents: dims.get("pain_point") and len([e for e in (ents.get("text", []) if isinstance(ents.get("text"), list) else []) if any(k in e for k in ["需求", "痛点", "问题"])]) >= 3 and not any(k in " ".join(ents.get("text", [])) for k in ["优先", "最重要", "核心", "首要"]),
        "message": "列举了多个需求但未区分优先级，资源可能分散。",
        "pressure": [
            "这些需求中哪个是用户最痛的？如果只解决一个，选哪个？",
        ],
    },
    {
        "id": "G38_idea_no_evaluation",
        "description": "有创意但缺少可行性评估",
        "predicate": lambda dims, ents: dims.get("innovation") and not dims.get("evidence") and not dims.get("risk"),
        "message": "提出了创新点但缺少可行性评估和风险分析。",
        "pressure": [
            "这个创新点的技术可行性如何验证？有没有做过小规模测试？",
        ],
    },
    {
        "id": "G39_solution_no_alternative",
        "description": "只有一个方案没有对比选择",
        "predicate": lambda dims, ents: dims.get("solution") and not dims.get("competitor") and not any(k in " ".join(ents.get("text", [])) for k in ["对比", "方案二", "备选", "替代方案", "比较"]),
        "message": "只提供了一个解决方案，缺少方案对比和替代选择。",
        "pressure": [
            "你考虑过其他解决方案吗？为什么选择了当前方案而不是其他的？",
        ],
    },
    {
        "id": "G40_design_without_iteration",
        "description": "提到设计但无迭代验证",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])) for k in ["设计", "原型", "UI", "UX", "界面"]) and not any(k in " ".join(ents.get("text", [])) for k in ["迭代", "测试", "反馈", "改进", "优化"]),
        "message": "提到了产品设计但缺少迭代验证过程。",
        "pressure": [
            "你的设计经过用户测试了吗？收到了什么反馈？做了哪些改进？",
        ],
    },
    {
        "id": "G41_academic_no_market",
        "description": "有技术成果但未讨论市场化路径",
        "predicate": lambda dims, ents: dims.get("technology") and dims.get("innovation") and not dims.get("market") and not dims.get("business_model"),
        "message": "有技术创新但缺少市场化路径和商业模式讨论。",
        "pressure": [
            "这项技术成果打算怎么走向市场？目标客户是谁？怎么收费？",
        ],
    },
    {
        "id": "G42_ip_no_protection",
        "description": "有核心技术但未讨论知识产权保护",
        "predicate": lambda dims, ents: dims.get("technology") and dims.get("innovation") and not any(k in " ".join(ents.get("text", [])) for k in ["专利", "知识产权", "版权", "商标", "授权", "许可"]),
        "message": "有核心技术创新但未讨论知识产权保护策略。",
        "pressure": [
            "你的核心技术有没有申请专利？如何防止被模仿？",
        ],
    },
    {
        "id": "G43_no_data_validation",
        "description": "使用数据/AI但缺少数据质量验证",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])) for k in ["数据", "AI", "算法", "模型", "机器学习", "深度学习"]) and not any(k in " ".join(ents.get("text", [])) for k in ["数据质量", "标注", "清洗", "验证集", "准确率", "精度"]),
        "message": "使用数据/AI技术但缺少数据质量验证说明。",
        "pressure": [
            "你的训练数据从哪里来？数据质量如何保证？有没有做过准确率验证？",
        ],
    },
    {
        "id": "G44_tech_stack_no_evidence",
        "description": "技术堆叠缺少可行性证据",
        "predicate": lambda dims, ents: dims.get("technology") and len([e for e in (ents.get("text", []) if isinstance(ents.get("text"), list) else []) if any(k in e for k in ["技术", "框架", "平台", "系统"])]) >= 2 and not dims.get("evidence"),
        "message": "技术方案较复杂但缺少可行性验证证据。",
        "pressure": [
            "你列举的技术栈是否都经过验证？有没有做过技术原型？",
        ],
    },
    {
        "id": "G45_no_ux_research",
        "description": "有产品方案但缺少用户研究",
        "predicate": lambda dims, ents: dims.get("solution") and dims.get("stakeholder") and not any(k in " ".join(ents.get("text", [])) for k in ["用户研究", "用户访谈", "可用性", "用户测试", "A/B", "体验"]),
        "message": "有产品方案但缺少用户研究和体验验证。",
        "pressure": [
            "你做过用户研究吗？目标用户对方案的反馈如何？",
        ],
    },
    {
        "id": "G46_no_user_feedback",
        "description": "有产品但无用户反馈机制",
        "predicate": lambda dims, ents: dims.get("solution") and not any(k in " ".join(ents.get("text", [])) for k in ["反馈", "评价", "NPS", "满意度", "用户声音", "回访"]),
        "message": "有产品方案但未建立用户反馈收集机制。",
        "pressure": [
            "你怎么收集用户反馈？有没有建立定期回访机制？",
        ],
    },
    {
        "id": "G47_privacy_no_compliance",
        "description": "涉及用户数据但无隐私合规说明",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])) for k in ["用户数据", "个人信息", "隐私", "注册", "实名"]) and not any(k in " ".join(ents.get("text", [])) for k in ["合规", "GDPR", "个保法", "隐私政策", "数据保护", "脱敏"]),
        "message": "涉及用户数据收集但未说明隐私合规措施。",
        "pressure": [
            "你收集了哪些用户数据？如何确保符合个人信息保护法？",
        ],
    },
    {
        "id": "G48_partnership_unvalidated",
        "description": "依赖合作方但未验证合作可行性",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])) for k in ["合作", "伙伴", "联合", "战略合作", "渠道商"]) and not any(k in " ".join(ents.get("text", [])) for k in ["签约", "意向书", "已对接", "协议", "确认"]),
        "message": "依赖外部合作方但未验证合作的实际可行性。",
        "pressure": [
            "你提到的合作方是否已经确认合作意向？有没有签署意向书或协议？",
        ],
    },
    {
        "id": "G49_esg_claim_no_metric",
        "description": "声称社会价值但无量化指标",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])) for k in ["社会价值", "社会责任", "公益", "可持续"]) and not any(k in " ".join(ents.get("text", [])) for k in ["%", "指标", "KPI", "衡量", "量化", "人次", "覆盖率"]),
        "message": "声称有社会价值但缺少量化衡量指标。",
        "pressure": [
            "你用什么指标衡量社会价值？能给出具体的数字目标吗？",
        ],
    },
    {
        "id": "G50_supply_chain_single_point",
        "description": "供应链存在单点依赖风险",
        "predicate": lambda dims, ents: any(k in " ".join(ents.get("text", [])) for k in ["供应商", "供应链", "采购", "原材料"]) and not any(k in " ".join(ents.get("text", [])) for k in ["备选", "多元", "替代", "多家", "分散"]),
        "message": "供应链可能存在单点依赖风险，缺少备选方案。",
        "pressure": [
            "你的核心供应商只有一家吗？如果断供怎么办？有备选供应商吗？",
        ],
    },
]


_OVERRIDES = _load_teacher_overrides()
_HYPEREDGE_TEMPLATES = _apply_template_overrides(_HYPEREDGE_TEMPLATES, _OVERRIDES.get("hyperedge_templates"))
EDGE_FAMILY_GROUPS: dict[str, list[str]] = {
    "价值叙事与一致性": [
        "Value_Loop_Edge", "User_Journey_Edge", "Presentation_Narrative_Edge",
        "Cross_Dimension_Coherence_Edge", "Stage_Goal_Fit_Edge",
    ],
    "用户-市场-需求": [
        "User_Pain_Fit_Edge", "Market_Segmentation_Edge",
        "Demand_Supply_Match_Edge", "Market_Competition_Edge",
    ],
    "风险、证据与评分": [
        "Risk_Pattern_Edge", "Evidence_Grounding_Edge",
        "Rule_Rubric_Tension_Edge", "Assumption_Stack_Edge", "Metric_Definition_Edge",
    ],
    "执行、团队与里程碑": [
        "Execution_Gap_Edge", "Team_Capability_Gap_Edge",
        "Milestone_Dependency_Edge", "MVP_Scope_Edge", "Founder_Risk_Edge",
    ],
    "合规、监管与伦理": [
        "Compliance_Safety_Edge", "Regulatory_Landscape_Edge", "Ethical_Bias_Edge",
        "Data_Privacy_Edge", "Industry_Compliance_Edge",
    ],
    "单位经济与财务结构": [
        "Pricing_Unit_Economics_Edge", "Cost_Structure_Edge",
        "Revenue_Sustainability_Edge", "Resource_Leverage_Edge", "Funding_Stage_Fit_Edge",
    ],
    "产品差异化与竞争动态": [
        "Innovation_Validation_Edge", "Substitute_Migration_Edge",
        "Competitive_Response_Edge", "IP_Moat_Edge", "Switching_Cost_Edge",
        "Network_Effect_Edge", "Pivot_Signal_Edge",
    ],
    "增长、渠道与规模化": [
        "Trust_Adoption_Edge", "Retention_Workflow_Embed_Edge",
        "Channel_Conversion_Edge", "Scalability_Bottleneck_Edge",
        "Data_Flywheel_Edge", "Timing_Window_Edge",
    ],
    "生态与多方利益": [
        "Ecosystem_Dependency_Edge", "Stakeholder_Conflict_Edge", "Ontology_Grounded_Edge",
        "Partnership_Network_Edge", "Supply_Chain_Edge",
    ],
    "社会与ESG": [
        "Social_Impact_Edge", "ESG_Measurability_Edge",
        "Community_Building_Edge", "Environmental_Impact_Edge", "Governance_Transparency_Edge",
    ],
    "问题发现与需求洞察": [
        "Problem_Discovery_Edge", "Scenario_Analysis_Edge", "Need_Prioritization_Edge",
        "Empathy_Map_Edge", "Insight_Validation_Edge",
    ],
    "创意孵化与方案设计": [
        "Ideation_Edge", "Concept_Evaluation_Edge", "Feasibility_Screen_Edge",
        "Design_Thinking_Edge", "Solution_Architecture_Edge",
    ],
    "知识转化与产学研": [
        "Academic_Transfer_Edge", "Industry_Academia_Edge", "IP_Commercialization_Edge",
        "Tech_Licensing_Edge", "Research_Application_Edge",
    ],
    "数据与技术验证": [
        "Tech_Readiness_Edge", "Data_Quality_Edge", "Tech_Debt_Edge",
        "API_Integration_Edge", "Prototype_Validation_Edge",
    ],
    "用户体验与设计思维": [
        "UX_Research_Edge", "Design_Driven_Edge", "Accessibility_Edge",
        "User_Education_Edge", "Feedback_Loop_Edge",
    ],
}

_FAMILY_TO_GROUP: dict[str, str] = {
    fam: grp for grp, fams in EDGE_FAMILY_GROUPS.items() for fam in fams
}

EDGE_FAMILY_LABELS: dict[str, str] = {
    "Value_Loop_Edge": "价值闭环超边",
    "User_Pain_Fit_Edge": "用户痛点匹配超边",
    "Risk_Pattern_Edge": "风险模式超边",
    "Evidence_Grounding_Edge": "证据锚定超边",
    "Market_Competition_Edge": "市场竞争超边",
    "Execution_Gap_Edge": "执行断裂超边",
    "Compliance_Safety_Edge": "合规安全超边",
    "Ontology_Grounded_Edge": "本体落地超边",
    "Innovation_Validation_Edge": "创新验证超边",
    "Pricing_Unit_Economics_Edge": "定价单元经济超边",
    "Substitute_Migration_Edge": "替代迁移超边",
    "Trust_Adoption_Edge": "信任采纳超边",
    "Retention_Workflow_Embed_Edge": "工作流嵌入超边",
    "Stage_Goal_Fit_Edge": "阶段目标匹配超边",
    "Rule_Rubric_Tension_Edge": "规则评分张力超边",
    "Team_Capability_Gap_Edge": "团队能力缺口超边",
    "User_Journey_Edge": "用户旅程闭环超边",
    "Social_Impact_Edge": "社会价值链超边",
    "Data_Flywheel_Edge": "数据飞轮超边",
    "Scalability_Bottleneck_Edge": "规模化瓶颈超边",
    "IP_Moat_Edge": "知识产权护城河超边",
    "Pivot_Signal_Edge": "转型信号超边",
    "Cost_Structure_Edge": "成本结构超边",
    "Ecosystem_Dependency_Edge": "生态依赖超边",
    "MVP_Scope_Edge": "MVP边界超边",
    "Stakeholder_Conflict_Edge": "利益方冲突超边",
    "Channel_Conversion_Edge": "渠道转化漏斗超边",
    "Regulatory_Landscape_Edge": "政策法规环境超边",
    "Presentation_Narrative_Edge": "路演叙事线超边",
    "Resource_Leverage_Edge": "资源杠杆超边",
    "Timing_Window_Edge": "时机窗口超边",
    "Revenue_Sustainability_Edge": "收入可持续性超边",
    "Demand_Supply_Match_Edge": "供需匹配超边",
    "Founder_Risk_Edge": "创始人风险超边",
    "Ethical_Bias_Edge": "伦理偏见超边",
    "Assumption_Stack_Edge": "假设堆叠超边",
    "Metric_Definition_Edge": "指标定义超边",
    "Market_Segmentation_Edge": "市场细分超边",
    "Competitive_Response_Edge": "竞品反应超边",
    "Milestone_Dependency_Edge": "里程碑依赖超边",
    "Funding_Stage_Fit_Edge": "融资阶段匹配超边",
    "Switching_Cost_Edge": "用户切换成本超边",
    "Network_Effect_Edge": "网络效应超边",
    "Cross_Dimension_Coherence_Edge": "跨维度一致性超边",
    "ESG_Measurability_Edge": "ESG可量化超边",
    "Data_Privacy_Edge": "数据隐私超边",
    "Industry_Compliance_Edge": "行业合规超边",
    "Partnership_Network_Edge": "合作网络超边",
    "Supply_Chain_Edge": "供应链超边",
    "Community_Building_Edge": "社区构建超边",
    "Environmental_Impact_Edge": "环境影响超边",
    "Governance_Transparency_Edge": "治理透明超边",
    "Problem_Discovery_Edge": "问题发现超边",
    "Scenario_Analysis_Edge": "场景分析超边",
    "Need_Prioritization_Edge": "需求优先级超边",
    "Empathy_Map_Edge": "共情图谱超边",
    "Insight_Validation_Edge": "洞察验证超边",
    "Ideation_Edge": "创意生成超边",
    "Concept_Evaluation_Edge": "概念评估超边",
    "Feasibility_Screen_Edge": "可行性筛选超边",
    "Design_Thinking_Edge": "设计思维超边",
    "Solution_Architecture_Edge": "方案架构超边",
    "Academic_Transfer_Edge": "学术转化超边",
    "Industry_Academia_Edge": "产学研合作超边",
    "IP_Commercialization_Edge": "知识产权商业化超边",
    "Tech_Licensing_Edge": "技术许可超边",
    "Research_Application_Edge": "研究应用超边",
    "Tech_Readiness_Edge": "技术成熟度超边",
    "Data_Quality_Edge": "数据质量超边",
    "Tech_Debt_Edge": "技术债务超边",
    "API_Integration_Edge": "接口集成超边",
    "Prototype_Validation_Edge": "原型验证超边",
    "UX_Research_Edge": "用户研究超边",
    "Design_Driven_Edge": "设计驱动超边",
    "Accessibility_Edge": "可达性超边",
    "User_Education_Edge": "用户教育超边",
    "Feedback_Loop_Edge": "反馈闭环超边",
}

EDGE_PREFIX: dict[str, str] = {
    "Value_Loop_Edge": "he_value_",
    "User_Pain_Fit_Edge": "he_userpain_",
    "Risk_Pattern_Edge": "he_risk_",
    "Evidence_Grounding_Edge": "he_evidence_",
    "Market_Competition_Edge": "he_market_",
    "Execution_Gap_Edge": "he_exec_",
    "Compliance_Safety_Edge": "he_compliance_",
    "Ontology_Grounded_Edge": "he_ontology_",
    "Innovation_Validation_Edge": "he_innovation_",
    "Pricing_Unit_Economics_Edge": "he_price_",
    "Substitute_Migration_Edge": "he_substitute_",
    "Trust_Adoption_Edge": "he_trust_",
    "Retention_Workflow_Embed_Edge": "he_retention_",
    "Stage_Goal_Fit_Edge": "he_stage_",
    "Rule_Rubric_Tension_Edge": "he_tension_",
    "Team_Capability_Gap_Edge": "he_teamgap_",
    "User_Journey_Edge": "he_journey_",
    "Social_Impact_Edge": "he_social_",
    "Data_Flywheel_Edge": "he_flywheel_",
    "Scalability_Bottleneck_Edge": "he_scale_",
    "IP_Moat_Edge": "he_ipmoat_",
    "Pivot_Signal_Edge": "he_pivot_",
    "Cost_Structure_Edge": "he_cost_",
    "Ecosystem_Dependency_Edge": "he_ecosystem_",
    "MVP_Scope_Edge": "he_mvp_",
    "Stakeholder_Conflict_Edge": "he_conflict_",
    "Channel_Conversion_Edge": "he_channel_",
    "Regulatory_Landscape_Edge": "he_regulatory_",
    "Presentation_Narrative_Edge": "he_narrative_",
    "Resource_Leverage_Edge": "he_leverage_",
    "Timing_Window_Edge": "he_timing_",
    "Revenue_Sustainability_Edge": "he_revenue_",
    "Demand_Supply_Match_Edge": "he_demsup_",
    "Founder_Risk_Edge": "he_founder_",
    "Ethical_Bias_Edge": "he_ethics_",
    "Assumption_Stack_Edge": "he_assume_",
    "Metric_Definition_Edge": "he_metric_",
    "Market_Segmentation_Edge": "he_segment_",
    "Competitive_Response_Edge": "he_compresp_",
    "Milestone_Dependency_Edge": "he_milestone_",
    "Funding_Stage_Fit_Edge": "he_funding_",
    "Switching_Cost_Edge": "he_switch_",
    "Network_Effect_Edge": "he_neteffect_",
    "Cross_Dimension_Coherence_Edge": "he_coherence_",
    "ESG_Measurability_Edge": "he_esg_",
    "Data_Privacy_Edge": "he_privacy_",
    "Industry_Compliance_Edge": "he_indcomp_",
    "Partnership_Network_Edge": "he_partner_",
    "Supply_Chain_Edge": "he_supply_",
    "Community_Building_Edge": "he_community_",
    "Environmental_Impact_Edge": "he_envimpact_",
    "Governance_Transparency_Edge": "he_govtrans_",
    "Problem_Discovery_Edge": "he_probdisc_",
    "Scenario_Analysis_Edge": "he_scenario_",
    "Need_Prioritization_Edge": "he_needpri_",
    "Empathy_Map_Edge": "he_empathy_",
    "Insight_Validation_Edge": "he_insight_",
    "Ideation_Edge": "he_ideation_",
    "Concept_Evaluation_Edge": "he_concept_",
    "Feasibility_Screen_Edge": "he_feasible_",
    "Design_Thinking_Edge": "he_designth_",
    "Solution_Architecture_Edge": "he_solarch_",
    "Academic_Transfer_Edge": "he_acadtran_",
    "Industry_Academia_Edge": "he_indacad_",
    "IP_Commercialization_Edge": "he_ipcomm_",
    "Tech_Licensing_Edge": "he_techlic_",
    "Research_Application_Edge": "he_resapp_",
    "Tech_Readiness_Edge": "he_techready_",
    "Data_Quality_Edge": "he_dataqual_",
    "Tech_Debt_Edge": "he_techdebt_",
    "API_Integration_Edge": "he_apiint_",
    "Prototype_Validation_Edge": "he_protoval_",
    "UX_Research_Edge": "he_uxres_",
    "Design_Driven_Edge": "he_designdr_",
    "Accessibility_Edge": "he_access_",
    "User_Education_Edge": "he_usered_",
    "Feedback_Loop_Edge": "he_feedback_",
}

EDGE_TARGET_COUNTS: dict[str, int] = {
    "Risk_Pattern_Edge": 18,
    "Value_Loop_Edge": 16,
    "User_Pain_Fit_Edge": 12,
    "Evidence_Grounding_Edge": 12,
    "Execution_Gap_Edge": 10,
    "Market_Competition_Edge": 10,
    "Compliance_Safety_Edge": 8,
    "Innovation_Validation_Edge": 8,
    "Pricing_Unit_Economics_Edge": 10,
    "Substitute_Migration_Edge": 10,
    "Trust_Adoption_Edge": 8,
    "Retention_Workflow_Embed_Edge": 8,
    "Stage_Goal_Fit_Edge": 8,
    "Rule_Rubric_Tension_Edge": 10,
    "Ontology_Grounded_Edge": 6,
    "Team_Capability_Gap_Edge": 8,
    "User_Journey_Edge": 10,
    "Social_Impact_Edge": 6,
    "Data_Flywheel_Edge": 8,
    "Scalability_Bottleneck_Edge": 8,
    "IP_Moat_Edge": 6,
    "Pivot_Signal_Edge": 6,
    "Cost_Structure_Edge": 8,
    "Ecosystem_Dependency_Edge": 6,
    "MVP_Scope_Edge": 8,
    "Stakeholder_Conflict_Edge": 6,
    "Channel_Conversion_Edge": 8,
    "Regulatory_Landscape_Edge": 6,
    "Presentation_Narrative_Edge": 8,
    "Resource_Leverage_Edge": 6,
    "Timing_Window_Edge": 6,
    "Revenue_Sustainability_Edge": 8,
    "Demand_Supply_Match_Edge": 8,
    "Founder_Risk_Edge": 6,
    "Ethical_Bias_Edge": 6,
    "Assumption_Stack_Edge": 8,
    "Metric_Definition_Edge": 6,
    "Market_Segmentation_Edge": 8,
    "Competitive_Response_Edge": 6,
    "Milestone_Dependency_Edge": 6,
    "Funding_Stage_Fit_Edge": 6,
    "Switching_Cost_Edge": 6,
    "Network_Effect_Edge": 8,
    "Cross_Dimension_Coherence_Edge": 6,
    "ESG_Measurability_Edge": 6,
    "Data_Privacy_Edge": 6,
    "Industry_Compliance_Edge": 6,
    "Partnership_Network_Edge": 6,
    "Supply_Chain_Edge": 6,
    "Community_Building_Edge": 6,
    "Environmental_Impact_Edge": 6,
    "Governance_Transparency_Edge": 6,
    "Problem_Discovery_Edge": 6,
    "Scenario_Analysis_Edge": 6,
    "Need_Prioritization_Edge": 6,
    "Empathy_Map_Edge": 6,
    "Insight_Validation_Edge": 6,
    "Ideation_Edge": 6,
    "Concept_Evaluation_Edge": 6,
    "Feasibility_Screen_Edge": 6,
    "Design_Thinking_Edge": 6,
    "Solution_Architecture_Edge": 6,
    "Academic_Transfer_Edge": 6,
    "Industry_Academia_Edge": 6,
    "IP_Commercialization_Edge": 6,
    "Tech_Licensing_Edge": 6,
    "Research_Application_Edge": 6,
    "Tech_Readiness_Edge": 6,
    "Data_Quality_Edge": 6,
    "Tech_Debt_Edge": 6,
    "API_Integration_Edge": 6,
    "Prototype_Validation_Edge": 6,
    "UX_Research_Edge": 6,
    "Design_Driven_Edge": 6,
    "Accessibility_Edge": 6,
    "User_Education_Edge": 6,
    "Feedback_Loop_Edge": 6,
}


DIMENSIONS: dict[str, str] = {
    "stakeholder": "目标用户",
    "pain_point": "痛点问题",
    "solution": "解决方案",
    "innovation": "创新点",
    "market": "目标市场",
    "competitor": "竞争格局",
    "business_model": "商业模式",
    "execution_step": "执行步骤",
    "risk_control": "风控合规",
    "technology": "技术路线",
    "resource": "资源优势",
    "team": "团队能力",
    "evidence": "证据与数据",
    "risk": "风险与合规",
    "channel": "获客渠道",
}


def _compute_quality_metrics(
    dim_entities: dict[str, list],
    cross_links: list[dict],
    template_matches: list[dict],
    consistency_issues: list[dict],
    hub_entities: list[dict],
    all_entities: list[dict],
    all_rels: list[dict],
) -> dict:
    """Compute scientifically rigorous quality metrics for the hypergraph analysis."""
    import math

    total_dims = len(DIMENSIONS)
    nodes = len(all_entities)
    edges = len(all_rels)

    # 1. Depth-weighted coverage (0-10)
    dim_depths = {}
    cross_dim_set = set()
    for cl in cross_links:
        if isinstance(cl, dict):
            cross_dim_set.add(cl.get("from_dim", ""))
            cross_dim_set.add(cl.get("to_dim", ""))
    for dim_key in DIMENSIONS:
        ents = dim_entities.get(dim_key, [])
        count = len(ents) if isinstance(ents, list) else 0
        if count == 0:
            depth = 0
        elif count == 1:
            depth = 1
        elif count <= 3:
            depth = 2
        else:
            depth = 3
        if dim_key in cross_dim_set and depth > 0:
            depth = min(3, depth + 0.5)
        dim_depths[dim_key] = depth
    depth_weighted_coverage = round(sum(dim_depths.values()) / max(1, total_dims * 3) * 10, 2)

    # 2. Graph density (0-1)
    graph_density = round(2 * edges / max(1, nodes * (nodes - 1)), 4) if nodes > 1 else 0

    # 3. Average node degree
    avg_node_degree = round(2 * edges / max(1, nodes), 2)

    # 4. Cross-dimension ratio (0-1)
    cross_dim_edges = len(cross_links)
    cross_dimension_ratio = round(cross_dim_edges / max(1, edges), 4) if edges > 0 else 0

    # 5. Hub concentration (Gini coefficient, 0-1)
    degrees = sorted([h.get("connections", 0) for h in hub_entities] if hub_entities else [])
    if not degrees:
        degrees = [0]
    n_deg = len(degrees)
    if n_deg <= 1 or sum(degrees) == 0:
        hub_concentration = 0.0
    else:
        cum = sum((2 * (i + 1) - n_deg - 1) * degrees[i] for i in range(n_deg))
        hub_concentration = round(cum / (n_deg * sum(degrees)), 4)

    # 6. Template completion score (0-10), weighted by pattern_type
    weight_map = {"ideal": 3, "risk": 2, "neutral": 1}
    total_weight = 0
    completed_weight = 0
    for tm in (template_matches or []):
        w = weight_map.get(tm.get("pattern_type", "neutral"), 1)
        total_weight += w
        if tm.get("status") == "complete":
            completed_weight += w
    template_completion_score = round(completed_weight / max(1, total_weight) * 10, 2)

    # 7. Consistency health score (0-10)
    severity_map = {
        "G1": 3, "G2": 2, "G3": 3, "G4": 2, "G5": 3, "G6": 3, "G7": 3, "G8": 2,
        "G9": 3, "G10": 2, "G11": 2, "G12": 2, "G13": 2, "G14": 2, "G15": 2,
        "G16": 1, "G17": 2, "G18": 3, "G19": 2, "G20": 3, "G21": 2, "G22": 2,
        "G23": 2, "G24": 2, "G25": 2, "G26": 2, "G27": 2, "G28": 2, "G29": 1,
        "G30": 2, "G31": 1, "G32": 2, "G33": 2, "G34": 2,
        "G35": 2, "G36": 2, "G37": 1, "G38": 2, "G39": 2, "G40": 1,
        "G41": 2, "G42": 2, "G43": 3, "G44": 2, "G45": 2, "G46": 1,
        "G47": 3, "G48": 1, "G49": 2, "G50": 2,
    }
    max_possible = sum(severity_map.values())
    violated_severity = sum(
        severity_map.get(str(issue.get("id", "")).split("_")[0], 2)
        for issue in (consistency_issues or [])
    )
    consistency_health_score = round(max(0, 10 - violated_severity / max(1, max_possible) * 10), 2)

    # 8. Information entropy (0-1, normalized Shannon entropy)
    dim_counts = [len(dim_entities.get(k, [])) for k in DIMENSIONS]
    total_ents = sum(dim_counts)
    if total_ents > 0 and total_dims > 1:
        proportions = [c / total_ents for c in dim_counts if c > 0]
        entropy = -sum(p * math.log2(p) for p in proportions)
        max_entropy = math.log2(total_dims)
        information_entropy = round(entropy / max_entropy, 4) if max_entropy > 0 else 0
    else:
        information_entropy = 0

    # 9. Family group balance (0-1)
    group_completion = {}
    for grp_name, fam_list in EDGE_FAMILY_GROUPS.items():
        complete_in_grp = sum(
            1 for tm in (template_matches or [])
            if tm.get("status") == "complete"
        )
        group_completion[grp_name] = min(1.0, complete_in_grp / max(1, len(fam_list)))
    grp_vals = list(group_completion.values())
    grp_total = sum(grp_vals)
    n_grps = len(grp_vals)
    if grp_total > 0 and n_grps > 1:
        grp_props = [v / grp_total for v in grp_vals if v > 0]
        grp_entropy = -sum(p * math.log2(p) for p in grp_props) if grp_props else 0
        family_group_balance = round(grp_entropy / math.log2(n_grps), 4) if math.log2(n_grps) > 0 else 0
    else:
        family_group_balance = 0

    formulas = {
        "depth_weighted_coverage": "sum(dim_depth_i) / (total_dims × 3) × 10, depth_i ∈ {0,1,2,3} by entity count + cross-link bonus",
        "graph_density": "2E / (V × (V-1)), V=nodes, E=edges",
        "avg_node_degree": "2E / V",
        "cross_dimension_ratio": "cross_dim_edges / total_edges",
        "hub_concentration": "Gini(node_degrees), 0=uniform, 1=concentrated",
        "template_completion_score": "Σ(complete_i × weight_i) / Σ(weight_i) × 10, ideal=3, risk=2, neutral=1",
        "consistency_health_score": "10 - violated_severity / max_severity × 10",
        "information_entropy": "H(dim_proportions) / log₂(total_dims), Shannon normalized entropy",
        "family_group_balance": "H(group_completions) / log₂(n_groups)",
    }

    return {
        "depth_weighted_coverage": depth_weighted_coverage,
        "graph_density": graph_density,
        "avg_node_degree": avg_node_degree,
        "cross_dimension_ratio": cross_dimension_ratio,
        "hub_concentration": hub_concentration,
        "template_completion_score": template_completion_score,
        "consistency_health_score": consistency_health_score,
        "information_entropy": information_entropy,
        "family_group_balance": family_group_balance,
        "dim_depths": dim_depths,
        "formulas": formulas,
    }


def _compute_design_rationality() -> dict:
    """Compute design rationality metrics for the hypergraph ontology (pure static, no case data needed)."""
    import math

    # ── 1. Theoretical Framework Alignment ──
    FRAMEWORK_MAPPING: dict[str, list[str]] = {
        "Lean Canvas (Maurya 2012)": ["价值叙事与一致性", "用户-市场-需求", "单位经济与财务结构"],
        "Business Model Canvas (Osterwalder 2010)": ["用户-市场-需求", "增长、渠道与规模化", "单位经济与财务结构", "生态与多方利益"],
        "Design Thinking (Stanford d.school)": ["问题发现与需求洞察", "创意孵化与方案设计", "用户体验与设计思维"],
        "Technology Readiness Level (NASA)": ["数据与技术验证", "产品差异化与竞争动态"],
        "Triple Helix (Etzkowitz 2003)": ["知识转化与产学研"],
        "COSO ERM / ISO 31000": ["风险、证据与评分", "合规、监管与伦理"],
        "ESG / UN SDGs": ["社会与ESG"],
        "Porter Five Forces + Moat Theory": ["产品差异化与竞争动态"],
        "Growth Hacking / AARRR (McClure 2007)": ["增长、渠道与规模化"],
        "Tuckman Team Development + OKR": ["执行、团队与里程碑"],
        "Platform Economics (Parker et al. 2016)": ["生态与多方利益"],
    }
    all_groups = list(EDGE_FAMILY_GROUPS.keys())
    groups_with_theory = set()
    framework_detail = []
    for fw_name, mapped_groups in FRAMEWORK_MAPPING.items():
        matched = [g for g in mapped_groups if g in all_groups]
        framework_detail.append({"framework": fw_name, "mapped_groups": matched, "count": len(matched)})
        groups_with_theory.update(matched)
    framework_coverage = round(len(groups_with_theory) / max(1, len(all_groups)), 4)

    # ── 2. Template Dimension Coverage Matrix ──
    dim_keys = list(DIMENSIONS.keys())
    n_dims = len(dim_keys)
    dim_index = {k: i for i, k in enumerate(dim_keys)}

    dim_freq = {k: 0 for k in dim_keys}
    cooccurrence = [[0] * n_dims for _ in range(n_dims)]
    pattern_counts = {"ideal": 0, "risk": 0, "neutral": 0}
    total_dim_refs = 0
    group_template_counts: dict[str, dict[str, int]] = {g: {"ideal": 0, "risk": 0, "neutral": 0, "total": 0} for g in all_groups}

    for tmpl in _HYPEREDGE_TEMPLATES:
        dims = tmpl.get("dimensions", [])
        pt = tmpl.get("pattern_type", "neutral")
        pattern_counts[pt] = pattern_counts.get(pt, 0) + 1
        total_dim_refs += len(dims)
        for d in dims:
            if d in dim_freq:
                dim_freq[d] += 1
        for i_idx in range(len(dims)):
            for j_idx in range(i_idx + 1, len(dims)):
                di, dj = dims[i_idx], dims[j_idx]
                if di in dim_index and dj in dim_index:
                    ii, jj = dim_index[di], dim_index[dj]
                    cooccurrence[ii][jj] += 1
                    cooccurrence[jj][ii] += 1

    n_templates = len(_HYPEREDGE_TEMPLATES)
    covered_dims = sum(1 for v in dim_freq.values() if v > 0)
    dim_coverage = round(covered_dims / max(1, n_dims), 4)
    avg_dims_per_template = round(total_dim_refs / max(1, n_templates), 2)

    freq_vals = [v for v in dim_freq.values() if v > 0]
    freq_total = sum(freq_vals)
    if freq_total > 0 and len(freq_vals) > 1:
        props = [v / freq_total for v in freq_vals]
        freq_entropy = -sum(p * math.log2(p) for p in props)
        freq_balance = round(freq_entropy / math.log2(len(freq_vals)), 4)
    else:
        freq_balance = 0

    # ── 3. Group Structural Balance ──
    group_sizes = [len(fams) for fams in EDGE_FAMILY_GROUPS.values()]
    n_groups = len(group_sizes)

    if n_groups > 1 and sum(group_sizes) > 0:
        gs_total = sum(group_sizes)
        gs_props = [s / gs_total for s in group_sizes if s > 0]
        gs_entropy = -sum(p * math.log2(p) for p in gs_props)
        group_balance_entropy = round(gs_entropy / math.log2(n_groups), 4)
    else:
        group_balance_entropy = 0

    sorted_gs = sorted(group_sizes)
    n_gs = len(sorted_gs)
    gs_sum = sum(sorted_gs)
    if n_gs > 1 and gs_sum > 0:
        cum = sum((2 * (i + 1) - n_gs - 1) * sorted_gs[i] for i in range(n_gs))
        group_gini = round(cum / (n_gs * gs_sum), 4)
    else:
        group_gini = 0

    # ── 4. Pattern Diversity (ideal/risk balance) ──
    ideal_r = pattern_counts.get("ideal", 0) / max(1, n_templates)
    risk_r = pattern_counts.get("risk", 0) / max(1, n_templates)
    neutral_r = pattern_counts.get("neutral", 0) / max(1, n_templates)
    pattern_ratios = [r for r in [ideal_r, risk_r, neutral_r] if r > 0]
    if len(pattern_ratios) > 1:
        pat_entropy = -sum(p * math.log2(p) for p in pattern_ratios)
        pattern_diversity = round(pat_entropy / math.log2(3), 4)
    else:
        pattern_diversity = 0

    # ── 5. Rule Dimension Coverage ──
    RULE_DIM_MAP: dict[str, list[str]] = {
        "G1": ["competitor"], "G2": ["stakeholder", "pain_point", "evidence"],
        "G3": ["solution", "pain_point"], "G4": ["channel"],
        "G5": [], "G6": ["market"], "G7": ["solution", "business_model"],
        "G8": ["evidence"], "G9": ["risk"], "G10": ["technology", "team"],
        "G11": ["stakeholder", "channel"], "G12": ["technology", "pain_point"],
        "G13": ["business_model", "competitor"], "G14": ["business_model", "market"],
        "G15": ["resource", "evidence"], "G16": ["team", "resource"],
        "G17": ["evidence", "stakeholder", "pain_point"], "G18": ["evidence"],
        "G19": [], "G20": ["risk"], "G21": ["business_model"],
        "G22": ["pain_point", "solution", "evidence"], "G23": ["team"],
        "G24": [], "G25": ["solution", "business_model", "evidence"],
        "G26": [], "G27": ["market", "stakeholder"], "G28": ["innovation", "competitor"],
        "G29": ["execution_step"], "G30": ["evidence"], "G31": ["solution", "stakeholder"],
        "G32": ["evidence"], "G33": ["business_model", "stakeholder", "evidence"],
        "G34": [], "G35": ["pain_point", "evidence"], "G36": ["stakeholder"],
        "G37": ["pain_point"], "G38": ["innovation", "evidence", "risk"],
        "G39": ["solution", "competitor"], "G40": [],
        "G41": ["technology", "innovation", "market", "business_model"],
        "G42": ["technology", "innovation"], "G43": [],
        "G44": ["technology", "evidence"], "G45": ["solution", "stakeholder"],
        "G46": ["solution"], "G47": [], "G48": [], "G49": [], "G50": [],
    }
    rule_dims_covered = set()
    rule_dim_freq: dict[str, int] = {k: 0 for k in dim_keys}
    for rule_id, rule_dims in RULE_DIM_MAP.items():
        for d in rule_dims:
            if d in rule_dim_freq:
                rule_dim_freq[d] += 1
                rule_dims_covered.add(d)
    rule_dim_coverage = round(len(rule_dims_covered) / max(1, n_dims), 4)

    # ── 6. Composite Score ──
    composite_score = round(
        framework_coverage * 0.25
        + dim_coverage * 0.25
        + group_balance_entropy * 0.20
        + pattern_diversity * 0.15
        + rule_dim_coverage * 0.15,
        4,
    )

    # ── 7. Design methodology statement ──
    methodology = {
        "layer_1_dimensions": {
            "description": "15个分析维度来自创新创业评审的通用维度拆解",
            "count": n_dims,
            "source": "精益画布(Lean Canvas) + 商业模式画布(BMC) + 设计思维(Design Thinking)框架融合",
            "dimensions": {k: v for k, v in DIMENSIONS.items()},
        },
        "layer_2_categories": {
            "description": "15个分类覆盖从问题发现到商业运营的完整创业旅程",
            "count": n_groups,
            "source": "创新到创业全流程阶段划分 + 横切关注点(风险/合规/ESG)",
            "categories": [{"name": g, "family_count": len(f)} for g, f in EDGE_FAMILY_GROUPS.items()],
        },
        "layer_3_families": {
            "description": "77个超边家族捕捉每个分类内的核心逻辑关系模式",
            "count": len(EDGE_FAMILY_LABELS),
            "source": "每个分类内识别影响项目成败的关键结构关系",
        },
    }

    return {
        "methodology": methodology,
        "framework_alignment": {
            "frameworks": framework_detail,
            "coverage": framework_coverage,
            "groups_mapped": len(groups_with_theory),
            "groups_total": len(all_groups),
        },
        "dimension_coverage": {
            "coverage_rate": dim_coverage,
            "covered_count": covered_dims,
            "total_count": n_dims,
            "dim_frequency": dim_freq,
            "frequency_balance": freq_balance,
            "avg_dims_per_template": avg_dims_per_template,
            "cooccurrence_matrix": {
                "dim_keys": dim_keys,
                "matrix": cooccurrence,
            },
        },
        "structural_balance": {
            "group_sizes": {g: len(f) for g, f in EDGE_FAMILY_GROUPS.items()},
            "entropy": group_balance_entropy,
            "gini": group_gini,
            "min_size": min(group_sizes) if group_sizes else 0,
            "max_size": max(group_sizes) if group_sizes else 0,
        },
        "pattern_diversity": {
            "ideal": pattern_counts.get("ideal", 0),
            "risk": pattern_counts.get("risk", 0),
            "neutral": pattern_counts.get("neutral", 0),
            "total": n_templates,
            "diversity_score": pattern_diversity,
        },
        "rule_coverage": {
            "total_rules": len(_CONSISTENCY_RULES),
            "dims_covered": len(rule_dims_covered),
            "dims_total": n_dims,
            "coverage_rate": rule_dim_coverage,
            "dim_frequency": rule_dim_freq,
        },
        "composite_score": composite_score,
        "score_formula": "0.25×framework + 0.25×dim_coverage + 0.20×structural_balance + 0.15×pattern_diversity + 0.15×rule_coverage",
        "templates_detail": [
            {
                "id": t.get("id", ""),
                "name": t.get("name", ""),
                "dimensions": t.get("dimensions", []),
                "pattern_type": t.get("pattern_type", "neutral"),
                "description": t.get("description", ""),
            }
            for t in _HYPEREDGE_TEMPLATES
        ],
    }


# ─────────────────────────────────────────────────────
#  Main service
# ─────────────────────────────────────────────────────

class HypergraphService:
    """Build/query teaching hypergraph + student dynamic analysis with HyperNetX."""

    def __init__(self, graph_service: GraphService) -> None:
        self.graph_service = graph_service
        self._hypergraph: hnx.Hypergraph | None = None
        self._records: list[HyperedgeRecord] = []
        self._family_counts: dict[str, int] = {}
        self._rule_alias: dict[str, list[str]] = {
            "H4": ["market_size_fallacy", "H9", "H19"],
            "H5": ["weak_user_evidence"],
            "H6": ["no_competitor_claim"],
            "H7": ["evidence_weak", "evidence_missing", "no_evidence"],
            "H8": ["unit_economics_not_proven", "unit_economics_unsound"],
            "H10": ["no_execution_plan", "execution_vague"],
            "H11": ["compliance_not_covered"],
            "H12": ["no_team_info", "team_missing"],
            "H13": ["no_risk_control", "risk_not_addressed"],
            "H14": ["no_innovation", "innovation_unclear"],
        }
        # Predefined hyperedge templates for logical loops.
        # These are used when analysing student content and do not
        # depend on Neo4j topology.
        self._edge_templates: list[dict[str, Any]] = _HYPEREDGE_TEMPLATES
        # Predefined hypergraph-level consistency rules.
        self._consistency_rules: list[dict[str, Any]] = _CONSISTENCY_RULES
        self._alias_to_rule: dict[str, str] = {}
        for rule_id, aliases in self._rule_alias.items():
            self._alias_to_rule[rule_id] = rule_id
            for alias in aliases:
                self._alias_to_rule[str(alias)] = rule_id

    def _canonical_rule_id(self, value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        return self._alias_to_rule.get(raw, raw)

    @staticmethod
    def _unique_texts(items: list[Any], max_items: int = 20) -> list[str]:
        """Deduplicate and clean a list of text values, preserving order."""
        seen: set[str] = set()
        out: list[str] = []
        for v in items or []:
            t = str(v or "").strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
            if len(out) >= max_items:
                break
        return out

    def _expand_rule_ids(self, values: list[Any] | None, max_items: int = 12) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            canonical = self._canonical_rule_id(value)
            if canonical and canonical not in seen:
                seen.add(canonical)
                out.append(canonical)
            raw = str(value or "").strip()
            if raw and raw not in seen:
                seen.add(raw)
                out.append(raw)
            if canonical:
                for alias in self._rule_alias.get(canonical, []):
                    alias_text = str(alias).strip()
                    if alias_text and alias_text not in seen:
                        seen.add(alias_text)
                        out.append(alias_text)
            if len(out) >= max_items:
                break
        return out[:max_items]

    def _has_rule(self, values: list[str], targets: set[str]) -> bool:
        canonical_values = {self._canonical_rule_id(v) for v in values if str(v).strip()}
        canonical_targets = {self._canonical_rule_id(v) for v in targets if str(v).strip()}
        return bool(canonical_values & canonical_targets)

    @staticmethod
    def _parse_node_members(node_set: set[str] | None) -> list[dict[str, str]]:
        members: list[dict[str, str]] = []
        for node in sorted(node_set or []):
            node_text = str(node)
            if "::" in node_text:
                ntype, name = node_text.split("::", 1)
            else:
                ntype, name = "Unknown", node_text
            members.append({
                "key": node_text,
                "type": ntype,
                "name": name,
                "display": name,
            })
        return members

    @staticmethod
    def _infer_stage_scope(
        evidence_types: list[str],
        business_models: list[str],
        execution_steps: list[str],
        risk_controls: list[str],
    ) -> str:
        if evidence_types and business_models and execution_steps:
            return "验证期"
        if business_models or execution_steps or risk_controls:
            return "原型期"
        return "想法期"

    @staticmethod
    def _estimate_severity(rule_count: int, rubric_count: int, support: int) -> tuple[str, float]:
        severity_score = rule_count * 1.5 + rubric_count * 0.6 + min(2.5, support / 2)
        if severity_score >= 7:
            return "高", round(min(10.0, 6.0 + severity_score / 2), 2)
        if severity_score >= 4:
            return "中", round(min(8.5, 3.8 + severity_score / 2.5), 2)
        return "低", round(min(6.0, 2.0 + severity_score / 3), 2)

    def _load_project_rows(self) -> list[dict[str, Any]]:
        try:
            rows = self.graph_service._query_with_fallback(
                lambda session: list(
                    session.run(
                        """
                        MATCH (p:Project)-[:BELONGS_TO]->(c:Category)
                        RETURN p.id AS project_id,
                               coalesce(p.name, p.id, '') AS project_name,
                               c.name AS category,
                               coalesce(p.confidence, 0.0) AS confidence,
                               [(p)-[:HAS_TARGET_USER]->(u:Stakeholder) | u.name] AS stakeholders,
                               [(p)-[:HAS_PAIN]->(pain:PainPoint) | pain.name] AS pains,
                               [(p)-[:HAS_SOLUTION]->(sol:Solution) | sol.name] AS solutions,
                               [(p)-[:HAS_INNOVATION]->(inv:InnovationPoint) | inv.name] AS innovations,
                               [(p)-[:HAS_BUSINESS_MODEL]->(bm:BusinessModelAspect) | bm.name] AS business_models,
                               [(p)-[:HAS_MARKET_ANALYSIS]->(m:Market) | m.name] AS markets,
                               [(p)-[:HAS_EXECUTION_STEP]->(ex:ExecutionStep) | ex.name] AS execution_steps,
                               [(p)-[:HAS_RISK_CONTROL]->(rc:RiskControlPoint) | rc.name] AS risk_controls,
                               [(p)-[:HAS_EVIDENCE]->(e:Evidence) | {quote: coalesce(e.quote, ''), type: coalesce(e.type, ''), source_unit: coalesce(e.source_unit, '')}] AS evidence_rows,
                               [(p)-[ev:EVALUATED_BY]->(ri:RubricItem) | {name: ri.name, covered: coalesce(ev.covered, false)}] AS rubric_rows,
                               [(p)-[:HITS_RULE]->(r:RiskRule) | r.id] AS rule_ids
                        """
                    )
                )
            )
        except Exception as exc:
            logger.warning("Hypergraph source query failed: %s", exc)
            rows = []

        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            evidence_rows = []
            for item in row.get("evidence_rows") or []:
                if not isinstance(item, dict):
                    continue
                quote = str(item.get("quote", "")).strip()
                evidence_rows.append({
                    "quote": quote[:160],
                    "type": str(item.get("type", "")).strip(),
                    "source_unit": str(item.get("source_unit", "")).strip(),
                })
            rubric_rows = []
            for item in row.get("rubric_rows") or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                if not name:
                    continue
                rubric_rows.append({
                    "name": name,
                    "covered": bool(item.get("covered", False)),
                })
            normalized_rows.append({
                "project_id": str(row.get("project_id") or ""),
                "project_name": str(row.get("project_name") or ""),
                "category": str(row.get("category") or "未分类"),
                "confidence": float(row.get("confidence") or 0.0),
                "stakeholders": self._unique_texts(list(row.get("stakeholders") or [])),
                "pains": self._unique_texts(list(row.get("pains") or [])),
                "solutions": self._unique_texts(list(row.get("solutions") or [])),
                "innovations": self._unique_texts(list(row.get("innovations") or [])),
                "business_models": self._unique_texts(list(row.get("business_models") or [])),
                "markets": self._unique_texts(list(row.get("markets") or [])),
                "execution_steps": self._unique_texts(list(row.get("execution_steps") or [])),
                "risk_controls": self._unique_texts(list(row.get("risk_controls") or [])),
                "evidence_rows": evidence_rows[:8],
                "rubric_rows": rubric_rows[:12],
                "rule_ids": self._expand_rule_ids(list(row.get("rule_ids") or []), max_items=12),
            })
        return normalized_rows

    def _load_ontology_rows(self) -> list[dict[str, Any]]:
        try:
            return self.graph_service._query_with_fallback(
                lambda session: list(
                    session.run(
                        """
                        MATCH (n)-[:INSTANCE_OF]->(o:OntologyNode)
                        OPTIONAL MATCH (p:Project)-[:BELONGS_TO]->(c:Category)
                        WHERE EXISTS { MATCH (p)-[:HAS_TARGET_USER]->(n) }
                           OR EXISTS { MATCH (p)-[:HAS_PAIN]->(n) }
                           OR EXISTS { MATCH (p)-[:HAS_SOLUTION]->(n) }
                           OR EXISTS { MATCH (p)-[:HAS_BUSINESS_MODEL]->(n) }
                           OR EXISTS { MATCH (p)-[:HAS_MARKET_ANALYSIS]->(n) }
                           OR EXISTS { MATCH (p)-[:HAS_EXECUTION_STEP]->(n) }
                           OR EXISTS { MATCH (p)-[:HAS_RISK_CONTROL]->(n) }
                        RETURN coalesce(o.id, o.name, 'unknown') AS ontology_id,
                               coalesce(o.name, o.id, 'unknown') AS ontology_name,
                               coalesce(n.name, n.id, '') AS instance_name,
                               head(labels(n)) AS instance_label,
                               collect(DISTINCT c.name)[0..5] AS categories,
                               count(DISTINCT p) AS support
                        ORDER BY support DESC
                        LIMIT 40
                        """
                    )
                )
            )
        except Exception:
            return []

    def _register_pattern(self, bucket: dict[tuple, dict[str, Any]], key: tuple, payload: dict[str, Any]) -> None:
        slot = bucket.setdefault(
            key,
            {
                "support": 0,
                "category": payload.get("category"),
                "node_set": set(),
                "rules": set(),
                "rubrics": set(),
                "evidence_quotes": [],
                "teaching_note": payload.get("teaching_note", ""),
                "retrieval_reason": payload.get("retrieval_reason", ""),
                "source_project_ids": set(),
                "confidence_sum": 0.0,
                "stage_counts": Counter(),
            },
        )
        slot["support"] += 1
        slot["node_set"].update(payload.get("node_set", set()))
        slot["rules"].update(payload.get("rules", []))
        slot["rubrics"].update(payload.get("rubrics", []))
        source_project_id = str(payload.get("source_project_id", "")).strip()
        if source_project_id:
            slot["source_project_ids"].add(source_project_id)
        slot["confidence_sum"] += float(payload.get("confidence", 0.0) or 0.0)
        stage_scope = str(payload.get("stage_scope", "")).strip()
        if stage_scope:
            slot["stage_counts"][stage_scope] += 1
        for quote in payload.get("evidence_quotes", []):
            q = str(quote or "").strip()
            if q and q not in slot["evidence_quotes"]:
                slot["evidence_quotes"].append(q[:160])
        if not slot["teaching_note"]:
            slot["teaching_note"] = payload.get("teaching_note", "")
        if not slot["retrieval_reason"]:
            slot["retrieval_reason"] = payload.get("retrieval_reason", "")

    def _add_record(
        self,
        edge_to_nodes: dict[str, set[str]],
        records: list[HyperedgeRecord],
        edge_type: str,
        payload: dict[str, Any],
    ) -> None:
        node_set = {str(x) for x in payload.get("node_set", set()) if str(x)}
        if len(node_set) < 3:
            return
        idx = self._family_counts.get(edge_type, 0) + 1
        self._family_counts[edge_type] = idx
        edge_id = f"{EDGE_PREFIX.get(edge_type, 'he_misc_')}{idx:03d}"
        edge_to_nodes[edge_id] = node_set
        support = int(payload.get("support", 1) or 1)
        rules = sorted({str(x) for x in payload.get("rules", []) if x})
        rubrics = sorted({str(x) for x in payload.get("rubrics", []) if x})
        member_nodes = self._parse_node_members(node_set)
        avg_confidence = round(float(payload.get("confidence_sum", 0.0) or 0.0) / max(1, support), 3)
        stage_counts = payload.get("stage_counts") or {}
        if isinstance(stage_counts, Counter):
            stage_scope = stage_counts.most_common(1)[0][0] if stage_counts else ""
        elif isinstance(stage_counts, dict):
            stage_scope = sorted(stage_counts.items(), key=lambda item: item[1], reverse=True)[0][0] if stage_counts else ""
        else:
            stage_scope = ""
        severity, score_impact = self._estimate_severity(len(rules), len(rubrics), support)
        records.append(
            HyperedgeRecord(
                hyperedge_id=edge_id,
                type=edge_type,
                support=support,
                teaching_note=str(payload.get("teaching_note", "") or EDGE_FAMILY_LABELS.get(edge_type, edge_type)),
                category=str(payload.get("category") or "") or None,
                rules=rules,
                rubrics=rubrics,
                evidence_quotes=[str(x)[:160] for x in (payload.get("evidence_quotes", []) or [])[:3] if x],
                retrieval_reason=str(payload.get("retrieval_reason", "")),
                node_set=node_set,
                source_project_ids=sorted({str(x) for x in payload.get("source_project_ids", set()) if x})[:8],
                member_nodes=member_nodes,
                confidence=avg_confidence,
                severity=severity,
                score_impact=score_impact,
                stage_scope=stage_scope,
            )
        )

    def _record_to_dict(self, rec: HyperedgeRecord) -> dict[str, Any]:
        return {
            "hyperedge_id": rec.hyperedge_id,
            "type": rec.type,
            "family_label": EDGE_FAMILY_LABELS.get(rec.type, rec.type),
            "support": rec.support,
            "teaching_note": rec.teaching_note,
            "category": rec.category,
            "rules": list(rec.rules),
            "rubrics": list(rec.rubrics),
            "evidence_quotes": list(rec.evidence_quotes),
            "retrieval_reason": rec.retrieval_reason,
            "nodes": sorted(rec.node_set) if rec.node_set else [],
            "member_nodes": list(rec.member_nodes),
            "source_project_ids": list(rec.source_project_ids),
            "confidence": rec.confidence,
            "severity": rec.severity,
            "score_impact": rec.score_impact,
            "stage_scope": rec.stage_scope,
        }

    # ═══════════════════════════════════════════════════
    #  1. Rebuild global teaching hypergraph from Neo4j
    # ═══════════════════════════════════════════════════

    def rebuild(self, min_pattern_support: int = 1, max_edges: int = 400) -> dict[str, Any]:
        min_pattern_support = max(1, min(min_pattern_support, 10))
        max_edges = max(5, min(max_edges, 600))
        rows = self._load_project_rows()
        ontology_rows = self._load_ontology_rows()
        edge_to_nodes: dict[str, set[str]] = {}
        records: list[HyperedgeRecord] = []
        self._family_counts = {}
        families: dict[str, dict[tuple, dict[str, Any]]] = {k: {} for k in EDGE_TARGET_COUNTS}

        for row in rows:
            project_id = str(row.get("project_id") or "")
            category = str(row.get("category") or "未分类")
            confidence = float(row.get("confidence") or 0.0)
            stakeholders = list(row.get("stakeholders") or [])
            pains = list(row.get("pains") or [])
            solutions = list(row.get("solutions") or [])
            innovations = list(row.get("innovations") or [])
            business_models = list(row.get("business_models") or [])
            markets = list(row.get("markets") or [])
            execution_steps = list(row.get("execution_steps") or [])
            risk_controls = list(row.get("risk_controls") or [])
            evidence_rows = list(row.get("evidence_rows") or [])
            rubric_rows = list(row.get("rubric_rows") or [])
            rule_ids = list(row.get("rule_ids") or [])
            evidence_quotes = [str(e.get("quote", "")).strip() for e in evidence_rows if isinstance(e, dict) and e.get("quote")]
            evidence_types = self._unique_texts([e.get("type", "") for e in evidence_rows if isinstance(e, dict)])
            covered_rubrics = self._unique_texts([r.get("name", "") for r in rubric_rows if isinstance(r, dict) and r.get("covered")])
            uncovered_rubrics = self._unique_texts([r.get("name", "") for r in rubric_rows if isinstance(r, dict) and not r.get("covered")])
            stage_scope = self._infer_stage_scope(evidence_types, business_models, execution_steps, risk_controls)
            base_pattern_meta = {
                "source_project_id": project_id,
                "confidence": confidence,
                "stage_scope": stage_scope,
            }

            if pains and solutions:
                stakeholder_candidates = stakeholders[:2] or ["未细分用户"]
                business_candidates = business_models[:2] or ["商业模式待补强"]
                market_candidates = markets[:2] or ["市场分析待补强"]
                for stakeholder in stakeholder_candidates:
                    for pain in pains[:2]:
                        for solution in solutions[:2]:
                            business_model = business_candidates[0]
                            market = market_candidates[0]
                            key = (category, stakeholder, pain, solution, business_model, market)
                            self._register_pattern(
                                families["Value_Loop_Edge"],
                                key,
                                {
                                    **base_pattern_meta,
                                    "category": category,
                                    "node_set": {
                                        f"Category::{category}",
                                        f"Stakeholder::{stakeholder}",
                                        f"PainPoint::{pain}",
                                        f"Solution::{solution}",
                                        f"BusinessModelAspect::{business_model}",
                                        f"Market::{market}",
                                    },
                                    "rules": rule_ids,
                                    "rubrics": covered_rubrics,
                                    "evidence_quotes": evidence_quotes[:2],
                                    "teaching_note": f"{category}类项目常围绕“{stakeholder}—{pain}—{solution}”形成价值闭环，并需要通过{business_model}完成变现。",
                                    "retrieval_reason": "目标用户、痛点、方案与商业模式同时出现，适合做价值闭环检索。",
                                },
                            )

            if stakeholders and pains:
                for stakeholder in stakeholders[:2]:
                    for pain in pains[:2]:
                        solution = solutions[0] if solutions else "解决方案待补强"
                        key = (category, stakeholder, pain, solution)
                        self._register_pattern(
                            families["User_Pain_Fit_Edge"],
                            key,
                            {
                                **base_pattern_meta,
                                "category": category,
                                "node_set": {
                                    f"Category::{category}",
                                    f"Stakeholder::{stakeholder}",
                                    f"PainPoint::{pain}",
                                    f"Solution::{solution}",
                                },
                                "rules": rule_ids,
                                "rubrics": covered_rubrics,
                                "evidence_quotes": evidence_quotes[:2],
                                "teaching_note": f"{category}类项目中，面向“{stakeholder}”的项目经常围绕“{pain}”来设计方案匹配。",
                                "retrieval_reason": "用户与痛点同时明确，适合用于用户痛点匹配追问。",
                            },
                        )

            if rule_ids:
                canonical_rules = [rid for rid in rule_ids if rid.startswith("H")]
                rule_tuple = tuple(sorted(canonical_rules[:4] or rule_ids[:4]))
                rubric_tuple = tuple(sorted((uncovered_rubrics or covered_rubrics)[:2]))
                key = (category, rule_tuple, rubric_tuple)
                self._register_pattern(
                    families["Risk_Pattern_Edge"],
                    key,
                    {
                        **base_pattern_meta,
                        "category": category,
                        "node_set": {f"Category::{category}"} | {f"RiskRule::{rid}" for rid in rule_tuple} | {f"RubricItem::{rb}" for rb in rubric_tuple},
                        "rules": list(rule_tuple),
                        "rubrics": list(rubric_tuple),
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类项目常见风险模式为“{'、'.join(rule_tuple)}”，通常会拖累{'、'.join(rubric_tuple) if rubric_tuple else '多个评分维度'}。",
                        "retrieval_reason": "风险规则与Rubric覆盖共同命中，适合做风险模式检索。",
                    },
                )

            if evidence_types and (covered_rubrics or uncovered_rubrics or rule_ids):
                rubric_anchor = tuple(sorted((uncovered_rubrics or covered_rubrics)[:2]))
                evidence_anchor = tuple(sorted(evidence_types[:2]))
                rule_anchor = tuple(sorted(rule_ids[:2]))
                key = (category, evidence_anchor, rubric_anchor, rule_anchor)
                self._register_pattern(
                    families["Evidence_Grounding_Edge"],
                    key,
                    {
                        **base_pattern_meta,
                        "category": category,
                        "node_set": {f"Category::{category}"} | {f"EvidenceType::{x}" for x in evidence_anchor} | {f"RubricItem::{x}" for x in rubric_anchor} | {f"RiskRule::{x}" for x in rule_anchor},
                        "rules": list(rule_anchor),
                        "rubrics": list(rubric_anchor),
                        "evidence_quotes": evidence_quotes[:3],
                        "teaching_note": f"{category}类项目常用“{'、'.join(evidence_anchor)}”类证据支撑{'、'.join(rubric_anchor) if rubric_anchor else '核心判断'}。",
                        "retrieval_reason": "证据类型与评分维度能对齐，适合做证据锚定检索。",
                    },
                )

            market_targets = {"H4", "H6", "H9", "H16", "H17", "H19"}
            market_rule_hit = self._has_rule(rule_ids, market_targets)
            if markets or market_rule_hit:
                for market in (markets[:2] or ["市场口径待校准"]):
                    stakeholder = stakeholders[0] if stakeholders else "目标用户待细化"
                    innovation = innovations[0] if innovations else (solutions[0] if solutions else "差异化待说明")
                    key = (category, market, stakeholder, innovation)
                    self._register_pattern(
                        families["Market_Competition_Edge"],
                        key,
                        {
                            **base_pattern_meta,
                            "category": category,
                            "node_set": {
                                f"Category::{category}",
                                f"Market::{market}",
                                f"Stakeholder::{stakeholder}",
                                f"InnovationPoint::{innovation}",
                            },
                            "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in market_targets][:6],
                            "rubrics": uncovered_rubrics or covered_rubrics,
                            "evidence_quotes": evidence_quotes[:2],
                            "teaching_note": f"{category}类项目的竞争与市场判断，通常要同时回答市场口径、替代方案和差异化价值三个问题。",
                            "retrieval_reason": "市场/竞争相关节点或规则被命中，适合做竞争与替代方案追问。",
                        },
                    )

            execution_targets = {"H10", "H12", "H21", "H22"}
            execution_rule_hit = self._has_rule(rule_ids, execution_targets)
            if execution_steps or execution_rule_hit:
                for step in (execution_steps[:2] or ["执行路径待拆解"]):
                    business_model = business_models[0] if business_models else "商业闭环待补强"
                    risk_control = risk_controls[0] if risk_controls else "风控机制待细化"
                    key = (category, step, business_model, risk_control)
                    self._register_pattern(
                        families["Execution_Gap_Edge"],
                        key,
                        {
                            **base_pattern_meta,
                            "category": category,
                            "node_set": {
                                f"Category::{category}",
                                f"ExecutionStep::{step}",
                                f"BusinessModelAspect::{business_model}",
                                f"RiskControlPoint::{risk_control}",
                            },
                            "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in execution_targets][:6],
                            "rubrics": [rb for rb in (covered_rubrics + uncovered_rubrics) if rb in {"Team & Execution", "Business Model Consistency"}],
                            "evidence_quotes": evidence_quotes[:2],
                            "teaching_note": f"{category}类项目在执行层面最常见的问题，是步骤、商业闭环和风控机制没有一起落地。",
                            "retrieval_reason": "执行节点或执行类风险被命中，适合做执行断裂追问。",
                        },
                    )

            compliance_targets = {"H11", "H22"}
            compliance_rule_hit = self._has_rule(rule_ids, compliance_targets)
            if risk_controls or compliance_rule_hit:
                risk_control = risk_controls[0] if risk_controls else "合规措施待细化"
                evidence_type = evidence_types[0] if evidence_types else "制度证据待补充"
                key = (category, risk_control, evidence_type)
                self._register_pattern(
                    families["Compliance_Safety_Edge"],
                    key,
                    {
                        **base_pattern_meta,
                        "category": category,
                        "node_set": {
                            f"Category::{category}",
                            f"RiskControlPoint::{risk_control}",
                            f"EvidenceType::{evidence_type}",
                            "RubricItem::合规与风险",
                        },
                        "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in compliance_targets][:6],
                        "rubrics": [rb for rb in (covered_rubrics + uncovered_rubrics) if "risk" in rb.lower() or "presentation" in rb.lower()],
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类项目一旦涉及数据、伦理或合规，就必须把措施写成可执行流程，而不是停留在原则层面。",
                        "retrieval_reason": "合规/风控节点或规则被命中，适合做安全边界追问。",
                    },
                )

            innovation_targets = {"H7", "H13", "H23"}
            innovation_rule_hit = self._has_rule(rule_ids, innovation_targets)
            if innovations or innovation_rule_hit:
                for innovation in (innovations[:2] or ["创新主张待验证"]):
                    evidence_type = evidence_types[0] if evidence_types else "验证证据待补充"
                    market = markets[0] if markets else "应用场景待限定"
                    key = (category, innovation, evidence_type, market)
                    self._register_pattern(
                        families["Innovation_Validation_Edge"],
                        key,
                        {
                            **base_pattern_meta,
                            "category": category,
                            "node_set": {
                                f"Category::{category}",
                                f"InnovationPoint::{innovation}",
                                f"EvidenceType::{evidence_type}",
                                f"Market::{market}",
                            },
                            "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in innovation_targets][:6],
                            "rubrics": [rb for rb in (covered_rubrics + uncovered_rubrics) if rb in {"Innovation & Differentiation", "Solution Feasibility"}],
                            "evidence_quotes": evidence_quotes[:2],
                            "teaching_note": f"{category}类项目的创新点必须能落到具体场景和可验证证据上，否则只是口号。",
                            "retrieval_reason": "创新主张或验证类规则被命中，适合做创新验证追问。",
                        },
                    )

            pricing_targets = {"H8", "H10", "H15", "H18"}
            pricing_rule_hit = self._has_rule(rule_ids, pricing_targets)
            if business_models or pricing_rule_hit:
                pricing_anchor = business_models[0] if business_models else "收费机制待验证"
                evidence_type = evidence_types[0] if evidence_types else "成本证据待补充"
                stakeholder = stakeholders[0] if stakeholders else "核心付费用户待细化"
                key = (category, stakeholder, pricing_anchor, evidence_type)
                self._register_pattern(
                    families["Pricing_Unit_Economics_Edge"],
                    key,
                    {
                        **base_pattern_meta,
                        "category": category,
                        "node_set": {
                            f"Category::{category}",
                            f"Stakeholder::{stakeholder}",
                            f"BusinessModelAspect::{pricing_anchor}",
                            f"EvidenceType::{evidence_type}",
                        } | {f"RiskRule::{rid}" for rid in rule_ids[:2]},
                        "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in pricing_targets][:6],
                        "rubrics": [rb for rb in (covered_rubrics + uncovered_rubrics) if rb in {"Financial Logic", "Business Model Consistency"}],
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类项目的定价能否成立，不只看收费数字，还要看交付成本、重度用户占比和单个用户毛利空间。",
                        "retrieval_reason": "商业模式与成本/财务规则共同出现，适合做单元经济压力测试。",
                    },
                )

            if stakeholders and (markets or innovations or solutions):
                substitute_anchor = innovations[0] if innovations else (solutions[0] if solutions else "替代优势待说明")
                market = markets[0] if markets else "替代场景待限定"
                stakeholder = stakeholders[0]
                key = (category, stakeholder, market, substitute_anchor)
                self._register_pattern(
                    families["Substitute_Migration_Edge"],
                    key,
                    {
                        **base_pattern_meta,
                        "category": category,
                        "node_set": {
                            f"Category::{category}",
                            f"Stakeholder::{stakeholder}",
                            f"Market::{market}",
                            f"InnovationPoint::{substitute_anchor}",
                        },
                        "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in market_targets][:6],
                        "rubrics": [rb for rb in (covered_rubrics + uncovered_rubrics) if rb in {"Innovation & Differentiation", "Market Opportunity"}],
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类项目若要让用户迁移，必须解释现有替代方案为什么不够好，以及切换成本由谁承担。",
                        "retrieval_reason": "用户、市场与差异化同时出现，适合做替代方案和迁移成本检索。",
                    },
                )

            trust_targets = {"H5", "H11", "H22"}
            trust_rule_hit = self._has_rule(rule_ids, trust_targets)
            if stakeholders and (risk_controls or evidence_types or trust_rule_hit):
                stakeholder = stakeholders[0]
                trust_anchor = risk_controls[0] if risk_controls else "可信机制待明确"
                evidence_type = evidence_types[0] if evidence_types else "可信证据待补充"
                solution = solutions[0] if solutions else "核心功能待定义"
                key = (category, stakeholder, solution, trust_anchor, evidence_type)
                self._register_pattern(
                    families["Trust_Adoption_Edge"],
                    key,
                    {
                        **base_pattern_meta,
                        "category": category,
                        "node_set": {
                            f"Category::{category}",
                            f"Stakeholder::{stakeholder}",
                            f"Solution::{solution}",
                            f"RiskControlPoint::{trust_anchor}",
                            f"EvidenceType::{evidence_type}",
                        },
                        "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in trust_targets][:6],
                        "rubrics": [rb for rb in (covered_rubrics + uncovered_rubrics) if rb in {"Solution Feasibility", "User Evidence Strength"}],
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类项目要被用户真正采用，往往不是功能够多，而是用户是否敢在关键任务里信任它。",
                        "retrieval_reason": "用户、可信机制与证据共同出现，适合做信任门槛检索。",
                    },
                )

            if stakeholders and execution_steps and solutions:
                stakeholder = stakeholders[0]
                execution_step = execution_steps[0]
                solution = solutions[0]
                business_anchor = business_models[0] if business_models else "留存机制待说明"
                key = (category, stakeholder, solution, execution_step, business_anchor)
                self._register_pattern(
                    families["Retention_Workflow_Embed_Edge"],
                    key,
                    {
                        **base_pattern_meta,
                        "category": category,
                        "node_set": {
                            f"Category::{category}",
                            f"Stakeholder::{stakeholder}",
                            f"Solution::{solution}",
                            f"ExecutionStep::{execution_step}",
                            f"BusinessModelAspect::{business_anchor}",
                        },
                        "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in execution_targets][:6],
                        "rubrics": [rb for rb in (covered_rubrics + uncovered_rubrics) if rb in {"Team & Execution", "Solution Feasibility"}],
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类工具想要留存，关键不是被试一次，而是能否嵌进用户原有工作流。",
                        "retrieval_reason": "执行步骤与核心方案共同出现，适合做留存与工作流嵌入检索。",
                    },
                )

            if rule_ids and (covered_rubrics or uncovered_rubrics):
                tension_rules = tuple(sorted(rule_ids[:3]))
                tension_rubrics = tuple(sorted((covered_rubrics + uncovered_rubrics)[:3]))
                evidence_type = evidence_types[0] if evidence_types else "结构证据待补充"
                key = (category, tension_rules, tension_rubrics, evidence_type)
                self._register_pattern(
                    families["Rule_Rubric_Tension_Edge"],
                    key,
                    {
                        **base_pattern_meta,
                        "category": category,
                        "node_set": {f"Category::{category}", f"EvidenceType::{evidence_type}"} | {f"RiskRule::{rid}" for rid in tension_rules} | {f"RubricItem::{rb}" for rb in tension_rubrics},
                        "rules": list(tension_rules),
                        "rubrics": list(tension_rubrics),
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类项目中，某些规则风险会同时拉低多个评分维度，形成“规则-评分张力”。",
                        "retrieval_reason": "规则命中和评分维度同时存在，适合解释为什么一个问题会被连续追问。",
                    },
                )

            if stage_scope:
                focus_rule = rule_ids[0] if rule_ids else ""
                focus_rubric = (uncovered_rubrics or covered_rubrics or ["阶段目标待明确"])[0]
                evidence_anchor = evidence_types[0] if evidence_types else "阶段证据待补充"
                key = (category, stage_scope, focus_rubric, evidence_anchor, focus_rule)
                self._register_pattern(
                    families["Stage_Goal_Fit_Edge"],
                    key,
                    {
                        **base_pattern_meta,
                        "category": category,
                        "node_set": {
                            f"Category::{category}",
                            f"Stage::{stage_scope}",
                            f"RubricItem::{focus_rubric}",
                            f"EvidenceType::{evidence_anchor}",
                        } | ({f"RiskRule::{focus_rule}"} if focus_rule else set()),
                        "rules": [focus_rule] if focus_rule else [],
                        "rubrics": [focus_rubric],
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类项目在{stage_scope}最重要的不是面面俱到，而是完成该阶段最关键的验证目标。",
                        "retrieval_reason": "阶段、证据与评分焦点可对齐，适合解释当前阶段应该优先证明什么。",
                    },
                )

            # ── New families (T21-T36) ──

            if stakeholders and solutions and execution_steps:
                team_member = execution_steps[0]
                tech = solutions[0]
                key = (category, team_member, tech)
                self._register_pattern(families["Team_Capability_Gap_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"ExecutionStep::{team_member}", f"Solution::{tech}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H9", "H10"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Team & Execution"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目的团队能力是否匹配技术和执行要求，是评委重点考察的维度。",
                    "retrieval_reason": "团队执行步骤与技术方案共现，适合做团队能力差距分析。",
                })

            if stakeholders and pains and solutions:
                stakeholder = stakeholders[0]
                pain = pains[0]
                solution = solutions[0]
                key = (category, stakeholder, pain, solution, "journey")
                self._register_pattern(families["User_Journey_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"Stakeholder::{stakeholder}", f"PainPoint::{pain}", f"Solution::{solution}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H1", "H2"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"User Evidence Strength", "Problem Definition"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目的用户旅程是否完整（触达→认知→试用→留存→推荐）决定了增长飞轮能否转起来。",
                    "retrieval_reason": "用户、痛点与方案构成旅程闭环。",
                })

            if stakeholders and pains and evidence_types:
                key = (category, stakeholders[0], pains[0], "social")
                self._register_pattern(families["Social_Impact_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"Stakeholder::{stakeholders[0]}", f"PainPoint::{pains[0]}", f"EvidenceType::{evidence_types[0] if evidence_types else '社会效果待量化'}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H5"}][:4],
                    "rubrics": covered_rubrics[:2],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目的社会价值需要量化——不是说'帮助了很多人'，而是用数据证明影响范围和深度。",
                    "retrieval_reason": "社会影响维度的用户与证据共现。",
                })

            if solutions and stakeholders and business_models:
                key = (category, solutions[0], stakeholders[0], "flywheel")
                self._register_pattern(families["Data_Flywheel_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"Solution::{solutions[0]}", f"Stakeholder::{stakeholders[0]}", f"BusinessModelAspect::{business_models[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H7", "H12"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Innovation & Differentiation", "Solution Feasibility"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目能否形成数据飞轮（更多用户→更多数据→更好产品→更多用户），是长期壁垒的关键。",
                    "retrieval_reason": "方案、用户与商业模式的飞轮结构。",
                })

            if markets and risk_controls:
                key = (category, markets[0], risk_controls[0], "scale")
                self._register_pattern(families["Scalability_Bottleneck_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"Market::{markets[0]}", f"RiskControlPoint::{risk_controls[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H9", "H14"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Team & Execution", "Market & Competition"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目从MVP到规模化最容易卡在哪？不是技术，往往是运营成本随规模非线性增长。",
                    "retrieval_reason": "市场与风控节点共现，适合做规模化瓶颈分析。",
                })

            if innovations and solutions:
                key = (category, innovations[0], solutions[0], "ip")
                self._register_pattern(families["IP_Moat_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"InnovationPoint::{innovations[0]}", f"Solution::{solutions[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H7", "H12"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Innovation & Differentiation"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目的壁垒是什么？是算法、数据、专利还是网络效应？评委会追问这个壁垒能撑多久。",
                    "retrieval_reason": "创新点与方案共现，适合做护城河分析。",
                })

            if evidence_types and stakeholders and pains:
                key = (category, evidence_types[0], stakeholders[0], "pivot")
                self._register_pattern(families["Pivot_Signal_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"EvidenceType::{evidence_types[0]}", f"Stakeholder::{stakeholders[0]}", f"PainPoint::{pains[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H1", "H5"}][:4],
                    "rubrics": covered_rubrics[:2],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目如果调研数据和预期不符，不要恐慌——这恰恰是最有价值的信号，说明你该调整方向了。",
                    "retrieval_reason": "证据与用户痛点出现偏差信号。",
                })

            if business_models and solutions:
                key = (category, business_models[0], solutions[0], "cost")
                self._register_pattern(families["Cost_Structure_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"BusinessModelAspect::{business_models[0]}", f"Solution::{solutions[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H8", "H10"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Financial Logic", "Business Model Consistency"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目的成本结构是否可持续？固定成本和边际成本的比例决定了盈亏平衡点。",
                    "retrieval_reason": "商业模式与方案的成本结构分析。",
                })

            if solutions and risk_controls:
                key = (category, solutions[0], risk_controls[0] if risk_controls else "平台依赖待评估", "eco")
                self._register_pattern(families["Ecosystem_Dependency_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"Solution::{solutions[0]}", f"RiskControlPoint::{risk_controls[0] if risk_controls else '平台依赖待评估'}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H11", "H14"}][:4],
                    "rubrics": covered_rubrics[:2],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目是否依赖某个平台/API/供应链？如果对方改规则或涨价，你的B方案是什么？",
                    "retrieval_reason": "方案与风控的生态依赖分析。",
                })

            if solutions and stakeholders and execution_steps:
                key = (category, solutions[0], stakeholders[0], execution_steps[0], "mvp")
                self._register_pattern(families["MVP_Scope_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"Solution::{solutions[0]}", f"Stakeholder::{stakeholders[0]}", f"ExecutionStep::{execution_steps[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H5", "H10"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Solution Feasibility", "User Evidence Strength"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目的MVP应该只包含一个核心假设的最小验证——不要贪多，先证明最关键的那一个。",
                    "retrieval_reason": "方案、用户与执行步骤构成MVP边界。",
                })

            if stakeholders and business_models and risk_controls:
                key = (category, stakeholders[0], business_models[0], "conflict")
                self._register_pattern(families["Stakeholder_Conflict_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"Stakeholder::{stakeholders[0]}", f"BusinessModelAspect::{business_models[0]}", f"RiskControlPoint::{risk_controls[0] if risk_controls else '利益平衡待设计'}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H1", "H3"}][:4],
                    "rubrics": covered_rubrics[:2],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目如果有多方利益相关者，要说清楚谁付费、谁受益、谁可能反对——以及你如何平衡。",
                    "retrieval_reason": "多方利益相关者与商业模式冲突分析。",
                })

            if stakeholders and evidence_types and business_models:
                key = (category, stakeholders[0], evidence_types[0] if evidence_types else "渠道证据待补充", "channel")
                self._register_pattern(families["Channel_Conversion_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"Stakeholder::{stakeholders[0]}", f"EvidenceType::{evidence_types[0] if evidence_types else '渠道证据待补充'}", f"BusinessModelAspect::{business_models[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H2", "H8"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Market & Competition", "Financial Logic"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目的获客不只是'在哪推广'，还要说清楚每一步的转化率假设和数据来源。",
                    "retrieval_reason": "用户、证据与商业模式的渠道转化分析。",
                })

            if risk_controls and markets:
                key = (category, risk_controls[0], markets[0], "regulatory")
                self._register_pattern(families["Regulatory_Landscape_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"RiskControlPoint::{risk_controls[0]}", f"Market::{markets[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H11", "H15"}][:4],
                    "rubrics": covered_rubrics[:2],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目所在行业有哪些法规红线？政策风向可能如何变化？这决定了你的天花板。",
                    "retrieval_reason": "风控与市场的政策法规环境分析。",
                })

            if stakeholders and pains and solutions and evidence_types:
                key = (category, stakeholders[0], pains[0], solutions[0], "narrative")
                self._register_pattern(families["Presentation_Narrative_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"Stakeholder::{stakeholders[0]}", f"PainPoint::{pains[0]}", f"Solution::{solutions[0]}", f"EvidenceType::{evidence_types[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H13"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Presentation Quality"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目路演的最佳叙事线：先讲一个真实用户故事→引出痛点→展示数据→方案→差异化→团队→展望。",
                    "retrieval_reason": "用户、痛点、方案与证据构成路演叙事线。",
                })

            if business_models and execution_steps:
                key = (category, business_models[0], execution_steps[0], "leverage")
                self._register_pattern(families["Resource_Leverage_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"BusinessModelAspect::{business_models[0]}", f"ExecutionStep::{execution_steps[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H9", "H14"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Team & Execution", "Business Model Consistency"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目资源有限时，要学会做减法——把80%的资源集中在最关键的一个验证点上。",
                    "retrieval_reason": "商业模式与执行步骤的资源杠杆分析。",
                })

            if markets and innovations:
                key = (category, markets[0], innovations[0], "timing")
                self._register_pattern(families["Timing_Window_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"Market::{markets[0]}", f"InnovationPoint::{innovations[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H4", "H6"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Market & Competition", "Innovation & Differentiation"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目的时机判断——太早了市场教育成本高，太晚了巨头已入场。你如何证明现在是最佳窗口期？",
                    "retrieval_reason": "市场与创新的时机窗口分析。",
                })

            # ── Batch 2 families (T37-T50) ──

            if business_models and markets and evidence_types:
                key = (category, business_models[0], markets[0], "revenue")
                self._register_pattern(families["Revenue_Sustainability_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"BusinessModelAspect::{business_models[0]}", f"Market::{markets[0]}", f"EvidenceType::{evidence_types[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H8", "H26"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Financial Logic", "Business Model Consistency"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目的收入是一次性的还是持续的？如果是订阅制，用户续费率假设来自哪里？",
                    "retrieval_reason": "商业模式与市场证据的收入可持续性分析。",
                })

            if stakeholders and pains and markets and solutions:
                key = (category, stakeholders[0], pains[0], solutions[0], "demsup")
                self._register_pattern(families["Demand_Supply_Match_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"Stakeholder::{stakeholders[0]}", f"PainPoint::{pains[0]}", f"Solution::{solutions[0]}", f"Market::{markets[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H1", "H5"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Problem Definition", "User Evidence Strength"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目最容易犯的错误是需求是真的但解决方案不匹配——用户要的是止痛药，你给了维生素。",
                    "retrieval_reason": "用户需求与产品供给的匹配度分析。",
                })

            if execution_steps and risk_controls:
                key = (category, execution_steps[0], risk_controls[0] if risk_controls else "单点依赖待评估", "founder")
                self._register_pattern(families["Founder_Risk_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"ExecutionStep::{execution_steps[0]}", f"RiskControlPoint::{risk_controls[0] if risk_controls else '单点依赖待评估'}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H10", "H21", "H25"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Team & Execution"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目如果核心技术或关键资源完全依赖一个人，那个人离开怎么办？评委一定会问这个。",
                    "retrieval_reason": "执行步骤与风控的关键人物依赖分析。",
                })

            if solutions and stakeholders and risk_controls:
                _has_ai_keyword = any(k in " ".join([str(s) for s in solutions + pains]) for k in ["AI", "算法", "推荐", "机器学习", "深度学习", "模型"])
                if _has_ai_keyword:
                    key = (category, solutions[0], stakeholders[0], "ethics")
                    self._register_pattern(families["Ethical_Bias_Edge"], key, {
                        **base_pattern_meta, "category": category,
                        "node_set": {f"Category::{category}", f"Solution::{solutions[0]}", f"Stakeholder::{stakeholders[0]}", f"RiskControlPoint::{risk_controls[0]}"},
                        "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H11", "H22"}][:4],
                        "rubrics": covered_rubrics[:2],
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类项目使用AI决策时，你考虑过算法偏见和公平性问题吗？不同用户群体是否被平等对待？",
                        "retrieval_reason": "AI/算法方案的伦理偏见与公平性分析。",
                    })

            if pains and solutions and business_models:
                ev_anchor = evidence_types[0] if evidence_types else "假设待验证"
                key = (category, pains[0], solutions[0], business_models[0], "assume")
                self._register_pattern(families["Assumption_Stack_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"PainPoint::{pains[0]}", f"Solution::{solutions[0]}", f"BusinessModelAspect::{business_models[0]}", f"EvidenceType::{ev_anchor}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H5", "H7", "H20"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"User Evidence Strength", "Solution Feasibility"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目从'用户有这个痛点'到'他们愿意为你的方案付钱'，中间有几个假设？每个假设你验证了几个？",
                    "retrieval_reason": "痛点、方案与商业模式之间的假设链分析。",
                })

            if evidence_types and solutions and business_models:
                key = (category, evidence_types[0], solutions[0], "metric")
                self._register_pattern(families["Metric_Definition_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"EvidenceType::{evidence_types[0]}", f"Solution::{solutions[0]}", f"BusinessModelAspect::{business_models[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H13", "H20"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Solution Feasibility", "User Evidence Strength"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目你说'效果好'，好的标准是什么？请给出一个具体数字和衡量方法。",
                    "retrieval_reason": "证据与方案的成功指标定义分析。",
                })

            if stakeholders and markets and pains:
                key = (category, stakeholders[0], markets[0], pains[0], "segment")
                self._register_pattern(families["Market_Segmentation_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"Stakeholder::{stakeholders[0]}", f"Market::{markets[0]}", f"PainPoint::{pains[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H1", "H4", "H19"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Problem Definition", "Market & Competition"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目说'面向所有用户'太宽了——哪个细分群体？什么场景？请把用户画像收窄到一个具体的人。",
                    "retrieval_reason": "用户、市场与痛点的细分聚焦分析。",
                })

            if innovations and markets and solutions:
                key = (category, innovations[0], markets[0], "compresp")
                self._register_pattern(families["Competitive_Response_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"InnovationPoint::{innovations[0]}", f"Market::{markets[0]}", f"Solution::{solutions[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H6", "H7", "H16"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Innovation & Differentiation", "Market & Competition"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目如果你的方案有效，巨头三个月就能抄。你的护城河不是功能本身，而是什么？",
                    "retrieval_reason": "创新点与市场的竞品反制风险分析。",
                })

            if execution_steps and solutions and business_models:
                key = (category, execution_steps[0], solutions[0], "milestone")
                self._register_pattern(families["Milestone_Dependency_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"ExecutionStep::{execution_steps[0]}", f"Solution::{solutions[0]}", f"BusinessModelAspect::{business_models[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H10", "H21"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Team & Execution"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目你的第二个里程碑依赖第一个的结果吗？如果第一步失败，后面的计划是否全部作废？需要设计容错路径。",
                    "retrieval_reason": "执行步骤之间的依赖与容错分析。",
                })

            funding_targets = {"H9", "H24"}
            funding_rule_hit = self._has_rule(rule_ids, funding_targets)
            if (business_models and markets and evidence_types) or funding_rule_hit:
                key = (category, business_models[0] if business_models else "融资计划待明确", markets[0] if markets else "市场阶段待定", "funding")
                self._register_pattern(families["Funding_Stage_Fit_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"BusinessModelAspect::{business_models[0] if business_models else '融资计划待明确'}", f"Market::{markets[0] if markets else '市场阶段待定'}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in funding_targets][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Financial Logic", "Business Model Consistency"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目在种子期就画A轮的饼，评委只会觉得你不落地。先证明PMF再谈融资。",
                    "retrieval_reason": "商业模式与市场阶段的融资节奏分析。",
                })

            if stakeholders and solutions and innovations:
                key = (category, stakeholders[0], solutions[0], innovations[0], "switch")
                self._register_pattern(families["Switching_Cost_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"Stakeholder::{stakeholders[0]}", f"Solution::{solutions[0]}", f"InnovationPoint::{innovations[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H16", "H17"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Innovation & Differentiation", "User Evidence Strength"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目用户现在的做法虽然不完美但免费或已习惯。你凭什么让他们花时间学你的新工具？切换成本是多少？",
                    "retrieval_reason": "用户、方案与创新的切换成本分析。",
                })

            if stakeholders and solutions and markets and business_models:
                key = (category, stakeholders[0], solutions[0], markets[0], "neteffect")
                self._register_pattern(families["Network_Effect_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"Stakeholder::{stakeholders[0]}", f"Solution::{solutions[0]}", f"Market::{markets[0]}", f"BusinessModelAspect::{business_models[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H7", "H9"}][:4],
                    "rubrics": [rb for rb in covered_rubrics if rb in {"Innovation & Differentiation", "Market & Competition"}],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目声称有网络效应——但真正的网络效应是用户越多产品越好用，不是用户越多数据越多。请证明因果链。",
                    "retrieval_reason": "用户、方案与市场的网络效应增长逻辑分析。",
                })

            if solutions and stakeholders and business_models and markets:
                key = (category, solutions[0], stakeholders[0], business_models[0], markets[0], "coherence")
                self._register_pattern(families["Cross_Dimension_Coherence_Edge"], key, {
                    **base_pattern_meta, "category": category,
                    "node_set": {f"Category::{category}", f"Solution::{solutions[0]}", f"Stakeholder::{stakeholders[0]}", f"BusinessModelAspect::{business_models[0]}", f"Market::{markets[0]}"},
                    "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H14"}][:4],
                    "rubrics": covered_rubrics[:3],
                    "evidence_quotes": evidence_quotes[:2],
                    "teaching_note": f"{category}类项目你的目标用户、解决方案、商业模式和市场定位之间讲的是同一个故事吗？评委会检查叙事一致性。",
                    "retrieval_reason": "多维度之间叙事一致性与逻辑自洽分析。",
                })

            if stakeholders and pains and evidence_types:
                _text_blob = " ".join([str(s) for s in pains + solutions + (markets or [])])
                _has_social = any(k in _text_blob for k in ["公益", "社会", "ESG", "乡村", "扶贫", "助农", "环保", "可持续发展"])
                if _has_social:
                    key = (category, stakeholders[0], pains[0], "esg")
                    self._register_pattern(families["ESG_Measurability_Edge"], key, {
                        **base_pattern_meta, "category": category,
                        "node_set": {f"Category::{category}", f"Stakeholder::{stakeholders[0]}", f"PainPoint::{pains[0]}", f"EvidenceType::{evidence_types[0]}"},
                        "rules": [rid for rid in rule_ids if self._canonical_rule_id(rid) in {"H5", "H13"}][:4],
                        "rubrics": covered_rubrics[:2],
                        "evidence_quotes": evidence_quotes[:2],
                        "teaching_note": f"{category}类项目说'帮助了很多人'不够——评委要看'帮助了多少人、改善了多少、用什么指标衡量'。",
                        "retrieval_reason": "社会影响的可量化与可验证分析。",
                    })

        for row in ontology_rows:
            ontology_name = str(row.get("ontology_name") or "未知本体")
            ontology_id = str(row.get("ontology_id") or ontology_name)
            instance_name = str(row.get("instance_name") or "").strip()
            instance_label = str(row.get("instance_label") or "实例")
            categories = self._unique_texts(list(row.get("categories") or []), max_items=3)
            support = int(row.get("support") or 0)
            if not instance_name or support < min_pattern_support:
                continue
            category = categories[0] if categories else "跨类别"
            key = (ontology_id, instance_name, tuple(categories))
            self._register_pattern(
                families["Ontology_Grounded_Edge"],
                key,
                {
                    "source_project_id": "",
                    "confidence": 0.0,
                    "stage_scope": "知识库",
                    "category": category,
                    "node_set": {f"OntologyNode::{ontology_name}", f"{instance_label}::{instance_name}"} | {f"Category::{c}" for c in categories},
                    "rules": [],
                    "rubrics": [],
                    "evidence_quotes": [],
                    "teaching_note": f"本体概念“{ontology_name}”在真实案例中常落地为“{instance_name}”等表述。",
                    "retrieval_reason": "教学本体与实例表达被打通，适合做概念落地解释。",
                },
            )
            families["Ontology_Grounded_Edge"][key]["support"] = support

        total_budget = max_edges
        created_counts: Counter[str] = Counter()
        available_counts: dict[str, int] = {}
        for edge_type, target_count in EDGE_TARGET_COUNTS.items():
            patterns = list(families[edge_type].values())
            eligible = [p for p in patterns if int(p.get("support", 0)) >= min_pattern_support]
            available_counts[edge_type] = len(eligible)
            eligible.sort(key=lambda item: (int(item.get("support", 0)), len(item.get("node_set", []))), reverse=True)
            count = 0
            for payload in eligible:
                if total_budget <= 0 or count >= target_count:
                    break
                self._add_record(edge_to_nodes, records, edge_type, payload)
                count += 1
                total_budget -= 1
            created_counts[edge_type] = count
            logger.info("Hypergraph edge type %s: %d available, %d created (target=%d)",
                        edge_type, len(eligible), count, target_count)

        self._hypergraph = hnx.Hypergraph(edge_to_nodes) if edge_to_nodes else hnx.Hypergraph({})
        self._records = records
        persist_result = self.graph_service.persist_hypergraph_records(
            [self._record_to_dict(rec) for rec in records],
            version="v2",
        )
        return {
            "ok": True,
            "created": dict(created_counts),
            "available_patterns": available_counts,
            "total_nodes": len(self._hypergraph.nodes) if self._hypergraph else 0,
            "total_edges": len(self._hypergraph.edges) if self._hypergraph else 0,
            "persisted": persist_result,
            "notes": "HyperNetX 超图已重建（基于 Neo4j 当前案例库构建多类教学超边）。",
        }

    def _build_insight_summary(self, edges: list[dict[str, Any]], topology: dict[str, Any], safe_edge_types: list[str]) -> tuple[str, list[str], list[str]]:
        if not edges:
            return "当前未检索到可用的教学超边。", [], []
        edge_labels = [EDGE_FAMILY_LABELS.get(str(edge.get("type", "")), str(edge.get("type", ""))) for edge in edges[:3]]
        hubs = [str(item.get("node", "")).split("::", 1)[-1] for item in (topology.get("hub_nodes") or [])[:3] if str(item.get("node", "")).strip()]
        key_dimensions = []
        for edge in edges[:4]:
            for node in edge.get("nodes", []) or []:
                node_text = str(node)
                if "::" in node_text:
                    dim = node_text.split("::", 1)[0]
                    if dim not in key_dimensions:
                        key_dimensions.append(dim)
        top_signals = [
            f"优先命中的超边类型：{'、'.join(edge_labels)}",
            f"当前高连接节点：{'、'.join(hubs)}" if hubs else "",
            f"当前偏好的超边族：{'、'.join(safe_edge_types)}" if safe_edge_types else "",
        ]
        top_signals = [x for x in top_signals if x][:4]
        summary = f"本轮超图主要命中了{'、'.join(edge_labels)}，说明当前问题更集中在{'、'.join(key_dimensions[:4]) or '关键维度联动'}。"
        return summary, top_signals, key_dimensions[:6]

    # ═══════════════════════════════════════════════════
    #  2. Query existing hypergraph for teaching insights
    # ═══════════════════════════════════════════════════

    def insight(
        self,
        category: str | None = None,
        rule_ids: list[str] | None = None,
        preferred_edge_types: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        if not self._records:
            rebuilt = self.rebuild(min_pattern_support=1, max_edges=400)
            if not rebuilt.get("ok"):
                return {"ok": False, "edges": [], "error": rebuilt.get("error", "rebuild failed")}

        safe_rules = [str(x) for x in (rule_ids or []) if x]
        safe_edge_types = [str(x) for x in (preferred_edge_types or []) if x]
        expanded_rules: set[str] = set(safe_rules)
        for rid in safe_rules:
            for alias in self._rule_alias.get(rid, []):
                expanded_rules.add(alias)

        matched: list[tuple[float, dict[str, Any]]] = []
        for rec in self._records:
            cat_hit = bool(category and rec.category and rec.category == category)
            rule_hit = any(r in rec.rules for r in expanded_rules) if expanded_rules else False
            type_hit = rec.type in safe_edge_types if safe_edge_types else False
            if (not category and not safe_rules and not safe_edge_types) or cat_hit or rule_hit or type_hit:
                score = 0.0
                if cat_hit:
                    score += 2.0
                if rule_hit:
                    score += 3.0
                if type_hit:
                    score += 1.8
                score += min(2.0, rec.support / 5)
                matched.append((score, {
                    "hyperedge_id": rec.hyperedge_id,
                    "type": rec.type,
                    "family_label": EDGE_FAMILY_LABELS.get(rec.type, rec.type),
                    "support": rec.support,
                    "teaching_note": rec.teaching_note,
                    "categories": [rec.category] if rec.category else [],
                    "rules": rec.rules,
                    "rubrics": rec.rubrics,
                    "evidence_quotes": rec.evidence_quotes,
                    "retrieval_reason": rec.retrieval_reason,
                    "nodes": sorted(rec.node_set) if rec.node_set else [],
                    "member_nodes": rec.member_nodes,
                    "source_project_ids": rec.source_project_ids,
                    "confidence": rec.confidence,
                    "severity": rec.severity,
                    "score_impact": rec.score_impact,
                    "stage_scope": rec.stage_scope,
                    "match_score": round(score, 2),
                }))

        matched.sort(key=lambda item: item[0], reverse=True)

        topology = self._get_topology_stats()
        limited_edges = [item for _, item in matched[:max(1, min(limit, 30))]]
        summary, top_signals, key_dimensions = self._build_insight_summary(limited_edges, topology, safe_edge_types)

        return {
            "ok": True,
            "summary": summary,
            "top_signals": top_signals,
            "key_dimensions": key_dimensions,
            "edges": limited_edges,
            "matched_by": {
                "category": category,
                "rule_ids": safe_rules,
                "expanded_rule_ids": sorted(expanded_rules),
                "preferred_edge_types": safe_edge_types,
            },
            "topology": topology,
            "meta": {
                "engine": "hypernetx",
                "edge_count": len(self._records),
                "node_count": len(self._hypergraph.nodes) if self._hypergraph else 0,
                "family_counts": dict(self._family_counts),
            },
        }

    def summary(self) -> dict[str, Any]:
        """Quick stats about the in-memory hypergraph."""
        return {
            "edge_count": len(self._records),
            "node_count": len(self._hypergraph.nodes) if self._hypergraph else 0,
            "family_counts": dict(self._family_counts),
            "rebuilt": len(self._records) > 0,
        }

    # ── In-memory hypergraph → force-graph viz data ───────────
    _FAMILY_COLORS: dict[str, str] = {
        "Risk_Pattern_Edge": "#ef4444",
        "Value_Loop_Edge": "#f59e0b",
        "User_Pain_Fit_Edge": "#fb923c",
        "Evidence_Grounding_Edge": "#22d3ee",
        "Execution_Gap_Edge": "#a78bfa",
        "Market_Competition_Edge": "#60a5fa",
        "Compliance_Safety_Edge": "#f472b6",
        "Innovation_Validation_Edge": "#34d399",
        "Pricing_Unit_Economics_Edge": "#fbbf24",
        "Substitute_Migration_Edge": "#94a3b8",
        "Trust_Adoption_Edge": "#38bdf8",
        "Retention_Workflow_Embed_Edge": "#c084fc",
        "Stage_Goal_Fit_Edge": "#4ade80",
        "Rule_Rubric_Tension_Edge": "#fb7185",
        "Ontology_Grounded_Edge": "#2dd4bf",
        "Team_Capability_Gap_Edge": "#e879f9",
        "User_Journey_Edge": "#fca5a5",
        "Social_Impact_Edge": "#86efac",
        "Data_Flywheel_Edge": "#7dd3fc",
        "Scalability_Bottleneck_Edge": "#fdba74",
        "IP_Moat_Edge": "#d8b4fe",
        "Pivot_Signal_Edge": "#fde68a",
        "Cost_Structure_Edge": "#bef264",
        "Ecosystem_Dependency_Edge": "#67e8f9",
        "MVP_Scope_Edge": "#fda4af",
        "Stakeholder_Conflict_Edge": "#a5b4fc",
        "Channel_Conversion_Edge": "#99f6e4",
        "Regulatory_Landscape_Edge": "#fed7aa",
        "Presentation_Narrative_Edge": "#c4b5fd",
        "Resource_Leverage_Edge": "#bbf7d0",
        "Timing_Window_Edge": "#fef08a",
        "Revenue_Sustainability_Edge": "#bae6fd",
        "Demand_Supply_Match_Edge": "#e9d5ff",
        "Founder_Risk_Edge": "#fecaca",
        "Ethical_Bias_Edge": "#d9f99d",
        "Assumption_Stack_Edge": "#a5f3fc",
        "Metric_Definition_Edge": "#ddd6fe",
        "Market_Segmentation_Edge": "#fbcfe8",
        "Competitive_Response_Edge": "#ccfbf1",
        "Milestone_Dependency_Edge": "#fef9c3",
        "Funding_Stage_Fit_Edge": "#e0e7ff",
        "Switching_Cost_Edge": "#cffafe",
        "Network_Effect_Edge": "#ede9fe",
        "Cross_Dimension_Coherence_Edge": "#fce7f3",
        "ESG_Measurability_Edge": "#ecfccb",
    }

    def get_viz_data(self) -> dict[str, Any]:
        """Build force-graph data directly from in-memory _records (no Neo4j).

        All RiskRules (H1-H27) and RubricItems (9 dimensions) are sourced from
        the local diagnosis_engine definitions, not Neo4j.
        """
        if not self._records:
            rebuilt = self.rebuild(min_pattern_support=1, max_edges=400)
            if not rebuilt.get("ok"):
                return {"graph": {"nodes": [], "links": []}, "stats": {}, "error": "rebuild failed"}

        from app.services.diagnosis_engine import RULE_FALLACY_MAP, RUBRICS
        from collections import Counter

        nodes: list[dict] = []
        links: list[dict] = []
        node_set: set[str] = set()
        seen_links: set[tuple[str, str, str]] = set()

        all_rule_names: dict[str, str] = dict(RULE_FALLACY_MAP)
        all_rubric_names: dict[str, str] = {r["item"]: r["item"] for r in RUBRICS}

        for rid, rname in all_rule_names.items():
            r_id = f"rule_{rid}"
            node_set.add(r_id)
            nodes.append({
                "id": r_id, "name": f"{rid} {rname}",
                "type": "RiskRule", "color": "#ef4444", "size": 5,
            })

        for rub_name in all_rubric_names:
            rb_id = f"rubric_{rub_name}"
            node_set.add(rb_id)
            nodes.append({
                "id": rb_id, "name": rub_name,
                "type": "RubricItem", "color": "#22c55e", "size": 5,
            })

        for rec in self._records:
            he_id = rec.hyperedge_id
            family_color = self._FAMILY_COLORS.get(rec.type, "#f59e0b")
            nodes.append({
                "id": he_id,
                "name": rec.teaching_note or EDGE_FAMILY_LABELS.get(rec.type, rec.type),
                "type": "Hyperedge",
                "family": rec.type,
                "family_label": EDGE_FAMILY_LABELS.get(rec.type, rec.type),
                "color": family_color,
                "size": 6,
                "shape": "rect",
                "support": rec.support,
                "severity": rec.severity,
                "category": rec.category or "",
            })
            node_set.add(he_id)

            for member in rec.member_nodes:
                m_id = member["key"]
                if m_id not in node_set:
                    node_set.add(m_id)
                    nodes.append({
                        "id": m_id,
                        "name": member["display"],
                        "type": "HyperNode",
                        "ntype": member["type"],
                        "color": "#38bdf8",
                        "size": 3,
                    })
                lk = (he_id, m_id, "HAS_MEMBER")
                if lk not in seen_links:
                    seen_links.add(lk)
                    links.append({"source": he_id, "target": m_id, "type": "HAS_MEMBER"})

            all_rules_for_edge: set[str] = set()
            for rid in rec.rules:
                raw = str(rid).strip()
                if raw.startswith("H") and raw[1:].isdigit():
                    all_rules_for_edge.add(raw)
                else:
                    canonical = self._canonical_rule_id(raw)
                    if canonical.startswith("H"):
                        all_rules_for_edge.add(canonical)
            family_meta = self._FAMILY_META.get(rec.type)
            if family_meta:
                all_rules_for_edge.update(family_meta.get("rules", []))
            for rule_id in all_rules_for_edge:
                r_id = f"rule_{rule_id}"
                if r_id not in node_set:
                    continue
                lk = (he_id, r_id, "TRIGGERS_RULE")
                if lk not in seen_links:
                    seen_links.add(lk)
                    links.append({"source": he_id, "target": r_id, "type": "TRIGGERS_RULE"})

            for rubric_id in rec.rubrics:
                rb_id = f"rubric_{rubric_id}"
                if rb_id not in node_set:
                    continue
                lk = (he_id, rb_id, "ALIGNS_WITH")
                if lk not in seen_links:
                    seen_links.add(lk)
                    links.append({"source": he_id, "target": rb_id, "type": "ALIGNS_WITH"})

        rubric_rules_map = {r["item"]: r.get("rules", []) for r in RUBRICS}
        for rub_name, linked_rules in rubric_rules_map.items():
            rb_id = f"rubric_{rub_name}"
            for rid in linked_rules:
                r_id = f"rule_{rid}"
                if r_id in node_set and rb_id in node_set:
                    lk = (r_id, rb_id, "EVALUATED_BY")
                    if lk not in seen_links:
                        seen_links.add(lk)
                        links.append({"source": r_id, "target": rb_id, "type": "EVALUATED_BY"})

        family_counts = Counter(rec.type for rec in self._records)
        return {
            "graph": {"nodes": nodes, "links": links},
            "stats": {
                "total_hyperedges": len(self._records),
                "total_hypernodes": sum(1 for n in nodes if n["type"] == "HyperNode"),
                "total_risk_rules": sum(1 for n in nodes if n["type"] == "RiskRule"),
                "total_rubric_items": sum(1 for n in nodes if n["type"] == "RubricItem"),
                "total_links": len(links),
                "total_families": len(family_counts),
                "family_counts": dict(family_counts),
            },
        }

    def library_snapshot(self, limit: int = 24) -> dict[str, Any]:
        db_snapshot = self.graph_service.hypergraph_library_snapshot(limit=limit)
        if db_snapshot and "error" not in db_snapshot:
            db_edge_count = int(((db_snapshot or {}).get("overview") or {}).get("edge_count") or 0)
            local_edge_count = len(self._records)
            # Prefer the richer local snapshot if memory already holds a rebuilt graph
            # and Neo4j is lagging behind with an older persisted version.
            if db_edge_count >= local_edge_count or local_edge_count == 0:
                return db_snapshot
        if not self._records:
            rebuilt = self.rebuild(min_pattern_support=1, max_edges=400)
            if not rebuilt.get("ok"):
                return {"error": rebuilt.get("error", "rebuild failed")}
        families = Counter(rec.type for rec in self._records)
        return {
            "overview": {
                "edge_count": len(self._records),
                "node_count": len(self._hypergraph.nodes) if self._hypergraph else 0,
                "avg_member_count": round(sum(len(rec.member_nodes) for rec in self._records) / max(1, len(self._records)), 2),
            },
            "families": [
                {
                    "family": family,
                    "label": EDGE_FAMILY_LABELS.get(family, family),
                    "count": count,
                    "avg_support": round(sum(rec.support for rec in self._records if rec.type == family) / max(1, count), 2),
                }
                for family, count in families.most_common()
            ],
            "edges": [self._record_to_dict(rec) for rec in sorted(self._records, key=lambda item: (-item.support, item.type))[:limit]],
        }

    _FAMILY_META: dict[str, dict[str, Any]] = {
        "Value_Loop_Edge": {"desc": "用户→痛点→方案→商业模式形成完整闭环", "type": "ideal", "rules": ["H1", "H2", "H3"]},
        "User_Pain_Fit_Edge": {"desc": "用户群体与痛点的匹配深度", "type": "risk", "rules": ["H1", "H5"]},
        "Risk_Pattern_Edge": {"desc": "跨类别通用的风险模式聚合", "type": "risk", "rules": ["H2", "H3", "H11"]},
        "Evidence_Grounding_Edge": {"desc": "核心主张是否有充分证据支撑", "type": "ideal", "rules": ["H5"]},
        "Market_Competition_Edge": {"desc": "市场定位与竞争格局分析", "type": "risk", "rules": ["H4", "H6"]},
        "Execution_Gap_Edge": {"desc": "执行计划与资源之间的断裂检测", "type": "risk", "rules": ["H10"]},
        "Compliance_Safety_Edge": {"desc": "合规、安全与法律风险检测", "type": "risk", "rules": ["H11"]},
        "Ontology_Grounded_Edge": {"desc": "知识本体概念的实例落地情况", "type": "ideal", "rules": ["H14"]},
        "Innovation_Validation_Edge": {"desc": "创新点是否经过验证而非空想", "type": "ideal", "rules": ["H7"]},
        "Pricing_Unit_Economics_Edge": {"desc": "定价策略与单元经济模型合理性", "type": "risk", "rules": ["H8", "H9"]},
        "Substitute_Migration_Edge": {"desc": "替代方案对用户迁移的影响", "type": "risk", "rules": ["H4", "H17"]},
        "Trust_Adoption_Edge": {"desc": "目标用户的信任建立与采纳路径", "type": "ideal", "rules": ["H16", "H17"]},
        "Retention_Workflow_Embed_Edge": {"desc": "产品嵌入用户工作流的深度", "type": "ideal", "rules": ["H16"]},
        "Stage_Goal_Fit_Edge": {"desc": "当前阶段目标与行动是否一致", "type": "risk", "rules": ["H10", "H13"]},
        "Rule_Rubric_Tension_Edge": {"desc": "风险规则与评分标准之间的张力", "type": "risk", "rules": ["H14"]},
        "Team_Capability_Gap_Edge": {"desc": "团队能力是否匹配技术和执行要求", "type": "risk", "rules": ["H9", "H10"]},
        "User_Journey_Edge": {"desc": "用户旅程从接触到留存的完整闭环", "type": "ideal", "rules": ["H1", "H16"]},
        "Social_Impact_Edge": {"desc": "项目的社会价值链与影响评估", "type": "ideal", "rules": ["H5", "H13"]},
        "Data_Flywheel_Edge": {"desc": "数据驱动的增长飞轮效应", "type": "ideal", "rules": ["H7", "H9"]},
        "Scalability_Bottleneck_Edge": {"desc": "规模化过程中的瓶颈识别", "type": "risk", "rules": ["H9", "H10"]},
        "IP_Moat_Edge": {"desc": "知识产权与技术壁垒的护城河", "type": "ideal", "rules": ["H7"]},
        "Pivot_Signal_Edge": {"desc": "需要转型调整的信号识别", "type": "risk", "rules": ["H5", "H6"]},
        "Cost_Structure_Edge": {"desc": "成本结构的合理性与可持续性", "type": "risk", "rules": ["H8", "H9"]},
        "Ecosystem_Dependency_Edge": {"desc": "对外部生态系统的依赖程度", "type": "risk", "rules": ["H11", "H6"]},
        "MVP_Scope_Edge": {"desc": "最小可行产品的边界与聚焦度", "type": "ideal", "rules": ["H10", "H13"]},
        "Stakeholder_Conflict_Edge": {"desc": "多方利益相关者的冲突检测", "type": "risk", "rules": ["H3", "H11"]},
        "Channel_Conversion_Edge": {"desc": "渠道到转化的漏斗效率分析", "type": "risk", "rules": ["H8", "H16"]},
        "Regulatory_Landscape_Edge": {"desc": "政策法规环境对项目的影响", "type": "risk", "rules": ["H11"]},
        "Presentation_Narrative_Edge": {"desc": "路演叙事线的结构与说服力", "type": "ideal", "rules": ["H14"]},
        "Resource_Leverage_Edge": {"desc": "现有资源的杠杆利用效率", "type": "ideal", "rules": ["H9", "H10"]},
        "Timing_Window_Edge": {"desc": "市场时机与技术成熟度匹配", "type": "risk", "rules": ["H4", "H6"]},
        "Revenue_Sustainability_Edge": {"desc": "收入模型的可持续性而非一次性", "type": "risk", "rules": ["H8", "H26"]},
        "Demand_Supply_Match_Edge": {"desc": "用户需求与产品供给的匹配度", "type": "ideal", "rules": ["H1", "H5"]},
        "Founder_Risk_Edge": {"desc": "关键人物依赖与单点故障风险", "type": "risk", "rules": ["H10", "H21", "H25"]},
        "Ethical_Bias_Edge": {"desc": "AI/算法的公平性与伦理风险", "type": "risk", "rules": ["H11", "H22"]},
        "Assumption_Stack_Edge": {"desc": "项目建立在多少层未验证假设之上", "type": "risk", "rules": ["H5", "H7", "H20"]},
        "Metric_Definition_Edge": {"desc": "成功指标是否清晰可衡量", "type": "ideal", "rules": ["H13", "H20"]},
        "Market_Segmentation_Edge": {"desc": "目标市场的细分聚焦程度", "type": "risk", "rules": ["H1", "H4", "H19"]},
        "Competitive_Response_Edge": {"desc": "竞品或巨头的模仿与反制风险", "type": "risk", "rules": ["H6", "H7", "H16"]},
        "Milestone_Dependency_Edge": {"desc": "里程碑之间的依赖关系与容错空间", "type": "risk", "rules": ["H10", "H21"]},
        "Funding_Stage_Fit_Edge": {"desc": "融资节奏与业务阶段是否匹配", "type": "risk", "rules": ["H9", "H24"]},
        "Switching_Cost_Edge": {"desc": "用户从现有方案迁移的成本", "type": "risk", "rules": ["H16", "H17"]},
        "Network_Effect_Edge": {"desc": "产品是否具备真正的网络效应逻辑", "type": "ideal", "rules": ["H7", "H9"]},
        "Cross_Dimension_Coherence_Edge": {"desc": "项目各维度之间叙述的自洽连贯性", "type": "ideal", "rules": ["H14"]},
        "ESG_Measurability_Edge": {"desc": "社会影响的可量化与可验证程度", "type": "ideal", "rules": ["H5", "H13"]},
        "Data_Privacy_Edge": {"desc": "数据隐私保护与用户数据合规管理", "type": "risk", "rules": ["H11", "H22"]},
        "Industry_Compliance_Edge": {"desc": "行业特定法规与标准的合规检测", "type": "risk", "rules": ["H11"]},
        "Partnership_Network_Edge": {"desc": "合作伙伴网络的广度与协同效应", "type": "ideal", "rules": ["H9", "H6"]},
        "Supply_Chain_Edge": {"desc": "供应链稳定性与弹性评估", "type": "risk", "rules": ["H10", "H11"]},
        "Community_Building_Edge": {"desc": "用户社区构建与社群运营能力", "type": "ideal", "rules": ["H16", "H13"]},
        "Environmental_Impact_Edge": {"desc": "项目环境影响与可持续发展评估", "type": "ideal", "rules": ["H5", "H13"]},
        "Governance_Transparency_Edge": {"desc": "治理结构透明度与决策合规性", "type": "ideal", "rules": ["H11", "H14"]},
        "Problem_Discovery_Edge": {"desc": "问题发现的深度与真实性验证", "type": "ideal", "rules": ["H1", "H5"]},
        "Scenario_Analysis_Edge": {"desc": "用户使用场景的系统化分析", "type": "ideal", "rules": ["H1", "H16"]},
        "Need_Prioritization_Edge": {"desc": "需求优先级的合理排序与聚焦", "type": "ideal", "rules": ["H1", "H13"]},
        "Empathy_Map_Edge": {"desc": "用户同理心地图与情感洞察", "type": "ideal", "rules": ["H1", "H5"]},
        "Insight_Validation_Edge": {"desc": "用户洞察的验证方法与证据强度", "type": "ideal", "rules": ["H5", "H7"]},
        "Ideation_Edge": {"desc": "创意生成的广度与创新性评估", "type": "ideal", "rules": ["H7"]},
        "Concept_Evaluation_Edge": {"desc": "方案概念的多维度评估与筛选", "type": "ideal", "rules": ["H7", "H5"]},
        "Feasibility_Screen_Edge": {"desc": "方案技术与商业可行性初筛", "type": "risk", "rules": ["H7", "H10"]},
        "Design_Thinking_Edge": {"desc": "设计思维流程的完整性与迭代深度", "type": "ideal", "rules": ["H14"]},
        "Solution_Architecture_Edge": {"desc": "解决方案架构的系统性与可扩展性", "type": "ideal", "rules": ["H7", "H9"]},
        "Academic_Transfer_Edge": {"desc": "学术成果向商业应用的转化路径", "type": "ideal", "rules": ["H7", "H5"]},
        "Industry_Academia_Edge": {"desc": "产学研合作的深度与协同机制", "type": "ideal", "rules": ["H9", "H10"]},
        "IP_Commercialization_Edge": {"desc": "知识产权商业化策略与路径", "type": "ideal", "rules": ["H7", "H8"]},
        "Tech_Licensing_Edge": {"desc": "技术许可模式与收益分配合理性", "type": "risk", "rules": ["H8", "H11"]},
        "Research_Application_Edge": {"desc": "研究成果的实际应用场景匹配度", "type": "ideal", "rules": ["H5", "H7"]},
        "Tech_Readiness_Edge": {"desc": "技术成熟度等级与落地准备度评估", "type": "risk", "rules": ["H7", "H10"]},
        "Data_Quality_Edge": {"desc": "数据质量、完整性与可用性评估", "type": "risk", "rules": ["H5", "H7"]},
        "Tech_Debt_Edge": {"desc": "技术债务积累程度与偿还计划", "type": "risk", "rules": ["H10", "H9"]},
        "API_Integration_Edge": {"desc": "系统集成与API生态兼容性", "type": "ideal", "rules": ["H7", "H9"]},
        "Prototype_Validation_Edge": {"desc": "原型验证的覆盖度与用户反馈闭环", "type": "ideal", "rules": ["H5", "H7"]},
        "UX_Research_Edge": {"desc": "用户体验研究的深度与方法科学性", "type": "ideal", "rules": ["H1", "H5"]},
        "Design_Driven_Edge": {"desc": "设计驱动创新的策略与实践落地", "type": "ideal", "rules": ["H7", "H14"]},
        "Accessibility_Edge": {"desc": "产品无障碍设计与包容性评估", "type": "ideal", "rules": ["H13", "H16"]},
        "User_Education_Edge": {"desc": "用户教育与上手引导的完善程度", "type": "ideal", "rules": ["H16", "H17"]},
        "Feedback_Loop_Edge": {"desc": "用户反馈收集与产品迭代闭环机制", "type": "ideal", "rules": ["H5", "H16"]},
    }

    def catalog(self) -> dict[str, Any]:
        """Return the full hypergraph design catalog for visualization."""
        from collections import Counter
        family_counts = Counter(rec.type for rec in self._records) if self._records else Counter()

        families_out = []
        for fam_key, label in EDGE_FAMILY_LABELS.items():
            meta = self._FAMILY_META.get(fam_key, {})
            families_out.append({
                "family": fam_key,
                "label": label,
                "group": _FAMILY_TO_GROUP.get(fam_key, "其他"),
                "pattern_type": meta.get("type", "risk"),
                "description": meta.get("desc", label),
                "linked_rules": meta.get("rules", []),
                "instance_count": family_counts.get(fam_key, 0),
            })

        groups_out = []
        for grp_name, grp_fams in EDGE_FAMILY_GROUPS.items():
            edge_sum = sum(family_counts.get(f, 0) for f in grp_fams)
            groups_out.append({
                "name": grp_name,
                "families": len(grp_fams),
                "edges": edge_sum,
            })

        rules_out = []
        for r in _CONSISTENCY_RULES:
            rules_out.append({
                "id": r["id"],
                "description": r["description"],
                "message": r.get("message", ""),
                "pressure_count": len(r.get("pressure", [])),
            })

        return {
            "families": families_out,
            "groups": groups_out,
            "rules": rules_out,
            "rules_count": len(_CONSISTENCY_RULES),
            "templates_count": len(_HYPEREDGE_TEMPLATES),
            "total_edges": len(self._records) if self._records else 0,
            "total_nodes": len(self._hypergraph.nodes) if self._hypergraph else 0,
            "total_families": len(EDGE_FAMILY_LABELS),
            "rationality": _compute_design_rationality(),
        }

    def project_match_view(self, hypergraph_insight: dict[str, Any], hypergraph_student: dict[str, Any], pressure_trace: dict[str, Any] | None = None) -> dict[str, Any]:
        edges = list((hypergraph_insight or {}).get("edges") or [])
        warnings = list((hypergraph_student or {}).get("pattern_warnings") or [])
        strengths = list((hypergraph_student or {}).get("pattern_strengths") or [])
        missing = list((hypergraph_student or {}).get("missing_dimensions") or [])
        dims_detail = (hypergraph_student or {}).get("dimensions") or {}
        pressure_trace = pressure_trace or {}

        covered_ents: dict[str, list[str]] = {}
        for dim_key, dim_info in dims_detail.items():
            if isinstance(dim_info, dict) and dim_info.get("entities"):
                covered_ents[dim_key] = [str(e) for e in dim_info["entities"][:4]]

        def _ent_summary(dim_key: str) -> str:
            ents = covered_ents.get(dim_key, [])
            if ents:
                return "、".join(ents[:3])
            return ""

        useful_cards: list[dict[str, Any]] = []
        if missing:
            first = missing[0]
            dim_name = first.get("dimension", "")
            reason = first.get("recommendation", "")
            existing = []
            for dk, ev in covered_ents.items():
                if ev:
                    existing.append(f"{dk}({', '.join(ev[:2])})")
            existing_hint = "、".join(existing[:3]) if existing else "暂无"
            useful_cards.append({
                "title": f"优先补充：{dim_name}",
                "summary": reason if reason else f"你的项目目前还缺少「{dim_name}」方面的信息",
                "reason": f"你已经提到了 {existing_hint}，但「{dim_name}」这个维度还是空白。评委通常会在这里追问。" if existing else reason,
                "project_hint": f"建议接下来聊一聊{dim_name}相关的内容，让项目的这个环节也能立住。",
                "importance": first.get("importance", ""),
                "tone": "gap",
            })
        if warnings:
            first = warnings[0]
            warn_text = first.get("warning", "")
            matched_rules = first.get("matched_rules", [])
            rules_hint = "、".join(str(r) for r in matched_rules[:3]) if matched_rules else ""
            useful_cards.append({
                "title": "需要留意的风险模式",
                "summary": warn_text,
                "reason": f"在 96 个标准案例中，有 {first.get('support', 0)} 个类似项目也触发了同类风险" + (f"（规则 {rules_hint}）" if rules_hint else "") + "。这意味着评委很可能会在这个方向追问。",
                "project_hint": "不必紧张，这说明你的项目已经进入到需要回答深层问题的阶段了。提前准备好这个方向的回应就好。",
                "importance": "高",
                "tone": "risk",
            })
        if strengths:
            first = strengths[0]
            note = first.get("note", "")
            edge_type = first.get("edge_type", "")
            type_labels = {
                "Value_Loop_Edge": "价值闭环", "User_Pain_Fit_Edge": "用户-痛点匹配",
                "Evidence_Grounding_Edge": "证据支撑", "Market_Competition_Edge": "市场竞争分析",
                "Execution_Gap_Edge": "执行路径", "Compliance_Safety_Edge": "合规安全",
                "Innovation_Validation_Edge": "创新验证",
            }
            type_label = type_labels.get(edge_type, edge_type)
            useful_cards.append({
                "title": f"优势结构：{type_label}",
                "summary": note,
                "reason": f"你的项目在「{type_label}」维度上与 {first.get('support', 0)} 个优秀案例呈现相似的结构特征，这是评委看重的亮点。",
                "project_hint": "答辩或计划书中可以主动强调这一点，让评委看到你在这方面的深度思考。",
                "importance": "中",
                "tone": "strength",
            })
        consistency = list((hypergraph_student or {}).get("consistency_issues") or [])
        if consistency and len(useful_cards) < 4:
            ci = consistency[0]
            ci_questions = ci.get("pressure_questions", [])
            useful_cards.append({
                "title": f"一致性检查：{ci.get('description', '逻辑矛盾')}",
                "summary": ci.get("message", ""),
                "reason": f"评委可能会追问：{ci_questions[0]}" if ci_questions else "",
                "project_hint": "检查你在这几个维度之间的描述是否前后一致，确保逻辑链条能自圆其说。",
                "importance": "高",
                "tone": "risk",
            })

        tmpl_matches = list((hypergraph_student or {}).get("template_matches") or [])
        complete_tmpls = [t for t in tmpl_matches if t.get("status") == "complete"]
        partial_tmpls = [t for t in tmpl_matches if t.get("status") == "partial"]
        if complete_tmpls and len(useful_cards) < 5:
            ct = complete_tmpls[0]
            useful_cards.append({
                "title": f"闭环已形成：{ct.get('name', '')}",
                "summary": ct.get("description", ""),
                "reason": f"你的项目已经覆盖了 {', '.join(ct.get('dimensions', []))} 这几个维度，形成了完整的分析闭环。",
                "project_hint": "这是你项目中一个完整的论证链条，答辩时可以沿着这条线展开。",
                "importance": "中",
                "tone": "strength",
            })
        elif partial_tmpls and len(useful_cards) < 5:
            pt = partial_tmpls[0]
            m_dims = pt.get("missing_dimensions", [])
            useful_cards.append({
                "title": f"即将闭环：{pt.get('name', '')}",
                "summary": f"只差 {', '.join(m_dims)} 就能形成完整闭环",
                "reason": pt.get("description", ""),
                "project_hint": f"补上这{'几个' if len(m_dims) > 1 else '一个'}维度，这条论证链就完整了。",
                "importance": "高",
                "tone": "gap",
            })

        process_trace = {
            "fallacy_label": pressure_trace.get("fallacy_label", ""),
            "selected_strategy": pressure_trace.get("selected_strategy", ""),
            "generated_question": pressure_trace.get("generated_question", ""),
            "edge_families": [str(edge.get("family_label") or edge.get("type") or "") for edge in edges[:12]],
            "matched_rules": sorted({str(rule) for edge in edges[:12] for rule in (edge.get("rules") or []) if str(rule).strip()})[:16],
        }
        return {
            "summary": (hypergraph_insight or {}).get("summary", ""),
            "process_trace": process_trace,
            "useful_cards": useful_cards[:5],
            "matched_edges": edges[:20],
            "library_overview": self.library_snapshot(limit=12).get("overview", {}),
        }

    def _get_topology_stats(self) -> dict[str, Any]:
        """Extract topology statistics from the built hypergraph."""
        if not self._hypergraph or len(self._hypergraph.edges) == 0:
            return {}
        try:
            hg = self._hypergraph
            node_degrees = {}
            for node in list(hg.nodes)[:20]:
                try:
                    memberships = hg.nodes.memberships[node]
                    node_degrees[str(node)] = len(memberships)
                except Exception:
                    pass

            edge_sizes = {}
            for edge in list(hg.edges)[:20]:
                try:
                    edge_sizes[str(edge)] = len(hg.edges[edge])
                except Exception:
                    pass

            hub_nodes = sorted(node_degrees.items(), key=lambda x: -x[1])[:5]

            return {
                "hub_nodes": [{"node": n, "degree": d, "interpretation": self._interpret_hub(n, d)} for n, d in hub_nodes],
                "avg_edge_size": round(sum(edge_sizes.values()) / max(1, len(edge_sizes)), 1) if edge_sizes else 0,
                "max_edge_size": max(edge_sizes.values()) if edge_sizes else 0,
                "family_leaderboard": [
                    {"type": edge_type, "label": EDGE_FAMILY_LABELS.get(edge_type, edge_type), "count": count}
                    for edge_type, count in sorted(self._family_counts.items(), key=lambda item: (-item[1], item[0]))[:6]
                ],
            }
        except Exception as exc:
            logger.warning("Topology stats extraction failed: %s", exc)
            return {}

    @staticmethod
    def _interpret_hub(node: str, degree: int) -> str:
        """Generate a human-readable interpretation of a hub node."""
        if "::" in node:
            ntype, name = node.split("::", 1)
        else:
            ntype, name = "Unknown", node

        if ntype == "RiskRule":
            return f"风险规则「{name}」关联{degree}种模式，是最普遍的问题"
        elif ntype == "Category":
            return f"「{name}」类别出现在{degree}种超边中，是最活跃的赛道"
        elif ntype == "Stakeholder":
            return f"目标用户「{name}」被{degree}种模式共享，是高频用户群"
        elif ntype == "PainPoint":
            return f"痛点「{name}」连接了{degree}种模式，是高频真实问题"
        elif ntype == "Market":
            return f"市场「{name}」涉及{degree}种模式，是热门目标市场"
        elif ntype == "RubricItem":
            return f"评分维度「{name}」被{degree}种模式反复命中，是重要教学检查点"
        return f"节点「{name}」关联{degree}种模式"

    # ═══════════════════════════════════════════════════
    #  3. Student content dynamic hypergraph analysis
    # ═══════════════════════════════════════════════════

    def analyze_student_content(
        self,
        entities: list[dict],
        relationships: list[dict],
        structural_gaps: list[str] | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        """
        Build a temporary hypergraph from student's KG entities and perform
        cross-dimensional pattern discovery.

        Returns structured insights about the student's project:
        - Dimension coverage (which key areas are addressed)
        - Cross-dimensional connections (which entities bridge multiple dimensions)
        - Missing dimensions (gaps that weaken the project)
        - Pattern matches with known good/bad patterns from teaching hypergraph
        """
        if not entities:
            return {
                "ok": False,
                "dimensions": {},
                "cross_links": [],
                "coverage_score": 0,
                "pattern_warnings": [],
                "pattern_strengths": [],
                "projected_edge_types": [],
                "missing_dimensions": ["无法分析：未提取到实体"],
            }

        dim_entities: dict[str, list[str]] = defaultdict(list)
        entity_map: dict[str, str] = {}
        raw_text_fragments: list[str] = []
        for e in entities:
            etype = str(e.get("type", "other")).lower()
            label = str(e.get("label", ""))
            eid = str(e.get("id", label))
            dim_entities[etype].append(label)
            entity_map[eid] = etype
            if label:
                raw_text_fragments.append(label)

        # Build student hypergraph edges
        student_edges: dict[str, set[str]] = {}

        for dim, ents in dim_entities.items():
            if ents:
                edge_id = f"dim_{dim}"
                student_edges[edge_id] = {f"{dim}::{e}" for e in ents}

        projected_edge_types: list[str] = []
        if dim_entities.get("stakeholder") and dim_entities.get("pain_point") and dim_entities.get("solution"):
            projected_edge_types.append("User_Pain_Fit_Edge")
        if dim_entities.get("pain_point") and dim_entities.get("solution") and dim_entities.get("business_model"):
            projected_edge_types.append("Value_Loop_Edge")
        if dim_entities.get("market") or dim_entities.get("competitor"):
            projected_edge_types.append("Market_Competition_Edge")
        if dim_entities.get("evidence"):
            projected_edge_types.append("Evidence_Grounding_Edge")
        if dim_entities.get("execution_step") or dim_entities.get("team"):
            projected_edge_types.append("Execution_Gap_Edge")
        if dim_entities.get("risk_control"):
            projected_edge_types.append("Compliance_Safety_Edge")
        if dim_entities.get("innovation"):
            projected_edge_types.append("Innovation_Validation_Edge")

        for rel in relationships:
            src = str(rel.get("source", ""))
            tgt = str(rel.get("target", ""))
            src_type = entity_map.get(src, "other")
            tgt_type = entity_map.get(tgt, "other")
            if src_type != tgt_type:
                edge_id = f"cross_{src}_{tgt}"
                student_edges[edge_id] = {f"{src_type}::{src}", f"{tgt_type}::{tgt}"}

        try:
            student_hg = hnx.Hypergraph(student_edges) if student_edges else None
        except Exception:
            student_hg = None

        # ── Dimension coverage analysis ──
        covered_dims = set(dim_entities.keys()) & set(DIMENSIONS.keys())
        all_dims = set(DIMENSIONS.keys())
        missing_dims = all_dims - covered_dims
        missing_dims_list = list(missing_dims)
        coverage_score = round(len(covered_dims) / max(1, len(all_dims)) * 10, 1)

        dimensions_detail = {}
        for dim, display_name in DIMENSIONS.items():
            ents = dim_entities.get(dim, [])
            dimensions_detail[dim] = {
                "name": display_name,
                "covered": len(ents) > 0,
                "entities": ents[:5],
                "count": len(ents),
            }

        # ── Cross-dimensional connections ──
        cross_links = []
        for rel in relationships:
            src = str(rel.get("source", ""))
            tgt = str(rel.get("target", ""))
            src_type = entity_map.get(src, "other")
            tgt_type = entity_map.get(tgt, "other")
            if src_type != tgt_type and src_type in DIMENSIONS and tgt_type in DIMENSIONS:
                cross_links.append({
                    "from_dim": DIMENSIONS[src_type],
                    "to_dim": DIMENSIONS[tgt_type],
                    "from_entity": src,
                    "to_entity": tgt,
                    "relation": str(rel.get("relation", "")),
                })

        # ── Hub entity analysis (using HyperNetX topology) ──
        hub_entities = []
        if student_hg and len(student_hg.nodes) > 0:
            try:
                for node in list(student_hg.nodes)[:30]:
                    try:
                        memberships = student_hg.nodes.memberships[node]
                        deg = len(memberships)
                    except Exception:
                        deg = 0
                    if deg >= 2:
                        node_str = str(node)
                        if "::" in node_str:
                            ntype, nname = node_str.split("::", 1)
                        else:
                            ntype, nname = "other", node_str
                        hub_entities.append({
                            "entity": nname, "type": ntype, "connections": deg,
                            "note": f"「{nname}」连接{deg}个维度，是项目的核心支撑点",
                        })
                hub_entities.sort(key=lambda x: -x["connections"])
            except Exception:
                pass

        # ── Pattern matching against teaching hypergraph ──
        pattern_warnings = []
        pattern_strengths = []
        if self._records:
            student_rule_like: set[str] = set()
            if not dim_entities.get("stakeholder"):
                student_rule_like.add("weak_user_evidence")
            elif len(dim_entities.get("stakeholder", [])) == 1:
                student_rule_like.add("weak_user_evidence")
            if not dim_entities.get("competitor"):
                student_rule_like.add("no_competitor_claim")
            if not dim_entities.get("market"):
                student_rule_like.add("market_size_fallacy")
            if not dim_entities.get("evidence"):
                student_rule_like.add("evidence_weak")
            if not dim_entities.get("execution_step"):
                student_rule_like.add("no_execution_plan")
            if not dim_entities.get("team"):
                student_rule_like.add("no_team_info")
            if not dim_entities.get("risk_control"):
                student_rule_like.add("no_risk_control")
            if not dim_entities.get("innovation"):
                student_rule_like.add("no_innovation")
            if not dim_entities.get("business_model"):
                student_rule_like.add("unit_economics_not_proven")

            _expanded_student = set(self._expand_rule_ids(list(student_rule_like), max_items=24))
            _gap_keywords = {g.replace("缺少", "").replace("缺", "") for g in (structural_gaps or []) if isinstance(g, str)}

            _dim_label_map = {
                "stakeholder": "目标用户", "pain_point": "痛点问题", "solution": "解决方案",
                "innovation": "创新点", "market": "目标市场", "competitor": "竞争格局",
                "business_model": "商业模式", "execution_step": "执行步骤",
                "risk_control": "风控合规", "evidence": "证据支撑",
                "technology": "技术路线", "resource": "资源优势", "team": "团队能力",
            }
            _present_dims_text = "、".join(
                f"{_dim_label_map.get(k, k)}({', '.join(v[:2])})"
                for k, v in dim_entities.items() if v
            )
            _missing_dims_text = "、".join(
                _dim_label_map.get(d, d) for d in missing_dims_list[:4]
            )

            for rec in self._records:
                if rec.type == "Risk_Pattern_Edge":
                    overlap = _expanded_student & set(rec.rules)
                    if not overlap and rec.teaching_note and _gap_keywords:
                        _note_lower = str(rec.teaching_note).lower()
                        if any(kw in _note_lower for kw in _gap_keywords if len(kw) >= 2):
                            overlap = {"keyword_match"}
                    if overlap and (not category or rec.category == category or not rec.category):
                        ctx_parts = []
                        if _missing_dims_text:
                            ctx_parts.append(f"你的项目目前缺少 {_missing_dims_text}")
                        if _present_dims_text:
                            ctx_parts.append(f"已有 {_present_dims_text}")
                        pattern_warnings.append({
                            "pattern_id": rec.hyperedge_id,
                            "warning": rec.teaching_note,
                            "matched_rules": sorted(overlap),
                            "support": rec.support,
                            "edge_type": rec.type,
                            "project_context": "；".join(ctx_parts) if ctx_parts else "",
                            "family_label": getattr(rec, "family_label", "") or EDGE_FAMILY_LABELS.get(rec.type, rec.type),
                        })
                elif rec.type in {"Value_Loop_Edge", "User_Pain_Fit_Edge", "Evidence_Grounding_Edge"}:
                    if category and rec.category == category and coverage_score >= 6:
                        related_ents = []
                        for d in ["stakeholder", "pain_point", "solution", "evidence"]:
                            related_ents.extend(dim_entities.get(d, [])[:2])
                        pattern_strengths.append({
                            "pattern_id": rec.hyperedge_id,
                            "note": rec.teaching_note,
                            "support": rec.support,
                            "edge_type": rec.type,
                            "related_entities": related_ents[:4],
                            "family_label": getattr(rec, "family_label", "") or EDGE_FAMILY_LABELS.get(rec.type, rec.type),
                        })
                elif rec.type in {"Market_Competition_Edge", "Execution_Gap_Edge", "Compliance_Safety_Edge", "Innovation_Validation_Edge"}:
                    if (not category or rec.category == category):
                        related_ents = []
                        for d in dim_entities:
                            related_ents.extend(dim_entities[d][:1])
                        pattern_strengths.append({
                            "pattern_id": rec.hyperedge_id,
                            "note": rec.teaching_note,
                            "support": rec.support,
                            "edge_type": rec.type,
                            "related_entities": related_ents[:4],
                            "family_label": getattr(rec, "family_label", "") or EDGE_FAMILY_LABELS.get(rec.type, rec.type),
                        })

        # ── Missing dimension recommendations (with project-specific hints) ──
        missing_recommendations = []
        _covered_summary = [
            f"{DIMENSIONS.get(k, k)}（{', '.join(v[:2])}）"
            for k, v in dim_entities.items() if v
        ]
        _covered_text = "、".join(_covered_summary[:4]) if _covered_summary else ""

        gap_importance: dict[str, tuple[str, str, str]] = {
            "stakeholder": ("极高", "缺少明确的目标用户画像，评委会质疑'你为谁解决问题'",
                            "试着描述一下：你想帮谁？他们是谁？在什么场景下遇到了什么困难？"),
            "pain_point": ("极高", "没有清晰的痛点描述，项目缺乏存在的理由",
                           "能不能用一两句话说清楚：用户最头疼的问题是什么？现在他们怎么解决？"),
            "solution": ("高", "缺少具体的解决方案描述",
                         "用户的问题你打算怎么解决？核心功能是什么？和现有方案有什么不同？"),
            "market": ("高", "没有市场分析，无法评估商业可行性",
                       "你的目标市场有多大？用户群体的规模大致是多少？可以引用公开数据。"),
            "competitor": ("中", "缺少竞争分析，评委会问'为什么是你'",
                           "市面上有没有类似的产品？它们做得好的地方和不足分别是什么？"),
            "business_model": ("中", "商业模式不清晰，盈利路径不明",
                               "你打算怎么赚钱？（订阅、交易抽成、广告、SaaS…）定价逻辑是什么？"),
            "technology": ("中", "技术路线未说明，可行性存疑",
                           "用什么技术栈？核心算法或架构是怎样的？有没有技术壁垒？"),
            "resource": ("低", "未提及资源优势，但可后续补充",
                         "你有没有独特的资源？比如数据、导师支持、行业人脉等。"),
            "team": ("低", "团队信息缺失，但非必须一开始就有",
                     "团队成员有谁？各自负责什么？有没有互补的能力？"),
        }
        for dim in missing_dims_list:
            if dim in gap_importance:
                importance, reason, hint = gap_importance[dim]
                rec_text = reason
                if _covered_text:
                    rec_text += f"。你已经提到了 {_covered_text}，但「{DIMENSIONS.get(dim, dim)}」还需要补上。"
                missing_recommendations.append({
                    "dimension": DIMENSIONS.get(dim, dim),
                    "importance": importance,
                    "recommendation": rec_text,
                    "action_hint": hint,
                })
        if structural_gaps:
            for gap in structural_gaps[:3]:
                missing_recommendations.append({
                    "dimension": "结构性",
                    "importance": "高",
                    "recommendation": gap,
                    "action_hint": "检查项目中相关维度之间的逻辑连接是否完整。",
                })
        missing_recommendations.sort(
            key=lambda x: {"极高": 0, "高": 1, "中": 2, "低": 3}.get(x["importance"], 4)
        )

        # ── Template-based loop coverage (using declarative templates) ──
        template_matches: list[dict[str, Any]] = []
        dim_presence = {k: bool(v) for k, v in dim_entities.items()}
        for tmpl in self._edge_templates:
            dims = tmpl.get("dimensions", [])
            missing_t = [d for d in dims if not dim_presence.get(d)]
            status = "complete" if not missing_t else ("partial" if len(missing_t) < len(dims) else "missing")
            template_matches.append({
                "id": tmpl.get("id"),
                "name": tmpl.get("name"),
                "description": tmpl.get("description"),
                "dimensions": dims,
                "missing_dimensions": missing_t,
                "status": status,
                "pattern_type": tmpl.get("pattern_type", "neutral"),
                "linked_rules": list(tmpl.get("linked_rules", [])),
            })

        # ── Consistency rules over dimensions + raw text ──
        consistency_issues: list[dict[str, Any]] = []
        text_ctx = " ".join(raw_text_fragments)
        rule_env = {
            "text": [text_ctx],
        }
        for rule in self._consistency_rules:
            pred: Callable[[dict, dict], bool] = rule.get("predicate")  # type: ignore[assignment]
            try:
                if callable(pred) and pred(dim_presence, rule_env):
                    consistency_issues.append({
                        "id": rule.get("id"),
                        "description": rule.get("description"),
                        "message": rule.get("message"),
                        "pressure_questions": list(rule.get("pressure", [])),
                    })
            except Exception:
                continue

        return {
            "ok": True,
            "coverage_score": coverage_score,
            "covered_count": len(covered_dims),
            "total_dimensions": len(all_dims),
            "dimensions": dimensions_detail,
            "cross_links": cross_links[:10],
            "hub_entities": hub_entities[:5],
            "pattern_warnings": pattern_warnings[:5],
            "pattern_strengths": pattern_strengths[:3],
            "projected_edge_types": projected_edge_types,
            "missing_dimensions": missing_recommendations[:6],
            "template_matches": template_matches,
            "consistency_issues": consistency_issues,
            "student_graph_stats": {
                "nodes": len(student_hg.nodes) if student_hg else 0,
                "edges": len(student_hg.edges) if student_hg else 0,
            },
            "quality_metrics": _compute_quality_metrics(
                dim_entities, cross_links, template_matches,
                consistency_issues, hub_entities,
                list(entity_map.values()) if 'entity_map' in dir() else entities,
                relationships,
            ),
        }
