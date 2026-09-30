"""答案版本对比（PRD 12.2）。"""
from __future__ import annotations

import difflib
from typing import Any

from app.db.models import Review
from app.services.text import split_sentences


def _units(text: str) -> list[str]:
    """按句切分，段尾句保留换行，前端按原样显示时分条结构不丢。"""
    out: list[str] = []
    for para in (text or "").split("\n"):
        sents = split_sentences(para)
        if sents:
            sents[-1] += "\n"
        out += sents
    return out


def compare(old: Review, new: Review, old_text: str, new_text: str) -> dict[str, Any]:
    op = {p["id"]: p for p in old.points or []}
    np_ = {p["id"]: p for p in new.points or []}
    gained = [np_[i]["label"] for i in np_ if np_[i]["status"] == "hit"
              and op.get(i, {}).get("status") != "hit"]
    lost = [op[i]["label"] for i in op if op[i]["status"] == "hit"
            and np_.get(i, {}).get("status") != "hit"]

    def issues(r: Review) -> set[str]:
        return {a["type"] + "｜" + a["quote"][:20] for a in r.annotations or [] if a["color"] != "green"}

    old_i, new_i = issues(old), issues(new)
    a, b = _units(old_text), _units(new_text)
    diff = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            diff += [{"op": "same", "text": s} for s in a[i1:i2]]
        else:
            diff += [{"op": "del", "text": s} for s in a[i1:i2]]
            diff += [{"op": "add", "text": s} for s in b[j1:j2]]
    old_dims = {d["key"]: d["got"] for d in old.dimensions or []}
    return {
        "score_delta": round(new.score - old.score, 1),
        "old_score": old.score, "new_score": new.score,
        "gained_points": gained, "lost_points": lost,
        "fixed_issues": sorted(x.split("｜")[0] for x in old_i - new_i),
        "new_issues": sorted(x.split("｜")[0] for x in new_i - old_i),
        "word_delta": new.word_count - old.word_count,
        "dimension_delta": [{"name": d["name"], "delta": round(d["got"] - old_dims.get(d["key"], 0), 1)}
                            for d in new.dimensions or []],
        "diff": diff,
        "method_changed": old.method != new.method,
    }
