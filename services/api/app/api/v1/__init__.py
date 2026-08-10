from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.aftercare import router as aftercare_router
from app.api.v1.auth import router as auth_router
from app.api.v1.safety import router as safety_router
from app.api.v1.chat import router as chat_router
from app.api.v1.conversation import router as conversation_router
from app.api.v1.speech import router as speech_router
from app.api.v1.workboard import router as workboard_router

router = APIRouter(prefix="/v1")
router.include_router(chat_router)
router.include_router(speech_router)
router.include_router(admin_router)
router.include_router(aftercare_router)
router.include_router(workboard_router)
router.include_router(conversation_router)
router.include_router(auth_router)
router.include_router(safety_router)

__all__ = ["router"]
