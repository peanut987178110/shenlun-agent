"""真题导入：用户从粉笔等网站复制整套卷粘贴进来，按规则切分成材料与题目。

全程不经过模型：材料和题干必须是原文，模型改写一个字都会让「证据化评分」失去依据。
切分规则针对常见的真题排版：
- 「作答要求」一行把全文分成给定资料与题目两部分；没有这一行时，从第一道带「（X分）」的题开始算题目。
- 资料以「资料1」「给定资料2」「【材料3】」这类单独成行的标题分隔，标题后的每一行是一段。
- 题目以「一、」「1.」「第一题」开头，直到下一题为止（含「要求：」各行）。
切分结果先给用户预览，确认后才保存。
"""
from __future__ import annotations

import re
from typing import Any

from app.db.models import PAPER_CODES
from app.services.sheet import CN_NUM

_MAT_HEAD = re.compile(
    r"^\s*[【\[（(]?\s*(?:给定)?(?:资料|材料)\s*([0-9]{1,2}|[一二三四五六七八九十]{1,2})\s*[】\]）)]?\s*([:：.．、])?\s*(.*)$")
_Q_HEAD = re.compile(r"^\s*(?:第\s*([一二三四五六七八九十\d]{1,2})\s*题|([一二三四五六七八九十])\s*[、.．]|(\d{1,2})\s*[、.．])\s*(.*)$")
_ANSWER_SECTION = re.compile(r"^\s*[二三]?\s*[、.．]?\s*作答要求\s*[:：]?\s*$")
# 题目下的要求条目：「要求：」「(1)」「（2）」「1.」「①」
_REQ_LINE = re.compile(r"^\s*(要求|[（(]\s*\d{1,2}\s*[)）]|\d{1,2}\s*[.．、]|[①②③④⑤⑥])")
_SCORE = re.compile(r"[（(]\s*(\d{1,3})\s*分\s*[）)]")
_RANGE = re.compile(r"(\d{3,4})\s*[—\-~～至到]+\s*(\d{3,4})\s*字")
_MAX = re.compile(r"(?:不超过|不多于|不得超过|限)\s*(\d{2,4})\s*字")
_REFS = re.compile(r"(?:给定)?(?:资料|材料)\s*“?([0-9一二三四五六七八九十、，,和与及—\-~～至到\s]+)")


def _num(s: str) -> int | None:
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s in CN_NUM:
        return CN_NUM[s]
    if len(s) == 2 and s[0] == "十":
        return 10 + CN_NUM.get(s[1], 0)
    return None


def guess_qtype(stem: str) -> str:
    head = stem[:120]
    if re.search(r"议论性文章|议论文|自拟题目.*文章|写一篇.*文章", stem):
        return "essay"
    if re.search(r"短评|评论|简报|倡议书|公开信|讲话稿|发言|推介|宣传稿|启事|提纲|汇报|编者按|导语|信", head):
        return "official"
    if re.search(r"概括|归纳|梳理", head):
        return "summary"
    if re.search(r"对策|建议|措施|怎么办|如何解决", head):
        return "countermeasure"
    if re.search(r"理解|分析|谈谈|评析|看法", head):
        return "analysis"
    return "official"


def parse_refs(stem: str) -> list[int]:
    """「资料1、2」「资料2—4」「资料3和资料5」→ [1,2] / [2,3,4] / [3,5]。「结合给定资料」→ []（全部）。"""
    refs: set[int] = set()
    for m in _REFS.finditer(stem):
        body = m.group(1)
        for a, b in re.findall(r"(\d+|[一二三四五六七八九十]+)\s*[—\-~～至到]+\s*(\d+|[一二三四五六七八九十]+)", body):
            x, y = _num(a), _num(b)
            if x and y and x <= y <= 20:
                refs.update(range(x, y + 1))
        for tok in re.split(r"[、，,和与及\s]+", re.sub(r"[—\-~～至到]", " ", body)):
            n = _num(tok)
            if n and n <= 20:
                refs.add(n)
    return sorted(refs)


def _word_limits(stem: str) -> tuple[int, int]:
    m = _RANGE.search(stem)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _MAX.search(stem)
    return (0, int(m.group(1))) if m else (0, 0)


