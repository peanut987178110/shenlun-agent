"""批改智能体编排（LangGraph）。

PRD 第 16 章的多智能体，落成一张固定顺序的状态图：

    理解题目 → 材料证据 → 评分 → 证据校验 ─┬─(有疑点且用了模型)→ 复核裁决 → 教练
                                          └──────────────────────────→ 教练

用显式图而不是让模型自由调度工具：批改的步骤和顺序是确定的，
自由调度既不可复现，也会多花 token。

「质量监控智能体」的职责落在证据校验节点：模型声称命中的评分点，引用必须逐字出现在答案里，
否则送复核；复核后仍找不到的一律按未命中处理。「不允许无依据批注」由这里保证，不靠提示词自觉。
"""
from __future__ import annotations

import operator
import re
import time
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.core.config import settings
from app.grading import rules
from app.grading.prompts import (ADJUDICATE_SYSTEM, GENERIC_SYSTEM_EXTRA, PROMPT_VERSION,
                                 SCORE_SYSTEM, render_task)
from app.grading.scoring import (LOW_CONFIDENCE, GradingContext, confidence, confidence_band,
                                 counterfactual, quote_in_answer, rank_annotations, score_points,
                                 score_range, word_penalty)
from app.llm.client import LLMError, complete_json
from app.services.matching import GENERIC_NOTICE
from app.services.text import normalize

Status = Literal["hit", "partial", "disputed", "miss", "beyond", "duplicate"]
Color = Literal["red", "orange", "yellow", "blue"]

RULE_NOTICE = ("本次为规则评分（未使用模型）：只能判断关键信息是否出现、对策是否有主体、"
               "是否照抄材料，不能理解语义。")
RULE_ESSAY_NOTICE = "大作文的立意、论证质量需要语义理解，规则评分只做了结构粗筛，分数参考价值很低。"
RULE_ESSAY_CAP = 0.4
RULE_EVIDENCE = 0.75
DRAFT_ID_BASE = 1000


# ---------------- 模型输出结构 ----------------

class PointOut(BaseModel):
    id: int
    status: Status
    quote: str = ""
    reason: str = ""


class LevelOut(BaseModel):
    key: str
    score: float = Field(ge=0)
    reason: str = ""


class AnnOut(BaseModel):
    quote: str
    type: str
    color: Color
    why: str = ""
    fix: str = ""


class DemoOut(BaseModel):
    id: int
    text: str


class DraftPoint(BaseModel):
    label: str
    score: float = Field(gt=0)
    status: Status
    quote: str = ""
    reason: str = ""


class ScoreOut(BaseModel):
    points: list[PointOut] = []
    levels: list[LevelOut] = []
    annotations: list[AnnOut] = []
    demos: list[DemoOut] = []
    draft_points: list[DraftPoint] = []


class AdjudicateOut(BaseModel):
    points: list[PointOut]


# ---------------- 状态 ----------------

class GradeState(TypedDict, total=False):
    ctx: GradingContext
    points: list[dict[str, Any]]
    material_text: dict[int, str]
    method: str
    model: str
    judgements: list[dict[str, Any]]
    levels: list[dict[str, Any]]
    llm_annotations: list[dict[str, Any]]
    demos: dict[int, str]
    disputed: list[int]
    evidence_rate: float
    agreement: float
    notices: Annotated[list[str], operator.add]
    trace: Annotated[list[dict[str, Any]], operator.add]
    result: dict[str, Any]


def _step(name: str, started: float, detail: str) -> list[dict[str, Any]]:
    return [{"node": name, "ms": int((time.time() - started) * 1000), "detail": detail}]


# ---------------- 节点 ----------------

async def understand(state: GradeState) -> GradeState:
    """题目理解：确定题型、评分维度与本次使用的评分配置。"""
    t = time.time()
    ctx = state["ctx"]
    dims = "、".join(f"{d['name']}({'要点' if d['mode'] == 'points' else '等级'})" for d in ctx.dimensions)
    notices = [GENERIC_NOTICE] if ctx.match_level == "generic" else []
    if ctx.rubric_ai:
        notices.append("本题评分点由模型按材料生成，未经教研确认，可在评分账本里查看每个评分点的材料依据。")
    src = f"评分配置 v{ctx.rubric_version}" if ctx.rubric_id else "无教研评分配置"
    return {"points": list(ctx.points), "notices": notices,
            "trace": _step("题目理解", t, f"{src}；维度：{dims}；评分点 {len(ctx.points)} 个")}


