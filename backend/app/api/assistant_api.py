"""对话助手与 AI 出题。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.assistant import chat
from app.api.bank_api import paper_out
from app.core.config import settings
from app.core.deps import current_user
from app.db.models import PAPER_CODES, Paper, User
from app.db.session import get_db
from app.services import generator

router = APIRouter(tags=["助手与出题"])


class ChatReq(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, str]] = []


@router.post("/assistant/chat")
async def assistant_chat(body: ChatReq, u: User = Depends(current_user)):
    return await chat(u.id, u.role, body.message, body.history)


class GenReq(BaseModel):
    code: str = Field(pattern="^[ABC]$")
    theme: str = Field(default="", max_length=60)


@router.post("/generate")
async def generate(body: GenReq, u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if not settings.llm_enabled:
        raise HTTPException(400, "AI 出题需要模型网关，当前未配置")
    running = (await db.execute(select(Paper.id).where(
        Paper.created_by == u.id, Paper.status == "generating").limit(1))).first()
    if running:
        raise HTTPException(409, "你有一套卷正在生成，完成后再出下一套")
    p = await generator.create_job(db, u.id, body.code, body.theme.strip())
    return paper_out(p)


@router.get("/generate")
async def my_generated(u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    ps = (await db.execute(select(Paper).where(Paper.origin == "generated", Paper.created_by == u.id)
                           .order_by(Paper.id.desc()).limit(30))).scalars().all()
    return {"codes": PAPER_CODES, "papers": [paper_out(p) for p in ps]}
