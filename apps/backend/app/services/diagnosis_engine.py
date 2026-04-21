from dataclasses import dataclass
import json
import logging
import re
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)
from app.services.kg_ontology import (
    get_rule_ontology_nodes,
    get_rule_tasks,
    get_rubric_error_pool,
    get_rubric_evidence_chain,
)
# ─────────────────────────────────────────────────────
# 规则 → 归属 agent（用于证据链追溯，前端显示「哪位智能体做的推断」）
# 无强依赖；按 RULE_EDGE_MAP 的家族主要领域粗映射。
# ─────────────────────────────────────────────────────
RULE_AGENT_MAP: dict[str, str] = {
    "H1": "用户痛点 Agent", "H5": "用户痛点 Agent", "H23": "创新挖掘 Agent",
    "H2": "渠道运营 Agent", "H18": "增长数据 Agent", "H27": "渠道运营 Agent",
    "H3": "财务商业 Agent", "H8": "财务商业 Agent", "H26": "财务商业 Agent",
    "H4": "市场洞察 Agent", "H19": "市场洞察 Agent",
    "H6": "竞品分析 Agent", "H16": "竞品分析 Agent", "H17": "竞品分析 Agent",
    "H7": "技术方案 Agent", "H12": "技术方案 Agent",
    "H9": "规模验证 Agent",
    "H10": "执行落地 Agent", "H21": "执行落地 Agent", "H24": "执行落地 Agent",
    "H11": "合规风控 Agent", "H22": "合规风控 Agent",
    "H13": "数据洞察 Agent",
    "H14": "表达呈现 Agent",
    "H15": "证据评审 Agent", "H20": "证据评审 Agent",
    "H25": "团队组织 Agent",
}


def _agent_for_rule(rule_id: str) -> str:
    return RULE_AGENT_MAP.get((rule_id or "").upper(), "综合诊断 Agent")


RULES = [
    {"id": "H1", "name": "客户-价值主张错位", "severity": "high", "keywords": ["万能", "所有人", "任何人"],
     "explanation": "你的描述中出现了面向「所有人」的表述。创业项目必须先聚焦到一个明确的核心客群，否则价值主张会失焦、渠道策略无从下手。",
     "fix_hint": "选定1个最具体的目标人群（如'25-35岁一线城市职场妈妈'），重新围绕她的痛点写价值主张。"},
    {"id": "H2", "name": "渠道不可达", "severity": "high", "keywords": ["全靠社交媒体", "自然增长", "裂变即可"],
     "explanation": "获客渠道依赖'自然增长/裂变'缺乏可控性。评委会质疑：如果裂变不起来怎么办？",
     "fix_hint": "列出至少2条可控的付费/合作获客渠道，并估算CAC。"},
    {"id": "H3", "name": "定价无支付意愿证据", "severity": "medium", "keywords": ["定价", "收费"], "requires": ["支付意愿", "愿意付费"],
     "explanation": "提到了定价/收费，但没有提及用户支付意愿验证。定价不能拍脑袋，需要真实调研数据支撑。",
     "fix_hint": "设计一个支付意愿调研（如Van Westendorp价格敏感度测试），收集至少20份有效数据。"},
    {"id": "H4", "name": "TAM/SAM/SOM口径混乱", "severity": "high", "keywords": ["tam", "sam", "som", "市场规模"],
     "explanation": "提到了市场规模相关概念，但TAM/SAM/SOM三层逻辑需要严格区分。很多项目把TAM当SOM用，会被评委秒杀。",
     "fix_hint": "从下往上算：SOM=你第1年能触达的付费用户×客单价，SAM=你的产品理论上能服务的市场，TAM=整个行业规模。"},
    {"id": "H5", "name": "需求证据不足", "severity": "high", "requires": ["访谈", "问卷", "用户证据", "调研", "内测", "使用日志", "点击率", "预约", "转化"],
     "explanation": "你的描述中缺少用户需求验证的证据（如访谈记录、内测数据、预约/点击转化等）。没有证据的需求只是假设。",
     "fix_hint": "先选一种最低成本的验证动作：场景访谈、演示观察、小范围内测、预约页点击测试四选一，用结果证明用户真的在意这个问题。"},
    {"id": "H6", "name": "竞品对比不可比", "severity": "medium", "keywords": ["无竞争对手", "没有对手", "没有竞争对手", "独一无二"],
     "explanation": "声称'没有竞争对手'反而是危险信号——要么市场不存在，要么分析不够深入。",
     "fix_hint": "列出至少3个直接/间接竞品，做功能对比矩阵，标明你的差异化维度。"},
    {"id": "H7", "name": "创新点不可验证", "severity": "high", "keywords": ["创新", "颠覆"], "requires": ["实验", "验证", "对照"],
     "explanation": "提到了创新/颠覆，但缺少验证手段。创新点必须是可验证的，否则就是口号。",
     "fix_hint": "设计一个MVP实验来验证核心创新假设，定义成功指标和对照组。"},
    {"id": "H8", "name": "单位经济不成立", "severity": "high", "keywords": ["cac", "ltv", "获客成本", "复购"],
     "explanation": "涉及了获客成本/复购等概念，但需要确保LTV>CAC，否则越卖越亏。",
     "fix_hint": "建立CAC/LTV/BEP三表：获客成本估算、用户终身价值计算、盈亏平衡时间点。"},
    {"id": "H9", "name": "增长逻辑跳跃", "severity": "medium", "keywords": ["1%", "百分之一", "指数增长"],
     "explanation": "'只要拿到1%的市场'这类表述是经典误区——自上而下的市场估算缺乏说服力。",
     "fix_hint": "改用自下而上的方法：列出可触达的渠道→预估每个渠道的转化率→汇总。"},
    {"id": "H10", "name": "里程碑不可交付", "severity": "medium", "keywords": ["一个月内", "三个月内全部完成"],
     "explanation": "里程碑设置过于激进，缺乏可交付性。不切实际的时间表会让评委质疑执行力。",
     "fix_hint": "将大目标拆成2周一个的小里程碑，每个都有明确的交付物和验收标准。"},
    {"id": "H11", "name": "合规/伦理缺口", "severity": "high", "keywords": ["隐私", "合规", "伦理", "数据安全"],
     "explanation": "涉及隐私/数据安全领域但未说明合规措施。这在评审中是一票否决项。",
     "fix_hint": "列出数据采集→存储→使用→销毁的全链路，标明每一步的合规依据。"},
    {"id": "H12", "name": "技术路线与资源不匹配", "severity": "high", "keywords": ["大模型", "芯片", "复杂硬件"],
     "explanation": "技术方案的资源需求（算力/硬件/团队能力）可能超出当前条件。",
     "fix_hint": "评估团队现有技术栈，如果要用大模型考虑用API调用而非自研训练。"},
    {"id": "H13", "name": "实验设计不合格", "severity": "medium", "keywords": ["实验", "ab测试", "对照组"], "requires": ["样本", "指标"],
     "explanation": "提到了实验/测试，但缺少样本量和评价指标的说明。没有指标的实验无法得出结论。",
     "fix_hint": "明确：样本量≥多少、核心指标是什么、对照组如何设置、多长时间。"},
    {"id": "H14", "name": "路演叙事断裂", "severity": "low", "keywords": ["愿景"], "min_length": 260,
     "explanation": "内容篇幅较短或叙事跳跃，尚未形成完整的路演结构（问题→方案→市场→模式→团队）。",
     "fix_hint": "按照'问题→方案→市场→商业模式→团队→里程碑'的框架重新组织你的内容。"},
    {"id": "H15", "name": "评分项证据覆盖不足", "severity": "medium", "keywords": [],
     "explanation": "多个评分维度缺少支撑证据，整体内容丰富度不够。补充更多数据和调研结果可以显著提分。",
     "fix_hint": "检查9个评分维度，找出得分最低的2-3项，针对性补充证据。"},
    {"id": "H16", "name": "替代方案未识别", "severity": "medium", "keywords": ["首创", "独家", "没人做", "没有替代", "没有竞争对手"],
     "requires": ["替代方案", "现有方案", "竞品"],
     "explanation": "强调独特性时没有交代用户当前如何凑合解决问题，容易高估自身差异化。",
     "fix_hint": "补一页“当前替代方案”分析，至少列出现有做法、用户为什么还在用、你替代它的难点。"},
    {"id": "H17", "name": "迁移成本未说明", "severity": "medium", "keywords": ["替换", "切换", "迁移", "改用"],
     "requires": ["迁移成本", "切换成本", "学习成本", "替换成本"],
     "explanation": "想让用户从原有方案迁移过来，但没有说明用户为此要付出什么成本。",
     "fix_hint": "补充迁移成本分析，至少说明时间成本、学习成本和数据迁移成本。"},
    {"id": "H18", "name": "付费用户与使用用户混淆", "severity": "medium", "keywords": ["用户量", "活跃用户", "下载量", "注册用户"],
     "requires": ["付费用户", "付费率", "转化率", "ARPU"],
     "explanation": "使用规模不等于商业价值，如果不区分使用用户和付费用户，收入推导会失真。",
     "fix_hint": "把用户规模拆成注册、活跃、付费三个层级，并估算每一级转化率。"},
    {"id": "H19", "name": "可触达市场口径缺失", "severity": "medium", "keywords": ["市场规模", "潜在用户", "行业空间", "很多人会用"],
     "requires": ["可触达", "首年", "som", "渠道"],
     "explanation": "描述了大市场，但没有解释第一年能通过哪些渠道触达哪些具体用户。",
     "fix_hint": "按渠道拆分首年可触达市场，并给出每条渠道的转化假设。"},
    {"id": "H20", "name": "证据与结论错配", "severity": "high", "keywords": ["证明", "验证了", "显著提升", "足以说明"],
     "requires": ["数据", "样本", "原话", "实验", "对照"],
     "explanation": "下了较强结论，但没有给出足够证据，容易让评委觉得结论跳步。",
     "fix_hint": "把每个关键结论对应到具体证据，至少补数据、样本来源或用户原话。"},
    {"id": "H21", "name": "执行步骤缺少负责人", "severity": "medium", "keywords": ["计划", "阶段", "里程碑", "执行步骤"],
     "requires": ["负责人", "分工", "谁负责"],
     "explanation": "写了执行计划但没有负责人，计划容易停留在纸面，难以证明执行能力。",
     "fix_hint": "为每个关键里程碑补充负责人、时间节点和交付物。"},
    {"id": "H22", "name": "风险控制措施空泛", "severity": "medium", "keywords": ["风险控制", "风控", "合规措施", "安全保障"],
     "requires": ["流程", "机制", "预案", "授权", "审计"],
     "explanation": "提到了风险控制，但缺少真正可执行的机制与流程，属于口号式风控。",
     "fix_hint": "把风控措施拆成流程、责任人和触发条件三部分来写。"},
    {"id": "H23", "name": "创新点与用户价值脱节", "severity": "medium", "keywords": ["创新", "黑科技", "领先", "独特技术"],
     "requires": ["用户价值", "效率", "成本", "体验", "结果"],
     "explanation": "强调了技术或创新性，但没有说明它给用户带来什么可感知价值。",
     "fix_hint": "把创新点翻译成用户价值语言：具体提升了什么、节省了什么、替代了什么。"},
    {"id": "H24", "name": "融资节奏与业务阶段不匹配", "severity": "medium", "keywords": ["融资", "天使轮", "A轮", "投资"],
     "requires": ["产品", "收入", "用户", "验证", "MVP"],
     "explanation": "提到了融资计划，但当前业务阶段可能还不到该轮次的融资条件。投资人会看业务里程碑而非商业计划书。",
     "fix_hint": "先梳理当前业务里程碑完成度，再匹配对应的融资节奏：种子轮看团队+方向，天使轮看MVP+初步验证，A轮看增长+单位经济。"},
    {"id": "H25", "name": "股权架构缺失", "severity": "medium", "keywords": ["合伙", "合伙人", "一起做", "团队"],
     "requires": ["股权", "分配", "协议", "出资"],
     "explanation": "多人合伙创业但未提及股权分配，这是早期创业最常见的定时炸弹。",
     "fix_hint": "尽早确定股权架构，建议创始人之间签订合伙协议，明确出资比例、退出机制和决策权。预留10-20%期权池。"},
    {"id": "H26", "name": "成本结构不透明", "severity": "medium", "keywords": ["收费", "定价", "盈利", "赚钱"],
     "requires": ["成本", "毛利", "固定成本", "变动成本", "运营成本"],
     "explanation": "有定价或盈利描述，但没有拆解成本结构。不知道成本就无法判断定价是否合理。",
     "fix_hint": "列出固定成本（服务器/人力/房租）和变动成本（获客/物流/提成），算出毛利率，确认定价能覆盖成本。"},
    {"id": "H27", "name": "增长渠道缺乏验证", "severity": "medium", "keywords": ["推广", "获客", "增长", "拉新", "引流"],
     "requires": ["转化率", "ROI", "测试", "数据", "成本"],
     "explanation": "提到了获客/推广计划，但缺少渠道验证数据。没有测试过的渠道假设是空中楼阁。",
     "fix_hint": "选择1-2个核心渠道先做小规模测试，记录获客成本、转化率和留存数据，再决定是否加大投入。"},
]

