"""教师复核（PRD 用户故事 5）。

队列只含低置信度和被申诉的批改。学员身份在队列中脱敏为「学员 #编号」（PRD 19.4 复核数据脱敏）。
教师改判保留 AI 原判（ai_status），这是后续校准评分模型的数据来源（教师校准体系）。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.bank_api import question_out
from app.api.review_api import review_out
from app.core.deps import require_teacher
from app.db.models import QTYPES, AnswerVersion, Appeal, Question, Review, Submission, User
from app.db.session import get_db
from app.grading.scoring import STATUS_CREDIT, STATUS_LABEL

router = APIRouter(prefix="/teacher", tags=["教师复核"])


@router.get("/queue")
async def queue(status: str = "queued", _: User = Depends(require_teacher),
                db: AsyncSession = Depends(get_db)):
    if status not in ("queued", "reviewed"):
        raise HTTPException(400, "status 只能是 queued 或 reviewed")
    rows = (await db.execute(select(Review, Submission).join(
        Submission, Review.submission_id == Submission.id).where(
        Review.review_status == status).order_by(Review.confidence, Review.id))).all()
    out = []
    for r, s in rows:
        q = await db.get(Question, s.question_id) if s.question_id else None
        n_appeal = len((await db.execute(select(Appeal.id).where(
            Appeal.review_id == r.id, Appeal.status != "resolved"))).all())
        out.append({"review_id": r.id, "student": f"学员 #{s.user_id}",
                    "question": f"{q.theme}·{QTYPES.get(q.qtype)}" if q else "自定义题目",
                    "score": r.score, "full_score": r.full_score, "confidence": r.confidence,
                    "method": r.method, "open_appeals": n_appeal,
                    "reason": "学员申诉" if n_appeal else "低置信度",
                    "created_at": r.created_at.strftime("%m-%d %H:%M")})
    return out


@router.get("/reviews/{rid}")
async def review_detail(rid: int, _: User = Depends(require_teacher),
                        db: AsyncSession = Depends(get_db)):
    r = await db.get(Review, rid)
    if not r or r.review_status == "none":
        raise HTTPException(404, "不在复核队列中")
    v = await db.get(AnswerVersion, r.answer_version_id)
    s = await db.get(Submission, r.submission_id)
    q = await db.get(Question, s.question_id) if s.question_id else None
    appeals = (await db.execute(select(Appeal).where(Appeal.review_id == rid))).scalars().all()
    return {**review_out(r, v, list(appeals)),
            "question": {**question_out(q), "reference_answer": q.reference_answer} if q else None,
            "custom_stem": s.custom_stem, "student": f"学员 #{s.user_id}"}


class PointFix(BaseModel):
    id: int
    status: str
    note: str = Field(default="", max_length=300)


class AppealDecision(BaseModel):
    id: int
    decision: str = Field(min_length=2, max_length=500)


class TeacherReview(BaseModel):
    points: list[PointFix] = []
    teacher_score: float = Field(ge=0)
    note: str = Field(default="", max_length=1000)
    appeals: list[AppealDecision] = []


@router.post("/reviews/{rid}")
async def submit_review(rid: int, body: TeacherReview, t: User = Depends(require_teacher),
                        db: AsyncSession = Depends(get_db)):
    r = await db.get(Review, rid)
    if not r or r.review_status == "none":
        raise HTTPException(404, "不在复核队列中")
    if body.teacher_score > r.full_score:
        raise HTTPException(400, f"分数不能超过满分 {r.full_score}")

    fixes = {f.id: f for f in body.points}
    points = []
    for p in r.points:
        f = fixes.get(p["id"])
        if f and f.status in STATUS_CREDIT and f.status != p["status"]:
            p = {**p, "ai_status": p.get("ai_status", p["status"]), "status": f.status,
                 "status_label": STATUS_LABEL[f.status],
                 "got": round(p["max"] * STATUS_CREDIT[f.status], 2),
                 "reason": f"教师改判：{f.note}" if f.note else "教师改判", "teacher_fixed": True}
        points.append(p)
    r.points = points  # 重新赋值，JSON 列才会被标记为已修改

    now = datetime.now()
    for d in body.appeals:
        a = await db.get(Appeal, d.id)
        if a and a.review_id == rid:
            a.status, a.decision, a.resolved_at = "resolved", d.decision, now
    r.teacher_score, r.teacher_note, r.teacher_id = body.teacher_score, body.note, t.id
    r.review_status = "reviewed"
    await db.commit()
    return {"ok": True, "review_status": r.review_status}
