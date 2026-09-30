"""批改任务：从作答组装上下文 → 跑批改图 → 落库 → 更新画像。

在后台任务里执行。模型批改一题要 30—90 秒，不能卡住 HTTP 请求；
前端轮询作答状态，批改过程中可以离开页面。
"""
from __future__ import annotations

import asyncio
import traceback

from sqlalchemy import select

from app.data.sample_papers import DEFAULT_WORD_RULE, DIMENSIONS
from app.db.models import AnswerVersion, Material, Question, Review, ScoringPoint, Submission
from app.core.config import settings
from app.db.session import SessionLocal
from app.grading.graph import run_grading
from app.grading.scoring import GradingContext
from app.services import ocr, profile
from app.services.rubric import active_rubric, ensure_rubric

_running: set[asyncio.Task] = set()


def start(submission_id: int, version_id: int) -> None:
    task = asyncio.create_task(_run(submission_id, version_id))
    _running.add(task)  # 持有引用，否则任务可能在执行中被垃圾回收
    task.add_done_callback(_running.discard)


async def build_context(db, sub: Submission, version: AnswerVersion) -> GradingContext:
    q = await db.get(Question, sub.question_id) if sub.question_id else None
    ocr_factor = ocr.ocr_quality_factor(sub.ocr_source, sub.ocr_lines or [])
    if not q:
        qtype = sub.custom_qtype or "summary"
        return GradingContext(
            qtype=qtype, stem=sub.custom_stem, full_score=sub.custom_full_score or 20,
            word_min=0, word_max=0, dimensions=DIMENSIONS[qtype], points=[],
            word_rule=DEFAULT_WORD_RULE, materials=[], answer=version.text,
            match_level="generic", ocr_factor=ocr_factor)

    # 真题、模拟卷第一次批改时没有评分点：有模型就先生成一份并落库，之后每次批改共用
    if settings.llm_enabled:
        rubric = await ensure_rubric(db, q)
    else:
        rubric = await active_rubric(db, q.id)
    points = []
    if rubric:
        points = [{"id": p.id, "label": p.label, "material_ref": p.material_ref,
                   "keywords": p.keywords, "partial": p.partial, "unacceptable": p.unacceptable,
                   "score": p.score}
                  for p in (await db.execute(select(ScoringPoint).where(
                      ScoringPoint.rubric_id == rubric.id).order_by(ScoringPoint.id))).scalars()]
    mats = (await db.execute(select(Material).where(
        Material.paper_id == q.paper_id, Material.no.in_(q.material_refs or []))
        .order_by(Material.no, Material.paragraph))).scalars().all()
    return GradingContext(
        qtype=q.qtype, stem=q.stem, full_score=q.full_score, word_min=q.word_min,
        word_max=q.word_max, dimensions=(rubric.dimensions if rubric else DIMENSIONS[q.qtype]),
        points=points, word_rule=(rubric.word_rule if rubric else DEFAULT_WORD_RULE),
        materials=[{"no": m.no, "paragraph": m.paragraph, "text": m.text} for m in mats],
        answer=version.text, match_level=sub.match_level or "exact", ocr_factor=ocr_factor,
        format_req=q.format_req, reference_answer=q.reference_answer,
        rubric_id=rubric.id if rubric else None, rubric_version=rubric.version if rubric else "",
        rubric_ai=bool(rubric and rubric.source.startswith("AI")))


async def gradable_offline(db, question_id: int | None) -> bool:
    """未配置模型时，这道题能不能用规则引擎批：需要有带关键词的评分点（大作文除外）。"""
    if not question_id:
        return False
    q = await db.get(Question, question_id)
    if not q:
        return False
    if q.qtype == "essay":
        return True
    r = await active_rubric(db, q.id)
    return bool(r and (await db.execute(select(ScoringPoint.id).where(
        ScoringPoint.rubric_id == r.id).limit(1))).first())


# 同一道题的评分配置只能生成一次：整卷批改时同题多份答卷可能并发触发生成
_rubric_locks: dict[int, asyncio.Lock] = {}
# 整卷一次提交 5 道题，限制同时跑的批改数，避免把网关打满
_slots = asyncio.Semaphore(3)


async def _run(submission_id: int, version_id: int) -> None:
    async with _slots:
        await _run_one(submission_id, version_id)


async def _run_one(submission_id: int, version_id: int) -> None:
    async with SessionLocal() as db:
        sub = await db.get(Submission, submission_id)
        version = await db.get(AnswerVersion, version_id)
        if not sub or not version:
            return
        try:
            lock = _rubric_locks.setdefault(sub.question_id or 0, asyncio.Lock())
            async with lock:
                ctx = await build_context(db, sub, version)
                # 评分配置先提交：SQLite 写锁不能跨越后面几十秒的模型调用
                await db.commit()
            r = await run_grading(ctx)
            review = Review(
                submission_id=sub.id, answer_version_id=version.id, method=r["method"],
                model=r["model"], prompt_version=r["prompt_version"], rubric_id=ctx.rubric_id,
                rubric_version=ctx.rubric_version, full_score=r["full_score"], score=r["score"],
                score_low=r["score_low"], score_high=r["score_high"], confidence=r["confidence"],
                confidence_factors=r["confidence_factors"], dimensions=r["dimensions"],
                points=r["points"], annotations=r["annotations"], suggestions=r["suggestions"],
                diagnosis=r["diagnosis"], hints=r["hints"], word_count=r["word_count"],
                word_penalty=r["word_penalty"], trace=r["trace"], notice=r["notice"],
                review_status="queued" if r["needs_review"] else "none",
            )
            db.add(review)
            await db.flush()
            await profile.update_after_review(db, sub.user_id, sub, review, ctx.qtype)
            sub.status, sub.error = "graded", ""
            await db.commit()
        except Exception as e:  # noqa: BLE001
            await db.rollback()
            sub = await db.get(Submission, submission_id)
            sub.status, sub.error = "failed", f"{type(e).__name__}: {str(e)[:300]}"
            await db.commit()
            traceback.print_exc()
