import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import assist, auth, calendars, chat, notifications, plan, projects, tasks
from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Clovio API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    # Local development on any port (Vite moves to the next free one).
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["health"])
def health():
    return {"ok": True}


for module in (auth, projects, tasks, plan, assist, notifications, calendars, chat):
    app.include_router(module.router)
