from __future__ import annotations
import argparse
import csv
from pathlib import Path
from app.config import settings
from app.services.document_parser import ParsedDocument
from app.services.hypergraph_document import HypergraphDocument
from ingest.common import (
    SUPPORTED_DOC_SUFFIXES,
    bool_from_csv,
    detect_appendix_start,
    detect_category,
    normalize_rel_path,
    now_iso,
    parse_quality,
)

METADATA_FIELDS = [
    "file_path",
    "file_name",
    "category",
    "doc_type",
    "file_size_mb",
    "text_chars",
    "segment_count",
    "parse_quality",
    "parse_note",
    "has_appendix_evidence",
    "appendix_start_index",
    "appendix_start_unit",
    "include_in_kg",
    # hypergraph metadata
    "document_id",
    "hypergraph_nodes",
    "hypergraph_edges",
    # manual columns
    "education_level",
    "year",
    "award_level",
    "school",
    "notes",
    "updated_at",
]
FAILURE_FIELDS = [
    "file_path",
    "category",
    "doc_type",
    "file_size_mb",
    "parse_quality",
    "parse_note",
    "suggestion",
]

MAX_PARSE_FILE_MB = settings.max_parse_file_mb


def load_existing(metadata_path: Path) -> dict[str, dict]:
    if not metadata_path.exists():
        return {}
    with metadata_path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        data: dict[str, dict] = {}
        for row in reader:
            key = (row.get("file_path") or "").strip()
            if key:
                data[key] = row
        return data


def discover_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in {"README.md", ".gitkeep", "metadata.csv"}:
            continue
        if path.name.startswith("._"):
            # macOS sidecar files
            continue
        if path.suffix.lower() not in SUPPORTED_DOC_SUFFIXES:
            continue
        out.append(path)
    return out


