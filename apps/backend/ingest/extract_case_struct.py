from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.llm_client import LlmClient
from app.services.document_parser import ParsedDocument, TextSegment
from app.services.hypergraph_document import HypergraphDocument
from ingest.common import (
    bool_from_csv,
    detect_appendix_start,
    now_iso,
    split_lines,
    unique_keep_order,
)

HEADING_RE = re.compile(r"^([一二三四五六七八九十]+[、.]|\d+[、.)]|#|\*{1,2})")
PROJECT_NAME_RE = re.compile(r"(项目名称|项目名|课题名称)[:：]\s*([^\n]{2,80})")
# 任意包含 "......" 这类点线的行都视为目录/无用信息
TOC_TRAIL_RE = re.compile(r"[\.·•．]{3,}")
# 表单/审批类元信息行（申请人、项目编号、审批意见等）
ADMIN_META_RE = re.compile(
    r"(申请人|负责人|指导教师|指导老师|项目编号|学号|身份证号|联系方式|联系电话|审批意见|审核意见|专家组意见|领导小组审批|学院意见|盖章|签字|年月日|填表说明|填写说明|一栏不填|只填负责人)"
)

TEAM_LINE_RE = re.compile(
    r"(团队成员和组织架构|团队成员|项目团队|核心团队|管理团队|组织架构|组织结构|团队架构|团队结构|Team members|Team composition|Team structure)"
)

TEAM_ROLE_RE = re.compile(
    r"(CEO|COO|CTO|CFO|CMO|首席执行官|首席技术官|负责人|经理|总监|工程师|研究员|博士|硕士|教授)"
)

SECTION_KEYWORDS = {
    "target_users": ["用户", "客户", "目标群体", "目标人群", "受众", "使用者"],
    "pain_points": [
        "痛点",
        "问题",
        "主要问题",
        "核心问题",
        "关键问题",
        "困难",
        "难点",
        "困境",
        "现状不足",
        "矛盾",
        "痛点分析",
        "问题分析",
    ],
    "solution": [
        "解决方案",
        "方案设计",
        "实施方案",
        "技术方案",
        "应用方案",
        "产品方案",
        "解决思路",
        "设计思路",
        "功能模块",
        "系统功能",
        "服务方案",
    ],
    "innovation_points": ["创新", "创新点", "特色", "差异化", "独特", "核心优势"],
    "business_model": [
        "商业模式",
        "盈利",
        "盈利模式",
        "营收",
        "收入",
        "收益",
        "收入来源",
        "收费",
        "收费模式",
        "收费标准",
        "付费",
        "付费模式",
        "盈利方式",
        "收益模式",
        "现金流",
        "现金流量",
        "单位经济",
        "单客经济",
        "unit economics",
        "LTV",
        "CAC",
        "成本结构",
        "固定成本",
        "变动成本",
        "变革成本",
        "免费模式",
        "变现"
    ],
    "market_analysis": [
        "市场分析",
        "市场调研",
        "市场调查",
        "市场需求",
        "需求趋势",
        "需求分析",
        "竞争",
        "竞品分析",
        "竞争格局",
        "同类产品",
        "行业分析",
        "行业现状",
        "行业趋势",
        "tam",
        "sam",
        "som",
        "TAM",
        "SAM",
        "SOM",
        "市场规模",
        "市场份额",
        "蓝海",
        "隐形替代品",
        "替代品"
    ],
    "execution_plan": [
        "里程碑",
        "实施计划",
        "推进计划",
        "工作计划",
        "项目计划",
        "时间表",
        "时间规划",
        "时间安排",
        "进度安排",
        "实施路径",
        "实施步骤",
        "阶段目标",
        "路线图",
        "排期",
        "roadmap",
        "人力资源规划",
        "团队分工",
        "关键路径",
        "任务分解"
    ],
    "risk_control": [
        # 使用相对精简的一组关键词来定位风险控制相关段落，
        # 细粒度维度由 RISK_CONTROL_DIMENSIONS 负责二次分类。
        "风险",
        "风险控制",
        "风险管理",
        "风险评估",
        "风险防控",
        "风控",
        "风险点",
        "隐患",
        "安全风险",
        "安全措施",
        "预案",
        "应急预案",
        "应急方案",
        "防范",
        "防范措施",
        "合规",
        "合规性",
        "法律风险",
        "政策风险",
        "监管",
        "行业准入",
        "隐私",
        "隐私保护",
        "数据安全",
        "数据合规",
        "AI 伦理",
        "算法公平",
        "闭环",
        "逻辑断层",
        "逻辑断裂",
        "证据不足",
        "缺乏证据",
        "不可验证",
    ],
}


# risk_control 维度：用于在清洗阶段对风险控制要点做再分类和打标签，
# 方便后续映射到 Rubric、规则和 Risk_Pattern_Edge。
RISK_CONTROL_DIMENSIONS: dict[str, dict[str, list[str]]] = {
    "compliance_ethics": {
        "label": "合规与伦理意识",
        "keywords": [
            "合规",
            "合规性",
            "法律风险",
            "政策风险",
            "监管",
            "监管要求",
            "行业准入",
            "行业规范",
            "隐私",
            "隐私保护",
            "数据安全",
            "数据保护",
            "数据合规",
            "AI 伦理",
            "人工智能伦理",
            "算法公平",
            "GDPR",
        ],
    },
    "logic_consistency": {
        "label": "逻辑自洽与闭环",
        "keywords": [
            "闭环",
            "逻辑",
            "逻辑链条",
            "逻辑断层",
            "逻辑断裂",
            "脱节",
            "孤立节点",
            "无法闭环",
            "环节缺失",
        ],
    },
    "fallacy": {
        "label": "常见思维误区",
        "keywords": [
            "没有竞争对手",
            "没有竞品",
            "无竞品",
            "蓝海",
            "1% 市场",
            "百分之一市场",
            "只要拿下",
            "只要占据",
            "指数增长",
            "技术万能",
            "技术万能论",
            "免费模式",
            "先做大再变现",
            "现金流缺失",
            "现金流断裂",
            "回本周期过长",
        ],
    },
    "evidence_coverage": {
        "label": "证据覆盖度与可验证性",
        "keywords": [
            "证据不足",
            "缺乏证据",
            "缺少证据",
            "不可验证",
            "尚未验证",
            "验证不足",
            "数据不足",
            "样本过少",
            "调研有限",
            "访谈数量有限",
            "R7",
            "H5",
        ],
    },
}

RISK_CONTROL_GENERAL_KEYWORDS = [
    "风险",
    "风险点",
    "风险控制",
    "风险管理",
    "风险评估",
    "风控",
    "隐患",
    "安全",
    "预案",
    "应急",
]


