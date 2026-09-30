"""文本工具：字数、归一化、隐私脱敏、相似度。"""
from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[，。、；：？！“”‘’（）《》【】—…·,.;:?!\"'()\[\]<>\-]")


def word_count(text: str) -> int:
    """申论字数：去掉空白后的字符数，含标点（与方格纸占格一致）。"""
    return len(_WS.sub("", text or ""))


def normalize(text: str) -> str:
    """用于关键词匹配：去空白、去标点、数字统一为半角。"""
    t = _WS.sub("", text or "")
    t = t.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    return _PUNCT.sub("", t)


# 隐私脱敏。顺序有讲究：身份证号比手机号长，先替换长的，避免被手机号规则切掉一截。
_PII_RULES = [
    (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "［身份证号］"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "［手机号］"),
    (re.compile(r"(准考证号?|考号)\s*[:：]?\s*[A-Za-z0-9]{6,}"), r"\1［已脱敏］"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "［邮箱］"),
]


def mask_pii(text: str) -> str:
    for pat, repl in _PII_RULES:
        text = pat.sub(repl, text)
    return text


def ngram_similarity(a: str, b: str, n: int = 2) -> float:
    """字符 n-gram 的 Jaccard 相似度。中文无需分词，题干匹配够用。"""
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    ga = {a[i:i + n] for i in range(max(1, len(a) - n + 1))}
    gb = {b[i:i + n] for i in range(max(1, len(b) - n + 1))}
    return len(ga & gb) / len(ga | gb)


def split_sentences(text: str) -> list[str]:
    """按中文句末标点和换行切句，保留标点。"""
    parts = re.split(r"(?<=[。！？；\n])", text or "")
    return [p for p in (s.strip() for s in parts) if p]
