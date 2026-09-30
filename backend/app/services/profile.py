"""学习画像：错误模式库、能力画像、训练处方（PRD 14、15）。

每次批改完成后调用 update_after_review。全部是规则计算，不调用模型：
画像要长期累积、前后可比，用模型生成会让同样的表现得出不同结论。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (AbilityRecord, ErrorPattern, Prescription, Question, Review,
                           Submission)
from app.grading.rules import TRAINING

ABILITIES = ["审题", "材料定位", "要点提炼", "概括", "原因分析", "影响分析", "对策设计", "结构组织",
             "分论点设计", "论证", "语言", "格式", "字数", "时间管理", "卷面"]

# 题型得分率主要反映哪些能力
QTYPE_ABILITIES = {
    "summary": ["要点提炼", "概括", "材料定位"],
    "countermeasure": ["对策设计", "材料定位"],
    "analysis": ["原因分析", "影响分析", "审题"],
    "official": ["格式", "语言"],
    "essay": ["论证", "结构组织", "分论点设计"],
}

HIGH_SEVERITY = {"要点遗漏", "对策空泛", "超字数"}

PRESCRIPTIONS = {
    "对策空泛": {
        "goal": "提升对策可操作性",
        "steps": ["完成 5 组「问题—主体—措施」拆解", "完成 3 道 150 字对策题",
                  "不看参考答案重写 1 道旧题", "完成 1 道陌生主题复测题"],
        "pass": ["复测题中不再出现「对策空泛」批注", "对策要点完整命中率 ≥ 60%"],
        "minutes": 60, "qtype": "countermeasure"},
    "要点遗漏": {
        "goal": "提高要点覆盖率",
        "steps": ["逐段标注材料中的问题、原因、对策", "先列要点清单再成文，对照材料逐条核对",
                  "完成 1 道陌生主题复测题"],
        "pass": ["复测题要点完整命中率 ≥ 60%", "未命中的评分点不超过 1 个"],
        "minutes": 45, "qtype": None},
    "原文摘抄": {
        "goal": "从摘抄转向概括",
        "steps": ["把 10 句材料原句各压缩到 10 字以内", "完成 1 道陌生主题复测题"],
        "pass": ["复测题中不再出现「原文摘抄」批注"],
        "minutes": 30, "qtype": "summary"},
    "超字数": {
        "goal": "控制字数",
        "steps": ["写前先列要点和每点字数预算", "完成 2 道限字题并自查字数", "完成 1 道陌生主题复测题"],
        "pass": ["复测题不超出字数上限"],
        "minutes": 30, "qtype": None},
    "格式缺项": {
        "goal": "应用文格式完整",
        "steps": ["默写倡议书、通知、讲话稿的格式要素", "完成 1 道应用文复测题"],
        "pass": ["复测题格式要素齐全"],
        "minutes": 20, "qtype": "official"},
}

RECENT_WINDOW = 5


async def update_after_review(db: AsyncSession, user_id: int, sub: Submission, review: Review,
                              qtype: str) -> None:
    await _update_abilities(db, user_id, review, qtype)
    await _update_errors(db, user_id, sub, review, qtype)
    await _check_retest(db, user_id, sub, review)


async def _update_abilities(db, user_id, review: Review, qtype: str) -> None:
    rate = 100 * review.score / review.full_score if review.full_score else 0
    # 规则评分可信度低，按一半权重计入画像
    weight = 0.5 if review.method == "rule" else 1.0
    for dim in QTYPE_ABILITIES.get(qtype, []):
        rec = (await db.execute(select(AbilityRecord).where(
            AbilityRecord.user_id == user_id, AbilityRecord.dimension == dim))).scalar_one_or_none()
        if not rec:
            rec = AbilityRecord(user_id=user_id, dimension=dim, score=rate, evidence_count=0)
            db.add(rec)
            old = rate
        else:
            old = rec.score
            alpha = 0.3 * weight
            rec.score = round(old * (1 - alpha) + rate * alpha, 1)
        rec.evidence_count = (rec.evidence_count or 0) + 1
        rec.trend = "up" if rec.score > old + 1 else "down" if rec.score < old - 1 else "flat"
        rec.mastery = _mastery(rec.score, rec.evidence_count, rec.trend)
        rec.updated_at = datetime.now()


def _mastery(score: float, n: int, trend: str) -> str:
    if n < 2:
        return "未建立"
    if score >= 75:
        return "稳定迁移" if n >= 4 and trend != "down" else "基本掌握"
    if score >= 60:
        return "不稳定" if trend == "down" else "初步掌握"
    return "未建立" if n < 3 else "不稳定"


async def _update_errors(db, user_id, sub: Submission, review: Review, qtype: str) -> None:
    found = {d["error_type"]: d for d in review.diagnosis}
    recent = (await db.execute(
        select(Review).join(Submission, Review.submission_id == Submission.id)
        .where(Submission.user_id == user_id).order_by(Review.id.desc()).limit(RECENT_WINDOW)
    )).scalars().all()

    existing = {e.error_type: e for e in (await db.execute(
        select(ErrorPattern).where(ErrorPattern.user_id == user_id))).scalars().all()}

    for t, d in found.items():
        e = existing.get(t)
        if not e:
            e = ErrorPattern(user_id=user_id, error_type=t, frequency=0)
            db.add(e)
            existing[t] = e
        e.frequency = (e.frequency or 0) + 1
        e.trigger_conditions = sorted(set((e.trigger_conditions or []) + d["trigger_conditions"]))
        e.recommended_training = TRAINING.get(t, [])
        e.example = d["example"]
        e.last_seen_at = datetime.now()
        e.severity = "high" if t in HIGH_SEVERITY or e.frequency >= 3 else "medium"
        e.mastery_status = "not_mastered"
        await _maybe_prescribe(db, user_id, sub, e)

    # 本次没出现的错误：同题型连续两次没出现视为掌握，一次视为不稳定
    for t, e in existing.items():
        if t in found:
            continue
        e.recent_frequency = sum(1 for r in recent if any(d["error_type"] == t for d in r.diagnosis))
        if e.frequency:
            e.mastery_status = "mastered" if e.recent_frequency == 0 and len(recent) >= 2 else "unstable"
    for t in found:
        existing[t].recent_frequency = sum(
            1 for r in recent if any(d["error_type"] == t for d in r.diagnosis))


async def _maybe_prescribe(db, user_id: int, sub: Submission, e: ErrorPattern) -> None:
    """同一错误出现 2 次、且没有进行中的处方时，开一张处方。"""
    tpl = PRESCRIPTIONS.get(e.error_type)
    if not tpl or e.frequency < 2:
        return
    active = (await db.execute(select(Prescription).where(
        Prescription.user_id == user_id, Prescription.error_type == e.error_type,
        Prescription.status == "active"))).scalar_one_or_none()
    if active:
        active.frequency = e.frequency
        return
    src_q = await db.get(Question, sub.question_id) if sub.question_id else None
    retest = await pick_retest(db, src_q, tpl["qtype"])
    db.add(Prescription(
        user_id=user_id, error_type=e.error_type, goal=tpl["goal"], frequency=e.frequency,
        impact="高" if e.severity == "high" else "中", steps=tpl["steps"],
        est_minutes=tpl["minutes"], pass_criteria=tpl["pass"],
        source_submission_id=sub.id,
        retest_question_id=retest.id if retest else None,
        retest_after=(datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d"),
    ))


async def pick_retest(db, src: Question | None, qtype: str | None) -> Question | None:
    """复测题：同题型、换主题。题库里的现成题，不临时生成（MVP 范围）。"""
    want = qtype or (src.qtype if src else None)
    stmt = select(Question)
    if want:
        stmt = stmt.where(Question.qtype == want)
    qs = (await db.execute(stmt)).scalars().all()
    if src:
        other = [q for q in qs if q.theme != src.theme and q.id != src.id]
        qs = other or [q for q in qs if q.id != src.id]
    return qs[0] if qs else None


async def _check_retest(db, user_id: int, sub: Submission, review: Review) -> None:
    """这次作答如果是某张进行中处方的复测题（处方开出之后作答的），判定处方是否通过。"""
    if not sub.question_id:
        return
    p = (await db.execute(select(Prescription).where(
        Prescription.user_id == user_id, Prescription.status == "active",
        Prescription.retest_question_id == sub.question_id,
        Prescription.created_at <= sub.created_at).limit(1))).scalar_one_or_none()
    if not p:
        return
    p.retest_submission_id = sub.id
    still = any(d["error_type"] == p.error_type for d in review.diagnosis)
    ledger = review.points or []
    hit_rate = sum(1 for x in ledger if x["status"] == "hit") / len(ledger) if ledger else 0
    passed = not still and (hit_rate >= 0.6 or not ledger)
    result = {"review_id": review.id, "error_repeated": still, "hit_rate": round(hit_rate, 2)}

    if not passed and p.source_submission_id:
        # 原题的最新版本里这个问题已经修好，但换了题又出现：原题修复但迁移失败
        last = (await db.execute(select(Review).where(
            Review.submission_id == p.source_submission_id).order_by(Review.id.desc()).limit(1)
        )).scalar_one_or_none()
        if last and not any(d["error_type"] == p.error_type for d in last.diagnosis):
            result["verdict"] = "原题已修复，但迁移到新题失败：方法还没有真正掌握"
    p.status = "passed" if passed else "failed"
    p.result = result
