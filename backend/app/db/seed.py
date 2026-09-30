"""启动时的数据准备。

- 真题：导入 app/data/papers/*.json，按文件名幂等（已导入的跳过，新增文件自动补进来）。
  真题不带评分点；第一次批改某道题时由模型按材料生成评分配置（services/rubric.py）。
- 自编示例题：只在 SEED_SAMPLE_PAPERS=true 时导入（测试用）。关闭后，旧库里没人作答过的示例卷会被清掉。
- 演示账号：密码每台机器随机生成，只在首次创建时打印一次。
"""
from __future__ import annotations

import secrets

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.security import hash_password
from app.data.papers_loader import load_all
from app.data.sample_papers import DEFAULT_WORD_RULE, DIMENSIONS, PAPERS
from app.db.models import (PAPER_CODES, Material, Paper, Question, Rubric, ScoringPoint,
                           Submission, User)
from app.db.session import SessionLocal


async def ensure_seeded() -> list[str]:
    lines: list[str] = []
    async with SessionLocal() as db:
        if settings.seed_real_papers:
            n = await _import_real(db)
            if n:
                lines.append(f"已导入真题：{n} 套")
        if settings.seed_sample_papers:
            if not (await db.execute(select(func.count(Paper.id)).where(Paper.origin == "sample"))).scalar():
                for p in PAPERS:
                    await _add_sample(db, p)
        else:
            n = await _drop_unused_samples(db)
            if n:
                lines.append(f"已移除未使用的示例卷：{n} 套")

        if settings.seed_demo_accounts and not (await db.execute(select(func.count(User.id)))).scalar():
            for username, name, role in (("student", "演示学员", "student"),
                                         ("teacher", "演示教师", "teacher")):
                pwd = secrets.token_urlsafe(9)
                db.add(User(username=username, display_name=name, role=role,
                            password_hash=hash_password(pwd)))
                lines.append(f"演示账号 {username} / {pwd}（{name}，仅本次显示，请登录后修改）")
        await db.commit()
    return lines


async def _import_real(db) -> int:
    have = set((await db.execute(select(Paper.source_key).where(Paper.origin == "real"))).scalars())
    n = 0
    for d in load_all():
        if f"{d['year']}_{d['code']}" in have:
            continue
        await add_real_paper(db, d)
        n += 1
    return n


async def paper_in_use(db, paper_id: int) -> bool:
    return (await db.execute(select(Submission.id).join(Question, Submission.question_id == Question.id)
                             .where(Question.paper_id == paper_id).limit(1))).first() is not None


async def delete_paper(db, pid: int) -> None:
    qids = list((await db.execute(select(Question.id).where(Question.paper_id == pid))).scalars())
    rids = list((await db.execute(select(Rubric.id).where(Rubric.question_id.in_(qids)))).scalars())
    await db.execute(delete(ScoringPoint).where(ScoringPoint.rubric_id.in_(rids)))
    await db.execute(delete(Rubric).where(Rubric.id.in_(rids)))
    await db.execute(delete(Question).where(Question.paper_id == pid))
    await db.execute(delete(Material).where(Material.paper_id == pid))
    await db.execute(delete(Paper).where(Paper.id == pid))


async def add_real_paper(db, d: dict) -> Paper:
    key = f"{d['year']}_{d['code']}"
    paper = Paper(
        name=d["name"], year=d["year"], code=d["code"],
        category=d.get("category") or PAPER_CODES.get(d["code"], ""),
        theme=d["topic"][:60], topic=d["topic"], origin="real", status=d["status"],
        exam_date=d.get("exam_date", ""), sources=d["sources"], source_key=key,
        source="真题", is_sample=False)
    db.add(paper)
    await db.flush()
    for m in d["materials"]:
        db.add(Material(paper_id=paper.id, no=m["no"], paragraph=m["paragraph"], text=m["text"]))
    for q in d["questions"]:
        db.add(Question(
            paper_id=paper.id, no=q["no"], qtype=q["qtype"], stem=q["stem"],
            full_score=q["full_score"], word_min=q.get("word_min", 0), word_max=q.get("word_max", 0),
            material_refs=q.get("material_refs", []), theme=d["topic"][:60]))
    await db.flush()
    return paper


async def _drop_unused_samples(db) -> int:
    """删掉没人作答过的示例卷。作答过的保留，免得用户的历史记录失去题目。"""
    ids = [p for p in (await db.execute(select(Paper.id).where(Paper.origin == "sample"))).scalars()
           if not await paper_in_use(db, p)]
    for pid in ids:
        await delete_paper(db, pid)
    return len(ids)


async def _add_sample(db, p: dict) -> None:
    paper = Paper(name=p["name"], year=p["year"], category=p["category"], theme=p["theme"],
                  topic=p["theme"], origin="sample", code="")
    db.add(paper)
    await db.flush()
    for no, para, ctype, text in p["materials"]:
        db.add(Material(paper_id=paper.id, no=no, paragraph=para, text=text, content_type=ctype))
    for q in p["questions"]:
        question = Question(
            paper_id=paper.id, no=q["no"], qtype=q["qtype"], stem=q["stem"],
            full_score=q["full_score"], word_min=q["word_min"], word_max=q["word_max"],
            material_refs=q["material_refs"], format_req=q.get("format_req", ""),
            reference_answer=q["reference_answer"], theme=q["theme"],
        )
        db.add(question)
        await db.flush()
        rubric = Rubric(question_id=question.id, dimensions=DIMENSIONS[q["qtype"]],
                        word_rule=DEFAULT_WORD_RULE)
        db.add(rubric)
        await db.flush()
        for sp in q["points"]:
            db.add(ScoringPoint(rubric_id=rubric.id, label=sp["label"],
                                material_ref=sp["material_ref"], keywords=sp["keywords"],
                                partial=sp.get("partial", []), score=sp["score"]))
