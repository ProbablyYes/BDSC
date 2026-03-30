"""
Challenge strategy library: structured Socratic questioning patterns
for the Critic agent. Each strategy has trigger conditions, multi-layer
probing questions, and expected evidence the student should provide.

Based on the requirements doc's "追问策略库" specification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
]

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


def match_strategies(
    text: str,
    triggered_rule_ids: list[str] | None = None,
    max_results: int = 3,
    fallacy_label: str = "",
    edge_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Find matching challenge strategies based on text keywords and/or triggered rules."""
    scored: list[tuple[float, ChallengeStrategy]] = []
    text_lower = text.lower()
    safe_edge_types = [str(x) for x in (edge_types or []) if x]

    for strategy in STRATEGIES:
        score = 0.0
        kw_hits = [k for k in strategy.trigger_keywords if k in text_lower]
        if kw_hits:
            score += len(kw_hits) * 2.0

        rule_hits = [r for r in strategy.trigger_rules if r in (triggered_rule_ids or [])]
        if rule_hits:
            score += len(rule_hits) * 3.0

        fallacy_hits = [f for f in _STRATEGY_FALLACY_PREFS.get(strategy.id, []) if f and f in fallacy_label]
        if fallacy_hits:
            score += len(fallacy_hits) * 2.5

        edge_hits = [e for e in _STRATEGY_EDGE_PREFS.get(strategy.id, []) if e in safe_edge_types]
        if edge_hits:
            score += len(edge_hits) * 1.8

        if score > 0:
            scored.append((score, strategy))

    scored.sort(key=lambda x: x[0], reverse=True)
    results: list[dict[str, Any]] = []
    for score, s in scored[:max_results]:
        results.append({
            "strategy_id": s.id,
            "name": s.name,
            "match_score": score,
            "probing_layers": s.probing_layers,
            "expected_evidence": s.expected_evidence,
            "counterfactual": s.counterfactual,
            "preferred_edge_types": _STRATEGY_EDGE_PREFS.get(s.id, []),
            "supported_fallacies": _STRATEGY_FALLACY_PREFS.get(s.id, []),
            "strategy_logic": _STRATEGY_LOGIC.get(s.id, ""),
            "matched_edge_types": [e for e in _STRATEGY_EDGE_PREFS.get(s.id, []) if e in safe_edge_types],
        })
    return results


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
