"""AI 模拟卷生成（LangGraph）。

    选结构模板 → 命制材料 → 命题 → 校验落库

- 结构模板取同卷别最近一年的真题：题型、分值、字数要求照搬，保证「和浙江省考卷差不多」
  指的是结构一致，而不是凭印象。题库里还没有这个卷别的真题时，用通用五题结构并在界面说明。
- 材料用虚构地名（H 市、L 县），不编造真实人物讲话和可被当真的统计数字、政策文号。
- 评分点不在这里生成：第一次批改某道题时由 services/rubric.py 按材料生成并落库，和真题走同一条路。
- 生成要两三分钟，在后台跑，进度写在 paper.status_note，前端轮询。
"""
from __future__ import annotations

import asyncio
import re
import time
import traceback
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.models import PAPER_CODES, QTYPES, Material, Paper, Question
from app.db.session import SessionLocal
from app.llm.client import complete_json, complete_text

GENERIC_STRUCTURE = [
    {"qtype": "summary", "full_score": 15, "word_min": 0, "word_max": 250},
    {"qtype": "analysis", "full_score": 15, "word_min": 0, "word_max": 300},
    {"qtype": "countermeasure", "full_score": 15, "word_min": 0, "word_max": 300},
    {"qtype": "official", "full_score": 15, "word_min": 0, "word_max": 500},
    {"qtype": "essay", "full_score": 40, "word_min": 1000, "word_max": 1200},
]

PLAN_SYSTEM = """你是浙江省公务员考试申论命题专家，为一套模拟卷设计「给定资料」的整体方案。

要求：
1. 共 {n_mat} 则材料。为每则写：体裁（新闻报道 / 干部群众访谈 / 调研报告 / 政策解读 / 评论文章 / 典型案例，
   至少一则含人物对话）、这则材料讲什么、要埋进去的信息点（问题、原因、做法、经验、不同观点）。
2. 信息点分散在不同材料里，让不同题目用不同材料；也要安排少量干扰信息。
3. 贴近浙江基层实际与近年政策方向（共同富裕、数字化改革、乡村振兴、基层治理、营商环境等，按主题选）。
{theme_line}
只输出 JSON：{{"title":"本卷主题（10 字以内）","topic":"一句话概括",
"outline":[{{"no":1,"genre":"新闻报道","focus":"讲什么","points":["信息点1","信息点2"]}}]}}"""

MATERIAL_SYSTEM = """你是浙江省公务员考试申论命题专家，按方案写一则「给定资料」。

要求：
1. 篇幅 {chars} 字左右（不少于 {min_chars} 字），分 3—6 段，写成真实考卷里的材料，不是提纲。
2. 按给定体裁写：新闻要有事件经过，访谈要有人物原话，调研报告要有调研发现，案例要有具体做法和成效。
3. 方案里的信息点都要写进去，但自然融在叙述里，不要逐条罗列、不要加小标题、不要替考生总结。
4. 地名一律用虚构代号（「H 市」「L 县」「青山镇」），人物用「张某」「老李」「某局负责人」。
   不要编造真实领导人讲话，不要写可能被当成真实数据的精确统计数字和政策文号。
5. 直接输出材料正文，段与段之间空一行。不要标题、不要「资料X」字样、不要任何说明文字、不要 JSON。"""

MAT_CHARS = 1300  # 每则材料目标字数；真题 4—6 则，合计约 5000—7500 字

QUESTIONS_SYSTEM = """你是浙江省公务员考试申论命题专家。根据给定资料，按指定结构命题。

题干写法仿照浙江省考：写明依据哪几则资料、作答任务、分值、作答要求和字数，例如
「根据给定资料2，概括H市在推进……过程中遇到的困难。（15分）要求：全面、准确、有条理。不超过250字。」
- 应用文题要给出写作身份、对象和文种。
- 大作文题给出话题或观点，要求自选角度、自拟题目。
- 每道题 material_refs 只能引用存在的材料编号，各题使用的材料尽量不完全重合。
题型、分值、字数必须与结构完全一致。只输出 JSON：
{"questions":[{"no":1,"stem":"...","material_refs":[1,2]}]}"""


class MatOut(BaseModel):
    no: int
    paragraphs: list[str] = Field(min_length=1)


class MaterialsOut(BaseModel):
    title: str = Field(min_length=2, max_length=40)
    topic: str = ""
    materials: list[MatOut] = Field(min_length=3, max_length=10)


