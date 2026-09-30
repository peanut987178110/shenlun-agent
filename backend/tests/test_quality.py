"""图像质量检测：用合成图片验证各类问题能被检出并定位到区域。"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFilter

from app.services.image_quality import check_page
from app.services.text import mask_pii, word_count


def _sheet(w: int = 1240, h: int = 1754) -> Image.Image:
    img = Image.new("L", (w, h), 230)
    d = ImageDraw.Draw(img)
    for y in range(120, h - 100, 42):
        for x in range(80, w - 80, 26):
            d.rectangle([x, y, x + 16, y + 22], outline=40, width=2)
    return img


def _bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def test_clean_page_is_a_or_b():
    q = check_page(_bytes(_sheet()))
    assert q.grade in ("A", "B"), q.issues


def test_blur_detected():
    q = check_page(_bytes(_sheet().filter(ImageFilter.GaussianBlur(6))))
    assert q.grade in ("C", "D") and any("模糊" in i["type"] for i in q.issues)


def test_glare_located_to_region():
    img = _sheet()
    ImageDraw.Draw(img).rectangle([0, 900, 1240, 1100], fill=255)  # 约 51%—63% 高度
    q = check_page(_bytes(img))
    glare = [i for i in q.issues if i["type"] == "反光"]
    assert glare and all("中" in i["region"] for i in glare)


def test_small_image_flagged():
    q = check_page(_bytes(_sheet().resize((400, 566))))
    assert any(i["type"] == "分辨率过低" for i in q.issues)


def test_skew_detected():
    q = check_page(_bytes(_sheet().rotate(6, fillcolor=230, expand=False)))
    assert abs(q.metrics["skew"]) >= 3


def test_not_an_image():
    assert check_page(b"hello").grade == "D"


def test_word_count_includes_punctuation():
    assert word_count("一、老人 不会用。\n") == 8


def test_mask_pii():
    s = mask_pii("电话13812345678，身份证330102199001011234，准考证号：A12345678")
    assert "138" not in s and "330102" not in s and "A12345678" not in s