RULE_FALLACY_MAP: dict[str, str] = {
    "H1": "价值主张失焦谬误",
    "H2": "渠道幻觉谬误",
    "H3": "定价拍脑袋谬误",
    "H4": "大数幻觉谬误",
    "H5": "需求假设谬误",
    "H6": "竞争真空谬误",
    "H7": "创新口号谬误",
    "H8": "单位经济谬误",
    "H9": "增长跳跃谬误",
    "H10": "里程碑不实谬误",
    "H11": "合规盲区谬误",
    "H12": "资源错配谬误",
    "H13": "实验设计缺陷谬误",
    "H14": "叙事断裂谬误",
    "H15": "评分项证据覆盖不足",
    "H16": "替代方案盲视谬误",
    "H17": "迁移成本忽视谬误",
    "H18": "用户口径混淆谬误",
    "H19": "可触达市场缺失谬误",
    "H20": "证据-结论跳步谬误",
    "H21": "执行无责任人谬误",
    "H22": "风控口号谬误",
    "H23": "创新-价值脱节谬误",
    "H24": "融资节奏错配谬误",
    "H25": "股权架构缺失谬误",
    "H26": "成本结构不透明谬误",
    "H27": "增长渠道未验证谬误",
}

# ─────────────────────────────────────────────────────
# 诊断规则 → 超图家族 映射（v2，对齐 77 家族体系）
#
# 设计原则：
#   1. 命名对齐 hypergraph_service.EDGE_FAMILY_LABELS（77 家族当前命名）
#   2. 每条规则点亮 3~6 个相关家族，打破"只引用风险/价值"偏置
#   3. 与 KEYWORD_FAMILY_MAP / INTENT_FAMILY_MAP 叠加后覆盖全部 77 家族
#   4. 同一家族允许出现在多条规则里（表达家族的多源触发性）
#
# 历史债（v1 问题）：v1 使用的 Stakeholder_Solution_Edge / Evidence_Chain_Edge /
# Competitive_Landscape_Edge / Innovation_Differentiation_Edge / Financial_Logic_Edge /
# Execution_Dependency_Edge 六个名字在 77 家族体系里已被改名/拆分，导致 type_hit
# 永远为 False，只有 Value_Loop / Risk_Pattern 能拿到加分，产生偏置。
# ─────────────────────────────────────────────────────
RULE_EDGE_MAP: dict[str, list[str]] = {
    "H1": ["Value_Loop_Edge", "User_Pain_Fit_Edge", "Market_Segmentation_Edge",
           "Need_Prioritization_Edge", "Empathy_Map_Edge"],
    "H2": ["Channel_Conversion_Edge", "User_Journey_Edge", "Demand_Supply_Match_Edge",
           "Risk_Pattern_Edge"],
    "H3": ["Pricing_Unit_Economics_Edge", "Revenue_Sustainability_Edge",
           "Evidence_Grounding_Edge", "Trust_Adoption_Edge"],
    "H4": ["Market_Segmentation_Edge", "Metric_Definition_Edge",
           "Scenario_Analysis_Edge", "Risk_Pattern_Edge"],
    "H5": ["Evidence_Grounding_Edge", "Insight_Validation_Edge", "UX_Research_Edge",
           "Problem_Discovery_Edge", "Empathy_Map_Edge"],
    "H6": ["Market_Competition_Edge", "Substitute_Migration_Edge",
           "Competitive_Response_Edge", "Switching_Cost_Edge", "IP_Moat_Edge"],
    "H7": ["Innovation_Validation_Edge", "Prototype_Validation_Edge",
           "Tech_Readiness_Edge", "Concept_Evaluation_Edge", "Research_Application_Edge"],
    "H8": ["Pricing_Unit_Economics_Edge", "Cost_Structure_Edge",
           "Revenue_Sustainability_Edge", "Risk_Pattern_Edge"],
    "H9": ["Demand_Supply_Match_Edge", "Assumption_Stack_Edge", "Scenario_Analysis_Edge",
           "Scalability_Bottleneck_Edge", "Network_Effect_Edge"],
    "H10": ["Milestone_Dependency_Edge", "Execution_Gap_Edge", "Feasibility_Screen_Edge",
            "MVP_Scope_Edge", "Solution_Architecture_Edge"],
    "H11": ["Compliance_Safety_Edge", "Data_Privacy_Edge", "Ethical_Bias_Edge",
            "Regulatory_Landscape_Edge", "Industry_Compliance_Edge",
            "Governance_Transparency_Edge"],
    "H12": ["Tech_Readiness_Edge", "Tech_Debt_Edge", "Resource_Leverage_Edge",
            "Feasibility_Screen_Edge", "API_Integration_Edge", "Solution_Architecture_Edge"],
    "H13": ["Insight_Validation_Edge", "Metric_Definition_Edge",
            "Prototype_Validation_Edge", "Data_Quality_Edge"],
    "H14": ["Presentation_Narrative_Edge", "Cross_Dimension_Coherence_Edge",
            "Value_Loop_Edge", "User_Education_Edge"],
    "H15": ["Rule_Rubric_Tension_Edge", "Evidence_Grounding_Edge",
            "Cross_Dimension_Coherence_Edge", "Feedback_Loop_Edge"],
    "H16": ["Substitute_Migration_Edge", "Market_Competition_Edge",
            "Assumption_Stack_Edge", "Competitive_Response_Edge"],
    "H17": ["Switching_Cost_Edge", "Substitute_Migration_Edge", "Trust_Adoption_Edge",
            "Retention_Workflow_Embed_Edge"],
    "H18": ["Metric_Definition_Edge", "Revenue_Sustainability_Edge",
            "Channel_Conversion_Edge", "Data_Flywheel_Edge"],
    "H19": ["Market_Segmentation_Edge", "Demand_Supply_Match_Edge",
            "Metric_Definition_Edge", "Scenario_Analysis_Edge"],
    "H20": ["Evidence_Grounding_Edge", "Assumption_Stack_Edge",
            "Insight_Validation_Edge", "Risk_Pattern_Edge"],
    "H21": ["Execution_Gap_Edge", "Milestone_Dependency_Edge",
            "Team_Capability_Gap_Edge", "Founder_Risk_Edge"],
    "H22": ["Risk_Pattern_Edge", "Scenario_Analysis_Edge",
            "Governance_Transparency_Edge", "Compliance_Safety_Edge", "Pivot_Signal_Edge"],
    "H23": ["Value_Loop_Edge", "User_Pain_Fit_Edge", "Innovation_Validation_Edge",
            "Academic_Transfer_Edge", "Ideation_Edge", "Design_Thinking_Edge"],
    "H24": ["Funding_Stage_Fit_Edge", "Stage_Goal_Fit_Edge",
            "Revenue_Sustainability_Edge", "Pivot_Signal_Edge"],
    "H25": ["Team_Capability_Gap_Edge", "Founder_Risk_Edge",
            "Stakeholder_Conflict_Edge", "Governance_Transparency_Edge",
            "Partnership_Network_Edge"],
    "H26": ["Cost_Structure_Edge", "Pricing_Unit_Economics_Edge",
            "Supply_Chain_Edge", "Metric_Definition_Edge"],
    "H27": ["Channel_Conversion_Edge", "Network_Effect_Edge",
            "Partnership_Network_Edge", "Data_Flywheel_Edge",
            "Community_Building_Edge", "Ecosystem_Dependency_Edge"],
}


# ─────────────────────────────────────────────────────
# 关键词 → 超图家族 兜底映射
#
# 专门点亮那些 H 规则不易覆盖到的"领域特化"家族（学术转化、ESG、设计等）。
# 当学生消息命中任一关键词即把对应家族塞进 preferred_edge_types。
# ─────────────────────────────────────────────────────
KEYWORD_FAMILY_MAP: dict[str, list[str]] = {
    # 本体/概念锚定：总是有效（学生用到抽象概念时激活）
    "本体": ["Ontology_Grounded_Edge"],
    "概念": ["Ontology_Grounded_Edge"],
    "定义": ["Ontology_Grounded_Edge", "Metric_Definition_Edge"],
    # 社会价值 / ESG / 公益
    "公益": ["Social_Impact_Edge", "Community_Building_Edge"],
    "社会": ["Social_Impact_Edge", "ESG_Measurability_Edge"],
    "ESG": ["ESG_Measurability_Edge", "Environmental_Impact_Edge", "Governance_Transparency_Edge"],
    "esg": ["ESG_Measurability_Edge", "Environmental_Impact_Edge"],
    "环保": ["Environmental_Impact_Edge", "ESG_Measurability_Edge"],
    "可持续": ["Environmental_Impact_Edge", "Revenue_Sustainability_Edge"],
    "碳排": ["Environmental_Impact_Edge", "ESG_Measurability_Edge"],
    # 产学研 / 学术转化 / IP
    "论文": ["Academic_Transfer_Edge", "Research_Application_Edge", "Industry_Academia_Edge"],
    "科研": ["Academic_Transfer_Edge", "Research_Application_Edge"],
    "学术": ["Academic_Transfer_Edge", "Industry_Academia_Edge"],
    "专利": ["IP_Moat_Edge", "IP_Commercialization_Edge", "Tech_Licensing_Edge"],
    "知识产权": ["IP_Moat_Edge", "IP_Commercialization_Edge"],
    "技术转让": ["Tech_Licensing_Edge", "IP_Commercialization_Edge"],
    "产学研": ["Industry_Academia_Edge", "Academic_Transfer_Edge"],
    # 设计 / 用户体验 / 可达性
    "设计": ["Design_Driven_Edge", "Design_Thinking_Edge", "UX_Research_Edge"],
    "UI": ["Design_Driven_Edge", "UX_Research_Edge"],
    "用户体验": ["UX_Research_Edge", "Design_Driven_Edge", "Feedback_Loop_Edge"],
    "无障碍": ["Accessibility_Edge", "User_Education_Edge"],
    "易用": ["Accessibility_Edge", "UX_Research_Edge"],
    # 时机窗口
    "时机": ["Timing_Window_Edge"],
    "窗口期": ["Timing_Window_Edge"],
    "先发": ["Timing_Window_Edge", "Competitive_Response_Edge"],
    # 教育用户 / 反馈
    "培训": ["User_Education_Edge"],
    "教育用户": ["User_Education_Edge"],
    "反馈": ["Feedback_Loop_Edge", "UX_Research_Edge"],
    # 供应链 / 生态
    "供应链": ["Supply_Chain_Edge", "Ecosystem_Dependency_Edge"],
    "上游": ["Supply_Chain_Edge", "Partnership_Network_Edge"],
    "生态": ["Ecosystem_Dependency_Edge", "Partnership_Network_Edge"],
    # 创意/发散
    "创意": ["Ideation_Edge", "Design_Thinking_Edge"],
    "设计思维": ["Design_Thinking_Edge", "Ideation_Edge"],
    # 架构/技术
    "架构": ["Solution_Architecture_Edge", "Tech_Readiness_Edge"],
    "接口": ["API_Integration_Edge", "Solution_Architecture_Edge"],
    "API": ["API_Integration_Edge"],
    "技术债": ["Tech_Debt_Edge", "Feasibility_Screen_Edge"],
    # 场景/旅程
    "场景": ["Scenario_Analysis_Edge", "User_Journey_Edge"],
    "用户旅程": ["User_Journey_Edge", "Channel_Conversion_Edge"],
}


