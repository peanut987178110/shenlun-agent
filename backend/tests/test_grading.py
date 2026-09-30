"""批改核心：规则引擎、分数核算、置信度、LangGraph 流程（模型用假实现替代）。"""
from __future__ import annotations

import pytest

from app.data.sample_papers import DEFAULT_WORD_RULE, DIMENSIONS, P1_MATERIALS, P1_QUESTIONS
from app.grading import graph, rules
from app.grading.scoring import (GradingContext, confidence, content_max, counterfactual,
                                 quote_in_answer, score_points, score_range, word_penalty)

GOOD = ("一、老年村民不会用平台，使用率低。\n二、部分干部搞形式主义，把平台当留痕工具重复拍照。\n"
        "三、群众诉求响应慢，办结率低。\n四、部门数据不互通，信息重复录入。\n五、报表多，加重基层负担。")
WEAK = "平台操作复杂。干部工作很辛苦。我觉得要加强宣传，提高群众认识。"


def make_ctx(qidx: int = 0, answer: str = GOOD, **kw) -> GradingContext:
    q = P1_QUESTIONS[qidx]
    pts = [{"id": i + 1, "label": p["label"], "material_ref": p["material_ref"],
            "keywords": p["keywords"], "partial": p.get("partial", []), "unacceptable": [],
            "score": p["score"]} for i, p in enumerate(q["points"])]
    mats = [{"no": no, "paragraph": para, "text": t} for no, para, _, t in P1_MATERIALS]
    return GradingContext(
        qtype=q["qtype"], stem=q["stem"], full_score=q["full_score"], word_min=q["word_min"],
        word_max=q["word_max"], dimensions=DIMENSIONS[q["qtype"]], points=pts,
        word_rule=DEFAULT_WORD_RULE, materials=mats, answer=answer, rubric_id=1,
        rubric_version="1", reference_answer=q["reference_answer"], **kw)


def test_rule_hits_reference_answer():
    ctx = make_ctx(answer=P1_QUESTIONS[0]["reference_answer"])
    js = [rules.match_point(p, ctx.answer) for p in ctx.points]
    assert [j["status"] for j in js] == ["hit"] * 5
    # 引用必须是答案原句
    assert all(quote_in_answer(j["quote"], ctx.answer) for j in js)


def test_rule_weak_answer_partial_or_miss():
    ctx = make_ctx(answer=WEAK)
    statuses = [rules.match_point(p, ctx.answer)["status"] for p in ctx.points]
    assert "hit" not in statuses
    assert statuses[0] == "partial"  # 「操作复杂」是部分命中表达


def test_keywords_in_different_paragraphs_not_combined():
    # 「老人」和「使用率低」分在不同条目（段落）里，不应拼成完整命中
    ctx = make_ctx(answer="一、老人经常来村委会。\n二、平台使用率低。")
    assert rules.match_point(ctx.points[0], ctx.answer)["status"] == "partial"
    # 相隔超过一句也不拼
    ctx = make_ctx(answer="老人经常来村委会。村里路灯坏了。平台使用率低。")
    assert rules.match_point(ctx.points[0], ctx.answer)["status"] == "partial"


def test_heading_plus_elaboration_counts_as_one_point():
    ctx = make_ctx(qidx=1, answer="四、改革考核方式。由看留痕数量转为看问题解决率和群众满意度。")
    assert rules.match_point(ctx.points[4], ctx.answer)["status"] == "hit"


def test_all_reference_answers_score_full_by_rule():
    from app.data.sample_papers import PAPERS
    for paper in PAPERS:
        for q in paper["questions"]:
            if q["reference_answer"] and q["points"]:
                for i, sp in enumerate(q["points"]):
                    r = rules.match_point({**sp, "id": i}, q["reference_answer"])
                    assert r["status"] == "hit", (paper["name"], q["no"], sp["label"])


def test_modifier_word_alone_is_not_partial():
    # 「使用率低」里的「低」不能让「诉求响应慢、办结率低」判成部分命中
    ctx = make_ctx(answer="老年村民不会用平台，使用率低。")
    assert rules.match_point(ctx.points[2], ctx.answer)["status"] == "miss"


@pytest.mark.asyncio
async def test_rule_confidence_never_high():
    r = await graph.run_grading(make_ctx(answer=GOOD))
    assert r["confidence_band"] != "高"


def test_score_scaling_and_levels():
    ctx = make_ctx()
    assert content_max(ctx) == 12  # 15 − 概括与表达 3
    content, ledger = score_points(ctx, [{"id": p["id"], "status": "hit", "quote": "x", "reason": ""}
                                         for p in ctx.points])
    assert content == 12 and sum(p["max"] for p in ledger) == pytest.approx(12)


