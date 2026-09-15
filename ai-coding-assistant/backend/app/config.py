"""
Configuration management for the AI Coding Assistant backend.
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # Application
    APP_NAME: str = "AI Coding Assistant"
    DEBUG: bool = False
    WORKSPACE_ROOT: str = os.getenv("WORKSPACE_ROOT", "/app")
    
    # API Keys
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    
    # Database
    DATABASE_PATH: str = "../data/app.db"
    
    # Storage
    UPLOAD_DIR: str = "../data/uploads"
    EXTRACTED_DIR: str = "../data/extracted"
    OCR_DIR: str = "../data/ocr"
    SCREENSHOT_DIR: str = "../data/screenshots"
    BACKUP_DIR: str = "../backups"
    DEBUG_REPORTS_DIR: str = "../data/debug_reports"
    
    # Qdrant Vector Store
    QDRANT_HOST: str = os.getenv("QDRANT_HOST", "qdrant" if os.path.exists("/.dockerenv") else "localhost")
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION: str = "documents"
    QDRANT_API_KEY: Optional[str] = None
    
    # Embeddings
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    EMBEDDING_DIMENSION: int = 384
    
    # OCR Settings
    OCR_ENABLED: bool = True
    ocr_enabled: bool = True
    TESSERACT_CMD: Optional[str] = None  # Path to tesseract executable if not in PATH
    
    # Chunking
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    
    # Browser Control
    BROWSER_HEADLESS: bool = True
    BROWSER_TIMEOUT: int = 30000  # milliseconds
    
    # Job Processing
    MAX_JOB_RETRIES: int = 3
    JOB_POLL_INTERVAL: int = 2  # seconds
    
# LLM Settings
    DEFAULT_MODEL: str = "llama3.1:latest"
    FAST_MODEL: str = os.getenv("FAST_MODEL", "qwen2.5:0.5b")
    DEFAULT_TEMPERATURE: float = 0.7
    DEFAULT_MAX_TOKENS: int = 2000
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")

    # Planner Settings
    PLANNER_MODEL: str = os.getenv("PLANNER_MODEL", "qwen2.5-coder:7b")
    MAX_PLAN_PHASES: int = int(os.getenv("MAX_PLAN_PHASES", "12"))
    
    # Coder Settings
    CODER_MODEL: str = os.getenv("CODER_MODEL", "qwen2.5-coder:7b")
    WORKSPACE_ROOT: str = os.getenv("WORKSPACE_ROOT", "/workspace/project")
    MAX_CODE_CONTEXT_FILES: int = int(os.getenv("MAX_CODE_CONTEXT_FILES", "8"))
    MAX_CODE_FILE_CHARS: int = int(os.getenv("MAX_CODE_FILE_CHARS", "12000"))
    
    # Applier Settings
    BACKUP_DIR: str = os.getenv("BACKUP_DIR", "/workspace/backups")
    
    # Web Search
    WEB_SEARCH_PROVIDER: str = os.getenv("WEB_SEARCH_PROVIDER", "searxng")
    SEARXNG_BASE_URL: str = os.getenv("SEARXNG_BASE_URL", "http://host.docker.internal:8080")
    WEB_SEARCH_MAX_RESULTS: int = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "8"))
    WEB_SEARCH_TIMEOUT_SECONDS: float = float(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "20.0"))
    
    # Browser Control
    BROWSER_HEADLESS: bool = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"
    BROWSER_SCREENSHOT_DIR: str = os.getenv("BROWSER_SCREENSHOT_DIR", "/data/screenshots")
    BROWSER_TIMEOUT_SECONDS: int = int(os.getenv("BROWSER_TIMEOUT_SECONDS", "30"))
    BROWSER_ALLOWED_HOSTS: str = os.getenv("BROWSER_ALLOWED_HOSTS", "localhost,127.0.0.1,host.docker.internal")
    
    # CORS
    CORS_ORIGINS: list = ["http://localhost:3000", "http://localhost:5173"]
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Global settings instance
settings = Settings()


def get_data_path(subdir: str = "") -> Path:
    """Get absolute path to data directory or subdirectory."""
    base_path = Path(__file__).parent.parent / "data"
    if subdir:
        return base_path / subdir
    return base_path


def ensure_directories():
    """Ensure all required directories exist."""
    dirs = [
        settings.UPLOAD_DIR,
        settings.EXTRACTED_DIR,
        settings.OCR_DIR,
        settings.SCREENSHOT_DIR,
        settings.BROWSER_SCREENSHOT_DIR,
        settings.BACKUP_DIR,
        settings.DEBUG_REPORTS_DIR,
    ]
    
    for dir_path in dirs:
        Path(dir_path).mkdir(parents=True, exist_ok=True)
