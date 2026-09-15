"""
OCR processing for scanned documents.
"""
import logging
from pathlib import Path
from typing import Optional
import pytesseract
from PIL import Image
from pdf2image import convert_from_path
from app.config import settings
from app.database import get_document_by_id, update_document_status

logger = logging.getLogger(__name__)

if settings.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD


def detect_likely_scanned_pdf(document_id: str) -> dict:
    """
    Heuristic to detect if a PDF is scanned.
    If extracted text is very short relative to page count, it's likely scanned.
    """
    doc = get_document_by_id(document_id)
    if not doc:
        return {"is_likely_scanned": False, "scanned_page_ratio": 0}
        
    text = doc.get("extracted_text", "")
    # Default to 1 if we don't have page_count in DB yet
    page_count = doc.get("page_count", 1) or 1
    
    if not text or len(text.strip()) < 100 * page_count:
        return {"is_likely_scanned": True, "scanned_page_ratio": 1.0}
    
    return {"is_likely_scanned": False, "scanned_page_ratio": 0.0}


def run_ocr_for_document(document_id: str) -> str:
    """Run OCR on a document and return extracted text."""
    doc = get_document_by_id(document_id)
    if not doc:
        raise ValueError(f"Document {document_id} not found")
    
    upload_path = Path(doc.get("file_path", ""))
    if not upload_path or not upload_path.exists():
        raise FileNotFoundError(f"Document file not found: {upload_path}")
    
    logger.info(f"Running OCR on {upload_path}")
    
    try:
        # Convert PDF to images
        images = convert_from_path(str(upload_path))
        
        # Run OCR on each page
        full_text = []
        for i, image in enumerate(images):
            logger.info(f"Processing page {i+1}/{len(images)}")
            text = pytesseract.image_to_string(image)
            full_text.append(text)
        
        result = "\n\n".join(full_text)
        
        # Save OCR result
        ocr_path = Path(settings.OCR_DIR) / f"{document_id}.txt"
        ocr_path.parent.mkdir(parents=True, exist_ok=True)
        ocr_path.write_text(result, encoding="utf-8")
        
        logger.info(f"OCR completed for {document_id}, extracted {len(result)} characters")
        return result
        
    except Exception as e:
        logger.error(f"OCR failed for {document_id}: {e}")
        raise
