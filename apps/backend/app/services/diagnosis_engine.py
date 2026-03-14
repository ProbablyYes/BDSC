from dataclasses import dataclass


RULES = [
    {"id": "H1", "name": "客户-价值主张错位", "severity": "high", "keywords": ["万能", "所有人", "任何人"]},
    {"id": "H2", "name": "渠道不可达", "severity": "high", "keywords": ["全靠社交媒体", "自然增长", "裂变即可"]},
    {"id": "H3", "name": "定价无支付意愿证据", "severity": "medium", "keywords": ["定价", "收费"], "requires": ["支付意愿", "愿意付费"]},
    {"id": "H4", "name": "TAM/SAM/SOM口径混乱", "severity": "high", "keywords": ["tam", "sam", "som", "市场规模"]},
    {"id": "H5", "name": "需求证据不足", "severity": "high", "requires": ["访谈", "问卷", "用户证据", "调研"]},
    {"id": "H6", "name": "竞品对比不可比", "severity": "medium", "keywords": ["无竞争对手", "没有对手", "独一无二"]},
    {"id": "H7", "name": "创新点不可验证", "severity": "high", "keywords": ["创新", "颠覆"], "requires": ["实验", "验证", "对照"]},
    {"id": "H8", "name": "单位经济不成立", "severity": "high", "keywords": ["cac", "ltv", "获客成本", "复购"]},
    {"id": "H9", "name": "增长逻辑跳跃", "severity": "medium", "keywords": ["1%", "百分之一", "指数增长"]},
    {"id": "H10", "name": "里程碑不可交付", "severity": "medium", "keywords": ["一个月内", "三个月内全部完成"]},
    {"id": "H11", "name": "合规/伦理缺口", "severity": "high", "keywords": ["隐私", "合规", "伦理", "数据安全"]},
    {"id": "H12", "name": "技术路线与资源不匹配", "severity": "high", "keywords": ["大模型", "芯片", "复杂硬件"]},
    {"id": "H13", "name": "实验设计不合格", "severity": "medium", "keywords": ["实验", "ab测试", "对照组"], "requires": ["样本", "指标"]},
    {"id": "H14", "name": "路演叙事断裂", "severity": "low", "keywords": ["愿景"], "min_length": 260},
    {"id": "H15", "name": "评分项证据覆盖不足", "severity": "medium", "keywords": []},
]

