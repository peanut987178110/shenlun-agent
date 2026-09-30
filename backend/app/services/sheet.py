"""答卷：按题切分、匹配试卷。

答题卡上一页往往写着好几道题，所以先整卷识别，再按题号切分成每道题的答案。
切分依据按可靠程度依次是：
1. 视觉模型认出的题号（它能看到答题卡上印刷的题号区域）；
2. 文本里的题号标记：「第一题」「第1题」，或以「1.」「二、」开头且后面像题干（含「根据」「给定资料」等）的行；
3. 只作答一道题时，全部归这道题。
切分结果一定交给用户确认，逐行可改，不直接拿去批改。

没选试卷就上传时，用答案内容匹配试卷：申论答案大量复用材料里的词，
所以「答案里的二字词有多少出现在这套卷的材料里」比题干相似度更能认出是哪套卷。
"""
from __future__ import annotations

import re
from typing import Any

from app.services.text import ngram_similarity, normalize

CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_Q_EXPLICIT = re.compile(r"^\s*第\s*([一二三四五六七八九十\d]{1,2})\s*题")
_Q_NUMBERED = re.compile(r"^\s*[（(]?([一二三四五六七八九十]|\d{1,2})[)）]?\s*[、.．]")
_STEM_WORDS = ("根据", "结合", "给定资料", "给定材料", "请你", "谈谈", "概括", "分析", "提出", "写一篇", "要求")


def _num(s: str) -> int | None:
    if s.isdigit():
        return int(s)
    return CN_NUM.get(s)


def detect_qno(line: str, valid: set[int]) -> int | None:
    """文本行是否是题号开头。考生答案里的「一、二、三」分条序号不算，除非后面跟着题干用语。"""
    m = _Q_EXPLICIT.match(line)
    if m:
        n = _num(m.group(1))
        return n if n in valid else None
    m = _Q_NUMBERED.match(line)
    if m and any(w in line[:40] for w in _STEM_WORDS):
        n = _num(m.group(1))
        return n if n in valid else None
    return None


def assign_questions(lines: list[dict[str, Any]], qnos: list[int]) -> list[dict[str, Any]]:
    """给每一行标上所属题号（qno），返回新列表。已有 qno（模型识别的）优先。"""
    valid = set(qnos)
    out, current = [], (qnos[0] if len(qnos) == 1 else None)
    for ln in lines:
        ln = dict(ln)
        q = ln.get("qno") if ln.get("qno") in valid else None
        if q is None:
            q = detect_qno(ln.get("text", ""), valid)
            if q is not None and ln.get("kind", "answer") == "answer":
                ln["kind"] = "question"  # 题号行本身不是答案
        if q is not None:
            current = q
        ln["qno"] = current
        out.append(ln)
    return out


def split_answers(lines: list[dict[str, Any]], qnos: list[int]) -> dict[int, str]:
    """按 qno 汇总每道题的答案全文。只取 kind=answer 的行，题目与草稿不参与批改。"""
    buckets: dict[int, list[str]] = {q: [] for q in qnos}
    for ln in lines:
        if ln.get("kind", "answer") == "answer" and ln.get("qno") in buckets:
            buckets[ln["qno"]].append(ln["text"])
    return {q: "\n".join(t).strip() for q, t in buckets.items() if "".join(t).strip()}


def _bigrams(text: str) -> set[str]:
    t = normalize(text)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def rank_papers(answer_text: str, question_text: str, papers: list[dict[str, Any]],
                top: int = 3) -> list[dict[str, Any]]:
    """papers: [{id, name, materials_text, stems}]。

    分数 = 0.7 × 答案二字词在材料中的覆盖率 + 0.3 × 识别到的题干与本卷题干的最高相似度。
    """
    ab = _bigrams(answer_text)
    out = []
    for p in papers:
        mb = _bigrams(p["materials_text"])
        cover = len(ab & mb) / len(ab) if ab and mb else 0.0
        stem_sim = max((ngram_similarity(question_text, s) for s in p["stems"]), default=0.0) \
            if question_text else 0.0
        score = 0.7 * cover + 0.3 * stem_sim if question_text else cover
        out.append({"paper_id": p["id"], "name": p["name"], "score": round(score, 3),
                    "material_cover": round(cover, 3), "stem_similarity": round(stem_sim, 3)})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:top]
