"""对话智能体：查资料、答疑（LangGraph ReAct）。

工具全部只读，并且绑定当前用户：只能查题库（真题、自己的模拟卷）和自己的学习记录。
智能体不能批改、不能改分、不能改数据，这些都走界面上的正式流程。

回答要有出处：题目和材料从题库工具查，考试常识从 exam_guide 查；题库里没有的不编。
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from sqlalchemy import or_, select

from app.core.config import settings
from app.data.zhejiang_guide import FACTS, METHOD
from app.db.models import (PAPER_CODES, QTYPES, ErrorPattern, Material, Paper, Prescription,
                           Question, Review, Submission)
from app.db.session import SessionLocal
from app.llm.client import chat_model

SYSTEM = """你是「浙考申论智阅」的学习助手，服务浙江省考申论备考的考生。

你能做的：查真题与模拟卷的题目、材料；解释题型和作答方法；结合考生自己的批改记录分析薄弱点、给练习建议。
工作规则：
1. 涉及具体试卷、题目、材料的内容，必须先用工具从题库查，回答时写明出自哪套卷第几题 / 第几则材料。题库里查不到就直说没有收录，不要凭记忆编题目或材料。
2. 考试常识（卷别、分值、时长）用 exam_guide 查。区分「公告规定」和「教研经验」，后者不要说成官方标准。
3. 你不能批改、打分或修改任何数据。考生要批改就告诉他去「开始批改」，要新题就去「AI 出题」。
4. 不承诺分数，不说「保证上岸」。
5. 用中文，简洁，面向考生，不输出 JSON 或工具原始结果。"""

MAX_TOOL_CHARS = 6000


def _tools(user_id: int, role: str) -> list[StructuredTool]:
    def visible(stmt):
        if role == "teacher":
            return stmt
        return stmt.where(or_(Paper.origin != "generated", Paper.created_by == user_id))

    async def search_papers(keyword: str = "", year: int = 0, code: str = "") -> str:
        """按关键词（主题、题干、材料内容）、年份、卷别（A/B/C）查题库里的试卷。返回试卷列表。"""
        async with SessionLocal() as db:
            stmt = visible(select(Paper).where(Paper.status.in_(["complete", "questions_only"])))
            if year:
                stmt = stmt.where(Paper.year == year)
            if code:
                stmt = stmt.where(Paper.code == code.upper()[:1])
            papers = (await db.execute(stmt.order_by(Paper.year.desc(), Paper.code))).scalars().all()
            out = []
            for p in papers:
                if keyword:
                    hit = keyword in (p.name + p.topic)
                    if not hit:
                        hit = (await db.execute(select(Question.id).where(
                            Question.paper_id == p.id, Question.stem.contains(keyword)).limit(1))).first() \
                            or (await db.execute(select(Material.id).where(
                                Material.paper_id == p.id, Material.text.contains(keyword)).limit(1))).first()
                    if not hit:
                        continue
                out.append(f"[paper_id={p.id}] {p.name}｜{p.origin}｜{p.topic}")
            return "\n".join(out[:20]) or "没有找到符合条件的试卷"

    async def get_paper(paper_id: int, with_materials: bool = False) -> str:
        """取一套卷的题目（题号、题型、分值、题干）。with_materials=True 时附上全部材料原文（较长）。"""
        async with SessionLocal() as db:
            p = await db.get(Paper, paper_id)
            if not p or (role != "teacher" and p.origin == "generated" and p.created_by != user_id):
                return "试卷不存在"
            qs = (await db.execute(select(Question).where(Question.paper_id == p.id)
                                   .order_by(Question.no))).scalars().all()
            text = [f"{p.name}（{PAPER_CODES.get(p.code, '')}，{p.origin}）主题：{p.topic}"]
            text += [f"第{q.no}题［{QTYPES[q.qtype]}，{q.full_score}分，材料{q.material_refs}］{q.stem}" for q in qs]
            if with_materials:
                mats = (await db.execute(select(Material).where(Material.paper_id == p.id)
                                         .order_by(Material.no, Material.paragraph))).scalars().all()
                text += [f"［材料{m.no}第{m.paragraph}段］{m.text}" for m in mats]
            return "\n".join(text)[:MAX_TOOL_CHARS]

    async def search_materials(keyword: str) -> str:
        """在全部材料原文里搜关键词，返回命中的段落和所在试卷。适合查「哪套卷讲过某个案例 / 政策」。"""
        async with SessionLocal() as db:
            rows = (await db.execute(visible(select(Material, Paper).join(Paper, Material.paper_id == Paper.id))
                                     .where(Material.text.contains(keyword)).limit(8))).all()
            return "\n".join(f"{p.name} 材料{m.no}第{m.paragraph}段：{m.text[:300]}" for m, p in rows) \
                or f"材料里没有「{keyword}」"

    async def exam_guide(part: str = "all") -> str:
        """浙江省考申论常识。part=facts 卷别、分值、时长等公告信息；part=method 各题型作答方法；all 两者都要。"""
        return {"facts": FACTS, "method": METHOD}.get(part, FACTS + "\n\n" + METHOD)

    async def my_learning(limit: int = 10) -> str:
        """当前考生自己的学习记录：最近批改得分、高频错误、进行中的训练处方。"""
        async with SessionLocal() as db:
            rows = (await db.execute(select(Review, Question).join(
                Submission, Review.submission_id == Submission.id).join(
                Question, Submission.question_id == Question.id).where(
                Submission.user_id == user_id).order_by(Review.id.desc()).limit(min(limit, 20)))).all()
            errs = (await db.execute(select(ErrorPattern).where(ErrorPattern.user_id == user_id)
                                     .order_by(ErrorPattern.frequency.desc()).limit(5))).scalars().all()
            rx = (await db.execute(select(Prescription).where(
                Prescription.user_id == user_id, Prescription.status == "active"))).scalars().all()
            lines = [f"[review_id={r.id}] {QTYPES[q.qtype]} {r.score}/{r.full_score}（{r.method}）" for r, q in rows]
            lines += [f"高频错误：{e.error_type} {e.frequency} 次（{e.mastery_status}）" for e in errs]
            lines += [f"训练处方：{p.goal}（{p.error_type}）" for p in rx]
            return "\n".join(lines) or "还没有批改记录"

    async def get_review(review_id: int) -> str:
        """当前考生自己的某次批改详情：得分、评分账本、主要问题、增分建议。"""
        async with SessionLocal() as db:
            r = await db.get(Review, review_id)
            sub = await db.get(Submission, r.submission_id) if r else None
            if not r or sub.user_id != user_id:
                return "批改记录不存在"
            pts = "\n".join(f"- {p['label']}：{p['status_label']} {p['got']}/{p['max']}" for p in r.points)
            anns = "\n".join(f"- {a['type']}：{a['why']}" for a in r.annotations if a["color"] != "green")[:1500]
            sug = "\n".join(f"- {s['action']}（+{s['gain_low']}—{s['gain_high']}）" for s in r.suggestions)
            return f"得分 {r.score}/{r.full_score}，置信度 {r.confidence}\n评分点：\n{pts}\n问题：\n{anns}\n建议：\n{sug}"

    fns = [search_papers, get_paper, search_materials, exam_guide, my_learning, get_review]
    return [StructuredTool.from_function(coroutine=f, name=f.__name__, description=f.__doc__) for f in fns]


async def chat(user_id: int, role: str, message: str, history: list[dict[str, str]]) -> dict[str, Any]:
    if not settings.llm_enabled:
        return {"reply": "对话助手需要模型网关，当前未配置。可以先在「题库」里浏览真题和材料。",
                "steps": [], "degraded": True}
    from langgraph.prebuilt import create_react_agent

    agent = create_react_agent(chat_model("medium", max_tokens=4000), _tools(user_id, role), prompt=SYSTEM)
    msgs: list[Any] = []
    for h in history[-10:]:
        cls = HumanMessage if h.get("role") == "user" else AIMessage
        msgs.append(cls(content=str(h.get("content", ""))[:4000]))
    msgs.append(HumanMessage(content=message))
    try:
        result = await agent.ainvoke({"messages": msgs}, config={"recursion_limit": 12})
    except Exception as e:  # noqa: BLE001
        return {"reply": f"助手这次没能完成回答（{type(e).__name__}），请换个说法再试。",
                "steps": [], "degraded": True}

    steps = []
    for m in result["messages"][len(msgs):]:
        if isinstance(m, AIMessage):
            steps += [{"tool": c["name"], "args": c["args"]} for c in m.tool_calls]
        elif isinstance(m, ToolMessage) and steps:
            steps[-1]["result"] = str(m.content)[:200]
    final = result["messages"][-1].content
    if isinstance(final, list):  # 部分模型返回内容块列表
        final = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in final)
    return {"reply": str(final), "steps": steps, "degraded": False}
