"""One-off maintenance script: rebuilds backend/storage/index/faiss.index to
drop orphaned vectors left behind by past deletes/supersedes/schema-reset
re-ingests (see vector_store.compact_index()'s docstring for the full
rationale and safety ordering). Run with the backend stopped.

Usage:
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\compact_faiss_index.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import vector_store

if __name__ == "__main__":
    report = vector_store.compact_index()
    dropped = report["before"] - report["after"]
    print(
        f"FAISS index compacted: {report['before']} -> {report['after']} vectors "
        f"({report['chunks_remapped']} live chunks remapped, {dropped} orphaned vectors dropped)."
    )
