import uuid

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from .. import ingestion, vector_store
from ..extractors import SUPPORTED_EXTENSIONS
from ..ingestion import DuplicateDocumentError
from ..schemas import JobStatusResponse, UploadAcceptedResponse

router = APIRouter()


def _run_ingest_job(job_id: str, file_bytes: bytes, filename: str, title: str | None,
                     supersedes: str | None):
    """The actual extract/chunk/embed/store pipeline, run via BackgroundTasks
    (off the request/response cycle, in FastAPI's threadpool) so a slow PDF
    doesn't block the event loop for other requests -- see ingestion.py."""
    vector_store.update_job(job_id, status="processing")
    try:
        result = ingestion.ingest_document(file_bytes, filename, title, supersedes_doc_id=supersedes)
        vector_store.update_job(job_id, status="done", result=result)
    except (DuplicateDocumentError, ValueError) as e:
        # Re-validated here in case of a race with another upload between the
        # router's synchronous precheck and this background run.
        vector_store.update_job(job_id, status="error", error=str(e))
    except Exception as e:
        vector_store.update_job(job_id, status="error", error=f"Unexpected error: {e}")


@router.post("/upload", response_model=UploadAcceptedResponse, status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    supersedes: str | None = Form(None),
):
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'. Supported: {supported}")

    file_bytes = await file.read()
    try:
        ingestion.validate_upload(file_bytes, supersedes)
    except DuplicateDocumentError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    job_id = uuid.uuid4().hex[:12]
    vector_store.create_job(job_id, file.filename)
    background_tasks.add_task(_run_ingest_job, job_id, file_bytes, file.filename, title, supersedes)

    return UploadAcceptedResponse(job_id=job_id, status="queued", filename=file.filename)


@router.get("/upload/jobs/{job_id}", response_model=JobStatusResponse)
def get_upload_job(job_id: str):
    job = vector_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(**job)
