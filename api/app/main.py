import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import REPO_ROOT
from app.routers import backup, coach, metrics, settings, sync, training
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
app.include_router(settings.router)
app.include_router(backup.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# Serve the built frontend when it exists, so the whole app is one process on one
# port and needs no Node at runtime — which is what makes running it entirely on a
# phone practical. Mounted last so the API routes above still win.
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
else:
    # Without this the app tells you to open a page it is not serving, and the
    # browser shows a bare 404 that says nothing about why. The server is fine;
    # it is the frontend that was never built. Say so, on the page the user was
    # told to open.
    @app.get("/{path:path}", response_class=HTMLResponse, include_in_schema=False)
    def no_frontend(path: str) -> HTMLResponse:
        return HTMLResponse(status_code=503, content=UNBUILT_PAGE)


UNBUILT_PAGE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aura — frontend not built</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; padding: 24px 16px; background: #0f1115; color: #e6e8ec;
         font: 16px/1.55 system-ui, -apple-system, sans-serif; }
  main { max-width: 34rem; margin: 0 auto; }
  h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
  p { color: #8b93a3; }
  code, pre { background: #171a21; border: 1px solid #262b36; border-radius: 6px; }
  code { padding: .1rem .35rem; font-size: .9em; }
  pre { padding: 12px; overflow-x: auto; margin: .75rem 0 1.25rem; }
  .ok { color: #0ca30c; }
  a { color: #5b9cff; }
</style>
</head>
<body>
<main>
  <h1>The server is running<span class="ok"> ✓</span></h1>
  <p>What is missing is the web interface: <code>web/dist</code> does not exist,
     so there is nothing to serve here. Your data is untouched.</p>

  <h2>Build it on the phone</h2>
  <pre>cd ~/fitness-ai-coach/web
npm install
npm run build</pre>

  <h2>Or download it, and skip Node entirely</h2>
  <p>Every push builds it. Open the repository&rsquo;s <b>Actions</b> tab, pick the
     newest <b>Web</b> run, download the <b>web-dist</b> artifact, and unzip it
     into <code>web/dist</code>.</p>

  <p>Then restart with <code>./scripts/start.sh</code> and reload this page.</p>
  <p>The API itself is up: <a href="/api/health">/api/health</a> ·
     <a href="/docs">/docs</a></p>
</main>
</body>
</html>
"""
