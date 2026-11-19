"""课程业务逻辑（P1.1 建，P1.2 扩展章节/知识点管理与学习状态）。

状态约定：
- 上传解析后先落成 status='draft' 的课程（用户可以在预览页反复修改、调序、增删）；
- 用户点"确认创建"才切成 status='active'，此时才会出现在课程中心；
- 删除课程同时删除教材文件与所有章节/知识点（ORM 级联 + 文件清理）。

归属校验：
带 `course_id` 参数的写操作会校验「这个章节/知识点确实属于该课程」，不匹配按 404 处理，
避免前端拿着过期 ID（例如切换课程后残留的选中项）改到另一门课的数据。

学习进度：
统一走 `services.learning`（四态 + 加权公式），本模块只负责取数，不另写一套算法。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.response import ConflictError, NotFoundError, ValidationError
from ..db.models import Chapter, Course, KnowledgePoint, LearningSession, TeachingProgress
from ..schemas.course import (
    ChapterCreate,
    ChapterOut,
    ChapterProgress,
    ChapterUpdate,
    CourseDetail,
    CourseProgress,
    CourseSummary,
    CourseUpdate,
    KnowledgePointCreate,
    KnowledgePointDetail,
    KnowledgePointOut,
    KnowledgePointSummary,
    KnowledgePointUpdate,
    RecentStudy,
    ReorderRequest,
    StatusCounts,
)
from . import learning, mastery
from .materials import SavedMaterial, delete_material_files
from .md_parser import ParsedMaterial, _summarize

logger = logging.getLogger(__name__)

SORT_OPTIONS = ("updated", "created", "studied")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None) -> datetime | None:
    """SQLite 存的是 naive UTC，这里补上时区标记再输出。

    否则前端 `new Date('2026-11-16T08:56:59')` 会按本地时间解析，
    「最近学习」在东八区会凭空差 8 小时。
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clip(text: str | None, limit: int) -> str:
    value = (text or "").strip()
    return value[:limit]


def _meta(course: Course) -> dict[str, Any]:
    try:
        data = json.loads(course.parse_meta or "{}")
    except ValueError:
        return {"warnings": [], "stats": {}}
    if not isinstance(data, dict):
        return {"warnings": [], "stats": {}}
    return {
        "warnings": [str(item) for item in data.get("warnings", []) if item],
        "stats": data.get("stats", {}) or {},
    }


def _all_points(course: Course) -> list[KnowledgePoint]:
    return [point for chapter in course.chapters for point in chapter.knowledge_points]


def _counts(course: Course) -> tuple[int, int, int, int, dict[str, int]]:
    """返回 (章节数, 知识点数, 代码块数, 进度, 状态分布)。"""
    chapters = course.chapters
    points = _all_points(course)
    code_total = sum(chapter.code_count for chapter in chapters)
    counts = learning.status_counts(points)
    return len(chapters), len(points), code_total, learning.progress_from_counts(counts), counts


def _touch(course: Course) -> None:
    """内容变更：只刷新 updated_at（学习行为走 _mark_studied）。"""
    course.updated_at = _utcnow()


def _mark_studied(course: Course, point: KnowledgePoint) -> None:
    """记录学习行为：知识点与课程各记一次时间，供「最近学习」排序。"""
    now = _utcnow()
    point.last_studied_at = now
    course.last_studied_at = now


def _reload(session: Session, course: Course) -> CourseDetail:
    """提交后重新读一次，避免关系集合缓存导致响应里缺章节/知识点。"""
    course_id = course.id
    session.expire_all()
    return to_detail(get_course(session, course_id))


def _status_counts_model(counts: dict[str, int]) -> StatusCounts:
    return StatusCounts(
        total=counts.get("total", 0),
        not_started=counts.get(learning.STATUS_NOT_STARTED, 0),
        in_progress=counts.get(learning.STATUS_IN_PROGRESS, 0),
        review=counts.get(learning.STATUS_REVIEW, 0),
        completed=counts.get(learning.STATUS_COMPLETED, 0),
    )


