from typing import Literal

from pydantic import BaseModel


class ChunkRecord(BaseModel):
    chunk_id: str
    doc_id: str
    chunk_type: Literal["njac_section", "njac_history", "generic"]
    citation: str | None = None
    section_title: str | None = None
    page_number: int | None = None
    text: str
    word_count: int
    references: list[str] = []


class DocumentSummary(BaseModel):
    doc_id: str
    title: str
    filename: str
    chunker_used: str
    chunk_count: int
    created_at: str
    is_latest: bool = True
    supersedes_doc_id: str | None = None


class UploadResponse(BaseModel):
    doc_id: str
    title: str
    filename: str
    chunker_used: str
    chunk_count: int
    ocr_used: bool = False
    supersedes_doc_id: str | None = None


class UploadAcceptedResponse(BaseModel):
    job_id: str
    status: Literal["queued"]
    filename: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "processing", "done", "error"]
    filename: str
    result: UploadResponse | None = None
    error: str | None = None


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5


class RetrievedChunk(BaseModel):
    chunk: ChunkRecord
    doc_title: str
    score: float


class QueryResponse(BaseModel):
    question: str
    answer: str | None
    citations: list[str]
    confidence: float
    llm_used: bool
    chunks: list[RetrievedChunk]


class DocumentSummaryResponse(BaseModel):
    doc_id: str
    title: str
    summary: str
    chunks_used: int
    chunks_total: int
    truncated: bool
