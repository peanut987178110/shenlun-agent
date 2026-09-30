"""答卷图像质量检测（PRD 8.2）。

在本地用 Pillow + numpy 完成，不调用任何模型，图片不出本机。
检测发生在 OCR 之前，拿不到行号，因此按「页面水平带」定位问题区域（见需求修订说明 #10）。

阈值是按手机拍摄的 A4 答题纸经验设定的初值，需要用真实答卷校准。
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

BANDS = 8
ANALYSIS_WIDTH = 1000

# 阈值（缩放到 ANALYSIS_WIDTH 后测得）
BLUR_UNREADABLE = 15.0
BLUR_SEVERE = 40.0
BLUR_MILD = 100.0
GLARE_PIXEL = 250
GLARE_BAND_RATIO = 0.08
SHADOW_BAND_RATIO = 0.6   # 带亮度低于整页中位数的 60%
SKEW_WARN_DEG = 3
MIN_SIDE_SEVERE = 600
MIN_SIDE_WARN = 1000
INK_MIN_RATIO = 0.005


@dataclass
class PageQuality:
    grade: str
    issues: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    sha256: str = ""


def _region(i: int, n: int = BANDS) -> str:
    top, bottom = round(i / n * 100), round((i + 1) / n * 100)
    center = (i + 0.5) / n
    name = ("上部" if center < 0.2 else "中上部" if center < 0.4 else "中部" if center < 0.6
            else "中下部" if center < 0.8 else "下部")
    return f"{name}（约 {top}%—{bottom}% 高度）"


def _laplacian_var(g: np.ndarray) -> float:
    if g.shape[0] < 3 or g.shape[1] < 3:
        return 0.0
    c = g[1:-1, 1:-1]
    lap = g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4 * c
    return float(lap.var())


def _ink_mask(g: np.ndarray) -> np.ndarray:
    # 比整页中位亮度暗 40 以上的像素视为笔迹。对阴影不敏感的简单做法，够粗筛用
    return g < (np.median(g) - 40)


def _skew_degrees(img: Image.Image) -> int:
    """投影法估计倾斜角：文字行对齐时，行方向投影的方差最大。"""
    small = img.resize((500, max(1, int(img.height * 500 / img.width))))
    best, best_var = 0, -1.0
    for deg in range(-8, 9):
        rot = np.asarray(small.rotate(deg, fillcolor=255), dtype=np.float32)
        rows = _ink_mask(rot).sum(axis=1)
        v = float(rows.var())
        if v > best_var:
            best, best_var = deg, v
    return best


def check_page(data: bytes) -> PageQuality:
    sha = hashlib.sha256(data).hexdigest()
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("L")
    except (UnidentifiedImageError, OSError, ValueError):
        return PageQuality("D", [{"level": "D", "type": "无法打开", "region": "整页",
                                  "message": "文件不是有效图片或已损坏"}], sha256=sha)

    w, h = img.size
    issues: list[dict[str, Any]] = []
    short = min(w, h)
    if short < MIN_SIDE_SEVERE:
        issues.append({"level": "C", "type": "分辨率过低", "region": "整页",
                       "message": f"图片短边只有 {short} 像素，文字细节可能丢失，请靠近拍摄或使用原图"})
    elif short < MIN_SIDE_WARN:
        issues.append({"level": "B", "type": "分辨率偏低", "region": "整页",
                       "message": f"图片短边 {short} 像素，小字可能识别不准"})

    scaled = img.resize((ANALYSIS_WIDTH, max(BANDS, int(h * ANALYSIS_WIDTH / w))))
    g = np.asarray(scaled, dtype=np.float32)
    ink = _ink_mask(g)
    ink_ratio = float(ink.mean())
    blur = _laplacian_var(g)
    median = float(np.median(g))

    metrics: dict[str, Any] = {"width": w, "height": h, "blur": round(blur, 1),
                               "ink_ratio": round(ink_ratio, 4), "brightness": round(median, 1)}

    if ink_ratio < INK_MIN_RATIO:
        issues.append({"level": "D", "type": "未检测到内容", "region": "整页",
                       "message": "页面上几乎没有笔迹，可能是空白页或拍摄过曝"})
    if blur < BLUR_UNREADABLE:
        issues.append({"level": "D", "type": "严重模糊", "region": "整页",
                       "message": "整页严重模糊，无法识别，请对焦后重拍"})
    elif blur < BLUR_SEVERE:
        issues.append({"level": "C", "type": "模糊", "region": "整页",
                       "message": "整页较模糊，关键内容可能识别错误，建议重拍"})
    elif blur < BLUR_MILD:
        issues.append({"level": "B", "type": "轻微模糊", "region": "整页",
                       "message": "整页略模糊，识别后请重点核对"})

    band_h = g.shape[0] // BANDS
    band_stats = []
    for i in range(BANDS):
        band = g[i * band_h:(i + 1) * band_h]
        glare = float((band >= GLARE_PIXEL).mean())
        mean = float(band.mean())
        band_stats.append({"glare": round(glare, 3), "mean": round(mean, 1),
                           "blur": round(_laplacian_var(band), 1)})
        # 纸面本身接近纯白时（扫描件），高亮像素不代表反光，用整页中位数排除
        if glare > GLARE_BAND_RATIO and median < GLARE_PIXEL - 5:
            issues.append({"level": "C", "type": "反光", "region": _region(i),
                           "message": f"{_region(i)}存在反光，可能影响该区域文字识别"})
        if median > 0 and mean < median * SHADOW_BAND_RATIO:
            issues.append({"level": "B", "type": "阴影", "region": _region(i),
                           "message": f"{_region(i)}偏暗，可能有手机或手的阴影"})
    metrics["bands"] = band_stats

    skew = _skew_degrees(scaled) if ink_ratio >= INK_MIN_RATIO else 0
    metrics["skew"] = skew
    if abs(skew) >= SKEW_WARN_DEG:
        issues.append({"level": "B", "type": "倾斜", "region": "整页",
                       "message": f"页面倾斜约 {abs(skew)}°，建议正对纸面拍摄"})

    # 裁切：边缘 3% 的笔迹密度远高于整页，说明文字可能延伸到了画面外
    edge = max(1, int(min(g.shape) * 0.03))
    for side, strip in (("上边缘", ink[:edge]), ("下边缘", ink[-edge:]),
                        ("左边缘", ink[:, :edge]), ("右边缘", ink[:, -edge:])):
        if ink_ratio >= INK_MIN_RATIO and float(strip.mean()) > ink_ratio * 2.5:
            issues.append({"level": "B", "type": "可能裁切", "region": side,
                           "message": f"{side}有较多笔迹，内容可能被裁掉，请确认整页都在画面内"})

    order = {"A": 0, "B": 1, "C": 2, "D": 3}
    grade = max((i["level"] for i in issues), key=lambda x: order[x], default="A")
    return PageQuality(grade, issues, metrics, sha)


def overall_grade(grades: list[str]) -> str:
    order = "ABCD"
    return max(grades, key=order.index) if grades else "D"