_REF = re.compile(r"材料\s*(\d+)(?:\s*第\s*(\d+)\s*段)?")


async def evidence(state: GradeState) -> GradeState:
    """材料证据：把评分点的「材料依据」解析成具体段落原文，用于评分账本的证据链展示。"""
    t = time.time()
    ctx = state["ctx"]
    out: dict[int, str] = {}
    for p in state["points"]:
        texts = []
        for no, para in _REF.findall(p.get("material_ref", "")):
            texts += [m["text"] for m in ctx.materials
                      if m["no"] == int(no) and (not para or m["paragraph"] == int(para))]
        out[p["id"]] = "\n".join(texts)
    linked = sum(1 for v in out.values() if v)
    return {"material_text": out,
            "trace": _step("材料证据", t, f"{linked}/{len(out)} 个评分点关联到材料原文")}


async def score(state: GradeState) -> GradeState:
    """评分：优先模型；未配置或调用失败时降级到规则引擎，并写明原因。"""
    t = time.time()
    ctx = state["ctx"]
    if settings.llm_enabled:
        try:
            return await _score_llm(state, t)
        except LLMError as e:
            fallback = _score_rule(state, t)
            fallback["notices"] = [f"模型调用失败，已改用规则评分（{str(e)[:80]}）"] + fallback["notices"]
            return fallback
    if not ctx.points and ctx.qtype != "essay":
        raise ValueError("未配置模型时只能批改有评分配置的题目")
    return _score_rule(state, t)


def _score_rule(state: GradeState, t: float) -> GradeState:
    ctx = state["ctx"]
    r = rules.grade_by_rule(ctx)
    notices = [RULE_NOTICE] + ([RULE_ESSAY_NOTICE] if ctx.qtype == "essay" else [])
    hits = sum(1 for j in r["judgements"] if j["status"] == "hit")
    return {"method": "rule", "model": "", "judgements": r["judgements"], "levels": r["levels"],
            "llm_annotations": [], "demos": {}, "notices": notices,
            "trace": _step("评分", t, f"规则引擎：{hits}/{len(r['judgements'])} 个评分点完整命中")}


async def _score_llm(state: GradeState, t: float) -> GradeState:
    ctx = state["ctx"]
    points = state["points"]
    generic = not points and ctx.qtype != "essay"
    system = SCORE_SYSTEM + (GENERIC_SYSTEM_EXTRA if generic else "")
    out, model = await complete_json(system=system, user=render_task(ctx), schema=ScoreOut)

    if generic:
        points = [{"id": DRAFT_ID_BASE + i, "label": d.label, "material_ref": "",
                   "keywords": [], "partial": [], "score": d.score}
                  for i, d in enumerate(out.draft_points)]
        judged = [{"id": DRAFT_ID_BASE + i, "status": d.status, "quote": d.quote, "reason": d.reason}
                  for i, d in enumerate(out.draft_points)]
    else:
        known = {p["id"] for p in points}
        got = {p.id: p for p in out.points if p.id in known}
        judged = [{"id": pid, "status": got[pid].status, "quote": got[pid].quote,
                   "reason": got[pid].reason} if pid in got else
                  {"id": pid, "status": "miss", "quote": "", "reason": "模型未判定此评分点"}
                  for pid in (p["id"] for p in points)]

    level_dims = {d["key"]: d for d in ctx.dimensions if d["mode"] == "level"}
    by_key = {lv.key: lv for lv in out.levels}
    levels = []
    for key, d in level_dims.items():
        lv = by_key.get(key)
        levels.append({"key": key, "name": d["name"], "mode": "level", "max": float(d["max"]),
                       "got": round(min(float(d["max"]), lv.score), 1) if lv else 0.0,
                       "reason": lv.reason if lv else "模型未给出该维度评分"})
    anns = [{"quote": a.quote, "type": a.type, "color": a.color, "why": a.why, "fix": a.fix,
             "rule": "模型判断", "impact": {"red": 2.0, "orange": 1.0}.get(a.color, 0.5)}
            for a in out.annotations]
    return {"method": "llm", "model": model, "points": points, "judgements": judged,
            "levels": levels, "llm_annotations": anns,
            "demos": {d.id: d.text for d in out.demos},
            "trace": _step("评分", t, f"{model}：判定 {len(judged)} 个评分点、{len(levels)} 个等级维度")}