def parse_paper(text: str, year: int, code: str) -> dict[str, Any]:
    """返回符合 papers/README.md 格式的 dict（sources 由调用方补）。"""
    lines = [ln.rstrip() for ln in (text or "").replace("\r", "").split("\n")]
    lines = [ln for ln in lines if ln.strip()]

    split = next((i for i, ln in enumerate(lines) if _ANSWER_SECTION.match(ln)), None)
    if split is None:
        # 没有「作答要求」：第一道「题号开头、且本行或后两行带分值」的行
        for i, ln in enumerate(lines):
            if _Q_HEAD.match(ln) and any(_SCORE.search(x) for x in lines[i:i + 3]):
                split = i
                break
    mat_lines = lines[:split] if split is not None else lines
    q_lines = lines[split + (1 if split is not None and _ANSWER_SECTION.match(lines[split]) else 0):] \
        if split is not None else []

    materials, no, para = [], None, 0
    for ln in mat_lines:
        m = _MAT_HEAD.match(ln)
        # 「资料1」单独成行，或「资料1：正文…」带冒号；正文里的「材料3显示…」不算标题
        if m and _num(m.group(1)) and (m.group(2) in ("：", ":") or len(m.group(3)) < 8):
            no, para = _num(m.group(1)), 0
            rest = m.group(3).strip()
            if rest:  # 「资料1：正文……」标题与正文同行
                para += 1
                materials.append({"no": no, "paragraph": para, "text": rest})
            continue
        if no is None:
            continue  # 资料之前的注意事项、卷首说明
        para += 1
        materials.append({"no": no, "paragraph": para, "text": ln.strip()})

    questions: list[dict[str, Any]] = []
    head_style = None  # 第一题用的题号样式：explicit「第一题」/ cn「一、」/ ar「1.」
    for ln in q_lines:
        m = _Q_HEAD.match(ln)
        n, style = None, None
        if m:
            style = "explicit" if m.group(1) else "cn" if m.group(2) else "ar"
            n = _num(m.group(1) or m.group(2) or m.group(3))
        cur = questions[-1] if questions else None
        # 「要求：1. 全面准确 2. 不超过300字」里的序号不是题号：
        # 题号必须按顺序出现、与第一题样式一致；已进入要求条目时，还得像题干（带分值或引用资料）
        if n is not None and head_style and style != head_style:
            n = None
        if n is not None and cur and cur["req"] and not (_SCORE.search(ln) or re.search(r"资料|材料", ln)):
            n = None
        if n == len(questions) + 1:
            head_style = head_style or style
            questions.append({"no": n, "lines": [ln.strip()], "score": bool(_SCORE.search(ln)), "req": False})
        elif cur is None or (cur["score"] and cur["req"] and not _REQ_LINE.match(ln)):
            # 不带题号的排版（如 2023 年卷）：上一题已有分值和「要求」，这一行又不是要求条目，就是下一题
            questions.append({"no": len(questions) + 1, "lines": [ln.strip()],
                              "score": bool(_SCORE.search(ln)), "req": False})
        else:
            cur["lines"].append(ln.strip())
            cur["score"] = cur["score"] or bool(_SCORE.search(ln))
            cur["req"] = cur["req"] or bool(_REQ_LINE.match(ln))
    out_q = []
    for q in questions:
        stem = "\n".join(q["lines"])
        sm = _SCORE.search(stem)
        wmin, wmax = _word_limits(stem)
        out_q.append({"no": q["no"], "qtype": guess_qtype(stem), "stem": stem,
                      "full_score": int(sm.group(1)) if sm else 0, "word_min": wmin, "word_max": wmax,
                      "material_refs": parse_refs(stem)})

    first = "".join(m["text"] for m in materials if m["no"] == 1)[:40]
    return {"year": year, "code": code, "category": PAPER_CODES.get(code, ""),
            "name": f"{year}年浙江省考申论{code}卷", "exam_date": "",
            "topic": first or f"{year}年{code}卷", "time_limit_min": 150, "full_score": 100,
            "status": "complete" if materials else "questions_only", "sources": [],
            "materials": materials, "questions": out_q}
