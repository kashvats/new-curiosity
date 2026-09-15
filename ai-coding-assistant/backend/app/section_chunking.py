"""
backend/app/section_chunking.py

Phase 44: Chapter/section-aware chunking for PDFs.

Safety rules:
- Does NOT replace or delete basic chunks unless replace_existing=True is explicitly passed.
- Does NOT damage code blocks — code-like lines are never classified as headings.
- Is purely additive to the existing chunking pipeline.
- All section chunks carry heading_path, chapter_title, section_title, subsection_title metadata.
"""

import os
import re
import json
import uuid
import hashlib
import string
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.database import (
    get_document_by_id,
    update_document_chunking,
    insert_chunk,
    insert_document_section,
    get_document_sections_db,
    delete_document_sections,
    delete_document_chunks_by_strategy,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["section-chunking"])

# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------

class SectionChunkRequest(BaseModel):
    chunk_size_tokens: int = 900
    overlap_tokens: int = 120
    replace_existing: bool = False


# ---------------------------------------------------------------------------
# Heading detection heuristics
# ---------------------------------------------------------------------------

# Patterns for numbered/named headings (compiled once)
_CHAPTER_PATTERNS = [
    re.compile(r'^(chapter|ch\.?)\s+(\d+|[ivxlcdmIVXLCDM]+|one|two|three|four|five|six|seven|eight|nine|ten)', re.IGNORECASE),
    re.compile(r'^section\s+\d+(\.\d+)*', re.IGNORECASE),
    re.compile(r'^part\s+(\d+|[ivxlcdmI]+)', re.IGNORECASE),
]
_NUMBERED_HEADING = re.compile(r'^(\d+\.){1,3}\s+[A-Z]')          # "1. Intro", "1.2 Variables", "1.2.3 Types"
_NUMBERED_HEADING_LAX = re.compile(r'^(\d+\.){1,3}\d*\s+\S')      # "1.2.3 anything"
_MARKDOWN_HEADING = re.compile(r'^(#{1,4})\s+\S')                  # Markdown # / ## / ###
_ALL_CAPS_LINE = re.compile(r'^[A-Z][A-Z\s\-:]{4,60}$')           # SHORT ALL CAPS LINES

# Code-like patterns — lines matching these are NEVER classified as headings
_CODE_INDICATORS = re.compile(
    r'[{}()\[\];=<>|&]|^\s+(def |class |if |for |while |return |import |from )|'
    r'^(def |class |import |from |async |await |function |const |let |var |public |private |protected )',
    re.MULTILINE
)
_PAGE_NUMBER_PATTERN = re.compile(r'^\s*\d+\s*$')                  # bare page numbers
_SHORT_CODE_LINE = re.compile(r'[_`@#$%]')                         # probable code/noise

# Lines that appear >3 times across the whole doc are likely headers/footers
def _find_repeated_lines(pages: List[Dict[str, Any]], threshold: int = 3) -> set:
    counts: Dict[str, int] = {}
    for page in pages:
        for line in (page.get("text") or "").splitlines():
            stripped = line.strip()
            if stripped:
                counts[stripped] = counts.get(stripped, 0) + 1
    return {line for line, cnt in counts.items() if cnt >= threshold}


def _is_code_block_start(line: str) -> bool:
    """True if this line looks like the start of a code block."""
    stripped = line.strip()
    if stripped.startswith("```") or stripped.startswith("~~~"):
        return True
    return bool(_CODE_INDICATORS.search(stripped))


