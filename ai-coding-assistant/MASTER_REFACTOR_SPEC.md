# MASTER REFACTOR SPEC

## Product Goal
Transform the application from a collection of tools and maintenance pages into an AI-first engineering workspace.
Users should focus on outcomes, not internal system operations.

---
## Final Navigation
- Dashboard
- Projects
- Agent Workspace
- Knowledge
- Quality Center
- History
- Settings
Optional: Developer Tools

---
## Agent Workspace
Merge:
- Task Planner
- Coding Agent
- Code Reviewer
- Apply Changes
- Test Planner
- Test Generator

Workflow:
Request → Planning → Generation → Review → Testing → Approval → Apply

---
## Knowledge
Keep:
- RAG Chat
- Knowledge Search
- Knowledge Bases
- Documents

Move to background automation:
- OCR
- Ingestion Queue
- Section Chunking
- Codebase Index

---
## Quality Center
Merge:
- Architecture
- Impact Analysis
- Project Auditor
- Audit Fixes
- Coverage
- Regression
- Performance

---
## History
Merge:
- Run History
- Change Timeline
- Restore Points
- Backups

---
## Backend Services
Convert these into autonomous services:
- OCR
- Chunking
- Indexing
- RAG Evaluation
- Knowledge Gap Detection
- Regression Detection
- Backups
- Restore Points
- Health Monitoring

---
## Rules
- Never expose backend pipeline stages as major navigation items.
- Prefer automation over manual operation.
- Preserve existing functionality during migration.
- Do not delete features before replacements exist.
- Use notifications, status cards, and timelines instead of dedicated pages whenever possible.

---
# PHASES & PROMPTS

## PHASE 1 — Navigation Cleanup

### Prompt 1
Read the MASTER REFACTOR SPEC first. Analyze the entire application.
Return:
1. Current route structure
2. Current sidebar structure
3. Pages that should be merged
4. Pages that should become backend services
5. Potential risks
Do not modify any code yet. Create a migration plan only.

### Prompt 2
Read the MASTER REFACTOR SPEC first. Implement the new sidebar navigation.
Target navigation: Dashboard, Projects, Agent Workspace, Knowledge, Quality Center, History, Settings. Optional: Developer Tools.
Do not delete existing routes. Do not modify backend code. Only reorganize navigation and route grouping.

### Prompt 3
Read the MASTER REFACTOR SPEC first. Create placeholder container pages: Agent Workspace, Quality Center, History.
Move existing page links into these new containers. Preserve existing functionality. Do not remove old pages yet.

---
## PHASE 2 — Backend Automation Foundation

### Prompt 4
Read the MASTER REFACTOR SPEC first. Implement a lightweight background jobs infrastructure.
Create: Job model, Job service, Job status tracking
Fields: id, type, status, payload, result, error, retry_count, created_at, started_at, completed_at
Statuses: queued, running, succeeded, failed
Do not add frontend pages.

### Prompt 5
Read the MASTER REFACTOR SPEC first. Implement an internal event system.
Support: document.uploaded, document.updated, codebase.changed, changes.applied
Allow events to enqueue background jobs. Keep implementation simple and backend-only. Do not modify UI.

### Prompt 6
Read the MASTER REFACTOR SPEC first. Implement automated jobs for: OCR, document ingestion, chunking, codebase indexing.
Trigger automatically when documents or code change. Keep existing UI functional. Do not remove pages yet.

---
## PHASE 3 — Remove Operational Pages

### Prompt 7
Read the MASTER REFACTOR SPEC first. Create dashboard status cards for: indexing status, document processing, background jobs, system health.
Create notification support for failures. Do not create standalone pages.

### Prompt 8
Read the MASTER REFACTOR SPEC first. Migrate the following pages into backend automation: OCR, Ingestion Queue, Section Chunking, Codebase Index, RAG Evaluation, Knowledge Gaps, Regression, Backups, Restore Points.
Replace them with: status cards, alerts, timeline entries, automation settings.
After confirming replacement functionality exists, remove obsolete routes and navigation entries. Provide a final migration report.

## Part 9 completed — production scheduler hardening

The dry-run scheduler now includes signed/replay-protected evidence, CI identity binding, operator audit identity, environment-specific gates, monotonic fenced leases, simulation, persisted alerts, telemetry and Prometheus metrics. These controls harden observe/propose scheduling only; scheduled and automatic source apply remain disabled.

Next: deployment adapters and operational resilience (external alert sinks, optional OpenTelemetry exporters, HA database/lease backends, Git provider provenance adapters, retention/disaster-recovery exercises). Do not enable unattended source promotion as an implicit follow-on.
