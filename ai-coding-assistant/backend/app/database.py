"""
Database connection and operations for SQLite.
"""
import sqlite3
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
from app.config import settings


def get_db_path() -> str:
    """Get the absolute path to the database file."""
    db_path = Path(settings.DATABASE_PATH)
    if not db_path.is_absolute():
        db_path = Path(__file__).parent.parent / settings.DATABASE_PATH
    return str(db_path)


def get_db_connection() -> sqlite3.Connection:
    """Create a new database connection with row factory."""
    # Increase timeout to 60s and allow multi-threading access
    conn = sqlite3.connect(get_db_path(), timeout=60.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable robust concurrency settings for WAL mode to prevent 'database is locked' errors
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    return conn


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_database():
    """Initialize database schema if it doesn't exist."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Documents table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                original_filename TEXT,
                file_hash TEXT UNIQUE,
                file_size INTEGER,
                mime_type TEXT,
                status TEXT DEFAULT 'uploaded',
                qdrant_status TEXT DEFAULT 'not_indexed',
                knowledge_base_id TEXT,
                extracted_text TEXT,
                is_scanned BOOLEAN DEFAULT 0,
                ocr_completed BOOLEAN DEFAULT 0,
                chunk_count INTEGER DEFAULT 0,
                indexed_chunk_count INTEGER DEFAULT 0,
                metadata_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                stored_filename TEXT,
                file_path TEXT,
                file_size_bytes INTEGER,
                is_likely_scanned BOOLEAN DEFAULT 0,
                ocr_status TEXT DEFAULT 'not_started',
                extraction_status TEXT DEFAULT 'not_started',
                extracted_path TEXT,
                extracted_at TEXT,
                chunking_status TEXT DEFAULT 'not_started',
                chunking_error TEXT,
                chunked_at TEXT,
                embedding_status TEXT DEFAULT 'not_started',
                project_id TEXT DEFAULT 'default'
            )
        """)
        
        # Add source_type to documents if it doesn't exist (Migration for Phase 21)
        try:
            cursor.execute("ALTER TABLE documents ADD COLUMN source_type TEXT DEFAULT 'pdf'")
        except sqlite3.OperationalError:
            pass # Column already exists
            
        # Web Memory Sources table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS web_memory_sources (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                query TEXT NOT NULL,
                title TEXT,
                urls_json TEXT,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
        """)
        
        # Manual Notes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS manual_notes (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
        """)
        
        # Project Audit Reports (Phase 58)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_audit_reports (
                id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                overall_status TEXT NOT NULL,
                summary_json TEXT,
                findings_json TEXT,
                recommendations_json TEXT,
                fix_queue_json TEXT,
                created_at TEXT NOT NULL
            )
        """)
        
        # Audit Fix History table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_fix_history (
                id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                task TEXT NOT NULL,
                changes_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        
        # Coder Sessions table — persistent graph execution state
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS coder_sessions (
                id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                goal TEXT NOT NULL,
                graph_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                completed_nodes TEXT NOT NULL DEFAULT '[]',
                failed_nodes TEXT NOT NULL DEFAULT '{}',
                generated_files TEXT NOT NULL DEFAULT '{}',
                import_warnings TEXT NOT NULL DEFAULT '[]',
                current_node_id TEXT,
                result_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # Migration: add import_warnings to existing databases that lack it
        try:
            cursor.execute("ALTER TABLE coder_sessions ADD COLUMN import_warnings TEXT NOT NULL DEFAULT '[]'")
        except Exception:
            pass  # Column already exists — safe to ignore
        # Migration: add file_paths_json to existing databases (for session resume)
        try:
            cursor.execute("ALTER TABLE coder_sessions ADD COLUMN file_paths_json TEXT NOT NULL DEFAULT '[]'")
        except Exception:
            pass  # Column already exists — safe to ignore
        

        # Document chunks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT,
                text TEXT,
                metadata_json TEXT,
                normalized_text_hash TEXT,
                page_start INTEGER,
                page_end INTEGER,
                token_estimate INTEGER,
                char_count INTEGER,
                status TEXT DEFAULT 'active',
                chunking_strategy TEXT DEFAULT 'basic',
                chapter_title TEXT,
                section_title TEXT,
                subsection_title TEXT,
                heading_path TEXT,
                parent_section_id TEXT,
                qdrant_status TEXT DEFAULT 'pending',
                qdrant_point_id TEXT,
                qdrant_indexed_at TEXT,
                qdrant_error TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
        """)
        
        # Official Docs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS official_docs (
                technology TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                version TEXT NOT NULL,
                chunk_count INTEGER DEFAULT 0,
                last_updated TEXT NOT NULL
            )
        """)
        
        # Background jobs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS background_jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                status TEXT DEFAULT 'queued',
                payload_json TEXT,
                result_json TEXT,
                error TEXT,
                retry_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT
            )
        """)
        
        # Pipeline logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_logs (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                retry_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
        """)
        
        # Knowledge bases table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_bases (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL
            )
        """)
        
        # Run history table (for test execution tracking)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS run_history (
                id TEXT PRIMARY KEY,
                run_type TEXT NOT NULL,
                status TEXT DEFAULT 'started',
                request_json TEXT,
                response_json TEXT,
                error TEXT,
                duration_ms INTEGER,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)

        # Error Memory table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS error_memory (
                id TEXT PRIMARY KEY,
                project_path TEXT NOT NULL,
                command TEXT NOT NULL,
                error_output TEXT NOT NULL,
                successful_fix TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        
        # Repair attempts — every detect/diagnose/patch/verify iteration is persisted.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS repair_attempts (
                id TEXT PRIMARY KEY,
                cycle_id TEXT,
                issue_id TEXT NOT NULL,
                attempt_no INTEGER NOT NULL,
                model TEXT,
                diagnosis TEXT,
                patch_json TEXT NOT NULL DEFAULT '[]',
                validation_plan_json TEXT NOT NULL DEFAULT '[]',
                validation_result_json TEXT NOT NULL DEFAULT '{}',
                failure_signature TEXT,
                quality_score REAL,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_repair_attempts_issue ON repair_attempts(issue_id, attempt_no)")

        # v1.1 contextual engineering experience memory.  Records are project-scoped
        # and auditable; this is operational learning, not model-weight retraining.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS engineering_experiences (
                id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                issue_id TEXT,
                fingerprint TEXT NOT NULL UNIQUE,
                task TEXT NOT NULL,
                task_terms_json TEXT NOT NULL DEFAULT '[]',
                strategy TEXT,
                outcome TEXT NOT NULL,
                failure_class TEXT,
                files_json TEXT NOT NULL DEFAULT '[]',
                lesson TEXT,
                validation_status TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                occurrence_count INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_engineering_experiences_project ON engineering_experiences(project_name,last_seen_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_engineering_experiences_issue ON engineering_experiences(issue_id)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS v11_benchmark_runs (
                id TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                suite_name TEXT NOT NULL,
                cases_json TEXT NOT NULL DEFAULT '[]',
                summary_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_v11_benchmark_suite ON v11_benchmark_runs(suite_name,created_at)")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS v11_model_usage (
                id TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL, operation TEXT NOT NULL,
                prompt_chars INTEGER NOT NULL DEFAULT 0, output_chars INTEGER NOT NULL DEFAULT 0,
                estimated_input_tokens INTEGER NOT NULL DEFAULT 0, estimated_output_tokens INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0, success INTEGER NOT NULL DEFAULT 1, error_type TEXT,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_v11_model_usage_created ON v11_model_usage(created_at)")

        # Manual self-improvement controller state. Part 4 intentionally leaves
        # recurring scheduling disabled; cycles are user-triggered and auditable.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_health_snapshots (
                id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                cycle_id TEXT,
                phase TEXT NOT NULL DEFAULT 'baseline',
                health_score REAL NOT NULL,
                dimensions_json TEXT NOT NULL DEFAULT '{}',
                findings_json TEXT NOT NULL DEFAULT '[]',
                checks_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_cycles (
                id TEXT PRIMARY KEY, project_name TEXT NOT NULL, trigger TEXT NOT NULL,
                state TEXT NOT NULL, policy TEXT NOT NULL DEFAULT 'manual',
                baseline_score REAL, final_score REAL, baseline_snapshot_id TEXT,
                final_snapshot_id TEXT, selected_candidate_id TEXT, selected_issue_id TEXT,
                request_json TEXT NOT NULL DEFAULT '{}', result_json TEXT,
                started_at TEXT NOT NULL, completed_at TEXT, stop_reason TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_candidates (
                id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL, problem TEXT NOT NULL,
                evidence_json TEXT, proposal TEXT, risk TEXT, benefit REAL, confidence REAL,
                urgency REAL DEFAULT 0.5, estimated_cost REAL, priority_score REAL,
                likely_files_json TEXT NOT NULL DEFAULT '[]', validation_plan_json TEXT NOT NULL DEFAULT '[]',
                issue_id TEXT, status TEXT NOT NULL, created_at TEXT, updated_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                state TEXT,
                message TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (cycle_id) REFERENCES improvement_cycles(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_outcomes (
                id TEXT PRIMARY KEY,
                cycle_id TEXT NOT NULL,
                candidate_id TEXT,
                issue_id TEXT,
                project_name TEXT NOT NULL,
                apply_status TEXT NOT NULL,
                baseline_score REAL,
                final_score REAL,
                score_delta REAL,
                baseline_snapshot_id TEXT,
                final_snapshot_id TEXT,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_experiments (
                id TEXT PRIMARY KEY,
                cycle_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                issue_id TEXT,
                experiment_rank INTEGER NOT NULL,
                status TEXT NOT NULL,
                quality_score REAL,
                usage_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_baselines (
                id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT 'approved',
                payload_json TEXT NOT NULL DEFAULT '{}',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_policies (
                id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                policy_json TEXT NOT NULL DEFAULT '{}',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_governance_checks (
                id TEXT PRIMARY KEY,
                cycle_id TEXT,
                candidate_id TEXT,
                issue_id TEXT,
                project_name TEXT NOT NULL,
                status TEXT NOT NULL,
                violations_json TEXT NOT NULL DEFAULT '[]',
                warnings_json TEXT NOT NULL DEFAULT '[]',
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_test_impacts (
                id TEXT PRIMARY KEY,
                cycle_id TEXT NOT NULL,
                candidate_id TEXT,
                issue_id TEXT,
                project_name TEXT NOT NULL,
                changed_files_json TEXT NOT NULL DEFAULT '[]',
                checks_json TEXT NOT NULL DEFAULT '[]',
                coverage_json TEXT NOT NULL DEFAULT '{}',
                passed INTEGER NOT NULL DEFAULT 0,
                quality_score REAL,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_approvals (
                id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL, project_name TEXT NOT NULL,
                approver_id TEXT NOT NULL, approver_hash TEXT NOT NULL, role TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_coverage_reports (
                id TEXT PRIMARY KEY, project_name TEXT NOT NULL, cycle_id TEXT, phase TEXT NOT NULL,
                format TEXT NOT NULL, line_coverage REAL, branch_coverage REAL,
                normalized_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_regression_attributions (
                id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL, candidate_id TEXT, issue_id TEXT, outcome_id TEXT,
                project_name TEXT NOT NULL, failure_class TEXT, dimension_deltas_json TEXT NOT NULL DEFAULT '{}',
                regressed_dimensions_json TEXT NOT NULL DEFAULT '{}', changed_files_json TEXT NOT NULL DEFAULT '[]',
                confidence TEXT NOT NULL DEFAULT 'none', details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            )
        """)
        # Part 8 dry-run scheduler/control-plane persistence. Scheduled runs may
        # only launch observe-only improvement cycles or canary observations.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_schedules (
                id TEXT PRIMARY KEY, project_name TEXT NOT NULL, name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1, mode TEXT NOT NULL DEFAULT 'observe_propose',
                interval_minutes INTEGER NOT NULL DEFAULT 1440, timezone TEXT NOT NULL DEFAULT 'UTC',
                maintenance_windows_json TEXT NOT NULL DEFAULT '[]',
                require_readiness INTEGER NOT NULL DEFAULT 1, require_ci_success INTEGER NOT NULL DEFAULT 0,
                require_slo INTEGER NOT NULL DEFAULT 0, max_runs_per_day INTEGER,
                request_json TEXT NOT NULL DEFAULT '{}', next_run_at TEXT, last_run_at TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_scheduler_runs (
                id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL, project_name TEXT NOT NULL,
                mode TEXT NOT NULL, status TEXT NOT NULL, cycle_id TEXT,
                decision_json TEXT NOT NULL DEFAULT '{}', started_at TEXT NOT NULL, completed_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_scheduler_leases (
                lease_key TEXT PRIMARY KEY, owner_id TEXT NOT NULL, acquired_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL, expires_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_scheduler_control (
                scope TEXT PRIMARY KEY, kill_switch INTEGER NOT NULL DEFAULT 0,
                reason TEXT, updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_ci_evidence (
                id TEXT PRIMARY KEY, project_name TEXT NOT NULL, provider TEXT NOT NULL,
                event_type TEXT NOT NULL DEFAULT 'ci', commit_sha TEXT, branch TEXT,
                status TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}', received_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_slo_evidence (
                id TEXT PRIMARY KEY, project_name TEXT NOT NULL, source TEXT NOT NULL,
                availability REAL, error_rate REAL, latency_p95_ms REAL, error_budget_remaining REAL,
                payload_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            )
        """)
        # Part 9 production scheduler hardening. Evidence deliveries are replay-protected,
        # operator actions are auditable, alerts/telemetry are persisted, and leases use
        # monotonically increasing fencing tokens for safer multi-instance coordination.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_webhook_deliveries (
                delivery_id TEXT PRIMARY KEY, project_name TEXT NOT NULL, evidence_type TEXT NOT NULL,
                signature_digest TEXT NOT NULL, signed_at TEXT NOT NULL, received_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_scheduler_lease_fences (
                lease_key TEXT PRIMARY KEY, last_token INTEGER NOT NULL DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_operator_audit (
                id TEXT PRIMARY KEY, operator_id TEXT NOT NULL, role TEXT NOT NULL, action TEXT NOT NULL,
                project_name TEXT, schedule_id TEXT, metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_scheduler_alerts (
                id TEXT PRIMARY KEY, project_name TEXT NOT NULL, schedule_id TEXT, run_id TEXT,
                severity TEXT NOT NULL, code TEXT NOT NULL, message TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL, acknowledged_at TEXT, acknowledged_by TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_scheduler_telemetry (
                id TEXT PRIMARY KEY, event_type TEXT NOT NULL, project_name TEXT, schedule_id TEXT, run_id TEXT,
                duration_ms REAL, attributes_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            )
        """)
        # Part 10 deployment/integration persistence.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_scheduler_deliveries (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, source_id TEXT NOT NULL, target TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, last_attempt_at TEXT, delivered_at TEXT, last_error TEXT,
                UNIQUE(kind, source_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_scheduler_dr_drills (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            )
        """)
        # Part 11 deployment packaging / reliability persistence.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_scheduler_status_publications (
                id TEXT PRIMARY KEY, provider TEXT NOT NULL, project_name TEXT NOT NULL,
                commit_sha TEXT NOT NULL, target TEXT NOT NULL, state TEXT NOT NULL,
                description TEXT, context TEXT, status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT, created_at TEXT NOT NULL,
                last_attempt_at TEXT, delivered_at TEXT, last_error TEXT, dead_lettered_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_scheduler_traces (
                id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, span_id TEXT NOT NULL, parent_span_id TEXT,
                name TEXT NOT NULL, project_name TEXT, schedule_id TEXT, run_id TEXT,
                status TEXT NOT NULL, duration_ms REAL, attributes_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL, otel_exported_at TEXT, otel_export_error TEXT
            )
        """)
        # Part 12 candidate-to-staging release orchestration. Production promotion is
        # deliberately not represented as an executable state in these tables.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_release_candidates (
                id TEXT PRIMARY KEY, project_name TEXT NOT NULL, issue_id TEXT NOT NULL,
                commit_sha TEXT, scm_provider TEXT, scm_target TEXT, status TEXT NOT NULL DEFAULT 'created',
                workspace_path TEXT, request_json TEXT NOT NULL DEFAULT '{}',
                evidence_bundle_json TEXT NOT NULL DEFAULT '{}', failure_reason TEXT,
                production_promotion_allowed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, staging_ready_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_release_checks (
                id TEXT PRIMARY KEY, release_id TEXT NOT NULL, check_type TEXT NOT NULL,
                status TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_release_artifacts (
                id TEXT PRIMARY KEY, release_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
                digest_sha256 TEXT NOT NULL, path TEXT, signature TEXT, signature_algorithm TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_preview_environments (
                id TEXT PRIMARY KEY, release_id TEXT NOT NULL, provider TEXT NOT NULL, preview_url TEXT,
                status TEXT NOT NULL, expires_at TEXT, metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        # Part 13 staging provider / release handoff persistence. Production requests are
        # evidence-only handoffs and are not executable deployment instructions.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_staging_deployments (
                id TEXT PRIMARY KEY, release_id TEXT NOT NULL, provider TEXT NOT NULL,
                environment TEXT NOT NULL DEFAULT 'staging', status TEXT NOT NULL DEFAULT 'created',
                deployment_ref TEXT, preview_url TEXT, manifest_json TEXT NOT NULL DEFAULT '{}',
                evidence_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                rolled_back_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_release_attestations (
                id TEXT PRIMARY KEY, release_id TEXT NOT NULL, kind TEXT NOT NULL, predicate_type TEXT NOT NULL,
                digest_sha256 TEXT NOT NULL, statement_json TEXT NOT NULL DEFAULT '{}', signature TEXT,
                signature_algorithm TEXT, created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_production_release_requests (
                id TEXT PRIMARY KEY, release_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'requested',
                requested_by TEXT NOT NULL, role TEXT NOT NULL, evidence_digest TEXT NOT NULL,
                request_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        # Part 14 production release governance. These tables contain approvals, immutable
        # locks and credential-free packages for an independent deployer; no deploy executor.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_production_governance_cases (
                id TEXT PRIMARY KEY, production_request_id TEXT NOT NULL, release_id TEXT NOT NULL,
                project_name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
                change_ticket_json TEXT NOT NULL DEFAULT '{}', release_train_id TEXT,
                rollout_plan_json TEXT NOT NULL DEFAULT '{}', governance_digest TEXT,
                lock_signature TEXT, lock_signature_algorithm TEXT, locked_by TEXT, locked_at TEXT,
                created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_production_governance_approvals (
                id TEXT PRIMARY KEY, case_id TEXT NOT NULL, approver_id TEXT NOT NULL, role TEXT NOT NULL,
                decision TEXT NOT NULL, evidence_digest TEXT NOT NULL, comment TEXT, created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_release_trains (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, environment TEXT NOT NULL DEFAULT 'production',
                status TEXT NOT NULL DEFAULT 'open', window_start TEXT NOT NULL, window_end TEXT NOT NULL,
                timezone TEXT NOT NULL DEFAULT 'UTC', metadata_json TEXT NOT NULL DEFAULT '{}',
                created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_production_deployment_packages (
                id TEXT PRIMARY KEY, case_id TEXT NOT NULL, digest_sha256 TEXT NOT NULL,
                signature TEXT NOT NULL, signature_algorithm TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_production_governance_events (
                id TEXT PRIMARY KEY, case_id TEXT NOT NULL, event_type TEXT NOT NULL,
                operator_id TEXT NOT NULL, role TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        # Part 15 fresh deployment authorization + signed production outcome feedback.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_production_deployment_authorizations (
                id TEXT PRIMARY KEY, package_id TEXT NOT NULL, case_id TEXT NOT NULL, project_name TEXT NOT NULL,
                digest_sha256 TEXT NOT NULL, signature TEXT NOT NULL, signature_algorithm TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}', issued_by TEXT NOT NULL, expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_production_outcomes (
                id TEXT PRIMARY KEY, deployment_id TEXT NOT NULL UNIQUE, package_id TEXT NOT NULL, authorization_id TEXT,
                case_id TEXT, release_id TEXT, project_name TEXT NOT NULL, commit_sha TEXT, provider TEXT,
                rollout_strategy TEXT, status TEXT NOT NULL, failure_class TEXT, candidate_strategy_key TEXT,
                metrics_json TEXT NOT NULL DEFAULT '{}', payload_json TEXT NOT NULL DEFAULT '{}',
                receipt_digest TEXT NOT NULL UNIQUE, signature TEXT NOT NULL, signature_algorithm TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS change_transactions (
                id TEXT PRIMARY KEY, candidate_id TEXT, patch_json TEXT NOT NULL, backup_ref TEXT,
                tests_before_json TEXT, tests_after_json TEXT, score_before REAL, score_after REAL,
                approval_status TEXT, apply_status TEXT, rollback_status TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS verified_repairs (
                issue_id TEXT PRIMARY KEY, project_name TEXT NOT NULL, task TEXT NOT NULL,
                proposed_changes_json TEXT NOT NULL, validation_json TEXT NOT NULL,
                review_json TEXT NOT NULL, security_json TEXT NOT NULL, quality_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'verified', snapshot_id TEXT,
                created_at TEXT NOT NULL, applied_at TEXT
            )
        """)

        # IDE sessions and event timeline. These back Ask/Plan/Edit/Fix/Review/Agent
        # modes and let the VS Code extension replay/stream every agent action.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ide_sessions (
                id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                project_name TEXT NOT NULL,
                task TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                issue_id TEXT,
                request_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ide_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                stage TEXT,
                message TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES ide_sessions(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ide_events_session ON ide_events(session_id, seq)")

        # Chat sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                document_id TEXT,
                knowledge_base_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Chat messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sources_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            )
        """)
        
        # Change timeline and analysis/evaluation tables used by the agentic pipeline.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS change_timeline (
                id TEXT PRIMARY KEY, event_type TEXT NOT NULL, title TEXT NOT NULL,
                description TEXT, related_test_run_id TEXT, related_snapshot_id TEXT,
                related_issue_id TEXT, status TEXT, metadata_json TEXT, created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_gap_reports (
                id TEXT PRIMARY KEY, scope TEXT NOT NULL, status TEXT NOT NULL,
                gaps_json TEXT NOT NULL DEFAULT '[]', summary_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rag_eval_sets (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, cases_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL, updated_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rag_eval_runs (
                id TEXT PRIMARY KEY, eval_set_id TEXT NOT NULL, status TEXT NOT NULL,
                score REAL, results_json TEXT NOT NULL DEFAULT '[]', model TEXT,
                created_at TEXT NOT NULL, completed_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS regression_reports (
                id TEXT PRIMARY KEY, baseline_ref TEXT, current_ref TEXT, status TEXT NOT NULL,
                regressions_json TEXT NOT NULL DEFAULT '[]', improvements_json TEXT NOT NULL DEFAULT '[]',
                unchanged_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_sections (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL, section_index INTEGER,
                level INTEGER, title TEXT, heading_path TEXT, page_start INTEGER, page_end INTEGER,
                metadata_json TEXT, created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
        """)

        # Backward-compatible schema repair. Older databases were created by several
        # generations of the ingestion pipeline with different column names.
        def ensure_columns(table_name: str, columns: dict[str, str]) -> None:
            existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()}
            for name, declaration in columns.items():
                if name not in existing:
                    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {declaration}")

        ensure_columns("documents", {
            "source_type": "TEXT DEFAULT 'pdf'",
            "stored_filename": "TEXT", "file_path": "TEXT", "file_size_bytes": "INTEGER",
            "is_likely_scanned": "BOOLEAN DEFAULT 0", "ocr_status": "TEXT DEFAULT 'not_started'",
            "extraction_status": "TEXT DEFAULT 'not_started'", "extracted_path": "TEXT",
            "extracted_at": "TEXT", "chunking_status": "TEXT DEFAULT 'not_started'",
            "chunking_error": "TEXT", "chunked_at": "TEXT",
            "embedding_status": "TEXT DEFAULT 'not_started'", "project_id": "TEXT DEFAULT 'default'",
        })
        ensure_columns("document_chunks", {
            "content": "TEXT", "text": "TEXT", "normalized_text_hash": "TEXT",
            "page_start": "INTEGER", "page_end": "INTEGER", "token_estimate": "INTEGER",
            "char_count": "INTEGER", "status": "TEXT DEFAULT 'active'",
            "chunking_strategy": "TEXT DEFAULT 'basic'", "chapter_title": "TEXT",
            "section_title": "TEXT", "subsection_title": "TEXT", "heading_path": "TEXT",
            "parent_section_id": "TEXT", "qdrant_indexed_at": "TEXT", "qdrant_error": "TEXT",
        })

        ensure_columns("verified_repairs", {
            "post_apply_validation_json": "TEXT",
            "rollback_reason": "TEXT",
            "rolled_back_at": "TEXT",
        })
        ensure_columns("improvement_cycles", {
            "policy": "TEXT NOT NULL DEFAULT 'manual'",
            "policy_integrity_json": "TEXT NOT NULL DEFAULT '{}'",
            "baseline_snapshot_id": "TEXT", "final_snapshot_id": "TEXT",
            "selected_issue_id": "TEXT", "request_json": "TEXT NOT NULL DEFAULT '{}'",
            "result_json": "TEXT",
            "budget_json": "TEXT NOT NULL DEFAULT '{}'",
            "usage_json": "TEXT NOT NULL DEFAULT '{}'",
            "policy_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
            "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
            "cancelled_at": "TEXT",
        })
        ensure_columns("improvement_production_governance_cases", {
            "artifact_binding_json": "TEXT NOT NULL DEFAULT '{}'",
        })

        ensure_columns("improvement_candidates", {
            "urgency": "REAL DEFAULT 0.5", "priority_score": "REAL",
            "likely_files_json": "TEXT NOT NULL DEFAULT '[]'",
            "validation_plan_json": "TEXT NOT NULL DEFAULT '[]'", "issue_id": "TEXT",
            "created_at": "TEXT", "updated_at": "TEXT",
            "strategy_key": "TEXT",
            "base_priority_score": "REAL",
            "learning_multiplier": "REAL DEFAULT 1.0",
            "history_samples": "INTEGER DEFAULT 0",
            "history_success_rate": "REAL DEFAULT 0",
            "history_average_score_delta": "REAL DEFAULT 0",
            "candidate_fingerprint": "TEXT",
            "suppressed": "INTEGER NOT NULL DEFAULT 0",
            "suppression_reason": "TEXT",
            "repeat_count": "INTEGER NOT NULL DEFAULT 0",
            "impact_memory_json": "TEXT NOT NULL DEFAULT '{}'",
            "base_risk": "TEXT",
            "cooldown_until": "TEXT",
            "cooldown_reason": "TEXT",
            "risk_escalation_json": "TEXT NOT NULL DEFAULT '{}'",
            "production_history_samples": "INTEGER DEFAULT 0",
            "production_failure_rate": "REAL DEFAULT 0",
            "production_rollbacks": "INTEGER DEFAULT 0",
            "production_learning_multiplier": "REAL DEFAULT 1.0",
        })
        ensure_columns("improvement_experiments", {
            "discarded_at": "TEXT",
        })
        ensure_columns("improvement_test_impacts", {
            "coverage_json": "TEXT NOT NULL DEFAULT '{}'",
        })

        # Create indexes for common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_kb ON documents(knowledge_base_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON background_jobs(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_type ON background_jobs(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_document ON pipeline_logs(document_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_health_project_created ON project_health_snapshots(project_name, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_cycles_project ON improvement_cycles(project_name, started_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_candidates_cycle ON improvement_candidates(cycle_id, priority_score)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_events_cycle ON improvement_events(cycle_id, seq)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_outcomes_project ON improvement_outcomes(project_name, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_experiments_cycle ON improvement_experiments(cycle_id, experiment_rank)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_project_baselines_project ON project_baselines(project_name, active, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_candidates_strategy ON improvement_candidates(strategy_key)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_candidates_fingerprint ON improvement_candidates(candidate_fingerprint)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_policies_project ON improvement_policies(project_name, active, updated_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_governance_cycle ON improvement_governance_checks(cycle_id, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_test_impacts_project ON improvement_test_impacts(project_name, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_approvals_cycle ON improvement_approvals(cycle_id, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_coverage_project ON improvement_coverage_reports(project_name, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_regressions_project ON improvement_regression_attributions(project_name, created_at)")
        # Additive Part 9 columns for existing Part 8 databases.
        ensure_columns("improvement_schedules", {
            "environment": "TEXT NOT NULL DEFAULT 'dev'",
            "ci_branch": "TEXT",
            "ci_commit_sha": "TEXT",
            "bind_ci_to_project_head": "INTEGER NOT NULL DEFAULT 0",
        })
        ensure_columns("improvement_scheduler_leases", {"fence_token": "INTEGER NOT NULL DEFAULT 0"})
        ensure_columns("improvement_scheduler_telemetry", {
            "otel_exported_at": "TEXT",
            "otel_export_error": "TEXT",
        })
        ensure_columns("improvement_scheduler_deliveries", {
            "next_attempt_at": "TEXT",
            "dead_lettered_at": "TEXT",
            "last_status_code": "INTEGER",
        })
        ensure_columns("improvement_scheduler_traces", {
            "otel_exported_at": "TEXT",
            "otel_export_error": "TEXT",
        })

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_schedules_due ON improvement_schedules(enabled, next_run_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_scheduler_runs_project ON improvement_scheduler_runs(project_name, started_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_scheduler_runs_schedule ON improvement_scheduler_runs(schedule_id, started_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_ci_project ON improvement_ci_evidence(project_name, received_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_slo_project ON improvement_slo_evidence(project_name, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_audit_created ON improvement_operator_audit(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_alerts_status ON improvement_scheduler_alerts(status, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_telemetry_created ON improvement_scheduler_telemetry(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_scheduler_deliveries_status ON improvement_scheduler_deliveries(status, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_scheduler_dr_created ON improvement_scheduler_dr_drills(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_status_publications_status ON improvement_scheduler_status_publications(status, next_attempt_at, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_scheduler_traces_run ON improvement_scheduler_traces(run_id, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_scheduler_traces_trace ON improvement_scheduler_traces(trace_id, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_release_project ON improvement_release_candidates(project_name, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_release_status ON improvement_release_candidates(status, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_release_checks_release ON improvement_release_checks(release_id, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_release_artifacts_release ON improvement_release_artifacts(release_id, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_preview_release ON improvement_preview_environments(release_id, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_staging_release ON improvement_staging_deployments(release_id, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_attestations_release ON improvement_release_attestations(release_id, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_improvement_prod_requests_release ON improvement_production_release_requests(release_id, created_at)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_prod_governance_request ON improvement_production_governance_cases(production_request_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_prod_governance_project ON improvement_production_governance_cases(project_name, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_prod_governance_status ON improvement_production_governance_cases(status, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_prod_governance_approvals_case ON improvement_production_governance_approvals(case_id, created_at)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_prod_governance_approval_digest ON improvement_production_governance_approvals(case_id, approver_id, evidence_digest)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_release_trains_window ON improvement_release_trains(status, window_start)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_prod_deployment_package_case ON improvement_production_deployment_packages(case_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_prod_governance_events_case ON improvement_production_governance_events(case_id, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_prod_authorizations_package ON improvement_production_deployment_authorizations(package_id, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_prod_outcomes_project ON improvement_production_outcomes(project_name, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_prod_outcomes_strategy ON improvement_production_outcomes(candidate_strategy_key, created_at)")

        # Architecture cache table (Map-Reduce semantic cache)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS architecture_cache (
                hash_key TEXT PRIMARY KEY,
                component_name TEXT,
                sub_architecture_md TEXT,
                updated_at TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_arch_cache_component ON architecture_cache(component_name)")
        
        # Backward-compatible migration: add arch_hash to audit reports if not present
        try:
            cursor.execute("ALTER TABLE project_audit_reports ADD COLUMN arch_hash TEXT")
        except Exception:
            pass  # Column already exists
        
        conn.commit()
    finally:
        conn.close()


# Document operations
def get_document_by_id(document_id: str) -> Optional[Dict[str, Any]]:
    """Get document by ID."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE id = ?", (document_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_document_by_hash(file_hash: str) -> Optional[Dict[str, Any]]:
    """Get document by file hash."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE file_hash = ?", (file_hash,))
        row = cursor.fetchone()
        return dict(row) if row else None


def insert_document(doc: Dict[str, Any]):
    """Insert a document while normalizing legacy field names.

    The project historically used two document schemas. Filtering to the live
    table columns lets old callers coexist with the canonical schema safely.
    """
    record = dict(doc)
    record.setdefault("filename", record.get("stored_filename") or record.get("original_filename") or record.get("id") or "document")
    if "file_size" not in record and "file_size_bytes" in record:
        record["file_size"] = record.get("file_size_bytes")
    if "is_scanned" not in record and "is_likely_scanned" in record:
        record["is_scanned"] = record.get("is_likely_scanned")

    with get_db() as conn:
        allowed = {row[1] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
        filtered = {key: value for key, value in record.items() if key in allowed}
        columns = ", ".join(filtered.keys())
        placeholders = ", ".join(["?" for _ in filtered])
        conn.execute(
            f"INSERT INTO documents ({columns}) VALUES ({placeholders})",
            tuple(filtered.values())
        )
        conn.commit()


def update_document_status(document_id: str, status: str, error: Optional[str] = None):
    """Update high-level document and indexing status."""
    with get_db() as conn:
        if status == "indexed":
            conn.execute(
                "UPDATE documents SET status = ?, embedding_status = 'embedded', qdrant_status = 'indexed', error = ? WHERE id = ?",
                (status, error, document_id),
            )
        else:
            conn.execute(
                "UPDATE documents SET status = ?, error = COALESCE(?, error) WHERE id = ?",
                (status, error, document_id),
            )
        conn.commit()


def update_document_chunking(document_id: str, chunk_count: int | Dict[str, Any]):
    """Update chunking state; accepts the old integer or newer state dictionary."""
    if isinstance(chunk_count, dict):
        values = dict(chunk_count)
        count = int(values.get("chunk_count", 0))
        status = str(values.get("chunking_status", "chunked"))
        error = values.get("chunking_error")
        chunked_at = values.get("chunked_at")
    else:
        count = int(chunk_count)
        status, error, chunked_at = "chunked", None, None
    with get_db() as conn:
        conn.execute(
            "UPDATE documents SET chunk_count = ?, chunking_status = ?, chunking_error = ?, chunked_at = COALESCE(?, chunked_at) WHERE id = ?",
            (count, status, error, chunked_at, document_id),
        )
        conn.commit()


def get_document_chunks_for_indexing(document_id: str) -> List[Dict[str, Any]]:
    """Get all chunks for a document that need indexing."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM document_chunks WHERE document_id = ? AND qdrant_status IN ('pending', 'not_started') ORDER BY chunk_index",
            (document_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


def insert_qdrant_index(chunk_id: str, point_id: str):
    """Mark a chunk as indexed in Qdrant."""
    from datetime import datetime, timezone
    with get_db() as conn:
        conn.execute(
            "UPDATE document_chunks SET qdrant_status = 'indexed', qdrant_point_id = ?, qdrant_indexed_at = ?, qdrant_error = NULL, error = NULL WHERE id = ?",
            (point_id, datetime.now(timezone.utc).isoformat(), chunk_id),
        )
        conn.commit()


def update_chunk_qdrant_status(chunk_id: str, status: str, error: Optional[str] = None):
    """Update chunk Qdrant state using both legacy and canonical error fields."""
    with get_db() as conn:
        conn.execute(
            "UPDATE document_chunks SET qdrant_status = ?, qdrant_error = ?, error = ? WHERE id = ?",
            (status, error, error, chunk_id),
        )
        conn.commit()


def get_qdrant_stats() -> Dict[str, int]:
    """Get Qdrant indexing statistics."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT qdrant_status, COUNT(*) as count FROM document_chunks GROUP BY qdrant_status")
        return {row["qdrant_status"]: row["count"] for row in cursor.fetchall()}


def get_document_qdrant_errors(document_id: str) -> List[Dict[str, Any]]:
    """Get Qdrant errors for a document."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM document_chunks WHERE document_id = ? AND qdrant_status = 'failed'",
            (document_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


def search_keyword_chunks(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Simple keyword search in chunks (fallback when Qdrant is unavailable)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT dc.*, dc.id as chunk_id, d.original_filename as filename 
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE COALESCE(dc.text, dc.content, '') LIKE ?
            ORDER BY dc.chunk_index
            LIMIT ?
            """,
            (f"%{query}%", limit)
        )
        return [dict(row) for row in cursor.fetchall()]


# Pipeline logs
def insert_pipeline_log(log: Dict[str, Any]):
    """Insert a pipeline log entry."""
    with get_db() as conn:
        columns = ", ".join(log.keys())
        placeholders = ", ".join(["?" for _ in log])
        conn.execute(
            f"INSERT INTO pipeline_logs ({columns}) VALUES ({placeholders})",
            tuple(log.values())
        )
        conn.commit()


def get_document_ids_in_kb(kb_id: str) -> List[str]:
    """Get all document IDs in a knowledge base."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM documents WHERE knowledge_base_id = ?", (kb_id,))
        return [row["id"] for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Compatibility/query helpers used by restored Part 2 modules
# ---------------------------------------------------------------------------
def get_all_rag_eval_sets() -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM rag_eval_sets ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]


def insert_chunk(chunk: Dict[str, Any]) -> bool:
    record = dict(chunk)
    if "content" not in record and "text" in record:
        record["content"] = record["text"]
    if "text" not in record and "content" in record:
        record["text"] = record["content"]
    with get_db() as conn:
        allowed = {row[1] for row in conn.execute("PRAGMA table_info(document_chunks)").fetchall()}
        filtered = {k: v for k, v in record.items() if k in allowed}
        cols = ", ".join(filtered)
        placeholders = ", ".join("?" for _ in filtered)
        cur = conn.execute(f"INSERT OR IGNORE INTO document_chunks ({cols}) VALUES ({placeholders})", tuple(filtered.values()))
        conn.commit()
        return cur.rowcount > 0


def insert_document_section(section: Dict[str, Any]) -> bool:
    record = dict(section)
    with get_db() as conn:
        allowed = {row[1] for row in conn.execute("PRAGMA table_info(document_sections)").fetchall()}
        filtered = {k: v for k, v in record.items() if k in allowed}
        cols = ", ".join(filtered)
        placeholders = ", ".join("?" for _ in filtered)
        cur = conn.execute(f"INSERT OR IGNORE INTO document_sections ({cols}) VALUES ({placeholders})", tuple(filtered.values()))
        conn.commit()
        return cur.rowcount > 0


def get_document_sections_db(document_id: str) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM document_sections WHERE document_id = ? ORDER BY section_index", (document_id,)).fetchall()
        return [dict(row) for row in rows]


def delete_document_sections(document_id: str) -> int:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM document_sections WHERE document_id = ?", (document_id,))
        conn.commit()
        return cur.rowcount


def delete_document_chunks_by_strategy(document_id: str, strategy: str) -> int:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM document_chunks WHERE document_id = ? AND COALESCE(chunking_strategy, 'basic') = ?", (document_id, strategy))
        conn.commit()
        return cur.rowcount
