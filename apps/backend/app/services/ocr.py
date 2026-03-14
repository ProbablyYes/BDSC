from pathlib import Path
from typing import Optional
import sys
import os
# print(f"--- 正在使用的 Python 解释器: {sys.executable} ---")
# print(f"--- 模块搜索路径: {sys.path} ---")
# dependency required: pip install pytesseract Pillow
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Users\hmlouis\AppData\Local\Programs\Tesseract-OCR\tesseract.exe'
try:
    from pytesseract import image_to_string
    from PIL import Image
except ImportError:
    raise ImportError("Please install pytesseract and Pillow to use OCR functionality.")

def process_with_ocr(file_path: Path) -> Optional[str]:
    """
    Process a file with OCR and return the extracted text.

    Args:
        file_path (Path): The path to the file to process.

    Returns:
        Optional[str]: The extracted text, or None if OCR fails.
    """
    try:
        # Open the image file
        with Image.open(file_path) as img:
            # Perform OCR on the image
            extracted_text = image_to_string(img, lang="eng")
            return extracted_text.strip()
    except Exception as e:
        print(f"OCR processing failed for {file_path}: {e}")
        return None