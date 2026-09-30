"""规则引擎。

两个用途：
1. 未配置模型或模型调用失败时，独立完成批改（结果标注「规则评分」，置信度打折）。
2. 模型路径里也会跑一遍规则检测（空泛对策、摘抄、重复、口语、格式），与模型批注合并。
   这些检测是确定性的，不依赖模型发挥。

规则只能做「看得见的」判断：关键词是否出现、句子里有没有主体、有没有照抄材料。
立意、论证这种需要理解的维度，规则给出的分数只是结构粗筛，大作文尤其如此。
"""
from __future__ import annotations

import re
from typing import Any

from app.db.models import QTYPES
from app.grading.scoring import GradingContext
from app.services.text import ngram_similarity, normalize, split_sentences

VAGUE_VERBS = ("加强", "提高", "完善", "提升", "推进", "强化", "加大", "健全", "优化", "做好", "重视")
SUBJECTS = ("政府", "部门", "县", "镇", "村委", "社区", "干部", "委员会", "局", "办公室", "网格员",
            "代办员", "街道", "党组织", "党支部", "商户", "居民", "企业", "学校", "管委会", "由")
CONCRETE = ("开展", "建立", "设立", "组织", "配备", "制定", "召开", "公开", "补贴", "培训", "打通",
            "统一", "新建", "明确", "规定", "每月", "每季度", "个工作日", "上门", "代为")
COLLOQUIAL = ("我觉得", "咱们", "啥", "咋", "反正", "挺好", "特别特别", "的话呢", "搞定")
SLOGAN = re.compile(r"让我们.{0,30}[！!]")
COPY_MIN = 15

TRAINING = {
    "要点遗漏": ["逐段标注材料中的问题、原因、对策", "先列要点再成文", "限时 10 分钟要点提取"],
    "对策空泛": ["主体识别", "对策结构拆解：主体＋对象＋动作＋方式", "限字对策训练"],
    "原文摘抄": ["同义概括改写练习", "把长句压缩为 10 字以内要点"],
    "要点重复": ["要点分类合并练习"],
    "超字数": ["先列提纲再写", "限字压缩练习"],
    "口语化": ["规范表达替换练习"],
    "格式缺项": ["常见文种格式默写"],
    "论证不足": ["分论点＋论据＋分析的三段式段落练习"],
}

CHAINS = {
    "要点遗漏": ["只抓住了部分材料", "遗漏了{refs}中的信息", "要点覆盖不全"],
    "对策空泛": ["只提取了「做什么」", "没写「谁来做、怎么做」", "对策缺少可操作性"],
    "原文摘抄": ["照抄材料原句", "没有提炼成要点", "占用字数，概括度低"],
    "要点重复": ["同一意思换说法写了两遍", "挤占其他要点的字数"],
    "超字数": ["没有先列要点再成文", "表述冗长", "超出字数上限被扣分"],
    "口语化": ["使用口头表达", "不符合申论书面语要求"],
    "格式缺项": ["没有按文种核对格式要素", "缺少{missing}"],
    "论证不足": ["段落只有观点", "缺少论据与分析", "论证说服力不足"],
}

ABILITY_OF = {"要点遗漏": "材料定位", "对策空泛": "对策设计", "原文摘抄": "概括",
              "要点重复": "要点提炼", "超字数": "字数", "口语化": "语言",
              "格式缺项": "格式", "论证不足": "论证"}


# ---------------- 评分点匹配 ----------------

def _group_hit(group: list[str], norm_sentence: str) -> str | None:
    return next((kw for kw in group if normalize(kw) and normalize(kw) in norm_sentence), None)


def _windows(answer: str) -> list[str]:
    """匹配窗口：单句，以及同一段内相邻两句。

    考生写分条要点时常是「标题句。展开句。」，如「改革考核方式。由看留痕转为看满意度。」，
    核心词和限定词分在两句里。只按单句匹配会系统性漏判；跨段不合并，避免把不同要点拼在一起。
    """
    out: list[str] = []
    for para in (answer or "").split("\n"):
        sents = split_sentences(para)
        out += sents
        out += [a + b for a, b in zip(sents, sents[1:])]
    return out