RUBRICS = [
    {"item": "Problem Definition", "weight": 0.1, "evidence": ["痛点", "场景", "用户画像"], "rules": ["H1", "H5"]},
    {"item": "User Evidence Strength", "weight": 0.15, "evidence": ["访谈", "问卷", "原话", "样本"], "rules": ["H5", "H13"]},
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


def _is_hit_rule(rule: dict, text: str) -> bool:
    has_keyword = bool(rule.get("keywords")) and any(k in text for k in rule.get("keywords", []))
    requires = rule.get("requires", [])
    requires_missing = bool(requires) and not any(k in text for k in requires)
    too_short = bool(rule.get("min_length")) and len(text) < int(rule["min_length"])
    return has_keyword or requires_missing or too_short


def _rule_penalty(severity: str) -> float:
    if severity == "high":
        return 2.0
    if severity == "medium":
        return 1.0
    return 0.5


def _evidence_score(text: str, evidence_keywords: list[str]) -> float:
    hit = sum(1 for k in evidence_keywords if k in text)
    if hit >= 2:
        return 5.0
    if hit == 1:
        return 3.0
    return 0.0


def _suggest_next_task(primary_rule_id: str) -> dict:
    mapping = {
        "H5": {
            "title": "完成用户证据闭环",
            "description": "围绕单一用户场景完成至少8份访谈并形成证据矩阵。",
            "acceptance_criteria": [">=8条用户原话", "痛点频次统计", "至少1条反证样本"],
        },
        "H1": {
            "title": "重做价值主张一致性表",
            "description": "明确目标客群，重写价值主张并校验渠道可达性。",
            "acceptance_criteria": ["1个核心客群", "2个可达渠道", "价值主张-渠道-收入一一对应"],
        },
        "H8": {
            "title": "补齐单位经济模型",
            "description": "建立 CAC/LTV/BEP 三表并给出关键假设来源。",
            "acceptance_criteria": ["CAC 估算可追溯", "LTV 假设有证据", "给出盈亏平衡点"],
        },
        "H11": {
            "title": "完成合规与伦理检查清单",
            "description": "列出数据采集、存储、使用、授权链路并补齐缺口。",
            "acceptance_criteria": ["隐私条款草案", "数据流向图", "风险控制点清单"],
        },
    }
    return mapping.get(
        primary_rule_id,
        {
            "title": "补齐证据并完成一次压力测试",
            "description": "围绕当前最高风险点，补证据并完成一轮反事实问答压力测试。",
            "acceptance_criteria": ["新增3条可验证证据", "完成1轮压力测试问答", "更新修正后的版本说明"],
        },
    )


def run_diagnosis(input_text: str, mode: str = "coursework") -> DiagnosisResult:
    normalized_text = input_text.lower()
    is_file = "[上传文件:" in input_text
    text_len = len(normalized_text)

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
            },
            next_task={
                "title": "描述你的项目",
                "description": "告诉我你的创业想法、目标用户和想解决的问题，越详细越好。",
                "acceptance_criteria": ["项目一句话描述", "目标用户是谁", "解决什么问题"],
            },
        )

    triggered_rules: list[dict] = []
    for rule in RULES:
        if _is_hit_rule(rule, normalized_text):
            triggered_rules.append({"id": rule["id"], "name": rule["name"], "severity": rule["severity"]})

    # H15: 如果命中规则较多或文本证据词偏少，则视为评分项覆盖不足。
    evidence_hits = sum(1 for k in ["访谈", "问卷", "tam", "sam", "som", "cac", "ltv", "里程碑"] if k in normalized_text)
    if len(triggered_rules) >= 4 or evidence_hits < 2:
        triggered_rules.append({"id": "H15", "name": "评分项证据覆盖不足", "severity": "medium"})

    unique_triggered = {r["id"]: r for r in triggered_rules}
    triggered_rules = list(unique_triggered.values())

    rubric: list[dict] = []
    weighted_total = 0.0
    total_weight = 0.0
    for row in RUBRICS:
        ev_score = _evidence_score(normalized_text, row["evidence"])
        penalties = sum(
            _rule_penalty(r["severity"])
            for r in triggered_rules
            if r["id"] in row["rules"]
        )
        dim_score = max(0.0, min(10.0, ev_score * 2.0 - penalties))
        rubric.append(
            {
                "item": row["item"],
                "score": round(dim_score, 2),
                "status": "risk" if dim_score < 6.0 else "ok",
                "weight": row["weight"],
            }
        )
        weighted_total += dim_score * row["weight"]
        total_weight += row["weight"]

    overall_score = round(weighted_total / total_weight, 2) if total_weight else 0.0
    high_rules = [r for r in triggered_rules if r["severity"] == "high"]
    primary_rule = high_rules[0]["id"] if high_rules else (triggered_rules[0]["id"] if triggered_rules else "NONE")

    if high_rules:
        bottleneck = f"当前最高风险为 {high_rules[0]['id']}（{high_rules[0]['name']}），会直接影响项目落地可行性。"
    elif triggered_rules:
        bottleneck = f"当前主要短板为 {triggered_rules[0]['id']}（{triggered_rules[0]['name']}），需要先补证据。"
    else:
        bottleneck = "未检测到高风险规则，建议进入下一轮压力测试和精细化验证。"

    next_task = _suggest_next_task(primary_rule)
    diagnosis = {
        "mode": mode,
        "overall_score": overall_score,
        "bottleneck": bottleneck,
        "triggered_rules": triggered_rules,
        "rubric": rubric,
        "capability_map": CAPABILITY_MAP,
        "summary": "已按 V2.0 规则集完成首轮诊断（15条规则 + 9项Rubric）。",
    }
    return DiagnosisResult(diagnosis=diagnosis, next_task=next_task)
