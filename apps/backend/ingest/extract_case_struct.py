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
    if not segments:
        return []

    # Detect split strategy
    if split_by == "page":
        page_markers = [seg for seg in segments if "page" in seg.text.lower()]
        if page_markers:
            # Split by page markers
            return _split_by_markers(segments, page_markers, max_chunks, max_chars_per_chunk)
    elif split_by == "chapter":
        chapter_markers = [seg for seg in segments if HEADING_RE.match(seg.text)]
        if chapter_markers:
            # Split by chapter markers
            return _split_by_markers(segments, chapter_markers, max_chunks, max_chars_per_chunk)

    # Default scoring-based chunk selection
    scored: list[tuple[int, TextSegment]] = [(_segment_score(seg.text), seg) for seg in segments if seg.text.strip()]
    scored.sort(key=lambda x: (x[0], len(x[1].text)), reverse=True)

    selected: list[TextSegment] = [seg for _, seg in scored[:max_chunks]]
    # Keep context from beginning to avoid losing project basics.
    for seg in segments[:2]:
        if seg not in selected:
            selected.append(seg)

    selected = sorted(selected, key=lambda s: s.index)[:max_chunks]
    out: list[dict[str, str]] = []
    for idx, seg in enumerate(selected, start=1):
        out.append(
            {
                "chunk_id": f"C{idx}",
                "source_unit": seg.source_unit,
                "text": seg.text[:max_chars_per_chunk],
            }
        )
    return out

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
    noisy_tokens = ["图注", "figure", "截图", "附图", "图片来源", "见下图", "如下图"]
    out: list[TextSegment] = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        low = text.lower()
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
        "business_model": ["string"],
        "market_analysis": ["string"],
        "execution_plan": ["string"],
        "risk_control": ["string"],
        "risk_flags": ["no_competitor_claim|market_size_fallacy|weak_user_evidence|compliance_not_covered"],
        "evidence": [
            {
                "type": "user_evidence|business_model_evidence|risk_evidence",
                "quote": "string",
                "chunk_id": "Cx",
            }
        ],
    }
    system_prompt = (
        "你是创新创业项目结构化抽取助手。"
        "请只基于给定chunks提取信息，输出严格JSON对象。"
        "不确定时返回空数组，不要编造。"
    )
    user_prompt = (
        f"默认项目名: {default_project_name}\n"
        f"请按此JSON结构返回: {json.dumps(schema_hint, ensure_ascii=False)}\n"
        f"文档片段: {json.dumps(chunks, ensure_ascii=False)}"
    )
    return llm.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model_override or None,
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
        "project_profile_patch": {
            "target_users": ["string"],
            "pain_points": ["string"],
            "solution": ["string"],
            "business_model": ["string"],
            "risk_control": ["string"],
        },
        "evidence_patch": [
            {"type": "user_evidence|business_model_evidence|risk_evidence", "quote": "string", "chunk_id": "Cx"}
        ],
        "drop_flags": ["string"],
    }
    system_prompt = (
        "你是结构化抽取质检助手。"
        "只保留在文档片段中有明确证据支持的字段，删除无依据内容。"
        "返回严格JSON对象。"
    )
    user_prompt = (
        f"已有抽取草稿: {json.dumps(draft_profile, ensure_ascii=False)}\n"
        f"文档片段: {json.dumps(chunks, ensure_ascii=False)}\n"
        f"请按结构返回: {json.dumps(verify_schema, ensure_ascii=False)}"
    )
    return llm.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=settings.llm_reason_model or settings.llm_fast_model,
        temperature=0.0,
    )


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


def build_case_record(
    row: dict,
    use_llm: bool = False,
    llm: LlmClient | None = None,
    llm_model: str = "",
    llm_verify: bool = False,
) -> dict:
    source_path = settings.teacher_examples_root / row["file_path"]
    parsed = parse_document(source_path)
    appendix_start = row.get("appendix_start_index", "")
    appendix_idx = int(appendix_start) if appendix_start.isdigit() else detect_appendix_start(parsed)

    core = filter_noisy_segments(core_segments(parsed, appendix_idx))
    core_text = text_from_segments(core)
    full_text = parsed.full_text

    project_name = infer_project_name(row.get("file_name", source_path.name), core_text or full_text)
    sections = {name: collect_section(core, kws) for name, kws in SECTION_KEYWORDS.items()}
    risk_flags = infer_risk_flags(core_text or full_text)

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
            drop_flags = _as_clean_str_list(verify_data.get("drop_flags"), limit=10)
            if drop_flags:
                risk_flags = [f for f in risk_flags if f not in set(drop_flags)]

    # LLM fields override heuristics when present.
    for field in SECTION_KEYWORDS:
        llm_values = _as_clean_str_list(llm_data.get(field))
        if llm_values:
            sections[field] = llm_values

    llm_project_name = str(llm_data.get("project_name", "")).strip()
    if llm_project_name:
        project_name = llm_project_name

    llm_flags = _as_clean_str_list(llm_data.get("risk_flags"), limit=8)
    if llm_flags:
        risk_flags = unique_keep_order(risk_flags + llm_flags)

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

    rubric_coverage = [
        {"rubric_item": "User Evidence Strength", "covered": any(e["type"] == "user_evidence" for e in evidence_items)},
        {
            "rubric_item": "Business Model Consistency",
            "covered": any(e["type"] == "business_model_evidence" for e in evidence_items),
        },
        {"rubric_item": "Risk Control", "covered": any(e["type"] == "risk_evidence" for e in evidence_items)},
    ]

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
        "evidence": evidence_items,
        "rubric_coverage": rubric_coverage,
        "summary": summary_text[:500],
        "confidence": round(confidence, 2),
        "llm": {
            "enabled": use_llm,
            "provider": settings.llm_provider,
            "model": llm_model or settings.llm_fast_model or settings.llm_model,
            "used": bool(llm_data),
        },
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
    for row in included:
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
            continue
        try:
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


if __name__ == "__main__":
    main()