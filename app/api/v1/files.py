from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.auth import PrincipalDependency, WriterDependency
from app.api.dependencies import SessionDependency
from app.models.artifact import ArtifactResponse
from app.services.files import FileService

router = APIRouter(prefix="/files", tags=["files"])


@router.post("", response_model=ArtifactResponse, status_code=201)
async def upload_file(
    file: UploadFile, request: Request, session: SessionDependency, principal: WriterDependency
) -> ArtifactResponse:
    service = FileService(session, request.app.state.settings, request.app.state.artifact_storage)
    record = await service.upload(file, owner_id=principal.user_id, company_id=principal.company_id)
    return ArtifactResponse.model_validate(record)


@router.delete("/{artifact_id}", status_code=200)
async def delete_file(
    artifact_id: str, request: Request, session: SessionDependency, principal: WriterDependency
) -> dict[str, object]:
    """ART-006: deletes the source, derived chunks, embeddings and the file."""
    service = FileService(session, request.app.state.settings, request.app.state.artifact_storage)
    removed_chunks = await service.delete(
        artifact_id, owner_id=principal.user_id, company_id=principal.company_id
    )
    return {"deleted": artifact_id, "removed_chunks": removed_chunks}


@router.get("/{artifact_id}")
async def download_file(
    artifact_id: str, request: Request, session: SessionDependency, principal: PrincipalDependency
) -> FileResponse:
    service = FileService(session, request.app.state.settings, request.app.state.artifact_storage)
    record, path = await service.get(
        artifact_id, owner_id=principal.user_id, company_id=principal.company_id
    )
    return FileResponse(
        path,
        media_type=record.mime_type,
        filename=record.filename,
        headers={"X-Content-Type-Options": "nosniff"},
    )
