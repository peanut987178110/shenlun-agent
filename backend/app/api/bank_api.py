"""题库浏览。

学员端不返回评分点关键词和参考答案：评分点是评分依据，提前看到就成了背答案；
参考答案按分层提示解锁（见 review_api.hints）。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import current_user
from app.data.papers_loader import PAPERS_DIR, validate
from app.db.seed import add_real_paper, delete_paper, paper_in_use
from app.services.paper_import import parse_paper
from app.db.models import ORIGINS, PAPER_CODES, QTYPES, Material, Paper, Question, Rubric, User
from app.db.session import get_db

router = APIRouter(prefix="/bank", tags=["题库"])


def question_out(q: Question, rubric: Rubric | None = None) -> dict:
    return {"id": q.id, "paper_id": q.paper_id, "no": q.no, "qtype": q.qtype,
            "qtype_label": QTYPES.get(q.qtype, q.qtype), "stem": q.stem, "full_score": q.full_score,
            "word_min": q.word_min, "word_max": q.word_max, "material_refs": q.material_refs,
            "format_req": q.format_req, "theme": q.theme,
            "rubric": ({"version": rubric.version, "source": rubric.source,
                        "updated_at": rubric.updated_at.strftime("%Y-%m-%d"),
                        "dimensions": [{"name": d["name"], "mode": d["mode"]} for d in rubric.dimensions]}
                       if rubric else None)}


def paper_out(p: Paper) -> dict:
    return {"id": p.id, "name": p.name, "exam": p.exam, "year": p.year, "code": p.code,
            "category": p.category or PAPER_CODES.get(p.code, ""), "theme": p.theme,
            "topic": p.topic, "origin": p.origin, "origin_label": ORIGINS.get(p.origin, p.origin),
            "status": p.status, "status_note": p.status_note, "exam_date": p.exam_date,
            "sources": p.sources, "is_sample": p.origin == "sample",
            "created_at": p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else ""}


@router.get("/papers")
async def papers(year: int | None = None, code: str | None = None, origin: str | None = None,
                 u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """真题按年份倒序、卷别排序；AI 模拟卷只列自己生成的（教师可见全部）。"""
    stmt = select(Paper)
    if year:
        stmt = stmt.where(Paper.year == year)
    if code:
        stmt = stmt.where(Paper.code == code)
    if origin:
        stmt = stmt.where(Paper.origin == origin)
    ps = [p for p in (await db.execute(stmt.order_by(Paper.year.desc(), Paper.code, Paper.id))).scalars()
          if p.origin != "generated" or p.created_by == u.id or u.role == "teacher"]
    qs = (await db.execute(select(Question).order_by(Question.paper_id, Question.no))).scalars().all()
    by_paper: dict[int, list] = {}
    for q in qs:
        by_paper.setdefault(q.paper_id, []).append(question_out(q))
    return [{**paper_out(p), "questions": by_paper.get(p.id, [])} for p in ps]


class ImportPreview(BaseModel):
    year: int = Field(ge=2010, le=2100)
    code: str = Field(pattern="^[ABC]$")
    text: str = Field(min_length=200, max_length=60000)


@router.post("/import/preview")
async def import_preview(body: ImportPreview, _: User = Depends(current_user)):
    """粘贴整套卷的文本，按规则切分，返回预览和校验问题。不保存。"""
    d = parse_paper(body.text, body.year, body.code)
    d["sources"] = [{"url": "manual://import", "note": "用户粘贴导入"}]
    return {"paper": d, "errors": validate(d, f"{body.year}_{body.code}.json")}


class ImportSave(BaseModel):
    paper: dict
    source_url: str = Field(default="", max_length=500)
    replace: bool = False


@router.post("/import")
async def import_save(body: ImportSave, _: User = Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    """保存导入的真题：写入 app/data/papers/{年度}_{卷别}.json（随仓库分发），并导入题库。

    同一年同一卷已存在时，需要 replace=True；已经有人作答过的旧卷不能替换，避免历史记录失去题目。
    """
    d = dict(body.paper)
    d["sources"] = [{"url": body.source_url.strip() or "manual://import", "note": "用户粘贴导入，材料与题干为原文"}]
    fname = f"{d.get('year')}_{d.get('code')}.json"
    errs = validate(d, fname)
    if errs:
        raise HTTPException(400, "；".join(errs[:5]))
    old = (await db.execute(select(Paper).where(Paper.origin == "real",
                                                Paper.source_key == fname[:-5]))).scalar_one_or_none()
    if old:
        if not body.replace:
            raise HTTPException(409, f"题库里已有 {d['name']}，确认要替换请勾选「替换已有试卷」")
        if await paper_in_use(db, old.id):
            raise HTTPException(409, f"{d['name']} 已经有人作答过，不能替换（历史批改记录会失去题目）")
        await delete_paper(db, old.id)
    (PAPERS_DIR / fname).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    p = await add_real_paper(db, d)
    await db.commit()
    return paper_out(p)


@router.get("/papers/{paper_id}")
async def paper_detail(paper_id: int, u: User = Depends(current_user),
                       db: AsyncSession = Depends(get_db)):
    p = await db.get(Paper, paper_id)
    if not p or (p.origin == "generated" and p.created_by != u.id and u.role != "teacher"):
        raise HTTPException(404, "试卷不存在")
    mats = (await db.execute(select(Material).where(Material.paper_id == paper_id)
                             .order_by(Material.no, Material.paragraph))).scalars().all()
    qs = (await db.execute(select(Question).where(Question.paper_id == paper_id)
                           .order_by(Question.no))).scalars().all()
    rubrics = {r.question_id: r for r in (await db.execute(select(Rubric).where(
        Rubric.question_id.in_([q.id for q in qs]), Rubric.active.is_(True)))).scalars()}
    return {**paper_out(p),
            "materials": [{"no": m.no, "paragraph": m.paragraph, "text": m.text} for m in mats],
            "questions": [question_out(q, rubrics.get(q.id)) for q in qs]}
