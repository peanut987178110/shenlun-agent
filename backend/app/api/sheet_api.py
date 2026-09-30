"""答卷流程：选卷 → 上传 / 录入 → 识别 → 按题切分确认 → 每道题分别批改。"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.bank_api import paper_out, question_out
from app.core.config import settings
from app.core.deps import current_user
from app.db.models import (AnswerVersion, Material, Paper, Question, Review, Sheet, SheetPage,
                           Submission, User)
from app.db.session import get_db
from app.services import grading_service, ocr
from app.services.image_quality import check_page, overall_grade
from app.services.sheet import assign_questions, rank_papers, split_answers
from app.services.text import mask_pii, word_count

router = APIRouter(prefix="/sheets", tags=["答卷"])

GRADE_TEXT = {"A": "可稳定识别", "B": "大部分可识别，识别后请重点核对",
              "C": "关键内容可能丢失，建议重拍；也可以继续并手动核对", "D": "无法识别，请重新拍摄"}


async def _own(db, u: User, sid: int) -> Sheet:
    s = await db.get(Sheet, sid)
    if not s or s.user_id != u.id:
        raise HTTPException(404, "答卷不存在")
    return s


async def _questions(db, s: Sheet) -> list[Question]:
    if not s.paper_id:
        return []
    qs = (await db.execute(select(Question).where(Question.paper_id == s.paper_id)
                           .order_by(Question.no))).scalars().all()
    if s.question_ids:
        qs = [q for q in qs if q.id in s.question_ids]
    return list(qs)


def _sniff(data: bytes) -> str:
    """按文件头判断类型，不信任文件名和 Content-Type。"""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:5] == b"%PDF-":
        return "pdf"
    return ""


class NewSheet(BaseModel):
    paper_id: int | None = None
    question_ids: list[int] = []
    time_spent_min: int | None = Field(default=None, ge=0, le=600)


@router.post("")
async def create(body: NewSheet, u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    s = Sheet(user_id=u.id, time_spent_min=body.time_spent_min)
    if body.paper_id:
        await _set_paper(db, s, body.paper_id, body.question_ids)
    db.add(s)
    await db.commit()
    return await detail(s.id, u, db)


async def _set_paper(db, s: Sheet, paper_id: int, question_ids: list[int]) -> None:
    p = await db.get(Paper, paper_id)
    if not p or p.status in ("generating", "failed"):
        raise HTTPException(404, "试卷不存在或还没生成完")
    all_ids = set((await db.execute(select(Question.id).where(Question.paper_id == paper_id))).scalars())
    if question_ids and not set(question_ids) <= all_ids:
        raise HTTPException(400, "所选题目不属于这套试卷")
    s.paper_id, s.question_ids = paper_id, list(question_ids)


@router.post("/{sid}/pages")
async def upload(sid: int, files: list[UploadFile] = File(...), u: User = Depends(current_user),
                 db: AsyncSession = Depends(get_db)):
    s = await _own(db, u, sid)
    if s.status not in ("draft", "recognized"):
        raise HTTPException(400, "答卷已提交批改，不能再追加页面")
    existing = (await db.execute(select(SheetPage).where(SheetPage.sheet_id == sid))).scalars().all()
    hashes = {p.sha256 for p in existing}
    limit = settings.max_upload_mb * 1024 * 1024
    images, pdf_text = [], []
    for f in files:
        data = await f.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"单个文件不能超过 {settings.max_upload_mb} MB")
        kind = _sniff(data)
        if kind in ("jpg", "png"):
            images.append(data)
        elif kind == "pdf":
            try:
                texts = ocr.pdf_text_pages(data)
            except Exception:  # noqa: BLE001
                raise HTTPException(400, "PDF 无法解析") from None
            if sum(word_count(t) for t in texts) >= 20:
                pdf_text += texts
            else:
                images += ocr.pdf_page_images(data)
        else:
            raise HTTPException(400, f"{f.filename}：只支持 JPG、PNG、PDF")
    if len(existing) + len(images) > settings.max_pages:
        raise HTTPException(400, f"每份答卷最多 {settings.max_pages} 页")

    folder = Path(settings.upload_dir) / str(u.id)
    folder.mkdir(parents=True, exist_ok=True)
    no = len(existing) + 1
    for data in images:
        q = check_page(data)
        if q.sha256 in hashes:
            q.issues.append({"level": "C", "type": "重复页", "region": "整页", "message": "与已上传的某一页完全相同"})
            q.grade = "C" if q.grade in ("A", "B") else q.grade
        hashes.add(q.sha256)
        path = folder / f"{secrets.token_hex(12)}.img"  # 随机文件名，不用上传时的文件名
        path.write_bytes(data)
        db.add(SheetPage(sheet_id=sid, page_no=no, file_path=str(path), sha256=q.sha256,
                         grade=q.grade, issues=q.issues, metrics=q.metrics))
        no += 1
    await db.flush()
    grades = [p.grade for p in (await db.execute(select(SheetPage).where(SheetPage.sheet_id == sid))).scalars()]
    s.quality_grade = overall_grade(grades) if grades else ""
    if pdf_text:
        lines = []
        for i, t in enumerate(pdf_text):
            lines += ocr.lines_from_text(t, i + 1)
        await _set_lines(db, s, lines, "pdf_text", "PDF 自带文字层，已直接提取")
        s.quality_grade = s.quality_grade or "A"
    await db.commit()
    return await detail(sid, u, db)


async def _set_lines(db, s: Sheet, lines: list[dict], source: str, note: str) -> None:
    qnos = [q.no for q in await _questions(db, s)]
    s.ocr_lines = assign_questions(lines, qnos) if qnos else lines
    s.ocr_source, s.ocr_note, s.status = source, note, "recognized"
    if not s.paper_id:
        s.paper_guess = await _guess(db, s.ocr_lines)


@router.get("/{sid}/pages/{page_no}/image")
async def page_image(sid: int, page_no: int, u: User = Depends(current_user),
                     db: AsyncSession = Depends(get_db)):
    await _own(db, u, sid)
    p = (await db.execute(select(SheetPage).where(SheetPage.sheet_id == sid,
                                                  SheetPage.page_no == page_no))).scalar_one_or_none()
    if not p or not p.file_path or not Path(p.file_path).exists():
        raise HTTPException(404, "原图不存在或已删除")
    kind = _sniff(Path(p.file_path).read_bytes()[:8])
    return FileResponse(p.file_path, media_type="image/png" if kind == "png" else "image/jpeg")


@router.delete("/{sid}/images")
async def delete_images(sid: int, u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """一键删除原图。识别出的文字和批改结果保留。"""
    await _own(db, u, sid)
    n = 0
    for p in (await db.execute(select(SheetPage).where(SheetPage.sheet_id == sid))).scalars():
        if p.file_path:
            Path(p.file_path).unlink(missing_ok=True)
            p.file_path = ""
            n += 1
    await db.commit()
    return {"deleted": n}


class RecognizeReq(BaseModel):
    force: bool = False


@router.post("/{sid}/recognize")
async def recognize(sid: int, body: RecognizeReq, u: User = Depends(current_user),
                    db: AsyncSession = Depends(get_db)):
    s = await _own(db, u, sid)
    pages = (await db.execute(select(SheetPage).where(SheetPage.sheet_id == sid)
                              .order_by(SheetPage.page_no))).scalars().all()
    if not pages:
        raise HTTPException(400, "还没有上传图片")
    if any(p.grade == "D" for p in pages):
        raise HTTPException(400, "有页面无法识别（D 级），请删除重拍后再识别")
    if any(p.grade == "C" for p in pages) and not body.force:
        raise HTTPException(409, "有页面质量较差（C 级），确认继续请勾选「我已了解风险」")
    if not settings.llm_enabled:
        raise HTTPException(400, "未配置视觉模型，请改用手动录入")
    if not u.consent_vision:
        raise HTTPException(403, "需要先同意将答卷图片发送给识别服务；不同意可以手动录入")

    qs = await _questions(db, s)
    hint = ("本卷题目：" + "；".join(f"第{q.no}题 {q.stem[:24]}" for q in qs)) if qs else ""
    lines, models = [], set()
    for p in pages:
        if not p.file_path:
            raise HTTPException(400, f"第 {p.page_no} 页原图已删除")
        try:
            got, model = await ocr.recognize_image(Path(p.file_path).read_bytes(), p.page_no, hint)
        except ocr.LLMError as e:
            raise HTTPException(502, f"第 {p.page_no} 页识别失败：{str(e)[:120]}。可以重试或手动录入") from None
        lines += got
        models.add(model)
    low = sum(1 for ln in lines if ln["confidence"] < ocr.LOW_CONF)
    await _set_lines(db, s, lines, "vision",
                     f"{'、'.join(models)} 识别 {len(lines)} 行，{low} 行把握较低已标黄")
    await db.commit()
    return await detail(sid, u, db)


async def _guess(db, lines: list[dict]) -> list[dict]:
    answer = "".join(ln["text"] for ln in lines if ln.get("kind", "answer") == "answer")
    stems = "".join(ln["text"] for ln in lines if ln.get("kind") == "question")
    papers = []
    for p in (await db.execute(select(Paper).where(Paper.status == "complete"))).scalars():
        mats = (await db.execute(select(Material.text).where(Material.paper_id == p.id))).scalars().all()
        qs = (await db.execute(select(Question.stem).where(Question.paper_id == p.id))).scalars().all()
        papers.append({"id": p.id, "name": p.name, "materials_text": "".join(mats), "stems": list(qs)})
    return rank_papers(answer, stems, papers)


class PaperReq(BaseModel):
    paper_id: int
    question_ids: list[int] = []


@router.post("/{sid}/paper")
async def set_paper(sid: int, body: PaperReq, u: User = Depends(current_user),
                    db: AsyncSession = Depends(get_db)):
    """上传后再确认是哪套卷（用自动匹配的结果或手选），并按题号重新切分。"""
    s = await _own(db, u, sid)
    if s.status not in ("draft", "recognized"):
        raise HTTPException(400, "答卷已提交批改")
    await _set_paper(db, s, body.paper_id, body.question_ids)
    if s.ocr_lines:
        qnos = [q.no for q in await _questions(db, s)]
        s.ocr_lines = assign_questions(s.ocr_lines, qnos)
    await db.commit()
    return await detail(sid, u, db)


class Mark(BaseModel):
    no: int = Field(ge=0, le=50)
    paragraph: int = Field(ge=0, le=1000)
    start: int = Field(ge=0, le=20000)
    end: int = Field(ge=1, le=20000)
    style: Literal["yellow", "green", "pink", "underline"]


class MarksReq(BaseModel):
    marks: list[Mark] = Field(max_length=3000)


@router.put("/{sid}/marks")
async def save_marks(sid: int, body: MarksReq, u: User = Depends(current_user),
                     db: AsyncSession = Depends(get_db)):
    """保存资料标记。整份覆盖写：前端持有完整列表，改一处就整体保存。"""
    s = await _own(db, u, sid)
    s.marks = [m.model_dump() for m in body.marks if m.end > m.start]
    await db.commit()
    return {"count": len(s.marks)}


class SubmitReq(BaseModel):
    # 两种方式二选一：编辑后的识别行（每行带 qno），或按题号给出答案全文（手动录入）
    lines: list[dict] | None = None
    answers: dict[int, str] | None = None


@router.post("/{sid}/submit")
async def submit(sid: int, body: SubmitReq, u: User = Depends(current_user),
                 db: AsyncSession = Depends(get_db)):
    """确认各题答案并开始批改。每道题建一个作答，分别批改；答案在这里做隐私脱敏。"""
    s = await _own(db, u, sid)
    if s.status in ("grading", "graded"):
        raise HTTPException(409, "答卷已提交批改")
    qs = await _questions(db, s)
    if not qs:
        raise HTTPException(400, "请先确认是哪套试卷")
    by_no = {q.no: q for q in qs}

    if body.lines is not None:
        lines = [{"page": int(x.get("page", 1)), "line": int(x.get("line", i + 1)),
                  "text": mask_pii(str(x.get("text", ""))[:500]),
                  "confidence": float(x.get("confidence", 1.0)),
                  "kind": x.get("kind") if x.get("kind") in ("answer", "question", "draft") else "answer",
                  "qno": x.get("qno") if x.get("qno") in by_no else None}
                 for i, x in enumerate(body.lines)]
        s.ocr_lines = lines
        answers = split_answers(lines, list(by_no))
    elif body.answers is not None:
        answers = {int(k): mask_pii(v).strip() for k, v in body.answers.items()
                   if int(k) in by_no and v and v.strip()}
        s.ocr_source = s.ocr_source or "manual"
        s.ocr_lines = [ln for q, t in answers.items() for ln in
                       [{**x, "qno": q} for x in ocr.lines_from_text(t, 1)]]
    else:
        raise HTTPException(400, "请提供识别行或各题答案")

    answers = {q: t for q, t in answers.items() if word_count(t) >= 5}
    if not answers:
        raise HTTPException(400, "没有可批改的答案（每道题至少 5 个字）")
    too_long = [q for q, t in answers.items() if word_count(t) > 5000]
    if too_long:
        raise HTTPException(400, f"第 {too_long[0]} 题答案超过 5000 字")
    if not settings.llm_enabled:
        offline = [q for q in answers if not await grading_service.gradable_offline(db, by_no[q].id)]
        if offline:
            raise HTTPException(400, f"第 {'、'.join(map(str, offline))} 题还没有评分配置，"
                                     "需要配置模型后才能批改（首次批改时由模型按材料生成评分点）")

    started = []
    for qno, text in sorted(answers.items()):
        sub = Submission(user_id=u.id, sheet_id=s.id, question_id=by_no[qno].id,
                         match_level="exact", ocr_source=s.ocr_source or "manual",
                         ocr_lines=[ln for ln in s.ocr_lines if ln.get("qno") == qno],
                         quality_grade=s.quality_grade, status="grading",
                         time_spent_min=s.time_spent_min)
        db.add(sub)
        await db.flush()
        v = AnswerVersion(submission_id=sub.id, version_no=1, kind="original", text=text,
                          word_count=word_count(text))
        db.add(v)
        await db.flush()
        started.append((sub.id, v.id))
    s.status = "grading"
    await db.commit()
    for sub_id, v_id in started:
        grading_service.start(sub_id, v_id)
    return await detail(sid, u, db)


@router.get("")
async def my_sheets(u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    sheets = (await db.execute(select(Sheet).where(Sheet.user_id == u.id)
                               .order_by(Sheet.id.desc()).limit(100))).scalars().all()
    out = []
    for s in sheets:
        p = await db.get(Paper, s.paper_id) if s.paper_id else None
        items = await _items(db, s)
        graded = [i for i in items if i["score"] is not None]
        out.append({"id": s.id, "status": _status(s, items),
                    "created_at": s.created_at.strftime("%Y-%m-%d %H:%M"),
                    "paper": p.name if p else "未选试卷", "questions": len(items),
                    "score": round(sum(i["score"] for i in graded), 1) if graded else None,
                    "full_score": sum(i["full_score"] for i in graded) if graded else None})
    return out


async def _items(db, s: Sheet) -> list[dict]:
    subs = (await db.execute(select(Submission).where(Submission.sheet_id == s.id)
                             .order_by(Submission.id))).scalars().all()
    out = []
    for sub in subs:
        q = await db.get(Question, sub.question_id)
        r = (await db.execute(select(Review).where(Review.submission_id == sub.id)
                              .order_by(Review.id.desc()).limit(1))).scalar_one_or_none()
        out.append({"submission_id": sub.id, "question_no": q.no if q else None,
                    "qtype": q.qtype if q else "", "full_score": q.full_score if q else 0,
                    "status": sub.status, "error": sub.error,
                    "review_id": r.id if r else None, "score": r.score if r else None,
                    "confidence": r.confidence if r else None, "method": r.method if r else ""})
    return out


def _status(s: Sheet, items: list[dict]) -> str:
    if s.status != "grading":
        return s.status
    if any(i["status"] == "grading" for i in items):
        return "grading"
    return "graded"


@router.get("/{sid}")
async def detail(sid: int, u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    s = await _own(db, u, sid)
    p = await db.get(Paper, s.paper_id) if s.paper_id else None
    qs = await _questions(db, s)
    pages = (await db.execute(select(SheetPage).where(SheetPage.sheet_id == sid)
                              .order_by(SheetPage.page_no))).scalars().all()
    items = await _items(db, s)
    status = _status(s, items)
    if status != s.status:
        s.status = status
        await db.commit()
    return {
        "id": s.id, "status": status, "paper": paper_out(p) if p else None,
        "questions": [question_out(q) for q in qs], "scope_all": not s.question_ids,
        "quality_grade": s.quality_grade, "quality_text": GRADE_TEXT.get(s.quality_grade, ""),
        "pages": [{"page_no": pg.page_no, "grade": pg.grade, "issues": pg.issues,
                   "has_image": bool(pg.file_path)} for pg in pages],
        "ocr_source": s.ocr_source, "ocr_note": s.ocr_note, "ocr_lines": s.ocr_lines,
        "low_conf": ocr.LOW_CONF, "paper_guess": s.paper_guess, "items": items,
        "marks": s.marks or [],
    }