# 常见目录/章节标题关键词，用于在清洗阶段剔除目录项和空洞标题
SECTION_TITLE_KEYWORDS = [
    "项目概况",
    "项目概述",
    "项目简介",
    "项目背景",
    "项目背景与意义",
    "研究背景",
    "研究内容",
    "研究目标",
    "研究内容与目标",
    "研究意义",
    "研究现状",
    "文献综述",
    "项目内容",
    "项目实施",
    "实施方案",
    "技术方案",
    "技术路线",
    "解决思路",
    "实施路径",
    "实践过程",
    "实践内容",
    "实践成效",
    "项目总结",
    "总结与展望",
    "结论与展望",
    "创新点",
    "项目创新点",
    "参考文献",
    "附录",
]


# 常见中文章节标题后缀，例如“项目背景”“实施方案”“研究现状”等
HEADING_SUFFIXES = [
    "概况",
    "概述",
    "背景",
    "简介",
    "内容",
    "情况",
    "计划",
    "方案",
    "路径",
    "思路",
    "分析",
    "研究",
    "总结",
    "展望",
    "建议",
    "目标",
    "意义",
    "成效",
    "现状",
    "综述",
    "路线",
    "模式",
    "框架",
]

# 章节型标题，如“第1章 绪论”“第一章 项目背景”等
CHAPTER_HEADING_RE = re.compile(r"^第[一二三四五六七八九十百千0-9]{1,3}章")


def _looks_like_directory_or_heading(text: str) -> bool:
    """Heuristic check: 是否是目录/章节标题，而不是实质内容。

    规则偏严格（宁可少收也不要把目录当内容）：
    - 含有“目录”且没有句子级标点
    - 纯英文 Contents/Table of contents
    - 短的章节标题（如“行业现状”“痛点分析”“政策支持”等）
    - 编号开头(一. / 1.) 且后半部分是常见章节标题
    """

    s = str(text).strip()
    if not s:
        return False
    # 句子级标点通常意味着已经是完整句子，不当作目录
    has_sentence_punct = any(ch in "。！？!?" for ch in s)

    # 明显目录行
    if "目录" in s and (len(s) <= 40 or not has_sentence_punct):
        return True

    low = s.lower()
    if low in {"contents", "table of contents"}:
        return True

    # 短且只像章节标题，不含句子标点
    if len(s) <= 30 and not has_sentence_punct:
        for kw in SECTION_TITLE_KEYWORDS:
            if kw in s:
                return True

        # 例如“项目背景”“实施方案”“研究现状”等，仅由若干词+常见后缀构成
        for suf in HEADING_SUFFIXES:
            if s.endswith(suf):
                return True

    # 编号开头的小节行统一视为章节标题，直接舍弃
    # 例如 “一、项目概况”“2. 研究内容与目标”，即便后面带少量正文，也不会进入知识库
    if HEADING_RE.match(s):
        return True

    return False


def _is_toc_or_heading_or_meta_line(text: str) -> bool:
    """统一判断是否为目录/章节标题/页码或比赛抬头等元信息行。

    这类行在 profile/evidence/segment 抽取中都应直接丢弃，
    避免把目录、页码或比赛口号写入知识库节点。
    """

    s = str(text).strip()
    if not s:
        return True
    # 明显章节标题（第1章、第一章等）
    if CHAPTER_HEADING_RE.match(s):
        return True
    # 含有目录点线的一整行直接视为目录
    if TOC_TRAIL_RE.search(s):
        return True
    # 明显目录/章节标题
    if _looks_like_directory_or_heading(s):
        return True
    # 纯页码
    if s.isdigit() and len(s) <= 3:
        return True
    # 只包含比赛名称等抬头的噪声行
    if "挑战杯" in s and "竞赛" in s and len(s) < 80:
        return True
    # 表单/审批说明类元信息（如“申请人为本科生创新团队，首页只填负责人。”、“专家组意见”、“审批意见”等）
    if ADMIN_META_RE.search(s):
        return True
    return False


def _is_noise_line(text: str, kind: str) -> bool:
    """统一判断在 profile/evidence 清洗阶段是否将该行视为噪声。

    kind:
    - "profile": 项目画像字段中的短句
    - "evidence": 证据 quote
    """

    s = str(text).strip()
    if not s:
        return True

    # 通用元信息行：目录、章节标题、页码、比赛抬头、表单/审批说明等
    if _is_toc_or_heading_or_meta_line(s):
        return True

    # 团队成员/组织架构相关句子统一视为噪声，直接丢弃
    if _looks_like_team_line(s):
        return True

    if kind == "profile":
        # profile 中极短碎片基本没有信息量
        return len(s) <= 2

    if kind == "evidence":
        # 证据字段：稍微放宽长度阈值，但依然丢弃极短碎片和“目录”类短行
        if len(s) <= 4:
            return True
        if "目录" in s and len(s) < 50:
            return True

    return False


def _looks_like_team_line(text: str) -> bool:
    """Detect whether a短句更像是“团队成员/组织架构”描述。

    用于在 profile 各字段之间做二次归类：
    - 明确包含“团队成员/项目团队/组织架构”等关键词
    - 或者是以项目符号开头，且包含典型职务/头衔（CEO、经理、博士等）
    """

    s = str(text).strip()
    if not s:
        return False

    if TEAM_LINE_RE.search(s) or TEAM_ROLE_RE.search(s):
        return True

    return False


def _postprocess_risk_control_items(items: list[str]) -> list[str]:
    """根据维度对 risk_control 要点做再分类与打标签。

    约定：这里只保留“文件中对风险的明确认知与处理措施”，
    不直接展示“缺失/不足/尚未覆盖”的风险盲点，这类信息交由 tags 表达。
    """

    labeled: list[str] = []
    negative_markers = [
        "缺乏",
        "不足",
        "缺少",
        "没有",
        "尚未",
        "未能",
        "未做到",
        "不具备",
        "不可验证",
        "不完善",
        "不充分",
    ]

    for raw in items:
        text = str(raw).strip()
        if not text:
            continue
        low = text.lower()

        # 明确描述“缺失/不足/尚未覆盖”的句子，不进入 project_profile.risk_control，
        # 由后续 risk gap 逻辑在 tags 中体现。
        if any(marker in text for marker in negative_markers):
            continue

        matched_labels: list[str] = []
        for dim in RISK_CONTROL_DIMENSIONS.values():
            label = dim.get("label", "").strip()
            keywords = dim.get("keywords", [])
            if not label or not keywords:
                continue
            if any(kw.lower() in low for kw in keywords):
                matched_labels.append(label)

        if not matched_labels:
            # 若仅匹配到通用风险关键词，则归入“通用风险控制”；否则视为与风险控制无关，直接丢弃。
            if not any(kw.lower() in low for kw in RISK_CONTROL_GENERAL_KEYWORDS):
                continue
            dim_label = "通用风险控制"
        else:
            # 最多保留前两个维度标签，避免标签过长。
            if len(matched_labels) == 1:
                dim_label = matched_labels[0]
            else:
                dim_label = "/".join(matched_labels[:2])

        labeled.append(f"【{dim_label}】{text}")

    return unique_keep_order(labeled)