def test_word_penalty():
    ctx = make_ctx(answer="字" * 260)  # 上限 200，超 60 字 → 两档
    n, pen, why = word_penalty(ctx)
    assert n == 260 and pen == 2 and "超出" in why


def test_confidence_and_range():
    c, f = confidence("similar", 0.9, 1.0, 0.8)
    assert c == pytest.approx(0.85 * 0.9 * 0.8, abs=1e-3)
    low, high = score_range(10, 15, 0.5)
    assert (low, high) == (7.8, 12.2)
    assert score_range(0.2, 15, 1.0) == (0.0, 0.7)


def test_counterfactual_sorted_by_gain_per_minute():
    ledger = [{"id": 1, "label": "a", "material_ref": "", "status": "miss", "max": 3, "got": 0},
              {"id": 2, "label": "b", "material_ref": "", "status": "partial", "max": 3, "got": 1.5}]
    s = counterfactual(ledger, 0, "")
    # 缺口 3 分耗时 2 分钟（1.5/分钟）与缺口 1.5 分耗时 1 分钟（1.5/分钟）并列，缺口区间要对
    assert {x["point_id"] for x in s} == {1, 2}
    assert next(x for x in s if x["point_id"] == 1)["gain_low"] == 1.5


def test_vague_countermeasure_detected():
    anns = rules.detect_vague("加强宣传，提高群众认识。由镇政府组织街坊议事会。")
    assert len(anns) == 1 and anns[0]["quote"].startswith("加强宣传")


def test_copy_detected():
    mats = [{"text": "上级要求每月上传不少于 20 条工作记录，于是走访拍照、会议拍照"}]
    anns = rules.detect_copy("上级要求每月上传不少于20条工作记录。", mats)
    assert anns and anns[0]["type"] == "原文摘抄"


def test_format_check():
    text = "关于使用村务云平台的倡议书\n全县村民朋友们：\n正文。\n青溪县人民政府办公室\n2026年9月29日"
    have, missing = rules.check_format(text)
    assert missing == []


@pytest.mark.asyncio
async def test_graph_rule_path_end_to_end():
    r = await graph.run_grading(make_ctx(answer=GOOD))
    assert r["method"] == "rule" and "规则评分" in r["notice"]
    assert 12 <= r["score"] <= 15
    assert [t["node"] for t in r["trace"]] == ["题目理解", "材料证据", "评分", "证据校验", "教练"]
    assert r["hints"]["L4"]["reference_answer"]
    assert r["score_low"] <= r["score"] <= r["score_high"]


def test_essay_dimensions_scaled_to_full_score():
    from app.services.grading_service import fit_dimensions
    dims = fit_dimensions(DIMENSIONS["essay"], 50)
    assert sum(d["max"] for d in dims) == pytest.approx(50)
    assert fit_dimensions(DIMENSIONS["summary"], 20) is DIMENSIONS["summary"]  # 有要点维度的不动


@pytest.mark.asyncio
async def test_graph_rule_essay_confidence_capped():
    r = await graph.run_grading(make_ctx(qidx=4, answer="数字治理要以人为本。\n" * 30))
    assert r["confidence"] <= graph.RULE_ESSAY_CAP and r["needs_review"]


@pytest.mark.asyncio
async def test_graph_llm_path_fabricated_quote_goes_to_miss(monkeypatch):
    """模型声称命中但编造引用：送复核；复核仍给不出真实引用时按未命中处理。"""
    monkeypatch.setattr(graph.settings, "llm_base_url", "http://fake")
    monkeypatch.setattr(graph.settings, "llm_api_key", "k")
    calls = []

    async def fake(*, system, user, schema, tier="medium", images=None):
        calls.append(tier)
        if schema is graph.ScoreOut:
            return graph.ScoreOut(
                points=[graph.PointOut(id=1, status="hit", quote="老年村民不会用平台", reason="ok"),
                        graph.PointOut(id=2, status="hit", quote="这句话答案里没有", reason="编的")],
                levels=[graph.LevelOut(key="language", score=99, reason="好")],
                annotations=[graph.AnnOut(quote="不存在的句子", type="x", color="red")],
            ), "fake-m"
        return graph.AdjudicateOut(points=[graph.PointOut(id=2, status="hit", quote="仍然是编的")]), "fake-l"

    monkeypatch.setattr(graph, "complete_json", fake)
    r = await graph.run_grading(make_ctx(answer=GOOD))
    ledger = {p["id"]: p for p in r["points"]}
    assert calls == ["medium", "large"]
    assert ledger[1]["status"] == "hit"
    assert ledger[2]["status"] == "miss" and ledger[2]["rechecked"]
    assert r["dimensions"][-1]["got"] == 3  # 等级分被裁到 max
    assert not any(a["quote"] == "不存在的句子" for a in r["annotations"])
    assert r["confidence_factors"]["evidence"] == 0.5