async def verify(state: GradeState) -> GradeState:
    """证据校验：引用必须真实出现在答案里。"""
    t = time.time()
    ctx = state["ctx"]
    if state["method"] == "rule":
        # 规则引擎的引用本来就取自答案原句，不存在编造；但关键词命中不等于语义命中。
        # 取 0.75，保证规则评分最多到「中」置信度，不会被标成「高」
        return {"disputed": [], "evidence_rate": RULE_EVIDENCE, "agreement": 1.0,
                "trace": _step("证据校验", t, f"规则评分，证据通过率按 {RULE_EVIDENCE} 计")}

    judged, disputed, claimed, ok = [], [], 0, 0
    for j in state["judgements"]:
        j = dict(j)
        if j["status"] != "miss":
            claimed += 1
            j["verified"] = quote_in_answer(j["quote"], ctx.answer)
            ok += j["verified"]
            if not j["verified"] or j["status"] == "disputed":
                disputed.append(j["id"])
        judged.append(j)
    anns = [a for a in state["llm_annotations"] if quote_in_answer(a["quote"], ctx.answer)]
    dropped = len(state["llm_annotations"]) - len(anns)
    rate = round(ok / claimed, 3) if claimed else 1.0
    return {"judgements": judged, "llm_annotations": anns, "disputed": disputed,
            "evidence_rate": rate, "agreement": 1.0,
            "trace": _step("证据校验", t, f"引用核对 {ok}/{claimed} 通过；"
                                         f"丢弃无依据批注 {dropped} 条；待复核 {len(disputed)} 个")}


def after_verify(state: GradeState) -> str:
    return "adjudicate" if state["method"] == "llm" and state["disputed"] else "coach"


async def adjudicate(state: GradeState) -> GradeState:
    """复核裁决：只把有疑点的评分点送大模型，不整题重跑。"""
    t = time.time()
    ctx = state["ctx"]
    ids = set(state["disputed"])
    labels = {p["id"]: p["label"] for p in state["points"]}
    items = "\n".join(
        f"- id={j['id']}｜{labels.get(j['id'], '')}｜初评 {j['status']}｜引用「{j['quote']}」｜"
        f"{'引用在答案中找不到' if not j.get('verified', True) else '初评拿不准'}"
        for j in state["judgements"] if j["id"] in ids)
    same = 0
    try:
        out, model = await complete_json(system=ADJUDICATE_SYSTEM, tier="large",
                                         user=render_task(ctx) + f"\n\n【待复核】\n{items}",
                                         schema=AdjudicateOut)
        final = {p.id: p for p in out.points if p.id in ids}
        detail = f"{model} 复核 {len(ids)} 个评分点"
    except LLMError as e:
        final, detail = {}, f"复核失败（{str(e)[:60]}），无法证实的引用按未命中处理"

    judged = []
    for j in state["judgements"]:
        if j["id"] not in ids:
            judged.append(j)
            continue
        new = final.get(j["id"])
        if new and (new.status == "miss" or quote_in_answer(new.quote, ctx.answer)):
            same += new.status == j["status"]
            judged.append({"id": j["id"], "status": new.status, "quote": new.quote,
                           "reason": new.reason, "verified": True, "rechecked": True})
        else:
            # 复核后仍无法在答案中找到依据：宁可少给分，也不给无依据的分
            judged.append({**j, "status": "miss", "quote": "", "verified": False, "rechecked": True,
                           "reason": "引用无法在答案中找到，按未命中处理"})
    agreement = 1.0 if same == len(ids) else 0.8
    return {"judgements": judged, "agreement": agreement,
            "trace": _step("复核裁决", t, f"{detail}；与初评一致 {same}/{len(ids)}")}