def _point_out(point: KnowledgePoint) -> KnowledgePointOut:
    return KnowledgePointOut(
        id=point.id,
        chapter_id=point.chapter_id,
        title=point.title,
        description=point.description,
        content_length=len(point.content or ""),
        sort_order=point.sort_order,
        code_count=point.code_count,
        mastery_level=point.mastery_level,
        learning_status=learning.safe_status(point.learning_status),
        mastery_state=mastery.safe_state(point.mastery_state),
        mastery_label=mastery.label(point.mastery_state),
        completion_source=point.completion_source,
        last_studied_at=_utc(point.last_studied_at),
    )


def _chapter_out(chapter: Chapter) -> ChapterOut:
    points = sorted(chapter.knowledge_points, key=lambda item: item.sort_order)
    counts = learning.status_counts(points)
    return ChapterOut(
        id=chapter.id,
        course_id=chapter.course_id,
        title=chapter.title,
        description=chapter.description,
        sort_order=chapter.sort_order,
        code_count=chapter.code_count,
        knowledge_points=[_point_out(point) for point in points],
        status_counts=_status_counts_model(counts),
        progress=learning.progress_from_counts(counts),
    )


def to_summary(course: Course) -> CourseSummary:
    chapter_count, point_count, code_count, progress, counts = _counts(course)
    return CourseSummary(
        id=course.id,
        title=course.title,
        description=course.description,
        status=course.status,
        icon=course.icon or "",
        source_type=course.source_type,
        source_name=course.source_name,
        source_bytes=course.source_bytes,
        chapter_count=chapter_count,
        knowledge_point_count=point_count,
        code_count=code_count,
        progress=progress,
        status_counts=_status_counts_model(counts),
        last_studied_at=_utc(course.last_studied_at),
        created_at=_utc(course.created_at) or course.created_at,
        updated_at=_utc(course.updated_at) or course.updated_at,
    )


def to_detail(course: Course) -> CourseDetail:
    summary = to_summary(course)
    meta = _meta(course)
    chapters = [_chapter_out(chapter) for chapter in sorted(course.chapters, key=lambda item: item.sort_order)]
    return CourseDetail(**summary.model_dump(), warnings=meta["warnings"], stats=meta["stats"], chapters=chapters)


def list_courses(
    session: Session,
    *,
    status: str = "active",
    q: str | None = None,
    sort: str = "updated",
) -> list[CourseSummary]:
    """课程列表：支持按标题/简介/教材名搜索，按创建时间、更新时间或最近学习排序。"""
    stmt = select(Course).where(Course.status == status)
    keyword = (q or "").strip()
    if keyword:
        pattern = f"%{keyword.lower()}%"
        stmt = stmt.where(
            func.lower(Course.title).like(pattern)
            | func.lower(Course.description).like(pattern)
            | func.lower(Course.source_name).like(pattern)
        )

    if sort == "created":
        stmt = stmt.order_by(Course.created_at.desc(), Course.id.desc())
    elif sort == "studied":
        # SQLite 没有 NULLS LAST 语法：先按「是否为空」升序，把没学过的排到末尾
        stmt = stmt.order_by(Course.last_studied_at.is_(None), Course.last_studied_at.desc(), Course.id.desc())
    else:
        stmt = stmt.order_by(Course.updated_at.desc(), Course.id.desc())

    return [to_summary(course) for course in session.scalars(stmt).all()]


def get_course(session: Session, course_id: int) -> Course:
    course = session.get(Course, course_id)
    if course is None:
        raise NotFoundError(f"课程 {course_id} 不存在")
    return course


def get_detail(session: Session, course_id: int) -> CourseDetail:
    return to_detail(get_course(session, course_id))


