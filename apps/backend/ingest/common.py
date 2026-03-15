from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from app.services.document_parser import ParsedDocument

SUPPORTED_DOC_SUFFIXES = {".pdf", ".pptx", ".ppt", ".docx", ".txt", ".md"}

APPENDIX_KEYWORDS = [
    "附录",
    "附件",
    "证明材料",
    "佐证材料",
    "补充材料",
    "支撑材料",
    "截图",
    "evidence",
    "appendix",
    "supplementary",
]


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def normalize_rel_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def detect_category(rel_path: Path) -> str:
    # Root-level files are treated as uncategorized records.
    return rel_path.parts[0] if len(rel_path.parts) > 1 else "未分类"


def bool_from_csv(value: str, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def detect_appendix_start(parsed: ParsedDocument) -> int | None:
    for segment in parsed.segments:
        low = segment.text.lower()
        if any(k.lower() in low for k in APPENDIX_KEYWORDS):
            return segment.index
    return None


def parse_quality(parsed: ParsedDocument) -> tuple[str, str]:
    chars = parsed.text_chars
    seg_count = parsed.segment_count
    if chars == 0 or seg_count == 0:
        return "C", "文档几乎未提取到有效文本，疑似扫描件或受保护文件。"

    short_segments = [s for s in parsed.segments if len(s.text.strip()) < 30]
    short_ratio = len(short_segments) / max(seg_count, 1)

    if parsed.doc_type == "pdf" and short_ratio > 0.7 and seg_count >= 8:
        return "C", "PDF 页面大多为低文本密度，疑似截图附录占比过高。"
    if chars < 300 or seg_count < 3:
        return "C", "文本量不足，难以支撑结构化抽取。"
    if chars < 1800 or short_ratio > 0.5:
        return "B", "可提取文本有限，建议人工复核关键字段。"
    return "A", "文本质量良好，可用于自动结构化抽取。"


def split_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    return [line for line in lines if line]


def unique_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = item.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out