async def coach(state: GradeState) -> GradeState:
    """教练：核算分数、置信度，生成批注、诊断、增分建议和分层提示。"""
    t = time.time()
    ctx = state["ctx"]
    ctx.points = state["points"]
    content, ledger = score_points(ctx, state["judgements"])
    for p in ledger:
        p["material_text"] = state.get("material_text", {}).get(p["id"], "")
    levels = state["levels"]
    n_words, penalty, penalty_reason = word_penalty(ctx)

    content_dim = next((d for d in ctx.dimensions if d["mode"] == "points"), None)
    dims = ([{"key": content_dim["key"], "name": content_dim["name"], "mode": "points",
              "max": round(sum(p["max"] for p in ledger), 1), "got": content,
              "reason": f"{sum(1 for p in ledger if p['status'] == 'hit')}/{len(ledger)} 个评分点完整命中"}]
            if content_dim and ledger else []) + levels
    total = content + sum(lv["got"] for lv in levels) - penalty
    total = round(min(ctx.full_score, max(0.0, total)) * 2) / 2  # 申论按 0.5 分给分

    conf, factors = confidence(ctx.match_level, ctx.ocr_factor, state["evidence_rate"],
                               state["agreement"], ctx.rubric_ai)
    if state["method"] == "rule" and ctx.qtype == "essay":
        conf = min(conf, RULE_ESSAY_CAP)
    low, high = score_range(total, ctx.full_score, conf)

    anns = _merge_annotations(ctx, ledger, rules.rule_annotations(ctx) + state["llm_annotations"],
                              penalty, penalty_reason, conf, state["method"])
    result = {
        "method": state["method"], "model": state.get("model", ""),
        "prompt_version": PROMPT_VERSION if state["method"] == "llm" else "",
        "full_score": ctx.full_score, "score": total, "score_low": low, "score_high": high,
        "confidence": conf, "confidence_band": confidence_band(conf),
        "confidence_factors": factors, "dimensions": dims, "points": ledger,
        "annotations": anns, "suggestions": counterfactual(ledger, penalty, penalty_reason),
        "diagnosis": rules.diagnose(ctx, ledger, anns, penalty_reason),
        "hints": rules.build_hints(ctx, ledger, anns, state.get("demos")),
        "word_count": n_words, "word_penalty": penalty,
        "needs_review": conf < LOW_CONFIDENCE,
    }
    return {"result": result,
            "trace": _step("教练", t, f"得分 {total}/{ctx.full_score}，置信度 {conf}（{confidence_band(conf)}），"
                                     f"批注 {len(anns)} 条")}


def _merge_annotations(ctx, ledger, raw, penalty, penalty_reason, conf, method) -> list[dict]:
    seen, anns = set(), []
    for a in raw:
        k = (normalize(a["quote"]), a["type"])
        if k in seen:
            continue
        seen.add(k)
        anns.append({**a, "confidence": 0.8 if a.get("rule") != "模型判断" else round(conf, 2),
                     "appealable": False})
    for p in ledger:
        if p["status"] == "hit" and p["quote"]:
            anns.append({"quote": p["quote"], "type": "有效得分点", "color": "green", "impact": 0,
                         "why": f"命中「{p['label']}」", "fix": "", "rule": p["material_ref"],
                         "point_id": p["id"], "confidence": round(conf, 2), "appealable": False})
        elif p["status"] in ("miss", "partial") and p["max"] - p["got"] >= 1:
            anns.append({"quote": p["quote"], "type": "要点缺失" if p["status"] == "miss" else "要点不完整",
                         "color": "red" if p["status"] == "miss" else "orange",
                         "impact": round(p["max"] - p["got"], 1),
                         "why": f"「{p['label']}」{p['reason']}", "fix": "见分层提示",
                         "rule": p["material_ref"], "point_id": p["id"],
                         "confidence": round(conf, 2), "appealable": True})
    if penalty:
        anns.append({"quote": "", "type": "字数问题", "color": "red", "impact": penalty,
                     "why": penalty_reason, "fix": "删去重复和案例细节", "rule": "字数要求",
                     "confidence": 1.0, "appealable": False})
    for i, a in enumerate(anns):
        a["id"] = i + 1
    return rank_annotations(anns)


# ---------------- 组装 ----------------

def build_graph():
    g = StateGraph(GradeState)
    g.add_node("understand", understand)
    g.add_node("evidence", evidence)
    g.add_node("score", score)
    g.add_node("verify", verify)
    g.add_node("adjudicate", adjudicate)
    g.add_node("coach", coach)
    g.add_edge(START, "understand")
    g.add_edge("understand", "evidence")
    g.add_edge("evidence", "score")
    g.add_edge("score", "verify")
    g.add_conditional_edges("verify", after_verify, {"adjudicate": "adjudicate", "coach": "coach"})
    g.add_edge("adjudicate", "coach")
    g.add_edge("coach", END)
    return g.compile()


_graph = None


async def run_grading(ctx: GradingContext) -> dict[str, Any]:
    global _graph
    if _graph is None:
        _graph = build_graph()
    state = await _graph.ainvoke({"ctx": ctx, "notices": [], "trace": []})
    result = state["result"]
    result["trace"] = state["trace"]
    result["notice"] = "\n".join(dict.fromkeys(state["notices"]))
    return result
