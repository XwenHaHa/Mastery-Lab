"""课程素材接口（P1.6-G）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ...core.response import ApiResponse, AppError, success
from ...services import material_library
from ...services.materials import MaterialError
from ..deps import db_session

router = APIRouter(tags=["materials"])


def _rethrow(exc: MaterialError) -> AppError:
    return AppError(exc.message, code=exc.code, status_code=exc.status_code)


@router.post(
    "/courses/{course_id}/materials",
    response_model=ApiResponse[dict],
    status_code=status.HTTP_201_CREATED,
    summary="上传课程素材（图片/音频/视频）",
)
async def upload_asset(
    course_id: int,
    file: UploadFile = File(..., description="PNG/JPEG/GIF/WebP、MP3/WAV/OGG/M4A、MP4/WebM"),
    caption: str = Form(default="", max_length=2000),
    session: Session = Depends(db_session),
) -> ApiResponse:
    try:
        material = await material_library.save_asset(
            session, course_id=course_id, upload=file, caption=caption
        )
    except MaterialError as exc:
        raise _rethrow(exc) from exc
    return success(material_library.payload(material), message="素材已上传")


@router.get(
    "/courses/{course_id}/materials",
    response_model=ApiResponse[list[dict]],
    summary="课程素材列表",
)
def list_assets(course_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    return success([material_library.payload(item) for item in material_library.list_assets(session, course_id)])


@router.get("/materials/{material_id}", response_model=ApiResponse[dict], summary="素材元数据")
def get_asset(material_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    try:
        material = material_library.get_asset(session, material_id)
    except MaterialError as exc:
        raise _rethrow(exc) from exc
    return success(material_library.payload(material))


@router.get("/materials/{material_id}/content", summary="读取素材文件（仅允许站内引用）")
def asset_content(material_id: int, session: Session = Depends(db_session)) -> FileResponse:
    try:
        material = material_library.get_asset(session, material_id)
        path = material_library.absolute_path(material.relative_path)
    except MaterialError as exc:
        raise _rethrow(exc) from exc
    return FileResponse(
        path,
        media_type=material.mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{material.id}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete("/materials/{material_id}", response_model=ApiResponse[None], summary="删除素材")
def delete_asset(material_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    try:
        material_library.delete_asset(session, material_id)
    except MaterialError as exc:
        raise _rethrow(exc) from exc
    return success(message="素材已删除")