def _clean_profile_items(field: str, items: list[str]) -> list[str]:
    """Post-process profile field values to drop noise and overly长文本.

    目标：
    - 去掉页码、目录行、比赛口号等噪声
    - 控制每条内容的长度（更像简短要点）
    - 限制每个字段的要点数量，避免灌入整段原文
    """
    if not items:
        return []

    # 一些字段的典型“空洞口号”语句，在知识库画像中可以直接丢弃，避免污染下游诊断。
    generic_phrases: dict[str, list[str]] = {
        "business_model": [
            "商业模式清晰",
            "商业模式明确",
            "盈利模式清晰",
            "盈利前景广阔",
            "盈利空间巨大",
            "具有良好的盈利前景",
        ],
        "market_analysis": [
            "市场前景广阔",
            "市场空间巨大",
            "市场潜力巨大",
            "具有广阔的发展前景",
        ],
        "execution_plan": [
            "稳步推进",
            "有序推进",
            "确保项目顺利进行",
            "保证项目顺利实施",
        ],
    }

    cleaned: list[str] = []
    for raw in items:
        text = str(raw).strip()
        if _is_noise_line(text, kind="profile"):
            continue

        # 去掉典型的空洞口号，保留真正描述结构和逻辑的语句
        for field_name, phrases in generic_phrases.items():
            if field == field_name and any(p in text for p in phrases):
                text = ""
                break
        if not text:
            continue

        # 控制单条长度：尽量截断到首句或合适的位置，保持“短句要点”风格
        if len(text) > 80:
            for sep in ["。", "；", "!", "！", "?", "？"]:
                pos = text.find(sep)
                if 15 < pos <= 60:
                    text = text[: pos + 1]
                    break
            if len(text) > 80:
                text = text[:80]

        cleaned.append(text)

    # 去重并保持顺序
    cleaned = unique_keep_order(cleaned)

    # risk_control：在通用清洗后，进一步根据维度做筛选与打标签，
    # 将非风险类语句剔除，保留适合构造成 Risk_Pattern_Edge 的要点。
    if field == "risk_control":
        cleaned = _postprocess_risk_control_items(cleaned)

    # 针对不同字段限制最多要点数量
    if field in {"target_users", "pain_points", "solution", "innovation_points"}:
        max_items = 4
    else:
        max_items = 6
    return cleaned[:max_items]


def _clean_evidence_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """清洗证据列表，去掉明显无用或目录型的 quote。

    - 丢弃空 quote 或极短的碎片
    - 丢弃被判定为目录/章节标题的 quote
    - 丢弃包含“目录”且长度很短的行
    """

    cleaned: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote", "")).strip()
        if _is_noise_line(quote, kind="evidence"):
            continue

        # 重新赋值 cleaned quote，保持其他字段不变
        new_item = dict(item)
        new_item["quote"] = quote[:400]
        cleaned.append(new_item)

    return cleaned


def infer_risk_gaps(core_text: str, sections: dict[str, list[str]] | None = None) -> list[str]:
    """Heuristically infer high-level *risk gaps* from文本与画像字段。

    输出代码仅用于在 tags 中标记“缺失/不足”的风险控制要素，
    不再单独暴露 risk_flags 字段：
    - weak_user_evidence：有清晰用户/痛点描述，但缺少访谈/问卷等需求证据；
    - market_size_fallacy：出现“1% 市场”等自上而下估算或类似表述；
    - no_competitor_claim：直接或隐含地声称“没有竞品/没有对手/蓝海”；
    - compliance_not_covered：涉及高风险行业或隐私场景，却缺少合规/伦理说明。
    """

    text = (core_text or "").strip()
    sections = sections or {}

    def _contains_any(s: str, keywords: list[str]) -> bool:
        if not s:
            return False
        low = s.lower()
        return any(kw.lower() in low for kw in keywords)

    flags: list[str] = []

    # 1) 需求证据强度：有用户/痛点，但缺少调研/访谈等证据 → weak_user_evidence
    user_context_parts: list[str] = [text]
    user_context_parts.extend(sections.get("target_users", []))
    user_context_parts.extend(sections.get("pain_points", []))
    user_context = "\n".join(user_context_parts)

    user_tokens = ["用户", "客户", "使用者", "受众", "目标人群"]
    research_tokens = [
        "访谈",
        "深度访谈",
        "问卷",
        "问卷调查",
        "调研",
        "调查",
        "走访",
        "interview",
        "survey",
        "questionnaire",
    ]
    if _contains_any(user_context, user_tokens) and not _contains_any(user_context, research_tokens):
        flags.append("weak_user_evidence")

    # 2) 市场规模谬误：典型 "1% 市场" / "拿下 X%" 式自上而下估算 → market_size_fallacy
    market_context_parts: list[str] = [text]
    market_context_parts.extend(sections.get("market_analysis", []))
    market_context = "\n".join(market_context_parts)

    market_patterns = [
        r"1\s*%\s*市场",
        r"1％\s*市场",
        r"百分之一\s*市场",
        r"只要[\u4e00-\u9fa5]*拿[到下]?\s*\d+%[\u4e00-\u9fa5]*市场",
        r"只需[\u4e00-\u9fa5]*占[据]?\s*\d+%[\u4e00-\u9fa5]*市场",
    ]
    for pattern in market_patterns:
        if re.search(pattern, market_context):
            flags.append("market_size_fallacy")
            break

    # 3) 无竞品 / 蓝海幻觉：直接声称没有竞品或只有自己 → no_competitor_claim
    competitor_context = market_context
    no_competitor_phrases = [
        "没有竞争对手",
        "没有竞品",
        "无竞品",
        "无竞争对手",
        "没有对手",
        "没有同类产品",
        "没有替代品",
        "无替代品",
        "蓝海市场",
        "蓝海",
        "没有任何竞争",
        "唯一的产品",
        "唯一的解决方案",
        "only player",
        "no competitor",
    ]
    if _contains_any(competitor_context, no_competitor_phrases):
        flags.append("no_competitor_claim")

    # 4) 合规与伦理缺口：涉及高风险领域却缺少合规/隐私/伦理说明 → compliance_not_covered
    risk_context_parts: list[str] = [text]
    risk_context_parts.extend(sections.get("risk_control", []))
    risk_context = "\n".join(risk_context_parts)

    sensitive_domain_tokens = [
        "医疗",
        "医院",
        "诊断",
        "处方",
        "药品",
        "手术",
        "金融",
        "证券",
        "理财",
        "贷款",
        "信贷",
        "借贷",
        "隐私",
        "人脸识别",
        "生物识别",
        "未成年人",
        "青少年",
        "校园欺凌",
        "数据采集",
        "数据抓取",
        "爬虫",
        "位置数据",
    ]
    compliance_tokens = [
        "合规",
        "合规性",
        "合规要求",
        "隐私保护",
        "数据保护",
        "数据合规",
        "伦理",
        "道德",
        "GDPR",
        "监管",
        "备案",
        "审批",
        "风控",
    ]

    if _contains_any(risk_context, sensitive_domain_tokens) and not _contains_any(
        risk_context, compliance_tokens
    ):
        flags.append("compliance_not_covered")

    return unique_keep_order(flags)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract structured cases from metadata.csv")
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Use configured LLM for enhanced extraction on A/B samples.",
    )
    parser.add_argument(
        "--llm-model",
        default="",
        help="Override model name for extraction. Default uses settings.llm_fast_model.",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=0,
        help="Optional limit for processed cases (0 means all).",
    )
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help="Only process selected categories (folder names). Can repeat.",
    )
    parser.add_argument(
        "--min-quality",
        choices=["A", "B"],
        default="B",
        help="Minimum parse quality to include (A only, or A/B).",
    )
    parser.add_argument(
        "--llm-verify",
        action="store_true",
        help="Run second-pass verification with reason model for better precision.",
    )
    parser.add_argument(
        "--push-neo4j",
        action="store_true",
        help="After extraction, import structured cases into Neo4j graph store.",
    )
    parser.add_argument(
        "--rejection-file",
        default="rejections.csv",
        help="Rejected records report filename under case_structured directory.",
    )
    return parser.parse_args(argv)


