"""课程素材库（P1.6-G）。

只允许图片、音频、视频；文件由服务端重命名落盘在 data/materials/<course_id>/。
教学活动和 Markdown 通过 material_id 引用，避免任意外链、base64 内联和路径穿越。
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..db.models import Course, Material
from .materials import MaterialError

CHUNK = 1024 * 1024
MAX_NAME_LEN = 160


def _safe_name(raw: str) -> str:
    name = Path(raw or "asset").name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip() or "asset"
    if len(name) > MAX_NAME_LEN:
        stem, dot, suffix = name.rpartition(".")
        name = (stem[: MAX_NAME_LEN - len(suffix) - 1] + "." + suffix) if dot else name[:MAX_NAME_LEN]
    return name


def _is_png(data: bytes) -> bool:
    return data.startswith(b"\x89PNG\r\n\x1a\n")


def _is_jpg(data: bytes) -> bool:
    return data.startswith(b"\xff\xd8\xff")


def _is_gif(data: bytes) -> bool:
    return data.startswith(b"GIF8")


def _is_webp(data: bytes) -> bool:
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def _is_mp3(data: bytes) -> bool:
    return data.startswith(b"ID3") or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)


def _is_wav(data: bytes) -> bool:
    return data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def _is_ogg(data: bytes) -> bool:
    return data.startswith(b"OggS")


def _is_ftyp(data: bytes) -> bool:
    return data[4:8] == b"ftyp"


def _is_webm(data: bytes) -> bool:
    return data.startswith(b"\x1a\x45\xdf\xa3")


# suffix -> (kind, mime, validator)
ALLOWED: dict[str, tuple[str, str, Callable[[bytes], bool]]] = {
    ".png": ("image", "image/png", _is_png),
    ".jpg": ("image", "image/jpeg", _is_jpg),
    ".jpeg": ("image", "image/jpeg", _is_jpg),
    ".gif": ("image", "image/gif", _is_gif),
    ".webp": ("image", "image/webp", _is_webp),
    ".mp3": ("audio", "audio/mpeg", _is_mp3),
    ".wav": ("audio", "audio/wav", _is_wav),
    ".ogg": ("audio", "audio/ogg", _is_ogg),
    ".m4a": ("audio", "audio/mp4", _is_ftyp),
    ".mp4": ("video", "video/mp4", _is_ftyp),
    ".webm": ("video", "video/webm", _is_webm),
}


@dataclass
class SavedAsset:
    material: Material
    absolute_path: Path


def _within_materials(path: Path) -> Path:
    root = settings.materials_dir.resolve()
    resolved = path.resolve()
    if root not in resolved.parents and resolved != root:
        raise MaterialError("素材路径超出允许的数据目录", status_code=400, code=2001)
    return resolved


def absolute_path(relative_path: str) -> Path:
    if not relative_path:
        raise MaterialError("素材路径为空", status_code=404, code=2002)
    path = _within_materials(settings.data_dir / relative_path)
    if not path.is_file():
        raise MaterialError("素材文件不存在，可能已被删除", status_code=404, code=2002)
    return path


async def save_asset(
    db: Session,
    *,
    course_id: int,
    upload: UploadFile,
    caption: str = "",
) -> Material:
    course = db.get(Course, course_id)
    if course is None:
        raise MaterialError("课程不存在", status_code=404, code=2003)

    display_name = _safe_name(upload.filename or "")
    suffix = Path(display_name).suffix.lower()
    config = ALLOWED.get(suffix)
    if config is None:
        raise MaterialError(
            f"不支持的素材类型 {suffix or '（无扩展名）'}；支持 PNG/JPEG/GIF/WebP、MP3/WAV/OGG/M4A、MP4/WebM",
            status_code=415,
            code=2004,
        )
    kind, mime_type, validator = config

    folder = settings.materials_dir / str(course_id)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{uuid.uuid4().hex}{suffix}"

    digest = hashlib.sha256()
    size = 0
    first = b""
    try:
        with target.open("wb") as handle:
            while True:
                chunk = await upload.read(CHUNK)
                if not chunk:
                    break
                if not first:
                    first = chunk[:64]
                size += len(chunk)
                if size > settings.max_asset_bytes:
                    raise MaterialError(
                        f"素材超过 {settings.max_asset_bytes // (1024 * 1024)} MB 上限",
                        status_code=413,
                        code=2005,
                    )
                digest.update(chunk)
                handle.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    if size == 0:
        target.unlink(missing_ok=True)
        raise MaterialError("素材文件为空（0 字节）", status_code=400, code=2006)
    if not validator(first):
        target.unlink(missing_ok=True)
        raise MaterialError("文件内容与扩展名不匹配，已拒绝保存", status_code=400, code=2007)

    relative = target.relative_to(settings.data_dir).as_posix()
    material = Material(
        course_id=course_id,
        file_name=display_name,
        relative_path=relative,
        mime_type=mime_type,
        kind=kind,
        size_bytes=size,
        sha256=digest.hexdigest(),
        caption=(caption or "")[:2000],
    )
    try:
        db.add(material)
        db.commit()
        db.refresh(material)
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise
    return material


def list_assets(db: Session, course_id: int) -> list[Material]:
    return list(
        db.scalars(
            select(Material).where(Material.course_id == course_id).order_by(Material.id.desc())
        ).all()
    )


def get_asset(db: Session, material_id: int) -> Material:
    material = db.get(Material, material_id)
    if material is None:
        raise MaterialError("素材不存在", status_code=404, code=2008)
    return material


def delete_asset(db: Session, material_id: int) -> None:
    material = get_asset(db, material_id)
    relative = material.relative_path
    course_id = material.course_id
    db.delete(material)
    db.commit()
    _remove_file(relative, course_id)


def delete_course_assets(db: Session, course_id: int) -> None:
    materials = list_assets(db, course_id)
    for material in materials:
        db.delete(material)
    if materials:
        db.commit()
    for material in materials:
        _remove_file(material.relative_path, course_id)


def _remove_file(relative_path: str, course_id: int) -> None:
    try:
        path = _within_materials(settings.data_dir / relative_path)
    except MaterialError:
        return
    path.unlink(missing_ok=True)
    folder = settings.materials_dir / str(course_id)
    try:
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        pass


def payload(material: Material) -> dict:
    return {
        "id": material.id,
        "courseId": material.course_id,
        "fileName": material.file_name,
        "kind": material.kind,
        "mimeType": material.mime_type,
        "sizeBytes": material.size_bytes,
        "caption": material.caption,
        "url": f"{settings.api_prefix}/materials/{material.id}/content",
        "createdAt": material.created_at.isoformat() if material.created_at else None,
    }


def material_ids_for_course(db: Session, course_id: int) -> set[int]:
    """当前课程拥有的素材 ID，用于活动定义归属校验（P1.7-A）。"""
    return set(
        db.scalars(select(Material.id).where(Material.course_id == course_id)).all()
    )


def resolve_material_refs(db: Session, material_ids: list[int], course_id: int) -> list[dict]:
    """把活动引用的素材解析成前端可读的元数据；缺失或跨课程时 exists=false。

    只读，不修改历史活动。删除素材后旧活动仍然保留定义，前端显示缺失占位。
    """
    unique = sorted({int(item) for item in material_ids if int(item) > 0})
    if not unique:
        return []
    rows = db.scalars(
        select(Material).where(Material.id.in_(unique), Material.course_id == course_id)
    ).all()
    by_id = {row.id: row for row in rows}
    result: list[dict] = []
    for material_id in unique:
        material = by_id.get(material_id)
        if material is None:
            result.append(
                {
                    "materialId": material_id,
                    "exists": False,
                    "courseId": course_id,
                    "fileName": "",
                    "kind": "unknown",
                    "mimeType": "",
                    "caption": "",
                    "url": "",
                }
            )
            continue
        result.append(
            {
                "materialId": material.id,
                "exists": True,
                "courseId": material.course_id,
                "fileName": material.file_name,
                "kind": material.kind,
                "mimeType": material.mime_type,
                "caption": material.caption,
                "url": f"{settings.api_prefix}/materials/{material.id}/content",
            }
        )
    return result
