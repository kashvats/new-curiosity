# AI Coding Assistant

A powerful, autonomous, agentic AI coding assistant designed to help you analyze codebases, draft modifications, review changes, and safely apply them. Built with a FastAPI backend and a React dashboard frontend.

## Project Overview
This project contains a comprehensive suite of AI-driven tools integrating:
- **Local RAG Knowledge Base**: Upload PDFs, chunk, embed, and index them into Qdrant for semantic search.
- **Planner Agent**: Analyzes your tasks and researches local RAG knowledge to formulate an actionable plan.
- **Coding Agent**: Automatically drafts the code modifications (in secure JSON format) required to complete the task.
- **Review & Apply Engine**: Provides manual/automated review gates before writing the code to disk. Safely backups the existing file using `.bak` format.
- **Web Search**: Integrates with SearXNG to look up information beyond local context.
- **Browser Control**: Secure, headless browser navigation via Playwright for fetching pages and taking screenshots.

## Prerequisites & Hardware Recommendation
- **Hardware**: We recommend at least an 8-core CPU with 16GB+ RAM to run local LLMs comfortably. A discrete GPU is heavily recommended for faster model inference.
- **Required Tools**:
  1. **Docker Desktop** (Make sure it is running on your host).
  2. **Ollama** (Install natively on the Windows host).
  
### Ollama Setup
Ensure Ollama is running natively on your host machine. Pull the following models:
```bash
ollama run qwen2.5-coder:7b
ollama run nomic-embed-text
ollama run qwen3:4b
```

## How to Start
1. Ensure Docker Desktop is running.
2. In the root of the project, run:
```bash
docker compose up --build
```
3. Once running, access the services at:
- **Frontend Dashboard**: [http://localhost:3000](http://localhost:3000)
- **Backend API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Qdrant Vector DB**: [http://localhost:6333](http://localhost:6333)

## Environment Variables
Copy `backend/.env.example` to `backend/.env` to customize settings. Critical variables:
- `OLLAMA_BASE_URL`: Should be `http://host.docker.internal:11434` when running in Docker.
- `WORKSPACE_ROOT`: Path to the local workspace you want the AI to modify.
- `BACKUP_DIR`: Directory where `.bak` files are saved before applying changes.
- `BROWSER_SCREENSHOT_DIR`: Directory where playwright saves headless screenshots.

## Full 12-Step Autonomous Workflow
1. **Upload PDF**: Upload architectural documents or manuals to the `/data/uploads` directory.
2. **Extract Text**: Parse the PDFs into raw text.
3. **Chunk**: Break text into semantically cohesive chunks.
4. **Generate Embeddings**: Run chunks through `nomic-embed-text`.
5. **Index to Qdrant**: Load the embeddings into the vector database.
6. **Search**: Manually test queries to ensure relevant chunks are returned.
7. **RAG Chat**: Chat with your local knowledge base.
8. **Plan Task**: Send a request to the Planner Agent to research and formulate a plan.
9. **Draft Code**: The Coding Agent generates safe JSON payloads detailing exactly what lines to modify.
10. **Review Code**: The Reviewer Agent audits the drafted code against safety rules.
11. **Dry-run Apply**: (Optional) Preview the unified diff.
12. **Confirm Apply**: Safely overwrite the files (the Applier always creates a `.bak` backup first!).

## Critical Safety Notes
- **RAG Execution**: The RAG chat only provides information, it does **not** execute PDF content.
- **Browser Constraints**: The Browser tool explicitly blocks dangerous URLs (e.g. `file://`, `chrome://`) to prevent path traversal, and interactive actions (clicking/typing) are strictly locked to safe internal hosts (`localhost`, `127.0.0.1`, `host.docker.internal`).
- **File Backups**: The `Apply Changes` endpoint will *never* overwrite a file without first saving a timestamped copy to the `BACKUP_DIR`.
- **Path Traversal**: All path modifications are strictly constrained to the `WORKSPACE_ROOT`.

---

## Developer Notes: How to continue development safely

If you intend to extend or modify this application:
1. **Work one phase at a time**: Do not introduce massive refactors across multiple domains simultaneously.
2. **Do not rewrite unrelated files**: Stick to the files relevant to the specific feature.
3. **When fixing a bug, only touch the file causing it**.
4. **Preserve existing API contracts**: The frontend relies heavily on the exact JSON structures currently defined.
5. **Test after every change**: Run the native test scripts inside `/scratch` before assuming a change works correctly in the main flow.