def _segment_score(text: str) -> int:
    low = text.lower()
    keywords = [
        "用户",
        "客户",
        "痛点",
        "需求",
        "商业模式",
        "盈利",
        "收入",
        "成本",
        "市场",
        "竞品",
        "访谈",
        "问卷",
        "证据",
        "风险",
        "合规",
    ]
    return sum(1 for kw in keywords if kw in low)

# split policy
def select_candidate_chunks(
    segments: list[TextSegment],
    max_chunks: int = 10,
    max_chars_per_chunk: int = 700,
    split_by: str = "auto",  # Options: "auto", "page", "chapter"
) -> list[dict[str, str]]:
    """Select chunks for LLM extraction.

    改进点：
    - 优先按章节/页标记做语义边界
    - 在默认 auto 模式下，按原文顺序滑动窗口聚合段落，每个 chunk 对应一个完整主题片段
    - 相邻 chunk 之间保留约 15% 的内容重叠，减少语义断层
    """
    if not segments:
        return []

    # Detect split strategy first when caller显式指定
    if split_by == "page":
        page_markers = [seg for seg in segments if "page" in seg.text.lower()]
        if page_markers:
            return _split_by_markers(segments, page_markers, max_chunks, max_chars_per_chunk)
    elif split_by == "chapter":
        chapter_markers = [seg for seg in segments if HEADING_RE.match(seg.text)]
        if chapter_markers:
            return _split_by_markers(segments, chapter_markers, max_chunks, max_chars_per_chunk)

    # AUTO: 语义优先的滑动窗口切片（带重叠）
    ordered = [seg for seg in segments if seg.text.strip()]
    if not ordered:
        return []
    # TextSegment.index 单调递增，保证顺序
    try:
        ordered.sort(key=lambda s: s.index)
    except AttributeError:
        # 回退：若无 index 属性，则按原顺序
        pass

    overlap_ratio = 0.15  # 10%~20% 的重叠，这里取中间值
    window_chars = max_chars_per_chunk
    max_total_chars = int(max_chars_per_chunk * (1 + overlap_ratio))

    chunks: list[dict[str, str]] = []
    start_idx = 0
    n = len(ordered)

    while start_idx < n and len(chunks) < max_chunks:
        current_chars = 0
        texts: list[str] = []
        source_unit = ordered[start_idx].source_unit
        idx = start_idx

        while idx < n and current_chars < window_chars:
            seg = ordered[idx]
            seg_text = seg.text.strip()
            if not seg_text:
                idx += 1
                continue

            # 如果遇到明显章节标题且本 chunk 已经有足够内容，则提前结束，避免跨主题
            if HEADING_RE.match(seg_text) and texts and current_chars > window_chars * 0.6:
                break

            texts.append(seg_text)
            current_chars += len(seg_text)
            idx += 1

        if not texts:
            start_idx = idx + 1
            continue

        text = "\n".join(texts)

        # 为当前窗口做软截断：尽量在句号/问号/感叹号后截断，避免打断句子
        if len(text) > window_chars:
            window = text[: window_chars + 50]
            cut_candidates = [
                window.rfind("。"),
                window.rfind("！"),
                window.rfind("？"),
                window.rfind("!"),
                window.rfind("?"),
            ]
            cut = max(cut_candidates)
            if cut >= int(window_chars * 0.6):
                text = window[: cut + 1]
            else:
                text = window[:window_chars]

        # 与前一个 chunk 做内容重叠（约 15% 尾部）
        if chunks:
            prev_text = chunks[-1]["text"]
            overlap_chars = int(len(prev_text) * overlap_ratio)
            prefix = prev_text[-overlap_chars:] if overlap_chars > 0 else ""
            if prefix:
                combined = (prefix + "\n" + text).strip()
            else:
                combined = text
            if len(combined) > max_total_chars:
                combined = combined[:max_total_chars]
            text = combined

        chunks.append(
            {
                "chunk_id": f"C{len(chunks) + 1}",
                "source_unit": source_unit,
                "text": text,
            }
        )

        # 下一窗口起点：按段落级滑动窗口，保留约 overlap_ratio 的段落重叠
        used_segments = max(1, idx - start_idx)
        overlap_segments = max(1, int(used_segments * overlap_ratio))
        start_idx = start_idx + used_segments - overlap_segments
        if start_idx <= 0:
            start_idx = 1

    return chunks

