"""题目匹配（PRD 5.3 / 8.4）。

三级：
- exact：用户从题库直接选题，或识别出的题干与题库题干高度一致（相似度 ≥ 0.85）。
- similar：相似度 0.45—0.85，需要用户确认。
- generic：没有匹配到，只用题型通用规则批改，置信度打折，并明确提示用户。
"""
from __future__ import annotations

from typing import Any

from app.services.text import ngram_similarity

EXACT = 0.85
SIMILAR = 0.45

MATCH_FACTOR = {"exact": 1.0, "similar": 0.85, "generic": 0.6}

GENERIC_NOTICE = "当前未匹配到本题的教研评分配置，本次结果采用通用题型评分规则，评分置信度较低。"


def rank_candidates(query: str, questions: list[Any], top: int = 3) -> list[dict[str, Any]]:
    scored = []
    for q in questions:
        s = ngram_similarity(query, q.stem)
        scored.append({"question_id": q.id, "similarity": round(s, 3), "stem": q.stem,
                       "qtype": q.qtype, "full_score": q.full_score,
                       "level": level_for(s)})
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:top]


def level_for(similarity: float) -> str:
    if similarity >= EXACT:
        return "exact"
    if similarity >= SIMILAR:
        return "similar"
    return "generic"
