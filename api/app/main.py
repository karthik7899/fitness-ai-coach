import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import REPO_ROOT
from app.routers import coach, metrics, sync, training
from app.scheduler import create_scheduler

WEB_DIST = REPO_ROOT / "web" / "dist"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    scheduler = create_scheduler()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Aura",
    description="Personal training data warehouse and coach",
    lifespan=lifespan,
)

# The Vite dev server is the only browser origin; everything runs on loopback.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(training.router)
app.include_router(metrics.router)
app.include_router(coach.router)
app.include_router(sync.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# Serve the built frontend when it exists, so the whole app is one process on one
# port and needs no Node at runtime — which is what makes running it entirely on a
# phone practical. Mounted last so the API routes above still win.
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