def _looks_like_heading(line: str, repeated_lines: set) -> Tuple[bool, int]:
    """
    Returns (is_heading, heading_level).
    Level 1 = chapter, 2 = section, 3 = subsection, 4 = sub-subsection.
    """
    stripped = line.strip()
    if not stripped:
        return False, 0
    if len(stripped) > 120:          # too long to be a heading
        return False, 0
    if stripped in repeated_lines:   # repeated header/footer
        return False, 0
    if _PAGE_NUMBER_PATTERN.match(stripped):
        return False, 0
    if _SHORT_CODE_LINE.search(stripped):
        return False, 0
    if _is_code_block_start(stripped):
        return False, 0

    # Markdown headings — level maps directly
    md = _MARKDOWN_HEADING.match(stripped)
    if md:
        depth = len(md.group(1))      # number of '#' chars
        return True, min(depth, 4)

    # Chapter/Part/Section keywords
    for pat in _CHAPTER_PATTERNS:
        if pat.match(stripped):
            return True, 1

    # Numbered headings: 1. → level 1, 1.2 → level 2, 1.2.3 → level 3
    nm = _NUMBERED_HEADING.match(stripped)
    if nm:
        dots = stripped.split()[0].count('.')
        return True, min(dots + 1, 4)

    nm2 = _NUMBERED_HEADING_LAX.match(stripped)
    if nm2:
        dots = stripped.split()[0].count('.')
        return True, min(dots + 1, 4)

    # Short ALL-CAPS lines (common in PDFs for chapter titles)
    if _ALL_CAPS_LINE.match(stripped):
        # Extra guard: must not be a common noise word cluster
        words = stripped.split()
        if 2 <= len(words) <= 10:
            return True, 1

    return False, 0


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------