def match_point(p: dict[str, Any], answer: str) -> dict[str, Any]:
    """按窗口匹配：所有关键词组必须落在同一句（或同段相邻两句）里才算完整命中，
    避免把散落在全文的词拼成一个要点。"""
    groups = p.get("keywords") or []
    best_n, best_sentence, core_hit = 0, "", False
    for s in _windows(answer):
        ns = normalize(s)
        n = sum(1 for g in groups if _group_hit(g, ns))
        # 第一组是评分点的核心对象（如「诉求」「数据」）。只命中修饰词（如「低」「多」）不算沾边，
        # 否则「使用率低」会被当成「办结率低」的部分命中
        core = bool(groups) and _group_hit(groups[0], ns) is not None
        if (core, n) > (core_hit, best_n):
            best_n, best_sentence, core_hit = n, s, core
    norm_all = normalize(answer)
    partial_phrase = next((x for x in p.get("partial", []) if normalize(x) in norm_all), None)

    if groups and best_n == len(groups):
        status = "hit"
    elif (core_hit and len(groups) >= 2) or partial_phrase:
        status = "partial"
    else:
        status = "miss"
    if status == "hit" and any(normalize(x) in norm_all for x in p.get("unacceptable", [])):
        status = "disputed"

    quote = best_sentence if core_hit else ""
    if not quote and partial_phrase:
        quote = next((s for s in split_sentences(answer) if normalize(partial_phrase) in normalize(s)), "")
    reason = {"hit": "关键信息齐全", "partial": f"只覆盖了部分关键信息（{best_n}/{len(groups)}）",
              "disputed": "命中关键词，但含有不可接受的表述", "miss": "未找到对应表述"}[status]
    return {"id": p["id"], "status": status, "quote": quote.strip(), "reason": reason}


# ---------------- 句子级检测 ----------------

def detect_vague(answer: str) -> list[dict]:
    out = []
    for s in split_sentences(answer):
        if any(v in s for v in VAGUE_VERBS) and not any(x in s for x in SUBJECTS) \
                and not any(x in s for x in CONCRETE):
            out.append({"quote": s, "type": "对策空泛", "color": "orange", "impact": 1.0,
                        "why": "只有「加强、提高」这类方向词，缺少责任主体和具体做法",
                        "fix": "按「由【谁】针对【什么对象】采取【什么具体措施】」改写",
                        "rule": "对策结构：责任主体＋目标对象＋具体动作＋执行方式"})
    return out


def detect_copy(answer: str, materials: list[dict]) -> list[dict]:
    mat = normalize("".join(m["text"] for m in materials))
    out = []
    for s in split_sentences(answer):
        ns = normalize(s)
        if len(ns) >= COPY_MIN and any(ns[i:i + COPY_MIN] in mat
                                       for i in range(0, len(ns) - COPY_MIN + 1)):
            out.append({"quote": s, "type": "原文摘抄", "color": "yellow", "impact": 0.5,
                        "why": f"有连续 {COPY_MIN} 字以上与材料原文相同",
                        "fix": "提炼成概括性表述，去掉案例细节和数字",
                        "rule": "概括题要求提炼而非摘抄"})
    return out


def detect_repeat(answer: str) -> list[dict]:
    sents = [s for s in split_sentences(answer) if len(normalize(s)) >= 8]
    out, seen = [], set()
    for i, a in enumerate(sents):
        for b in sents[i + 1:]:
            if b not in seen and ngram_similarity(a, b) > 0.6:
                seen.add(b)
                out.append({"quote": b, "type": "要点重复", "color": "yellow", "impact": 0.5,
                            "why": f"与前文「{a[:20]}…」意思重复",
                            "fix": "删去或合并，把字数留给未覆盖的要点", "rule": "要点不重复"})
    return out


