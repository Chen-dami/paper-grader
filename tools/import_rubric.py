"""
从评分标准 .docx 自动生成 data/rubric.json（增强版）。
LLM 一次性提取：题目结构 + grading_type + topic_keywords + submission_labels + data_checks。

用法: python tools/import_rubric.py "评分标准.docx"
      python tools/import_rubric.py "评分标准.docx" -o custom_rubric.json
"""
import sys, os, re, json, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.extractor import extract
from src import llm
import yaml


def parse_rubric_docx(docx_path: str, output_path: str = "data/rubric.json"):
    """读评分标准 docx，调 LLM 结构化，输出增强版 rubric.json"""
    config = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    llm.init_llm(config.get("llm", {}))

    # 提取文档内容
    paper = extract(docx_path, "output/_rubric_temp")

    # 取所有表格
    all_tables = ""
    for ti, table in enumerate(paper["tables"]):
        rows_text = []
        for row in table:
            cells = [str(c).strip() for c in row if str(c).strip()]
            if cells:
                rows_text.append(" | ".join(cells))
        if rows_text:
            all_tables += f"\n--- 表格{ti} ---\n" + "\n".join(rows_text)

    # 取段落
    paragraphs = "\n".join(text for _, text in paper["paragraphs"] if text.strip())

    prompt = f"""你是评分标准结构化提取工具。从以下课程考核文档中提取完整的评分标准，输出严格 JSON。

===== 文档段落 =====
{paragraphs[:3000]}

===== 文档表格 =====
{all_tables[:5000]}

===== 输出格式（直接JSON，不要markdown代码块）=====
{{
  "exam": {{
    "name": "课程名",
    "semester": "学期（如2025-2026学年第二学期）",
    "total_score": 100,
    "time_limit": "考试时长（如90分钟）"
  }},
  "questions": [
    {{
      "id": 1,
      "name": "题目名称（如：文本生成）",
      "max_score": 15,
      "description": "题目要求和主题的一句话描述",
      "grading_type": "text",
      "topic_keywords": ["主题核心词1", "主题核心词2"],
      "submission_labels": [
        {{"label": "提示词", "field": "prompt_text"}},
        {{"label": "生成结果", "field": "result_text", "type": "text_or_image"}}
      ],
      "data_checks": null,
      "criteria": [
        {{"id": "1-1", "name": "得分项名称", "max": 5, "desc": "得分标准描述"}}
      ]
    }}
  ]
}}

===== 字段填写规则 =====

1. grading_type（必填，从以下4种中选择）：
   - "code": 纯数据处理题（涉及Excel/数据清洗/去重/补空/格式统一），可用pandas自动检测
   - "vision": 涉及图片/海报/视频/设计，需要评估视觉质量
   - "text": 纯文字生成题，评估提示词和文案
   - "hybrid": 智能体/机器人搭建，需要评估截图+链接+逻辑

2. topic_keywords（必填，3-10个）：
   - 从题目描述中提取核心主题关键词，用于判断学生是否"切题"
   - 例如茶艺题→["茶艺","茶文化","茶道","茶叶","泡茶","茶器","茶饮","茶","茗"]
   - 航天题→["文昌","航天","火箭","发射","卫星","空间站","太空","宇宙"]
   - 如果没有明确主题词（如纯技术题），给空数组[]

3. submission_labels（必填）：
   - 从"提交材料/提交要求"中提取每项对应的标签
   - label: 学生表格中的标签文字
   - field: 对应字段名（prompt_text/result_text/image_prompt/video_prompt/persona_text）
   - type（可选）: "text"=纯文本, "text_or_image"=文本或截图, "image"=图片, "video"=视频

4. data_checks（仅 grading_type="code" 时填写，否则 null）：
   - 包含去重/补空/日期格式/排序等检查项
   - 格式示例：
     {{"dedup": true, "fillna": {{"column_pattern": "金额|价"}}, "date_format": {{"column_pattern": "日期|时间", "format": "YYYY-MM-DD"}}, "sort": {{"column_pattern": "日期"}}}}
   - 如果题目没有明确的数据检查要求，给 {{}}

5. criteria（必填）：
   - 每个 criterion 的 max 之和应等于该题的 max_score
   - id 格式："题号-序号" 如 "1-1", "1-2"

直接输出 JSON，不要任何解释文字。"""

    result = llm.grade_with_text(prompt, 0)
    raw = result.get("raw_response", "")

    # 解析 JSON
    rubric = _parse_json(raw)
    if not rubric:
        print("[ERR] LLM 返回无法解析，请检查评分标准 docx 格式")
        print(f"原始返回: {raw[:500]}")
        sys.exit(1)

    # 校验必要字段
    if "questions" not in rubric:
        rubric["questions"] = []
    if "exam" not in rubric:
        rubric["exam"] = {"name": "未知课程", "semester": "", "total_score": 100, "time_limit": ""}

    # 为每道题补全缺失字段
    for q in rubric["questions"]:
        q.setdefault("grading_type", "text")
        q.setdefault("topic_keywords", [])
        q.setdefault("submission_labels", [])
        q.setdefault("data_checks", None if q.get("grading_type") != "code" else {})
        # 确保 criteria id 格式正确
        for i, c in enumerate(q.get("criteria", [])):
            if "id" not in c or not c["id"]:
                c["id"] = f"{q['id']}-{i+1}"

    # 计算总分
    total = rubric["exam"].get("total_score", 0)
    if total == 0:
        total = sum(q.get("max_score", 0) for q in rubric["questions"])
        rubric["exam"]["total_score"] = total

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(rubric, f, ensure_ascii=False, indent=2)

    # 统计输出
    q_count = len(rubric["questions"])
    code_count = sum(1 for q in rubric["questions"] if q.get("grading_type") == "code")
    llm_count = q_count - code_count
    print(f"[OK] 已生成 {output_path}")
    print(f"     课程: {rubric['exam']['name']} | {q_count}道题 | 满分{rubric['exam']['total_score']}")
    print(f"     题型: {code_count}道纯代码(0 token) + {llm_count}道LLM评分")
    for q in rubric["questions"]:
        kws = q.get("topic_keywords", [])
        labels = [sl.get("label", "") for sl in q.get("submission_labels", [])]
        print(f"     Q{q['id']} {q['name']}({q['max_score']}分) [{q.get('grading_type','?')}] "
              f"关键词={kws[:5]} 标签={labels}")

    # 清理临时目录
    import shutil
    if os.path.isdir("output/_rubric_temp"):
        shutil.rmtree("output/_rubric_temp", ignore_errors=True)

    return rubric


def _parse_json(text: str) -> dict:
    """从 LLM 回复中提取 JSON"""
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试 ```json ... ``` 代码块
    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # 尝试匹配最外层花括号
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从评分标准docx生成rubric.json")
    parser.add_argument("docx", help="评分标准.docx 文件路径")
    parser.add_argument("-o", "--output", default="data/rubric.json", help="输出路径（默认data/rubric.json）")
    args = parser.parse_args()

    if not os.path.exists(args.docx):
        print(f"文件不存在: {args.docx}")
        sys.exit(1)

    parse_rubric_docx(args.docx, args.output)
