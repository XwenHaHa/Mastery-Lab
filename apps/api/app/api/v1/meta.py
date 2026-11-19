"""教学元数据接口（P1.6-A）。

前端不再硬编码阶段中文名和顺序，改为读取这里；旧值仍作为兜底。
"""

from fastapi import APIRouter

from ...core.config import settings
from ...core.response import ApiResponse, success
from ...services import activity_protocol, subject_profiles, teaching_stages

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/teaching", summary="教学阶段、流水线版本与学科策略元数据")
def teaching_meta() -> ApiResponse:
    payload = teaching_stages.pipeline_payload(settings.teaching_pipeline_version)
    payload["activityTypes"] = list(activity_protocol.ACTIVITY_TYPES)
    payload["subjectProfiles"] = subject_profiles.payload()
    return success(payload)