class OutlineItem(BaseModel):
    no: int
    genre: str = ""
    focus: str
    points: list[str] = []


class PlanOut(BaseModel):
    title: str = Field(min_length=2, max_length=40)
    topic: str = ""
    outline: list[OutlineItem] = Field(min_length=3, max_length=8)


_MAT_HEAD = re.compile(r"^\s*(【?\s*(给定)?资料\s*[\d一二三四五六七八九十]+\s*】?|#+.*)\s*$")


def split_paragraphs(text: str) -> list[str]:
    """纯文本材料按空行（或换行）切段，去掉模型偶尔加的「资料X」标题行与代码块围栏。"""
    t = re.sub(r"```\w*", "", text or "").strip()
    blocks = re.split(r"\n\s*\n", t) if "\n\n" in t.replace("\r", "") else t.splitlines()
    out = []
    for b in blocks:
        b = " ".join(x.strip() for x in b.splitlines() if x.strip() and not _MAT_HEAD.match(x))
        if len(b) >= 10:
            out.append(b)
    return out


class QOut(BaseModel):
    no: int
    stem: str = Field(min_length=15)
    material_refs: list[int] = []


class QuestionsOut(BaseModel):
    questions: list[QOut]


class GenState(TypedDict, total=False):
    paper_id: int
    code: str
    theme: str
    structure: list[dict[str, Any]]
    template_name: str
    materials: MaterialsOut
    questions: list[dict[str, Any]]


async def _note(paper_id: int, note: str, status: str | None = None, **fields) -> None:
    async with SessionLocal() as db:
        p = await db.get(Paper, paper_id)
        p.status_note = note
        if status:
            p.status = status
        for k, v in fields.items():
            setattr(p, k, v)
        await db.commit()


async def pick_template(db, code: str) -> tuple[list[dict[str, Any]], str]:
    """同卷别最近一年的真题结构。"""
    p = (await db.execute(select(Paper).where(Paper.origin == "real", Paper.code == code)
                          .order_by(Paper.year.desc()).limit(1))).scalar_one_or_none()
    if p:
        qs = (await db.execute(select(Question).where(Question.paper_id == p.id)
                               .order_by(Question.no))).scalars().all()
        if qs:
            return ([{"qtype": q.qtype, "full_score": q.full_score, "word_min": q.word_min,
                      "word_max": q.word_max} for q in qs], p.name)
    return GENERIC_STRUCTURE, ""


async def node_materials(state: GenState) -> GenState:
    """先定方案，再逐则并行写材料。

    一次调用写全部材料时，模型会把篇幅压到要求的一半以下（实测 4 则只写了约 1900 字）。
    拆成每则一次调用，并对过短的那则重写一次。
    """
    await _note(state["paper_id"], "正在设计材料方案…")
    n_mat = 5 if len(state["structure"]) <= 3 else 6
    theme = state.get("theme", "").strip()
    head = f"卷别：浙江省考申论{state['code']}卷（{PAPER_CODES[state['code']]}）。本卷 {len(state['structure'])} 道题：" + \
        "、".join(QTYPES[s["qtype"]] for s in state["structure"])
    plan, _ = await complete_json(
        system=PLAN_SYSTEM.format(n_mat=n_mat, theme_line=f"4. 本卷主题：{theme}" if theme
                                  else "4. 主题自选，贴近浙江近两年的基层工作重点。"),
        user=head, schema=PlanOut, tier="medium", max_tokens=3000, temperature=0.8)

    await _note(state["paper_id"], f"正在撰写 {len(plan.outline)} 则给定资料（约 1—2 分钟）…")
    min_chars = int(MAT_CHARS * 0.7)

    async def write(item: OutlineItem) -> list[str]:
        user = (f"本卷主题：{plan.title}（{plan.topic}）\n本则：资料{item.no}，体裁：{item.genre}\n"
                f"讲什么：{item.focus}\n要写进去的信息点：\n" + "\n".join(f"- {p}" for p in item.points))
        system = MATERIAL_SYSTEM.format(chars=MAT_CHARS, min_chars=min_chars)
        best: list[str] = []
        for _ in range(3):
            # 长篇中文不走 JSON：材料里的人物原话常带引号，模型写成英文双引号就会让整段 JSON 失效
            text = await complete_text(system=system, user=user, max_tokens=4000, temperature=0.8)
            paras = split_paragraphs(text)
            if sum(len(p) for p in paras) > sum(len(p) for p in best):
                best = paras
            if sum(len(p) for p in best) >= min_chars:
                break
            user += f"\n\n上一版只有 {sum(len(p) for p in paras)} 字，太短，请写到 {MAT_CHARS} 字左右。"
        return best

    written = await asyncio.gather(*(write(it) for it in plan.outline))
    mats = MaterialsOut(title=plan.title, topic=plan.topic,
                        materials=[MatOut(no=i + 1, paragraphs=p) for i, p in enumerate(written) if p])
    return {"materials": mats}