# ─────────────────────────────────────────────────────
# 意图 → 超图家族 兜底映射
#
# 当学生意图明确（如 pressure_test / learning_concept），让对应家族优先出现。
# ─────────────────────────────────────────────────────
INTENT_FAMILY_MAP: dict[str, list[str]] = {
    "pressure_test": [
        "Risk_Pattern_Edge", "Assumption_Stack_Edge", "Scenario_Analysis_Edge",
        "Evidence_Grounding_Edge", "Pivot_Signal_Edge",
    ],
    "learning_concept": [
        "Ontology_Grounded_Edge", "Design_Thinking_Edge", "Ideation_Edge",
        "Problem_Discovery_Edge", "Concept_Evaluation_Edge",
    ],
    "business_plan_feedback": [
        "Value_Loop_Edge", "Cross_Dimension_Coherence_Edge",
        "Presentation_Narrative_Edge", "Rule_Rubric_Tension_Edge",
    ],
    "competition_strategy": [
        "Market_Competition_Edge", "Competitive_Response_Edge", "IP_Moat_Edge",
        "Timing_Window_Edge", "Innovation_Validation_Edge",
    ],
    "fundraising": [
        "Funding_Stage_Fit_Edge", "Revenue_Sustainability_Edge",
        "Pricing_Unit_Economics_Edge", "Founder_Risk_Edge",
    ],
    "social_impact": [
        "Social_Impact_Edge", "ESG_Measurability_Edge",
        "Community_Building_Edge", "Environmental_Impact_Edge",
    ],
}


def get_preferred_edge_families(
    rule_ids: list[str] | None = None,
    intent: str | None = None,
    message: str | None = None,
    cap_per_source: int = 6,
) -> list[str]:
    """Assemble diverse preferred edge families from rules + intent + keywords.

    Ensures retrieval is not biased by a single source. Returns deduplicated,
    order-preserved list where:
      - first come rule-derived families (they fire when student text actually
        triggered a diagnosis),
      - then intent-derived families,
      - then keyword-derived families (weakest signal).
    """
    collected: list[str] = []
    seen: set[str] = set()

    def _push(fams: list[str]) -> None:
        count = 0
        for fam in fams:
            if not fam or fam in seen:
                continue
            collected.append(fam)
            seen.add(fam)
            count += 1
            if count >= cap_per_source:
                break

    for rid in rule_ids or []:
        _push(RULE_EDGE_MAP.get(str(rid), []))
    if intent:
        _push(INTENT_FAMILY_MAP.get(str(intent), []))
    if message:
        msg = str(message)
        for kw, fams in KEYWORD_FAMILY_MAP.items():
            if kw in msg:
                _push(fams)
    return collected

RULE_STRATEGY_MAP: dict[str, list[str]] = {
    "H1": ["broad_competition_logic"],
    "H2": ["precision_acquisition_logic"],
    "H3": ["cashflow_survival_logic"],
    "H4": ["market_sizing_logic"],
    "H5": ["evidence_validation_logic"],
    "H6": ["broad_competition_logic"],
    "H7": ["evidence_validation_logic"],
    "H8": ["cashflow_survival_logic"],
    "H9": ["market_sizing_logic", "cashflow_survival_logic"],
    "H10": ["execution_feasibility_logic"],
    "H11": ["compliance_risk_logic"],
    "H12": ["execution_feasibility_logic"],
    "H13": ["evidence_validation_logic"],
    "H14": ["narrative_structure_logic"],
    "H15": ["evidence_validation_logic"],
    "H16": ["broad_competition_logic"],
    "H17": ["broad_competition_logic", "precision_acquisition_logic"],
    "H18": ["cashflow_survival_logic"],
    "H19": ["market_sizing_logic", "precision_acquisition_logic"],
    "H20": ["evidence_validation_logic"],
    "H21": ["execution_feasibility_logic"],
    "H22": ["compliance_risk_logic"],
    "H23": ["evidence_validation_logic", "broad_competition_logic"],
}

RUBRICS = [
    {"item": "Problem Definition", "weight": 0.1, "evidence": ["痛点", "场景", "用户画像"], "rules": ["H1", "H5"]},
    {"item": "User Evidence Strength", "weight": 0.15, "evidence": ["访谈", "问卷", "原话", "样本", "内测", "点击", "转化", "预约", "日志"], "rules": ["H5", "H13"]},
    {"item": "Solution Feasibility", "weight": 0.1, "evidence": ["技术路线", "mvp", "资源"], "rules": ["H7", "H12"]},
    {"item": "Business Model Consistency", "weight": 0.15, "evidence": ["价值主张", "渠道", "收入", "成本"], "rules": ["H1", "H2", "H3"]},
    {"item": "Market & Competition", "weight": 0.1, "evidence": ["市场规模", "tam", "sam", "som", "竞品"], "rules": ["H4", "H6"]},
    {"item": "Financial Logic", "weight": 0.1, "evidence": ["cac", "ltv", "现金流", "回本"], "rules": ["H8", "H9"]},
    {"item": "Innovation & Differentiation", "weight": 0.1, "evidence": ["创新点", "差异化", "对比矩阵"], "rules": ["H6", "H7"]},
    {"item": "Team & Execution", "weight": 0.05, "evidence": ["团队", "分工", "里程碑"], "rules": ["H10", "H12"]},
    {"item": "Presentation Quality", "weight": 0.05, "evidence": ["路演", "结构", "叙事", "数据支撑"], "rules": ["H14", "H15"]},
]

COMPETITION_RUBRIC_WEIGHTS: dict[str, dict[str, float]] = {
    "internet_plus": {
        "Problem Definition": 0.08,
        "User Evidence Strength": 0.10,
        "Solution Feasibility": 0.10,
        "Business Model Consistency": 0.20,
        "Market & Competition": 0.15,
        "Financial Logic": 0.10,
        "Innovation & Differentiation": 0.10,
        "Team & Execution": 0.07,
        "Presentation Quality": 0.10,
    },
    "challenge_cup": {
        "Problem Definition": 0.10,
        "User Evidence Strength": 0.15,
        "Solution Feasibility": 0.15,
        "Business Model Consistency": 0.08,
        "Market & Competition": 0.07,
        "Financial Logic": 0.05,
        "Innovation & Differentiation": 0.20,
        "Team & Execution": 0.10,
        "Presentation Quality": 0.10,
    },
    "dachuang": {
        "Problem Definition": 0.12,
        "User Evidence Strength": 0.12,
        "Solution Feasibility": 0.18,
        "Business Model Consistency": 0.10,
        "Market & Competition": 0.08,
        "Financial Logic": 0.08,
        "Innovation & Differentiation": 0.15,
        "Team & Execution": 0.12,
        "Presentation Quality": 0.05,
    },
}


def _get_rubrics(competition_type: str = "") -> list[dict]:
    """Return RUBRICS with weights adjusted for the given competition type."""
    overrides = COMPETITION_RUBRIC_WEIGHTS.get(competition_type, {})
    if not overrides:
        return RUBRICS
    return [{**row, "weight": overrides.get(row["item"], row["weight"])} for row in RUBRICS]

COMPETITION_RULE_EMPHASIS: dict[str, dict[str, str]] = {
    "H1": {
        "internet_plus": "互联网+评审高度关注客户-价值主张一致性，这直接影响商业模式得分",
        "challenge_cup": "挑战杯更关注技术创新，但清晰的用户定位仍是基本要求",
        "dachuang": "大创项目需明确服务对象，评审会检查用户定位是否切实",
    },
    "H2": {
        "internet_plus": "互联网+评委会追问渠道可达性和获客路径的具体数据",
        "challenge_cup": "挑战杯对渠道要求较低，但应用落地型项目仍需说明推广路径",
        "dachuang": "大创评审关注方案是否可执行，渠道可达性是落地能力的一部分",
    },
    "H3": {
        "internet_plus": "这是互联网+核心扣分点：定价和支付意愿验证直接决定商业模式是否成立",
        "challenge_cup": "挑战杯不强制要求定价模型，但若涉及应用落地建议简要说明",
        "dachuang": "大创项目如涉及创业训练赛道，需有基本的价值交换逻辑",
    },
    "H4": {
        "internet_plus": "互联网+要求TAM/SAM/SOM论证清晰，这是市场维度的关键评审点",
        "challenge_cup": "挑战杯对市场规模论证的要求低于互联网+，但不应完全缺失",
        "dachuang": "大创项目建议有基本的市场空间判断，不需要严格的三层市场分析",
    },
    "H5": {
        "internet_plus": "用户证据是互联网+评审的基础，缺乏证据会严重影响多个维度得分",
        "challenge_cup": "挑战杯特别看重调研严谨性，需求证据不足会直接影响评分",
        "dachuang": "大创评审看重实践过程，用户调研是证明动手能力的重要依据",
    },
    "H6": {
        "internet_plus": "互联网+要求完整的竞品对比矩阵，声称无竞争对手是常见扣分点",
        "challenge_cup": "挑战杯看重技术对比和文献综述，需说明与现有方案的差异",
        "dachuang": "大创项目至少应说明现有替代方案，体现对领域的了解",
    },
    "H7": {
        "internet_plus": "互联网+要求创新点有可验证的对比依据，不能只停在口号层面",
        "challenge_cup": "这是挑战杯最核心的评审维度——创新含量必须有实验或原型验证",
        "dachuang": "大创评审看重是否有新视角或新方法，创新可验证性是加分项",
    },
    "H8": {
        "internet_plus": "单位经济模型是互联网+答辩必问环节，务必完善CAC/LTV分析",
        "challenge_cup": "挑战杯通常不直接考核单位经济，但应用型项目可作为加分项",
        "dachuang": "大创创业训练赛道建议有基本的经济可行性分析",
    },
    "H9": {
        "internet_plus": "互联网+评委对增长逻辑敏感，'占1%市场'式论证会被追问",
        "challenge_cup": "挑战杯对增长预测要求不高，但技术推广路径应合理",
        "dachuang": "大创项目的增长预期应实事求是，与训练计划周期匹配",
    },
    "H10": {
        "internet_plus": "互联网+要求有清晰的里程碑和可交付物，时间表应具体可执行",
        "challenge_cup": "挑战杯看重研究进度和阶段性成果，里程碑需与实验计划匹配",
        "dachuang": "这是大创评审重点——训练过程记录和里程碑追踪直接影响评审",
    },
    "H11": {
        "internet_plus": "涉及隐私、数据、医疗等领域时，互联网+评委必看合规措施",
        "challenge_cup": "挑战杯涉及实验伦理和数据安全时，合规审查是基本要求",
        "dachuang": "大创项目应体现对合规和伦理的基本意识",
    },
    "H12": {
        "internet_plus": "互联网+评委会追问技术路线与团队资源是否匹配",
        "challenge_cup": "这是挑战杯关键评审点——技术路线必须与团队科研能力匹配",
        "dachuang": "大创评审特别看重方案的可落地性，技术路线需匹配团队能力",
    },
    "H13": {
        "internet_plus": "互联网+鼓励有实验数据支撑产品假设，但不强制要求学术级实验",
        "challenge_cup": "这是挑战杯核心评审维度——实验设计的严谨性和可重复性",
        "dachuang": "大创项目的实验设计应体现科学训练过程，不需要顶刊级别",
    },
    "H14": {
        "internet_plus": "互联网+路演表达是重要评审维度，叙事结构直接影响评委印象",
        "challenge_cup": "挑战杯看重汇报的逻辑性和学术规范，叙事可稍弱但逻辑须清晰",
        "dachuang": "大创答辩要求清晰表达，重点展示训练过程和成果",
    },
    "H15": {
        "internet_plus": "互联网+评审是逐维度打分，证据覆盖不全会拉低多个维度",
        "challenge_cup": "挑战杯评审看重证据链完整度，特别是实验和调研部分",
        "dachuang": "大创评审关注过程性证据，阶段成果记录是关键",
    },
    "H16": {
        "internet_plus": "互联网+评委常追问'如果巨头进入怎么办'，替代方案分析很重要",
        "challenge_cup": "挑战杯需要文献综述和现有方案对比，替代方案是基本功",
        "dachuang": "大创项目应了解领域内已有方案，体现调研深度",
    },
    "H17": {
        "internet_plus": "互联网+评审会考虑用户迁移成本，这影响市场进入策略评价",
        "challenge_cup": "挑战杯对迁移成本的关注较低，除非是产品替换类项目",
        "dachuang": "大创项目如涉及替换现有方案，应简要说明切换难度",
    },
    "H18": {
        "internet_plus": "互联网+评委区分付费用户和注册用户，混淆会影响商业模式可信度",
        "challenge_cup": "挑战杯对用户分层要求不高，但应准确表述用户相关数据",
        "dachuang": "大创项目引用用户数据时应区分类型，体现数据素养",
    },
    "H19": {
        "internet_plus": "互联网+要求可触达市场(SOM)的论证路径，不能只说TAM",
        "challenge_cup": "挑战杯对市场口径的精确度要求低于互联网+",
        "dachuang": "大创项目有基本的目标用户规模估计即可",
    },
    "H20": {
        "internet_plus": "互联网+评委对'数据注水'非常敏感，证据与结论必须对应",
        "challenge_cup": "这是挑战杯调研严谨性的核心——证据必须支撑结论",
        "dachuang": "大创评审看重实事求是，证据与结论的对应关系是基本要求",
    },
    "H21": {
        "internet_plus": "互联网+要求团队分工明确，执行步骤需有负责人",
        "challenge_cup": "挑战杯看重团队协作，但分工形式可更灵活",
        "dachuang": "大创项目的分工和负责人是评审检查训练过程的重要依据",
    },
    "H22": {
        "internet_plus": "互联网+要求有具体的风控措施和预案，不能空泛描述",
        "challenge_cup": "挑战杯涉及实验安全时需有具体措施，其他类型可简要说明",
        "dachuang": "大创项目应有基本的风险意识和应对思路",
    },
    "H23": {
        "internet_plus": "互联网+要求创新点直接转化为用户价值，技术创新需连接商业逻辑",
        "challenge_cup": "挑战杯允许纯技术创新，但应说明潜在应用价值",
        "dachuang": "大创项目的创新应服务于实际问题，不能为创新而创新",
    },
}

