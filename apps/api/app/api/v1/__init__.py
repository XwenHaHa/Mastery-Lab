"""v1 路由汇总。新增模块时只需在这里注册一个子路由。"""

from fastapi import APIRouter

from . import classroom, courses, health, models, teaching

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(models.router)
api_router.include_router(courses.router)
api_router.include_router(courses.node_router)
api_router.include_router(classroom.router)
api_router.include_router(teaching.router)
