from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import vector_store
from .routers import documents, query, summary, upload

app = FastAPI(title="Construction RAG API", version="0.1.0")

# Phase 4: React dev server (Vite default port) needs cross-origin access.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(documents.router)
app.include_router(query.router)
app.include_router(summary.router)


@app.on_event("startup")
def on_startup():
    vector_store.init_db()


@app.get("/health")
def health():
    return {"status": "ok"}
