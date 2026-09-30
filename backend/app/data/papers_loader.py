"""真题 JSON 的校验与读取。格式见 papers/README.md。

直接运行即校验全部文件：python backend/app/data/papers_loader.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PAPERS_DIR = Path(__file__).resolve().parent / "papers"
QTYPES = {"summary", "analysis", "countermeasure", "official", "essay"}
# D 类（村干部）考《综合应用能力》，不是申论，不收
CODES = {"A", "B", "C"}
STATUSES = {"complete", "questions_only"}


def validate(d: dict[str, Any], fname: str = "") -> list[str]:
    errs: list[str] = []

    def need(key: str, typ: type) -> None:
        if not isinstance(d.get(key), typ):
            errs.append(f"缺少或类型错误：{key}")

    for k, t in (("year", int), ("code", str), ("category", str), ("name", str), ("topic", str),
                 ("status", str), ("sources", list), ("materials", list), ("questions", list)):
        need(k, t)
    if errs:
        return errs
    if d["code"] not in CODES:
        errs.append(f"code 必须是 {CODES}")
    if d["status"] not in STATUSES:
        errs.append(f"status 必须是 {STATUSES}")
    if fname and fname != f"{d['year']}_{d['code']}.json":
        errs.append(f"文件名应为 {d['year']}_{d['code']}.json")
    if not d["sources"] or not all(isinstance(s, dict) and s.get("url") for s in d["sources"]):
        errs.append("sources 至少一条，且每条要有 url")

    nos = set()
    for i, m in enumerate(d["materials"]):
        if not (isinstance(m.get("no"), int) and isinstance(m.get("paragraph"), int)
                and isinstance(m.get("text"), str) and m["text"].strip()):
            errs.append(f"materials[{i}] 需要 no、paragraph（整数）和非空 text")
            continue
        nos.add(m["no"])
    if d["status"] == "complete" and not d["materials"]:
        errs.append("status=complete 但没有材料")
    if d["status"] == "questions_only" and d["materials"]:
        errs.append("有材料时 status 应为 complete")

    total = 0.0
    if not d["questions"]:
        errs.append("没有题目")
    for i, q in enumerate(d["questions"]):
        where = f"questions[{i}]"
        if q.get("qtype") not in QTYPES:
            errs.append(f"{where}.qtype 必须是 {QTYPES}")
        if not isinstance(q.get("stem"), str) or len(q["stem"]) < 10:
            errs.append(f"{where}.stem 缺失或过短")
        if not isinstance(q.get("full_score"), (int, float)) or q["full_score"] <= 0:
            errs.append(f"{where}.full_score 必须为正数")
        else:
            total += q["full_score"]
        for k in ("word_min", "word_max"):
            if not isinstance(q.get(k, 0), int):
                errs.append(f"{where}.{k} 必须是整数")
        refs = q.get("material_refs", [])
        if not isinstance(refs, list) or any(not isinstance(r, int) for r in refs):
            errs.append(f"{where}.material_refs 必须是整数列表")
        elif d["materials"] and any(r not in nos for r in refs):
            errs.append(f"{where}.material_refs 引用了不存在的材料 {sorted(set(refs) - nos)}")
    full = d.get("full_score", 100)
    if d["questions"] and abs(total - full) > 0.01:
        errs.append(f"各题分值之和 {total} ≠ 试卷满分 {full}")
    return errs


def load_all() -> list[dict[str, Any]]:
    """读取全部通过校验的试卷。校验不通过的文件跳过并打印原因，不阻止启动。"""
    out = []
    for f in sorted(PAPERS_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[题库] 跳过 {f.name}：无法解析（{e}）")
            continue
        errs = validate(d, f.name)
        if errs:
            print(f"[题库] 跳过 {f.name}：{'；'.join(errs[:3])}")
            continue
        out.append(d)
    return out


if __name__ == "__main__":
    files = sorted(PAPERS_DIR.glob("*.json"))
    bad = 0
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            errs = validate(d, f.name)
        except json.JSONDecodeError as e:
            errs = [f"JSON 解析失败：{e}"]
        if errs:
            bad += 1
            print(f"✗ {f.name}")
            for e in errs:
                print(f"    {e}")
        else:
            n_chars = sum(len(m["text"]) for m in d["materials"])
            print(f"✓ {f.name}  {d['status']}  材料 {n_chars} 字  题目 {len(d['questions'])} 道  {d['topic']}")
    print(f"共 {len(files)} 个文件，{bad} 个不通过")
    sys.exit(1 if bad else 0)
