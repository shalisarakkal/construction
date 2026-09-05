from fastapi import APIRouter

from .. import llm, vector_store
from ..config import settings
from ..embeddings import embed_query
from ..schemas import ChunkRecord, QueryRequest, QueryResponse, RetrievedChunk


def build_context_block(results: list[tuple[dict, str, float]]) -> str:
    """Matches dream.md section 4 context-assembly format:
    [Chunk N — Doc: <title>, <citation or page>]"""
    parts = []
    for chunk, doc_title, _score in results:
        locator = chunk.get("citation") or f"Page {chunk.get('page_number')}"
        parts.append(f"[Doc: {doc_title}, {locator}]\n{chunk['text']}")
    return "\n\n".join(parts)


router = APIRouter()


@router.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    top_k = request.top_k or settings.default_top_k
    query_vector = embed_query(request.question)
    results = vector_store.search(query_vector, top_k, doc_ids=request.doc_ids)

    citations = []
    for chunk, doc_title, _score in results:
        locator = chunk.get("citation") or f"page {chunk.get('page_number')}"
        citations.append(f"{doc_title} — {locator}")

    confidence = results[0][2] if results else 0.0

    answer = None
    llm_used = False
    if results and llm.is_configured():
        context_block = build_context_block(results)
        answer = llm.synthesize_answer(request.question, context_block)
        llm_used = True

    return QueryResponse(
        question=request.question,
        answer=answer,
        citations=citations,
        confidence=confidence,
        llm_used=llm_used,
        chunks=[
            RetrievedChunk(chunk=ChunkRecord(**chunk), doc_title=doc_title, score=score)
            for chunk, doc_title, score in results
        ],
    )
