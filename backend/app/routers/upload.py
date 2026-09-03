from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .. import ingestion
from ..extractors import SUPPORTED_EXTENSIONS
from ..ingestion import DuplicateDocumentError
from ..schemas import UploadResponse

router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
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
        result = ingestion.ingest_document(file_bytes, file.filename, title, supersedes_doc_id=supersedes)
    except DuplicateDocumentError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return UploadResponse(**result)
