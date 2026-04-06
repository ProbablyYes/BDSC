from __future__ import annotations

"""Offline script to enrich structured case JSONs with创业相关分类。

功能：
- 浏览每个 case_*.json 对应的源文件名和结构化内容；
- 若文本中出现“有限责任公司”，则在分类中写入 类型="创业"、名称="high relevance"；
- 否则若出现“创业”，则写入 类型="创业"、名称="relevance"；
- 若已有同类型记录，则按优先级进行合并（high relevance > relevance），保持幂等。

使用方式（从 workspace 根目录）：

    cd apps/backend
    python -m ingest.enrich_case_entrepreneurship

该脚本会就地更新 data/graph_seed/case_structured 下的 case_*.json 文件。
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.config import settings


# 关键词配置：
# - HIGH_RELEVANCE_KEYWORDS 命中则标记为 "high relevance"；
# - RELEVANCE_KEYWORDS 命中则（在未命中 high 的前提下）标记为 "relevance"。
#
# 说明：
# - HIGH 侧重“真实企业主体/公司化运营”的线索，例如各种形式的有限公司、股份公司等；
# - 普通 RELEVANCE 明确聚焦“创业”活动本身，例如创业项目/创业大赛/创业计划书，
#   不会因为只出现“创新”“创新能力”“科技创新”等词就被误判为创业相关。

HIGH_RELEVANCE_KEYWORDS: list[str] = [
    "有限责任公司",
    "有限公司",  # 例如 “某某科技有限公司”
    "股份有限公司",
    "创业公司",
    "初创公司",
]

RELEVANCE_KEYWORDS: list[str] = [
    "创业",
    "大学生创业",
    "创业项目",
    "创业计划",
    "创业计划书",
    "创业实践",
    "创业团队",
    "创业大赛",
]


def _gather_text_from_case(case: Dict[str, Any]) -> str:
    """Collect relevant text from a case JSON (file name + profile + summary + evidence)."""

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

    return "\n".join(parts)


def _detect_entrepreneurship_level(text: str) -> str:
    """Return desired 名称 value for 类型="创业": "high relevance" / "relevance" / "".

    优先级：
    - 若命中 HIGH_RELEVANCE_KEYWORDS 中任意一个短语，返回 "high relevance"；
    - 否则若命中 RELEVANCE_KEYWORDS 中任意一个短语，返回 "relevance"；
    - 否则返回空字符串（不添加分类）。
    """

    if not text:
        return ""

    # 先判断高相关度：任何一个高相关关键词命中即可。
    for kw in HIGH_RELEVANCE_KEYWORDS:
        if kw and kw in text:
            return "high relevance"

    # 再判断一般相关度。
    for kw in RELEVANCE_KEYWORDS:
        if kw and kw in text:
            return "relevance"

    return ""


def _rank_level(name: str) -> int:
    """Map 名称 to priority rank (larger = stronger relevance)."""

    if name == "high relevance":
        return 2
    if name == "relevance":
        return 1
    return 0


def _merge_entrepreneurship_classification(case: Dict[str, Any], desired_name: str) -> bool:
    """Merge entrepreneurship classification into case["分类"].

    - desired_name: "high relevance" / "relevance" / "".
    - 返回 True 表示 JSON 有修改。
    """

    if not desired_name:
        return False

    existing = case.get("分类")
    records: List[Dict[str, Any]] = []
    best_level = _rank_level(desired_name)

    # 先保留所有非“创业”类型的分类；同时收集已有创业分类的最高等级。
    if isinstance(existing, list):
        for item in existing:
            if not isinstance(item, dict):
                continue
            rec_type = str(item.get("类型", "")).strip()
            rec_name = str(item.get("名称", "")).strip()
            if not rec_type and not rec_name:
                continue
            if rec_type == "创业":
                level = _rank_level(rec_name)
                if level > best_level:
                    best_level = level
            else:
                records.append({"类型": rec_type, "名称": rec_name})

    # 根据最高等级决定最终要写入的 名称。
    final_name: str
    if best_level >= 2:
        final_name = "high relevance"
    elif best_level == 1:
        final_name = "relevance"
    else:
        # 若既没有检测到关键词，也没有有意义的既有值，则不写入。
        return False

    # 追加/覆盖一个统一的创业分类记录。
    records.append({"类型": "创业", "名称": final_name})

    # 若 records 与原始 分类 完全一致，可以认为无变化；这里为简单起见直接赋值。
    case["分类"] = records
    return True


def enrich_entrepreneurship() -> None:
    """Main entry: scan all case JSONs and enrich with entrepreneurship classification."""

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
            case: Dict[str, Any] = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            print(f"skip {path.name}: read/parse error: {exc}")
            continue

        text = _gather_text_from_case(case)
        desired_name = _detect_entrepreneurship_level(text)
        if not desired_name:
            continue

        if not _merge_entrepreneurship_classification(case, desired_name):
            continue

        try:
            path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print(f"failed to write {path.name}: {exc}")
            continue

        updated_files += 1
        print(f"updated {path.name}: 创业={desired_name}")

    print(f"entrepreneurship enrichment done. total={total_files}, updated={updated_files}")


if __name__ == "__main__":  # pragma: no cover
    enrich_entrepreneurship()
