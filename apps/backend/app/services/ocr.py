"""OCR service for processing document images and extracting text."""

from pathlib import Path

from app.services.document_parser import ParsedDocument, TextSegment
from pptx import Presentation
from pypdf import PdfReader


def process_with_ocr(file_path: Path) -> ParsedDocument:
    """
    Process a file using OCR/advanced text extraction to extract text and structure.
    
    For PPTX files, performs comprehensive content extraction from all slides.
    For PDF files, attempts to extract all text including from images where possible.
    
    Args:
        file_path: Path to the document file to process
        
    Returns:
        ParsedDocument with extracted content
    """
    doc_type = file_path.suffix.lstrip(".").lower()
    
    if doc_type in {"pptx", "ppt"}:
        return _process_pptx_for_ocr(file_path, doc_type)
    elif doc_type == "pdf":
        return _process_pdf_for_ocr(file_path)
    else:
        # For unsupported formats, return empty document
        return ParsedDocument(
            file_path=file_path,
            doc_type=doc_type,
            segments=[],
        )


def _process_pptx_for_ocr(file_path: Path, doc_type: str) -> ParsedDocument:
    """
    Extract comprehensive content from PPTX files.
    Includes text, shapes, tables, and speaker notes.
    """
    segments: list[TextSegment] = []
    try:
        prs = Presentation(str(file_path))
        for slide_idx, slide in enumerate(prs.slides):
            slide_content = []
            
            # Extract text from shapes
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    slide_content.append(shape.text.strip())
                    
                # Extract text from table cells if present
                if hasattr(shape, "table"):
                    table = shape.table
                    for row in table.rows:
                        for cell in row.cells:
                            if cell.text.strip():
                                slide_content.append(cell.text.strip())
            
            # Extract speaker notes
            if slide.has_notes_slide:
                notes_text = slide.notes_slide.notes_text_frame.text.strip()
                if notes_text:
                    slide_content.append(f"[备注] {notes_text}")
            
            # Create segment if content found
            if slide_content:
                segments.append(
                    TextSegment(
                        index=slide_idx,
                        source_unit=f"slide_{slide_idx+1}",
                        text="\n".join(slide_content),
                    )
                )
    except Exception:
        # If parsing fails, return empty segments
        pass
    
    return ParsedDocument(
        file_path=file_path,
        doc_type=doc_type,
        segments=segments,
    )


def _process_pdf_for_ocr(file_path: Path) -> ParsedDocument:
    """
    Extract comprehensive content from PDF files.
    Attempts to extract all available text.
    """
    segments: list[TextSegment] = []
    try:
        reader = PdfReader(str(file_path), strict=False)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return ParsedDocument(
                    file_path=file_path,
                    doc_type="pdf",
                    segments=[],
                )
        
        # Extract text from all pages
        for page_idx, page in enumerate(reader.pages):
            page_text = (page.extract_text() or "").strip()
            if page_text:
                segments.append(
                    TextSegment(
                        index=page_idx,
                        source_unit=f"page_{page_idx+1}",
                        text=page_text,
                    )
                )
    except Exception:
        pass
    
    return ParsedDocument(
        file_path=file_path,
        doc_type="pdf",
        segments=segments,
    )
