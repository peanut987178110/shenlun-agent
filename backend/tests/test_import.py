"""真题导入：把已收录的真题还原成粘贴文本，用不同排版切分，结果必须与原数据一致。"""
from __future__ import annotations

import json

import pytest

from app.data.papers_loader import PAPERS_DIR, validate
from app.services.paper_import import guess_qtype, parse_paper, parse_refs

PAPERS = sorted(PAPERS_DIR.glob("*.json"))


def _to_text(d: dict, style: int) -> str:
    """style 0：资料1 / 作答要求；1：【资料1】/ 无作答要求行；2：给定资料1：与正文同一行。"""
    out = ["注意事项", "1.本题本由给定资料与作答要求两部分构成。考试时限为150分钟。", "给定资料"]
    nos = sorted({m["no"] for m in d["materials"]})
    for no in nos:
        paras = [m["text"] for m in d["materials"] if m["no"] == no]
        if style == 0:
            out += [f"资料{no}"] + paras
        elif style == 1:
            out += [f"【资料{no}】"] + paras
        else:
            out += [f"给定资料{no}：{paras[0]}"] + paras[1:]
    if style != 1:
        out.append("作答要求")
    for q in d["questions"]:
        out.append(q["stem"])
    return "\n".join(out)


@pytest.mark.parametrize("path", PAPERS, ids=[p.stem for p in PAPERS])
@pytest.mark.parametrize("style", [0, 1, 2])
def test_roundtrip_real_papers(path, style):
    d = json.loads(path.read_text(encoding="utf-8"))
    numbered = all(q["stem"][:2].rstrip()[:1] in "一二三四五六123456789" for q in d["questions"])
    if style == 1 and not numbered:
        pytest.skip("题目不带题号时必须有「作答要求」一行，界面会提示")
    got = parse_paper(_to_text(d, style), d["year"], d["code"])

    def per_material(ms):  # 段落边界可能不同（原数据有段内换行），逐则比较全文
        return {no: "".join(m["text"].replace("\n", "") for m in ms if m["no"] == no)
                for no in sorted({m["no"] for m in ms})}

    assert per_material(got["materials"]) == per_material(d["materials"])
    assert [q["stem"] for q in got["questions"]] == [q["stem"] for q in d["questions"]]
    assert [q["full_score"] for q in got["questions"]] == [q["full_score"] for q in d["questions"]]
    got["sources"] = [{"url": "manual://import"}]
    assert validate(got, path.name) == []


def test_requirement_numbers_are_not_new_questions():
    text = ("资料1\n" + "材料正文。" * 20 + "\n作答要求\n一、根据资料1，概括问题。（20分）\n要求：\n1.全面准确；\n2.不超过300字。\n"
            "二、结合给定资料，自拟题目，写一篇议论性文章。（80分）\n要求：\n（1）观点明确；\n（2）1000—1200字。")
    d = parse_paper(text, 2026, "C")
    assert [q["no"] for q in d["questions"]] == [1, 2]
    assert d["questions"][0]["word_max"] == 300 and d["questions"][0]["qtype"] == "summary"
    assert (d["questions"][1]["word_min"], d["questions"][1]["word_max"]) == (1000, 1200)
    assert d["questions"][1]["qtype"] == "essay"


def test_refs_and_qtype():
    assert parse_refs("根据资料1、2，写一则短评") == [1, 2]
    assert parse_refs("根据给定资料2—4，概括") == [2, 3, 4]
    assert parse_refs("资料3和资料5是……") == [3, 5]
    assert parse_refs("结合给定资料，写一篇文章") == []
    assert guess_qtype("就资料5中的问题，提出相应对策。（20分）") == "countermeasure"
    assert guess_qtype("根据资料4，写一则短评。（30分）") == "official"
    assert guess_qtype("根据资料4，谈谈你对“共享法庭”建设的理解。") == "analysis"