CAPABILITY_MAP = [
    {"stage": "痛点发现", "dimension": "敏锐度与同理心", "focus": "识别真需求并给出用户证据"},
    {"stage": "方案策划", "dimension": "创造力与可行性", "focus": "验证创新点并匹配资源"},
    {"stage": "商业建模", "dimension": "商业逻辑性", "focus": "打通价值-渠道-收入闭环"},
    {"stage": "团队与资源", "dimension": "协作与执行力", "focus": "分工、里程碑与交付能力"},
    {"stage": "路演表达", "dimension": "叙事与抗压", "focus": "结构完整、数据可信、问答稳定"},
]


@dataclass
class DiagnosisResult:
    diagnosis: dict
    next_task: dict


_EVIDENCE_SYNONYMS: dict[str, list[str]] = {
    "tam": ["市场总量", "total addressable", "总体市场", "市场容量"],
    "sam": ["可服务市场", "serviceable addressable", "目标市场规模"],
    "som": ["可获得市场", "serviceable obtainable", "实际可获取"],
    "cac": ["获客成本", "customer acquisition", "获取成本", "拉新成本"],
    "ltv": ["用户价值", "lifetime value", "生命周期价值", "终身价值"],
    "访谈": ["用户访谈", "深度访谈", "调研访谈", "用户反馈", "用户洞察"],
    "问卷": ["调研问卷", "问卷调查", "线上调研", "需求调研"],
    "点击": ["点击率", "点击数据", "点击转化", "CTR"],
    "转化": ["转化率", "留资转化", "付费转化", "注册转化"],
    "预约": ["预约页", "预约人数", "预约转化", "预定"],
    "日志": ["使用日志", "行为日志", "埋点数据", "操作记录"],
    "竞品": ["竞争分析", "竞争对手", "竞品分析", "市场竞争", "对标分析"],
    "市场规模": ["market size", "市场空间", "行业规模", "市场前景"],
    "技术路线": ["技术方案", "技术架构", "技术栈", "系统架构"],
    "mvp": ["最小可行", "原型", "demo", "试点", "pilot"],
    "里程碑": ["发展阶段", "规划", "路线图", "时间表", "计划表"],
    "团队": ["核心成员", "创始人", "合伙人", "团队成员", "人员构成"],
    "创新点": ["差异化", "核心优势", "独特价值", "技术壁垒"],
    "价值主张": ["价值定位", "核心价值", "用户价值", "产品价值"],
    "渠道": ["获客渠道", "销售渠道", "推广方式", "营销渠道"],
    "收入": ["营收", "收入模式", "盈利模式", "变现", "收费模式"],
    "成本": ["成本结构", "运营成本", "固定成本", "可变成本"],
}


def _fuzzy_match(keyword: str, text: str) -> bool:
    if keyword in text:
        return True
    for syn in _EVIDENCE_SYNONYMS.get(keyword, []):
        if syn.lower() in text:
            return True
    return False


def _is_hit_rule(rule: dict, text: str, text_len: int = 0) -> bool:
    keywords = rule.get("keywords", [])
    requires = rule.get("requires", [])
    has_keyword = bool(keywords) and any(_fuzzy_match(k, text) for k in keywords)
    requires_missing = bool(requires) and not any(_fuzzy_match(k, text) for k in requires)
    too_short = bool(rule.get("min_length")) and text_len < int(rule["min_length"])

    if has_keyword and requires_missing:
        return True
    if has_keyword and not requires:
        return True
    if requires_missing and not keywords:
        return True
    if too_short:
        return True
    return False


def _rule_penalty(severity: str, stage: str, is_file: bool = False) -> float:
    base = {"high": 0.68, "medium": 0.36}.get(severity, 0.18)
    stage_factor = {
        "idea": 0.72,
        "structured": 0.86,
        "validated": 1.0,
        "document": 1.0,
    }.get(stage, 0.9)
    penalty = base * stage_factor
    return penalty * 0.65 if is_file else penalty


def _infer_project_stage(text: str, is_file: bool = False) -> str:
    stage, _ = _infer_project_stage_with_signals(text, is_file=is_file)
    return stage


def _infer_project_stage_with_signals(text: str, is_file: bool = False) -> tuple[str, dict]:
    """返回 (stage, signals) —— signals 里含各信号词命中数，用于 rationale。"""
    evidence_keys = [
        "访谈", "问卷", "样本", "数据", "实验", "验证", "原型", "mvp",
        "调研", "田野", "试点", "poc", "用户测试", "留存", "dau", "内测",
    ]
    business_keys = [
        "市场规模", "tam", "sam", "som", "定价", "商业模式", "渠道",
        "收入", "成本", "毛利", "财务", "客单价", "盈利模式", "变现",
    ]
    execution_keys = [
        "团队", "里程碑", "时间表", "技术路线", "落地", "执行",
        "分工", "负责人", "路线图", "计划表",
    ]
    evidence_hit_kw = [k for k in evidence_keys if _fuzzy_match(k, text)]
    business_hit_kw = [k for k in business_keys if _fuzzy_match(k, text)]
    execution_hit_kw = [k for k in execution_keys if _fuzzy_match(k, text)]
    evidence_hits = len(evidence_hit_kw)
    business_hits = len(business_hit_kw)
    execution_hits = len(execution_hit_kw)
    text_len = len(text)
    number_hits = len(re.findall(r"\d+(?:\.\d+)?%?", text))

    if is_file and text_len >= 800:
        stage = "document"
    elif evidence_hits >= 4 and business_hits >= 3:
        stage = "validated"
    elif (
        business_hits >= 2
        or execution_hits >= 2
        or text_len >= 350
        or (number_hits >= 3 and business_hits >= 2 and text_len >= 400)
    ):
        stage = "structured"
    else:
        stage = "idea"
    signals = {
        "evidence_hits": evidence_hits,
        "business_hits": business_hits,
        "execution_hits": execution_hits,
        "evidence_hit_kw": evidence_hit_kw[:6],
        "business_hit_kw": business_hit_kw[:6],
        "execution_hit_kw": execution_hit_kw[:6],
        "text_len": text_len,
        "number_hits": number_hits,
        "is_file": is_file,
    }
    return stage, signals


def _build_stage_rationale(stage: str, stage_label_cn: str, signals: dict) -> dict:
    """返回 project_stage rationale：解释为什么判定为这个阶段。"""
    steps: list[dict] = []
    evidence_hit_kw = signals.get("evidence_hit_kw") or []
    business_hit_kw = signals.get("business_hit_kw") or []
    execution_hit_kw = signals.get("execution_hit_kw") or []
    text_len = signals.get("text_len", 0)
    number_hits = signals.get("number_hits", 0)
    is_file = bool(signals.get("is_file", False))

    steps.append({
        "kind": "base",
        "label": "阶段判定依据：证据词 / 商业词 / 执行词 命中数 + 文本长度",
        "detail": (
            f"证据词命中 {signals.get('evidence_hits', 0)}；"
            f"商业词命中 {signals.get('business_hits', 0)}；"
            f"执行词命中 {signals.get('execution_hits', 0)}；"
            f"文本长度 {text_len}；数字 {number_hits}"
        ),
    })
    if evidence_hit_kw:
        steps.append({
            "kind": "evidence",
            "label": f"命中证据词：{ '、'.join(evidence_hit_kw) }",
            "severity": "info",
        })
    if business_hit_kw:
        steps.append({
            "kind": "evidence",
            "label": f"命中商业词：{ '、'.join(business_hit_kw) }",
            "severity": "info",
        })
    if execution_hit_kw:
        steps.append({
            "kind": "evidence",
            "label": f"命中执行词：{ '、'.join(execution_hit_kw) }",
            "severity": "info",
        })

    if stage == "document":
        steps.append({
            "kind": "adjust",
            "label": "上传文件且长度 ≥ 800 字，判为「文档化阶段」",
            "detail": "文件级别输入默认视为完整计划书结构",
        })
    elif stage == "validated":
        steps.append({
            "kind": "adjust",
            "label": "证据词 ≥4 且商业词 ≥3，判为「已验证阶段」",
            "detail": "同时出现多种用户证据与商业要素",
        })
    elif stage == "structured":
        steps.append({
            "kind": "adjust",
            "label": "触发了结构化阈值（商业词 ≥2 或 执行词 ≥2 或 长度 ≥350）",
            "detail": "已具备初步逻辑但证据尚未完全闭环",
        })
    else:
        steps.append({
            "kind": "adjust",
            "label": "未满足更高阶段阈值 → 判为「想法萌芽期」",
            "detail": "建议先补用户证据或商业闭环",
        })

    return {
        "field": "project_stage",
        "value": stage_label_cn,
        "formula": "threshold(evidence_hits, business_hits, execution_hits, text_len, is_file)",
        "formula_display": (
            f"当前阶段 = {stage_label_cn}（{stage}）\n"
            f"证据词命中 {signals.get('evidence_hits', 0)}；"
            f"商业词命中 {signals.get('business_hits', 0)}；"
            f"执行词命中 {signals.get('execution_hits', 0)}；"
            f"文本长度 {text_len}"
            + ("（文件级输入）" if is_file else "")
        ),
        "reasoning_steps": steps,
        "note": f"text_len={text_len} · number_hits={number_hits}",
    }


def _stage_baseline(stage: str, is_file: bool = False) -> float:
    if is_file:
        return {"document": 5.5, "validated": 5.0, "structured": 4.0, "idea": 2.5}.get(stage, 4.0)
    return {"idea": 2.0, "structured": 3.8, "validated": 5.2, "document": 6.0}.get(stage, 3.5)


