from fastapi import APIRouter, HTTPException

from .. import llm, vector_store
from ..config import settings
from ..schemas import DocumentSummaryResponse

router = APIRouter()

# Whole-document context passed to a single LLM call; large NJAC subchapters
# (e.g. njac_5_23_6.pdf, 406 chunks) exceed a sane single-call budget, so
# chunks are included in order up to this word cap and the response reports
# whether it was truncated -- see docs/AllDevFlow.md Phase 4 notes.
MAX_SUMMARY_WORDS = 6000


@router.post("/documents/{doc_id}/summary", response_model=DocumentSummaryResponse)
def summarize_document(doc_id: str):
    if not llm.is_configured():
        raise HTTPException(
            status_code=503,
            detail=f"Summary generation requires the '{settings.llm_provider}' LLM provider "
                   "to be configured and reachable",
        )

    chunks = vector_store.get_document_chunks(doc_id)
    if not chunks:
        raise HTTPException(status_code=404, detail="Document not found or has no chunks")

    docs = {d["doc_id"]: d for d in vector_store.list_documents()}
    title = docs.get(doc_id, {}).get("title", doc_id)

    used = []
    word_total = 0
    for chunk in chunks:
        words = chunk["word_count"]
        if used and word_total + words > MAX_SUMMARY_WORDS:
            break
        used.append(chunk)
        word_total += words

    context_block = "\n\n".join(c["text"] for c in used)
    summary_text = llm.synthesize_summary(title, context_block)

    return DocumentSummaryResponse(
        doc_id=doc_id,
        title=title,
        summary=summary_text,
        chunks_used=len(used),
        chunks_total=len(chunks),
        truncated=len(used) < len(chunks),
    )