def detect_colloquial(answer: str) -> list[dict]:
    out = []
    for s in split_sentences(answer):
        word = next((w for w in COLLOQUIAL if w in s), None)
        if word:
            out.append({"quote": s, "type": "口语化", "color": "blue", "impact": 0.3,
                        "why": f"「{word}」是口头表达", "fix": "换成规范书面语",
                        "rule": "申论语言要求规范、准确"})
        if SLOGAN.search(s):
            out.append({"quote": s, "type": "口号式表达", "color": "blue", "impact": 0.3,
                        "why": "结尾只喊口号，没有回扣论点", "fix": "用一句话总结论点并落到实处",
                        "rule": "结尾应回应中心论点"})
    return out


def check_format(answer: str) -> tuple[list[str], list[str]]:
    """应用文格式四要素：标题、称谓、落款、日期。返回 (具备的, 缺少的)。"""
    lines = [ln.strip() for ln in answer.splitlines() if ln.strip()]
    have = []
    if lines and len(lines[0]) <= 25 and not lines[0].endswith("。"):
        have.append("标题")
    if any(ln.endswith(("：", ":")) and len(ln) <= 20 for ln in lines[:3]):
        have.append("称谓")
    tail = lines[-3:]
    if any(re.search(r"(办公室|政府|委员会|局|中心|社区|支部)$", ln) for ln in tail):
        have.append("落款")
    if any(re.search(r"(\d{4}|[〇零一二三四五六七八九]{4})\s*年.{1,3}月.{1,3}日", ln) for ln in tail):
        have.append("日期")
    missing = [x for x in ("标题", "称谓", "落款", "日期") if x not in have]
    return have, missing


def rule_annotations(ctx: GradingContext) -> list[dict]:
    """与题型相关的确定性检测。模型路径和规则路径都会调用。"""
    a = ctx.answer
    anns = detect_repeat(a) + detect_colloquial(a)
    if ctx.qtype == "countermeasure":
        anns += detect_vague(a)
    if ctx.qtype in ("summary", "countermeasure", "analysis"):
        anns += detect_copy(a, ctx.materials)
    return anns


# ---------------- 等级型维度的规则打分 ----------------

def _level_by_rule(dim: dict, ctx: GradingContext, anns: list[dict]) -> dict:
    mx = float(dim.get("max", 0))
    kinds = [x["type"] for x in anns]
    paragraphs = [p for p in ctx.answer.split("\n") if p.strip()]
    key = dim["key"]
    reason: str
    if key == "format":
        have, missing = check_format(ctx.answer)
        s = mx * len(have) / 4
        reason = f"具备 {'、'.join(have) or '无'}；缺少 {'、'.join(missing) or '无'}"
    elif key == "logic":
        markers = sum(1 for w in ("因此", "所以", "因为", "由于", "综上", "可见", "一方面", "另一方面")
                      if w in ctx.answer)
        s = mx * min(1.0, 0.4 + 0.15 * markers)
        reason = f"逻辑连接词 {markers} 个（规则只能粗判结构，不能判断分析是否成立）"
    elif ctx.qtype == "essay":
        theme_words = [w for w in re.findall(r"“(.+?)”", ctx.stem)]
        ratio = {"thesis": 1.0 if theme_words and any(normalize(t) in normalize(ctx.answer)
                                                       for t in theme_words) else 0.5,
                 "structure": min(1.0, len(paragraphs) / 6),
                 "material": 0.7 if any(m["text"][:4] in ctx.answer for m in ctx.materials) else 0.5,
                 "argument": min(1.0, 0.4 + 0.1 * sum(ctx.answer.count(w) for w in ("例如", "比如", "正如", "因此"))),
                 "language": 1.0 - 0.15 * kinds.count("口语化") - 0.15 * kinds.count("口号式表达")}[key]
        s = mx * max(0.3, ratio)
        reason = "规则粗筛（段落数、扣题词、论证标记），不代表对文章质量的判断"
    else:  # language / 具体性
        deduct = 0.25 * (kinds.count("对策空泛") + kinds.count("原文摘抄") + kinds.count("要点重复")) \
                 + 0.15 * kinds.count("口语化")
        s = mx * max(0.3, 1 - deduct)
        reason = f"扣分项：{'、'.join(sorted(set(kinds))) or '无'}"
    return {"key": key, "name": dim["name"], "mode": "level", "max": mx,
            "got": round(s, 1), "reason": reason}