def build_row(
    path: Path,
    root: Path,
    existing: dict[str, dict],
    parse_pdf_deep: bool,
    max_parse_file_mb: float = MAX_PARSE_FILE_MB,
) -> dict:
    rel_path = normalize_rel_path(path, root)
    rel_obj = Path(rel_path)
    file_size_mb = path.stat().st_size / (1024 * 1024)
    parsed: ParsedDocument | None = None
    hypergraph_doc: HypergraphDocument | None = None
    appendix_start: int | None = None

    suffix = path.suffix.lower()

    # Use HypergraphDocument as the single source of truth for all
    # content-derived metadata. For large/fast PDF modes we only
    # limit pages,不再走 OCR 分支。
    pages_limit = 80
    if suffix == ".pdf":
        if not parse_pdf_deep:
            pages_limit = 20
        if file_size_mb > max_parse_file_mb:
            pages_limit = 100

    try:
        if suffix == ".pdf":
            hypergraph_doc = HypergraphDocument.from_file(path, max_pdf_pages=pages_limit)
        else:
            hypergraph_doc = HypergraphDocument.from_file(path)

        parsed = ParsedDocument(
            file_path=path,
            doc_type=hypergraph_doc.doc_type,
            segments=hypergraph_doc.get_segments(),
        )
        quality, note = parse_quality(parsed)
        appendix_start = detect_appendix_start(parsed)

        # Annotate notes for partial PDF parsing scenarios.
        if suffix == ".pdf" and file_size_mb > max_parse_file_mb:
            note = f"{note}（大文件，仅抽取前{pages_limit}页）"
        elif suffix == ".pdf" and not parse_pdf_deep:
            note = f"{note}（快速模式，仅抽取前{pages_limit}页）"
    except Exception as e:  # noqa: BLE001
        quality, note = ("F", f"解析失败: {str(e)}")
        parsed = ParsedDocument(file_path=path, doc_type=suffix.lstrip("."), segments=[])
        hypergraph_doc = None

    previous = existing.get(rel_path, {})
    # KG inclusion logic:
    # - A质量：必须进入（强制True）
    # - B质量：遵循历史记录（如无历史默认True）
    # - C/F质量：永不进入（强制False）
    if quality in {"C", "F"}:
        include_in_kg = False
    elif quality == "A":
        # A质量强制进入KG（最高优先级）
        include_in_kg = True
    elif quality == "B":
        # B质量遵循历史记录，如无历史则默认为True
        include_in_kg_default = True
        include_in_kg = bool_from_csv(previous.get("include_in_kg", ""), default=include_in_kg_default)
    else:
        # 其他未知质量等级不进入
        include_in_kg = False

    appendix_unit = ""
    if appendix_start is not None:
        matched = next((seg for seg in parsed.segments if seg.index == appendix_start), None)
        appendix_unit = matched.source_unit if matched else ""

    # Get hypergraph statistics if available
    hypergraph_stats = {}
    if hypergraph_doc:
        hypergraph_stats = hypergraph_doc.get_stats()

    return {
        "file_path": rel_path,
        "file_name": path.name,
        "category": detect_category(rel_obj),
        # Prefer doc_type from HyperNetX stats when available
        "doc_type": hypergraph_stats.get("doc_type", parsed.doc_type),
        "file_size_mb": f"{file_size_mb:.2f}",
        # Content-derived fields come from HyperNetX statistics when possible
        "text_chars": str(hypergraph_stats.get("text_chars", parsed.text_chars)),
        "segment_count": str(hypergraph_stats.get("segment_count", parsed.segment_count)),
        "parse_quality": quality,
        "parse_note": note,
        "has_appendix_evidence": "true" if appendix_start is not None else "false",
        "appendix_start_index": "" if appendix_start is None else str(appendix_start),
        "appendix_start_unit": appendix_unit,
        "include_in_kg": "true" if include_in_kg else "false",
        # Hypergraph metadata
        "document_id": hypergraph_stats.get("document_id", ""),
        # Prefer dedicated hypergraph_* counters when present
        "hypergraph_nodes": str(
            hypergraph_stats.get("hypergraph_nodes", hypergraph_stats.get("node_count", 0))
        ),
        "hypergraph_edges": str(
            hypergraph_stats.get("hypergraph_edges", hypergraph_stats.get("edge_count", 0))
        ),
        # Manual columns
        "education_level": previous.get("education_level", "unknown"),
        "year": previous.get("year", ""),
        "award_level": previous.get("award_level", ""),
        "school": previous.get("school", ""),
        "notes": previous.get("notes", ""),
        "updated_at": now_iso(),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build teacher examples metadata.csv")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use limited-page PDF parsing via HyperNetX for speed.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Optional limit for scanned files (0 means all).",
    )
    parser.add_argument(
        "--max-parse-mb",
        type=float,
        default=MAX_PARSE_FILE_MB,
        help="When file size exceeds this limit, only parse a subset of pages (still via HyperNetX).",
    )
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help="Only parse selected categories (folder names). Can be repeated.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    root = settings.teacher_examples_root
    metadata_path = root / "metadata.csv"
    existing = load_existing(metadata_path)
    files = discover_files(root)
    if args.max_files and args.max_files > 0:
        files = files[: args.max_files]
    if args.category:
        allowed = set(args.category)
        files = [p for p in files if detect_category(Path(normalize_rel_path(p, root))) in allowed]

    rows = [
        build_row(
            path,
            root,
            existing,
            parse_pdf_deep=not args.fast,
            max_parse_file_mb=args.max_parse_mb,
        )
        for path in files
    ]
    rows.sort(key=lambda x: (x["category"], x["file_path"]))

    with metadata_path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=METADATA_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    failed_rows = []
    for row in rows:
        if row["parse_quality"] != "C":
            continue
        if "扫描" in row["parse_note"] or "未提取" in row["parse_note"]:
            suggestion = "建议补充可编辑版源文件（pptx/docx），或提供文字版摘要以便重新抽取。"
        elif "过大" in row["parse_note"]:
            suggestion = "建议先做摘要版或拆分后再深度抽取。"
        elif "解析失败" in row["parse_note"]:
            suggestion = "建议检查文件是否损坏，或改用其他格式重导出。"
        else:
            suggestion = "建议人工补充关键摘要后再纳入图谱。"
        failed_rows.append(
            {
                "file_path": row["file_path"],
                "category": row["category"],
                "doc_type": row["doc_type"],
                "file_size_mb": row["file_size_mb"],
                "parse_quality": row["parse_quality"],
                "parse_note": row["parse_note"],
                "suggestion": suggestion,
            }
        )

    failure_path = root / "parse_failures.csv"
    with failure_path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=FAILURE_FIELDS)
        writer.writeheader()
        writer.writerows(failed_rows)

    quality_count = {"A": 0, "B": 0, "C": 0}
    for row in rows:
        quality_count[row["parse_quality"]] = quality_count.get(row["parse_quality"], 0) + 1
    print("metadata generated:", metadata_path)
    print("failure list generated:", failure_path)
    print("files:", len(rows), "quality:", quality_count, "failures:", len(failed_rows))


if __name__ == "__main__":
    main()