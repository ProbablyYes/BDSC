from dataclasses import dataclass
import json
from pathlib import Path

from app.config import settings
from app.services.kg_ontology import (
    get_rule_ontology_nodes,
    get_rule_tasks,
    get_rubric_error_pool,
    get_rubric_evidence_chain,
)


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
]

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
    evidence_hits = sum(1 for k in ["访谈", "问卷", "样本", "数据", "实验", "验证", "原型", "mvp"] if _fuzzy_match(k, text))
    business_hits = sum(1 for k in ["市场规模", "tam", "sam", "som", "定价", "商业模式", "渠道", "收入", "成本"] if _fuzzy_match(k, text))
    execution_hits = sum(1 for k in ["团队", "里程碑", "时间表", "技术路线", "落地", "执行"] if _fuzzy_match(k, text))
    text_len = len(text)

    if is_file and text_len >= 800:
        return "document"
    if evidence_hits >= 4 and business_hits >= 3:
        return "validated"
    if business_hits >= 2 or execution_hits >= 2 or text_len >= 350:
        return "structured"
    return "idea"


def _stage_baseline(stage: str, is_file: bool = False) -> float:
    if is_file:
        return {"document": 5.9, "validated": 5.6, "structured": 5.2, "idea": 4.7}.get(stage, 5.2)
    return {"idea": 4.1, "structured": 5.0, "validated": 5.9, "document": 6.3}.get(stage, 4.8)


def _stage_ceiling(stage: str, is_file: bool = False) -> float:
    if is_file:
        return {"document": 9.3, "validated": 8.8, "structured": 8.2, "idea": 7.5}.get(stage, 8.2)
    return {"idea": 6.9, "structured": 8.1, "validated": 8.9, "document": 9.1}.get(stage, 8.0)


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
    boost = ratio * (3.4 if is_file else 2.8)
    if hit >= 3:
        boost += 0.5
    elif hit == 0:
        boost -= 0.18 if stage == "idea" else 0.45
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
    """Use LLM to intelligently score each rubric dimension for uploaded files."""
    try:
        from app.services.llm_client import LlmClient
        llm = LlmClient()
        if not llm.enabled:
            return None

        rubric_desc = "\n".join(
            f"- {r['item']} (weight {r['weight']}): evidence={r['evidence']}"
            for r in RUBRICS
        )
        result = llm.chat_json(
            system_prompt=(
                "You are a startup project evaluator. Score each rubric dimension 0-10.\n"
                "Be fair and nuanced: a complete business plan typically scores 5-8.\n"
                "Only give <3 if the dimension is completely missing.\n"
                "Only give >8 if there is exceptional evidence.\n\n"
                f"Rubric dimensions:\n{rubric_desc}\n\n"
                'Output JSON: {"scores": [{"item": "...", "score": 0-10, "reason": "one sentence"}]}'
            ),
            user_prompt=f"Evaluate this project content (mode={mode}):\n\n{text[:4000]}",
            temperature=0.2,
        )
        if result and "scores" in result:
            return result["scores"]
    except Exception:
        pass
    return None


