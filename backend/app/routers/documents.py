from fastapi import APIRouter, HTTPException, Response

from .. import ingestion, vector_store
from ..schemas import ChunkRecord, DocumentSummary

router = APIRouter()


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(include_all: bool = False):
    return [DocumentSummary(**d) for d in vector_store.list_documents(include_all=include_all)]


@router.get("/documents/{doc_id}/versions", response_model=list[DocumentSummary])
def get_document_versions(doc_id: str):
    versions = vector_store.get_document_versions(doc_id)
    if not versions:
        raise HTTPException(status_code=404, detail="Document not found")
    doc_ids = [v["doc_id"] for v in versions]
    counts = {d["doc_id"]: d["chunk_count"] for d in vector_store.list_documents(include_all=True)}
    return [DocumentSummary(**v, chunk_count=counts.get(v["doc_id"], 0)) for v in versions]


@router.get("/documents/{doc_id}/chunks", response_model=list[ChunkRecord])
def get_document_chunks(doc_id: str):
    chunks = vector_store.get_document_chunks(doc_id)
    if not chunks:
        raise HTTPException(status_code=404, detail="Document not found or has no chunks")
    return [ChunkRecord(**c) for c in chunks]


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str):
    if not ingestion.delete_document(doc_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(status_code=204)
