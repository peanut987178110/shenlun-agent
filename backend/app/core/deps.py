"""当前用户解析与权限。

只认 `Authorization: Bearer <token>`，没有任何请求头旁路。
数据隔离在查询层做：学员只能读自己的作答；教师只能读进入过复核队列的作答。
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import parse_token
from app.db.models import Review, Submission, User
from app.db.session import get_db

ROLE_STUDENT = "student"
ROLE_TEACHER = "teacher"


async def current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "请先登录")
    payload = parse_token(token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期，请重新登录")
    u = await db.get(User, int(payload.get("u", 0)))
    if not u or not u.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不存在或已停用")
    return u


async def require_teacher(user: User = Depends(current_user)) -> User:
    if user.role != ROLE_TEACHER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅教师可执行此操作")
    return user


async def own_submission(db: AsyncSession, user: User, submission_id: int) -> Submission:
    """取作答并校验访问权。不存在与无权访问返回同一个 404，不暴露他人作答是否存在。

    教师只能看进入过复核队列的作答（低置信度或被申诉），不能浏览任意学员的答卷（PRD 18.3）。
    """
    sub = await db.get(Submission, submission_id)
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作答不存在")
    if sub.user_id == user.id:
        return sub
    if user.role == ROLE_TEACHER:
        queued = (await db.execute(select(Review.id).where(
            Review.submission_id == sub.id, Review.review_status != "none").limit(1))).first()
        if queued:
            return sub
    raise HTTPException(status.HTTP_404_NOT_FOUND, "作答不存在")
