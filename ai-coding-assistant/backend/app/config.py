"""Configuration management for the AI Coding Assistant backend."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Single canonical configuration schema.

    Uppercase names are canonical. Compatibility properties at the bottom keep older
    modules working while they are migrated incrementally.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "AI Coding Assistant"
    DEBUG: bool = False
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Workspace / persistence
    WORKSPACE_ROOT: str = "/workspace/project"
    BACKUP_DIR: str = "/workspace/backups"
    DATABASE_PATH: str = Field(
        default="../data/app.db",
        validation_alias=AliasChoices("DATABASE_PATH", "APP_DATABASE_PATH"),
    )
    UPLOAD_DIR: str = "../data/uploads"
    EXTRACTED_DIR: str = "../data/extracted"
    OCR_DIR: str = "../data/ocr"
    SCREENSHOT_DIR: str = "../data/screenshots"
    DEBUG_REPORTS_DIR: str = "../data/debug_reports"

    # API keys
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None

    # Qdrant
    QDRANT_HOST: str = Field(default_factory=lambda: "qdrant" if Path("/.dockerenv").exists() else "localhost")
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION: str = "documents"
    QDRANT_API_KEY: Optional[str] = None

    # Embeddings / chunking
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    EMBEDDING_DIMENSION: int = 384
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200

    # OCR
    OCR_ENABLED: bool = True
    TESSERACT_CMD: Optional[str] = None

    # Jobs
    MAX_JOB_RETRIES: int = 3
    JOB_POLL_INTERVAL: int = 2

    # LLM / Ollama
    DEFAULT_MODEL: str = Field(
        default="llama3.1:latest",
        validation_alias=AliasChoices("DEFAULT_MODEL", "CHAT_MODEL"),
    )
    FAST_MODEL: str = "qwen2.5:0.5b"
    PLANNER_MODEL: str = "qwen2.5-coder:7b"
    CODER_MODEL: str = "qwen2.5-coder:7b"
    DEBUGGER_MODEL: str = "qwen2.5-coder:7b"
    REVIEWER_MODEL: str = "qwen2.5-coder:7b"
    DEFAULT_TEMPERATURE: float = 0.7
    DEFAULT_MAX_TOKENS: int = 2000
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"
    MAX_PLAN_PHASES: int = 12
    MAX_CODE_CONTEXT_FILES: int = 8
    MAX_CODE_FILE_CHARS: int = 12000

    # Web search
    WEB_SEARCH_PROVIDER: str = "searxng"
    SEARXNG_BASE_URL: str = "http://host.docker.internal:8080"
    WEB_SEARCH_MAX_RESULTS: int = 8
    WEB_SEARCH_TIMEOUT_SECONDS: float = 20.0

    # Browser
    BROWSER_HEADLESS: bool = True
    BROWSER_TIMEOUT: int = 30000  # retained for older browser module
    BROWSER_SCREENSHOT_DIR: str = "/data/screenshots"
    BROWSER_TIMEOUT_SECONDS: int = 30
    BROWSER_ALLOWED_HOSTS: str = "localhost,127.0.0.1,host.docker.internal"

    # Agent/self-improvement safety
    MAX_REPAIR_ATTEMPTS: int = 4
    MAX_PATCH_FILES: int = 12
    MAX_PATCH_BYTES: int = 500_000
    COMMAND_TIMEOUT_SECONDS: int = 120
    MAX_COMMAND_OUTPUT_CHARS: int = 40_000
    AGENT_ALLOWED_EXECUTABLES: str = "python,python3,pytest,npm,git,ruff,mypy"
    AGENT_PROTECTED_PATHS: str = ".env,.git/,data/ai_coder.db"

    # Manual self-improvement controller (Part 4)
    IMPROVEMENT_DEFAULT_POLICY: str = "manual"
    IMPROVEMENT_ALLOWED_RISKS: str = "low,medium"
    IMPROVEMENT_MAX_CANDIDATES: int = 8
    IMPROVEMENT_MAX_FILES: int = 8
    IMPROVEMENT_ACCEPTABLE_HEALTH_SCORE: float = 92.0
    IMPROVEMENT_MIN_PRIORITY: float = 0.05
    IMPROVEMENT_MAX_SCORE_REGRESSION: float = 3.0
    IMPROVEMENT_SOURCE_SCAN_FILES: int = 400
    IMPROVEMENT_SOURCE_SCAN_BYTES: int = 2_000_000

    # Outcome learning, experiments, drift and cycle budgets (Part 5)
    IMPROVEMENT_MIN_LEARNING_SAMPLES: int = 3
    IMPROVEMENT_HISTORY_LIMIT: int = 200
    IMPROVEMENT_EXPERIMENT_MAX_CANDIDATES: int = 3
    IMPROVEMENT_MAX_CYCLE_REPAIRS: int = 3
    IMPROVEMENT_MAX_CYCLE_ATTEMPTS: int = 8
    IMPROVEMENT_MAX_CYCLE_CHANGED_FILES: int = 16
    IMPROVEMENT_MAX_CYCLE_PATCH_BYTES: int = 600_000

    # Governance, repetition suppression and impact memory (Part 6)
    IMPROVEMENT_REPEAT_LIMIT: int = 2
    IMPROVEMENT_REPEAT_HISTORY_LIMIT: int = 50
    IMPROVEMENT_POLICY_MAX_REQUIRED_PATHS: int = 100
    IMPROVEMENT_POLICY_MAX_PROTECTED_ROUTES: int = 200
    IMPROVEMENT_GOVERNANCE_MAX_MODULE_LINES: int = 1200
    IMPROVEMENT_TEST_IMPACT_HISTORY_LIMIT: int = 200

    # Autonomy readiness, policy integrity, approval identity and cooldowns (Part 7)
    IMPROVEMENT_POLICY_SIGNING_KEY: str = ""
    IMPROVEMENT_APPROVER_CREDENTIALS_JSON: str = "{}"
    IMPROVEMENT_COOLDOWN_VALIDATION_HOURS: int = 2
    IMPROVEMENT_COOLDOWN_GOVERNANCE_HOURS: int = 12
    IMPROVEMENT_COOLDOWN_BUDGET_HOURS: int = 1
    IMPROVEMENT_COOLDOWN_ROLLBACK_HOURS: int = 24
    IMPROVEMENT_RISK_ESCALATION_FAILURES: int = 2
    IMPROVEMENT_READINESS_MIN_HEALTH: float = 85.0
    IMPROVEMENT_READINESS_MIN_COVERAGE: float = 70.0
    IMPROVEMENT_READINESS_MIN_DEPENDENCY_SCORE: float = 85.0
    IMPROVEMENT_READINESS_MIN_SUCCESSFUL_CYCLES: int = 3
    IMPROVEMENT_READINESS_MAX_ROLLBACK_RATE: float = 0.10
    IMPROVEMENT_READINESS_LOOKBACK: int = 20
    IMPROVEMENT_COVERAGE_MAX_REPORT_BYTES: int = 2_000_000

    # Dry-run scheduler/control plane (Part 8). Scheduled execution is restricted
    # to observe/propose-only cycles; automatic source promotion remains disabled.
    IMPROVEMENT_DRY_RUN_SCHEDULER_ENABLED: bool = False
    IMPROVEMENT_SCHEDULER_POLL_SECONDS: int = 60
    IMPROVEMENT_SCHEDULER_LEASE_TTL_SECONDS: int = 300
    IMPROVEMENT_SCHEDULER_MIN_INTERVAL_MINUTES: int = 15
    IMPROVEMENT_SCHEDULER_MAX_GLOBAL_RUNS_PER_HOUR: int = 10
    IMPROVEMENT_SCHEDULER_MAX_PROJECT_RUNS_PER_DAY: int = 4
    IMPROVEMENT_SCHEDULER_MAX_SCHEDULES_PER_PROJECT: int = 20
    IMPROVEMENT_SCHEDULER_CI_MAX_AGE_MINUTES: int = 1440
    IMPROVEMENT_SCHEDULER_SLO_MAX_AGE_MINUTES: int = 120
    IMPROVEMENT_SCHEDULER_SLO_MIN_ERROR_BUDGET: float = 20.0
    IMPROVEMENT_SCHEDULER_SLO_MIN_AVAILABILITY: float = 99.0
    IMPROVEMENT_SCHEDULER_SLO_MAX_ERROR_RATE: float = 1.0
    IMPROVEMENT_SCHEDULER_SLO_MAX_P95_MS: float = 2500.0
    IMPROVEMENT_SCHEDULER_CANARY_MIN_HEALTH: float = 80.0
    IMPROVEMENT_EVIDENCE_WEBHOOK_TOKEN: str = ""
    IMPROVEMENT_EVIDENCE_MAX_BYTES: int = 1_000_000

    # Production scheduler hardening (Part 9). These controls authenticate
    # evidence/operators and improve observability; they do not authorize apply.
    IMPROVEMENT_EVIDENCE_WEBHOOK_SIGNING_SECRET: str = ""
    IMPROVEMENT_EVIDENCE_WEBHOOK_MAX_SKEW_SECONDS: int = 300
    IMPROVEMENT_OPERATOR_CREDENTIALS_JSON: str = "{}"
    IMPROVEMENT_SCHEDULER_ALERT_RETENTION_DAYS: int = 30
    IMPROVEMENT_SCHEDULER_TELEMETRY_RETENTION_DAYS: int = 30
    IMPROVEMENT_SCHEDULER_PROD_MIN_INTERVAL_MINUTES: int = 60
    IMPROVEMENT_SCHEDULER_STAGING_MIN_INTERVAL_MINUTES: int = 30

    # Deployment / operations hardening (Part 10). Defaults keep all external
    # integrations optional and preserve the dry-run-only scheduler boundary.
    IMPROVEMENT_SCHEDULER_LEASE_BACKEND: str = "sqlite"
    IMPROVEMENT_SCHEDULER_REDIS_URL: str = ""
    IMPROVEMENT_SCHEDULER_REDIS_PREFIX: str = "ai-coding-assistant:scheduler"
    IMPROVEMENT_SCHEDULER_POSTGRES_DSN: str = ""
    IMPROVEMENT_SCHEDULER_LEADER_ELECTION_ENABLED: bool = True
    IMPROVEMENT_SCHEDULER_LEADER_LEASE_TTL_SECONDS: int = 120
    IMPROVEMENT_ALERT_WEBHOOK_URL: str = ""
    IMPROVEMENT_ALERT_WEBHOOK_SIGNING_SECRET: str = ""
    IMPROVEMENT_OTEL_EXPORTER_ENDPOINT: str = ""
    IMPROVEMENT_OTEL_EXPORTER_HEADERS_JSON: str = "{}"
    IMPROVEMENT_INTEGRATION_ALLOW_HTTP: bool = False
    IMPROVEMENT_INTEGRATION_HTTP_TIMEOUT_SECONDS: float = 5.0
    IMPROVEMENT_GITHUB_WEBHOOK_SECRET: str = ""
    IMPROVEMENT_GITLAB_WEBHOOK_TOKEN: str = ""
    IMPROVEMENT_WEBHOOK_DELIVERY_RETENTION_DAYS: int = 30
    IMPROVEMENT_OPERATOR_AUDIT_RETENTION_DAYS: int = 180
    IMPROVEMENT_SCHEDULER_RUN_RETENTION_DAYS: int = 90
    IMPROVEMENT_INTEGRATION_DELIVERY_RETENTION_DAYS: int = 30
    IMPROVEMENT_SCHEDULER_DR_DIR: str = "../data/scheduler-drills"

    # Deployment packaging / integration reliability (Part 11). These controls
    # harden operations only; scheduled source promotion remains disabled.
    IMPROVEMENT_SECRETS_PROVIDER: str = "env"
    IMPROVEMENT_SECRETS_DIR: str = "/run/secrets"
    IMPROVEMENT_INTEGRATION_MAX_ATTEMPTS: int = 5
    IMPROVEMENT_INTEGRATION_BACKOFF_BASE_SECONDS: int = 30
    IMPROVEMENT_INTEGRATION_BACKOFF_MAX_SECONDS: int = 3600
    IMPROVEMENT_GITHUB_STATUS_TOKEN: str = ""
    IMPROVEMENT_GITLAB_STATUS_TOKEN: str = ""
    IMPROVEMENT_GITLAB_API_BASE: str = "https://gitlab.com/api/v4"
    IMPROVEMENT_SCHEDULER_DR_BACKUP_KEEP: int = 10
    IMPROVEMENT_SCHEDULER_TRACE_RETENTION_DAYS: int = 14
    IMPROVEMENT_PROBE_REQUIRE_COORDINATION: bool = True

    # Candidate-to-staging release orchestration (Part 12). The release pipeline
    # may prepare isolated candidates and staging evidence, but never production apply.
    IMPROVEMENT_RELEASE_ROOT: str = "../data/releases"
    IMPROVEMENT_RELEASE_BUILD_MODE: str = "validate_only"  # validate_only|docker
    IMPROVEMENT_RELEASE_REQUIRE_CONTAINER_BUILD: bool = False
    IMPROVEMENT_RELEASE_DOCKER_NETWORK: str = "none"
    IMPROVEMENT_RELEASE_BUILD_TIMEOUT_SECONDS: int = 900
    IMPROVEMENT_RELEASE_PREVIEW_PROVIDER: str = "none"  # none|external
    IMPROVEMENT_RELEASE_PREVIEW_TTL_HOURS: int = 24
    IMPROVEMENT_RELEASE_SIGNING_KEY: str = ""
    IMPROVEMENT_RELEASE_REQUIRE_SIGNATURE: bool = True
    IMPROVEMENT_RELEASE_REQUIRE_VULNERABILITY_REPORT: bool = True
    IMPROVEMENT_RELEASE_MAX_CRITICAL_VULNS: int = 0
    IMPROVEMENT_RELEASE_MAX_HIGH_VULNS: int = 0
    IMPROVEMENT_RELEASE_MAX_MEDIUM_VULNS: int = 20
    IMPROVEMENT_RELEASE_VULN_SCANNER: str = "report_only"  # report_only|trivy
    IMPROVEMENT_RELEASE_VULN_REPORT_MAX_BYTES: int = 4_000_000
    IMPROVEMENT_RELEASE_WORKSPACE_TTL_HOURS: int = 48

    # Staging provider / release handoff orchestration (Part 13). External execution is
    # opt-in and production deployment remains unsupported by this application.
    IMPROVEMENT_STAGING_EXECUTION_ENABLED: bool = False
    IMPROVEMENT_STAGING_CI_TRIGGER_ENABLED: bool = False
    IMPROVEMENT_STAGING_OCI_EXECUTION_ENABLED: bool = False
    IMPROVEMENT_STAGING_PRODUCTION_DENY_TOKENS: str = "prod,production"
    IMPROVEMENT_STAGING_GITHUB_WORKFLOW: str = "staging.yml"
    IMPROVEMENT_GITHUB_ACTIONS_TOKEN: str = ""
    IMPROVEMENT_GITLAB_PIPELINE_TOKEN: str = ""
    IMPROVEMENT_RELEASE_COSIGN_ENABLED: bool = False
    IMPROVEMENT_STAGING_AUTO_TEARDOWN_EXPIRED: bool = False
    IMPROVEMENT_PRODUCTION_REQUEST_REQUIRE_VERIFIED_OPERATOR: bool = True
    IMPROVEMENT_PRODUCTION_REQUEST_ALLOWED_ROLES: str = "release-manager,maintainer"

    # Production release governance plane (Part 14). This plane authorizes and signs
    # credential-free deployment packages but cannot execute production deployments.
    IMPROVEMENT_PRODUCTION_GOVERNANCE_MIN_APPROVALS: int = 2
    IMPROVEMENT_PRODUCTION_GOVERNANCE_REQUIRED_ROLES: str = "release-manager,ops"
    IMPROVEMENT_PRODUCTION_GOVERNANCE_ALLOWED_APPROVER_ROLES: str = "release-manager,ops,security,maintainer"
    IMPROVEMENT_PRODUCTION_GOVERNANCE_CREATOR_ROLES: str = "release-manager,maintainer"
    IMPROVEMENT_PRODUCTION_GOVERNANCE_EDITOR_ROLES: str = "release-manager,maintainer,ops"
    IMPROVEMENT_PRODUCTION_GOVERNANCE_TRAIN_ROLES: str = "release-manager,ops"
    IMPROVEMENT_PRODUCTION_GOVERNANCE_LOCK_ROLES: str = "release-manager"
    IMPROVEMENT_PRODUCTION_GOVERNANCE_PACKAGE_ROLES: str = "release-manager,ops"
    IMPROVEMENT_PRODUCTION_GOVERNANCE_CHANGE_TICKET_REQUIRED: bool = True
    IMPROVEMENT_PRODUCTION_GOVERNANCE_CHANGE_TICKET_PATTERN: str = r"^[A-Z][A-Z0-9]+-[0-9]+$"
    IMPROVEMENT_PRODUCTION_GOVERNANCE_FREEZE_WINDOWS_JSON: str = "[]"
    IMPROVEMENT_PRODUCTION_GOVERNANCE_DEFAULT_TIMEZONE: str = "UTC"
    IMPROVEMENT_PRODUCTION_GOVERNANCE_RELEASE_TRAIN_REQUIRED: bool = False
    IMPROVEMENT_PRODUCTION_GOVERNANCE_RELEASE_TRAIN_WINDOW_REQUIRED: bool = False
    IMPROVEMENT_PRODUCTION_GOVERNANCE_LOCK_REQUIRE_SIGNATURE: bool = True
    IMPROVEMENT_PRODUCTION_GOVERNANCE_PACKAGE_REQUIRE_SIGNATURE: bool = True
    IMPROVEMENT_PRODUCTION_GOVERNANCE_DEPLOYER_AUDIENCE: str = "independent-production-deployer"

    # Independent production deployer handoff + production outcome learning (Part 15).
    # The AI backend still stores no production credentials and performs no deployment.
    IMPROVEMENT_PRODUCTION_GOVERNANCE_ARTIFACT_BINDING_REQUIRED: bool = False
    IMPROVEMENT_PRODUCTION_AUTHORIZATION_TTL_MINUTES: int = 10
    IMPROVEMENT_PRODUCTION_AUTHORIZATION_ROLES: str = "release-manager,ops"
    IMPROVEMENT_PRODUCTION_OUTCOME_SIGNING_KEY: str = ""
    IMPROVEMENT_PRODUCTION_OUTCOME_MAX_BYTES: int = 1_000_000
    IMPROVEMENT_PRODUCTION_LEARNING_LOOKBACK: int = 100
    IMPROVEMENT_PRODUCTION_LEARNING_ROLLBACK_PENALTY: float = 0.35

    # Part 16 production hardening / readiness certification.
    IMPROVEMENT_PRODUCTION_OUTCOME_PREVIOUS_SIGNING_KEYS: str = ""
    IMPROVEMENT_CERTIFICATION_SIGNING_KEY: str = ""
    IMPROVEMENT_CERTIFICATION_MAX_EVIDENCE_AGE_HOURS: int = 168
    IMPROVEMENT_CERTIFICATION_REQUIRED_GATES: str = "deployer_tests,migration_safety,key_rotation,slo_window,rollback_drill,chaos_failover,security_attack,audit_chain,load_concurrency"
    IMPROVEMENT_CERTIFICATION_MIN_PRODUCTION_SUCCESS_RATE: float = 0.80
    IMPROVEMENT_CERTIFICATION_MAX_ROLLBACK_RATE: float = 0.20

    # v1.1 intelligence / efficiency improvements. These tune deterministic
    # routing and local repository context selection; they do not weaken any
    # reviewer, security, governance, staging, or production boundary.
    V11_ADAPTIVE_ROUTING_ENABLED: bool = True
    V11_REPOSITORY_CONTEXT_ENABLED: bool = True
    V11_REPOSITORY_GRAPH_MAX_FILES: int = 1200
    V11_REPOSITORY_GRAPH_MAX_BYTES: int = 8_000_000
    V11_REPOSITORY_GRAPH_CACHE_SECONDS: float = 3.0
    V11_REPOSITORY_CONTEXT_MAX_FILES: int = 8
    V11_EXPERIENCE_MEMORY_ENABLED: bool = True
    V11_EXPERIENCE_HISTORY_LIMIT: int = 300
    V11_EXPERIENCE_PROMPT_LIMIT: int = 5

    V11_MODEL_USAGE_TELEMETRY_ENABLED: bool = True

    # ------------------------------------------------------------------
    # Compatibility aliases for older modules. New code should use the
    # uppercase canonical names above.
    # ------------------------------------------------------------------
    @property
    def workspace_root(self) -> str:
        return self.WORKSPACE_ROOT

    @property
    def ollama_base_url(self) -> str:
        return self.OLLAMA_BASE_URL

    @property
    def chat_model(self) -> str:
        return self.DEFAULT_MODEL

    @property
    def app_database_path(self) -> str:
        return self.DATABASE_PATH

    @property
    def max_code_context_files(self) -> int:
        return self.MAX_CODE_CONTEXT_FILES

    @property
    def max_code_file_chars(self) -> int:
        return self.MAX_CODE_FILE_CHARS

    @property
    def web_search_provider(self) -> str:
        return self.WEB_SEARCH_PROVIDER

    @property
    def searxng_base_url(self) -> str:
        return self.SEARXNG_BASE_URL

    @property
    def browser_headless(self) -> bool:
        return self.BROWSER_HEADLESS

    @property
    def browser_screenshot_dir(self) -> str:
        return self.BROWSER_SCREENSHOT_DIR

    @property
    def ocr_enabled(self) -> bool:
        return self.OCR_ENABLED


settings = Settings()


def get_data_path(subdir: str = "") -> Path:
    """Get absolute path to the backend data directory or a child directory."""
    base_path = Path(__file__).parent.parent / "data"
    return base_path / subdir if subdir else base_path


def ensure_directories() -> None:
    """Ensure all local writable directories exist."""
    for dir_path in (
        settings.UPLOAD_DIR,
        settings.EXTRACTED_DIR,
        settings.OCR_DIR,
        settings.SCREENSHOT_DIR,
        settings.BROWSER_SCREENSHOT_DIR,
        settings.BACKUP_DIR,
        settings.DEBUG_REPORTS_DIR,
    ):
        Path(dir_path).mkdir(parents=True, exist_ok=True)
