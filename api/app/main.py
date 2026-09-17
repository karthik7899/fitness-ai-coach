from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import coach, metrics, sync, training

app = FastAPI(title="Aura", description="Personal training data warehouse and coach")

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
