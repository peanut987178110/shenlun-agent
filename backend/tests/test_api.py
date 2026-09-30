"""接口端到端：选卷 → 整卷手动录入 → 按题批改 → 提示 → 修改复评 → 对比 → 申诉 → 教师复核。"""
from __future__ import annotations

import asyncio
import io

import httpx
import pytest
from PIL import Image, ImageDraw

from app.core.security import hash_password
from app.db.models import User
from app.db.session import SessionLocal
from main import app

Q1 = ("一、老年村民不会用平台，使用率低。\n二、部分干部搞形式主义，把平台当留痕工具。\n"
      "三、群众诉求响应慢，办结率低。")
Q1_REVISED = Q1 + "\n四、部门数据不互通，信息重复录入。\n五、报表多，加重基层负担。"
Q2 = "一、配备数字代办员，由网格员为老年村民代录诉求。\n二、打通部门数据，统一采集标准。"


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield c


async def _register(c, name: str) -> dict:
    r = await c.post("/api/auth/register", json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def _sample_paper(c, h) -> dict:
    papers = (await c.get("/api/bank/papers", headers=h)).json()
    return next(p for p in papers if p["origin"] == "sample" and len(p["questions"]) == 5)


async def _wait_sheet(c, h, sid: int) -> dict:
    for _ in range(200):
        d = (await c.get(f"/api/sheets/{sid}", headers=h)).json()
        if d["status"] == "graded":
            return d
        await asyncio.sleep(0.05)
    raise AssertionError(f"批改超时：{d['items']}")


async def _wait_sub(c, h, sid: int) -> dict:
    for _ in range(200):
        d = (await c.get(f"/api/submissions/{sid}", headers=h)).json()
        if d["status"] in ("graded", "failed"):
            return d
        await asyncio.sleep(0.05)
    raise AssertionError("复评超时")


async def test_auth_required_and_no_header_bypass(client):
    assert (await client.get("/api/profile/dashboard")).status_code == 401
    assert (await client.get("/api/profile/dashboard", headers={"X-User-Id": "1"})).status_code == 401
    r = await client.get("/api/profile/dashboard", headers={"Authorization": "Bearer forged.token"})
    assert r.status_code == 401


async def test_bank_shows_materials_but_not_scoring_points(client):
    h = await _register(client, "bank_user")
    p = await _sample_paper(client, h)
    detail = (await client.get(f"/api/bank/papers/{p['id']}", headers=h)).json()
    assert detail["materials"] and detail["origin"] == "sample"
    q = detail["questions"][0]
    assert "reference_answer" not in q and "points" not in q


async def test_whole_paper_flow(client):
    h = await _register(client, "flow_user")
    p = await _sample_paper(client, h)
    q1, q2 = p["questions"][0], p["questions"][1]
    sheet = (await client.post("/api/sheets", json={"paper_id": p["id"],
                                                    "question_ids": [q1["id"], q2["id"]]}, headers=h)).json()
    assert [q["no"] for q in sheet["questions"]] == [1, 2]

    # 整卷按题录入。手机号在提交时脱敏
    r = await client.post(f"/api/sheets/{sheet['id']}/submit", headers=h,
                          json={"answers": {"1": Q1 + "\n电话13812345678", "2": Q2}})
    assert r.status_code == 200, r.text
    d = await _wait_sheet(client, h, sheet["id"])
    assert len(d["items"]) == 2 and all(i["score"] is not None for i in d["items"])
    item1 = next(i for i in d["items"] if i["question_no"] == 1)

    sub = (await client.get(f"/api/submissions/{item1['submission_id']}", headers=h)).json()
    assert "13812345678" not in sub["versions"][0]["text"]
    rid1 = item1["review_id"]
    rv = (await client.get(f"/api/reviews/{rid1}", headers=h)).json()
    assert rv["method"] == "rule" and rv["disclaimer"] and "hints" not in rv
    assert rv["score_low"] <= rv["score"] <= rv["score_high"]

    # 分层提示逐级解锁
    assert (await client.post(f"/api/reviews/{rid1}/hints/4", headers=h)).status_code == 400
    for lv in (1, 2, 3):
        hr = await client.post(f"/api/reviews/{rid1}/hints/{lv}", headers=h)
        assert hr.status_code == 200
    assert "L4" not in hr.json()["hints"]

    # 修改复评：解锁过 L3，记为 AI 指导版
    r = await client.post(f"/api/submissions/{item1['submission_id']}/revise", json={"text": Q1_REVISED}, headers=h)
    assert r.json()["kind"] == "guided"
    sub = await _wait_sub(client, h, item1["submission_id"])
    rid2 = sub["latest_review_id"]
    cmp = (await client.get(f"/api/reviews/{rid2}/compare/{rid1}", headers=h)).json()
    assert cmp["score_delta"] > 0 and len(cmp["gained_points"]) == 2

    # 申诉 → 教师复核
    rv2 = (await client.get(f"/api/reviews/{rid2}", headers=h)).json()
    pid = rv2["points"][0]["id"]
    r = await client.post(f"/api/reviews/{rid2}/appeals", headers=h,
                          json={"point_id": pid, "reason": "我写了「老年村民不会用平台」"})
    assert r.status_code == 200 and r.json()["recheck"]["quoted_found"]
    assert (await client.get("/api/teacher/queue", headers=h)).status_code == 403

    async with SessionLocal() as db:
        db.add(User(username="teacher_t1", password_hash=hash_password("password123"), role="teacher"))
        await db.commit()
    th = {"Authorization": "Bearer " + (await client.post(
        "/api/auth/login", json={"username": "teacher_t1", "password": "password123"})).json()["token"]}
    item = next(x for x in (await client.get("/api/teacher/queue", headers=th)).json() if x["review_id"] == rid2)
    assert item["student"].startswith("学员 #") and item["open_appeals"] == 1
    det = (await client.get(f"/api/teacher/reviews/{rid2}", headers=th)).json()
    r = await client.post(f"/api/teacher/reviews/{rid2}", headers=th, json={
        "points": [{"id": pid, "status": "partial"}], "teacher_score": 12, "note": "不错",
        "appeals": [{"id": det["appeals"][0]["id"], "decision": "维持部分命中"}]})
    assert r.status_code == 200
    rv2 = (await client.get(f"/api/reviews/{rid2}", headers=h)).json()
    assert rv2["teacher_score"] == 12 and rv2["points"][0]["ai_status"] == "hit"

    sheets = (await client.get("/api/sheets", headers=h)).json()
    assert sheets[0]["questions"] == 2 and sheets[0]["score"] is not None


async def test_recognized_lines_split_by_question(client):
    """识别行带 qno 提交：各题答案分开，题目行和草稿不进答案。"""
    h = await _register(client, "split_user")
    p = await _sample_paper(client, h)
    sheet = (await client.post("/api/sheets", json={"paper_id": p["id"]}, headers=h)).json()
    lines = [{"text": "第一题", "kind": "question", "qno": 1},
             {"text": Q1, "kind": "answer", "qno": 1},
             {"text": "草稿：老人 形式", "kind": "draft", "qno": 1},
             {"text": Q2, "kind": "answer", "qno": 2}]
    await client.post(f"/api/sheets/{sheet['id']}/submit", json={"lines": lines}, headers=h)
    d = await _wait_sheet(client, h, sheet["id"])
    texts = {}
    for i in d["items"]:
        s = (await client.get(f"/api/submissions/{i['submission_id']}", headers=h)).json()
        texts[i["question_no"]] = s["versions"][0]["text"]
    assert set(texts) == {1, 2}
    assert "草稿" not in texts[1] and "第一题" not in texts[1] and texts[2] == Q2


async def test_paper_guess_after_upload_without_paper(client):
    """没选试卷就上传：按答案内容猜出是哪套卷，确认后按题号重新切分。"""
    from app.api.sheet_api import _guess
    h = await _register(client, "guess_user")
    sheet = (await client.post("/api/sheets", json={}, headers=h)).json()
    async with SessionLocal() as db:
        guess = await _guess(db, [{"text": Q1_REVISED, "kind": "answer"}])
    p = await _sample_paper(client, h)
    assert guess[0]["paper_id"] == p["id"] and guess[0]["material_cover"] > 0.3
    r = await client.post(f"/api/sheets/{sheet['id']}/paper", json={"paper_id": p["id"]}, headers=h)
    assert r.json()["paper"]["id"] == p["id"]


async def test_other_user_cannot_see_sheet_or_submission(client):
    h1 = await _register(client, "owner_u")
    h2 = await _register(client, "intruder")
    p = await _sample_paper(client, h1)
    sheet = (await client.post("/api/sheets", json={"paper_id": p["id"]}, headers=h1)).json()
    assert (await client.get(f"/api/sheets/{sheet['id']}", headers=h2)).status_code == 404
    r = await client.post(f"/api/sheets/{sheet['id']}/submit", json={"answers": {"1": Q1}}, headers=h2)
    assert r.status_code == 404
    await client.post(f"/api/sheets/{sheet['id']}/submit", json={"answers": {"1": Q1}}, headers=h1)
    d = await _wait_sheet(client, h1, sheet["id"])
    sub_id = d["items"][0]["submission_id"]
    assert (await client.get(f"/api/submissions/{sub_id}", headers=h2)).status_code == 404


def _page(blank: bool = False) -> bytes:
    img = Image.new("L", (1240, 1754), 235)
    if not blank:
        d = ImageDraw.Draw(img)
        for y in range(120, 1650, 42):
            for x in range(80, 1160, 26):
                d.rectangle([x, y, x + 16, y + 22], outline=40, width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def test_upload_quality_and_recognize_guard(client):
    h = await _register(client, "upload_u")
    sid = (await client.post("/api/sheets", json={}, headers=h)).json()["id"]
    files = [("files", ("a.png", _page(), "image/png")), ("files", ("b.png", _page(), "image/png")),
             ("files", ("c.png", _page(blank=True), "image/png"))]
    d = (await client.post(f"/api/sheets/{sid}/pages", files=files, headers=h)).json()
    grades = [p["grade"] for p in d["pages"]]
    assert grades[0] in ("A", "B")
    assert grades[1] == "C" and any(i["type"] == "重复页" for i in d["pages"][1]["issues"])
    assert grades[2] == "D" and d["quality_grade"] == "D"
    assert (await client.post(f"/api/sheets/{sid}/recognize", json={}, headers=h)).status_code == 400
    r = await client.post(f"/api/sheets/{sid}/pages", headers=h,
                          files=[("files", ("x.png", b"not an image", "image/png"))])
    assert r.status_code == 400
    assert (await client.delete(f"/api/sheets/{sid}/images", headers=h)).json()["deleted"] == 3
    assert (await client.get(f"/api/sheets/{sid}/pages/1/image", headers=h)).status_code == 404


async def test_real_question_without_rubric_needs_llm(client):
    """真题没有评分点：未配置模型时明确拒绝，而不是给一个没有依据的分数。"""
    from app.db.models import Material, Paper, Question
    h = await _register(client, "real_u")
    async with SessionLocal() as db:
        p = Paper(name="测试真题卷", year=2025, code="A", category="综合类", origin="real", topic="t")
        db.add(p)
        await db.flush()
        db.add(Material(paper_id=p.id, no=1, paragraph=1, text="材料正文" * 20))
        db.add(Question(paper_id=p.id, no=1, qtype="summary", stem="根据给定资料1，概括问题。（20分）",
                        full_score=20, material_refs=[1]))
        await db.commit()
        pid = p.id
    sheet = (await client.post("/api/sheets", json={"paper_id": pid}, headers=h)).json()
    r = await client.post(f"/api/sheets/{sheet['id']}/submit", json={"answers": {"1": Q1}}, headers=h)
    assert r.status_code == 400 and "评分配置" in r.json()["detail"]


async def test_import_paper_preview_save_replace(client, monkeypatch, tmp_path):
    from app.api import bank_api
    monkeypatch.setattr(bank_api, "PAPERS_DIR", tmp_path)  # 不往仓库里写
    h = await _register(client, "import_u")
    text = ("资料1\n" + "第一则材料正文，讲县域执法。" * 10 + "\n资料2\n" + "第二则材料正文，讲群众反映。" * 10 +
            "\n作答要求\n一、根据资料1，概括存在的问题。（20分）\n要求：全面准确，不超过300字。\n"
            "二、根据资料2，写一则短评。（30分）\n要求：\n（1）观点鲜明；\n（2）不超过500字。\n"
            "三、结合给定资料，自选角度，自拟题目，写一篇议论性文章。（50分）\n要求：\n（1）观点明确；\n（2）1000—1200字。")
    pv = (await client.post("/api/bank/import/preview", json={"year": 2099, "code": "B", "text": text}, headers=h)).json()
    assert pv["errors"] == []
    d = pv["paper"]
    assert [q["qtype"] for q in d["questions"]] == ["summary", "official", "essay"]
    assert [q["material_refs"] for q in d["questions"]] == [[1], [2], []]
    r = await client.post("/api/bank/import", json={"paper": d, "source_url": "https://example.com/p"}, headers=h)
    assert r.status_code == 200, r.text
    assert (tmp_path / "2099_B.json").exists()
    pid = r.json()["id"]
    assert (await client.post("/api/bank/import", json={"paper": d}, headers=h)).status_code == 409
    r = await client.post("/api/bank/import", json={"paper": d, "replace": True}, headers=h)
    assert r.status_code == 200
    reals = [p for p in (await client.get("/api/bank/papers", params={"year": 2099, "code": "B"}, headers=h)).json()]
    assert len(reals) == 1 and pid  # 替换后只剩一套
    # 作答过的卷不能被替换
    new_pid = r.json()["id"]
    s = (await client.post("/api/sheets", json={"paper_id": new_pid}, headers=h)).json()
    from app.db.models import Question, Submission
    async with SessionLocal() as db:
        from sqlalchemy import select
        qid = (await db.execute(select(Question.id).where(Question.paper_id == new_pid))).scalars().first()
        db.add(Submission(user_id=1, sheet_id=s["id"], question_id=qid))
        await db.commit()
    r = await client.post("/api/bank/import", json={"paper": d, "replace": True}, headers=h)
    assert r.status_code == 409 and "作答过" in r.json()["detail"]


async def test_material_marks_saved_and_private(client):
    h1 = await _register(client, "mark_u")
    h2 = await _register(client, "mark_x")
    p = await _sample_paper(client, h1)
    sid = (await client.post("/api/sheets", json={"paper_id": p["id"]}, headers=h1)).json()["id"]
    marks = [{"no": 1, "paragraph": 2, "start": 3, "end": 10, "style": "yellow"},
             {"no": 1, "paragraph": 2, "start": 5, "end": 8, "style": "underline"}]
    r = await client.put(f"/api/sheets/{sid}/marks", json={"marks": marks}, headers=h1)
    assert r.json()["count"] == 2
    assert (await client.get(f"/api/sheets/{sid}", headers=h1)).json()["marks"] == marks
    bad = [{"no": 1, "paragraph": 1, "start": 0, "end": 5, "style": "<script>"}]
    assert (await client.put(f"/api/sheets/{sid}/marks", json={"marks": bad}, headers=h1)).status_code == 422
    assert (await client.put(f"/api/sheets/{sid}/marks", json={"marks": []}, headers=h2)).status_code == 404


async def test_assistant_and_generator_degrade_without_llm(client):
    h = await _register(client, "asst_u")
    r = (await client.post("/api/assistant/chat", json={"message": "2025年A卷考了什么"}, headers=h)).json()
    assert r["degraded"] is True
    assert (await client.post("/api/generate", json={"code": "A"}, headers=h)).status_code == 400
    assert (await client.post("/api/generate", json={"code": "D"}, headers=h)).status_code == 422
