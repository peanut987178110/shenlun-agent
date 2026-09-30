"""答卷识别（PRD 8.3）。

三条路径，按可用性依次选择：
1. PDF 自带文字层：直接提取，视为可信文本。
2. 视觉模型：逐行识别，带行号、置信度、行类型（答案 / 题目 / 草稿）。需要用户已同意图片外发。
3. 手动录入：前两条都不可用时，由用户在确认页输入。

图片发送前会缩到长边 1600 像素并转 JPEG，缩小体积，也去掉了原图的 EXIF（含拍摄地点）。
"""
from __future__ import annotations

import base64
import io
from typing import Literal

from PIL import Image, ImageOps
from pydantic import BaseModel, Field
from pypdf import PdfReader

from app.llm.client import LLMError, complete_json
from app.services.text import word_count

LOW_CONF = 0.8

OCR_SYSTEM = """你是申论手写答卷的文字识别器。只做识别，不做评价，不纠正考生的错别字和语病。
逐行输出图片中的文字，保持原有换行。对每一行给出：
- text：原样转写。看不清的字用 □ 代替，不要猜。
- confidence：0—1，你对这一行识别准确的把握。
- kind：answer（考生正式答案）、question（印刷的题号、题目或说明）、draft（草稿、划掉的内容、页边演算）。
- qno：这一行属于第几题（整数）。依据答题卡上印刷的题号区域（如「一」「第二题」「3.」）判断；
  一道题的答案会延续到下一个题号出现为止，跨页也一样。考生答案内部自己写的「一、二、三」是分条序号，不是题号。
  判断不了填 null。
只输出 JSON：{"lines":[{"text":"...","confidence":0.95,"kind":"answer","qno":1}]}"""


class OcrLine(BaseModel):
    text: str
    confidence: float = Field(ge=0, le=1)
    kind: Literal["answer", "question", "draft"] = "answer"
    qno: int | None = None


class OcrResult(BaseModel):
    lines: list[OcrLine]


def to_data_url(data: bytes, max_side: int = 1600) -> str:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)  # 重新编码，不带 EXIF
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


async def recognize_image(data: bytes, page_no: int, hint: str = "") -> tuple[list[dict], str]:
    """hint：本卷各题的题号与题干开头，帮助模型认题号。上一页最后一题的题号也在里面。"""
    result, model = await complete_json(
        system=OCR_SYSTEM, user=f"这是答卷第 {page_no} 页。{hint}", schema=OcrResult,
        tier="vision", images=[to_data_url(data)], max_tokens=8000)
    return [{"page": page_no, "line": i + 1, "text": ln.text,
             "confidence": round(ln.confidence, 2), "kind": ln.kind, "qno": ln.qno}
            for i, ln in enumerate(result.lines)], model


def pdf_text_pages(data: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(data))
    return [(p.extract_text() or "").strip() for p in reader.pages]


def pdf_page_images(data: bytes) -> list[bytes]:
    """扫描件 PDF：每页取面积最大的内嵌图片。"""
    out: list[bytes] = []
    for page in PdfReader(io.BytesIO(data)).pages:
        imgs = list(page.images)
        if imgs:
            best = max(imgs, key=lambda im: len(im.data))
            out.append(best.data)
    return out


def lines_from_text(text: str, page_no: int) -> list[dict]:
    return [{"page": page_no, "line": i + 1, "text": ln, "confidence": 1.0, "kind": "answer"}
            for i, ln in enumerate(t for t in text.splitlines() if t.strip())]


def answer_text(lines: list[dict]) -> str:
    """只取正式答案行拼成全文，题目和草稿不参与批改。"""
    return "\n".join(ln["text"] for ln in lines if ln.get("kind", "answer") == "answer")


def ocr_quality_factor(source: str, lines: list[dict]) -> float:
    """置信度公式里的「识别质量系数」（需求修订说明第二节）。"""
    if source in ("manual", "pdf_text"):
        return 1.0
    ans = [ln for ln in lines if ln.get("kind", "answer") == "answer"]
    if not ans:
        return 0.7
    low = sum(1 for ln in ans if ln["confidence"] < LOW_CONF) / len(ans)
    return round(1.0 - 0.3 * low, 3)


__all__ = ["LLMError", "recognize_image", "pdf_text_pages", "pdf_page_images",
           "lines_from_text", "answer_text", "ocr_quality_factor", "word_count", "LOW_CONF"]
