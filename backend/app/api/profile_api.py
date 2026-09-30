"""首页看板、能力画像、错误模式库、训练处方。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.bank_api import question_out
from app.core.deps import current_user
from app.db.models import (QTYPES, AbilityRecord, ErrorPattern, Prescription, Question, Review,
                           Sheet, Submission, User)
from app.db.session import get_db
from app.services.profile import ABILITIES

router = APIRouter(prefix="/profile", tags=["学习画像"])


@router.get("/dashboard")
async def dashboard(u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Review, Submission).join(
        Submission, Review.submission_id == Submission.id).where(
        Submission.user_id == u.id).order_by(Review.id))).all()
    # 每个作答只取最新一次批改计入平均分，避免反复修改同一题把平均分刷高
    latest: dict[int, Review] = {}
    for r, s in rows:
        latest[s.id] = r
    rates = [100 * r.score / r.full_score for r in latest.values() if r.full_score]
    trend = [{"date": r.created_at.strftime("%m-%d"), "rate": round(100 * r.score / r.full_score, 1)}
             for r, _ in rows[-12:] if r.full_score]
    errors = (await db.execute(select(ErrorPattern).where(ErrorPattern.user_id == u.id)
                               .order_by(ErrorPattern.frequency.desc()).limit(3))).scalars().all()
    rx = (await db.execute(select(Prescription).where(
        Prescription.user_id == u.id, Prescription.status == "active")
        .order_by(Prescription.id.desc()).limit(1))).scalar_one_or_none()
    # 待复盘：批改过但只有原始版本、还没有二次修改的作答
    pending = []
    for sid, r in list(latest.items())[-20:]:
        if r.score < r.full_score * 0.8:
            s = await db.get(Submission, sid)
            n_versions = len({x.answer_version_id for x, ss in rows if ss.id == sid})
            if n_versions == 1:
                q = await db.get(Question, s.question_id) if s.question_id else None
                pending.append({"submission_id": sid, "review_id": r.id, "score": r.score,
                                "full_score": r.full_score,
                                "question": f"{q.theme}·{QTYPES.get(q.qtype)}" if q else "自定义题目"})
    return {
        "goal": {"exam": "浙江省考", "year": u.exam_year, "category": u.exam_category,
                 "target_score": u.target_score, "exam_date": u.exam_date},
        "count": len(latest),
        "avg_rate": round(sum(rates) / len(rates), 1) if rates else None,
        "last": ({"score": rows[-1][0].score, "full_score": rows[-1][0].full_score,
                  "review_id": rows[-1][0].id} if rows else None),
        "trend": trend,
        "top_errors": [{"error_type": e.error_type, "frequency": e.frequency,
                        "mastery_status": e.mastery_status} for e in errors],
        "pending_review": pending[-5:],
        "today_prescription": _rx_out(rx) if rx else None,
    }


@router.get("/abilities")
async def abilities(u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    recs = {r.dimension: r for r in (await db.execute(select(AbilityRecord).where(
        AbilityRecord.user_id == u.id))).scalars()}
    return [{"dimension": d, "score": recs[d].score if d in recs else None,
             "evidence_count": recs[d].evidence_count if d in recs else 0,
             "trend": recs[d].trend if d in recs else "", "mastery": recs[d].mastery if d in recs else "未建立"}
            for d in ABILITIES]


@router.get("/errors")
async def errors(u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    es = (await db.execute(select(ErrorPattern).where(ErrorPattern.user_id == u.id)
                           .order_by(ErrorPattern.frequency.desc()))).scalars().all()
    return [{"error_type": e.error_type, "frequency": e.frequency,
             "recent_frequency": e.recent_frequency, "severity": e.severity,
             "trigger_conditions": e.trigger_conditions,
             "recommended_training": e.recommended_training, "mastery_status": e.mastery_status,
             "example": e.example, "last_seen_at": e.last_seen_at.strftime("%Y-%m-%d")} for e in es]


def _rx_out(p: Prescription) -> dict:
    return {"id": p.id, "error_type": p.error_type, "goal": p.goal, "frequency": p.frequency,
            "impact": p.impact, "steps": p.steps, "est_minutes": p.est_minutes,
            "pass_criteria": p.pass_criteria, "retest_question_id": p.retest_question_id,
            "retest_submission_id": p.retest_submission_id, "retest_after": p.retest_after,
            "status": p.status, "result": p.result,
            "created_at": p.created_at.strftime("%Y-%m-%d")}


@router.get("/prescriptions")
async def prescriptions(u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    ps = (await db.execute(select(Prescription).where(Prescription.user_id == u.id)
                           .order_by(Prescription.id.desc()))).scalars().all()
    out = []
    for p in ps:
        q = await db.get(Question, p.retest_question_id) if p.retest_question_id else None
        out.append({**_rx_out(p), "retest_question": question_out(q) if q else None})
    return out


@router.post("/prescriptions/{pid}/retest")
async def start_retest(pid: int, u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """开始复测：为处方的复测题建一次作答，批改完成后自动判定处方是否通过。"""
    p = await db.get(Prescription, pid)
    if not p or p.user_id != u.id:
        raise HTTPException(404, "处方不存在")
    if p.status != "active":
        raise HTTPException(400, "处方已结束")
    if not p.retest_question_id:
        raise HTTPException(400, "题库中没有可用的复测题")
    q = await db.get(Question, p.retest_question_id)
    if not q:
        raise HTTPException(400, "复测题已不在题库中")
    s = Sheet(user_id=u.id, paper_id=q.paper_id, question_ids=[q.id])
    db.add(s)
    await db.commit()
    return {"sheet_id": s.id}