def _stage_ceiling(stage: str, is_file: bool = False) -> float:
    if is_file:
        return {"document": 9.8, "validated": 9.5, "structured": 8.8, "idea": 7.5}.get(stage, 8.5)
    return {"idea": 7.0, "structured": 8.6, "validated": 9.4, "document": 9.7}.get(stage, 8.5)


def _score_band(score: float) -> str:
    if score >= 8.3:
        return "成熟可冲刺"
    if score >= 7.0:
        return "较成熟"
    if score >= 5.5:
        return "基本成形"
    if score >= 4.0:
        return "早期可塑"
    return "想法探索期"


def _evidence_score(text: str, evidence_keywords: list[str], stage: str, is_file: bool = False) -> float:
    hit = sum(1 for k in evidence_keywords if _fuzzy_match(k, text))
    total = len(evidence_keywords)
    ratio = hit / max(total, 1)
    base = _stage_baseline(stage, is_file=is_file)
    boost = ratio * (5.2 if is_file else 4.2)
    if hit >= 5:
        boost += 1.0
    elif hit >= 3:
        boost += 0.5
    elif hit == 0:
        boost -= 0.6 if stage == "idea" else 0.9
    return max(0.0, min(_stage_ceiling(stage, is_file=is_file), base + boost))


def _suggest_next_task(primary_rule_id: str) -> dict:
    mapping = {
        "H5": {
            "title": "用一种最低成本的方法验证真实需求",
            "description": "不要默认做大而全调研，先从场景访谈、演示观察、小范围内测、预约页点击测试里选1种最适合你项目的验证方式。",
            "template_guideline": [
                "先明确你要验证的唯一判断，例如“研究生会不会因为文献追踪而持续使用”",
                "在四种动作里只选一种：5次场景访谈、10人演示观察、一次小范围内测、一个预约页点击测试",
                "只记录一个行为信号：是否愿意继续用、是否愿意预约、是否愿意留下联系方式、是否愿意反馈具体痛点",
            ],
            "acceptance_criteria": ["明确1个待验证判断", "完成1种验证动作", "拿到可复述的行为证据或反证"],
        },
        "H1": {
            "title": "重做价值主张一致性表",
            "description": "明确目标客群，重写价值主张并校验渠道可达性。",
            "template_guideline": [
                "写清唯一核心用户是谁",
                "写清该用户最痛的1个问题和当前替代方案",
                "分别列出价值主张、渠道、收入方式是否一一对应",
            ],
            "acceptance_criteria": ["1个核心客群", "2个可达渠道", "价值主张-渠道-收入一一对应"],
        },
        "H8": {
            "title": "补齐单位经济模型",
            "description": "建立 CAC/LTV/BEP 三表并给出关键假设来源。",
            "template_guideline": [
                "先估算单个用户获取成本CAC",
                "再估算单个用户生命周期价值LTV",
                "最后计算盈亏平衡点，并注明关键假设来源",
            ],
            "acceptance_criteria": ["CAC 估算可追溯", "LTV 假设有证据", "给出盈亏平衡点"],
        },
        "H11": {
            "title": "完成合规与伦理检查清单",
            "description": "列出数据采集、存储、使用、授权链路并补齐缺口。",
            "template_guideline": [
                "画出数据流向图",
                "标出每一步是否取得授权",
                "逐条补上制度、协议或风控措施",
            ],
            "acceptance_criteria": ["隐私条款草案", "数据流向图", "风险控制点清单"],
        },
        "H2": {
            "title": "重做首批用户触达路径",
            "description": "不要空讲增长，先把第一批用户从哪里来、怎么触达、为什么会点进来拆成一条真实路径。",
            "template_guideline": [
                "只保留2条最可能成功的渠道，不要同时铺太多",
                "写清每条渠道对应的人群、触达动作、转化节点",
                "给出每条渠道的首轮测试指标，例如点击、留资、加群或预约",
            ],
            "acceptance_criteria": ["2条可执行渠道", "每条渠道有转化节点", "首轮测试指标明确"],
        },
        "H3": {
            "title": "先验证价格接受度而不是直接定价",
            "description": "把“收费多少”改成“用户在什么条件下愿意付钱”，先验证支付门槛，再决定定价。",
            "template_guideline": [
                "列出基础版、进阶版、团队版3种可能付费对象",
                "为每种对象写出“为什么值得付费”的具体触发点",
                "用价格对话、预约付费按钮或小范围预售三选一测试接受度",
            ],
            "acceptance_criteria": ["至少2档价格假设", "对应价值点清楚", "拿到初步支付反馈"],
        },
        "H6": {
            "title": "补一张真实可比的竞品/替代方案矩阵",
            "description": "不要再写“没有对手”，先把用户现在怎么凑合解决这件事列出来，再比较你到底赢在哪里。",
            "template_guideline": [
                "至少列3种当前替代方案，包含直接竞品和土办法",
                "比较功能、价格、使用门槛、迁移成本",
                "最后只保留1个你最能打的差异点，不要铺太多卖点",
            ],
            "acceptance_criteria": ["至少3个替代方案", "4个比较维度", "1个核心差异点结论"],
        },
        "H7": {
            "title": "把创新点变成一个可验证的小实验",
            "description": "不要只说创新，先把最关键的新东西拆成一个最小实验，看它是否真的带来更好结果。",
            "template_guideline": [
                "写清创新点到底想改善什么结果",
                "设一个最小对照：有这个功能和没有这个功能差在哪里",
                "只盯1个结果指标，例如完成率、停留时长、理解准确率",
            ],
            "acceptance_criteria": ["创新假设明确", "有对照方案", "有1个可观测指标"],
        },
        "H10": {
            "title": "把大计划压缩成最近两周可交付版本",
            "description": "先别排很长时间线，只拆最近两周必须交付的东西，让执行显得真实可信。",
            "template_guideline": [
                "把大目标拆成2周内可完成的3个交付物",
                "每个交付物写清负责人和完成标准",
                "删掉当前资源明显做不到的远期事项",
            ],
            "acceptance_criteria": ["两周交付物清单", "负责人明确", "每项有完成标准"],
        },
        "H13": {
            "title": "重做实验设计说明",
            "description": "把“我们测过”改成“我们怎么测、测了多少、看什么指标”，否则验证没有说服力。",
            "template_guideline": [
                "写清样本是谁、数量多少、持续多久",
                "只保留1-2个核心指标",
                "说明什么结果算通过，什么结果算不过",
            ],
            "acceptance_criteria": ["样本量明确", "核心指标明确", "通过阈值明确"],
        },
        "H16": {
            "title": "补齐“用户今天怎么凑合解决”的替代方案页",
            "description": "真正的竞争不只来自同类产品，还来自用户现有习惯、表格、人工流程和免费工具。",
            "template_guideline": [
                "至少写3种当前凑合方案",
                "标出每种方案为什么还被继续使用",
                "说明你替换它最大的阻力是什么",
            ],
            "acceptance_criteria": ["3种替代方案", "每种有保留原因", "替换阻力清楚"],
        },
        "H17": {
            "title": "把迁移成本说清楚",
            "description": "如果用户要换到你这里，他要多学什么、多做什么、丢掉什么，这些都要算进去。",
            "template_guideline": [
                "拆时间成本、学习成本、数据迁移成本三类",
                "说明哪一类成本最高",
                "给出1个降低迁移成本的设计动作",
            ],
            "acceptance_criteria": ["3类迁移成本", "最高阻力点明确", "至少1个降阻动作"],
        },
        "H18": {
            "title": "把用户规模拆成漏斗而不是一句总量",
            "description": "不要直接拿总用户量推收入，先拆注册、活跃、付费三个层级，再看收入逻辑是否成立。",
            "template_guideline": [
                "列出注册、活跃、付费三层人数",
                "为每层之间填一个转化率假设",
                "再用付费层去推收入，而不是用总用户量",
            ],
            "acceptance_criteria": ["三层用户漏斗", "转化率假设", "收入推导基于付费层"],
        },
        "H19": {
            "title": "把大市场改写成首年可触达市场",
            "description": "不要只说行业很大，先说明你首年能通过哪些渠道碰到哪些具体人。",
            "template_guideline": [
                "只选首年最现实的1-2个渠道",
                "估算每个渠道能触达的人数",
                "写清这些人为什么会在这个渠道出现",
            ],
            "acceptance_criteria": ["首年渠道明确", "每条渠道有可触达人数", "触达逻辑合理"],
        },
        "H20": {
            "title": "把关键结论逐条挂到证据上",
            "description": "不要再用一句“验证了”带过，先把每个关键结论后面对应的证据补全。",
            "template_guideline": [
                "列出3个最关键结论",
                "每个结论后面配1条数据、1条原话或1个实验结果",
                "删掉没有证据支撑的强判断",
            ],
            "acceptance_criteria": ["3条关键结论", "每条有对应证据", "删除无证据强结论"],
        },
        "H21": {
            "title": "把执行计划补上负责人",
            "description": "计划本身不够，必须让人看到这件事到底谁来做、做到什么程度才算完成。",
            "template_guideline": [
                "列出最近3项关键动作",
                "每项动作标明负责人",
                "给每项动作补交付物和时间点",
            ],
            "acceptance_criteria": ["3项动作", "每项有负责人", "每项有交付物和时间点"],
        },
        "H22": {
            "title": "把风控口号改成可执行预案",
            "description": "别只写“加强风控”，要把什么时候触发、谁来处理、怎么处理写清楚。",
            "template_guideline": [
                "列出最现实的2类风险",
                "每类风险写触发条件、负责人、处理动作",
                "说明事后如何复盘和追踪",
            ],
            "acceptance_criteria": ["2类风险预案", "每类含触发条件", "每类含负责人和处理动作"],
        },
        "H23": {
            "title": "把创新语言翻译成用户收益语言",
            "description": "不要只讲技术领先，要让老师或评委立刻看懂：这到底给用户省了什么、快了什么、好在哪里。",
            "template_guideline": [
                "列出1个技术亮点",
                "把它翻译成效率、成本、体验或结果上的具体收益",
                "用一句非技术语言重新写价值主张",
            ],
            "acceptance_criteria": ["1个技术亮点", "1个可感知收益", "1句非技术版价值主张"],
        },
    }
    return mapping.get(
        primary_rule_id,
        {
            "title": "补齐证据并完成一次压力测试",
            "description": "围绕当前最高风险点，补证据并完成一轮反事实问答压力测试。",
            "template_guideline": [
                "先明确当前最高风险点是什么",
                "补至少3条能直接支撑该点的证据",
                "用评委视角做一轮反问并更新答案",
            ],
            "acceptance_criteria": ["新增3条可验证证据", "完成1轮压力测试问答", "更新修正后的版本说明"],
        },
    )


def _extract_trigger_quote(text: str, rule: dict) -> str:
    search_terms = [str(x) for x in (rule.get("keywords", []) or []) + (rule.get("requires", []) or []) if x]
    for term in search_terms:
        idx = text.lower().find(str(term).lower())
        if idx >= 0:
            start = max(0, idx - 18)
            end = min(len(text), idx + len(term) + 30)
            snippet = re.sub(r"\s+", " ", text[start:end]).strip()
            return snippet[:120]
    fallback = re.sub(r"\s+", " ", text).strip()[:120]
    return fallback


