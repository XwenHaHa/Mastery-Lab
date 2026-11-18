"""课程、章节、知识点与学习状态接口（P1.1 建，P1.2 补齐管理能力）。

路径分两类，指向同一批服务函数：

1. 课程内路径（P1.2 前端使用）：`/courses/{course_id}/chapters/{chapter_id}`，
   服务层会校验被操作的章节/知识点确实属于该课程，防止拿过期 ID 改到别的课程；
2. 扁平路径（P1.1 导入预览页使用，继续保留）：`/chapters/{chapter_id}`、`/knowledge-points/{point_id}`，
   路径里没有课程 ID，因此没有跨课程歧义。

所有接口沿用统一响应外壳 `{code, message, data}`。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.orm import Session

from ...core.response import ApiResponse, AppError, success
from ...schemas.course import (
    ChapterCreate,
    ChapterOut,
    ChapterReorderRequest,
    ChapterUpdate,
    CourseDetail,
    CourseProgress,
    CourseSummary,
    CourseUpdate,
    KnowledgePointCreate,
    KnowledgePointDetail,
    KnowledgePointSummary,
    KnowledgePointUpdate,
    PointReorderRequest,
    PointStatusUpdate,
    ReorderRequest,
)
from ...services import course_service
from ...services.materials import MaterialError, delete_material_files, parse_material, save_material
from ..deps import db_session

router = APIRouter(prefix="/courses", tags=["courses"])
node_router = APIRouter(tags=["courses"])


def _rethrow(exc: MaterialError) -> AppError:
    return AppError(exc.message, code=exc.code, status_code=exc.status_code)


# ------------------------------------------------------------------ 课程

@router.get("", response_model=ApiResponse[list[CourseSummary]], summary="课程列表（可搜索、可排序）")
def list_courses(
    course_status: str = Query(default="active", alias="status", pattern="^(active|draft)$"),
    q: str | None = Query(default=None, max_length=120, description="按课程名/简介/教材名搜索"),
    sort: str = Query(default="updated", pattern="^(updated|created|studied)$", description="updated=最近更新，created=创建时间，studied=最近学习"),
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(course_service.list_courses(session, status=course_status, q=q, sort=sort))


@router.post(
    "/upload",
    response_model=ApiResponse[CourseDetail],
    status_code=status.HTTP_201_CREATED,
    summary="上传教材并解析为课程草稿（需要用户确认才创建正式课程）",
)
async def upload_material(
    file: UploadFile = File(..., description="Markdown(.md/.markdown/.txt) 或 PDF(.pdf)"),
    session: Session = Depends(db_session),
) -> ApiResponse:
    saved = None
    try:
        saved = await save_material(file)
        parsed = parse_material(saved)
    except MaterialError as exc:
        if saved is not None:
            delete_material_files(saved.relative_path)
        raise _rethrow(exc) from exc

    detail = course_service.create_draft(session, saved, parsed)
    return success(detail, message="解析完成，请确认课程结构")


@router.get("/{course_id}", response_model=ApiResponse[CourseDetail], summary="课程详情（含章节与知识点目录）")
def get_course(course_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    return success(course_service.get_detail(session, course_id))


@router.patch("/{course_id}", response_model=ApiResponse[CourseDetail], summary="修改课程名称/简介/图标")
def update_course(
    course_id: int,
    payload: CourseUpdate,
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(course_service.update_course(session, course_id, payload), message="已保存")


@router.post("/{course_id}/confirm", response_model=ApiResponse[CourseDetail], summary="确认创建正式课程")
def confirm_course(course_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    return success(course_service.confirm_course(session, course_id), message="课程已创建")


@router.delete(
    "/{course_id}",
    response_model=ApiResponse[None],
    summary="删除课程（连同章节、知识点、学习状态与教材文件）",
)
def delete_course(course_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    course_service.delete_course(session, course_id)
    return success(message="课程已删除")


@router.get("/{course_id}/progress", response_model=ApiResponse[CourseProgress], summary="课程学习进度（总览 + 分章节 + 最近学习）")
def get_progress(course_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    return success(course_service.course_progress(session, course_id))


# ------------------------------------------------------------------ 章节

@router.get("/{course_id}/chapters", response_model=ApiResponse[list[ChapterOut]], summary="获取课程章节（含知识点）")
def list_chapters(course_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    return success(course_service.list_chapters(session, course_id))


@router.post("/{course_id}/chapters", response_model=ApiResponse[CourseDetail], summary="新增章节")
def add_chapter(
    course_id: int,
    payload: ChapterCreate,
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(course_service.add_chapter(session, course_id, payload), message="章节已添加")


# 注意：reorder 必须声明在 /{chapter_id} 之前，否则 "reorder" 会被当成 chapter_id 解析失败
@router.patch("/{course_id}/chapters/reorder", response_model=ApiResponse[CourseDetail], summary="调整章节顺序")
def reorder_chapters(
    course_id: int,
    payload: ChapterReorderRequest,
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(course_service.reorder_chapters(session, course_id, payload.ids), message="顺序已更新")


@router.patch("/{course_id}/chapters/{chapter_id}", response_model=ApiResponse[CourseDetail], summary="修改章节")
def update_chapter(
    course_id: int,
    chapter_id: int,
    payload: ChapterUpdate,
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(
        course_service.update_chapter(session, chapter_id, payload, course_id=course_id), message="已保存"
    )


@router.delete("/{course_id}/chapters/{chapter_id}", response_model=ApiResponse[CourseDetail], summary="删除章节及其知识点")
def delete_chapter(course_id: int, chapter_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    return success(course_service.delete_chapter(session, chapter_id, course_id=course_id), message="章节已删除")


# ------------------------------------------------------------------ 知识点

@router.get("/{course_id}/knowledge-points", response_model=ApiResponse[list[KnowledgePointSummary]], summary="课程知识点列表")
def list_points(
    course_id: int,
    point_status: str | None = Query(default=None, alias="status", max_length=16),
    q: str | None = Query(default=None, max_length=120),
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(course_service.list_points(session, course_id, status=point_status, q=q))


@router.post(
    "/{course_id}/chapters/{chapter_id}/knowledge-points",
    response_model=ApiResponse[CourseDetail],
    summary="新增知识点",
)
def add_point(
    course_id: int,
    chapter_id: int,
    payload: KnowledgePointCreate,
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(
        course_service.add_point(session, chapter_id, payload, course_id=course_id), message="知识点已添加"
    )


@router.patch(
    "/{course_id}/chapters/{chapter_id}/knowledge-points/reorder",
    response_model=ApiResponse[CourseDetail],
    summary="调整知识点顺序",
)
def reorder_points(
    course_id: int,
    chapter_id: int,
    payload: PointReorderRequest,
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(
        course_service.reorder_points(session, chapter_id, payload.ids, course_id=course_id), message="顺序已更新"
    )


@router.patch("/{course_id}/knowledge-points/{point_id}", response_model=ApiResponse[CourseDetail], summary="修改知识点")
def update_point(
    course_id: int,
    point_id: int,
    payload: KnowledgePointUpdate,
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(course_service.update_point(session, point_id, payload, course_id=course_id), message="已保存")


@router.delete("/{course_id}/knowledge-points/{point_id}", response_model=ApiResponse[CourseDetail], summary="删除知识点")
def delete_point(course_id: int, point_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    return success(course_service.delete_point(session, point_id, course_id=course_id), message="知识点已删除")


@router.patch(
    "/{course_id}/knowledge-points/{point_id}/status",
    response_model=ApiResponse[CourseDetail],
    summary="更新知识点学习状态",
)
def set_point_status(
    course_id: int,
    point_id: int,
    payload: PointStatusUpdate,
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(
        course_service.set_point_status(session, point_id, payload.status, course_id=course_id), message="学习状态已更新"
    )


@router.patch("/{course_id}/reorder", response_model=ApiResponse[CourseDetail], summary="批量调整章节/知识点顺序（导入预览）")
def reorder(
    course_id: int,
    payload: ReorderRequest,
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(course_service.reorder(session, course_id, payload), message="顺序已更新")


# ------------------------------------------------------------------ 扁平路径（P1.1 兼容）

@node_router.get("/knowledge-points/{point_id}", response_model=ApiResponse[KnowledgePointDetail], summary="知识点详情（含正文）")
def get_point(point_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    return success(course_service.point_detail(session, point_id))


@node_router.patch("/knowledge-points/{point_id}", response_model=ApiResponse[CourseDetail], summary="修改知识点")
def update_point_flat(
    point_id: int,
    payload: KnowledgePointUpdate,
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(course_service.update_point(session, point_id, payload), message="已保存")


@node_router.delete("/knowledge-points/{point_id}", response_model=ApiResponse[CourseDetail], summary="删除知识点")
def delete_point_flat(point_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    return success(course_service.delete_point(session, point_id), message="知识点已删除")


@node_router.patch("/knowledge-points/{point_id}/status", response_model=ApiResponse[CourseDetail], summary="更新知识点学习状态")
def set_point_status_flat(
    point_id: int,
    payload: PointStatusUpdate,
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(course_service.set_point_status(session, point_id, payload.status), message="学习状态已更新")


@node_router.patch("/chapters/{chapter_id}", response_model=ApiResponse[CourseDetail], summary="修改章节")
def update_chapter_flat(
    chapter_id: int,
    payload: ChapterUpdate,
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(course_service.update_chapter(session, chapter_id, payload), message="已保存")


@node_router.delete("/chapters/{chapter_id}", response_model=ApiResponse[CourseDetail], summary="删除章节")
def delete_chapter_flat(chapter_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    return success(course_service.delete_chapter(session, chapter_id), message="章节已删除")


@node_router.post(
    "/chapters/{chapter_id}/knowledge-points",
    response_model=ApiResponse[CourseDetail],
    summary="新增知识点",
)
def add_point_flat(
    chapter_id: int,
    payload: KnowledgePointCreate,
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(course_service.add_point(session, chapter_id, payload), message="知识点已添加")


@node_router.patch(
    "/chapters/{chapter_id}/knowledge-points/reorder",
    response_model=ApiResponse[CourseDetail],
    summary="调整知识点顺序",
)
def reorder_points_flat(
    chapter_id: int,
    payload: PointReorderRequest,
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(course_service.reorder_points(session, chapter_id, payload.ids), message="顺序已更新")
