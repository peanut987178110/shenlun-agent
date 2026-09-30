"""答卷切分、试卷匹配、真题 JSON 校验、评分配置生成、AI 出题、对话工具。模型调用全部用假实现。"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.data.papers_loader import PAPERS_DIR, validate
from app.db.models import Material, Paper, Question, Rubric, ScoringPoint
from app.db.session import SessionLocal, init_db
from app.services import generator, rubric
from app.services.sheet import assign_questions, detect_qno, rank_papers, split_answers


# ---------------- 切分 ----------------

def test_detect_qno_ignores_answer_bullets():
    valid = {1, 2, 3}
    assert detect_qno("第二题", valid) == 2
    assert detect_qno("第3题 根据给定资料", valid) == 3
    assert detect_qno("二、根据给定资料2，分析……", valid) == 2
    assert detect_qno("二、部门数据不互通", valid) is None  # 考生答案的分条序号
    assert detect_qno("第九题", valid) is None


def test_assign_questions_prefers_model_qno_then_markers():
    lines = [{"text": "第一题", "kind": "answer"}, {"text": "一、老人不会用", "kind": "answer"},
             {"text": "二、形式主义", "kind": "answer"}, {"text": "第二题", "kind": "answer"},
             {"text": "配备代办员", "kind": "answer"}, {"text": "模型说是第3题", "kind": "answer", "qno": 3}]
    out = assign_questions(lines, [1, 2, 3])
    assert [x["qno"] for x in out] == [1, 1, 1, 2, 2, 3]
    assert out[0]["kind"] == "question" and out[3]["kind"] == "question"
    ans = split_answers(out, [1, 2, 3])
    assert ans[1] == "一、老人不会用\n二、形式主义" and ans[2] == "配备代办员"


def test_single_question_takes_all_lines():
    out = assign_questions([{"text": "一、甲", "kind": "answer"}, {"text": "二、乙", "kind": "answer"}], [4])
    assert split_answers(out, [4]) == {4: "一、甲\n二、乙"}


def test_rank_papers_by_material_overlap():
    papers = [{"id": 1, "name": "乡村", "materials_text": "老年村民不会用平台，干部形式主义留痕", "stems": []},
              {"id": 2, "name": "老街", "materials_text": "老街改造租金上涨老字号搬走", "stems": []}]
    r = rank_papers("老年村民不会用平台", "", papers)
    assert r[0]["paper_id"] == 1 and r[0]["score"] > r[1]["score"]


# ---------------- 真题 JSON ----------------

def _paper(**kw):
    d = {"year": 2025, "code": "A", "category": "综合类", "name": "2025年浙江省考申论A卷", "topic": "t",
         "status": "complete", "sources": [{"url": "https://x"}],
         "materials": [{"no": 1, "paragraph": 1, "text": "材料"}],
         "questions": [{"no": 1, "qtype": "summary", "stem": "根据给定资料1，概括问题（100分）",
                        "full_score": 100, "word_min": 0, "word_max": 300, "material_refs": [1]}]}
    d.update(kw)
    return d


def test_extract_json_repairs_inner_quotes():
    from app.llm.client import extract_json
    bad = '{"title":"数字政府","topic":"有干部说"上线就算完成"，群众不满意"}'
    assert extract_json(bad)["topic"] == "有干部说”上线就算完成”，群众不满意"
    assert extract_json('{"a": "x", "b": ["y"]}') == {"a": "x", "b": ["y"]}


def test_split_paragraphs():
    t = "```\n资料2\n\n第一段内容，老人不会用手机办事。\n\n第二段内容，数据不互通需要重复提交。\n```"
    assert generator.split_paragraphs(t) == ["第一段内容，老人不会用手机办事。", "第二段内容，数据不互通需要重复提交。"]


def test_validate_paper_json():
    assert validate(_paper(), "2025_A.json") == []
    assert any("文件名" in e for e in validate(_paper(), "2024_A.json"))
    assert any("code" in e for e in validate(_paper(code="D"), ""))
    bad = _paper()
    bad["questions"][0]["material_refs"] = [9]
    assert any("不存在的材料" in e for e in validate(bad, ""))
    bad = _paper()
    bad["questions"][0]["full_score"] = 60
    assert any("分值之和" in e for e in validate(bad, ""))


def test_shipped_real_papers_are_valid():
    for f in PAPERS_DIR.glob("*.json"):
        assert validate(json.loads(f.read_text(encoding="utf-8")), f.name) == [], f.name


# ---------------- 评分配置生成 ----------------

async def _real_question(qtype: str = "summary", full: float = 20) -> Question:
    await init_db()
    async with SessionLocal() as db:
        p = Paper(name="生成测试卷", year=2025, code="B", category="基层类", origin="real", topic="t")
        db.add(p)
        await db.flush()
        db.add(Material(paper_id=p.id, no=1, paragraph=1, text="老年人不会用手机上报，干部重复填报表格。"))
        q = Question(paper_id=p.id, no=1, qtype=qtype, stem="根据给定资料1，概括存在的问题。（20分）",
                     full_score=full, material_refs=[1])
        db.add(q)
        await db.commit()
        return q


async def test_ensure_rubric_generates_once_and_scales(monkeypatch):
    calls = []

    async def fake(**kw):
        calls.append(kw["tier"])
        return rubric.RubricDraft(points=[
            rubric.PointDraft(label="老人使用难", material_ref="材料1第1段", score=5,
                              keywords=[["老年人", "老人"], ["不会用"]]),
            rubric.PointDraft(label="重复填报", material_ref="材料1第1段", score=5,
                              keywords=[["报表", "表格"], ["重复"]])],
            reference_answer="一、老人不会用。二、重复填报。"), "fake"

    monkeypatch.setattr(rubric, "complete_json", fake)
    q = await _real_question()
    async with SessionLocal() as db:
        q = await db.get(Question, q.id)
        r1 = await rubric.ensure_rubric(db, q)
        await db.commit()
        r2 = await rubric.ensure_rubric(db, q)
        pts = (await db.execute(select(ScoringPoint).where(ScoringPoint.rubric_id == r1.id))).scalars().all()
        assert r1.id == r2.id and calls == ["large"]
        assert r1.source.startswith("AI")
        # 要点满分 = 20 − 概括与表达 3 = 17，两点各 8.5
        assert sum(p.score for p in pts) == pytest.approx(17)
        assert q.reference_answer.startswith("一、")


async def test_essay_rubric_needs_no_model(monkeypatch):
    async def boom(**kw):
        raise AssertionError("大作文不应调用模型")
    monkeypatch.setattr(rubric, "complete_json", boom)
    q = await _real_question("essay", 40)
    async with SessionLocal() as db:
        r = await rubric.ensure_rubric(db, await db.get(Question, q.id))
        assert r.dimensions[0]["key"] == "thesis"


# ---------------- AI 出题 ----------------

async def test_generator_uses_real_structure(monkeypatch):
    await init_db()
    async with SessionLocal() as db:
        p = Paper(name="2025年浙江省考申论C卷", year=2025, code="C", category="行政执法类", origin="real",
                  topic="t", source_key="2025_C")
        db.add(p)
        await db.flush()
        for no, qt, sc, wmax in ((1, "summary", 20, 250), (2, "countermeasure", 40, 400), (3, "essay", 40, 1200)):
            db.add(Question(paper_id=p.id, no=no, qtype=qt, stem="题干" * 10, full_score=sc, word_max=wmax,
                            word_min=1000 if qt == "essay" else 0))
        await db.commit()

    writes = []

    async def fake_text(*, user="", **kw):
        writes.append(user)
        # 第一次写得太短，触发一次重写；正文里带英文引号和「资料X」标题行，都要能处理
        n = 5 if len(writes) == 1 else 200
        return f"资料1\n\n他说\"系统上线了就算完成\"。{'段落一。' * n}\n\n{'段落二。' * n}"

    async def fake(*, schema, user="", **kw):
        if schema is generator.PlanOut:
            return generator.PlanOut(title="执法规范化", topic="基层执法", outline=[
                generator.OutlineItem(no=i, genre="新闻报道", focus=f"焦点{i}", points=["p"]) for i in (1, 2, 5, 7)]), "fake"
        return generator.QuestionsOut(questions=[
            generator.QOut(no=1, stem="根据给定资料1，概括执法中的问题。（20分）", material_refs=[1, 99]),
            generator.QOut(no=2, stem="根据给定资料2—3，提出改进建议。（40分）", material_refs=[2, 3]),
            generator.QOut(no=3, stem="参考给定资料，以规范执法为话题写一篇文章。（40分）", material_refs=[])]), "fake"

    monkeypatch.setattr(generator, "complete_json", fake)
    monkeypatch.setattr(generator, "complete_text", fake_text)
    async with SessionLocal() as db:
        job = await generator.create_job(db, user_id=1, code="C", theme="执法")
    await next(iter(generator._running))
    async with SessionLocal() as db:
        p = await db.get(Paper, job.id)
        qs = (await db.execute(select(Question).where(Question.paper_id == p.id).order_by(Question.no))).scalars().all()
        mats = (await db.execute(select(Material.no).where(Material.paper_id == p.id))).scalars().all()
    assert p.status == "complete" and p.origin == "generated", p.status_note
    assert "结构参照" in p.status_note and "浙江省考申论C卷" in p.status_note
    assert [q.qtype for q in qs] == ["summary", "countermeasure", "essay"]
    assert [q.full_score for q in qs] == [20, 40, 40]
    assert sorted(set(mats)) == [1, 2, 3, 4]  # 跳号被重排
    assert len(writes) == 5 and "太短" in writes[1]  # 4 则材料，其中一则过短重写
    assert qs[0].material_refs == [1]          # 不存在的材料编号被丢掉
    assert qs[2].material_refs == [1, 2, 3, 4]


# ---------------- 对话工具 ----------------

async def test_assistant_tools_scoped_to_user():
    from app.agents.assistant import _tools
    await init_db()
    async with SessionLocal() as db:
        mine = Paper(name="我的模拟卷", year=2026, code="A", category="综合类", origin="generated",
                     created_by=501, topic="共同富裕", status="complete")
        other = Paper(name="别人的模拟卷", year=2026, code="A", category="综合类", origin="generated",
                      created_by=502, topic="共同富裕", status="complete")
        db.add_all([mine, other])
        await db.flush()
        db.add(Material(paper_id=other.id, no=1, paragraph=1, text="独家案例：星河村共富工坊"))
        await db.commit()
        other_id = other.id
    tools = {t.name: t for t in _tools(501, "student")}
    found = await tools["search_papers"].ainvoke({"keyword": "共同富裕"})
    assert "我的模拟卷" in found and "别人的模拟卷" not in found
    assert await tools["get_paper"].ainvoke({"paper_id": other_id}) == "试卷不存在"
    assert "没有" in await tools["search_materials"].ainvoke({"keyword": "星河村"})
    assert "A 卷（综合类）" in await tools["exam_guide"].ainvoke({"part": "facts"})
