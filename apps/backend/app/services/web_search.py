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
}
_BLACKLIST_TERMS = {
    "小说", "下载", "破解版", "电影", "成人视频", "博彩", "彩票网站", "游戏攻略",
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
    for token in re.findall(r"[A-Za-z][A-Za-z0-9\-\+]{1,24}|[\u4e00-\u9fff]{2,8}", text):
        word = token.strip()
        if not word or word.lower() in _STOPWORDS or word in _STOPWORDS:
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

    keywords = _extract_message_keywords(message)
    if not keywords:
        return prefix[:80]

    query = f"{prefix} {' '.join(keywords[:3])}"
    return query[:80]


def _result_relevance(item: dict[str, str], query_keywords: list[str]) -> int:
    text = f"{item.get('title','')} {item.get('body','')} {item.get('href','')}".lower()
    if any(term in text for term in _BLACKLIST_TERMS):
        return -100
    score = 0
    for kw in query_keywords:
        kw_l = kw.lower()
        if kw_l and kw_l in text:
            score += 2
    if any(sig in text for sig in ("创业", "商业", "竞品", "市场", "ai", "医疗", "行业", "案例")):
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
            if _result_relevance(item, query_keywords) < 1:
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
