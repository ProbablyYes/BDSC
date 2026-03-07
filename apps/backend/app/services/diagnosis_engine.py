from dataclasses import dataclass


RUBRIC_ITEMS = [
    "Problem Definition",
    "User Evidence Strength",
    "Solution Feasibility",
    "Business Model Consistency",
    "Market & Competition",
]

RISK_RULES = {
    "H1": "客户-价值主张错位",
    "H5": "需求证据不足",
    "H8": "单位经济不成立",
    "H14": "路演叙事断裂",
}


@dataclass
class DiagnosisResult:
    diagnosis: dict
    next_task: dict


def run_diagnosis(input_text: str, mode: str = "coursework") -> DiagnosisResult:
    normalized_text = input_text.lower()
    triggered_rules: list[dict] = []

    if "没有对手" in normalized_text or "唯一" in normalized_text:
        triggered_rules.append({"id": "H1", "name": RISK_RULES["H1"], "severity": "high"})
    if "1%" in normalized_text or "百分之一" in normalized_text:
        triggered_rules.append({"id": "H8", "name": RISK_RULES["H8"], "severity": "high"})
    if "访谈" not in normalized_text and "问卷" not in normalized_text:
        triggered_rules.append({"id": "H5", "name": RISK_RULES["H5"], "severity": "medium"})
    if len(input_text) < 240:
        triggered_rules.append({"id": "H14", "name": RISK_RULES["H14"], "severity": "medium"})

    score_base = 7.0 if mode == "coursework" else 6.5
    rubric = []
    for idx, name in enumerate(RUBRIC_ITEMS):
        penalty = 0.6 * len(triggered_rules) / (idx + 2)
        rubric.append(
            {
                "item": name,
                "score": round(max(3.0, score_base - penalty), 1),
                "status": "risk" if penalty >= 1.0 else "ok",
            }
        )

    if "market" in normalized_text or "市场" in normalized_text:
        bottleneck = "商业模型证据不足，尚未形成可执行闭环。"
        next_task = {
            "title": "补齐 BMC 的收入与渠道闭环",
            "description": "基于一个清晰用户画像，完成价值主张-渠道-收入来源的一致性表。",
            "acceptance_criteria": [
                "给出1个目标用户细分",
                "至少2个可触达渠道及获客成本估算",
                "每种收入方式都有支付意愿证据",
            ],
        }
    else:
        bottleneck = "问题定义与证据链偏弱，项目方向可能偏离真实需求。"
        next_task = {
            "title": "完成首轮用户证据采集",
            "description": "围绕单一场景访谈至少5位目标用户，整理痛点频率与严重度。",
            "acceptance_criteria": [
                "5条以上访谈原句",
                "痛点频率统计表",
                "保留至少1条反证观点",
            ],
        }

    diagnosis = {
        "mode": mode,
        "bottleneck": bottleneck,
        "triggered_rules": triggered_rules,
        "rubric": rubric,
        "summary": "系统已基于课程规则与项目文本生成首轮诊断，可继续迭代反馈。",
    }

    return DiagnosisResult(diagnosis=diagnosis, next_task=next_task)
