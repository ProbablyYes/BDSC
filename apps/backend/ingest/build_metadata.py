from __future__ import annotations

import csv
from pathlib import Path

from app.config import settings
from app.services.document_parser import ParsedDocument, parse_document
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
    # manual columns
    "education_level",
    "year",
    "award_level",
    "school",
    "notes",
    "updated_at",
]

MAX_PARSE_FILE_MB = 30.0


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


def build_row(path: Path, root: Path, existing: dict[str, dict]) -> dict:
    rel_path = normalize_rel_path(path, root)
    rel_obj = Path(rel_path)
    file_size_mb = path.stat().st_size / (1024 * 1024)
    parsed = None
    appendix_start = None

    if file_size_mb > MAX_PARSE_FILE_MB and path.suffix.lower() in {".pdf", ".pptx", ".docx"}:
        quality, note = (
            "C",
            f"文件过大({file_size_mb:.2f}MB)，已跳过自动解析，可人工补充摘要后入库。",
        )
        parsed = ParsedDocument(file_path=path, doc_type=path.suffix.lower().lstrip("."), segments=[])
    else:
        try:
            parsed = parse_document(path)
            quality, note = parse_quality(parsed)
            appendix_start = detect_appendix_start(parsed)
        except Exception as exc:  # noqa: BLE001
            quality, note = ("C", f"解析失败：{exc}")
            parsed = ParsedDocument(file_path=path, doc_type=path.suffix.lower().lstrip("."), segments=[])

    previous = existing.get(rel_path, {})
    include_in_kg_default = quality in {"A", "B"}
    include_in_kg = bool_from_csv(previous.get("include_in_kg", ""), default=include_in_kg_default)

    appendix_unit = ""
    if appendix_start is not None:
        matched = next((seg for seg in parsed.segments if seg.index == appendix_start), None)
        appendix_unit = matched.source_unit if matched else ""

    return {
        "file_path": rel_path,
        "file_name": path.name,
        "category": detect_category(rel_obj),
        "doc_type": parsed.doc_type,
        "file_size_mb": f"{file_size_mb:.2f}",
        "text_chars": str(parsed.text_chars),
        "segment_count": str(parsed.segment_count),
        "parse_quality": quality,
        "parse_note": note,
        "has_appendix_evidence": "true" if appendix_start is not None else "false",
        "appendix_start_index": "" if appendix_start is None else str(appendix_start),
        "appendix_start_unit": appendix_unit,
        "include_in_kg": "true" if include_in_kg else "false",
        "education_level": previous.get("education_level", "unknown"),
        "year": previous.get("year", ""),
        "award_level": previous.get("award_level", ""),
        "school": previous.get("school", ""),
        "notes": previous.get("notes", ""),
        "updated_at": now_iso(),
    }


def main() -> None:
    root = settings.teacher_examples_root
    metadata_path = root / "metadata.csv"
    existing = load_existing(metadata_path)
    files = discover_files(root)

    rows = [build_row(path, root, existing) for path in files]
    rows.sort(key=lambda x: (x["category"], x["file_path"]))

    with metadata_path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=METADATA_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    quality_count = {"A": 0, "B": 0, "C": 0}
    for row in rows:
        quality_count[row["parse_quality"]] = quality_count.get(row["parse_quality"], 0) + 1
    print("metadata generated:", metadata_path)
    print("files:", len(rows), "quality:", quality_count)


if __name__ == "__main__":
    main()
