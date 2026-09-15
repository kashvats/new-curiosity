"""
backend/app/job_handlers.py

Production-grade background job handlers for the fully automated document
ingestion pipeline.

Pipeline stages (triggered automatically on upload):
  document.uploaded
    └─> document.ingest  (extract text via pypdf)
          └─> document.post_extract  (detect if scanned -> route to OCR or chunk)
                ├─> document.ocr  (if scanned + OCR enabled)
                │     └─> document.chunk
                └─> document.chunk  (if text-based)
                      └─> document.embed
                            └─> document.index
                                  └─> document.ready  (final)

Each handler:
  - Checks idempotency (skips if the stage is already done)
  - Raises exceptions on real failures (job_service will retry up to 3x)
  - Dispatches the next event only on success
  - document.failed is dispatched by job_service after exhausting retries
"""

import logging
import asyncio
from app.job_service import register_job_handler
from app.ocr import run_ocr_for_document, detect_likely_scanned_pdf
from app.extraction import extract_pdf_text
from app.chunking import process_document_chunks
from app.codebase_indexing import scan_codebase_for_project

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# STAGE 1: Ingest (extract text from PDF with pypdf)
# ---------------------------------------------------------------------------

@register_job_handler("document.ingest")
async def handle_ingest_job(job_id: str, payload: dict):
    """
    Extract raw text from a PDF using pypdf.
    Idempotent: skips if extraction_status is already 'extracted'.
    """
    document_id = payload.get("document_id")
    if not document_id:
        raise ValueError("Missing document_id in payload")

    from app.database import get_document_by_id
    doc = get_document_by_id(document_id)
    if not doc:
        raise RuntimeError(f"Document {document_id} not found in database")

    # Idempotency: already extracted
    if doc.get("extraction_status") == "extracted":
        logger.info(f"[{document_id}] Extraction already done — skipping ingest, routing to post_extract")
        from app.events import dispatch
        await dispatch("document.post_extract", {"document_id": document_id})
        return {"status": "skipped_idempotent"}

    logger.info(f"[{document_id}] Stage 1: Extracting text and diagrams (PyMuPDF + VLM)")
    res = await extract_pdf_text(document_id)

    if res.get("status") == "failed":
        raise RuntimeError(f"Text extraction failed: {res.get('message')}")

    from app.events import dispatch
    await dispatch("document.post_extract", {"document_id": document_id})
    return {"status": "completed", "page_count": res.get("page_count")}


# ---------------------------------------------------------------------------
# STAGE 2: Post-Extract — detect scanned vs text-based and route
# ---------------------------------------------------------------------------

@register_job_handler("document.post_extract")
async def handle_post_extract_job(job_id: str, payload: dict):
    """
    After extraction, determine if the PDF needs OCR.
    Routes:
      - text-based  -> dispatch document.chunk
      - scanned     -> dispatch document.ocr (then document.chunk follows)
    Idempotent: checks chunking_status before routing.
    """
    document_id = payload.get("document_id")
    if not document_id:
        raise ValueError("Missing document_id in payload")

    from app.database import get_document_by_id
    doc = get_document_by_id(document_id)
    if not doc:
        raise RuntimeError(f"Document {document_id} not found")

    # If already chunked, skip all of this
    if doc.get("chunking_status") == "chunked":
        logger.info(f"[{document_id}] Already chunked — routing directly to embed")
        from app.events import dispatch
        await dispatch("document.embed", {"document_id": document_id})
        return {"status": "skipped_idempotent"}

    from app.events import dispatch
    detection = await asyncio.to_thread(detect_likely_scanned_pdf, document_id)
    is_scanned = detection.get("is_likely_scanned", False)
    scanned_ratio = detection.get("scanned_page_ratio", 0)

    logger.info(f"[{document_id}] PDF quality: scanned_ratio={scanned_ratio}, is_scanned={is_scanned}")

    if is_scanned:
        logger.info(f"[{document_id}] Scanned PDF detected — routing to OCR stage")
        await dispatch("document.ocr", {"document_id": document_id})
        return {"status": "routed_to_ocr", "scanned_ratio": scanned_ratio}
    else:
        logger.info(f"[{document_id}] Text-based PDF — routing directly to chunking")
        await dispatch("document.chunk", {"document_id": document_id})
        return {"status": "routed_to_chunk", "scanned_ratio": scanned_ratio}


# ---------------------------------------------------------------------------
# STAGE 3a: OCR (only for scanned PDFs)
# ---------------------------------------------------------------------------

