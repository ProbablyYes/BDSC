from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

from app.config import settings
from app.services.document_parser import ParsedDocument, TextSegment, parse_document
from ingest.common import (
    bool_from_csv,
    detect_appendix_start,
    now_iso,
    split_lines,
    unique_keep_order,
)

HEADING_RE = re.compile(r"^([一二三四五六七八九十]+[、.]|\d+[、.)]|#|\*{1,2})")
PROJECT_NAME_RE = re.compile(r"(项目名称|项目名|课题名称)[:：]\s*([^\n]{2,80})")

SECTION_KEYWORDS = {
    "target_users": ["用户", "客户", "目标群体", "目标人群"],
    "pain_points": ["痛点", "问题", "需求", "难点"],
    "solution": ["解决方案", "方案", "产品", "系统"],
    "innovation_points": ["创新", "创新点", "差异化", "核心优势"],
    "business_model": ["商业模式", "盈利模式", "收入", "收费"],
    "market_analysis": ["市场", "竞品", "竞争", "tAM", "sam", "som"],
    "execution_plan": ["里程碑", "计划", "进度", "实施路径"],
    "risk_control": ["风险", "合规", "伦理", "隐私", "数据安全"],
}


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


def infer_risk_flags(core_text: str) -> list[str]:
    flags = []
    low = core_text.lower()
    if "没有对手" in core_text or "唯一" in core_text:
        flags.append("no_competitor_claim")
    if "1%" in low or "百分之一" in core_text:
        flags.append("market_size_fallacy")
    if "访谈" not in core_text and "问卷" not in core_text:
        flags.append("weak_user_evidence")
    if "合规" not in core_text and "伦理" not in core_text and "隐私" not in core_text:
        flags.append("compliance_not_covered")
    return flags


def make_case_id(file_path: str) -> str:
    digest = hashlib.sha1(file_path.encode("utf-8")).hexdigest()[:12]
    return f"case_{digest}"


def build_case_record(row: dict) -> dict:
    source_path = settings.teacher_examples_root / row["file_path"]
    parsed = parse_document(source_path)
    appendix_start = row.get("appendix_start_index", "")
    appendix_idx = int(appendix_start) if appendix_start.isdigit() else detect_appendix_start(parsed)

    core = core_segments(parsed, appendix_idx)
    core_text = text_from_segments(core)
    full_text = parsed.full_text

    project_name = infer_project_name(row.get("file_name", source_path.name), core_text or full_text)
    sections = {name: collect_section(core, kws) for name, kws in SECTION_KEYWORDS.items()}
    risk_flags = infer_risk_flags(core_text or full_text)

    parse_quality = row.get("parse_quality", "C")
    confidence = {"A": 0.9, "B": 0.7, "C": 0.45}.get(parse_quality, 0.5)
    if len(core_text) < 1000:
        confidence = max(0.35, confidence - 0.15)

    case_id = make_case_id(row["file_path"])
    summary_text = (core_text or full_text).strip().replace("\n", " ")
    summary_text = re.sub(r"\s+", " ", summary_text)

    return {
        "case_id": case_id,
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
        "risk_flags": risk_flags,
        "summary": summary_text[:500],
        "confidence": round(confidence, 2),
        "generated_at": now_iso(),
    }


def main() -> None:
    metadata_path = settings.teacher_examples_root / "metadata.csv"
    out_dir = settings.data_root / "graph_seed" / "case_structured"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = read_metadata(metadata_path)
    included = [r for r in rows if bool_from_csv(r.get("include_in_kg", "true"), default=True)]

    manifest: list[dict] = []
    skipped = 0
    for row in included:
        if row.get("parse_quality", "C") == "C":
            skipped += 1
            continue
        try:
            case = build_case_record(row)
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            print(f"skip {row.get('file_path')}: {exc}")
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

    manifest_path = out_dir / "manifest.json"
    summary_path = out_dir / "summary.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(
        json.dumps(
            {
                "generated_at": now_iso(),
                "metadata_rows": len(rows),
                "included_rows": len(included),
                "generated_cases": len(manifest),
                "skipped": skipped,
                "manifest": manifest_path.name,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("structured cases generated:", len(manifest))
    print("output:", out_dir)


if __name__ == "__main__":
    main()