def detect_headings_from_pages(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Scan all pages and return a flat list of detected headings.
    Each heading: {page_number, line_index, text, level}
    """
    repeated = _find_repeated_lines(pages)
    headings = []
    in_code_block = False

    for page in pages:
        page_num = page.get("page_number", 0)
        lines = (page.get("text") or "").splitlines()
        for li, line in enumerate(lines):
            stripped = line.strip()

            # Track code fences to suppress heading detection inside code
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue

            is_h, level = _looks_like_heading(line, repeated)
            if is_h:
                headings.append({
                    "page_number": page_num,
                    "line_index": li,
                    "text": stripped,
                    "level": level,
                })

    return headings


def build_section_tree(
    headings: List[Dict[str, Any]],
    pages: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Build a flat list of section objects from the heading list.
    Each section spans from its heading to the start of the next same-or-higher-level heading.
    Sections include text content from the pages they cover.
    """
    if not headings:
        # No headings found — treat the entire document as a single section
        all_text = "\n\n".join(
            (p.get("text") or "").strip()
            for p in pages
            if (p.get("text") or "").strip()
        )
        first_page = pages[0].get("page_number", 1) if pages else 1
        last_page = pages[-1].get("page_number", 1) if pages else 1
        return [{
            "title": "Document",
            "level": 1,
            "heading_path": "Document",
            "page_start": first_page,
            "page_end": last_page,
            "text": all_text,
            "parent_section_id": None,
        }]

    # Build page text lookup
    page_text: Dict[int, str] = {p["page_number"]: (p.get("text") or "") for p in pages}

    sections = []
    heading_stack: List[Dict[str, Any]] = []  # track ancestor headings by level

    for idx, h in enumerate(headings):
        # Compute heading_path from ancestor stack
        # Pop stack entries that are same level or deeper
        while heading_stack and heading_stack[-1]["level"] >= h["level"]:
            heading_stack.pop()

        path_parts = [a["text"] for a in heading_stack] + [h["text"]]
        heading_path = " > ".join(path_parts)

        # Determine parent_section_id
        parent_section_id = heading_stack[-1].get("section_id") if heading_stack else None

        section_id = str(uuid.uuid4())
        h["section_id"] = section_id  # store for child reference

        # Determine page range for this section (up to next heading)
        page_start = h["page_number"]
        if idx + 1 < len(headings):
            page_end = headings[idx + 1]["page_number"]
        else:
            page_end = pages[-1].get("page_number", page_start) if pages else page_start

        # Collect text for this section's page range
        section_text_parts = []
        for pn in range(page_start, page_end + 1):
            txt = page_text.get(pn, "")
            if txt.strip():
                section_text_parts.append(txt)
        section_text = "\n\n".join(section_text_parts)

        sections.append({
            "id": section_id,
            "title": h["text"],
            "level": h["level"],
            "heading_path": heading_path,
            "page_start": page_start,
            "page_end": page_end,
            "text": section_text,
            "parent_section_id": parent_section_id,
        })

        heading_stack.append(h)

    return sections


def _normalize_for_hash(text: str) -> str:
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = re.sub(r'\s+', '', text)
    return text


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def split_sections_into_chunks(
    sections: List[Dict[str, Any]],
    chunk_size_tokens: int = 900,
    overlap_tokens: int = 120,
) -> List[Dict[str, Any]]:
    """
    Split each section's text into token-limited chunks with overlap.
    Carries section metadata onto every chunk.
    """
    chunks: List[Dict[str, Any]] = []
    global_chunk_index = 0

    for section in sections:
        text = section.get("text", "")
        if not text.strip():
            continue

        # Determine title hierarchy from level
        level = section.get("level", 1)
        chapter_title = section["title"] if level == 1 else None
        section_title = section["title"] if level == 2 else None
        subsection_title = section["title"] if level >= 3 else None

        # If heading_path has ancestors, pull chapter/section from path components
        path_parts = (section.get("heading_path") or section["title"]).split(" > ")
        if len(path_parts) >= 1:
            chapter_title = path_parts[0]
        if len(path_parts) >= 2:
            section_title = path_parts[1]
        if len(path_parts) >= 3:
            subsection_title = path_parts[2]

        # Split section text into paragraphs
        paragraphs = [p.strip() for p in re.split(r'\n\n+', text) if p.strip()]

        current_texts: List[str] = []
        current_tokens = 0

        def flush_chunk():
            nonlocal global_chunk_index
            if not current_texts:
                return
            full_text = "\n\n".join(current_texts)
            chunks.append({
                "text": full_text,
                "page_start": section.get("page_start"),
                "page_end": section.get("page_end"),
                "chunk_index": global_chunk_index,
                "token_estimate": _estimate_tokens(full_text),
                "char_count": len(full_text),
                "chunking_strategy": "section",
                "chapter_title": chapter_title,
                "section_title": section_title,
                "subsection_title": subsection_title,
                "heading_path": section.get("heading_path"),
                "parent_section_id": section.get("parent_section_id"),
            })
            global_chunk_index += 1

        for para in paragraphs:
            para_tokens = _estimate_tokens(para)

            if current_tokens + para_tokens > chunk_size_tokens and current_texts:
                flush_chunk()
                # Overlap: keep last N tokens worth of text
                if overlap_tokens > 0 and current_texts:
                    kept = []
                    kept_tok = 0
                    for t in reversed(current_texts):
                        t_tok = _estimate_tokens(t)
                        if kept_tok + t_tok > overlap_tokens and kept:
                            break
                        kept.insert(0, t)
                        kept_tok += t_tok
                    current_texts = kept
                    current_tokens = kept_tok
                else:
                    current_texts = []
                    current_tokens = 0

            current_texts.append(para)
            current_tokens += para_tokens

        if current_texts:
            flush_chunk()

    return chunks


def chunk_document_by_sections(
    document_id: str,
    chunk_size_tokens: int = 900,
    overlap_tokens: int = 120,
    replace_existing: bool = False,
) -> dict:
    """
    Main entry point: detect headings, build sections, chunk by section,
    persist to DB. Returns summary dict.
    """
    doc = get_document_by_id(document_id)
    if not doc:
        return {"status": "failed", "message": "Document not found."}

    if doc.get("extraction_status") != "extracted":
        return {"status": "failed", "message": "Document must be extracted first."}

    extracted_path = doc.get("extracted_path")
    if not extracted_path or not os.path.exists(extracted_path):
        return {"status": "failed", "message": "Extracted JSON not found on disk."}

    try:
        with open(extracted_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"status": "failed", "message": f"Cannot read extracted JSON: {e}"}

    pages = data.get("pages", [])
    if not pages:
        return {"status": "failed", "message": "No pages found in extracted JSON."}

    warnings: List[str] = []

    # --- Optionally delete existing section chunks and sections ---
    if replace_existing:
        delete_document_sections(document_id)
        delete_document_chunks_by_strategy(document_id, "section")
        warnings.append("Previous section chunks deleted. Re-embedding and re-indexing required.")

    # --- Detect headings ---
    headings = detect_headings_from_pages(pages)
    if not headings:
        warnings.append("No headings detected. Document will be treated as a single section.")

    # --- Build section tree ---
    sections = build_section_tree(headings, pages)

    # --- Persist sections ---
    now = datetime.now(timezone.utc).isoformat()
    sections_created = 0
    for i, sec in enumerate(sections):
        sec.setdefault("id", str(uuid.uuid4()))
        row = {
            "id": sec["id"],
            "document_id": document_id,
            "section_index": i,
            "level": sec.get("level", 1),
            "title": sec["title"],
            "heading_path": sec.get("heading_path"),
            "page_start": sec.get("page_start"),
            "page_end": sec.get("page_end"),
            "text_preview": (sec.get("text") or "")[:300],
            "created_at": now,
        }
        if insert_document_section(row):
            sections_created += 1

    # --- Split into chunks ---
    raw_chunks = split_sections_into_chunks(sections, chunk_size_tokens, overlap_tokens)

    # --- Persist chunks ---
    chunks_created = 0
    skipped = 0
    for c in raw_chunks:
        norm_hash = hashlib.sha256(_normalize_for_hash(c["text"]).encode("utf-8")).hexdigest()
        chunk_data = {
            "id": str(uuid.uuid4()),
            "document_id": document_id,
            "chunk_index": c["chunk_index"],
            "text": c["text"],
            "normalized_text_hash": norm_hash,
            "page_start": c.get("page_start"),
            "page_end": c.get("page_end"),
            "token_estimate": c["token_estimate"],
            "char_count": c["char_count"],
            "status": "chunked",
            "created_at": now,
            # Section metadata
            "chunking_strategy": "section",
            "chapter_title": c.get("chapter_title"),
            "section_title": c.get("section_title"),
            "subsection_title": c.get("subsection_title"),
            "heading_path": c.get("heading_path"),
            "parent_section_id": c.get("parent_section_id"),
        }
        inserted = _insert_section_chunk(chunk_data)
        if inserted:
            chunks_created += 1
        else:
            skipped += 1

    # Update document chunking status if we created chunks
    if chunks_created > 0:
        update_document_chunking(document_id, {
            "chunking_status": "chunked",
            "chunk_count": chunks_created,
            "chunking_error": None,
            "chunked_at": now,
        })

    if skipped > 0:
        warnings.append(f"{skipped} duplicate chunks were skipped.")

    return {
        "status": "chunked",
        "document_id": document_id,
        "strategy": "section",
        "sections_found": sections_created,
        "chunks_created": chunks_created,
        "warnings": warnings,
    }


def _insert_section_chunk(chunk_data: dict) -> bool:
    """Insert a section chunk with all metadata columns."""
    from app.database import get_db_connection
    import sqlite3
    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO document_chunks (
                id, document_id, chunk_index, text, normalized_text_hash,
                page_start, page_end, token_estimate, char_count, status, created_at,
                chunking_strategy, chapter_title, section_title, subsection_title,
                heading_path, parent_section_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chunk_data["id"], chunk_data["document_id"], chunk_data["chunk_index"],
            chunk_data["text"], chunk_data["normalized_text_hash"],
            chunk_data.get("page_start"), chunk_data.get("page_end"),
            chunk_data["token_estimate"], chunk_data["char_count"],
            chunk_data["status"], chunk_data["created_at"],
            chunk_data.get("chunking_strategy", "section"),
            chunk_data.get("chapter_title"),
            chunk_data.get("section_title"),
            chunk_data.get("subsection_title"),
            chunk_data.get("heading_path"),
            chunk_data.get("parent_section_id"),
        ))
        conn.commit()
        return conn.total_changes > 0
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_document_sections(document_id: str) -> List[Dict[str, Any]]:
    """Public wrapper for DB helper."""
    return get_document_sections_db(document_id)


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@router.post("/{document_id}/chunk/sections")
async def section_chunk_document(document_id: str, req: SectionChunkRequest):
    """
    Run section-aware chunking. Detects headings and creates chunks with
    chapter/section/subsection metadata. Existing basic chunks are untouched
    unless replace_existing=True.
    """
    doc = get_document_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    result = chunk_document_by_sections(
        document_id,
        chunk_size_tokens=req.chunk_size_tokens,
        overlap_tokens=req.overlap_tokens,
        replace_existing=req.replace_existing,
    )

    if result["status"] == "failed":
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.get("/{document_id}/sections")
async def get_sections(document_id: str):
    """Return all detected sections for a document."""
    doc = get_document_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    sections = get_document_sections(document_id)
    return {
        "document_id": document_id,
        "sections": sections,
    }
