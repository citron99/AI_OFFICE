from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.files import router as files_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.legal import router as legal_router
from app.api.v1.metrics import router as metrics_router
from app.api.v1.office import router as office_router
from app.api.v1.reviews import router as reviews_router
from app.api.v1.schedules import router as schedules_router
from app.api.v1.tasks import router as tasks_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(metrics_router)
api_router.include_router(tasks_router)
api_router.include_router(files_router)
api_router.include_router(knowledge_router)
api_router.include_router(legal_router)
api_router.include_router(office_router)
api_router.include_router(reviews_router)
api_router.include_router(schedules_router)
