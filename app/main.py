"""FastAPI application entrypoint for the agent conversation session API."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from app.api.routes.sessions import sessions_router

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(sessions_router)
