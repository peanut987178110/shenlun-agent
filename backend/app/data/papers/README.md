# 真题数据

每套试卷一个 JSON 文件，命名 `{年份}_{卷别}.json`，如 `2025_A.json`。启动时自动导入题库。

校验：`python backend/app/data/papers_loader.py`（在项目根目录，用 .venv 的 python）

## 浙江省考试卷类别

| 卷别 | 考试类别 | 适用职位 | 笔试科目 |
|---|---|---|---|
| A | 综合类 | 县级以上机关（不含行政执法类） | 行测 A + 申论 A |
| B | 基层类 | 乡镇（街道）机关（不含村干部职位） | 行测 B + 申论 B |
| C | 行政执法类 | 公安执勤、司法警察、综合执法、市场监管、生态环保等一线执法职位 | 行测 C + 申论 C |
| D | 村干部类 | 乡镇（街道）面向村干部的职位 | 行测 D + 《综合应用能力》（不考申论） |

来源：华图教育整理的 2023 年浙江省考公告考试类别，<https://www.huatu.com/2023/0831/2682260.html>。每年以当年省考公告为准。

## 字段

```json
{
  "year": 2025,
  "code": "A",
  "category": "综合类（县级以上机关）",
  "name": "2025年浙江省考申论A卷",
  "exam_date": "2024-12-08",
  "topic": "一句话概括本卷主题",
  "time_limit_min": 150,
  "full_score": 100,
  "status": "complete",
  "sources": [{"url": "...", "note": "材料全文来源"}],
  "materials": [{"no": 1, "paragraph": 1, "text": "逐字原文"}],
  "questions": [{"no": 1, "qtype": "summary", "stem": "题干原文（含分值与字数要求）",
                 "full_score": 20, "word_min": 0, "word_max": 300, "material_refs": [1, 2]}]
}
```

- `status`：`complete` 材料与题目都齐；`questions_only` 只有题目、没有材料全文。
- `qtype`：summary 归纳概括 / analysis 综合分析 / countermeasure 提出对策 / official 应用文（贯彻执行）/ essay 大作文。
- `exam_date`：考试日期。浙江省考通常在前一年 12 月考，「2025 年度」考试在 2024 年 12 月。
- 不收录机构参考答案。评分点由模型按材料生成，标注「AI 生成，待教研确认」。