async def node_questions(state: GenState) -> GenState:
    await _note(state["paper_id"], "正在按真题结构命题…")
    mats = state["materials"].materials
    structure = state["structure"]
    shape = "\n".join(
        f"第{i + 1}题：{QTYPES[s['qtype']]}，{s['full_score']}分，"
        f"{'字数 ' + str(s['word_min']) + '—' + str(s['word_max']) if s['word_min'] else '不超过 ' + str(s['word_max']) + ' 字'}"
        for i, s in enumerate(structure))
    user = f"【结构】\n{shape}\n\n【给定资料】\n" + "\n".join(
        f"资料{m.no}\n" + "\n".join(m.paragraphs) for m in mats)
    out, _ = await complete_json(system=QUESTIONS_SYSTEM, user=user, schema=QuestionsOut,
                                 tier="medium", max_tokens=4000, temperature=0.5)
    if len(out.questions) != len(structure):
        raise ValueError(f"题目数量不对：要 {len(structure)} 道，生成了 {len(out.questions)} 道")
    valid = {m.no for m in mats}
    qs = []
    for i, (q, s) in enumerate(zip(out.questions, structure)):
        refs = [r for r in q.material_refs if r in valid] or sorted(valid)
        qs.append({**s, "no": i + 1, "stem": q.stem, "material_refs": refs})  # 题型分值以结构为准
    return {"questions": qs}


async def node_save(state: GenState) -> GenState:
    mats = state["materials"]
    async with SessionLocal() as db:
        p = await db.get(Paper, state["paper_id"])
        for m in mats.materials:
            for j, para in enumerate(m.paragraphs):
                db.add(Material(paper_id=p.id, no=m.no, paragraph=j + 1, text=para.strip()))
        for q in state["questions"]:
            db.add(Question(paper_id=p.id, no=q["no"], qtype=q["qtype"], stem=q["stem"],
                            full_score=q["full_score"], word_min=q["word_min"], word_max=q["word_max"],
                            material_refs=q["material_refs"], theme=mats.title))
        n_chars = sum(len(x) for m in mats.materials for x in m.paragraphs)
        p.name = f"AI 模拟卷 · {state['code']}卷 · {mats.title}"
        p.theme, p.topic, p.status = mats.title, mats.topic or mats.title, "complete"
        p.status_note = (f"材料 {len(mats.materials)} 则约 {n_chars} 字，{len(state['questions'])} 道题。"
                         + (f"结构参照 {state['template_name']}。" if state["template_name"]
                            else "题库里还没有该卷别的真题，用的是通用五题结构。"))
        await db.commit()
    return {}


def _build():
    g = StateGraph(GenState)
    g.add_node("materials", node_materials)
    g.add_node("questions", node_questions)
    g.add_node("save", node_save)
    g.add_edge(START, "materials")
    g.add_edge("materials", "questions")
    g.add_edge("questions", "save")
    g.add_edge("save", END)
    return g.compile()


_graph = None
_running: set[asyncio.Task] = set()


async def create_job(db, user_id: int, code: str, theme: str) -> Paper:
    structure, template_name = await pick_template(db, code)
    p = Paper(name=f"AI 模拟卷 · {code}卷（生成中）", year=time.localtime().tm_year + 1, code=code,
              category=PAPER_CODES[code], theme=theme[:60], topic=theme, origin="generated",
              status="generating", status_note="排队中…", created_by=user_id, source="AI 生成",
              is_sample=False)
    db.add(p)
    await db.commit()
    task = asyncio.create_task(_run({"paper_id": p.id, "code": code, "theme": theme,
                                     "structure": structure, "template_name": template_name}))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return p


async def _run(state: GenState) -> None:
    global _graph
    if _graph is None:
        _graph = _build()
    try:
        await _graph.ainvoke(state)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        await _note(state["paper_id"], f"生成失败：{str(e)[:200]}。可以直接重新生成。", status="failed",
                    name=f"AI 模拟卷 · {state['code']}卷（生成失败）")