def _impact_message(rule_id: str, rule_name: str) -> str:
    mapping = {
        "H1": "价值主张和客群不一致，会导致评委认为项目定位失焦，后续渠道和收入论证都站不住。",
        "H2": "渠道不可达会让获客计划失真，进一步影响增长预测和竞赛说服力。",
        "H3": "没有支付意愿证据，收费设计容易被认为拍脑袋，影响商业模式可信度。",
        "H4": "市场口径混乱会直接削弱商业论证，评委通常会在这一页重点追问。",
        "H5": "缺少用户证据意味着真实需求未被证明，项目容易被归类为想当然。",
        "H6": "竞品分析不到位会削弱差异化与护城河论证。",
        "H7": "创新点不可验证会让技术或方案亮点变成口号，难以支撑高分。",
        "H8": "单位经济不成立会直接打击项目可持续性，竞赛和融资都很难通过。",
        "H9": "增长逻辑跳步会让市场论证显得过于乐观，评委通常会追问第一批用户从哪里来。",
        "H10": "时间线过度乐观会削弱团队执行可信度。",
        "H11": "合规伦理缺口往往是一票否决风险。",
        "H12": "技术路线与资源不匹配会让执行计划显得不可信。",
        "H13": "实验设计不合格会让验证结果失去说服力。",
        "H16": "看不见替代方案会导致竞争判断失真，难以证明你真的比现有做法更好。",
        "H17": "忽略迁移成本会高估用户转化速度，影响获客和留存判断。",
        "H18": "把使用人数当收入基础，会让财务模型高估得过于明显。",
        "H19": "只讲大市场不讲可触达市场，会让商业预测显得悬空。",
        "H20": "证据与结论不匹配会直接损害项目可信度。",
        "H21": "没有负责人会让执行计划变成口号，难以落地。",
        "H22": "空泛的风控措施无法应对真实风险，评委会认为项目准备不足。",
        "H23": "创新点如果无法转译成用户价值，就很难形成真正的竞争优势。",
    }
    return mapping.get(rule_id, f"{rule_name}如果不修复，会继续拖低项目可信度和评审得分。")


def _llm_rubric_score(text: str, mode: str) -> list[dict] | None:
    """Use LLM to score each rubric dimension with per-item justification."""
    try:
        from app.services.llm_client import LlmClient
        llm = LlmClient()
        if not llm.enabled:
            return None

        rubric_desc = "\n".join(
            f"- {r['item']}（权重{r['weight']}）：需要的证据={r['evidence']}"
            for r in RUBRICS
        )
        result = llm.chat_json(
            system_prompt=(
                "你是创业项目评审专家。请对以下每个评分维度打 0-10 分，并给出**中文**评分依据。\n"
                "评分原则（按真实质量打，不要锚定中段 5-6 分）：\n"
                "- 1-2 分：该维度内容完全缺失，或只出现名词但没有任何展开\n"
                "- 3-4 分：有概念但无细节、无数据、无证据来源（典型早期想法）\n"
                "- 5-6 分：有细节描述但缺量化数字或证据来源\n"
                "- 7-8 分：有细节 + 量化数字 + 至少一处证据来源（调研/案例/对照）\n"
                "- 9-10 分：有细节 + 量化 + 多处证据 + 替代方案分析 / SOTA 对比 / 实验结论\n"
                "打分要求：\n"
                "- 请给出真实区分度的分数，不要把大多数维度都压到 5-6 分\n"
                "- 只要某维度已有细节+量化+证据，就应该 7 分起步，不用等『特别充分』才给高分\n"
                "- reason 必须引用学生原文片段（直接抄 3-10 个字），并指出落在哪一档、为什么\n"
                "- reason 严禁出现「不够完善」「有待加强」这类空话\n\n"
                f"评分维度：\n{rubric_desc}\n\n"
                '输出 JSON：{"scores": [{"item": "...", "score": 0-10, "reason": "引用原文+分档理由"}]}'
            ),
            user_prompt=f"请评估以下项目内容（模式={mode}）：\n\n{text[:4000]}",
            temperature=0.2,
        )
        if result and "scores" in result:
            return result["scores"]
    except Exception:
        pass
    return None


