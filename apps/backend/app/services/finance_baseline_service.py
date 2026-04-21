"""
finance_baseline_service — 行业财务基线三层查询服务

设计原则（跟用户确认后的方案）:
1. 聊天侧 finance_guard 走 allow_online=False —— 只读本地缓存，永不阻塞对话。
2. 深度报告 finance_report_service 走 allow_online=True —— 数据过期时联网刷新。
3. 优先级：本地 JSON 缓存 → 联网搜索 + LLM 抽数 → 硬编码 seed 兜底。

文件布局:
  data/finance_baselines/_seed.json      启动时从 INDUSTRY_BASELINES 写入一次
  data/finance_baselines/教育.json       该行业最新版本（含 source/url/updated_at）
  data/finance_baselines/SaaS.json
  ...

每个行业文件格式:
  {
    "industry": "SaaS",
    "baseline": { "cac_range": [...], ... },   # 与 INDUSTRY_BASELINES[ind] 字段完全一致
    "source": "seed" | "web" | "teacher_edit",
    "updated_at": "2026-04-17T10:00:00Z",
    "evidence": [
      {"field": "cac_range", "value": [200, 1500], "url": "...", "snippet": "..."}
    ]
  }
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 延迟导入，避免循环依赖
_BASELINES_DIR = Path("data/finance_baselines")
_SEED_FILE = _BASELINES_DIR / "_seed.json"
_FRESH_DAYS = 90           # 超过这么多天视为过期
_WEB_CACHE_DAYS = 30       # 联网刷新间隔（即便未过期，用户主动触发也能强刷）
_LOCK = threading.Lock()
_SEED_INITED: bool = False


# ══════════════════════════════════════════════════════════════════
#  基础工具
# ══════════════════════════════════════════════════════════════════

def _ensure_dir() -> None:
    _BASELINES_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _is_fresh(payload: dict, max_age_days: int = _FRESH_DAYS) -> bool:
    dt = _parse_iso(payload.get("updated_at"))
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - dt < timedelta(days=max_age_days)


def _slugify(industry_key: str) -> str:
    # 行业名已经是内置枚举，直接当文件名够用；禁止路径穿越
    safe = "".join(c for c in industry_key if c.isalnum() or c in "-_\u4e00-\u9fff")
    return safe or "unknown"


def _cache_path(industry_key: str) -> Path:
    return _BASELINES_DIR / f"{_slugify(industry_key)}.json"


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("finance_baseline read failed (%s): %s", path, exc)
        return None


def _write_json(path: Path, payload: dict) -> None:
    _ensure_dir()
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


# ══════════════════════════════════════════════════════════════════
#  Seed 初始化
# ══════════════════════════════════════════════════════════════════

def init_seed_if_missing() -> None:
    """第一次启动时把 INDUSTRY_BASELINES 写成 seed 文件。后续不覆盖。"""
    global _SEED_INITED
    if _SEED_INITED:
        return
    with _LOCK:
        if _SEED_INITED:
            return
        _ensure_dir()
        # 懒加载，避免循环依赖
        from .finance_analyst import INDUSTRY_BASELINES

        if not _SEED_FILE.exists():
            seed = {
                "industries": {
                    key: {
                        "industry": key,
                        "baseline": dict(value),
                        "source": "seed",
                        "updated_at": _now_iso(),
                        "evidence": [],
                    }
                    for key, value in INDUSTRY_BASELINES.items()
                },
                "created_at": _now_iso(),
                "note": "Seed baselines from finance_analyst.INDUSTRY_BASELINES",
            }
            _write_json(_SEED_FILE, seed)
            logger.info("finance_baseline seed written to %s", _SEED_FILE)

        # 同时：为每个行业生成单文件缓存（如不存在）
        seed = _read_json(_SEED_FILE) or {}
        industries = seed.get("industries", {})
        for key, rec in industries.items():
            path = _cache_path(key)
            if not path.exists():
                _write_json(path, rec)
        _SEED_INITED = True


def _seed_baseline(industry_key: str) -> dict | None:
    """从 seed 文件拿一条 baseline，找不到返回 None。"""
    seed = _read_json(_SEED_FILE) or {}
    industries = seed.get("industries", {})
    rec = industries.get(industry_key)
    if rec:
        return rec
    return None


# ══════════════════════════════════════════════════════════════════
#  联网刷新（allow_online=True 时才走）
# ══════════════════════════════════════════════════════════════════

_FIELDS_SPEC = {
    "cac_range": "获客成本（CAC）合理区间，元/付费用户",
    "monthly_price_range": "典型月价 / ARPU 区间，元",
    "monthly_retention": "月留存率区间，0-1 的小数",
    "gross_margin": "毛利率区间，0-1 的小数",
    "avg_user_lifetime_months": "平均用户生命周期（月）",
}


def _ddg_snippets(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """轻量 DDGS 检索，返回 [{title, snippet, url}]。"""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results, region="cn-zh"))
        out = []
        for item in raw:
            out.append({
                "title": item.get("title", ""),
                "snippet": (item.get("body", "") or "")[:400],
                "url": item.get("href", ""),
            })
        return out
    except Exception as exc:
        logger.warning("ddgs failed for '%s': %s", query, exc)
        return []


def _llm_extract_numbers(industry_key: str, snippets: list[dict]) -> dict[str, Any]:
    """
    把一堆网页 snippet 喂给 LLM，让它抽出结构化的数字区间。
    失败/LLM 未启用 → 返回 {}。
    """
    if not snippets:
        return {}
    try:
        from .llm_client import llm_client
    except Exception:
        return {}
    if not getattr(llm_client, "enabled", False):
        return {}

    context = "\n\n".join(
        f"[{i + 1}] {s.get('title', '')}\n{s.get('snippet', '')}\n来源: {s.get('url', '')}"
        for i, s in enumerate(snippets[:6])
    )

    field_spec = "\n".join(f"- {k}: {v}" for k, v in _FIELDS_SPEC.items())

    system = (
        "你是财务/行业研究分析师。任务：从提供的若干网页摘录中抽取一个行业的关键财务基线数字。\n"
        "严格遵守：\n"
        "1. 只能根据提供的摘录归纳，不得凭空编造。\n"
        "2. 同一字段若多个来源不一致，取中位或给出包含主流观点的区间。\n"
        "3. 抽不到的字段就省略；宁缺毋滥。\n"
        "4. 每条数据必须绑定 evidence（引用哪条 snippet 的 url）。"
    )
    user = (
        f"目标行业: {industry_key}\n\n"
        f"需要抽取的字段（数据口径）:\n{field_spec}\n\n"
        f"网页摘录:\n{context}\n\n"
        "请返回 JSON，结构:\n"
        "{\n"
        '  "baseline": {"cac_range": [lo, hi], "monthly_price_range": [lo, hi], '
        '"monthly_retention": [lo, hi], "gross_margin": [lo, hi], "avg_user_lifetime_months": N, "note": "一句话总结"},\n'
        '  "evidence": [{"field": "cac_range", "value": [lo, hi], "url": "...", "snippet": "..."}]\n'
        "}\n"
        "抽不到的字段直接不写。"
    )

    try:
        result = llm_client.chat_json(system_prompt=system, user_prompt=user, temperature=0.0)
    except Exception as exc:
        logger.warning("LLM extract baseline failed (%s): %s", industry_key, exc)
        return {}
    if not isinstance(result, dict):
        return {}
    return result


def _merge_with_seed(industry_key: str, llm_out: dict) -> dict | None:
    """把 LLM 抽出的字段合到 seed 之上，返回完整记录。"""
    seed_rec = _seed_baseline(industry_key)
    if not seed_rec:
        return None
    base = dict(seed_rec.get("baseline", {}))
    llm_base = llm_out.get("baseline") if isinstance(llm_out, dict) else None
    if isinstance(llm_base, dict):
        for k, v in llm_base.items():
            if k in _FIELDS_SPEC or k == "note":
                base[k] = v
    return {
        "industry": industry_key,
        "baseline": base,
        "source": "web",
        "updated_at": _now_iso(),
        "evidence": llm_out.get("evidence", []) if isinstance(llm_out, dict) else [],
    }


def refresh_from_web(industry_key: str) -> dict | None:
    """联网刷新指定行业的基线，成功返回新记录并落盘，失败返回 None。"""
    _ensure_dir()
    query = f"{industry_key} 行业 CAC LTV 毛利率 留存率 基准 2024"
    snippets = _ddg_snippets(query, max_results=5)
    if not snippets:
        return None
    llm_out = _llm_extract_numbers(industry_key, snippets)
    if not llm_out:
        return None
    merged = _merge_with_seed(industry_key, llm_out)
    if not merged:
        return None
    _write_json(_cache_path(industry_key), merged)
    logger.info("finance_baseline refreshed from web: %s", industry_key)
    return merged


# ══════════════════════════════════════════════════════════════════
#  对外：统一解析入口
# ══════════════════════════════════════════════════════════════════

def _match_industry_key(industry_hint: str) -> str:
    """归一化到 INDUSTRY_BASELINES 内的 key。"""
    from .finance_analyst import _match_industry
    return _match_industry(industry_hint)


def resolve_baseline(industry_hint: str, *, allow_online: bool = False) -> dict[str, Any]:
    """
    返回与 INDUSTRY_BASELINES[ind] 字段完全兼容的 dict，同时附带 _meta。
    聊天侧 allow_online=False，只读本地。
    深度报告 allow_online=True，文件过期会尝试联网刷新。
    """
    key = _match_industry_key(industry_hint)
    init_seed_if_missing()

    cache = _read_json(_cache_path(key))
    need_refresh = allow_online and (cache is None or not _is_fresh(cache, _FRESH_DAYS))
    if need_refresh:
        refreshed = refresh_from_web(key)
        if refreshed:
            cache = refreshed

    if cache is None:
        # 真的啥都没有，回退到 seed（此时理论上 init 已经写过）
        cache = _seed_baseline(key) or {
            "industry": key,
            "baseline": {},
            "source": "hardcoded",
            "updated_at": _now_iso(),
            "evidence": [],
        }

    baseline = dict(cache.get("baseline", {}))
    # 塞入 _meta，方便上游追踪数据来源
    baseline["_meta"] = {
        "industry": key,
        "source": cache.get("source", "seed"),
        "updated_at": cache.get("updated_at"),
        "evidence_count": len(cache.get("evidence", []) or []),
    }
    return baseline


def get_baseline_record(industry_hint: str) -> dict | None:
    """拿完整记录（含 evidence 明细），给老师端/面板用。"""
    key = _match_industry_key(industry_hint)
    init_seed_if_missing()
    return _read_json(_cache_path(key))


def list_all_baselines() -> list[dict]:
    """列出所有行业的基线记录，给老师端管理用。"""
    init_seed_if_missing()
    out: list[dict] = []
    for path in sorted(_BASELINES_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        rec = _read_json(path)
        if rec:
            out.append(rec)
    return out


__all__ = [
    "init_seed_if_missing",
    "resolve_baseline",
    "get_baseline_record",
    "list_all_baselines",
    "refresh_from_web",
]
