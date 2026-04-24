"""
Challenge strategy library: structured Socratic questioning patterns
for the Critic agent. Each strategy has trigger conditions, multi-layer
probing questions, and expected evidence the student should provide.

Based on the requirements doc's "追问策略库" specification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.project_cognition import normalize_track_vector


@dataclass
class ChallengeStrategy:
    id: str
    name: str
    trigger_keywords: list[str]
    trigger_rules: list[str]
    probing_layers: list[str]
    expected_evidence: list[str]
    counterfactual: str
    severity: str = "high"
    applies_to_spectrum: dict[str, tuple[float, float]] = field(default_factory=dict)
    applies_to_stage: list[str] = field(default_factory=list)
    applies_to_competition: list[str] = field(default_factory=list)
    strategy_type: str = "adversarial"


STRATEGIES: list[ChallengeStrategy] = [
    ChallengeStrategy(
        id="CS01",
        name="无竞争对手三层探测",
        trigger_keywords=["无竞争对手", "没有对手", "独一无二", "蓝海", "没人做过"],
        trigger_rules=["H6"],
        probing_layers=[
            "隐形替代品探测: 用户在你的产品出现之前，是怎么解决这个问题的？那个方案就是你的竞争对手。",
            "巨头入场模拟: 如果腾讯/阿里明天做一个一样的功能，他们有什么优势？你的护城河在哪？",
            "成本转换测试: 用户从现有方案切换到你的产品，需要付出什么成本（时间、金钱、学习）？这个成本足够低吗？",
        ],
        expected_evidence=["替代方案分析", "竞品对比矩阵", "用户切换成本评估"],
        counterfactual="如果市场真的是蓝海，为什么没有任何人尝试过？是需求不存在，还是你没看到竞争者？",
    ),
    ChallengeStrategy(
        id="CS02",
        name="1%市场份额幻觉",
        trigger_keywords=["1%", "百分之一", "只要", "中国人", "市场很大"],
        trigger_rules=["H9", "H4"],
        probing_layers=[
            "获客路径验证: 你打算怎么接触到这1%的用户？具体的获客渠道是什么？",
            "单位经济核算: 获取一个用户的成本(CAC)是多少？这个用户一生能给你带来多少收入(LTV)？",
            "增长瓶颈追问: 从0到前100个用户，你的具体计划是什么？不要说'自然增长'。",
        ],
        expected_evidence=["获客渠道和CAC估算", "LTV计算依据", "前100用户获取计划"],
        counterfactual="'只要拿到1%的市场'是创业计划书中最危险的假设。请证明你能拿到第一个1000个付费用户。",
    ),
    ChallengeStrategy(
        id="CS03",
        name="技术门槛幻觉",
        trigger_keywords=["技术壁垒", "门槛极高", "专利保护", "核心算法", "独有技术"],
        trigger_rules=["H7", "H12"],
        probing_layers=[
            "可复制性检验: 一个同等水平的团队，需要多长时间能复现你的核心技术？",
            "技术与需求脱钩检验: 你的技术虽好，但用户真正在乎的是技术本身还是它带来的效果？有更简单的方案能达到80%效果吗？",
            "资源匹配检验: 你的技术路线需要什么资源（GPU、数据、人才）？你团队现在有多少？差距有多大？",
        ],
        expected_evidence=["技术复现时间估算", "用户需求优先级排序", "资源-需求匹配表"],
        counterfactual="如果你的技术优势在12个月后被开源方案追平，你的产品还有存在价值吗？",
    ),
    ChallengeStrategy(
        id="CS04",
        name="需求证据缺失",
        trigger_keywords=["我觉得", "应该需要", "肯定有人", "很多人都"],
        trigger_rules=["H5"],
        probing_layers=[
            "证据来源追问: 你说'很多人需要'，具体跟多少人聊过？他们怎么描述自己的痛点？",
            "付费意愿检验: 他们目前为解决这个问题花了多少钱？如果你的产品定价X元，他们愿意付吗？你怎么知道的？",
            "伪需求识别: 用户说'这个挺好的'和用户说'我愿意每月花200块钱用'是完全不同的信号。你拿到的是哪种？",
        ],
        expected_evidence=[">=5份用户访谈原话", "付费意愿数据", "需求频次统计"],
        counterfactual="如果你的'需求'只来自身边朋友的礼貌性认可，而非真实用户的行为证据，这个项目就建立在沙子上。",
    ),
    ChallengeStrategy(
        id="CS05",
        name="商业模式闭环断裂",
        trigger_keywords=["先免费再收费", "先做大用户量", "流量变现", "羊毛出在猪身上"],
        trigger_rules=["H1", "H2", "H3", "H8"],
        probing_layers=[
            "价值传递检验: 你的产品给用户提供什么价值？这个价值用户自己认可吗？",
            "渠道可达性: 你说通过XX渠道获客，这个渠道的单次触达成本是多少？转化率预期是多少？依据是什么？",
            "收入逻辑检验: '先做大用户再变现'——请给出一个具体的变现时间点和方式。没有变现路径的用户增长是烧钱。",
        ],
        expected_evidence=["价值主张画布", "渠道成本数据", "变现路径和时间表"],
        counterfactual="如果你的免费用户永远不转化为付费用户，公司的现金流能撑多久？",
    ),
    ChallengeStrategy(
        id="CS06",
        name="里程碑过度乐观",
        trigger_keywords=["一个月内", "三个月完成", "快速上线", "马上就能"],
        trigger_rules=["H10"],
        probing_layers=[
            "任务拆解检验: 你说'三个月完成MVP'，请把这三个月拆成每周的任务清单。每周交付什么？",
            "资源瓶颈检验: 完成这些任务需要几个人？什么技能？你现在有这些人吗？",
            "风险缓冲检验: 如果核心开发人员离队，或者技术方案走不通，你的Plan B是什么？",
        ],
        expected_evidence=["每周级别的任务拆解", "团队能力矩阵", "风险预案"],
        counterfactual="如果每个任务实际耗时是预期的2倍（这在创业中是常态），你的时间线还成立吗？",
    ),
    ChallengeStrategy(
        id="CS07",
        name="合规伦理盲区",
        trigger_keywords=["用户数据", "隐私", "人脸识别", "个人信息", "医疗数据"],
        trigger_rules=["H11"],
        probing_layers=[
            "数据合规检验: 你收集哪些用户数据？存储在哪里？用户是否明确同意？依据什么法规？",
            "伦理风险检验: 你的产品如果被滥用，最坏情况是什么？你有什么防范措施？",
            "监管预判: 如果相关监管政策收紧（参考教育双减、医疗AI审查），你的产品还能运营吗？",
        ],
        expected_evidence=["数据流向图", "隐私协议草案", "监管风险评估"],
        counterfactual="如果个人信息保护法要求你删除所有用户数据，你的商业模式是否还成立？",
    ),
    ChallengeStrategy(
        id="CS08",
        name="定价无支撑",
        trigger_keywords=["定价", "收费", "订阅", "付费"],
        trigger_rules=["H3"],
        probing_layers=[
            "支付意愿检验: 你的定价依据是什么？做过价格敏感性测试吗？",
            "竞品定价对比: 类似产品的市场价格区间是多少？你比他们贵还是便宜？为什么？",
            "价格弹性检验: 如果价格上涨50%，你预计流失多少用户？如果下降50%，能多获取多少？",
        ],
        expected_evidence=["价格测试数据", "竞品定价对比表", "价格弹性分析"],
        counterfactual="如果用户觉得你的产品值0元（因为有免费替代品），你怎么说服他们付费？",
    ),
    ChallengeStrategy(
        id="CS09",
        name="创新点不可验证",
        trigger_keywords=["颠覆", "革命性", "全球首创", "行业领先"],
        trigger_rules=["H7"],
        probing_layers=[
            "实验设计检验: 你怎么证明你的创新确实有效？有没有对照实验或A/B测试？",
            "效果量化检验: '提升效率'——提升多少？跟什么基线比？测试样本有多大？",
            "可复现性检验: 别人按照你的方法能得到同样的结果吗？",
        ],
        expected_evidence=["实验/测试数据", "效果量化指标", "对照组结果"],
        counterfactual="如果严格测试后发现效果提升不到5%，你的'颠覆性创新'叙事还站得住吗？",
    ),
    ChallengeStrategy(
        id="CS10",
        name="TAM/SAM/SOM混乱",
        trigger_keywords=["万亿市场", "千亿规模", "市场巨大"],
        trigger_rules=["H4"],
        probing_layers=[
            "口径检验: 你说的市场规模是TAM还是SAM？你实际能触达的市场(SOM)有多大？",
            "自下而上估算: 请用'单价×目标用户数×复购频次'来估算你第一年的实际可获得市场。",
            "增长合理性: 从SOM到SAM，你的增长路径是什么？每一步需要什么资源？",
        ],
        expected_evidence=["TAM/SAM/SOM三层估算", "自下而上的市场测算", "增长路径规划"],
        counterfactual="一个万亿的TAM对你毫无意义——关键是你第一年能从中切到多少。",
    ),
    ChallengeStrategy(
        id="CS11",
        name="免费模式盈利幻觉",
        trigger_keywords=["免费", "不收钱", "先免费", "免费用户"],
        trigger_rules=["H3", "H8"],
        probing_layers=[
            "免费阶段的目标是什么？是为了获取数据、用户还是口碑？对应的量化指标是什么？",
            "当你开始收费时，用户为什么不会流失到仍然免费的替代方案？",
            "如果永远无法向当前用户群收费，你的商业模式还有哪些备选路径？",
        ],
        expected_evidence=["免费转付费路径图", "竞品收费/免费对比", "不同定价方案的敏感性测试结果"],
        counterfactual="如果所有核心功能都长期免费且没有清晰的变现路径，这更像是一个公益项目而非可持续的创业项目。",
    ),
    ChallengeStrategy(
        id="CS12",
        name="平台化过度扩张",
        trigger_keywords=["生态", "平台", "闭环生态", "全链路"],
        trigger_rules=["H1", "H9"],
        probing_layers=[
            "你当前阶段的最小可行产品（MVP）只解决哪一个最具体的场景？请避免一次性覆盖整条价值链。",
            "从单点工具到平台生态，中间至少要经历哪3个可验证的阶段？每个阶段的核心指标是什么？",
            "如果你只允许做一件事做到极致（而不是做平台），你会选哪件事？为什么？",
        ],
        expected_evidence=["单点MVP定义", "阶段性产品路线图", "每阶段的北极星指标设计"],
        counterfactual="过早谈平台和生态，往往意味着对单点价值和执行路径还没有想清楚。",
    ),
    ChallengeStrategy(
        id="CS13",
        name="数据驱动口号化",
        trigger_keywords=["数据驱动", "AI决策", "智能推荐", "算法优化"],
        trigger_rules=["H7", "H13"],
        probing_layers=[
            "目前你真正可用的数据有哪些？规模、多样性和更新频率分别如何？",
            "如果暂时不用任何复杂算法，只用简单规则或人工判断，效果会差多少？有没有做过对比？",
            "哪些关键业务决策必须依赖算法，哪些其实只要有基本统计分析就足够？",
        ],
        expected_evidence=["现有数据清单", "算法vs规则的效果对比", "关键决策点与所需数据/算法映射"],
        counterfactual="如果暂时无法获取大规模高质量数据，你现在的方案是否还能正常运转？",
    ),
    ChallengeStrategy(
        id="CS14",
        name="团队结构关键角色缺失",
        trigger_keywords=["我们会找", "外包", "有很多同学", "学校会支持"],
        trigger_rules=["H10", "H12"],
        probing_layers=[
            "项目的3个关键岗位分别是什么？目前这些岗位对应的是哪几位具体同学或导师？",
            "如果外部合作方/外包团队退出，你们内部是否有人可以暂时接手关键工作？",
            "未来6个月最难招到的关键人才是谁？如果始终招不到，这个项目还能怎么调整？",
        ],
        expected_evidence=["关键岗位清单及责任人", "内部与外部资源的备份方案", "未来人才需求与风险评估"],
        counterfactual="如果现在的团队在未来半年内无法扩张，你们是否仍然有办法达成既定里程碑？",
    ),
    ChallengeStrategy(
        id="CS15",
        name="增长黑客万能药幻觉",
        trigger_keywords=["增长黑客", "裂变海报", "私域流量", "投放一点广告"],
        trigger_rules=["H2", "H9"],
        probing_layers=[
            "你具体设计过哪一个完整的增长实验？从假设、实验设计到评价指标分别是什么？",
            "如果第一次投放/裂变效果远低于预期，你的迭代策略是什么？会调整哪3个变量？",
            "请给出一个你认为最有潜力的增长杠杆，并估算它在现实约束下的上限效果。",
        ],
        expected_evidence=["至少1个完整增长实验闭环", "增长实验数据记录", "主要增长杠杆及其上限估算"],
        counterfactual="没有经过严谨设计和验证的'增长黑客'，通常只是换了一种说法的'多发几条朋友圈'。",
    ),
    ChallengeStrategy(
        id="CS16",
        name="公益影响力量化缺口",
        trigger_keywords=["社会价值", "公益", "帮助别人", "社会影响", "受益人"],
        trigger_rules=[],
        probing_layers=[
            "你说这个项目有社会价值，具体改变了谁的什么结果？有没有一个改变前后可以比较的指标？",
            "如果评委追问'为什么这不是一项善意活动而是一个可评估的项目'，你会拿出什么证据？",
            "除了受益人数量，你还能用什么指标证明影响质量，而不是只证明覆盖范围？",
        ],
        expected_evidence=["受益人画像", "影响指标定义", "改变前后对比数据或原话"],
        counterfactual="如果无法定义影响力，你就很难证明这个项目真正缓解了社会问题，而不是只传递了善意。",
        severity="medium",
        applies_to_spectrum={"biz_public": (0.3, 1.0)},
        applies_to_stage=["idea", "structured", "validated"],
        strategy_type="socratic",
    ),
    ChallengeStrategy(
        id="CS17",
        name="公益持续资金追问",
        trigger_keywords=["资助", "可持续", "基金会", "政府支持", "长期运营"],
        trigger_rules=[],
        probing_layers=[
            "如果项目不靠盈利，未来3年的主要资金来源分别是什么？是单一依赖，还是多元结构？",
            "谁是真正的支付/资助方？他们为什么愿意持续买单？你能给他们什么可复命的结果？",
            "如果当前最关键的资助渠道消失，这个项目还能以什么方式继续活下去？",
        ],
        expected_evidence=["资金来源结构图", "支付/资助方清单", "持续运营假设"],
        counterfactual="没有持续资金结构的公益项目，往往只能依靠创始人热情短暂存在。",
        severity="high",
        applies_to_spectrum={"biz_public": (0.4, 1.0)},
        applies_to_stage=["structured", "validated", "scale"],
        strategy_type="adversarial",
    ),
    ChallengeStrategy(
        id="CS18",
        name="创新点锚定与对照组校验",
        trigger_keywords=["创新", "首创", "原创", "突破", "新方法"],
        trigger_rules=[],
        probing_layers=[
            "你说这个方案有创新性，它相对最接近的已有方案到底多了哪一个可验证增量？",
            "如果评委让你给出 baseline，你会拿哪个现有方案做对照？为什么？",
            "去掉'首创/突破'这些词后，你还能用什么指标证明这个创新不是口号？",
        ],
        expected_evidence=["baseline 选择理由", "对照指标", "创新增量说明"],
        counterfactual="如果说不清相对谁而新，创新性很容易变成学生主观感受，而不是可评估结论。",
        severity="high",
        applies_to_spectrum={"innov_venture": (-1.0, -0.25)},
        applies_to_stage=["idea", "structured", "validated"],
        strategy_type="adversarial",
    ),
    ChallengeStrategy(
        id="CS19",
        name="研究到产品跳跃校验",
        trigger_keywords=["论文", "算法", "模型", "科研", "落地"],
        trigger_rules=[],
        probing_layers=[
            "你的技术成果转成产品后，用户真正感知到的价值是什么？这一步有没有被证明？",
            "如果技术效果成立但用户体验很差，项目还能成立吗？你准备怎么验证这两条线？",
            "研究问题和产品问题分别是什么？现在是不是只证明了前者，还没证明后者？",
        ],
        expected_evidence=["技术验证结果", "用户价值验证", "研究问题/产品问题拆分"],
        counterfactual="很多项目不是技术不行，而是把“研究成立”误以为“产品成立”。",
        severity="medium",
        applies_to_spectrum={"innov_venture": (-0.6, 0.2)},
        applies_to_stage=["validated", "scale"],
        strategy_type="socratic",
    ),
    ChallengeStrategy(
        id="CS20",
        name="想法期过早收敛防护",
        trigger_keywords=["已经决定", "就做这个", "方案已定", "最后选了", "不考虑别的"],
        trigger_rules=["H_PREMATURE_LOCK"],
        probing_layers=[
            "你在锁定这个方向之前对比过哪几种方案？为什么另外几种被排除了？",
            "如果6周后发现当前核心假设不成立，你准备通过什么信号尽快知道，而不是越做越深？",
            "现在最不确定的一点是什么？有没有一个100元、3天内能做完的小实验去先证伪它？",
        ],
        expected_evidence=["备选方向对比", "关键假设清单", "最小证伪实验"],
        counterfactual="想法期最大的风险往往不是选错，而是锁定太早，放弃了还没展开的搜索空间。",
        severity="medium",
        applies_to_stage=["idea"],
        strategy_type="socratic",
    ),
]


def _load_teacher_overrides() -> dict:
    """Load optional teacher override configuration for challenge strategies."""
    try:
        cfg_dir = settings.workspace_root / "config"
        overrides_path = cfg_dir / "teacher_overrides.json"
        if not overrides_path.exists():
            return {}
        data = json.loads(overrides_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _apply_strategy_overrides(
    strategies: list[ChallengeStrategy], overrides: list[dict] | None
) -> list[ChallengeStrategy]:
    if not overrides:
        return strategies
    by_id: dict[str, ChallengeStrategy] = {s.id: s for s in strategies}
    for ov in overrides:
        sid = str(ov.get("id") or "").strip()
        if not sid:
            continue
        base = by_id.get(sid)
        if base is None:
            # New strategy provided entirely by configuration.
            try:
                by_id[sid] = ChallengeStrategy(
                    id=sid,
                    name=str(ov.get("name", sid)),
                    trigger_keywords=list(ov.get("trigger_keywords", [])),
                    trigger_rules=list(ov.get("trigger_rules", [])),
                    probing_layers=list(ov.get("probing_layers", [])),
                    expected_evidence=list(ov.get("expected_evidence", [])),
                    counterfactual=str(ov.get("counterfactual", "")),
                    severity=str(ov.get("severity", "high")),
                    applies_to_spectrum=dict(ov.get("applies_to_spectrum", {})),
                    applies_to_stage=list(ov.get("applies_to_stage", [])),
                    applies_to_competition=list(ov.get("applies_to_competition", [])),
                    strategy_type=str(ov.get("strategy_type", "adversarial")),
                )
            except Exception:  # noqa: BLE001
                continue
        else:
            # Patch existing strategy fields; unspecified fields保持原值。
            try:
                by_id[sid] = ChallengeStrategy(
                    id=sid,
                    name=str(ov.get("name", base.name)),
                    trigger_keywords=list(ov.get("trigger_keywords", base.trigger_keywords)),
                    trigger_rules=list(ov.get("trigger_rules", base.trigger_rules)),
                    probing_layers=list(ov.get("probing_layers", base.probing_layers)),
                    expected_evidence=list(ov.get("expected_evidence", base.expected_evidence)),
                    counterfactual=str(ov.get("counterfactual", base.counterfactual)),
                    severity=str(ov.get("severity", base.severity)),
                    applies_to_spectrum=dict(ov.get("applies_to_spectrum", base.applies_to_spectrum)),
                    applies_to_stage=list(ov.get("applies_to_stage", base.applies_to_stage)),
                    applies_to_competition=list(ov.get("applies_to_competition", base.applies_to_competition)),
                    strategy_type=str(ov.get("strategy_type", base.strategy_type)),
                )
            except Exception:  # noqa: BLE001
                continue
    return list(by_id.values())


_OVERRIDES = _load_teacher_overrides()
STRATEGIES = _apply_strategy_overrides(STRATEGIES, _OVERRIDES.get("challenge_strategies"))

_STRATEGY_BY_ID: dict[str, ChallengeStrategy] = {s.id: s for s in STRATEGIES}
_STRATEGY_BY_RULE: dict[str, list[ChallengeStrategy]] = {}
for _s in STRATEGIES:
    for _r in _s.trigger_rules:
        _STRATEGY_BY_RULE.setdefault(_r, []).append(_s)

_STRATEGY_EDGE_PREFS: dict[str, list[str]] = {
    "CS01": ["Market_Competition_Edge", "Risk_Pattern_Edge", "Value_Loop_Edge"],
    "CS02": ["Market_Competition_Edge", "Risk_Pattern_Edge", "Evidence_Grounding_Edge"],
    "CS03": ["Innovation_Validation_Edge", "Execution_Gap_Edge", "Value_Loop_Edge"],
    "CS04": ["User_Pain_Fit_Edge", "Evidence_Grounding_Edge", "Value_Loop_Edge"],
    "CS05": ["Value_Loop_Edge", "Execution_Gap_Edge", "Evidence_Grounding_Edge"],
    "CS06": ["Execution_Gap_Edge", "Risk_Pattern_Edge"],
    "CS07": ["Compliance_Safety_Edge", "Risk_Pattern_Edge", "Evidence_Grounding_Edge"],
    "CS08": ["Evidence_Grounding_Edge", "Market_Competition_Edge", "Value_Loop_Edge"],
    "CS09": ["Innovation_Validation_Edge", "Evidence_Grounding_Edge"],
    "CS10": ["Market_Competition_Edge", "Risk_Pattern_Edge", "Evidence_Grounding_Edge"],
}

_STRATEGY_FALLACY_PREFS: dict[str, list[str]] = {
    "CS01": ["无竞争对手谬误", "替代方案盲区", "迁移成本盲区"],
    "CS02": ["大数幻觉谬误", "市场规模口径谬误", "可触达市场缺失"],
    "CS03": ["资源错配风险", "技术门槛幻觉", "创新点不可验证"],
    "CS04": ["需求证据不足", "证据覆盖不足", "证据与结论错配"],
    "CS05": ["单位经济未证成", "客群与价值错位", "用户价值与收入混淆"],
    "CS06": ["执行过度乐观", "执行责任不清"],
    "CS07": ["合规伦理缺口", "风险控制空泛"],
    "CS08": ["定价无支撑"],
    "CS09": ["创新点不可验证", "实验设计失真", "创新价值脱节"],
    "CS10": ["市场规模口径谬误", "大数幻觉谬误", "可触达市场缺失"],
}

_STRATEGY_LOGIC: dict[str, str] = {
    "CS01": "广义竞争逻辑 + 隐形替代方案 + 迁移成本逻辑",
    "CS02": "精准获客逻辑 + CAC/LTV 逻辑 + 自下而上市场估算",
    "CS03": "技术可复制性逻辑 + 资源匹配逻辑",
    "CS04": "需求证据逻辑 + 支付意愿检验",
    "CS05": "价值闭环逻辑 + 现金流生存逻辑",
    "CS06": "执行拆解逻辑 + 负责人校验",
    "CS07": "合规边界逻辑 + 最坏情境预判",
    "CS08": "价格敏感度逻辑 + 免费替代品比较",
    "CS09": "实验验证逻辑 + 对照组意识",
    "CS10": "TAM/SAM/SOM 口径校验 + 增长合理性",
}


def _in_spectrum_window(strategy: ChallengeStrategy, track_vector: dict[str, Any] | None) -> bool:
    if not strategy.applies_to_spectrum:
        return True
    tv = normalize_track_vector(track_vector)
    for axis, window in strategy.applies_to_spectrum.items():
        if not isinstance(window, (list, tuple)) or len(window) != 2:
            continue
        try:
            low = float(window[0])
            high = float(window[1])
            value = float(tv.get(axis, 0.0) or 0.0)
        except Exception:
            continue
        if value < low or value > high:
            return False
    return True


def select_probing_strategies(
    text: str,
    *,
    triggered_rule_ids: list[str] | None = None,
    fallacy_label: str = "",
    edge_types: list[str] | None = None,
    track_vector: dict[str, Any] | None = None,
    project_stage: str = "",
    competition_type: str = "",
    max_results: int = 3,
) -> list[dict[str, Any]]:
    scored: list[tuple[float, ChallengeStrategy, list[str], list[str], list[str]]] = []
    text_lower = str(text or "").lower()
    safe_edge_types = [str(x) for x in (edge_types or []) if x]
    safe_rules = [str(x) for x in (triggered_rule_ids or []) if x]

    for strategy in STRATEGIES:
        if not _in_spectrum_window(strategy, track_vector):
            continue
        if strategy.applies_to_stage and project_stage and project_stage not in strategy.applies_to_stage:
            continue
        if strategy.applies_to_competition and competition_type and competition_type not in strategy.applies_to_competition:
            continue

        score = 0.0
        kw_hits = [k for k in strategy.trigger_keywords if k and k.lower() in text_lower]
        if kw_hits:
            score += len(kw_hits) * 2.0
        rule_hits = [r for r in strategy.trigger_rules if r in safe_rules]
        if rule_hits:
            score += len(rule_hits) * 3.0
        fallacy_hits = [f for f in _STRATEGY_FALLACY_PREFS.get(strategy.id, []) if f and f in fallacy_label]
        if fallacy_hits:
            score += len(fallacy_hits) * 2.5
        edge_hits = [e for e in _STRATEGY_EDGE_PREFS.get(strategy.id, []) if e in safe_edge_types]
        if edge_hits:
            score += len(edge_hits) * 1.8
        if strategy.applies_to_stage and project_stage:
            score += 0.8
        if strategy.applies_to_spectrum:
            score += 0.8
        if score > 0:
            scored.append((score, strategy, kw_hits, rule_hits, edge_hits))

    scored.sort(key=lambda x: x[0], reverse=True)
    results: list[dict[str, Any]] = []
    for score, s, kw_hits, rule_hits, edge_hits in scored[:max_results]:
        results.append({
            "strategy_id": s.id,
            "name": s.name,
            "match_score": round(score, 2),
            "probing_layers": s.probing_layers,
            "expected_evidence": s.expected_evidence,
            "counterfactual": s.counterfactual,
            "preferred_edge_types": _STRATEGY_EDGE_PREFS.get(s.id, []),
            "supported_fallacies": _STRATEGY_FALLACY_PREFS.get(s.id, []),
            "strategy_logic": _STRATEGY_LOGIC.get(s.id, ""),
            "matched_edge_types": edge_hits,
            "matched_keywords": kw_hits,
            "matched_rules": rule_hits,
            "strategy_type": s.strategy_type,
            "applies_to_stage": s.applies_to_stage,
            "applies_to_competition": s.applies_to_competition,
        })
    return results


def match_strategies(
    text: str,
    triggered_rule_ids: list[str] | None = None,
    max_results: int = 3,
    fallacy_label: str = "",
    edge_types: list[str] | None = None,
    track_vector: dict[str, Any] | None = None,
    project_stage: str = "",
    competition_type: str = "",
) -> list[dict[str, Any]]:
    """Find matching challenge strategies based on text keywords and/or triggered rules."""
    return select_probing_strategies(
        text,
        triggered_rule_ids=triggered_rule_ids,
        fallacy_label=fallacy_label,
        edge_types=edge_types,
        track_vector=track_vector,
        project_stage=project_stage,
        competition_type=competition_type,
        max_results=max_results,
    )


def format_for_critic(strategies: list[dict[str, Any]], max_chars: int = 800) -> str:
    """Format matched strategies into context for the Critic agent."""
    if not strategies:
        return ""
    parts: list[str] = []
    for s in strategies[:2]:
        part = f"**策略: {s['name']}**\n"
        for i, layer in enumerate(s["probing_layers"], 1):
            part += f"  追问{i}: {layer}\n"
        part += f"  反事实: {s['counterfactual']}\n"
        part += f"  需要学生提供: {', '.join(s['expected_evidence'])}\n"
        parts.append(part)
    text = "\n".join(parts)
    return text[:max_chars]
