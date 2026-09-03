import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from app import vector_store
from app.config import settings
from app.main import app


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    """Points storage_dir at a per-test tmp_path so tests never touch the
    real dev database/FAISS index, then boots a fresh SQLite schema + empty
    FAISS index for that path. Use this directly (without `client`) for
    tests that call vector_store/ingestion functions without going through
    the HTTP layer."""
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    settings.documents_dir.mkdir(parents=True, exist_ok=True)
    settings.index_dir.mkdir(parents=True, exist_ok=True)
    vector_store.init_db()


@pytest.fixture
def client(isolated_storage):
    with TestClient(app) as test_client:
        yield test_client