def run_diagnosis(
    input_text: str,
    mode: str = "coursework",
    competition_type: str = "",
    structured_signals: dict[str, float] | None = None,
) -> DiagnosisResult:
    """
    structured_signals: 外部量化证据映射 {rule_id: score 0-1}。
      来源：finance_guard / finance_report_service 的 evidence_for_diagnosis。
      当 signals[rule_id] ≥ 0.5 时：
        - 即使关键词没命中，也视作该规则"有证据支撑"，给对应维度加分（非扣分）
        - 已命中规则可降低其惩罚系数（算作已补偿）
    """
    normalized_text = input_text.lower()
    is_file = "[" + "上传文件:" in input_text
    text_len = len(normalized_text)
    project_stage, stage_signals = _infer_project_stage_with_signals(normalized_text, is_file=is_file)
    active_rubrics = _get_rubrics(competition_type)
    structured_signals = structured_signals or {}

    if not is_file and text_len < 50:
        return DiagnosisResult(
            diagnosis={
                "mode": mode,
                "overall_score": None,
                "bottleneck": "",
                "triggered_rules": [],
                "rubric": [],
                "capability_map": CAPABILITY_MAP,
                "summary": "消息较短，暂不进行完整诊断。请描述你的项目或上传文件以获得详细分析。",
                "info_sufficient": False,
                "project_stage": "idea",
                "score_band": "",
                "grading_principles": [
                    "信息太少时不做完整评分",
                    "先补全目标用户、痛点、方案三项核心信息",
                ],
            },
            next_task={
                "title": "描述你的项目",
                "description": "告诉我你的创业想法、目标用户和想解决的问题，越详细越好。",
                "acceptance_criteria": ["项目一句话描述", "目标用户是谁", "解决什么问题"],
            },
        )

    triggered_rules: list[dict] = []
    for rule in RULES:
        if rule["id"] == "H15":
            continue
        if _is_hit_rule(rule, normalized_text, text_len=text_len):
            matched_kws = [k for k in rule.get("keywords", []) if _fuzzy_match(k, normalized_text)]
            missing_reqs = [k for k in rule.get("requires", []) if not _fuzzy_match(k, normalized_text)]
            quote = _extract_trigger_quote(input_text, rule)
            score_impact = round(_rule_penalty(rule["severity"], project_stage, is_file=is_file), 2)
            agent_name = _agent_for_rule(rule["id"])
            triggered_rules.append({
                "id": rule["id"],
                "name": rule["name"],
                "fallacy_label": RULE_FALLACY_MAP.get(rule["id"], rule["name"]),
                "severity": rule["severity"],
                "explanation": rule.get("explanation", ""),
                "fix_hint": rule.get("fix_hint", ""),
                "matched_keywords": matched_kws,
                "missing_requires": missing_reqs,
                "preferred_edge_types": RULE_EDGE_MAP.get(rule["id"], []),
                "preferred_strategy_ids": RULE_STRATEGY_MAP.get(rule["id"], []),
                "quote": quote,
                "trigger_message": f"原文片段：“{quote}” → 触发「{rule['name']}」，因为{rule.get('explanation', '')}",
                "impact": _impact_message(rule["id"], rule["name"]),
                "fix_task": rule.get("fix_hint", ""),
                # ── Rationale 兼容字段（供教师/学生 UI 追溯到底是如何推断的） ──
                "agent_name": agent_name,
                "score_impact": -score_impact,
                "inference_chain": [
                    {"step": "input", "text": (quote or "")[:200]},
                    {"step": "keyword_hit", "keywords": matched_kws, "detail": "匹配到敏感关键词"},
                    *(
                        [{"step": "required_missing", "missing": missing_reqs,
                          "detail": "缺少必要佐证字段"}]
                        if missing_reqs else []
                    ),
                    {"step": "rule_trigger", "rule_id": rule["id"], "rule_name": rule["name"],
                     "agent": agent_name, "severity": rule["severity"]},
                    {"step": "score_impact", "delta": -score_impact, "scope": "overall",
                     "detail": f"扣 {score_impact:.2f} 分"},
                ],
            })

    evidence_hits = sum(1 for k in ["访谈", "问卷", "tam", "sam", "som", "cac", "ltv", "里程碑", "原型", "内测", "实验"] if _fuzzy_match(k, normalized_text))
    if evidence_hits < 1 and not is_file and text_len > 220 and project_stage != "idea":
        h15 = next((r for r in RULES if r["id"] == "H15"), {})
        h15_quote = re.sub(r"\s+", " ", input_text).strip()[:120]
        h15_impact = round(_rule_penalty("medium", project_stage, is_file=is_file), 2)
        triggered_rules.append({
            "id": "H15", "name": "评分项证据覆盖不足", "severity": "medium",
            "fallacy_label": RULE_FALLACY_MAP.get("H15", "评分项证据覆盖不足"),
            "explanation": h15.get("explanation", ""),
            "fix_hint": h15.get("fix_hint", ""),
            "matched_keywords": [], "missing_requires": [],
            "preferred_edge_types": RULE_EDGE_MAP.get("H15", []),
            "preferred_strategy_ids": RULE_STRATEGY_MAP.get("H15", []),
            "quote": h15_quote,
            "trigger_message": f"原文整体信息仍偏概括，触发「评分项证据覆盖不足」，因为{h15.get('explanation', '')}",
            "impact": _impact_message("H15", "评分项证据覆盖不足"),
            "fix_task": h15.get("fix_hint", ""),
            "agent_name": _agent_for_rule("H15"),
            "score_impact": -h15_impact,
            "inference_chain": [
                {"step": "input", "text": h15_quote},
                {"step": "evidence_scan", "detail": f"在原文中检索 TAM/访谈/样本等关键词，命中 {evidence_hits} 项"},
                {"step": "rule_trigger", "rule_id": "H15", "rule_name": "评分项证据覆盖不足",
                 "agent": _agent_for_rule("H15"), "severity": "medium"},
                {"step": "score_impact", "delta": -h15_impact, "scope": "overall",
                 "detail": f"扣 {h15_impact:.2f} 分"},
            ],
        })

    unique_triggered = {r["id"]: r for r in triggered_rules}
    triggered_rules = list(unique_triggered.values())

    if competition_type:
        for rule in triggered_rules:
            emphasis = COMPETITION_RULE_EMPHASIS.get(rule["id"], {})
            ctx = emphasis.get(competition_type, "")
            if ctx:
                rule["competition_context"] = ctx

    for rule in triggered_rules:
        task = _suggest_next_task(rule["id"])
        rule["linked_task"] = {
            "title": task.get("title", ""),
            "description": task.get("description", ""),
            "acceptance_criteria": task.get("acceptance_criteria", []),
            "template_guideline": task.get("template_guideline", []),
        }

    # ── LLM-based scoring: uploaded files OR substantial project text ──
    llm_scores = None
    _use_llm = (is_file and text_len > 200) or (text_len > 400 and project_stage not in ("idea",))
    if _use_llm:
        llm_scores = _llm_rubric_score(input_text, mode)

    rubric: list[dict] = []
    weighted_total = 0.0
    total_weight = 0.0

    if llm_scores:
        llm_map = {s["item"]: s for s in llm_scores}
        _default_by_stage = {"idea": 2.0, "structured": 3.5, "validated": 4.5, "document": 5.0}
        fallback_score = _default_by_stage.get(project_stage, 3.0)
        for row in active_rubrics:
            llm_s = llm_map.get(row["item"])
            # 本维度 signals 强证据 bonus
            sig_bonus_llm = 0.0
            for r_id in row.get("rules", []):
                sv = float(structured_signals.get(r_id, 0.0) or 0.0)
                if sv >= 0.7:
                    sig_bonus_llm += 0.6
                elif sv >= 0.5:
                    sig_bonus_llm += 0.3
            sig_bonus_llm = min(sig_bonus_llm, 1.5)
            # 命中/缺失证据（LLM 分支也给出，便于前端展示）
            matched_evidence_llm = [kw for kw in row["evidence"] if kw.lower() in normalized_text]
            missing_evidence_llm = [kw for kw in row["evidence"] if kw.lower() not in normalized_text]
            dim_rules_llm = [r for r in triggered_rules if r["id"] in row["rules"]]
            if llm_s:
                base_llm = float(llm_s.get("score", fallback_score))
                dim_score = max(0.0, min(10.0, base_llm + sig_bonus_llm))
                reason = llm_s.get("reason", "")
                if sig_bonus_llm > 0.2:
                    reason = (reason + "；" if reason else "") + f"财务模块量化证据(+{round(sig_bonus_llm, 1)})"
                rubric.append({
                    "item": row["item"],
                    "score": round(dim_score, 2),
                    "status": "risk" if dim_score < 5.0 else "ok",
                    "weight": row["weight"],
                    "reason": reason,
                    "source": "llm",
                    "base_score": round(base_llm, 2),
                    "signal_bonus": round(sig_bonus_llm, 2),
                    "rule_penalty": 0.0,
                    "length_bonus": 0.0,
                    "evidence_bonus": 0.0,
                    "matched_evidence": matched_evidence_llm,
                    "missing_evidence": missing_evidence_llm,
                    "dim_rules": [{"id": r["id"], "name": r["name"], "severity": r.get("severity", "")} for r in dim_rules_llm],
                    "evidence_chain": get_rubric_evidence_chain(row["item"]),
                    "common_mistakes": get_rubric_error_pool(row["item"]),
                })
            else:
                final_fallback = min(10.0, fallback_score + sig_bonus_llm)
                reason = f"LLM 未对该维度评分，按项目阶段({project_stage})默认 {fallback_score} 分"
                if sig_bonus_llm > 0.2:
                    reason += f"；+ 财务模块证据({round(sig_bonus_llm, 1)})"
                rubric.append({
                    "item": row["item"],
                    "score": round(final_fallback, 2),
                    "status": "risk" if final_fallback < 5.0 else "ok",
                    "weight": row["weight"],
                    "reason": reason,
                    "source": "stage_default",
                    "base_score": round(fallback_score, 2),
                    "signal_bonus": round(sig_bonus_llm, 2),
                    "rule_penalty": 0.0,
                    "length_bonus": 0.0,
                    "evidence_bonus": 0.0,
                    "matched_evidence": matched_evidence_llm,
                    "missing_evidence": missing_evidence_llm,
                    "dim_rules": [{"id": r["id"], "name": r["name"], "severity": r.get("severity", "")} for r in dim_rules_llm],
                })
            weighted_total += rubric[-1]["score"] * row["weight"]
            total_weight += row["weight"]
    else:
        length_bonus = min(1.0, text_len / 2200) if is_file else min(0.6, text_len / 700)
        for row in active_rubrics:
            ev_score = _evidence_score(normalized_text, row["evidence"], stage=project_stage, is_file=is_file)
            matched_evidence = [kw for kw in row["evidence"] if kw.lower() in normalized_text]
            missing_evidence = [kw for kw in row["evidence"] if kw.lower() not in normalized_text]
            dim_rules = [r for r in triggered_rules if r["id"] in row["rules"]]
            # ── 外部结构化证据：命中规则的 signals 越高，penalty 越小 ──
            penalties = 0.0
            for r in dim_rules:
                base_pen = _rule_penalty(r["severity"], project_stage, is_file=is_file)
                sig_val = float(structured_signals.get(r["id"], 0.0) or 0.0)
                if sig_val >= 0.7:
                    base_pen *= 0.25  # 已经有深度财务证据，仅保留 25% 扣分
                elif sig_val >= 0.5:
                    base_pen *= 0.55
                elif sig_val >= 0.3:
                    base_pen *= 0.8
                penalties += base_pen
            penalties = min(penalties, 1.15 if project_stage == "idea" else 1.45 if project_stage == "structured" else 1.8)
            # ── 未命中规则，也可以通过 signals 反向加分（该维度关联的规则里有强证据）──
            signal_bonus = 0.0
            for r_id in row.get("rules", []):
                if r_id in [r["id"] for r in dim_rules]:
                    continue  # 已在 penalty 里处理
                sig_val = float(structured_signals.get(r_id, 0.0) or 0.0)
                if sig_val >= 0.7:
                    signal_bonus += 0.9
                elif sig_val >= 0.5:
                    signal_bonus += 0.5
            signal_bonus = min(signal_bonus, 2.0)
            dim_score = max(0.0, min(10.0, ev_score + length_bonus + signal_bonus - penalties))

            if dim_rules:
                reason = "；".join(
                    f"触发{r['name']}(-{round(_rule_penalty(r['severity'], project_stage, is_file=is_file), 1)})"
                    for r in dim_rules[:2]
                )
            elif len(matched_evidence) >= len(row["evidence"]) * 0.6:
                reason = f"证据较充分，覆盖了{', '.join(matched_evidence[:3])}"
            elif missing_evidence:
                reason = f"缺少{', '.join(missing_evidence[:3])}相关证据"
            else:
                reason = ""
            if signal_bonus > 0.1:
                reason = (reason + "；" if reason else "") + f"财务分析模块已补充量化证据(+{round(signal_bonus, 1)})"

            rubric.append({
                "item": row["item"],
                "score": round(dim_score, 2),
                "status": "risk" if dim_score < 5.0 else "ok",
                "weight": row["weight"],
                "reason": reason,
                "source": "rule_based",
                "base_score": round(ev_score, 2),
                "evidence_bonus": round(ev_score, 2),
                "length_bonus": round(length_bonus, 2),
                "signal_bonus": round(signal_bonus, 2),
                "rule_penalty": round(penalties, 2),
                "matched_evidence": matched_evidence,
                "missing_evidence": missing_evidence,
                "dim_rules": [{"id": r["id"], "name": r["name"], "severity": r.get("severity", "")} for r in dim_rules],
                "evidence_chain": get_rubric_evidence_chain(row["item"]),
                "common_mistakes": get_rubric_error_pool(row["item"]),
            })
            weighted_total += dim_score * row["weight"]
            total_weight += row["weight"]

    # ── 给每个 rubric 条目挂 rationale：解释这一维度分数的计算来源 ──
    stage_label_cn = {
        "idea": "想法萌芽期",
        "structured": "结构化阶段",
        "validated": "已验证阶段",
        "document": "文档化阶段",
    }.get(project_stage, f"阶段 {project_stage}")
    # 按 rule_id 快速找到 triggered rule（为了拿 quote / agent_name）
    triggered_rule_by_id = {tr["id"]: tr for tr in triggered_rules}
    active_rubrics_by_item = {row["item"]: row for row in active_rubrics}
    for r_entry in rubric:
        row = active_rubrics_by_item.get(r_entry["item"], {})
        linked_rules = [
            {"rule_id": tr["id"], "rule_name": tr["name"], "impact": tr.get("score_impact", 0)}
            for tr in triggered_rules if tr["id"] in (row.get("rules") or [])
        ][:4]
        base_score = float(r_entry.get("base_score", 0.0) or 0.0)
        signal_bonus = float(r_entry.get("signal_bonus", 0.0) or 0.0)
        length_bonus = float(r_entry.get("length_bonus", 0.0) or 0.0)
        rule_penalty = float(r_entry.get("rule_penalty", 0.0) or 0.0)
        matched_ev = r_entry.get("matched_evidence") or []
        missing_ev = r_entry.get("missing_evidence") or []
        src = r_entry.get("source", "unknown")

        # ── 构造 reasoning_steps（推理链）：一条条交代这个分怎么来的 ──
        reasoning_steps: list[dict] = []
        if src == "llm":
            reasoning_steps.append({
                "kind": "base",
                "label": f"LLM 按「{stage_label_cn}」对该维度评分",
                "delta": round(base_score, 2),
                "detail": f"基础分 {base_score:.2f}",
            })
        elif src == "stage_default":
            reasoning_steps.append({
                "kind": "base",
                "label": f"LLM 未对该维度打分，按阶段「{stage_label_cn}」默认值",
                "delta": round(base_score, 2),
                "detail": f"阶段默认 {base_score:.2f}",
            })
        else:
            reasoning_steps.append({
                "kind": "base",
                "label": f"证据覆盖基线（阶段：{stage_label_cn}）",
                "delta": round(base_score, 2),
                "detail": f"基于文本命中关键词评估，基础 {base_score:.2f}",
            })
            if length_bonus > 0.05:
                reasoning_steps.append({
                    "kind": "adjust",
                    "label": "文本长度达标",
                    "delta": round(length_bonus, 2),
                    "detail": f"文本完整度加成 +{length_bonus:.2f}",
                })
        for kw in matched_ev[:4]:
            reasoning_steps.append({
                "kind": "evidence",
                "label": f"命中关键证据「{kw}」",
                "delta": 0.0,
                "severity": "info",
                "detail": "文本中检测到相关表述",
            })
        if signal_bonus > 0.05:
            reasoning_steps.append({
                "kind": "evidence",
                "label": "财务/量化模块补充证据",
                "delta": round(signal_bonus, 2),
                "severity": "info",
                "detail": f"外部结构化信号加成 +{signal_bonus:.2f}",
            })
        for lr in linked_rules:
            imp = float(lr.get("impact", 0.0) or 0.0)
            tr = triggered_rule_by_id.get(lr["rule_id"], {})
            reasoning_steps.append({
                "kind": "rule",
                "label": f"触发风险 {lr['rule_id']}·{lr['rule_name']}",
                "delta": round(imp, 2),
                "severity": tr.get("severity", "medium"),
                "agent_name": tr.get("agent_name", ""),
                "quote": (tr.get("quote") or "")[:120],
                "detail": tr.get("explanation", "") or tr.get("trigger_message", ""),
            })
        if not linked_rules and missing_ev and src == "rule_based":
            reasoning_steps.append({
                "kind": "adjust",
                "label": f"尚未出现「{ '、'.join(missing_ev[:3]) }」相关证据",
                "delta": 0.0,
                "detail": "未额外加分也未扣分",
            })
        if rule_penalty > 0.05:
            reasoning_steps.append({
                "kind": "adjust",
                "label": f"以上扣分合计",
                "delta": -round(rule_penalty, 2),
                "detail": f"扣分累计 {rule_penalty:.2f} 分",
            })

        # 基于 reasoning_steps 渲染 formula_display（保留旧 lines 形态，兼容老前端）
        lines: list[str] = [f"{r_entry['item']} = {r_entry['score']:.2f} / 10"]
        for st in reasoning_steps:
            kd = st.get("kind", "")
            lb = st.get("label", "")
            dt = st.get("delta", 0)
            try:
                dtf = float(dt)
            except Exception:
                dtf = 0.0
            if kd in ("base", "baseline"):
                lines.append(f"  基线 · {lb} = {dtf:.2f}")
            elif kd == "evidence":
                lines.append(f"  +证据 · {lb}" + (f"  +{dtf:.2f}" if abs(dtf) > 0.01 else ""))
            elif kd == "rule":
                lines.append(f"  ⚠ 规则 · {lb}  {dtf:+.2f}")
            elif kd == "adjust":
                if abs(dtf) > 0.01:
                    lines.append(f"  调整 · {lb}  {dtf:+.2f}")
                else:
                    lines.append(f"  说明 · {lb}")
        lines.append(f"→ 最终 {r_entry['score']:.2f}")

        r_entry["rationale"] = {
            "field": f"rubric:{r_entry['item']}",
            "value": r_entry["score"],
            "formula": "base_evidence + bonuses − rule_penalties",
            "formula_display": "\n".join(lines),
            "reasoning_steps": reasoning_steps,
            "inputs": (
                [
                    {"label": "基础分", "value": round(base_score, 2),
                     "impact": f"+{base_score:.2f}"},
                ]
                + ([{"label": "文本长度", "value": round(length_bonus, 2),
                     "impact": f"+{length_bonus:.2f}"}] if length_bonus > 0.05 else [])
                + ([{"label": "量化证据", "value": round(signal_bonus, 2),
                     "impact": f"+{signal_bonus:.2f}"}] if signal_bonus > 0.05 else [])
                + [
                    {"label": f"风险 {r['rule_id']}", "value": r["rule_name"],
                     "rule_id": r["rule_id"], "impact": f"{r['impact']:+.2f}"}
                    for r in linked_rules
                ]
                + [{"label": "权重", "value": row.get("weight", 1.0),
                    "impact": f"×{row.get('weight', 1.0)}"}]
            ),
            "contributing_evidence": [
                {"excerpt": (triggered_rule_by_id.get(r["rule_id"], {}).get("quote") or "")[:120],
                 "rule_id": r["rule_id"],
                 "agent": triggered_rule_by_id.get(r["rule_id"], {}).get("agent_name", ""),
                 "impact": f"{r['impact']:+.2f}"}
                for r in linked_rules if triggered_rule_by_id.get(r["rule_id"], {}).get("quote")
            ],
            "note": f"阶段：{stage_label_cn} · 来源：{src}",
        }

    overall_raw = round(weighted_total / total_weight, 2) if total_weight else 0.0
    stage_floor = {"idea": 1.5, "structured": 3.0, "validated": 5.0, "document": 5.5}.get(project_stage, 2.5)
    stage_ceiling = {"idea": 7.5, "structured": 9.0, "validated": 9.6, "document": 9.8}.get(project_stage, 8.5)
    overall_score = round(min(stage_ceiling, max(stage_floor, overall_raw)), 2)
    source_breakdown: dict[str, int] = {}
    for r in rubric:
        key = str(r.get("source", "unknown"))
        source_breakdown[key] = source_breakdown.get(key, 0) + 1
    logger.info(
        "[diagnosis] stage=%s mode=%s comp=%s len=%d raw=%.2f clipped=%.2f floor=%.2f ceil=%.2f source=%s rules=%d",
        project_stage, mode, competition_type, text_len,
        overall_raw, overall_score, stage_floor, stage_ceiling,
        source_breakdown, len(triggered_rules),
    )
    high_rules = [r for r in triggered_rules if r["severity"] == "high"]
    primary_rule = high_rules[0]["id"] if high_rules else (triggered_rules[0]["id"] if triggered_rules else "NONE")

    # ── bottleneck + rationale ──
    bottleneck_steps: list[dict] = []
    lowest_rubric = min(rubric, key=lambda r: float(r.get("score", 10.0))) if rubric else None
    if high_rules:
        bottleneck = f"当前最高风险为 {high_rules[0]['id']}（{high_rules[0]['name']}），会直接影响项目落地可行性。"
        bottleneck_steps.append({
            "kind": "rule",
            "label": f"检测到高严重性风险 {high_rules[0]['id']}·{high_rules[0]['name']}",
            "severity": "critical",
            "agent_name": high_rules[0].get("agent_name", ""),
            "quote": (high_rules[0].get("quote") or "")[:120],
            "detail": high_rules[0].get("explanation", ""),
        })
        if lowest_rubric:
            bottleneck_steps.append({
                "kind": "evidence",
                "label": f"最低维度 {lowest_rubric['item']} = {lowest_rubric['score']:.2f}",
                "detail": "可作为瓶颈突破口",
            })
    elif triggered_rules:
        bottleneck = f"当前主要短板为 {triggered_rules[0]['id']}（{triggered_rules[0]['name']}），需要先补证据。"
        bottleneck_steps.append({
            "kind": "rule",
            "label": f"未检测到高风险，取首条触发规则 {triggered_rules[0]['id']}·{triggered_rules[0]['name']}",
            "severity": triggered_rules[0].get("severity", "medium"),
            "agent_name": triggered_rules[0].get("agent_name", ""),
            "quote": (triggered_rules[0].get("quote") or "")[:120],
        })
        if lowest_rubric:
            bottleneck_steps.append({
                "kind": "evidence",
                "label": f"最低维度 {lowest_rubric['item']} = {lowest_rubric['score']:.2f}",
            })
    else:
        bottleneck = "未检测到高风险规则，建议进入下一轮压力测试和精细化验证。"
        if lowest_rubric:
            bottleneck_steps.append({
                "kind": "evidence",
                "label": f"最低维度 {lowest_rubric['item']} = {lowest_rubric['score']:.2f}（可作为下一轮改进焦点）",
            })
        else:
            bottleneck_steps.append({
                "kind": "base",
                "label": "无规则命中且 rubric 未产出，仅提示继续推进验证",
            })
    bottleneck_rationale = {
        "field": "bottleneck",
        "value": bottleneck,
        "formula": "select_highest_severity_rule ∨ lowest_rubric",
        "formula_display": "\n".join(
            ["瓶颈选择：优先看高风险规则；若无，则看最低 rubric 维度。"]
            + [f"· {s.get('label', '')}" for s in bottleneck_steps]
        ),
        "reasoning_steps": bottleneck_steps,
        "note": f"触发 {len(triggered_rules)} 条规则（高风险 {len(high_rules)} 条）",
    }

    next_task = _suggest_next_task(primary_rule)
    # ── next_task rationale ──
    next_task_steps: list[dict] = []
    if primary_rule == "NONE":
        next_task_steps.append({
            "kind": "base",
            "label": "没有命中规则 → 使用通用下一步任务模板",
            "detail": "建议补齐证据并完成一次压力测试",
        })
    else:
        pr_name = next((r.get("name", "") for r in triggered_rules if r.get("id") == primary_rule), "")
        next_task_steps.append({
            "kind": "base",
            "label": f"以最关键风险 {primary_rule}·{pr_name} 作为任务选取依据",
            "detail": "优先看高严重性规则，若无则取首条命中",
        })
    next_task_steps.append({
        "kind": "evidence",
        "label": f"匹配任务模板 → {next_task.get('title', '')}",
        "detail": next_task.get("description", "")[:120],
    })
    for step in (next_task.get("template_guideline") or [])[:4]:
        next_task_steps.append({
            "kind": "evidence",
            "label": step,
            "severity": "info",
        })
    next_task["rationale"] = {
        "field": "next_task",
        "value": next_task.get("title", ""),
        "formula": "suggest_next_task(primary_rule_id)",
        "formula_display": (
            f"下一步任务 = {next_task.get('title', '')}\n"
            f"依据：{primary_rule}（{'主风险' if primary_rule != 'NONE' else '无风险命中'}）\n"
            f"描述：{(next_task.get('description') or '')[:120]}"
        ),
        "reasoning_steps": next_task_steps,
        "note": f"基于规则 {primary_rule} 触发的任务模板",
    }
    # 将风险规则与 KG 本体节点关联，方便前端/教师追踪“依据从何而来”。
    triggered_with_ontology: list[dict] = []
    for r in triggered_rules:
        nodes = get_rule_ontology_nodes(r.get("id", ""))
        enriched = dict(r)
        if nodes:
            enriched["ontology_nodes"] = nodes
        tasks = get_rule_tasks(r.get("id", ""))
        if tasks:
            enriched["ontology_tasks"] = tasks
        triggered_with_ontology.append(enriched)

    comp_label = {"internet_plus": "互联网+", "challenge_cup": "挑战杯", "dachuang": "大创"}.get(competition_type, "")

    # ── overall rationale：展示加权公式 + 阶段 floor/ceiling 夹子 ──
    overall_inputs: list[dict] = []
    overall_steps: list[dict] = []
    overall_steps.append({
        "kind": "base",
        "label": f"项目阶段=「{stage_label_cn}」，区间基线 [{stage_floor}, {stage_ceiling}]",
        "delta": 0.0,
        "detail": f"项目阶段决定分数最终可接受区间",
    })
    for r_entry in rubric:
        w = float(r_entry.get("weight", 1.0) or 1.0)
        sc = float(r_entry.get("score", 0.0) or 0.0)
        overall_inputs.append({
            "label": f"rubric·{r_entry['item']}",
            "value": round(sc, 2),
            "weight": w,
            "impact": f"+{sc * w:.2f}",
        })
        overall_steps.append({
            "kind": "evidence",
            "label": f"{r_entry['item']} {sc:.2f} × 权重 {w:.2f}",
            "delta": round(sc * w, 2),
            "detail": f"该维度贡献 {sc * w:+.2f}",
        })
    for tr in triggered_with_ontology:
        overall_inputs.append({
            "label": f"风险·{tr['id']}",
            "value": tr.get("name", ""),
            "weight": -1.0,
            "rule_id": tr["id"],
            "impact": f"（已计入单维度扣分）",
        })
        overall_steps.append({
            "kind": "rule",
            "label": f"风险 {tr['id']}·{tr.get('name', '')}（已计入单维度）",
            "delta": 0.0,
            "severity": tr.get("severity", "medium"),
            "agent_name": tr.get("agent_name", ""),
            "quote": (tr.get("quote") or "")[:120],
            "detail": tr.get("impact", ""),
        })
    parts_display = " + ".join(
        f"{r['score']:.1f}×{r.get('weight', 1.0):.1f}" for r in rubric
    ) or "0"
    # 人话版综合分说明
    clip_note = ""
    if overall_raw < stage_floor:
        clip_note = f"原始加权平均 {overall_raw:.2f} 低于阶段下限 {stage_floor}，被抬到 {stage_floor}"
        overall_steps.append({
            "kind": "adjust",
            "label": f"阶段下限夹子 ↑",
            "delta": round(stage_floor - overall_raw, 2),
            "detail": clip_note,
        })
    elif overall_raw > stage_ceiling:
        clip_note = f"原始加权平均 {overall_raw:.2f} 超过阶段上限 {stage_ceiling}，被压到 {stage_ceiling}"
        overall_steps.append({
            "kind": "adjust",
            "label": f"阶段上限夹子 ↓",
            "delta": round(stage_ceiling - overall_raw, 2),
            "detail": clip_note,
        })
    else:
        clip_note = f"原始加权平均 {overall_raw:.2f} 落在阶段区间内，不再修正"
    overall_rationale = {
        "field": "overall",
        "value": overall_score,
        "formula": "clip(Σ(rubric_i × w_i) / Σw_i, stage_floor, stage_ceiling)",
        "formula_display": (
            f"综合分 = 按 9 个维度加权平均后，再夹到阶段允许区间。\n"
            f"项目处于「{stage_label_cn}」→ 区间 [{stage_floor}, {stage_ceiling}]\n"
            f"加权平均 = ({parts_display}) ÷ {total_weight:.1f} = {overall_raw:.2f}\n"
            f"{clip_note}\n"
            f"最终综合分 = {overall_score}"
        ),
        "reasoning_steps": overall_steps,
        "inputs": overall_inputs,
        "note": f"项目阶段 {project_stage} · 触发 {len(triggered_rules)} 条风险",
        "stage_floor": stage_floor,
        "stage_ceiling": stage_ceiling,
        "raw_score": overall_raw,
        "project_stage": project_stage,
        "project_stage_cn": stage_label_cn,
    }

    project_stage_rationale = _build_stage_rationale(project_stage, stage_label_cn, stage_signals)

    summary_text = (
        f"已按 V2.0 规则集完成{'「' + comp_label + '」赛道权重下的' if comp_label else ''}诊断"
        f"（{len(RULES)}条规则 + {len(active_rubrics)}项Rubric）。"
    )
    summary_rationale = {
        "field": "current_summary",
        "value": summary_text,
        "formula": "compose(mode, competition_type, rule_count, rubric_count)",
        "formula_display": (
            f"摘要 = 以 {mode} 模式" + (f"、{comp_label} 赛道权重" if comp_label else "")
            + f"，跑完 {len(RULES)} 条规则 + {len(active_rubrics)} 项 Rubric 后的诊断总览。"
        ),
        "reasoning_steps": [
            {"kind": "base", "label": f"模式 mode = {mode}"},
            {"kind": "evidence", "label": f"赛道 {comp_label or '通用'}"},
            {"kind": "evidence", "label": f"规则库 {len(RULES)} 条 + Rubric {len(active_rubrics)} 项"},
            {"kind": "adjust", "label": f"触发 {len(triggered_rules)} 条规则 · 综合分 {overall_score}"},
        ],
        "note": "本摘要是自动生成的诊断总览，可被老师订正。",
    }

    diagnosis = {
        "mode": mode,
        "competition_type": competition_type,
        "overall_score": overall_score,
        "score_band": _score_band(overall_score),
        "overall_rationale": overall_rationale,
        "project_stage": project_stage,
        "project_stage_rationale": project_stage_rationale,
        "bottleneck": bottleneck,
        "bottleneck_rationale": bottleneck_rationale,
        "triggered_rules": triggered_with_ontology,
        "rubric": rubric,
        "capability_map": CAPABILITY_MAP,
        "grading_principles": [
            "先按项目阶段评分，不把早期想法按成熟计划书标准苛评",
            "有初步逻辑但证据未补齐的项目，分数应落在中低段而不是接近零分",
            "高分必须建立在用户证据、市场竞争、商业闭环和执行计划同时较完整之上",
        ],
        "summary": summary_text,
        "summary_rationale": summary_rationale,
        "info_sufficient": True,
    }
    return DiagnosisResult(diagnosis=diagnosis, next_task=next_task)
