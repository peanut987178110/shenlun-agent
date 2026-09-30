"""系统状态。模型网关的地址和密钥只在 backend/.env 中配置，不经接口读写，避免密钥落库或回显。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.deps import current_user, require_teacher
from app.db.models import User
from app.llm.client import ping

router = APIRouter(prefix="/system", tags=["系统"])


@router.get("/status")
async def status(_: User = Depends(current_user)):
    return {"app": settings.app_name, "version": settings.app_version,
            "llm_enabled": settings.llm_enabled, "llm_provider": settings.llm_provider_label,
            "models": {"medium": settings.llm_model_medium, "large": settings.llm_model_large,
                       "vision": settings.llm_model_vision} if settings.llm_enabled else None,
            "max_upload_mb": settings.max_upload_mb, "max_pages": settings.max_pages}


@router.post("/ping")
async def ping_llm(_: User = Depends(require_teacher)):
    ok, msg = await ping()
    return {"ok": ok, "message": msg}