def _get_chapter(session: Session, chapter_id: int, course_id: int | None = None) -> Chapter:
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise NotFoundError(f"章节 {chapter_id} 不存在")
    if course_id is not None and chapter.course_id != course_id:
        raise NotFoundError(f"章节 {chapter_id} 不属于课程 {course_id}")
    return chapter


def _get_point(session: Session, point_id: int, course_id: int | None = None) -> KnowledgePoint:
    point = session.get(KnowledgePoint, point_id)
    if point is None:
        raise NotFoundError(f"知识点 {point_id} 不存在")
    if course_id is not None and point.chapter.course_id != course_id:
        raise NotFoundError(f"知识点 {point_id} 不属于课程 {course_id}")
    return point


def create_draft(session: Session, saved: SavedMaterial, parsed: ParsedMaterial) -> CourseDetail:
    course = Course(
        title=_clip(parsed.title, 200) or "未命名课程",
        description=_clip(parsed.description, 2000),
        source_type=saved.source_type,
        source_name=saved.display_name,
        source_file=saved.relative_path,
        source_sha256=saved.sha256,
        source_bytes=saved.size_bytes,
        status="draft",
        parse_meta=json.dumps(
            {"warnings": parsed.warnings, "stats": parsed.stats},
            ensure_ascii=False,
        ),
    )
    course.icon = ""
    course.last_studied_at = None

    for chapter_index, parsed_chapter in enumerate(parsed.chapters):
        chapter = Chapter(
            title=_clip(parsed_chapter.title, 200) or f"第 {chapter_index + 1} 章",
            description=_clip(parsed_chapter.description, 2000),
            sort_order=chapter_index,
            code_count=parsed_chapter.code_count,
        )
        for point_index, parsed_point in enumerate(parsed_chapter.points):
            content = parsed_point.text
            chapter.knowledge_points.append(
                KnowledgePoint(
                    title=_clip(parsed_point.title, 200) or f"知识点 {point_index + 1}",
                    description=_clip(_summarize(content.split("\n")), 2000),
                    content=content,
                    sort_order=point_index,
                    code_count=parsed_point.code_count,
                    learning_status=learning.STATUS_NOT_STARTED,
                )
            )
        course.chapters.append(chapter)

    session.add(course)
    session.commit()
    session.refresh(course)
    logger.info(
        "教材解析完成：course=%s title=%s chapters=%s points=%s",
        course.id,
        course.title,
        len(course.chapters),
        len(_all_points(course)),
    )
    return _reload(session, course)


def update_course(session: Session, course_id: int, payload: CourseUpdate) -> CourseDetail:
    course = get_course(session, course_id)
    if payload.title is not None:
        course.title = _clip(payload.title, 200)
    if payload.description is not None:
        course.description = _clip(payload.description, 2000)
    fields_set = payload.model_fields_set
    if payload.icon is not None or "icon" in fields_set:
        course.icon = _clip(payload.icon or "", 16)
    _touch(course)
    session.commit()
    session.refresh(course)
    return _reload(session, course)


def confirm_course(session: Session, course_id: int) -> CourseDetail:
    course = get_course(session, course_id)
    if course.status != "active":
        if not course.chapters:
            raise ValidationError("课程还没有章节，不能确认创建")
    course.status = "active"
    _touch(course)
    session.commit()
    session.refresh(course)
    logger.info("课程已确认创建：course=%s title=%s", course.id, course.title)
    return _reload(session, course)


def delete_course(session: Session, course_id: int) -> None:
    """删除课程：章节、知识点、学习状态随 ORM 级联一起删除，再清理教材文件。"""
    course = get_course(session, course_id)
    source_file = course.source_file
    session.delete(course)
    session.commit()
    delete_material_files(source_file)
    logger.info("课程已删除：course=%s file=%s", course_id, source_file)


# ---------------------------------------------------------------- 章节