def grade_by_rule(ctx: GradingContext) -> dict[str, Any]:
    """规则路径的评分判断。返回与模型路径同构的结构，交给 scoring 统一核算。"""
    judgements = [match_point(p, ctx.answer) for p in ctx.points]
    anns = rule_annotations(ctx)
    levels = [_level_by_rule(d, ctx, anns) for d in ctx.dimensions if d["mode"] == "level"]
    return {"judgements": judgements, "levels": levels, "annotations": anns}


# ---------------- 诊断与分层提示（两条路径共用）----------------

def diagnose(ctx: GradingContext, ledger: list[dict], anns: list[dict],
             penalty_reason: str) -> list[dict]:
    """失分因果诊断（PRD 差异化二）。每条诊断带因果链、触发条件、推荐训练。"""
    qlabel = QTYPES.get(ctx.qtype, "")
    found: dict[str, dict] = {}

    missed = [p for p in ledger if p["status"] in ("miss", "partial")]
    if missed and sum(p["max"] - p["got"] for p in missed) >= ctx.full_score * 0.15:
        refs = "、".join(sorted({p["material_ref"] for p in missed if p["material_ref"]}))
        found["要点遗漏"] = {"refs": refs or "材料", "example": missed[0]["label"],
                           "triggers": [f"{qlabel}题", f"材料涉及 {len(ctx.materials)} 段"]}
    for a in anns:
        t = a["type"]
        if t in CHAINS and t not in found:
            found[t] = {"example": a["quote"][:40], "triggers": [f"{qlabel}题"]}
    if penalty_reason and "超出" in penalty_reason:
        found["超字数"] = {"example": penalty_reason, "triggers": [f"字数上限 {ctx.word_max}"]}
    if ctx.qtype == "official":
        _, missing = check_format(ctx.answer)
        if missing:
            found["格式缺项"] = {"missing": "、".join(missing), "example": "、".join(missing),
                             "triggers": ["应用文"]}

    out = []
    for t, info in found.items():
        chain = [step.format(refs=info.get("refs", ""), missing=info.get("missing", ""))
                 for step in CHAINS[t]]
        out.append({"error_type": t, "chain": chain, "example": info["example"],
                    "trigger_conditions": info["triggers"],
                    "recommended_training": TRAINING.get(t, []),
                    "ability": ABILITY_OF.get(t, "")})
    return out


def build_hints(ctx: GradingContext, ledger: list[dict], anns: list[dict],
                demos: dict[int, str] | None = None) -> dict[str, Any]:
    """分层提示（PRD 12.1）：问题 → 提示 → 局部示范 → 参考答案。

    接口按级别返回，前三级不含参考答案。前端拿不到还没解锁的内容，
    避免「默认不展示高分答案」只靠界面隐藏。
    """
    lacking = [p for p in ledger if p["status"] != "hit"]
    return {
        "L1": {"summary": f"有 {len(lacking)} 个评分点未完整覆盖，"
                          f"{sum(1 for a in anns if a['color'] in ('red', 'orange'))} 处明显影响得分的问题"},
        "L2": [{"point_id": p["id"], "hint": f"回看{p['material_ref'] or '材料'}，"
                                            f"答案里还缺一个{('要点' if p['status'] == 'miss' else '更完整的表述')}"}
               for p in lacking],
        "L3": [{"point_id": p["id"], "label": p["label"],
                "demo": (demos or {}).get(p["id"], "")} for p in lacking],
        "L4": {"reference_answer": ctx.reference_answer,
               "note": "参考答案只是一种合理写法，不是唯一答案。评分看是否覆盖评分点，不看是否与它一致。"},
    }
