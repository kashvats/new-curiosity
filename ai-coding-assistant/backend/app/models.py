"""
Pydantic models for API requests and responses.
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime


# Document Models
class DocumentUploadResponse(BaseModel):
    id: str
    filename: str
    file_hash: str
    status: str
    created_at: str


class DocumentResponse(BaseModel):
    id: str
    filename: str
    status: str
    qdrant_status: str
    chunk_count: int
    indexed_chunk_count: int
    created_at: str
    error: Optional[str] = None


# Job Models
class JobModel(BaseModel):
    id: str
    type: str
    status: str
    payload: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class JobResponse(BaseModel):
    job_id: str
    status: str


# Search Models
class SearchRequest(BaseModel):
    query: str
    knowledge_base_id: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=100)
    score_threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class SearchResult(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    content: str
    score: float
    chunk_index: int


class SearchResponse(BaseModel):
    results: List[SearchResult]
    query: str
    total_results: int


# Web Search Models
class WebSearchRequest(BaseModel):
    query: str
    num_results: int = Field(default=5, ge=1, le=20)


class WebSearchResult(BaseModel):
    title: str
    url: str
    snippet: str


class WebSearchResponse(BaseModel):
    results: List[WebSearchResult]
    query: str


# Browser Control Models
class BrowserOpenRequest(BaseModel):
    url: str


class BrowserTextRequest(BaseModel):
    url: str


class BrowserScreenshotRequest(BaseModel):
    url: str
    full_page: bool = False


class BrowserClickRequest(BaseModel):
    url: str
    selector: str


class BrowserTypeRequest(BaseModel):
    url: str
    selector: str
    text: str


class BrowserResponse(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None


# Test Models
class TestPlanRequest(BaseModel):
    project_id: str
    description: str
    file_paths: Optional[List[str]] = None


class TestPlanResponse(BaseModel):
    plan_id: str
    status: str
    test_cases: List[Dict[str, Any]]


class TestGenerateRequest(BaseModel):
    plan_id: str
    test_case_id: str


class TestGenerateResponse(BaseModel):
    test_id: str
    file_path: str
    code: str


class TestExecuteRequest(BaseModel):
    test_ids: List[str]
    project_id: str


class TestRunRequest(BaseModel):
    command_id: str
    confirm: bool = True


class TestExecuteResponse(BaseModel):
    run_id: str
    status: str
    results: List[Dict[str, Any]]


# Settings Models
class SettingsExportResponse(BaseModel):
    settings: Dict[str, Any]
    exported_at: str


class SettingsImportRequest(BaseModel):
    settings: Dict[str, Any]


class SettingsImportPreviewRequest(BaseModel):
    settings: Dict[str, Any]


# Knowledge Base Models
class KnowledgeBaseCreate(BaseModel):
    name: str
    description: Optional[str] = None


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    document_count: int
    created_at: str


# Run History Models
class RunHistoryCreate(BaseModel):
    run_type: str
    request_json: Optional[str] = None


class RunHistoryUpdate(BaseModel):
    status: str
    response_json: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None


class RunHistoryResponse(BaseModel):
    id: str
    run_type: str
    status: str
    duration_ms: Optional[int]
    created_at: str
    completed_at: Optional[str]
    error: Optional[str] = None

# Agent/RAG evaluation models
class EvalRunRequest(BaseModel):
    limit: int = Field(default=5, ge=1, le=50)
    score_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    knowledge_base_id: Optional[str] = None
