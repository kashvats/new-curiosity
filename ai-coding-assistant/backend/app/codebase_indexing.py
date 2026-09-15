"""
Codebase indexing for project analysis.
"""
import logging
import uuid
from pathlib import Path
from typing import List, Dict, Any

from app.embeddings import get_embeddings
from app.qdrant_store import upsert_chunk_vector, ensure_collection
from app.config import settings

logger = logging.getLogger(__name__)


def scan_codebase_for_project(project_path: str, extensions: List[str] = None) -> Dict[str, Any]:
    """Scan a codebase and return file structure."""
    if extensions is None:
        extensions = [".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".cpp", ".c", ".h", ".md"]
    
    project = Path(project_path)
    if not project.exists():
        raise FileNotFoundError(f"Project path not found: {project_path}")
    
    files = []
    for ext in extensions:
        files.extend(project.rglob(f"*{ext}"))
    
    # Filter out common excluded directories
    excluded = {"node_modules", ".git", "__pycache__", "venv", ".venv", "dist", "build"}
    files = [f for f in files if not any(excl in f.parts for excl in excluded)]
    
    result = {
        "project_path": str(project),
        "file_count": len(files),
        "files": [str(f) for f in files]  # Full paths for internal use
    }
    
    logger.info(f"Scanned {result['file_count']} files in {project_path}")
    return result


def chunk_file_content(file_path: str, max_tokens: int = 500) -> List[Dict[str, str]]:
    """Simple line-based chunker for source code."""
    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not read {file_path}: {e}")
        return []

    lines = content.split("\n")
    chunks = []
    current_chunk = []
    current_length = 0
    
    # Very rough token estimation (1 token ~= 4 chars)
    max_chars = max_tokens * 4
    
    for i, line in enumerate(lines):
        current_chunk.append(line)
        current_length += len(line)
        
        if current_length >= max_chars or i == len(lines) - 1:
            chunk_text = "\n".join(current_chunk)
            chunks.append({
                "text": chunk_text,
                "start_line": max(1, i - len(current_chunk) + 2),
                "end_line": i + 1
            })
            # Overlap: keep the last 5 lines for context in the next chunk
            current_chunk = current_chunk[-5:]
            current_length = sum(len(l) for l in current_chunk)
            
    return chunks


def index_codebase(project_path: str) -> Dict[str, Any]:
    """Extract, chunk, embed, and save the entire codebase to Qdrant."""
    code_collection = getattr(settings, "QDRANT_CODE_COLLECTION", "codebase")
    ensure_collection(code_collection)
    
    scan_result = scan_codebase_for_project(project_path)
    files = scan_result["files"]
    
    total_chunks = 0
    for fpath in files:
        chunks = chunk_file_content(fpath)
        if not chunks:
            continue
            
        texts = [c["text"] for c in chunks]
        embeddings = get_embeddings(texts)
        
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            chunk_id = str(uuid.uuid4())
            metadata = {
                "file_path": str(Path(fpath).relative_to(project_path)),
                "start_line": chunk["start_line"],
                "end_line": chunk["end_line"],
                "content": chunk["text"],
                "type": "code"
            }
            upsert_chunk_vector(chunk_id, emb, metadata, collection_name=code_collection)
            total_chunks += 1
            
    logger.info(f"Successfully indexed {len(files)} files into {total_chunks} chunks.")
    
    return {
        "status": "ok",
        "files_indexed": len(files),
        "total_chunks": total_chunks
    }


# ---------------------------------------------------------------------------
# Symbol Extractor — zero LLM, pure static analysis
# ---------------------------------------------------------------------------
import ast as _ast
import re as _re


def extract_symbols(file_path: str) -> Dict[str, Any]:
    """
    Extract function names, class names, and top-level imports from a source file.
    Uses ast.parse() for .py files and regex for .js/.ts/.jsx/.tsx files.
    Returns empty dicts on any failure — never raises.
    """
    result: Dict[str, Any] = {
        "functions": [],
        "classes": [],
        "imports": [],
        "error": None
    }
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return result

    try:
        content = p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        result["error"] = str(e)
        return result

    suffix = p.suffix.lower()

    # ── Python ────────────────────────────────────────────────────────────────
    if suffix == ".py":
        try:
            tree = _ast.parse(content)
            for node in _ast.walk(tree):
                if isinstance(node, _ast.FunctionDef) or isinstance(node, _ast.AsyncFunctionDef):
                    # Only top-level and class-level functions (depth 1-2)
                    result["functions"].append(node.name)
                elif isinstance(node, _ast.ClassDef):
                    result["classes"].append(node.name)
                elif isinstance(node, _ast.Import):
                    for alias in node.names:
                        result["imports"].append(alias.name)
                elif isinstance(node, _ast.ImportFrom):
                    if node.module:
                        result["imports"].append(node.module)
        except SyntaxError as e:
            result["error"] = f"SyntaxError: {e}"

    # ── JavaScript / TypeScript ───────────────────────────────────────────────
    elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
        # Function declarations: function foo() | const foo = () => | const foo = async () =>
        fn_patterns = [
            r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(",
            r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(",
            r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\w*\s*=>",
        ]
        for pat in fn_patterns:
            result["functions"].extend(_re.findall(pat, content))

        # Class declarations
        result["classes"].extend(_re.findall(r"class\s+(\w+)", content))

        # Imports: import X from 'y' | import { X } from 'y'
        result["imports"].extend(_re.findall(r"from\s+['\"]([^'\"]+)['\"]", content))
        result["imports"].extend(_re.findall(r"require\(['\"]([^'\"]+)['\"]\)", content))

    # Deduplicate
    result["functions"] = sorted(set(result["functions"]))
    result["classes"] = sorted(set(result["classes"]))
    result["imports"] = sorted(set(result["imports"]))

    return result


def build_project_symbol_index(project_path: str) -> Dict[str, Any]:
    """
    Scan the entire project and return a structured symbol index:
    { "relative/path/to/file.py": { "functions": [...], "classes": [...], "imports": [...] } }

    Uses scan_codebase_for_project for file discovery (reusing existing logic).
    Skips files > 100KB to avoid memory issues.
    Returns the index dict and also a compact summary string for LLM injection.
    """
    scan_result = scan_codebase_for_project(project_path)
    files = scan_result.get("files", [])
    base = Path(project_path).resolve()

    index: Dict[str, Any] = {}
    MAX_FILE_SIZE = 100_000  # 100KB

    for fpath in files:
        try:
            fp = Path(fpath)
            if fp.stat().st_size > MAX_FILE_SIZE:
                continue
            rel = str(fp.relative_to(base))
            symbols = extract_symbols(fpath)
            # Only store files that actually have something useful
            if symbols["functions"] or symbols["classes"]:
                index[rel] = {
                    "functions": symbols["functions"],
                    "classes": symbols["classes"],
                    "imports": symbols["imports"][:15],  # cap imports to avoid bloat
                }
        except Exception:
            continue

    # Build a compact summary string for LLM prompt injection
    summary_lines = []
    for rel_path, syms in sorted(index.items()):
        fn_str = ", ".join(syms["functions"][:10]) or "none"
        cls_str = ", ".join(syms["classes"]) or "none"
        summary_lines.append(f"  {rel_path}: classes=[{cls_str}] functions=[{fn_str}]")

    summary = "\n".join(summary_lines) if summary_lines else "  (no symbols found)"

    logger.info(f"Symbol index built: {len(index)} files with symbols out of {len(files)} total")

    return {
        "index": index,
        "summary": summary,
        "file_count": len(index)
    }

