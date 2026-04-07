from __future__ import annotations

"""Offline script to enrich structured case JSONs with competition (赛事) classification.

Usage (from workspace root):

    python -m ingest.enrich_case_competitions

This will scan all case_*.json files under data/graph_seed/case_structured,
inspect both the original file name (source.file_name / source.file_path)
AND the structured content (project_profile, summary, evidence),
then, when it detects known competition keywords such as "挑战杯"、"互联网+"、"创青春",
append a new top-level field "分类" with entries of the form:

    "分类": [
        {"类型": "赛事", "名称": "挑战杯"},
        {"类型": "赛事", "名称": "互联网+大学生创新创业大赛"},
    ]

Existing 分类 entries are preserved and merged (去重 by 类型+名称).
"""

import json
from pathlib import Path
from typing import Any, Dict, List

from app.config import settings


# Canonical competition names we care about, together with simple
# keyword-based detection rules. Detection is conservative to
# avoid把普通“互联网+”口号误判为赛事。
COMPETITION_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "挑战杯",
        "aliases": ["挑战杯"],
    },
    {
        # 中国国际“互联网+”大学生创新创业大赛
        "name": "互联网+大学生创新创业大赛",
        # 只要文本中同时出现“互联网+”和典型赛事用语（大赛/竞赛/专项赛），
        # 即视为该赛事的引用。
        "aliases": ["互联网+"],
        "require_competition_word": True,
    },
    {
        "name": "创青春",
        "aliases": ["创青春"],
    },
]

# 在“互联网+”检测中使用的典型赛事词。
COMPETITION_WORDS = ["大赛", "竞赛", "专项赛", "比赛"]


def _gather_text_from_case(case: Dict[str, Any]) -> str:
    """Collect all relevant text fields (file name + content) into one string.

    包含：
    - source.file_name / source.file_path
    - project_profile 中各字段
    - summary
    - evidence[].quote
    """

    parts: List[str] = []

    source = case.get("source", {}) or {}
    for key in ("file_name", "file_path"):
        val = source.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())

    profile = case.get("project_profile", {}) or {}
    for value in profile.values():
        if isinstance(value, str):
            if value.strip():
                parts.append(value.strip())
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    parts.append(item.strip())

    summary = case.get("summary")
    if isinstance(summary, str) and summary.strip():
        parts.append(summary.strip())

    for ev in case.get("evidence", []) or []:
        if not isinstance(ev, dict):
            continue
        quote = ev.get("quote")
        if isinstance(quote, str) and quote.strip():
            parts.append(quote.strip())

    # 直接拼接为一个长文本即可，中文不区分大小写。
    return "\n".join(parts)


def _detect_competitions(text: str) -> List[str]:
    """Return a list of canonical competition names detected in text.

    规则：
    - "挑战杯"：出现即认为属于该赛事。
    - "互联网+大学生创新创业大赛"：文本中包含“互联网+”且同时出现“大赛/竞赛/专项赛/比赛”等词；
    - "创青春"：出现即认为属于该赛事。
    """

    if not text:
        return []

    result: List[str] = []

    for comp in COMPETITION_DEFINITIONS:
        name = str(comp.get("name", "")).strip()
        if not name:
            continue
        aliases = [a for a in comp.get("aliases", []) if isinstance(a, str) and a]
        require_comp_word = bool(comp.get("require_competition_word", False))

        found = False
        for alias in aliases:
            if not alias:
                continue
            if alias in text:
                if require_comp_word:
                    # 对“互联网+”类赛事，再要求同时出现典型赛事用语，
                    # 避免把“互联网+政务服务”等一般描述误识别为赛事。
                    if any(w in text for w in COMPETITION_WORDS):
                        found = True
                        break
                else:
                    found = True
                    break
        if found and name not in result:
            result.append(name)

    return result


def _merge_classification(case: Dict[str, Any], competitions: List[str]) -> bool:
    """Merge detected competitions into case["分类"].

    Returns True if the case JSON was modified.
    """

    if not competitions:
        return False

    existing = case.get("分类")
    records: List[Dict[str, Any]] = []
    if isinstance(existing, list):
        for item in existing:
            if isinstance(item, dict):
                # 只保留有 类型 / 名称 两个字段的记录，其余按原样忽略。
                rec_type = str(item.get("类型", "")).strip()
                rec_name = str(item.get("名称", "")).strip()
                if rec_type or rec_name:
                    records.append({"类型": rec_type, "名称": rec_name})

    seen = {(r["类型"], r["名称"]) for r in records}
    changed = False

    for comp_name in competitions:
        key = ("赛事", comp_name)
        if key in seen:
            continue
        records.append({"类型": "赛事", "名称": comp_name})
        seen.add(key)
        changed = True

    if not changed:
        return False

    case["分类"] = records
    return True


def enrich_competitions() -> None:
    """Main entry: scan all case JSONs and enrich with competition info."""

    case_dir: Path = settings.data_root / "graph_seed" / "case_structured"
    if not case_dir.exists():
        print(f"case directory not found: {case_dir}")
        return

    total_files = 0
    updated_files = 0

    for path in sorted(case_dir.glob("case_*.json")):
        total_files += 1
        try:
            raw = path.read_text(encoding="utf-8")
            case = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            print(f"skip {path.name}: read/parse error: {exc}")
            continue

        text = _gather_text_from_case(case)
        competitions = _detect_competitions(text)
        if not competitions:
            continue

        if not _merge_classification(case, competitions):
            continue

        try:
            path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print(f"failed to write {path.name}: {exc}")
            continue

        updated_files += 1
        print(f"updated {path.name}: 赛事={competitions}")

    print(f"competition enrichment done. total={total_files}, updated={updated_files}")


if __name__ == "__main__":  # pragma: no cover
    enrich_competitions()
