"""Application entry point: FastAPI app factory, startup pipeline, and route registration."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

PROJECT_ROOT = Path(__file__).parent.absolute()
load_dotenv(PROJECT_ROOT.parent / ".env")

from src.config.settings import (
    APP_NAME,
    APP_VERSION,
    DEBUG,
    API_HOST,
    API_PORT,
    RELOAD,
    CORS_ORIGINS,
    validate_settings,
)
from src.config.database import connect_db, close_db, get_db
from src.middleware.logging_middleware import LoggingMiddleware
from src.middleware.error_middleware import ErrorHandlerMiddleware
from src.middleware.request_context import RequestContextMiddleware
from src.middleware.security_headers import SecurityHeadersMiddleware
from src.observability import setup_tracing
from src.utils.logger import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

validate_settings()


class StartupPipeline:
    """Initializes RAG, agent, and question systems before the API accepts traffic."""

    def __init__(self):
        self.rag_initialized = False
        self.agent_initialized = False
        self.documents_processed = 0
        self.chunks_created = 0
        self.errors: list[str] = []

    async def initialize_rag(self) -> bool:
        data_path = PROJECT_ROOT.parent / "data" / "raw"
        if not data_path.exists() or not any(data_path.iterdir()):
            logger.warning("No documents found in data/raw — RAG features disabled")
            return False

        try:
            from src.services.rag import initialize_rag, get_rag_status

            await asyncio.to_thread(initialize_rag, False)
            self.rag_initialized = True

            metrics = get_rag_status().get("metrics", {})
            self.documents_processed = metrics.get("total_documents", 0)
            self.chunks_created = metrics.get("total_chunks", 0)
            logger.info(
                "RAG ready: %s documents, %s chunks",
                self.documents_processed,
                self.chunks_created,
            )
            return True
        except Exception as e:
            logger.exception("RAG initialization failed")
            self.errors.append(f"RAG: {e}")
            return False

    async def initialize_agent(self) -> bool:
        try:
            from src.services.agent import initialize_agent

            await asyncio.to_thread(initialize_agent, False, None)
            self.agent_initialized = True
            logger.info("Agent graph compiled")
            return True
        except Exception as e:
            logger.exception("Agent initialization failed")
            self.errors.append(f"Agent: {e}")
            return False

    async def initialize_questions(self) -> bool:
        """Seed the question queue. Non-critical: failures are logged, not fatal."""
        try:
            from src.services.question_manager import initialize_question_file

            count = await initialize_question_file(get_db())
            logger.info("Question queue initialized with %s questions", count)
        except Exception as e:
            logger.warning("Question queue initialization skipped: %s", e)
        return True

    async def run(self) -> bool:
        rag_ok = await self.initialize_rag()
        agent_ok = await self.initialize_agent()
        await self.initialize_questions()

        if self.errors:
            for error in self.errors:
                logger.warning("Startup issue: %s", error)

        overall = rag_ok and agent_ok
        logger.info(
            "Startup complete — RAG: %s | Agent: %s",
            "ready" if rag_ok else "unavailable",
            "ready" if agent_ok else "unavailable",
        )
        return overall


pipeline = StartupPipeline()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s (debug=%s)", APP_NAME, APP_VERSION, DEBUG)

    await connect_db()

    try:
        from src.services.chat_manager import ensure_indexes as ensure_chat_indexes

        await ensure_chat_indexes(get_db())
        db = get_db()
        await db["user_n8n_credentials"].create_index("user_id", unique=True)
        await db["user_n8n_workflows"].create_index([("user_id", 1), ("workflow_key", 1)], unique=True)
        logger.info("Chat + n8n indexes ready")
    except Exception as e:
        logger.warning("Chat/n8n index setup skipped: %s", e)

    app.state.pipeline_status = await pipeline.run()
    app.state.rag_ready = pipeline.rag_initialized
    app.state.agent_ready = pipeline.agent_initialized

    yield

    await close_db()
    logger.info("Shutdown complete")


async def initialize_rag(force_reindex: bool = False):
    """Initialize RAG with auto-build capability"""
    try:
        if os.getenv("AUTO_BUILD_RAG", "true").lower() == "true":
            from src.services.rag.auto_build import ensure_index_exists
            success = await asyncio.to_thread(
                ensure_index_exists,
                force_rebuild=force_reindex,
                rebuild_on_empty=True,
                max_retries=3
            )
            
            if success:
                from src.services.rag.engine import initialize_rag as init_rag
                init_rag(force_reindex=False)
            else:
                logger.error("❌ RAG could not be initialized")
        else:
            from src.services.rag.engine import initialize_rag as init_rag
            init_rag(force_reindex=force_reindex)
            
    except Exception as e:
        logger.error(f"❌ RAG initialization failed: {e}")
        raise

def create_app() -> FastAPI:
    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        description="Multi-agent Economic & Investment Advisor with RAG",
        lifespan=lifespan,
        docs_url="/docs" if DEBUG else None,
        openapi_url="/openapi.json" if DEBUG else None,
    )

    setup_tracing(app)

    app.add_middleware(ErrorHandlerMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=not DEBUG)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if DEBUG else CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(RequestContextMiddleware)

    from src.routes.agent import router as agent_router
    from src.routes.agent.webhook import router as webhook_router
    from src.routes.user import router as user_router
    from src.routes.auth_routes import router as auth_router
    from src.routes.email_routes import router as email_router
    from src.routes.question_router import router as question_router
    from src.routes.history_routes import router as history_router
    from src.routes.health_routes import router as health_router
    from src.routes.chat_routes import router as chat_router
    from src.routes.n8n_routes import router as n8n_router
    from src.routes.webhook_user import router as webhook_user_router

    app.include_router(agent_router, prefix="/api/v1")
    app.include_router(webhook_router)
    app.include_router(webhook_user_router)
    app.include_router(user_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(email_router, prefix="/api/v1")
    app.include_router(question_router, prefix="/api/v1")
    app.include_router(history_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(n8n_router, prefix="/api/v1")

    @app.get("/", tags=["root"])
    async def root():
        return {
            "name": APP_NAME,
            "version": APP_VERSION,
            "status": "running",
            "pipeline_status": {
                "ready": getattr(app.state, "pipeline_status", False),
                "rag": getattr(app.state, "rag_ready", False),
                "agent": getattr(app.state, "agent_ready", False),
                "documents_processed": pipeline.documents_processed,
                "chunks_created": pipeline.chunks_created,
            },
        }

    @app.get("/health", tags=["health"])
    async def health():
        ready = getattr(app.state, "pipeline_status", False)
        return {
            "status": "healthy" if ready else "degraded",
            "app": APP_NAME,
            "version": APP_VERSION,
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=RELOAD,
        log_level="debug" if DEBUG else "info",
    )
