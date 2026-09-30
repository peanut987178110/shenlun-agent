"""数据模型。

相对 PRD 第 17 章的调整（见 docs/需求修订说明.md）：
- 材料挂在试卷下，不挂题目。申论材料整卷共享，题目用 material_refs 引用材料编号。
- 评分配置单独成表并版本化：每次批改记录用的是哪个版本，配置更新后旧结果仍可追溯。
- 补了申诉、错误模式、训练处方三张表，以及上传页面表（原图可单独删除）。
- 批注、得分点结果、增分建议作为批改结果的一部分以 JSON 存储：它们只随一次批改产生和读取，
  没有跨批改查询的需求，拆表只会增加写入复杂度。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 题型
QTYPES = {
    "summary": "归纳概括",
    "analysis": "综合分析",
    "countermeasure": "提出对策",
    "official": "应用文",
    "essay": "大作文",
}


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


def _now() -> datetime:
    return datetime.now()


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(64), default="")
    role: Mapped[str] = mapped_column(String(16), default="student")  # student / teacher
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 目标设置（PRD 8.1）
    exam_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exam_category: Mapped[str] = mapped_column(String(32), default="")
    target_region: Mapped[str] = mapped_column(String(32), default="")
    target_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_level: Mapped[str] = mapped_column(String(16), default="")
    exam_date: Mapped[str] = mapped_column(String(16), default="")
    # 隐私（PRD 19.4 修订）：None 表示尚未询问
    consent_vision: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    allow_training_data: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# 浙江省考试卷类别。D 卷考《综合应用能力》，不考申论，题库不收
PAPER_CODES = {
    "A": "综合类（县级以上机关）",
    "B": "基层类（乡镇街道）",
    "C": "行政执法类",
}
ORIGINS = {"real": "真题", "generated": "AI 模拟卷", "sample": "示例题"}


class Paper(Base):
    __tablename__ = "papers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    exam: Mapped[str] = mapped_column(String(32), default="浙江省考")
    year: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(1), default="")  # A / B / C
    category: Mapped[str] = mapped_column(String(32))
    batch: Mapped[str] = mapped_column(String(32), default="")
    theme: Mapped[str] = mapped_column(String(64), default="")
    topic: Mapped[str] = mapped_column(Text, default="")
    # real 真题 / generated AI 模拟卷 / sample 示例题。界面按它标注，不混淆
    origin: Mapped[str] = mapped_column(String(16), default="sample")
    # complete / questions_only / generating / failed
    status: Mapped[str] = mapped_column(String(16), default="complete")
    status_note: Mapped[str] = mapped_column(Text, default="")
    exam_date: Mapped[str] = mapped_column(String(16), default="")
    sources: Mapped[list[Any]] = mapped_column(default=list)
    source_key: Mapped[str] = mapped_column(String(32), default="")  # 真题文件名，用于幂等导入
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    source: Mapped[str] = mapped_column(String(32), default="自编示例")
    is_sample: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[str] = mapped_column(String(16), default="1")


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    no: Mapped[int] = mapped_column(Integer)          # 材料编号
    paragraph: Mapped[int] = mapped_column(Integer)   # 段落编号
    text: Mapped[str] = mapped_column(Text)
    # 事实 / 问题 / 原因 / 影响 / 对策 / 案例 / 观点
    content_type: Mapped[str] = mapped_column(String(16), default="")
    keywords: Mapped[list[Any]] = mapped_column(default=list)


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    no: Mapped[int] = mapped_column(Integer)
    qtype: Mapped[str] = mapped_column(String(16))
    stem: Mapped[str] = mapped_column(Text)
    full_score: Mapped[float] = mapped_column(Float)
    word_min: Mapped[int] = mapped_column(Integer, default=0)
    word_max: Mapped[int] = mapped_column(Integer, default=0)
    material_refs: Mapped[list[Any]] = mapped_column(default=list)  # 材料编号列表
    format_req: Mapped[str] = mapped_column(Text, default="")
    reference_answer: Mapped[str] = mapped_column(Text, default="")
    theme: Mapped[str] = mapped_column(String(64), default="")


class Rubric(Base):
    """评分配置。一题可有多个版本，active 的那个用于新批改。"""
    __tablename__ = "rubrics"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    version: Mapped[str] = mapped_column(String(16), default="1")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 教研编写 / 机构参考 / 用户自定义 / 自编示例。界面不出现「官方」
    source: Mapped[str] = mapped_column(String(32), default="自编示例")
    # [{key, name, mode: points|level, max, guide}]
    dimensions: Mapped[list[Any]] = mapped_column(default=list)
    # 字数规则：{"over_per": 50, "over_deduct": 1, "under_ratio": 0.8, "under_deduct": 1}
    word_rule: Mapped[dict[str, Any]] = mapped_column(default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ScoringPoint(Base):
    __tablename__ = "scoring_points"
    id: Mapped[int] = mapped_column(primary_key=True)
    rubric_id: Mapped[int] = mapped_column(ForeignKey("rubrics.id"), index=True)
    dimension: Mapped[str] = mapped_column(String(32), default="content")
    label: Mapped[str] = mapped_column(String(128))
    material_ref: Mapped[str] = mapped_column(String(64), default="")  # 如「材料2第3段」
    # 命中判定：keywords 里每组至少命中一个词。组内是同义词，组间是「且」
    keywords: Mapped[list[Any]] = mapped_column(default=list)
    partial: Mapped[list[Any]] = mapped_column(default=list)       # 部分命中表达
    unacceptable: Mapped[list[Any]] = mapped_column(default=list)  # 不可接受表达
    score: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(Text, default="")


class Sheet(Base):
    """一份答卷：对应一套试卷，可以含多道题的答案。

    流程：选卷（或上传后自动匹配试卷）→ 上传 / 录入 → 识别 → 按题切分并确认 → 每道题各建一个
    Submission 分别批改。答题卡上一页往往写着好几道题，所以上传和识别以答卷为单位，批改以题为单位。
    """
    __tablename__ = "sheets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    paper_id: Mapped[int | None] = mapped_column(ForeignKey("papers.id"), nullable=True)
    question_ids: Mapped[list[Any]] = mapped_column(default=list)  # 本次作答的题；空 = 整卷
    # draft / recognized / split / grading / graded
    status: Mapped[str] = mapped_column(String(16), default="draft")
    quality_grade: Mapped[str] = mapped_column(String(1), default="")
    ocr_source: Mapped[str] = mapped_column(String(16), default="")  # vision / pdf_text / manual
    ocr_lines: Mapped[list[Any]] = mapped_column(default=list)
    ocr_note: Mapped[str] = mapped_column(Text, default="")
    paper_guess: Mapped[list[Any]] = mapped_column(default=list)
    # 在线作答时在给定资料上做的标记：[{no, paragraph, start, end, style}]，按字符偏移定位
    marks: Mapped[list[Any]] = mapped_column(default=list)
    time_spent_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SheetPage(Base):
    __tablename__ = "sheet_pages"
    id: Mapped[int] = mapped_column(primary_key=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("sheets.id"), index=True)
    page_no: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(String(256), default="")  # 删除原图后置空
    sha256: Mapped[str] = mapped_column(String(64), default="")
    grade: Mapped[str] = mapped_column(String(1), default="")
    issues: Mapped[list[Any]] = mapped_column(default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Submission(Base):
    """一道题的作答。来自答卷切分（sheet_id 非空），批改、修改复评都以它为单位。"""
    __tablename__ = "submissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    sheet_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"), nullable=True)
    # uploaded / recognized / confirmed / matched / grading / graded / failed
    status: Mapped[str] = mapped_column(String(16), default="uploaded")
    quality_grade: Mapped[str] = mapped_column(String(1), default="")
    # vision / pdf_text / manual
    ocr_source: Mapped[str] = mapped_column(String(16), default="")
    ocr_lines: Mapped[list[Any]] = mapped_column(default=list)
    ocr_note: Mapped[str] = mapped_column(Text, default="")
    # exact / similar / generic
    match_level: Mapped[str] = mapped_column(String(16), default="")
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    custom_stem: Mapped[str] = mapped_column(Text, default="")
    custom_qtype: Mapped[str] = mapped_column(String(16), default="")
    custom_full_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_spent_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SubmissionPage(Base):
    __tablename__ = "submission_pages"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    page_no: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(String(256), default="")  # 删除原图后置空
    sha256: Mapped[str] = mapped_column(String(64), default="")
    grade: Mapped[str] = mapped_column(String(1), default="")
    issues: Mapped[list[Any]] = mapped_column(default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)


class AnswerVersion(Base):
    __tablename__ = "answer_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    # original / self_revised / guided / timed_rewrite
    kind: Mapped[str] = mapped_column(String(16), default="original")
    text: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Review(Base):
    """一次批改结果。字段对应 PRD 17.7，外加评分方式、提示词版本、置信度因子与执行轨迹。"""
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    answer_version_id: Mapped[int] = mapped_column(ForeignKey("answer_versions.id"), index=True)
    method: Mapped[str] = mapped_column(String(8))  # llm / rule
    model: Mapped[str] = mapped_column(String(64), default="")
    prompt_version: Mapped[str] = mapped_column(String(16), default="")
    rubric_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rubric_version: Mapped[str] = mapped_column(String(16), default="")
    full_score: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)
    score_low: Mapped[float] = mapped_column(Float)
    score_high: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    confidence_factors: Mapped[dict[str, Any]] = mapped_column(default=dict)
    dimensions: Mapped[list[Any]] = mapped_column(default=list)
    points: Mapped[list[Any]] = mapped_column(default=list)       # 评分账本
    annotations: Mapped[list[Any]] = mapped_column(default=list)  # 红线批注
    suggestions: Mapped[list[Any]] = mapped_column(default=list)  # 反事实增分
    diagnosis: Mapped[list[Any]] = mapped_column(default=list)    # 失分因果
    hints: Mapped[dict[str, Any]] = mapped_column(default=dict)   # 分层提示
    # 学员已解锁的提示级别 0—4。解锁到 L3 以上后提交的修改记为「AI 指导版」
    hint_level: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    word_penalty: Mapped[float] = mapped_column(Float, default=0.0)
    trace: Mapped[list[Any]] = mapped_column(default=list)
    notice: Mapped[str] = mapped_column(Text, default="")
    # none / queued / reviewed
    review_status: Mapped[str] = mapped_column(String(16), default="none")
    teacher_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    teacher_note: Mapped[str] = mapped_column(Text, default="")
    teacher_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Appeal(Base):
    __tablename__ = "appeals"
    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    point_label: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)
    # pending / rechecked / resolved
    status: Mapped[str] = mapped_column(String(16), default="pending")
    recheck: Mapped[dict[str, Any]] = mapped_column(default=dict)
    decision: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ErrorPattern(Base):
    __tablename__ = "error_patterns"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    error_type: Mapped[str] = mapped_column(String(64))
    frequency: Mapped[int] = mapped_column(Integer, default=0)
    # 最近 5 次批改里出现的次数
    recent_frequency: Mapped[int] = mapped_column(Integer, default=0)
    severity: Mapped[str] = mapped_column(String(8), default="medium")
    trigger_conditions: Mapped[list[Any]] = mapped_column(default=list)
    recommended_training: Mapped[list[Any]] = mapped_column(default=list)
    # not_mastered / unstable / mastered
    mastery_status: Mapped[str] = mapped_column(String(16), default="not_mastered")
    example: Mapped[str] = mapped_column(Text, default="")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AbilityRecord(Base):
    __tablename__ = "ability_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    dimension: Mapped[str] = mapped_column(String(32))
    score: Mapped[float] = mapped_column(Float, default=0.0)  # 0—100
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    trend: Mapped[str] = mapped_column(String(8), default="flat")
    mastery: Mapped[str] = mapped_column(String(16), default="未建立")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Prescription(Base):
    __tablename__ = "prescriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    error_type: Mapped[str] = mapped_column(String(64))
    goal: Mapped[str] = mapped_column(String(128))
    frequency: Mapped[int] = mapped_column(Integer, default=0)
    impact: Mapped[str] = mapped_column(String(64), default="")
    steps: Mapped[list[Any]] = mapped_column(default=list)
    est_minutes: Mapped[int] = mapped_column(Integer, default=30)
    pass_criteria: Mapped[list[Any]] = mapped_column(default=list)
    # 产生处方的那次作答。复测不通过时用它判断「原题修复但迁移失败」（PRD 23.6）
    source_submission_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retest_question_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retest_submission_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retest_after: Mapped[str] = mapped_column(String(16), default="")
    # active / passed / failed
    status: Mapped[str] = mapped_column(String(16), default="active")
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
