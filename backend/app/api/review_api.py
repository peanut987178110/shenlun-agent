"""批改结果：报告、分层提示、版本对比、评分申诉。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import current_user, own_submission
from app.db.models import AnswerVersion, Appeal, Review, User
from app.db.session import get_db
from app.grading import rules
from app.grading.scoring import confidence_band
from app.services import versions
from app.services.grading_service import build_context
from app.services.text import normalize

router = APIRouter(prefix="/reviews", tags=["批改结果"])

DISCLAIMER = "模拟评分，仅供训练参考，不等同于正式考试分数，也不代表与阅卷结果一致。"
KIND_LABEL = {"original": "原始答案", "self_revised": "自改版", "guided": "AI 指导版",
              "timed_rewrite": "限时重写版"}


async def _load(db, u: User, rid: int) -> tuple[Review, AnswerVersion]:
    r = await db.get(Review, rid)
    if not r:
        raise HTTPException(404, "批改结果不存在")
    await own_submission(db, u, r.submission_id)
    return r, await db.get(AnswerVersion, r.answer_version_id)


def review_out(r: Review, v: AnswerVersion, appeals: list[Appeal]) -> dict:
    return {
        "id": r.id, "submission_id": r.submission_id, "created_at": r.created_at.strftime("%Y-%m-%d %H:%M"),
        "version": {"id": v.id, "version_no": v.version_no, "kind": v.kind,
                    "kind_label": KIND_LABEL.get(v.kind, v.kind), "text": v.text},
        "method": r.method, "method_label": "模型评分" if r.method == "llm" else "规则评分",
        "model": r.model, "prompt_version": r.prompt_version, "rubric_version": r.rubric_version,
        "full_score": r.full_score, "score": r.score, "score_low": r.score_low,
        "score_high": r.score_high, "confidence": r.confidence,
        "confidence_band": confidence_band(r.confidence), "confidence_factors": r.confidence_factors,
        "dimensions": r.dimensions, "points": r.points, "annotations": r.annotations,
        "suggestions": r.suggestions, "diagnosis": r.diagnosis, "word_count": r.word_count,
        "word_penalty": r.word_penalty, "trace": r.trace, "notice": r.notice,
        "disclaimer": DISCLAIMER, "hint_level": r.hint_level,
        "review_status": r.review_status, "teacher_score": r.teacher_score,
        "teacher_note": r.teacher_note,
        "appeals": [{"id": a.id, "point_label": a.point_label, "reason": a.reason,
                     "status": a.status, "recheck": a.recheck, "decision": a.decision}
                    for a in appeals],
    }


@router.get("/{rid}")
async def get_review(rid: int, u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    r, v = await _load(db, u, rid)
    appeals = (await db.execute(select(Appeal).where(Appeal.review_id == rid))).scalars().all()
    return review_out(r, v, list(appeals))


@router.post("/{rid}/hints/{level}")
async def unlock_hint(rid: int, level: int, u: User = Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    """逐级解锁：只返回到请求的级别为止，且必须按顺序解锁，不能直接跳到参考答案。"""
    if level not in (1, 2, 3, 4):
        raise HTTPException(400, "提示级别为 1—4")
    r, _ = await _load(db, u, rid)
    if level > r.hint_level + 1:
        raise HTTPException(400, f"请先查看第 {r.hint_level + 1} 级提示")
    r.hint_level = max(r.hint_level, level)
    await db.commit()
    return {"hint_level": r.hint_level,
            "hints": {f"L{i}": r.hints.get(f"L{i}") for i in range(1, r.hint_level + 1)}}


@router.get("/{rid}/compare/{other}")
async def compare(rid: int, other: int, u: User = Depends(current_user),
                  db: AsyncSession = Depends(get_db)):
    new, nv = await _load(db, u, rid)
    old, ov = await _load(db, u, other)
    if new.submission_id != old.submission_id:
        raise HTTPException(400, "只能对比同一作答的不同版本")
    out = versions.compare(old, new, ov.text, nv.text)
    out["old_version"] = {"no": ov.version_no, "kind": KIND_LABEL.get(ov.kind)}
    out["new_version"] = {"no": nv.version_no, "kind": KIND_LABEL.get(nv.kind)}
    return out


class AppealReq(BaseModel):
    point_id: int
    reason: str = Field(min_length=4, max_length=500)


@router.post("/{rid}/appeals")
async def appeal(rid: int, body: AppealReq, u: User = Depends(current_user),
                 db: AsyncSession = Depends(get_db)):
    """评分申诉（PRD 差异化五）。

    先自动重检：原文复查（考生指出的表述是否在答案里）+ 规则重匹配；
    重检结论只作参考，申诉一律进入教师复核队列，由教师给最终结论。
    """
    r, v = await _load(db, u, rid)
    sub = await own_submission(db, u, r.submission_id)
    if sub.user_id != u.id:
        raise HTTPException(403, "只能申诉自己的批改结果")
    point = next((p for p in r.points if p["id"] == body.point_id), None)
    if not point:
        raise HTTPException(404, "评分点不存在")

    ctx = await build_context(db, sub, v)
    raw = next((p for p in ctx.points if p["id"] == body.point_id), None)
    recheck: dict = {"original_status": point["status"]}
    if raw:
        rm = rules.match_point(raw, v.text)
        recheck["rule_status"] = rm["status"]
        recheck["rule_quote"] = rm["quote"]
    # 考生在申诉理由里引用的原文，确实出现在答案中吗
    quoted = [s for s in body.reason.replace("“", "「").replace("”", "」").split("「")[1:]]
    quoted = [s.split("」")[0] for s in quoted]
    recheck["quoted_found"] = [q for q in quoted if q and normalize(q) in normalize(v.text)]
    recheck["note"] = ("规则重检认为可能命中，建议教师重点核对" if recheck.get("rule_status") in ("hit", "partial")
                       and point["status"] == "miss" else "重检未发现明显漏判，由教师复核给出最终结论")
    recheck["llm_available"] = settings.llm_enabled

    a = Appeal(review_id=rid, user_id=u.id, point_label=point["label"], reason=body.reason,
               status="rechecked", recheck=recheck)
    db.add(a)
    r.review_status = "queued"
    await db.commit()
    return {"id": a.id, "status": a.status, "recheck": recheck,
            "message": "申诉已提交，已进入教师复核队列"}


@router.get("/{rid}/appeals")
async def list_appeals(rid: int, u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await _load(db, u, rid)
    return [{"id": a.id, "point_label": a.point_label, "reason": a.reason, "status": a.status,
             "recheck": a.recheck, "decision": a.decision,
             "resolved_at": a.resolved_at.strftime("%m-%d %H:%M") if a.resolved_at else None}
            for a in (await db.execute(select(Appeal).where(Appeal.review_id == rid))).scalars()]