@register_job_handler("document.ocr")
async def handle_ocr_job(job_id: str, payload: dict):
    """
    Run Tesseract OCR on scanned PDFs.
    Idempotent: if OCR is disabled, falls through to chunking anyway using whatever text was extracted.
    """
    document_id = payload.get("document_id")
    if not document_id:
        raise ValueError("Missing document_id in payload")

    from app.config import settings
    from app.events import dispatch

    if not settings.ocr_enabled:
        logger.warning(f"[{document_id}] OCR is disabled (OCR_ENABLED=false) — proceeding with pypdf text as-is")
        await dispatch("document.chunk", {"document_id": document_id})
        return {"status": "skipped_ocr_disabled"}

    logger.info(f"[{document_id}] Stage 3a: Running OCR")
    res = await asyncio.to_thread(run_ocr_for_document, document_id)

    if res.get("status") not in ("ok", "merged", "not_needed", "skipped_not_scanned"):
        # Log a warning but don't halt the pipeline. We can fallback to the initially extracted text.
        logger.warning(f"[{document_id}] OCR failed (possibly missing Poppler/Tesseract): {res.get('message', 'unknown error')}. Falling back to default extraction.")
        res["status"] = "skipped_ocr_failed"

    await dispatch("document.chunk", {"document_id": document_id})
    return {"status": "completed", "ocr_status": res.get("status")}


# ---------------------------------------------------------------------------
# STAGE 3b: Chunking
# ---------------------------------------------------------------------------

@register_job_handler("document.chunk")
async def handle_chunk_job(job_id: str, payload: dict):
    """
    Split extracted text into overlapping chunks.
    Idempotent: skips if already chunked.
    """
    document_id = payload.get("document_id")
    if not document_id:
        raise ValueError("Missing document_id in payload")

    from app.database import get_document_by_id
    doc = get_document_by_id(document_id)
    if not doc:
        raise RuntimeError(f"Document {document_id} not found")

    if doc.get("chunking_status") == "chunked":
        logger.info(f"[{document_id}] Already chunked — skipping to embed")
        from app.events import dispatch
        await dispatch("document.embed", {"document_id": document_id})
        return {"status": "skipped_idempotent"}

    logger.info(f"[{document_id}] Stage 3b: Chunking document")
    res = await asyncio.to_thread(process_document_chunks, document_id)

    if res.get("status") == "failed":
        raise RuntimeError(f"Chunking failed: {res.get('message')}")

    from app.events import dispatch
    await dispatch("document.embed", {"document_id": document_id})
    return {"status": "completed", "chunk_count": res.get("chunk_count")}


# ---------------------------------------------------------------------------
# STAGE 4: Embedding
# ---------------------------------------------------------------------------

@register_job_handler("document.embed")
async def handle_embed_job(job_id: str, payload: dict):
    """
    Generate vector embeddings for all chunks via SentenceTransformers.
    Note: search.py handles embedding on the fly right before indexing,
    so this stage just forwards to document.index.
    """
    document_id = payload.get("document_id")
    if not document_id:
        raise ValueError("Missing document_id in payload")

    from app.events import dispatch
    logger.info(f"[{document_id}] Stage 4: Forwarding to Qdrant indexing stage (embeddings generated on the fly)")
    await dispatch("document.index", {"document_id": document_id})
    return {"status": "forwarded_to_index"}


# ---------------------------------------------------------------------------
# STAGE 5: Qdrant Indexing
# ---------------------------------------------------------------------------

@register_job_handler("document.index")
async def handle_index_job(job_id: str, payload: dict):
    """
    Upsert all chunk vectors into Qdrant.
    Idempotent: skips chunks already indexed.
    """
    document_id = payload.get("document_id")
    if not document_id:
        raise ValueError("Missing document_id in payload")

    from app.database import get_document_by_id
    doc = get_document_by_id(document_id)
    if not doc:
        raise RuntimeError(f"Document {document_id} not found")

    if doc.get("qdrant_status") == "indexed":
        logger.info(f"[{document_id}] Already indexed in Qdrant — dispatching ready")
        from app.events import dispatch
        await dispatch("document.ready", {"document_id": document_id})
        return {"status": "skipped_idempotent"}

    logger.info(f"[{document_id}] Stage 5: Indexing into Qdrant")
    from app.search import index_document_chunks
    res = await asyncio.to_thread(index_document_chunks, document_id)

    if res.get("status") == "failed":
        raise RuntimeError(f"Qdrant indexing failed: {res.get('message')}")

    from app.events import dispatch
    await dispatch("document.ready", {
        "document_id": document_id,
        "indexed_chunks": res.get("indexed_chunks"),
        "collection": res.get("collection")
    })
    return {"status": "completed", "indexed_chunks": res.get("indexed_chunks")}