def _split_by_markers(
    segments: list[TextSegment],
    markers: list[TextSegment],
    max_chunks: int,
    max_chars_per_chunk: int,
) -> list[dict[str, str]]:
    """Split segments by detected markers (e.g., pages or chapters)."""
    chunks: list[dict[str, str]] = []
    current_chunk: list[str] = []
    chunk_id = 1

    for seg in segments:
        if seg in markers and current_chunk:
            # Finalize current chunk
            chunks.append(
                {
                    "chunk_id": f"C{chunk_id}",
                    "source_unit": seg.source_unit,
                    "text": "\n".join(current_chunk)[:max_chars_per_chunk],
                }
            )
            chunk_id += 1
            current_chunk = []
        current_chunk.append(seg.text)

    # Add the last chunk
    if current_chunk:
        chunks.append(
            {
                "chunk_id": f"C{chunk_id}",
                "source_unit": segments[-1].source_unit,
                "text": "\n".join(current_chunk)[:max_chars_per_chunk],
            }
        )

    return chunks[:max_chunks]


def filter_noisy_segments(segments: list[TextSegment]) -> list[TextSegment]:
    """Drop obvious screenshot/noise lines before LLM selection."""
    noisy_tokens = [
        "图注",
        "figure",
        "截图",
        "附图",
        "图片来源",
        "见下图",
        "如下图",
    ]
    out: list[TextSegment] = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        low = text.lower()
        # 统一丢弃目录/章节标题/页码/比赛抬头等元信息行
        if _is_toc_or_heading_or_meta_line(text):
            continue
        if len(text) < 12 and any(tok in low for tok in ["图", "表", "页"]):
            continue
        if any(tok in low for tok in noisy_tokens) and len(text) < 40:
            continue
        out.append(seg)
    return out


def llm_extract_profile(
    llm: LlmClient,
    chunks: list[dict[str, str]],
    default_project_name: str,
    model_override: str = "",
) -> dict[str, Any]:
    if not chunks:
        return {}

    schema_hint = {
        "project_name": "string",
        "target_users": ["string"],
        "pain_points": ["string"],
        "solution": ["string"],
        "innovation_points": ["string"],
        # 四个核心模块：在知识库中以要点式短句刻画结构与逻辑，而不是口号。
        "business_model": ["string"],
        "market_analysis": ["string"],
        "execution_plan": ["string"],
        # risk_control 仅保留“文件中对风险的明确认知与正确处理”，
        # 不包含“缺失/不足/尚未覆盖”的风险盲点，这些会通过 tags 体现。
        "risk_control": ["string"],
        # 画像字段的代表性原文证据，供知识库与诊断引擎追溯。
        "evidence": [
            {
                "type": "user_evidence|business_model_evidence|risk_evidence",
                "quote": "string",
                "chunk_id": "Cx",
            }
        ],
    }
    system_prompt = (
        "你是“双创智能体知识库”的结构化信息抽取助手。"
        "任务：从创新创业项目的文档片段中，抽取用于知识图谱、超图诊断和检索问答的关键信息。"
        "必须严格只依据提供的文本内容，不得引入外部常识或主观推断，也不能编造不存在的信息。"
        "输出必须是一个符合给定 schema_hint 的 JSON 对象，不要增加、删除或重命名任何字段。"
        "所有数组字段（如 target_users、pain_points、solution 等）应返回少量要点式短句（通常 1~4 条，每条约 20~50 个汉字），"
        "每条语义完整、书面表达，能够独立回答对应字段名提出的问题。"
        "请使用客观、具体的表述，避免空洞口号、重复表述或“本项目很好”“具有广阔前景”这类泛泛评价。"
        "严禁把目录行、章节标题、页码、比赛/活动口号（如“挑战杯”）、表单/填报说明、审批意见等噪声内容写入任何字段。"
        "严禁输出团队成员名单、导师/学院信息、个人履历、职称/职位列表、具体获奖记录等与项目内容无关的信息。"
        "当文中缺乏可靠信息时，请将该字段设为 [] 或保持默认值，而不是猜测。"
    )
    user_prompt = (
        f"默认项目名（当文中未出现更精确名称时可使用）: {default_project_name}\n"
        "你将收到若干文档片段 chunks，它们是一个 JSON 数组，每个元素包含 chunk_id、source_unit 和 text 字段。"\
        "你只能使用这些 text 字段中的明确信息进行抽取，不要把数组结构本身或未出现的细节写入结果。"\
        "字段含义与写作要点概括如下："\
        "project_name：项目或产品名称，如文本中出现更规范或更完整名称，可替换默认项目名；名称中不要包含学校、学院、竞赛名称等抬头。"\
        "target_users：典型目标用户/受益群体（谁会使用或受益），用 1~3 条具体人群描述。"\
        "pain_points：上述人群当前面临的关键问题和困难，结合具体场景进行概括。"\
        "solution：本项目提供的核心方案/产品/服务，重点写“做了什么”和“如何缓解上述痛点”，不要写团队优势或个人履历。"\
        "innovation_points：相对现有做法的关键创新点或差异化优势。"\
        "business_model：围绕“钱从哪来”刻画商业闭环，要说明核心价值主张、目标客户、触达渠道、主要收入来源与关键成本，必要时补充单位经济（如 LTV、CAC、毛利、回本周期等）或现金流特征；避免只写“商业模式清晰/盈利空间巨大”这类空洞口号。"\
        "market_analysis：市场规模、细分赛道、典型痛点与竞品格局的客观描述；若文中给出 TAM/SAM/SOM 或竞品对比表，请用 1~3 条要点概括口径与主要结论，而不是简单抄表。"\
        "execution_plan：项目实施阶段、关键里程碑与时间安排，以及与团队角色/外部资源的匹配情况；重点写“谁在什么时间交付什么结果”，而不是“稳步推进/有序开展”等泛泛表述。"\
        "risk_control：请将每条要点视为一个潜在的风险模式（Risk_Pattern），用于在超图中构建 Risk_Pattern_Edge。"\
        "仅保留“文件中对风险的明确认知与正确处理”，例如识别到何种风险、采取了哪些控制/缓解措施、未来的改进计划等；"\
        "不要把“缺乏证据/尚未考虑/没有说明/尚未建立风控机制”等风险盲点写入 risk_control，这类缺失信息会在系统中以其它方式标记；"\
        "优先围绕以下四类内容提炼短句："\
        "（1）合规与伦理意识：在涉及医疗、金融、未成年人、隐私数据等高敏感场景时，项目如何识别并应对合规/伦理风险；"\
        "（2）逻辑自洽性检查：痛点、功能、商业模式、结果之间是否形成闭环，例如如何保证承诺的结果可被交付和验证；"\
        "（3）常见思维误区（Fallacies）的自我规避：例如主动识别“没有竞争对手/蓝海市场”“只要拿下 1% 市场”“技术万能论”等风险，并给出更稳健的论证路径；"\
        "（4）证据覆盖度：针对关键假设给出可验证的证据来源、验证路径或数据收集计划，而不是仅指出“证据不足”。"\
        "每条 risk_control 要点尽量包含“风险类型 + 触发情境/条件 + 处理方式/控制措施 + 预期效果”几个要素，使用简洁的书面语，不要只写“注意风险/加强管理”之类空洞表述。"\
        "若文中出现规则或 Rubric 编号（如 H5、H11、H14、R7 等），可以原样保留在 risk_control 描述中，但不要凭空编造。"\
        "evidence：从 text 中选取能直接支撑上述判断的代表性原文引文，每条包括 type（user_evidence/business_model_evidence/risk_evidence）、quote、chunk_id；quote 可适度删去图号或无意义编号，但不得改写事实。"\
        "请严格按照下面给出的 JSON 结构返回最终结果（注意：不要返回 risk_flags 等未在 schema_hint 中声明的字段）："\
        f"{json.dumps(schema_hint, ensure_ascii=False)}\n"\
        f"文档片段（仅供你提取信息，不要原样复制长段落）: {json.dumps(chunks, ensure_ascii=False)}"
    )
    # 优先使用推理模型进行知识库画像抽取；如调用方显式传入 model_override，则以其为准。
    model_name = model_override or settings.llm_reason_model or settings.llm_fast_model or settings.llm_model or None
    return llm.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model_name,
        temperature=0.0,
    )


