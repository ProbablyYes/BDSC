"""
Web search agent: searches the internet for professional knowledge
to supplement the AI's responses with real-world, up-to-date information.

Uses DuckDuckGo (free, no API key required).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _build_search_query(message: str, intent: str) -> str | None:
    """Generate a focused search query based on the student's message and intent."""
    INTENT_SEARCH_PREFIXES = {
        "business_model": "创业 商业模式",
        "project_diagnosis": "创业项目 分析",
        "evidence_check": "用户调研 方法论",
        "competition_prep": "互联网+ 创业大赛 评审标准",
        "learning_concept": "创新创业",
        "idea_brainstorm": "创业方向 趋势",
        "market_competitor": "竞品分析 同类产品",
        "pressure_test": "创业 风险分析",
        "general_chat": "创新创业",
    }
    prefix = INTENT_SEARCH_PREFIXES.get(intent, "创新创业")
    if not prefix:
        return None

    keywords: list[str] = []
    for term in ["商业模式", "盈利", "市场规模", "TAM", "SAM", "用户调研",
                 "竞品分析", "路演", "MVP", "精益创业", "获客成本",
                 "融资", "股权", "痛点", "用户画像", "定价策略",
                 "创业计划书", "商业画布", "价值主张"]:
        if term.lower() in message.lower():
            keywords.append(term)

    if not keywords:
        words = message[:60].replace("我想", "").replace("我们", "").replace("怎么", "").strip()
        keywords = [words[:20]]

    query = f"{prefix} {' '.join(keywords[:3])}"
    return query[:80]


def web_search(message: str, intent: str, max_results: int = 3) -> dict[str, Any]:
    """
    Search the web for relevant professional knowledge.
    Returns structured results with titles, snippets, and URLs.
    """
    query = _build_search_query(message, intent)
    if not query:
        return {"searched": False, "query": None, "results": [], "summary": ""}

    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results, region="cn-zh"))

        results: list[dict[str, str]] = []
        for item in raw:
            results.append({
                "title": item.get("title", ""),
                "snippet": item.get("body", "")[:200],
                "url": item.get("href", ""),
            })

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
