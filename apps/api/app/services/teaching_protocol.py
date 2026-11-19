import json
import re

from pydantic import ValidationError as SchemaError
from sqlalchemy import select

from ..core.response import ValidationError
from ..schemas.teaching import TeachingJudgment, TeachingTask


def build_messages(db, row, progress, operation, content):
    """兼容入口：P1.4 起提示词统一由 prompt_assembler 组装。"""
    from .prompt_assembler import teaching_messages

    return teaching_messages(db, row, progress, operation, content)


def parse_result(text, operation, db):
    raw = text.strip()
    if raw.startswith('```') and raw.endswith('```'):
        raw = re.sub(r'^```(?:json)?\s*', '', raw)[:-3].strip()
    try:
        if operation.kind == "task":
            result = TeachingTask.model_validate_json(raw)
            combined = result.instruction + result.question
            if combined.count('?') + combined.count('？') > 1 or re.search(r'(?:^|\n)\s*(?:2[.、)]|二[、.])', result.question):
                raise ValueError("multiple questions")
            if operation.stage == "VERIFY":
                previous = db.scalars(select(TeachingOperation).where(TeachingOperation.session_id == operation.session_id, TeachingOperation.kind == 'task', TeachingOperation.status == 'completed')).all()
                normalize = lambda value: re.sub(r'\W+', '', value).casefold()
                if any(normalize(json.loads(item.result_json).get('question', '')) == normalize(result.question) for item in previous):
                    raise ValueError("repeated verification question")
            return result, f"{result.instruction}\n\n{result.question}"
        result = TeachingJudgment.model_validate_json(raw)
        return result, result.feedback
    except (SchemaError, ValueError, TypeError):
        raise ValidationError("模型返回的教学结构无效，本阶段未推进，请重试或切换模型") from None
