"""教材文件存储与解析调度（P1.1）。

安全约束：
- 文件名只取 basename，过滤控制字符，长度截断；绝不使用客户端路径拼接；
- 实际落盘目录由服务端生成（data/courses/<uuid>/），与用户文件名无关；
- 任何读写都要经过 _within_courses 校验，防止 ../ 穿越到数据目录之外；
- 单文件大小上限来自配置，超限立刻中止，不落地半截文件。
"""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from ..core.config import settings
from .md_parser import ParsedMaterial, parse_markdown
from .pdf_parser import PdfNoTextError, parse_pdf

SUPPORTED_SUFFIXES = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "markdown",
    ".pdf": "pdf",
}
MAX_NAME_LEN = 120
CHUNK = 1024 * 1024


class MaterialError(Exception):
    """教材处理失败，携带可直接展示的提示与 HTTP 状态。"""

    def __init__(self, message: str, *, status_code: int = 400, code: int = 1006) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


@dataclass
class SavedMaterial:
    relative_path: str
    absolute_path: Path
    display_name: str
    source_type: str
    size_bytes: int
    sha256: str


def _safe_display_name(raw: str) -> str:
    name = Path(raw or "material").name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip() or "material"
    if len(name) > MAX_NAME_LEN:
        stem, dot, suffix = name.rpartition(".")
        if dot and len(suffix) <= 8:
            name = stem[: MAX_NAME_LEN - len(suffix) - 1] + "." + suffix
        else:
            name = name[:MAX_NAME_LEN]
    return name


def _within_courses(path: Path) -> Path:
    root = settings.courses_dir.resolve()
    resolved = path.resolve()
    if root not in resolved.parents and resolved != root:
        raise MaterialError("文件路径超出允许的数据目录", status_code=400, code=1007)
    return resolved


def absolute_source_path(relative_path: str) -> Path:
    if not relative_path:
        raise MaterialError("教材文件路径为空", status_code=404, code=1001)
    candidate = settings.data_dir / relative_path
    resolved = _within_courses(candidate)
    if not resolved.is_file():
        raise MaterialError("教材文件不存在，可能已被删除", status_code=404, code=1001)
    return resolved


async def save_material(upload: UploadFile) -> SavedMaterial:
    display_name = _safe_display_name(upload.filename or "")
    suffix = Path(display_name).suffix.lower()
    source_type = SUPPORTED_SUFFIXES.get(suffix)
    if source_type is None:
        raise MaterialError(
            f"不支持的文件类型 {suffix or '（无扩展名）'}，目前支持 Markdown（.md/.markdown/.txt）与 PDF（.pdf）",
            status_code=415,
            code=1008,
        )

    settings.courses_dir.mkdir(parents=True, exist_ok=True)
    folder = settings.courses_dir / uuid.uuid4().hex[:12]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / display_name

    digest = hashlib.sha256()
    size = 0
    buffer = io.BytesIO()
    try:
        while True:
            chunk = await upload.read(CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > settings.max_material_bytes:
                raise MaterialError(
                    f"文件超过 {settings.max_material_bytes // (1024 * 1024)} MB 上限",
                    status_code=413,
                    code=1009,
                )
            digest.update(chunk)
            buffer.write(chunk)
    finally:
        await upload.close()

    if size == 0:
        shutil.rmtree(folder, ignore_errors=True)
        raise MaterialError("文件是空的（0 字节），请选择有内容的教材", status_code=400, code=1010)

    data = buffer.getvalue()
    if source_type == "pdf":
        if not data.lstrip()[:5].startswith(b"%PDF"):
            shutil.rmtree(folder, ignore_errors=True)
            raise MaterialError("文件扩展名是 .pdf，但内容不是有效的 PDF", status_code=400, code=1011)
    else:
        # 文本类：尝试严格解码，失败时交给上层用宽松模式读取并提示
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                data.decode("gb18030")
            except UnicodeDecodeError as exc:
                shutil.rmtree(folder, ignore_errors=True)
                raise MaterialError("文件不是有效的 UTF-8 / GB18030 文本，可能已损坏", status_code=400, code=1012) from exc

    target.write_bytes(data)
    relative = target.relative_to(settings.data_dir).as_posix()
    return SavedMaterial(
        relative_path=relative,
        absolute_path=target,
        display_name=display_name,
        source_type=source_type,
        size_bytes=size,
        sha256=digest.hexdigest(),
    )


def read_material_text(absolute_path: Path) -> str:
    raw = absolute_path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_material(saved: SavedMaterial) -> ParsedMaterial:
    fallback_title = Path(saved.display_name).stem or "未命名教材"
    if saved.source_type == "pdf":
        try:
            return parse_pdf(saved.absolute_path, fallback_title)
        except PdfNoTextError as exc:
            raise MaterialError(str(exc), status_code=422, code=1013) from exc
    text = read_material_text(saved.absolute_path)
    if not text.strip():
        raise MaterialError("教材内容为空，没有可解析的正文", status_code=400, code=1014)
    return parse_markdown(text, fallback_title)


def delete_material_files(relative_path: str) -> None:
    """删除教材文件及其所在目录（仅限 data/courses 内）。"""
    if not relative_path:
        return
    try:
        path = settings.data_dir / relative_path
        resolved = _within_courses(path)
    except MaterialError:
        return
    if resolved.is_file():
        resolved.unlink(missing_ok=True)
    parent = resolved.parent
    root = settings.courses_dir.resolve()
    if parent != root and root in parent.parents and parent.is_dir():
        if not any(parent.iterdir()):
            parent.rmdir()
