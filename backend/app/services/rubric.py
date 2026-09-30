"""为没有评分配置的题目生成评分配置（真题、AI 模拟卷）。

真题没有公开的阅卷细则，机构参考答案也不收录，所以评分点由模型按材料生成：
- 每个评分点带材料依据和关键词组。关键词组让规则引擎也能用这份配置（模型不可用时降级）。
- 生成一次就落库，之后同一道题的每次批改、每次复评都用同一份配置，分数前后可比。
- 来源标注「AI 生成，待教研确认」，置信度里的题目匹配系数按 0.85 计（见需求修订说明）。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.data.sample_papers import DEFAULT_WORD_RULE, DIMENSIONS
from app.db.models import QTYPES, Material, Question, Rubric, ScoringPoint
from app.llm.client import LLMError, complete_json

AI_SOURCE = "AI 生成，待教研确认"

RUBRIC_SYSTEM = """你是浙江省考申论教研员，为一道题制定评分细则。只依据给定材料，不引入材料外的内容。

要求：
1. 列出 3—8 个评分点。每个评分点是材料中能找到依据的一个要点，写明依据在哪则材料第几段。
   label 是要点的短语概括，不超过 20 字（如「补齐冷链物流短板」），不要把整条答案写进去。
2. 各评分点分值之和必须等于给定的「要点满分」，每点 1—4 分，可用 0.5。
3. keywords 是判定命中的关键词组：外层数组是「且」，内层数组是同义词「或」。
   第一组必须是这个要点的核心对象（名词），后面的组是限定它的谓词或修饰。每组 2—6 个词，
   覆盖考生可能的不同说法，每个词 2—6 个字。例：[["老人","老年人","老年群体"],["不会用","使用困难","数字鸿沟"]]
4. partial 列 0—3 个「方向对但不完整」的说法。
5. reference_answer：按题目字数要求写一份示范答案，覆盖全部评分点。
只输出 JSON：
{"points":[{"label":"...","material_ref":"材料2第3段","score":2,"keywords":[["..."],["..."]],"partial":["..."]}],
 "reference_answer":"..."}"""


class PointDraft(BaseModel):
    label: str = Field(min_length=2, max_length=80)
    material_ref: str = ""
    score: float = Field(gt=0, le=10)
    keywords: list[list[str]] = Field(min_length=1)
    partial: list[str] = []


class RubricDraft(BaseModel):
    points: list[PointDraft] = Field(min_length=1, max_length=12)
    reference_answer: str = ""


def points_budget(qtype: str, full_score: float) -> float:
    level = sum(d.get("max", 0) for d in DIMENSIONS[qtype] if d["mode"] == "level")
    return max(1.0, full_score - level)


async def active_rubric(db, question_id: int) -> Rubric | None:
    return (await db.execute(select(Rubric).where(
        Rubric.question_id == question_id, Rubric.active.is_(True))
        .order_by(Rubric.id.desc()).limit(1))).scalar_one_or_none()


async def ensure_rubric(db, q: Question) -> Rubric:
    """返回题目的评分配置；没有（或是没有评分点的非作文题）就生成一份。

    大作文只有等级型维度，不需要评分点，直接建配置。模型不可用时抛 LLMError。
    """
    r = await active_rubric(db, q.id)
    if r and (q.qtype == "essay" or await _has_points(db, r.id)):
        return r
    if q.qtype == "essay":
        r = Rubric(question_id=q.id, dimensions=DIMENSIONS["essay"], word_rule=DEFAULT_WORD_RULE,
                   source=AI_SOURCE, notes="大作文按等级型维度评分，无评分点")
        db.add(r)
        await db.flush()
        return r

    stmt = select(Material).where(Material.paper_id == q.paper_id)
    if q.material_refs:
        stmt = stmt.where(Material.no.in_(q.material_refs))
    mats = (await db.execute(stmt.order_by(Material.no, Material.paragraph))).scalars().all()
    if not mats:
        raise LLMError("这道题没有材料原文，无法生成评分配置")
    budget = points_budget(q.qtype, q.full_score)
    user = (f"【题型】{QTYPES[q.qtype]}\n【题干】{q.stem}\n【题目满分】{q.full_score}\n"
            f"【要点满分】{budget}（其余分数给表达、格式等等级型维度，你不用管）\n"
            f"【字数】{q.word_min or '不限'}—{q.word_max or '不限'}\n【材料】\n"
            + "\n".join(f"［材料{m.no}第{m.paragraph}段］{m.text}" for m in mats))
    draft, _model = await complete_json(system=RUBRIC_SYSTEM, user=user, schema=RubricDraft,
                                        tier="large", max_tokens=6000)

    # 模型给的分值之和常有偏差，按比例拉回要点满分，保证分数核算自洽
    total = sum(p.score for p in draft.points)
    scale = budget / total if total else 1
    if r:
        r.active = False
    r = Rubric(question_id=q.id, dimensions=DIMENSIONS[q.qtype], word_rule=DEFAULT_WORD_RULE,
               source=AI_SOURCE, version=f"ai-{datetime.now():%Y%m%d%H%M}",
               notes="评分点由模型按材料生成，未经教研确认")
    db.add(r)
    await db.flush()
    for p in draft.points:
        groups = [[w.strip() for w in g if w.strip()] for g in p.keywords]
        db.add(ScoringPoint(rubric_id=r.id, label=p.label, material_ref=p.material_ref,
                            keywords=[g for g in groups if g], partial=p.partial,
                            score=round(p.score * scale * 2) / 2 or 0.5))
    if draft.reference_answer and not q.reference_answer:
        q.reference_answer = draft.reference_answer
    await db.flush()
    return r


async def _has_points(db, rubric_id: int) -> bool:
    return (await db.execute(select(ScoringPoint.id).where(
        ScoringPoint.rubric_id == rubric_id).limit(1))).first() is not None