def list_chapters(session: Session, course_id: int) -> list[ChapterOut]:
    course = get_course(session, course_id)
    return [_chapter_out(chapter) for chapter in sorted(course.chapters, key=lambda item: item.sort_order)]


def add_chapter(session: Session, course_id: int, payload: ChapterCreate) -> CourseDetail:
    course = get_course(session, course_id)
    next_order = max((chapter.sort_order for chapter in course.chapters), default=-1) + 1
    chapter = Chapter(
        course_id=course.id,
        title=_clip(payload.title, 200),
        description=_clip(payload.description, 2000),
        sort_order=next_order,
        code_count=0,
    )
    session.add(chapter)
    _touch(course)
    session.commit()
    session.refresh(course)
    return _reload(session, course)


def update_chapter(
    session: Session,
    chapter_id: int,
    payload: ChapterUpdate,
    *,
    course_id: int | None = None,
) -> CourseDetail:
    chapter = _get_chapter(session, chapter_id, course_id)
    if payload.title is not None:
        chapter.title = _clip(payload.title, 200)
    if payload.description is not None:
        chapter.description = _clip(payload.description, 2000)
    course = chapter.course
    _touch(course)
    session.commit()
    session.refresh(course)
    return _reload(session, course)


def delete_chapter(session: Session, chapter_id: int, *, course_id: int | None = None) -> CourseDetail:
    """删除章节及其全部知识点（学习状态随知识点行一起删除，不留孤儿数据）。"""
    chapter = _get_chapter(session, chapter_id, course_id)
    course = chapter.course
    removed_points = len(chapter.knowledge_points)
    session.delete(chapter)
    session.flush()
    _renumber_chapters(course)
    _touch(course)
    session.commit()
    logger.info("章节已删除：chapter=%s 连带知识点=%s", chapter_id, removed_points)
    session.refresh(course)
    return _reload(session, course)


def _renumber_chapters(course: Course) -> None:
    for index, chapter in enumerate(sorted(course.chapters, key=lambda item: item.sort_order)):
        chapter.sort_order = index


def reorder_chapters(session: Session, course_id: int, ids: list[int]) -> CourseDetail:
    """按给定顺序重写章节 sort_order；ids 必须是当前课程全部章节的一个排列。"""
    course = get_course(session, course_id)
    chapters = {chapter.id: chapter for chapter in course.chapters}
    if len(ids) != len(set(ids)):
        raise ValidationError("章节顺序里有重复 ID")
    if sorted(ids) != sorted(chapters):
        raise ValidationError("章节顺序与当前课程不一致，请刷新后重试")
    for index, chapter_id in enumerate(ids):
        chapters[chapter_id].sort_order = index
    _touch(course)
    session.commit()
    session.refresh(course)
    return _reload(session, course)


# ---------------------------------------------------------------- 知识点


def list_points(
    session: Session,
    course_id: int,
    *,
    status: str | None = None,
    q: str | None = None,
) -> list[KnowledgePointSummary]:
    """课程内知识点平铺列表：可按学习状态过滤、按标题搜索。"""
    course = get_course(session, course_id)
    wanted = learning.normalize_status(status) if status else None
    keyword = (q or "").strip().lower()

    items: list[KnowledgePointSummary] = []
    for chapter in sorted(course.chapters, key=lambda item: item.sort_order):
        for point in sorted(chapter.knowledge_points, key=lambda item: item.sort_order):
            current = learning.safe_status(point.learning_status)
            if wanted and current != wanted:
                continue
            if keyword and keyword not in point.title.lower() and keyword not in (point.description or "").lower():
                continue
            items.append(
                KnowledgePointSummary(
                    id=point.id,
                    chapter_id=chapter.id,
                    chapter_title=chapter.title,
                    title=point.title,
                    description=point.description,
                    sort_order=point.sort_order,
                    code_count=point.code_count,
                    content_length=len(point.content or ""),
                    learning_status=current,
                    mastery_state=mastery.safe_state(point.mastery_state),
                    mastery_label=mastery.label(point.mastery_state),
                    completion_source=point.completion_source,
                    last_studied_at=point.last_studied_at,
                )
            )
    return items