def llm_verify_profile(
    llm: LlmClient,
    chunks: list[dict[str, str]],
    draft_profile: dict[str, Any],
) -> dict[str, Any]:
    if not chunks:
        return {}
    verify_schema = {
        # 针对画像字段的“修正补丁”，只列出需要整体替换的字段。
        "project_profile_patch": {
            "target_users": ["string"],
            "pain_points": ["string"],
            "solution": ["string"],
            "innovation_points": ["string"],
            "business_model": ["string"],
            "market_analysis": ["string"],
            "execution_plan": ["string"],
            # risk_control 依然只保留“明确认知与正确处理”的要点。
            "risk_control": ["string"],
        },
        # 代表性证据列表的完整替换（如非空，则视为新的 evidence 列表）。
        "evidence_patch": [
            {
                "type": "user_evidence|business_model_evidence|risk_evidence",
                "quote": "string",
                "chunk_id": "Cx",
            }
        ],
    }
    system_prompt = (
        "你是“双创智能体知识库”的结构化抽取质检助手。"
        "任务：在已有抽取草稿的基础上，结合文档片段进行核查和微调，提升画像和证据的准确性与可用性。"
        "你必须仅依据提供的文档片段判断哪些要点有明确证据支持，不得凭空增删内容。"
        "project_profile_patch 中出现的字段表示需要替换的字段；每个字段的数组是该字段的最终要点列表，未出现的字段保持原值。"
        "请将各字段整理为若干条简短要点（通常 1~4 条、每条不超过 50 个汉字），语义完整、表述客观，能够单独回答对应问题。"
        "请删除目录/章节标题/页码/比赛口号/表单说明/审批意见、空洞口号、重复表述等噪声内容。"
        "不得在 solution、innovation_points、market_analysis、execution_plan 等字段写入团队成员、导师/学院信息、个人履历、职称/职位列表或具体获奖记录。"
        "对于 business_model，请优先保留能体现收入来源、收费方式、渠道与客户匹配关系、成本结构或单位经济（LTV/CAC/毛利等）的要点；"
        "对于 market_analysis，请突出 TAM/SAM/SOM 口径、关键假设与竞品格局；"
        "对于 execution_plan，请突出里程碑、时间表与责任分工；"
        "对于 risk_control，请优先保留能够明确描述“风险类型 + 触发情境/条件 + 处理方式/控制措施 + 预期效果”的要点，"
        "只保留文件中已经给出的风险识别与处理方案；单纯指出“缺乏证据/尚未考虑/没有说明/尚未建立风控机制”等风险盲点的句子，请不要放入 risk_control，而是直接丢弃。"
        "evidence_patch 如为非空数组，视为新的完整证据列表；若为空数组或根本不返回该键，则使用原 evidence。仅保留能直接支撑画像要点的代表性引文。"
        "请严格按照给定 verify_schema 返回一个 JSON 对象，不要新增或省略顶层键。"
    )
    user_prompt = (
        f"已有抽取草稿 draft_profile: {json.dumps(draft_profile, ensure_ascii=False)}\n"
        f"对应的文档片段 chunks: {json.dumps(chunks, ensure_ascii=False)}\n"
        "请你完成以下工作："\
        "1）逐字段检查 draft_profile 与文档片段的一致性，删除没有证据支持或明显夸大的要点，必要时根据文中信息补充遗漏但重要的要点；"\
        "2）将需要修改的字段写入 project_profile_patch，字段值为整理后的字符串数组；未需修改的字段可以省略；"\
        "3）如需调整证据列表，请在 evidence_patch 中给出新的完整列表（可重用草稿中的 quote 和 chunk_id，也可以从文档片段中重新选择）；否则返回空数组或省略该键；"\
        f"请严格按照此 JSON 结构返回: {json.dumps(verify_schema, ensure_ascii=False)}"
    )

    # 优先使用推理模型进行质检，如遇超时/失败则自动回退到 fast 模型，
    # 保证始终尽量使用 LLM 对抽取结果做一次检查，而不是直接放弃。
    models_to_try: list[str] = []
    if settings.llm_reason_model:
        models_to_try.append(settings.llm_reason_model)
    # fast_model 作为兜底
    fast_model = settings.llm_fast_model or settings.llm_model
    if fast_model and fast_model not in models_to_try:
        models_to_try.append(fast_model)

    for model_name in models_to_try:
        result = llm.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model_name,
            temperature=0.0,
        )
        if result:
            return result

    # 所有模型都失败时，返回空 dict，让上游保留原始抽取结果
    return {}


def _as_clean_str_list(value: Any, limit: int = 10) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return unique_keep_order(out)


def read_metadata(metadata_path: Path) -> list[dict]:
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.csv not found: {metadata_path}")
    with metadata_path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def core_segments(parsed: ParsedDocument, appendix_start_index: int | None) -> list[TextSegment]:
    if appendix_start_index is None:
        return parsed.segments
    result = [seg for seg in parsed.segments if seg.index < appendix_start_index]
    # fallback: appendix starts too early, avoid losing the whole document.
    return result if len(result) >= 2 else parsed.segments


def text_from_segments(segments: list[TextSegment]) -> str:
    return "\n".join(seg.text for seg in segments if seg.text.strip())


def infer_project_name(default_name: str, text: str) -> str:
    match = PROJECT_NAME_RE.search(text)
    if match:
        return match.group(2).strip("：: ")
    return Path(default_name).stem


