"""
Document text extraction (PDF, DOCX, etc.)
"""
import logging
from pathlib import Path
from typing import Optional
from pypdf import PdfReader
from docx import Document as DocxDocument
from app.config import settings
from app.database import get_document_by_id

logger = logging.getLogger(__name__)


from app.database import get_db
import base64
from app.vision import describe_image

async def extract_pdf_text(document_id: str) -> dict:
    """Extract text from PDF file and query Vision Model for images. Updates database."""
    try:
        doc = get_document_by_id(document_id)
        if not doc:
            return {"status": "failed", "message": f"Document {document_id} not found"}
            
        file_path = doc.get("file_path")
        if not file_path or not Path(file_path).exists():
            return {"status": "failed", "message": f"File not found: {file_path}"}
            
        reader = PdfReader(str(file_path))
        page_count = len(reader.pages)
        
        text_parts = []
        for i, page in enumerate(reader.pages):
            # 1. Extract text
            text = page.extract_text()
            if text:
                text_parts.append(text)
                
            # 2. Extract images for VLM processing
            if len(page.images) > 0:
                logger.info(f"Found {len(page.images)} images on page {i+1}. Querying Vision model...")
                for image_file_object in page.images:
                    # image_file_object.data contains the raw bytes of the image
                    b64_image = base64.b64encode(image_file_object.data).decode('utf-8')
                    # Pause extraction to let VLM process it
                    description = await describe_image(b64_image)
                    if description:
                        text_parts.append(description)
        
        full_text = "\n\n".join(text_parts)
        logger.info(f"Extracted {len(full_text)} characters from {page_count} pages")
        
        # Update database
        with get_db() as conn:
            conn.execute(
                "UPDATE documents SET extracted_text = ?, extraction_status = 'extracted' WHERE id = ?",
                (full_text, document_id)
            )
            conn.commit()
        
        return {"status": "ok", "page_count": page_count}
    except Exception as e:
        logger.error(f"Error extracting PDF text: {e}")
        return {"status": "failed", "message": str(e)}


def extract_docx_text(file_path: Path) -> str:
    """Extract text from DOCX file."""
    try:
        doc = DocxDocument(str(file_path))
        text_parts = [paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip()]
        full_text = "\n\n".join(text_parts)
        logger.info(f"Extracted {len(full_text)} characters from DOCX")
        return full_text
    except Exception as e:
        logger.error(f"Error extracting DOCX text: {e}")
        raise


async def extract_text_from_document(document_id: str) -> str:
    """Extract text from a document based on its type."""
    doc = get_document_by_id(document_id)
    if not doc:
        raise ValueError(f"Document {document_id} not found")
    
    file_path = Path(settings.UPLOAD_DIR) / doc["filename"]
    if not file_path.exists():
        raise FileNotFoundError(f"Document file not found: {file_path}")
    
    mime_type = doc.get("mime_type", "")
    
    if "pdf" in mime_type or file_path.suffix.lower() == ".pdf":
        res = await extract_pdf_text(document_id)
        # return text is not easy here because extract_pdf_text updates the DB directly and returns a status dict
        # wait, the original code had: text, page_count = extract_pdf_text(file_path)
        # But wait, looking at lines 17-49, extract_pdf_text returns {"status": "ok", "page_count": page_count}
        # and updates the DB directly!
        # The old line 94 says: text, page_count = extract_pdf_text(file_path) 
        # This means the old code was broken or I misread it! 
        # Let's fix this properly.
        doc_updated = get_document_by_id(document_id)
        return doc_updated.get("extracted_text", "")
    elif "word" in mime_type or file_path.suffix.lower() in [".docx", ".doc"]:
        return extract_docx_text(file_path)
    elif file_path.suffix.lower() == ".txt":
        return file_path.read_text(encoding="utf-8")
    else:
        raise ValueError(f"Unsupported document type: {mime_type}")
