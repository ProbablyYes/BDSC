from dataclasses import dataclass
import logging
from pathlib import Path

from docx import Document
from pypdf import PdfReader
from pptx import Presentation


SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".pptx", ".ppt"}
logging.getLogger("pypdf").setLevel(logging.ERROR)


@dataclass
class TextSegment:
    index: int
    source_unit: str
    text: str


@dataclass
class ParsedDocument:
    file_path: Path
    doc_type: str
    segments: list[TextSegment]

    @property
    def full_text(self) -> str:
        return "\n".join(seg.text for seg in self.segments if seg.text.strip())

    @property
    def text_chars(self) -> int:
        return len(self.full_text)

    @property
    def segment_count(self) -> int:
        return len(self.segments)


def parse_document(file_path: Path, max_pdf_pages: int = 80) -> ParsedDocument:
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return ParsedDocument(file_path=file_path, doc_type=suffix.lstrip("."), segments=[])

    if suffix in {".txt", ".md"}:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        segments = [
            TextSegment(index=i, source_unit=f"line_{i+1}", text=line.strip())
            for i, line in enumerate(content.splitlines())
            if line.strip()
        ]
        return ParsedDocument(file_path=file_path, doc_type=suffix.lstrip("."), segments=segments)

    if suffix == ".pdf":
        reader = PdfReader(str(file_path), strict=False)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001
                return ParsedDocument(file_path=file_path, doc_type="pdf", segments=[])
        segments: list[TextSegment] = []
        for i, page in enumerate(reader.pages[:max_pdf_pages]):
            page_text = (page.extract_text() or "").strip()
            if page_text:
                segments.append(TextSegment(index=i, source_unit=f"page_{i+1}", text=page_text))
        return ParsedDocument(file_path=file_path, doc_type="pdf", segments=segments)

    if suffix == ".docx":
        doc = Document(str(file_path))
        segments = [
            TextSegment(index=i, source_unit=f"paragraph_{i+1}", text=p.text.strip())
            for i, p in enumerate(doc.paragraphs)
            if p.text.strip()
        ]
        return ParsedDocument(file_path=file_path, doc_type="docx", segments=segments)

    if suffix == ".pptx":
        prs = Presentation(str(file_path))
        segments: list[TextSegment] = []
        for i, slide in enumerate(prs.slides):
            slide_lines: list[str] = []
            for shape in slide.shapes:
                text = getattr(shape, "text", "")
                if text and text.strip():
                    slide_lines.append(text.strip())
            if slide_lines:
                segments.append(
                    TextSegment(
                        index=i,
                        source_unit=f"slide_{i+1}",
                        text="\n".join(slide_lines),
                    )
                )
        return ParsedDocument(file_path=file_path, doc_type="pptx", segments=segments)

    if suffix == ".ppt":
        try:
            # Attempt to parse .ppt (97-2003) files with python-pptx
            prs = Presentation(str(file_path))
            segments: list[TextSegment] = []
            for i, slide in enumerate(prs.slides):
                slide_lines: list[str] = []
                for shape in slide.shapes:
                    text = getattr(shape, "text", "")
                    if text and text.strip():
                        slide_lines.append(text.strip())
                if slide_lines:
                    segments.append(
                        TextSegment(
                            index=i,
                            source_unit=f"slide_{i+1}",
                            text="\n".join(slide_lines),
                        )
                    )
            return ParsedDocument(file_path=file_path, doc_type="ppt", segments=segments)
        except Exception:  # noqa: BLE001
            # If parsing fails (format not supported), return empty segments
            return ParsedDocument(file_path=file_path, doc_type="ppt", segments=[])

    return ParsedDocument(file_path=file_path, doc_type=suffix.lstrip("."), segments=[])


def extract_text(file_path: Path) -> str:
    return parse_document(file_path).full_text
