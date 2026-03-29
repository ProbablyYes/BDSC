from __future__ import annotations

import json
from pathlib import Path

from app.config import settings


CATEGORY_KEYWORDS = {
    "医疗健康": ["医疗", "健康", "医院", "诊疗", "放射", "药"],
    "科技创新": ["ai", "算法", "模型", "大模型", "芯片", "机器人", "数据"],
    "教育服务": ["教育", "课堂", "教学", "学习", "教培"],
    "环境保护": ["环保", "碳", "减排", "污染", "生态"],
    "乡村振兴": ["乡村", "农业", "农田", "助农", "种植"],
    "智能制造": ["制造", "工业", "工厂", "装备", "生产"],
    "文旅文创": ["文旅", "文创", "旅游", "文化"],
    "社会治理": ["政务", "治理", "公共服务", "风险治理"],
    # 新增“社会公益”类别，对应 teacher_examples/社会公益 目录
    "社会公益": [
        "公益",
        "慈善",
        "志愿",
        "志愿服务",
        "社会服务",
        "社区服务",
        "社会组织",
        "公益项目",
    ],
}


def _structured_dir() -> Path:
    return settings.data_root / "graph_seed" / "case_structured"


def _read_manifest() -> list[dict]:
    path = _structured_dir() / "manifest.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def infer_category(text: str) -> str:
    low = text.lower()
    for category, words in CATEGORY_KEYWORDS.items():
        if any(w.lower() in low for w in words):
            return category
    return "科技创新"


def retrieve_cases_by_category(category: str, limit: int = 3) -> list[dict]:
    manifest = _read_manifest()
    hits = [item for item in manifest if item.get("category") == category]
    if not hits:
        hits = manifest[:]
    hits = hits[:limit]
    return [
        {
            "case_id": item.get("case_id"),
            "category": item.get("category"),
            "file_path": item.get("file_path"),
            "confidence": item.get("confidence"),
        }
        for item in hits
    ]


def category_patterns(limit: int = 5) -> list[dict]:
    manifest = _read_manifest()
    counter: dict[str, int] = {}
    for item in manifest:
        cat = item.get("category", "未分类")
        counter[cat] = counter.get(cat, 0) + 1
    top = sorted(counter.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [{"category": cat, "case_count": count} for cat, count in top]
