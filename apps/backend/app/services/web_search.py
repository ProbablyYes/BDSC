"""
Web search agent: searches the internet for professional knowledge
to supplement the AI's responses with real-world, up-to-date information.

Uses DuckDuckGo (free, no API key required).
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_STOPWORDS = {
    "我们", "你们", "项目", "产品", "方向", "问题", "一下", "看看", "分析",
    "怎么", "什么", "是否", "这个", "那个", "目前", "现在", "想要", "希望",
    "可以", "以及", "然后", "因为", "如果", "但是", "一个", "一些", "整体",
    "帮我", "我想", "我有", "我的", "想法", "比较", "时候", "地方", "觉得",
    "知道", "需要", "应该", "之类", "的话", "确实", "有没有", "大概", "做到",
    "不过", "还是", "已经", "真的", "比如", "所以", "而且", "就是", "不是",
    "不到", "不了", "可能", "关于", "考虑", "打算", "设想", "进行", "介绍",
    "主要", "其实", "我把", "我再", "我再把", "整个", "完整", "一点", "更好",
    "阶段", "早期", "先帮", "严格", "角度", "不确定", "尝试", "正在",
}
_BLACKLIST_TERMS = {
    "小说", "下载", "破解版", "电影", "成人视频", "博彩", "彩票网站", "游戏攻略",
    "色情", "赌博", "网赚", "兼职日结", "刷单", "棋牌", "彩票", "黄色",
    "视频下载", "种子", "torrent", "porn", "casino", "gambling", "bet365",
    "adult", "xxx", "sex", "slot", "lottery", "贷款", "网贷", "借钱",
    "代写", "代做", "枪手", "挂机", "外挂", "私服", "传奇", "玄幻",
    "算命", "风水", "免费领", "抽奖", "中奖", "加微信",
}
_BLACKLIST_DOMAINS = {
    "porn", "xxx", "adult", "casino", "gambling", "bet", "lottery",
    "torrent", "crack", "warez", "pirate", "onlyfans", "xvideos",
}
_QUALITY_DOMAINS = {
    "zhihu.com", "36kr.com", "jianshu.com", "csdn.net", "mp.weixin.qq.com",
    "baidu.com", "gov.cn", "edu.cn", "org.cn", "nature.com", "ieee.org",
    "arxiv.org", "scholar.google", "wikipedia.org", "github.com",
    "创业邦", "虎嗅", "亿欧", "人民网", "新华网",
}
_DOMAIN_HINTS = [
    "AI", "医疗", "教育", "农业", "电商", "论文", "科研", "研究生", "医院", "医生",
    "患者", "康复", "慢病", "影像", "病历", "问诊", "药物", "文献", "高校", "校园",
]


def _extract_message_keywords(message: str, limit: int = 5) -> list[str]:
    text = re.sub(r"\s+", " ", message or "").strip()
    if not text:
        return []
    keywords: list[str] = []
    for hint in _DOMAIN_HINTS:
        if hint.lower() in text.lower() and hint not in keywords:
            keywords.append(hint)
    for token in re.findall(r"[A-Za-z][A-Za-z0-9\-\+]{1,24}|[\u4e00-\u9fff]{2,5}", text):
        word = token.strip()
        if not word or word.lower() in _STOPWORDS or word in _STOPWORDS:
            continue
        if len(word) > 1 and all("\u4e00" <= c <= "\u9fff" for c in word):
            if any(sw in word for sw in _STOPWORDS):
                continue
        if word not in keywords:
            keywords.append(word)
        if len(keywords) >= limit:
            break
    return keywords[:limit]


def _intent_search_prefix(intent: str, message: str) -> str:
    if intent == "market_competitor":
        return "同类产品 竞品 替代方案"
    if intent == "competition_prep":
        return "创业大赛 评委 评分 路演"
    if intent == "business_model":
        return "创业项目 商业模式 定价 渠道"
    if intent == "idea_brainstorm":
        return "创业方向 趋势 场景"
    if intent == "pressure_test":
        return "创业项目 替代方案 竞争 风险"
    if intent == "learning_concept":
        return "创新创业 方法论 案例"
    if intent == "project_diagnosis":
        if any(word in message for word in ("医疗", "医生", "医院", "患者", "病历", "康复")):
            return "AI医疗 创业 场景"
        return "创业项目 案例 分析"
    return "创新创业"


def _build_search_query(message: str, intent: str) -> str | None:
    """Generate a focused search query based on the student's message and intent."""
    prefix = _intent_search_prefix(intent, message)
    if not prefix:
        return None

    keywords = _extract_message_keywords(message, limit=4)
    if not keywords:
        return prefix[:50]

    good_kw = [kw for kw in keywords[:3] if len(kw) <= 12 and not any(sw in kw for sw in ("我", "你", "他", "她"))]
    query = f"{prefix} {' '.join(good_kw[:2])}"
    return query[:55]


def _result_relevance(item: dict[str, str], query_keywords: list[str]) -> int:
    text = f"{item.get('title','')} {item.get('body','')} {item.get('href','')}".lower()
    href = item.get("href", "").lower()
    if any(term in text for term in _BLACKLIST_TERMS):
        return -100
    if any(bd in href for bd in _BLACKLIST_DOMAINS):
        return -100
    score = 0
    if any(qd in href for qd in _QUALITY_DOMAINS):
        score += 3
    for kw in query_keywords:
        kw_l = kw.lower()
        if kw_l and kw_l in text:
            score += 2
    if any(sig in text for sig in ("创业", "商业", "竞品", "市场", "ai", "医疗", "行业", "案例", "论文", "研究")):
        score += 1
    return score


def web_search(message: str, intent: str, max_results: int = 3) -> dict[str, Any]:
    """
    Search the web for relevant professional knowledge.
    Returns structured results with titles, snippets, and URLs.
    """
    query = _build_search_query(message, intent)
    if not query:
        return {"searched": False, "query": None, "results": [], "summary": ""}
    query_keywords = _extract_message_keywords(query, limit=6)

    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results, region="cn-zh"))
        ranked = sorted(raw, key=lambda item: _result_relevance(item, query_keywords), reverse=True)

        results: list[dict[str, str]] = []
        for item in ranked:
            if _result_relevance(item, query_keywords) < 2:
                continue
            results.append({
                "title": item.get("title", ""),
                "snippet": item.get("body", "")[:200],
                "url": item.get("href", ""),
            })
            if len(results) >= max_results:
                break

        summary = ""
        if results:
            snippets = [r["snippet"] for r in results if r["snippet"]]
            summary = "\n".join(f"- {s}" for s in snippets[:3])

        return {
            "searched": True,
            "query": query,
            "results": results,
            "summary": summary,
        }
    except Exception as exc:
        logger.warning("Web search failed for query '%s': %s", query, exc)
        return {"searched": False, "query": query, "results": [], "summary": "", "error": str(exc)}


def format_for_llm(search_result: dict[str, Any], max_chars: int = 600) -> str:
    """Format web search results into context for LLM prompts."""
    if not search_result.get("searched") or not search_result.get("results"):
        return ""
    parts: list[str] = [f"## 联网搜索结果（关键词: {search_result['query']}）"]
    for r in search_result["results"][:3]:
        parts.append(f"- **{r['title']}**: {r['snippet']}")
    text = "\n".join(parts)
    return text[:max_chars]
