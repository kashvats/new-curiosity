"""
Main FastAPI application entry point.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings, ensure_directories
from app.database import init_database
from app.job_service import job_worker_loop

# Strong references to background tasks.
# asyncio.create_task() alone is NOT enough — the GC can silently kill a task
# if nothing holds a reference to it. This set guarantees survival.
_background_tasks: set = set()

# Configure logging
logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting AI Coding Assistant backend...")
    
    # Ensure directories exist
    ensure_directories()
    
    # Initialize database
    init_database()
    logger.info("Database initialized")
    
    # Start background job worker with a strong reference to prevent GC from killing it
    job_task = asyncio.create_task(job_worker_loop())
    _background_tasks.add(job_task)
    job_task.add_done_callback(_background_tasks.discard)
    logger.info("Background job worker started")

    # Part 8 dry-run improvement scheduler. Disabled by default and incapable of
    # automatic source promotion; when enabled it launches observe-only cycles.
    scheduler_task = None
    if settings.IMPROVEMENT_DRY_RUN_SCHEDULER_ENABLED:
        try:
            from app.improvement_scheduler import scheduler_worker_loop
            scheduler_task = asyncio.create_task(scheduler_worker_loop())
            _background_tasks.add(scheduler_task)
            scheduler_task.add_done_callback(_background_tasks.discard)
            logger.info("Dry-run improvement scheduler started (observe/propose only)")
        except Exception as e:
            logger.warning(f"Could not start dry-run improvement scheduler: {e}")
    
    # Start background file watcher
    try:
        from app.watcher import project_watcher
        asyncio.get_running_loop().run_in_executor(None, project_watcher.start)
    except Exception as e:
        logger.warning(f"Could not start project watcher: {e}")
    
    # Import and register job handlers
    try:
        from app import job_handlers
        logger.info("Job handlers registered")
    except ImportError as e:
        logger.warning(f"Could not import job handlers: {e}")

    # Verify FAST_MODEL is available in Ollama to prevent silent map phase failures
    try:
        import httpx
        ollama_url = getattr(settings, "OLLAMA_BASE_URL", "http://host.docker.internal:11434")
        fast_model = getattr(settings, "FAST_MODEL", "qwen2.5:0.5b")
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{ollama_url.rstrip('/')}/api/tags")
            if resp.status_code == 200:
                available = [m["name"] for m in resp.json().get("models", [])]
                if not any(fast_model in m for m in available):
                    logger.warning(
                        f"[Startup] FAST_MODEL '{fast_model}' not found in Ollama. "
                        f"Architecture map phase will fail silently. Run: ollama pull {fast_model}"
                    )
                else:
                    logger.info(f"[Startup] FAST_MODEL '{fast_model}' verified OK.")
    except Exception as e:
        logger.warning(f"[Startup] Could not verify Ollama model availability: {e}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    
    try:
        from app.watcher import project_watcher
        project_watcher.stop()
    except Exception:
        pass
        
    job_task.cancel()
    try:
        await job_task
    except asyncio.CancelledError:
        pass

    if scheduler_task is not None:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
    
    try:
        from app.model_manager import model_manager
        await model_manager.aclose()
    except Exception:
        pass


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="Backend API for AI-powered coding assistant",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "ok", "service": settings.APP_NAME}


@app.get("/health/live")
async def health_live():
    from app.improvement_scheduler_health import liveness_probe
    return liveness_probe()


@app.get("/health/ready")
async def health_ready():
    from app.improvement_scheduler_health import readiness_probe
    result = readiness_probe()
    return JSONResponse(status_code=200 if result.get("ready") else 503, content=result)

@app.get("/qdrant/health")
async def qdrant_health_check():
    from app.qdrant_store import get_client
    try:
        client = get_client()
        client.get_collections()
        return {"status": "ok", "qdrant_url": f"http://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/")
async def root():
    return {
        "message": "AI Coding Assistant API",
        "version": "1.0.0",
        "docs": "/docs"
    }


# Import and include routers
try:
    from app.dashboard import router as dashboard_router
    app.include_router(dashboard_router)
    logger.info("Dashboard router registered")
except ImportError as e:
    logger.warning(f"Could not import dashboard router: {e}")

try:
    from app.tools import router as tools_router
    app.include_router(tools_router)
    logger.info("Tools router registered")
except ImportError as e:
    logger.warning(f"Could not import tools router: {e}")




try:
    from app.test_planner import router as test_planner_router
    app.include_router(test_planner_router)
    logger.info("Test planner router registered")
except ImportError as e:
    logger.warning(f"Could not import test planner router: {e}")

try:
    from app.test_generator import router as test_generator_router
    app.include_router(test_generator_router)
    logger.info("Test generator router registered")
except ImportError as e:
    logger.warning(f"Could not import test generator router: {e}")

try:
    from app.test_runner import router as test_runner_router
    app.include_router(test_runner_router)
    logger.info("Test runner router registered")
except ImportError as e:
    logger.warning(f"Could not import test runner router: {e}")



try:
    from app.projects import router as projects_router
    app.include_router(projects_router)
    logger.info("Projects router registered")
except ImportError as e:
    logger.warning(f"Could not import projects router: {e}")

try:
    from app.settings_portability import router as settings_router
    app.include_router(settings_router)
    logger.info("Settings router registered")
except ImportError as e:
    logger.warning(f"Could not import settings router: {e}")

try:
    from app.storage import router as storage_router
    app.include_router(storage_router)
    logger.info("Storage router registered")
except ImportError as e:
    logger.warning(f"Could not import storage router: {e}")

try:
    from app.models_api import router as models_router
    app.include_router(models_router)
    logger.info("Models router registered")
except ImportError as e:
    logger.warning(f"Could not import models router: {e}")

try:
    from app.memory_api import router as memory_router
    app.include_router(memory_router)
    logger.info("Memory router registered")
except ImportError as e:
    logger.warning(f"Could not import memory router: {e}")

try:
    from app.architecture_api import router as architecture_router
    app.include_router(architecture_router)
    logger.info("Architecture router registered")
except ImportError as e:
    logger.warning(f"Could not import architecture router: {e}")

try:
    from app.impact_api import router as impact_router
    app.include_router(impact_router)
    logger.info("Impact router registered")
except ImportError as e:
    logger.warning(f"Could not import impact router: {e}")


try:
    from app.search import router as search_router
    app.include_router(search_router)
    logger.info("Document search router registered")
except ImportError as e:
    logger.warning(f"Could not import document search router: {e}")

try:
    from app.agents_api import router as agents_router
    app.include_router(agents_router)
    logger.info("Agents router registered")
except ImportError as e:
    logger.warning(f"Could not import agents router: {e}")

try:
    from app.ide_api import router as ide_router
    app.include_router(ide_router)
    logger.info("IDE router registered")
except ImportError as e:
    logger.warning(f"Could not import IDE router: {e}")

try:
    from app.improvement_api import router as improvement_router
    app.include_router(improvement_router)
    logger.info("Improvement controller router registered")
except ImportError as e:
    logger.warning(f"Could not import improvement controller router: {e}")

try:
    from app.improvement_scheduler_api import router as improvement_scheduler_router
    app.include_router(improvement_scheduler_router)
    logger.info("Dry-run improvement scheduler router registered")
except ImportError as e:
    logger.warning(f"Could not import dry-run improvement scheduler router: {e}")

try:
    from app.improvement_release_api import router as improvement_release_router
    app.include_router(improvement_release_router)
    logger.info("Candidate-to-staging release router registered")
except ImportError as e:
    logger.warning(f"Could not import candidate-to-staging release router: {e}")

try:
    from app.improvement_staging_api import router as improvement_staging_router
    app.include_router(improvement_staging_router)
    logger.info("Staging provider and release-handoff router registered")
except ImportError as e:
    logger.warning(f"Could not import staging provider router: {e}")

try:
    from app.improvement_production_governance_api import router as production_governance_router
    app.include_router(production_governance_router)

    from app.improvement_production_feedback_api import router as production_feedback_router
    app.include_router(production_feedback_router)
    logger.info("Production release governance router registered")
except ImportError as e:
    logger.warning(f"Could not import production governance router: {e}")

try:
    from app.improvement_certification_api import router as production_certification_router
    app.include_router(production_certification_router)
    logger.info("Production readiness certification router registered")
except ImportError as e:
    logger.warning(f"Could not import production certification router: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
