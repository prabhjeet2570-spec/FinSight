import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.connection import init_db, close_db
from app.routers import documents, query

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting FinSight API...")
    await init_db()
    yield
    await close_db()
    logger.info("FinSight API shut down.")


app = FastAPI(
    title="FinSight API",
    description="Financial intelligence powered by document RAG and SEC EDGAR structured data",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(documents.router)
app.include_router(query.router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "finsight-api"}
