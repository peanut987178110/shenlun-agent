"""账号：注册、登录、目标设置、隐私设置。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import current_user
from app.core.security import hash_password, make_token, password_issue, verify_password
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["账号"])


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role,
            "exam_year": u.exam_year, "exam_category": u.exam_category,
            "target_region": u.target_region, "target_score": u.target_score,
            "current_level": u.current_level, "exam_date": u.exam_date,
            "consent_vision": u.consent_vision, "allow_training_data": u.allow_training_data,
            "goal_set": bool(u.exam_category and u.target_score)}


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_\-]+$")
    password: str
    display_name: str = Field(default="", max_length=32)


@router.post("/register")
async def register(body: Credentials, db: AsyncSession = Depends(get_db)):
    """开放注册只能注册学员。教师账号由已有教师创建，避免任何人自封教师查看他人答卷。"""
    if issue := password_issue(body.password):
        raise HTTPException(400, issue)
    if (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none():
        raise HTTPException(400, "用户名已被使用")
    u = User(username=body.username, password_hash=hash_password(body.password),
             display_name=body.display_name or body.username, role="student")
    db.add(u)
    await db.commit()
    token, exp = make_token(u.id, u.role)
    return {"token": token, "expires_at": exp, "user": user_out(u)}


@router.post("/login")
async def login(body: Credentials, db: AsyncSession = Depends(get_db)):
    u = (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    # 用户名不存在与密码错误返回同一句话，不暴露账号是否存在
    if not u or not u.active or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    token, exp = make_token(u.id, u.role)
    return {"token": token, "expires_at": exp, "user": user_out(u)}


@router.get("/me")
async def me(u: User = Depends(current_user)):
    return {**user_out(u), "llm_enabled": settings.llm_enabled,
            "llm_provider": settings.llm_provider_label}


class Goal(BaseModel):
    exam_year: int | None = Field(default=None, ge=2000, le=2100)
    exam_category: str = Field(default="", max_length=32)
    target_region: str = Field(default="", max_length=32)
    target_score: float | None = Field(default=None, ge=0, le=200)
    current_level: str = Field(default="", max_length=16)
    exam_date: str = Field(default="", max_length=16)
    display_name: str | None = Field(default=None, max_length=32)


@router.put("/me/goal")
async def set_goal(body: Goal, u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(u, k, v)
    await db.commit()
    return user_out(u)


class Privacy(BaseModel):
    consent_vision: bool | None = None
    allow_training_data: bool | None = None


@router.put("/me/privacy")
async def set_privacy(body: Privacy, u: User = Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    if body.consent_vision is not None:
        u.consent_vision = body.consent_vision
    if body.allow_training_data is not None:
        u.allow_training_data = body.allow_training_data
    await db.commit()
    return user_out(u)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


@router.put("/me/password")
async def change_password(body: PasswordChange, u: User = Depends(current_user),
                          db: AsyncSession = Depends(get_db)):
    if not verify_password(body.old_password, u.password_hash):
        raise HTTPException(400, "原密码错误")
    if issue := password_issue(body.new_password):
        raise HTTPException(400, issue)
    u.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"ok": True}


class NewTeacher(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_\-]+$")
    password: str
    display_name: str = Field(default="", max_length=32)


@router.post("/teachers")
async def create_teacher(body: NewTeacher, u: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    if u.role != "teacher":
        raise HTTPException(403, "仅教师可创建教师账号")
    if issue := password_issue(body.password):
        raise HTTPException(400, issue)
    if (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none():
        raise HTTPException(400, "用户名已被使用")
    t = User(username=body.username, password_hash=hash_password(body.password),
             display_name=body.display_name or body.username, role="teacher")
    db.add(t)
    await db.commit()
    return user_out(t)