def point_detail(session: Session, point_id: int, *, course_id: int | None = None) -> KnowledgePointDetail:
    point = _get_point(session, point_id, course_id)
    chapter = point.chapter
    course = chapter.course
    ordered = [
        item
        for row in sorted(course.chapters, key=lambda entry: entry.sort_order)
        for item in sorted(row.knowledge_points, key=lambda entry: entry.sort_order)
    ]
    index = next((i for i, item in enumerate(ordered) if item.id == point.id), -1)
    previous_id = ordered[index - 1].id if index > 0 else None
    next_id = ordered[index + 1].id if 0 <= index < len(ordered) - 1 else None
    return KnowledgePointDetail(
        id=point.id,
        chapter_id=chapter.id,
        chapter_title=chapter.title,
        course_id=course.id,
        course_title=course.title,
        title=point.title,
        description=point.description,
        content=point.content or "",
        sort_order=point.sort_order,
        code_count=point.code_count,
        learning_status=learning.safe_status(point.learning_status),
        mastery_state=mastery.safe_state(point.mastery_state),
        mastery_label=mastery.label(point.mastery_state),
        last_studied_at=_utc(point.last_studied_at),
        previous_id=previous_id,
        next_id=next_id,
        completion_source=point.completion_source,
    )


def add_point(
    session: Session,
    chapter_id: int,
    payload: KnowledgePointCreate,
    *,
    course_id: int | None = None,
) -> CourseDetail:
    chapter = _get_chapter(session, chapter_id, course_id)
    next_order = max((point.sort_order for point in chapter.knowledge_points), default=-1) + 1
    point = KnowledgePoint(
        chapter_id=chapter.id,
        title=_clip(payload.title, 200),
        description=_clip(payload.description, 2000),
        content=payload.content or "",
        sort_order=next_order,
        code_count=0,
        learning_status=learning.STATUS_NOT_STARTED,
    )
    session.add(point)
    course = chapter.course
    _touch(course)
    session.commit()
    session.refresh(course)
    return _reload(session, course)


def update_point(
    session: Session,
    point_id: int,
    payload: KnowledgePointUpdate,
    *,
    course_id: int | None = None,
) -> CourseDetail:
    point = _get_point(session, point_id, course_id)
    if payload.title is not None:
        point.title = _clip(payload.title, 200)
    if payload.description is not None:
        point.description = _clip(payload.description, 2000)
    if payload.content is not None:
        point.content = payload.content
    course = point.chapter.course
    _touch(course)
    session.commit()
    session.refresh(course)
    return _reload(session, course)


def delete_point(session: Session, point_id: int, *, course_id: int | None = None) -> CourseDetail:
    point = _get_point(session, point_id, course_id)
    chapter = point.chapter
    course = chapter.course
    session.delete(point)
    session.flush()
    for index, item in enumerate(sorted(chapter.knowledge_points, key=lambda row: row.sort_order)):
        item.sort_order = index
    _touch(course)
    session.commit()
    session.refresh(course)
    return _reload(session, course)


def reorder_points(session: Session, chapter_id: int, ids: list[int], *, course_id: int | None = None) -> CourseDetail:
    """按给定顺序重写章节内知识点的 sort_order（ids 必须是全量排列）。"""
    chapter = _get_chapter(session, chapter_id, course_id)
    points = {point.id: point for point in chapter.knowledge_points}
    if len(ids) != len(set(ids)):
        raise ValidationError("知识点顺序里有重复 ID")
    if sorted(ids) != sorted(points):
        raise ValidationError("知识点顺序与当前章节不一致，请刷新后重试")
    for index, point_id in enumerate(ids):
        points[point_id].sort_order = index
    course = chapter.course
    _touch(course)
    session.commit()
    session.refresh(course)
    return _reload(session, course)


