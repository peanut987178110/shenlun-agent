"""评分核算：模型路径和规则路径共用的纯函数。

把「谁判断命中」和「命中之后怎么算分」分开：前者可以是模型也可以是规则，
后者必须是确定的代码，这样同一组判断永远得出同一个分数，评分账本才可审计。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.matching import MATCH_FACTOR
from app.services.text import normalize, word_count

# 命中状态 → 得分比例（PRD 11.2 的六种状态）
STATUS_CREDIT = {"hit": 1.0, "partial": 0.5, "disputed": 0.5, "miss": 0.0,
                 "beyond": 0.0, "duplicate": 0.0}
STATUS_LABEL = {"hit": "完整命中", "partial": "部分命中", "disputed": "表达争议",
                "miss": "未命中", "beyond": "材料外推", "duplicate": "重复"}

LOW_CONFIDENCE = 0.6
HIGH_CONFIDENCE = 0.8


@dataclass
class GradingContext:
    qtype: str
    stem: str
    full_score: float
    word_min: int
    word_max: int
    dimensions: list[dict[str, Any]]
    points: list[dict[str, Any]]           # {id, label, material_ref, keywords, partial, unacceptable, score}
    word_rule: dict[str, Any]
    materials: list[dict[str, Any]]        # {no, paragraph, text}
    answer: str
    match_level: str = "exact"
    ocr_factor: float = 1.0
    format_req: str = ""
    reference_answer: str = ""
    rubric_id: int | None = None
    rubric_version: str = ""
    rubric_ai: bool = False  # 评分配置由模型生成、未经教研确认
    trace: list[dict[str, Any]] = field(default_factory=list)


def content_max(ctx: GradingContext) -> float:
    """要点型维度的满分 = 题目满分 − 各等级型维度满分之和。"""
    level_total = sum(d.get("max", 0) for d in ctx.dimensions if d["mode"] == "level")
    return max(0.0, ctx.full_score - level_total)


def score_points(ctx: GradingContext, results: list[dict[str, Any]]) -> tuple[float, list[dict]]:
    """results: [{id, status, quote, reason}]。返回 (要点维度得分, 评分账本)。

    评分点原始分值之和不一定等于要点维度满分，按比例缩放，账本里同时给出原始分和折算分。
    """
    by_id = {r["id"]: r for r in results}
    raw_total = sum(p["score"] for p in ctx.points) or 1.0
    scale = content_max(ctx) / raw_total
    ledger, earned = [], 0.0
    for p in ctx.points:
        r = by_id.get(p["id"], {"status": "miss", "quote": "", "reason": "未判定"})
        status = r["status"] if r["status"] in STATUS_CREDIT else "miss"
        got = round(p["score"] * STATUS_CREDIT[status] * scale, 2)
        earned += got
        ledger.append({
            "id": p["id"], "label": p["label"], "material_ref": p.get("material_ref", ""),
            "status": status, "status_label": STATUS_LABEL[status],
            "quote": r.get("quote", ""), "reason": r.get("reason", ""),
            "max": round(p["score"] * scale, 2), "got": got,
            "verified": r.get("verified", True), "rechecked": r.get("rechecked", False),
        })
    return round(earned, 2), ledger


def word_penalty(ctx: GradingContext) -> tuple[int, float, str]:
    n = word_count(ctx.answer)
    rule = ctx.word_rule or {}
    if ctx.word_max and n > ctx.word_max:
        per = rule.get("over_per", 50) or 50
        steps = -(-(n - ctx.word_max) // per)  # 向上取整
        pen = min(steps * rule.get("over_deduct", 1.0), ctx.full_score * 0.2)
        return n, round(pen, 2), f"超出字数上限 {n - ctx.word_max} 字"
    floor = ctx.word_min or 0
    if floor and n < floor * rule.get("under_ratio", 0.8):
        return n, rule.get("under_deduct", 1.0), f"字数 {n}，明显少于下限 {floor}"
    return n, 0.0, ""


def confidence(match_level: str, ocr_factor: float, evidence_rate: float,
               agreement: float, rubric_ai: bool = False) -> tuple[float, dict[str, float]]:
    """置信度 = 题目匹配 × 识别质量 × 证据通过率 × 复核一致（需求修订说明第二节）。

    评分配置是模型生成、未经教研确认的，题目匹配系数最高按 0.85 计。
    """
    match = MATCH_FACTOR.get(match_level, 0.6)
    if rubric_ai:
        match = min(match, 0.85)
    factors = {"match": match, "ocr": ocr_factor,
               "evidence": evidence_rate, "agreement": agreement}
    c = 1.0
    for v in factors.values():
        c *= v
    return round(c, 3), factors


def score_range(score: float, full: float, conf: float) -> tuple[float, float]:
    half = max(0.5, full * (1 - conf) * 0.3)
    return round(max(0.0, score - half), 1), round(min(full, score + half), 1)


def confidence_band(conf: float) -> str:
    return "高" if conf >= HIGH_CONFIDENCE else "中" if conf >= LOW_CONFIDENCE else "低"


def quote_in_answer(quote: str, answer: str) -> bool:
    """证据校验：引用必须真实出现在答案里。归一化后比较，容忍标点与空白差异。"""
    q = normalize(quote)
    return bool(q) and len(q) >= 2 and q in normalize(answer)


def counterfactual(ledger: list[dict], penalty: float, penalty_reason: str) -> list[dict]:
    """反事实增分（PRD 13，按修订后的公式）。

    缺口分 = 评分点满分 − 当前得分；预计增分 ∈ [缺口 × 0.5, 缺口]；按「增分上限 ÷ 耗时」排序。
    """
    out = []
    for p in ledger:
        gap = round(p["max"] - p["got"], 2)
        if gap <= 0:
            continue
        minutes = 2 if p["status"] == "miss" else 1
        action = (f"补写「{p['label']}」，依据见{p['material_ref'] or '材料'}"
                  if p["status"] == "miss" else
                  f"把与「{p['label']}」相关的表述写完整、写具体")
        out.append({"action": action, "point_id": p["id"], "minutes": minutes,
                    "gain_low": round(gap * 0.5, 1), "gain_high": round(gap, 1)})
    if penalty > 0:
        out.append({"action": f"压缩或补足字数：{penalty_reason}", "point_id": None,
                    "minutes": 2, "gain_low": round(penalty * 0.5, 1),
                    "gain_high": round(penalty, 1)})
    out.sort(key=lambda s: s["gain_high"] / s["minutes"], reverse=True)
    for i, s in enumerate(out):
        s["priority"] = "高" if i < 2 else "中" if i < 4 else "低"
    return out[:5]


def rank_annotations(anns: list[dict], limit: int = 5) -> list[dict]:
    """PRD 10.3 避免满篇红线：默认只展开影响最大的几条问题，其余折叠。绿色得分点不占名额。"""
    order = {"red": 0, "orange": 1, "yellow": 2, "blue": 3, "green": 9}
    problems = sorted((a for a in anns if a["color"] != "green"),
                      key=lambda a: (order.get(a["color"], 5), -a.get("impact", 0)))
    for i, a in enumerate(problems):
        a["folded"] = i >= limit
    for a in anns:
        if a["color"] == "green":
            a["folded"] = False
    return problems + [a for a in anns if a["color"] == "green"]