def run_diagnosis(input_text: str, mode: str = "coursework") -> DiagnosisResult:
    normalized_text = input_text.lower()
    is_file = "[" + "上传文件:" in input_text
    text_len = len(normalized_text)
    project_stage = _infer_project_stage(normalized_text, is_file=is_file)

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
            })

    evidence_hits = sum(1 for k in ["访谈", "问卷", "tam", "sam", "som", "cac", "ltv", "里程碑", "原型", "内测", "实验"] if _fuzzy_match(k, normalized_text))
    if evidence_hits < 1 and not is_file and text_len > 220 and project_stage != "idea":
        h15 = next((r for r in RULES if r["id"] == "H15"), {})
        triggered_rules.append({
            "id": "H15", "name": "评分项证据覆盖不足", "severity": "medium",
            "fallacy_label": RULE_FALLACY_MAP.get("H15", "评分项证据覆盖不足"),
            "explanation": h15.get("explanation", ""),
            "fix_hint": h15.get("fix_hint", ""),
            "matched_keywords": [], "missing_requires": [],
            "preferred_edge_types": RULE_EDGE_MAP.get("H15", []),
            "preferred_strategy_ids": RULE_STRATEGY_MAP.get("H15", []),
            "quote": re.sub(r"\s+", " ", input_text).strip()[:120],
            "trigger_message": f"原文整体信息仍偏概括，触发「评分项证据覆盖不足」，因为{h15.get('explanation', '')}",
            "impact": _impact_message("H15", "评分项证据覆盖不足"),
            "fix_task": h15.get("fix_hint", ""),
        })

    unique_triggered = {r["id"]: r for r in triggered_rules}
    triggered_rules = list(unique_triggered.values())

    # ── LLM-based scoring for uploaded files ──
    llm_scores = None
    if is_file and text_len > 200:
        llm_scores = _llm_rubric_score(input_text, mode)

    rubric: list[dict] = []
    weighted_total = 0.0
    total_weight = 0.0

    if llm_scores:
        llm_map = {s["item"]: s for s in llm_scores}
        for row in RUBRICS:
            llm_s = llm_map.get(row["item"])
            if llm_s:
                dim_score = max(0.0, min(10.0, float(llm_s.get("score", 5))))
                rubric.append({
                    "item": row["item"],
                    "score": round(dim_score, 2),
                    "status": "risk" if dim_score < 5.0 else "ok",
                    "weight": row["weight"],
                    "reason": llm_s.get("reason", ""),
                    # 结构化证据链 & 常见错误池，保证每个评分维度可追溯
                    "evidence_chain": get_rubric_evidence_chain(row["item"]),
                    "common_mistakes": get_rubric_error_pool(row["item"]),
                })
            else:
                rubric.append({
                    "item": row["item"], "score": 5.0,
                    "status": "ok", "weight": row["weight"],
                })
            weighted_total += rubric[-1]["score"] * row["weight"]
            total_weight += row["weight"]
    else:
        length_bonus = min(1.0, text_len / 2200) if is_file else min(0.6, text_len / 700)
        for row in RUBRICS:
            ev_score = _evidence_score(normalized_text, row["evidence"], stage=project_stage, is_file=is_file)
            penalties = sum(
                _rule_penalty(r["severity"], project_stage, is_file=is_file)
                for r in triggered_rules if r["id"] in row["rules"]
            )
            penalties = min(penalties, 1.15 if project_stage == "idea" else 1.45 if project_stage == "structured" else 1.8)
            dim_score = max(0.0, min(10.0, ev_score + length_bonus - penalties))
            rubric.append({
                "item": row["item"],
                "score": round(dim_score, 2),
                "status": "risk" if dim_score < 5.0 else "ok",
                "weight": row["weight"],
                "evidence_chain": get_rubric_evidence_chain(row["item"]),
                "common_mistakes": get_rubric_error_pool(row["item"]),
            })
            weighted_total += dim_score * row["weight"]
            total_weight += row["weight"]

    overall_score = round(weighted_total / total_weight, 2) if total_weight else 0.0
    stage_floor = {"idea": 4.2, "structured": 5.0, "validated": 5.9, "document": 6.2}.get(project_stage, 4.8)
    stage_ceiling = {"idea": 6.4, "structured": 7.9, "validated": 8.9, "document": 9.3}.get(project_stage, 8.1)
    overall_score = round(min(stage_ceiling, max(stage_floor, overall_score)), 2)
    high_rules = [r for r in triggered_rules if r["severity"] == "high"]
    primary_rule = high_rules[0]["id"] if high_rules else (triggered_rules[0]["id"] if triggered_rules else "NONE")

    if high_rules:
        bottleneck = f"当前最高风险为 {high_rules[0]['id']}（{high_rules[0]['name']}），会直接影响项目落地可行性。"
    elif triggered_rules:
        bottleneck = f"当前主要短板为 {triggered_rules[0]['id']}（{triggered_rules[0]['name']}），需要先补证据。"
    else:
        bottleneck = "未检测到高风险规则，建议进入下一轮压力测试和精细化验证。"

    next_task = _suggest_next_task(primary_rule)
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

    diagnosis = {
        "mode": mode,
        "overall_score": overall_score,
        "score_band": _score_band(overall_score),
        "project_stage": project_stage,
        "bottleneck": bottleneck,
        "triggered_rules": triggered_with_ontology,
        "rubric": rubric,
        "capability_map": CAPABILITY_MAP,
        "grading_principles": [
            "先按项目阶段评分，不把早期想法按成熟计划书标准苛评",
            "有初步逻辑但证据未补齐的项目，分数应落在中低段而不是接近零分",
            "高分必须建立在用户证据、市场竞争、商业闭环和执行计划同时较完整之上",
        ],
        "summary": f"已按 V2.0 规则集完成首轮诊断（{len(RULES)}条规则 + {len(RUBRICS)}项Rubric）。",
        "info_sufficient": True,
    }
    return DiagnosisResult(diagnosis=diagnosis, next_task=next_task)