# ---------------------------------------------------------------- 学习状态与进度


def set_point_status(
    session: Session,
    point_id: int,
    status: str,
    *,
    course_id: int | None = None,
) -> CourseDetail:
    """手工调整学习状态。状态变更即视为一次学习行为，同时刷新最近学习时间。"""
    point = _get_point(session, point_id, course_id)
    try:
        normalized = learning.normalize_status(status)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if normalized == "completed":
        verified = session.scalar(select(TeachingProgress).join(LearningSession, LearningSession.id == TeachingProgress.session_id).where(
            LearningSession.knowledge_point_id == point_id, TeachingProgress.verification_result == "PASSED", TeachingProgress.current_stage == "NEXT"))
        if verified is None:
            raise ConflictError("需要先在学习教室通过 VERIFY 学习验证，不能手工跳过验证标记完成")
    point.learning_status = normalized
    course = point.chapter.course
    _mark_studied(course, point)
    session.commit()
    session.refresh(course)
    logger.info("学习状态更新：point=%s -> %s", point_id, point.learning_status)
    return _reload(session, course)


def course_progress(session: Session, course_id: int) -> CourseProgress:
    """课程学习进度总览：总体、分章节、最近学习的知识点。"""
    course = get_course(session, course_id)
    points = _all_points(course)
    counts = learning.status_counts(points)

    chapters: list[ChapterProgress] = []
    for chapter in sorted(course.chapters, key=lambda item: item.sort_order):
        chapter_counts = learning.status_counts(chapter.knowledge_points)
        chapters.append(
            ChapterProgress(
                id=chapter.id,
                title=chapter.title,
                sort_order=chapter.sort_order,
                knowledge_point_count=len(chapter.knowledge_points),
                progress=learning.progress_from_counts(chapter_counts),
                status_counts=_status_counts_model(chapter_counts),
            )
        )

    studied = sorted(
        (point for point in points if point.last_studied_at is not None),
        key=lambda item: item.last_studied_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:6]
    recent = [
        RecentStudy(
            point_id=point.id,
            title=point.title,
            chapter_id=point.chapter_id,
            chapter_title=point.chapter.title,
            learning_status=learning.safe_status(point.learning_status),
            mastery_state=mastery.safe_state(point.mastery_state),
            mastery_label=mastery.label(point.mastery_state),
            last_studied_at=_utc(point.last_studied_at) or _utcnow(),
        )
        for point in studied
    ]

    return CourseProgress(
        course_id=course.id,
        progress=learning.progress_from_counts(counts),
        status_counts=_status_counts_model(counts),
        chapters=chapters,
        recent=recent,
    )


def reorder(session: Session, course_id: int, payload: ReorderRequest) -> CourseDetail:
    """兼容 P1.1 导入预览页的整批排序接口（章节 + 多个章节的知识点一起提交）。"""
    course = get_course(session, course_id)
    chapters = {chapter.id: chapter for chapter in course.chapters}

    if payload.chapters:
        if sorted(payload.chapters) != sorted(chapters):
            raise ValidationError("章节顺序与当前课程不一致，请刷新后重试")
        for index, chapter_id in enumerate(payload.chapters):
            chapters[chapter_id].sort_order = index

    for order in payload.knowledge_points:
        chapter = chapters.get(order.chapter_id)
        if chapter is None:
            raise ValidationError("知识点排序引用了不属于该课程的章节")
        points = {point.id: point for point in chapter.knowledge_points}
        if sorted(order.ids) != sorted(points):
            raise ValidationError("知识点顺序与当前章节不一致，请刷新后重试")
        for index, point_id in enumerate(order.ids):
            points[point_id].sort_order = index

    _touch(course)
    session.commit()
    session.refresh(course)
    return _reload(session, course)
