"""单题作答：详情、修改复评。作答由答卷提交时按题创建（见 sheet_api）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.bank_api import question_out
from app.core.deps import current_user, own_submission
from app.db.models import AnswerVersion, Question, Review, User
from app.db.session import get_db
from app.services import grading_service
from app.services.text import mask_pii, word_count

router = APIRouter(prefix="/submissions", tags=["作答"])


async def _latest_version(db, sid: int) -> AnswerVersion | None:
    return (await db.execute(select(AnswerVersion).where(AnswerVersion.submission_id == sid)
                             .order_by(AnswerVersion.version_no.desc()).limit(1))).scalar_one_or_none()


class ReviseReq(BaseModel):
    text: str = Field(min_length=5, max_length=20000)
    kind: str = "self_revised"  # self_revised / timed_rewrite


@router.post("/{sid}/revise")
async def revise(sid: int, body: ReviseReq, u: User = Depends(current_user),
                 db: AsyncSession = Depends(get_db)):
    """二次修改：保存新版本并复评。解锁过局部示范以上的提示，自动记为「AI 指导版」。"""
    sub = await own_submission(db, u, sid)
    if sub.user_id != u.id:
        raise HTTPException(403, "只能修改自己的作答")
    if sub.status == "grading":
        raise HTTPException(409, "正在批改中")
    last = await _latest_version(db, sid)
    if not last:
        raise HTTPException(400, "还没有原始答案")
    last_review = (await db.execute(select(Review).where(Review.submission_id == sid)
                                    .order_by(Review.id.desc()).limit(1))).scalar_one_or_none()
    kind = body.kind if body.kind in ("self_revised", "timed_rewrite") else "self_revised"
    if last_review and last_review.hint_level >= 3 and kind == "self_revised":
        kind = "guided"
    text = mask_pii(body.text)
    v = AnswerVersion(submission_id=sid, version_no=last.version_no + 1, kind=kind, text=text,
                      word_count=word_count(text))
    db.add(v)
    sub.status = "grading"
    await db.commit()
    grading_service.start(sid, v.id)
    return {"status": "grading", "version_id": v.id, "kind": kind}


@router.get("/{sid}")
async def detail(sid: int, u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    sub = await own_submission(db, u, sid)
    versions = (await db.execute(select(AnswerVersion).where(AnswerVersion.submission_id == sid)
                                 .order_by(AnswerVersion.version_no))).scalars().all()
    reviews = (await db.execute(select(Review).where(Review.submission_id == sid)
                                .order_by(Review.id))).scalars().all()
    q = await db.get(Question, sub.question_id) if sub.question_id else None
    by_version = {r.answer_version_id: r for r in reviews}
    return {
        "id": sub.id, "sheet_id": sub.sheet_id, "status": sub.status, "error": sub.error,
        "question": question_out(q) if q else None,
        "versions": [{"id": v.id, "version_no": v.version_no, "kind": v.kind, "text": v.text,
                      "word_count": v.word_count, "created_at": v.created_at.strftime("%m-%d %H:%M"),
                      "review_id": by_version[v.id].id if v.id in by_version else None,
                      "score": by_version[v.id].score if v.id in by_version else None}
                     for v in versions],
        "latest_review_id": reviews[-1].id if reviews else None,
    }