def collect_section(segments: list[TextSegment], keywords: list[str], max_segments: int = 8) -> list[str]:
    for idx, seg in enumerate(segments):
        low = seg.text.lower()
        if not any(k.lower() in low for k in keywords):
            continue
        bucket = [seg.text]
        for nxt in segments[idx + 1 : idx + 1 + max_segments]:
            line = nxt.text.strip()
            if HEADING_RE.match(line):
                break
            bucket.append(line)
        lines = unique_keep_order(split_lines("\n".join(bucket)))
        return lines[:10]
    return []


def make_case_id(file_path: str) -> str:
    digest = hashlib.sha1(file_path.encode("utf-8")).hexdigest()[:12]
    return f"case_{digest}"


def build_case_record(
    row: dict,
    use_llm: bool = False,
    llm: LlmClient | None = None,
    llm_model: str = "",
    llm_verify: bool = False,
) -> dict:
    source_path = settings.teacher_examples_root / row["file_path"]
    
    # Use HypergraphDocument for unified processing
    hypergraph_doc = HypergraphDocument.from_file(source_path)
    parsed = ParsedDocument(
        file_path=source_path,
        doc_type=hypergraph_doc.doc_type,
        segments=hypergraph_doc.get_segments(),
    )
    
    appendix_start = row.get("appendix_start_index", "")
    appendix_idx = int(appendix_start) if appendix_start.isdigit() else detect_appendix_start(parsed)

    core = filter_noisy_segments(core_segments(parsed, appendix_idx))
    core_text = text_from_segments(core)
    full_text = parsed.full_text

    project_name = infer_project_name(row.get("file_name", source_path.name), core_text or full_text)
    sections = {name: collect_section(core, kws) for name, kws in SECTION_KEYWORDS.items()}

    llm_data: dict[str, Any] = {}
    chunk_map: dict[str, str] = {}
    if use_llm and llm:
        candidate_chunks = select_candidate_chunks(core, max_chunks=10, max_chars_per_chunk=700)
        chunk_map = {item["chunk_id"]: item["source_unit"] for item in candidate_chunks}
        llm_data = llm_extract_profile(
            llm=llm,
            chunks=candidate_chunks,
            default_project_name=project_name,
            model_override=llm_model,
        )
        if llm_verify:
            verify_data = llm_verify_profile(llm=llm, chunks=candidate_chunks, draft_profile=llm_data)
            profile_patch = verify_data.get("project_profile_patch", {})
            if isinstance(profile_patch, dict):
                llm_data.update(profile_patch)
            evidence_patch = verify_data.get("evidence_patch", [])
            if isinstance(evidence_patch, list) and evidence_patch:
                llm_data["evidence"] = evidence_patch

    # LLM fields override heuristics when present.
    for field in SECTION_KEYWORDS:
        llm_values = _as_clean_str_list(llm_data.get(field))
        if llm_values:
            sections[field] = llm_values

    llm_project_name = str(llm_data.get("project_name", "")).strip()
    if llm_project_name:
        project_name = llm_project_name

    # 基于文本和画像字段推断“风险盲点”，仅用于 tags，不再单独暴露 risk_flags 字段。
    risk_gaps = infer_risk_gaps(core_text or full_text, sections=sections)

    parse_quality = row.get("parse_quality", "C")
    confidence = {"A": 0.9, "B": 0.7, "C": 0.45}.get(parse_quality, 0.5)
    if len(core_text) < 1000:
        confidence = max(0.35, confidence - 0.15)

    case_id = make_case_id(row["file_path"])
    summary_text = (core_text or full_text).strip().replace("\n", " ")
    summary_text = re.sub(r"\s+", " ", summary_text)

    evidence_items = []
    for idx, item in enumerate(llm_data.get("evidence", []) if isinstance(llm_data, dict) else [], start=1):
        if not isinstance(item, dict):
            continue
        evidence_type = str(item.get("type", "")).strip()
        quote = str(item.get("quote", "")).strip()
        chunk_id = str(item.get("chunk_id", "")).strip()
        if not evidence_type or not quote:
            continue
        evidence_items.append(
            {
                "id": f"{case_id}_e{idx}",
                "type": evidence_type,
                "quote": quote[:400],
                "chunk_id": chunk_id,
                "source_unit": chunk_map.get(chunk_id, ""),
            }
        )

    # 二次清洗证据，剔除目录/章节标题等无信息内容
    evidence_items = _clean_evidence_items(evidence_items)

    # 清洗各个 profile 字段，去除噪声与空话，并限制长度/数量
    for field_name, values in list(sections.items()):
        sections[field_name] = _clean_profile_items(field_name, values or [])

    # 基于提取到的项目内容完善 rubric_coverage，尤其是 Risk Control：
    # - User Evidence Strength：是否存在 user_evidence 类型的证据；
    # - Business Model Consistency：是否存在 business_model_evidence 类型的证据；
    # - Risk Control：只要项目画像中存在 risk_control 要点，或存在 risk_evidence 证据，即视为已覆盖。
    has_user_evidence = any(e["type"] == "user_evidence" for e in evidence_items)
    has_bm_evidence = any(e["type"] == "business_model_evidence" for e in evidence_items)
    has_risk_profile = bool(sections.get("risk_control"))
    has_risk_evidence = any(e["type"] == "risk_evidence" for e in evidence_items)

    rubric_coverage = [
        {"rubric_item": "User Evidence Strength", "covered": has_user_evidence},
        {"rubric_item": "Business Model Consistency", "covered": has_bm_evidence},
        {"rubric_item": "Risk Control", "covered": has_risk_profile or has_risk_evidence},
    ]

    # Derive lightweight metadata tags for downstream检索与过滤
    tags: list[str] = []
    category = row.get("category", "未分类")
    if category:
        tags.append(f"category:{category}")
    edu_level = str(row.get("education_level", "")).strip()
    if edu_level:
        tags.append(f"education_level:{edu_level}")
    award_level = str(row.get("award_level", "")).strip()
    if award_level:
        tags.append(f"award_level:{award_level}")
    doc_type = str(row.get("doc_type", "") or hypergraph_doc.doc_type).strip()
    if doc_type:
        tags.append(f"doc_type:{doc_type}")
    # 缺失的 risk_control / 风险盲点通过 tags 暴露，而不再使用单独的 risk_flags 字段。
    # 若整个文档未能抽取到任何 risk_control 要点，则打一个汇总 tag。
    if not sections.get("risk_control"):
        tags.append("risk_control:missing")
    # 具体的风险盲点代码（如 weak_user_evidence、market_size_fallacy 等）
    # 以 risk_gap:* 的形式加入 tags，便于下游诊断使用。
    for gap in risk_gaps:
        tags.append(f"risk_gap:{gap}")
    for rc in rubric_coverage:
        if rc.get("covered"):
            name = str(rc.get("rubric_item", "")).strip()
            if name:
                tags.append(f"rubric:{name}")
    tags = unique_keep_order(tags)

    # Get hypergraph statistics
    hypergraph_stats = hypergraph_doc.get_stats()

    # 记录本次抽取时优先使用的 LLM 模型（与 llm_extract_profile 中保持一致）
    effective_llm_model = (
        llm_model
        or settings.llm_reason_model
        or settings.llm_fast_model
        or settings.llm_model
    )

    return {
        "case_id": case_id,
        "document_id": hypergraph_doc.document_id,
        "source": {
            "file_path": row["file_path"],
            "file_name": row.get("file_name", source_path.name),
            "category": row.get("category", "未分类"),
            "doc_type": row.get("doc_type", ""),
            "parse_quality": parse_quality,
            "include_in_kg": bool_from_csv(row.get("include_in_kg", "true"), default=True),
            "education_level": row.get("education_level", "unknown"),
            "year": row.get("year", ""),
            "award_level": row.get("award_level", ""),
            "school": row.get("school", ""),
        },
        "document_stats": {
            "segment_count": parsed.segment_count,
            "full_text_chars": len(full_text),
            "core_text_chars": len(core_text),
            "appendix_start_index": appendix_idx,
            "has_appendix_evidence": appendix_idx is not None,
            # Hypergraph statistics
            "hypergraph_nodes": hypergraph_stats.get("node_count", 0),
            "hypergraph_edges": hypergraph_stats.get("edge_count", 0),
            "hypergraph_hypernode_count": hypergraph_stats.get("hypergraph_nodes", 0),
            "hypergraph_hyperedge_count": hypergraph_stats.get("hypergraph_edges", 0),
        },
        "project_profile": {
            "project_name": project_name,
            "target_users": sections["target_users"],
            "pain_points": sections["pain_points"],
            "solution": sections["solution"],
            "innovation_points": sections["innovation_points"],
            "business_model": sections["business_model"],
            "market_analysis": sections["market_analysis"],
            "execution_plan": sections["execution_plan"],
            "risk_control": sections["risk_control"],
        },
        "tags": tags,
        "evidence": evidence_items,
        "rubric_coverage": rubric_coverage,
        "summary": summary_text[:500],
        "confidence": round(confidence, 2),
        "llm": {
            "enabled": use_llm,
            "provider": settings.llm_provider,
            "model": effective_llm_model,
            "used": bool(llm_data),
        },
        "engine": "hypernetx",
        "generated_at": now_iso(),
    }


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    metadata_path = settings.teacher_examples_root / "metadata.csv"
    out_dir = settings.data_root / "graph_seed" / "case_structured"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = read_metadata(metadata_path)
    included = [r for r in rows if bool_from_csv(r.get("include_in_kg", "true"), default=True)]
    if args.category:
        allowed = set(args.category)
        included = [r for r in included if r.get("category", "") in allowed]
    if args.max_cases and args.max_cases > 0:
        included = included[: args.max_cases]

    llm = LlmClient() if args.llm else None
    if args.llm and (llm is None or not llm.enabled):
        print("LLM disabled: missing llm_api_key/llm_base_url in environment or .env")

    manifest: list[dict] = []
    skipped = 0
    rejected: list[dict[str, str]] = []
    min_quality_rank = {"A": 2, "B": 1}.get(args.min_quality, 1)
    total = len(included)
    print(
        f"starting structured extraction: {total} rows (min_quality={args.min_quality}, "
        f"llm={'on' if args.llm else 'off'}, verify={'on' if args.llm and args.llm_verify else 'off'})",
        flush=True,
    )
    for idx, row in enumerate(included, start=1):
        row_quality = row.get("parse_quality", "C")
        quality_rank = {"A": 2, "B": 1, "C": 0}.get(row_quality, 0)
        if quality_rank < min_quality_rank:
            skipped += 1
            rejected.append(
                {
                    "file_path": row.get("file_path", ""),
                    "category": row.get("category", ""),
                    "parse_quality": row_quality,
                    "reason": f"quality below threshold ({args.min_quality})",
                    "suggestion": "补充可编辑文本版本、减少截图附录或人工摘要后重试。",
                }
            )
            print(
                f"[{idx}/{total}] skip (low_quality={row_quality}) {row.get('file_path', '')}",
                flush=True,
            )
            continue
        try:
            print(
                f"[{idx}/{total}] extracting {row.get('file_path', '')}...",
                flush=True,
            )
            case = build_case_record(
                row,
                use_llm=bool(args.llm and llm and llm.enabled),
                llm=llm,
                llm_model=args.llm_model,
                llm_verify=bool(args.llm and args.llm_verify),
            )
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            print(f"skip {row.get('file_path')}: {exc}")
            rejected.append(
                {
                    "file_path": row.get("file_path", ""),
                    "category": row.get("category", ""),
                    "parse_quality": row_quality,
                    "reason": f"extract_failed: {exc}",
                    "suggestion": "检查文档格式或手工补充关键字段。",
                }
            )
            continue

        out_path = out_dir / f"{case['case_id']}.json"
        out_path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest.append(
            {
                "case_id": case["case_id"],
                "file_path": row["file_path"],
                "category": row.get("category", "未分类"),
                "confidence": case["confidence"],
                "output_file": out_path.name,
            }
        )

        print(
            f"[{idx}/{total}] ok -> {out_path.name} (confidence={case['confidence']})",
            flush=True,
        )

    manifest_path = out_dir / "manifest.json"
    summary_path = out_dir / "summary.json"
    rejection_path = out_dir / args.rejection_file
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with rejection_path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=["file_path", "category", "parse_quality", "reason", "suggestion"])
        writer.writeheader()
        writer.writerows(rejected)
    summary_path.write_text(
        json.dumps(
            {
                "generated_at": now_iso(),
                "metadata_rows": len(rows),
                "included_rows": len(included),
                "generated_cases": len(manifest),
                "skipped": skipped,
                "manifest": manifest_path.name,
                "rejections": rejection_path.name,
                "min_quality": args.min_quality,
                "llm_verify": bool(args.llm and args.llm_verify),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("structured cases generated:", len(manifest))
    print("rejected cases:", len(rejected), "->", rejection_path)
    print("output:", out_dir)

    # Optional: upload structured cases into Neo4j for offline KG analysis.
    if getattr(args, "push_neo4j", False):
        try:
            from kg import import_to_neo4j as kg_import

            kg_import.main()
        except Exception as exc:  # noqa: BLE001
            print(f"neo4j import failed: {exc}")


if __name__ == "__main__":
    main()