# ---------------------------------------------------------------------------
# STAGE 6: Ready (terminal success state — log and mark document)
# ---------------------------------------------------------------------------

@register_job_handler("document.ready")
async def handle_ready_job(job_id: str, payload: dict):
    """
    Terminal success state. Marks the document as fully processed.
    """
    document_id = payload.get("document_id")
    if not document_id:
        raise ValueError("Missing document_id in payload")

    logger.info(f"[{document_id}] ✅ Pipeline complete — document is READY in Qdrant")
    return {"status": "ready"}


# ---------------------------------------------------------------------------
# FAILURE HANDLER (dispatched by job_service after 3 retries)
# ---------------------------------------------------------------------------

@register_job_handler("document.failed")
async def handle_failed_job(job_id: str, payload: dict):
    """
    Terminal failure state. Logs the failure for visibility.
    """
    document_id = payload.get("document_id")
    stage = payload.get("stage", "unknown")
    error = payload.get("error", "unknown error")
    logger.error(f"[{document_id}] ❌ Pipeline FAILED at stage '{stage}': {error}")
    return {"status": "failed", "document_id": document_id, "stage": stage}


# ---------------------------------------------------------------------------
# CODEBASE & AUXILIARY JOBS (unchanged)
# ---------------------------------------------------------------------------

@register_job_handler("codebase.index")
async def handle_codebase_index_job(job_id: str, payload: dict):
    project_id = payload.get("project_id", "default")
    logger.info(f"Running automated codebase indexing for project {project_id}")
    res = await asyncio.to_thread(scan_codebase_for_project, project_id)
    return {"status": "completed", "result": res}


@register_job_handler("knowledge.gaps")
async def handle_knowledge_gaps_job(job_id: str, payload: dict):
    logger.info("Running automated knowledge gap detection")
    from app.knowledge_gap_detection import create_knowledge_gap_report
    res = await asyncio.to_thread(create_knowledge_gap_report, scope="all")
    return {"status": "completed", "report_id": res.get("report_id")}


@register_job_handler("knowledge.rag_eval")
async def handle_rag_eval_job(job_id: str, payload: dict):
    logger.info("Running automated RAG evaluation")
    from app.database import get_all_rag_eval_sets
    from app.rag_eval import run_eval_set
    from app.models import EvalRunRequest
    sets = get_all_rag_eval_sets()
    if not sets:
        return {"status": "skipped", "message": "No eval sets found"}
    set_id = sets[0]["id"]
    res = await run_eval_set(set_id, EvalRunRequest())
    return {"status": "completed", "run_id": res.get("run_id")}


@register_job_handler("codebase.regression")
async def handle_regression_job(job_id: str, payload: dict):
    logger.info("Running automated regression detection")
    from app.regression_detection import compare_debug_reports, create_regression_report
    from app.config import settings
    from pathlib import Path
    import glob
    import os
    reports_dir = Path(settings.workspace_root) / "debug_reports"
    if not reports_dir.exists():
        return {"status": "skipped", "message": "No debug reports found"}
    json_files = glob.glob(str(reports_dir / "*.json"))
    json_files.sort(key=os.path.getmtime, reverse=True)
    if len(json_files) < 2:
        return {"status": "skipped", "message": "Not enough debug reports to compare"}
    current = json_files[0]
    baseline = json_files[1]
    regs, imps, unchs = compare_debug_reports(baseline, current)
    report_id = create_regression_report(
        baseline_debug=baseline, current_debug=current,
        baseline_test=None, current_test=None, restore_point_id=None,
        regressions=regs, improvements=imps, unchanged=unchs
    )
    return {"status": "completed", "report_id": report_id}


@register_job_handler("workspace.backup")
async def handle_backup_job(job_id: str, payload: dict):
    logger.info("Running automated workspace backup")
    from app.apply_changes import create_project_snapshot
    res = create_project_snapshot("auto-backup")
    return {"status": "completed", "snapshot_id": res.get("snapshot_id")}


# Wire up pipeline events to job queues
from app.events import subscribe, enqueue_job_on_event

subscribe("document.uploaded", enqueue_job_on_event("document.ingest"))
subscribe("document.post_extract", enqueue_job_on_event("document.post_extract"))
subscribe("document.ocr", enqueue_job_on_event("document.ocr"))
subscribe("document.chunk", enqueue_job_on_event("document.chunk"))
subscribe("document.embed", enqueue_job_on_event("document.embed"))
subscribe("document.index", enqueue_job_on_event("document.index"))
subscribe("document.ready", enqueue_job_on_event("document.ready"))
subscribe("document.failed", enqueue_job_on_event("document.failed"))
