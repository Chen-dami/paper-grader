"""
从评分标准 .docx 自动生成 data/rubric.json。
用法: python tools/import_rubric.py "评分标准.docx"
"""
import sys, os, re, json, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.extractor import extract
from src import llm
import yaml


def parse_rubric_docx(docx_path: str, output_path: str = "data/rubric.json"):
    config = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    config.setdefault("llm", {})["temperature"] = 0.05
    llm.init_llm(config.get("llm", {}))

    paper = extract(docx_path, "output/_rubric_temp")

    all_tables = ""
    for ti, table in enumerate(paper["tables"]):
        rows_text = []
        for row in table:
            cells = [str(c).strip() for c in row if str(c).strip()]
            if cells:
                rows_text.append(" | ".join(cells))
        if rows_text:
            all_tables += f"\n--- 表格{ti} ---\n" + "\n".join(rows_text)

    paragraphs = "\n".join(text for _, text in paper["paragraphs"] if text.strip())

    prompt = f"""你是评分标准结构化提取工具。从课程考核文档提取完整评分标准，输出 JSON。

===== 文档段落 =====
{paragraphs[:6000]}

===== 文档表格 =====
{all_tables[:10000]}

===== 输出 JSON 格式 =====
{{
  "exam": {{
    "name": "课程名",
    "semester": "学期",
    "total_score": 100,
    "time_limit": "时长"
  }},
  "questions": [
    {{
      "id": 1,
      "name": "题目名",
      "max_score": 15,
      "description": "题目描述",
      "grading_type": "text",
      "topic_keywords": ["关键词1", "关键词2"],
      "submission_labels": [
        {{"label": "提示词", "field": "prompt_text"}},
        {{"label": "生成结果", "field": "result_text", "type": "text_or_image"}}
      ],
      "data_checks": null,
      "criteria": [
        {{"id": "1-1", "name": "得分项", "max": 5, "desc": "标准描述"}}
      ]
    }}
  ]
}}

===== 规则 =====
1. grading_type: code/vision/text/hybrid 之一
2. topic_keywords: 3-10个核心主题词，判断切题用。纯技术题给[]
3. submission_labels: 从提交材料提取，field取prompt_text/result_text/image_prompt/video_prompt/persona_text
4. data_checks: 仅code题填写，含dedup/fillna/date_format/sort
5. criteria: 各项max之和等于该题max_score
6. id格式: "题号-序号"

直接输出 JSON。"""

    rubric = None
    for attempt in range(2):
        result = llm.grade_with_text(prompt, 0)
        raw = result.get("raw_response", "")
        rubric = _parse_json(raw)
        if rubric and "questions" in rubric and len(rubric.get("questions", [])) > 0:
            break
        if attempt == 0:
            print("[RETRY] 解析失败，重试...")
    else:
        print("[ERR] 无法解析 LLM 返回")
        print(f"返回: {raw[:500]}")
        sys.exit(1)

    if "questions" not in rubric:
        rubric["questions"] = []
    if "exam" not in rubric:
        rubric["exam"] = {"name": "未知课程", "semester": "", "total_score": 100, "time_limit": ""}

    for q in rubric["questions"]:
        q.setdefault("grading_type", "text")
        q.setdefault("topic_keywords", [])
        q.setdefault("submission_labels", [])
        q.setdefault("data_checks", None if q.get("grading_type") != "code" else {})
        for i, c in enumerate(q.get("criteria", [])):
            if "id" not in c or not c["id"]:
                c["id"] = f"{q['id']}-{i+1}"
        _fix_criteria_sum(q)

    total = rubric["exam"].get("total_score", 0)
    if total == 0:
        total = sum(q.get("max_score", 0) for q in rubric["questions"])
        rubric["exam"]["total_score"] = total

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(rubric, f, ensure_ascii=False, indent=2)

    q_count = len(rubric["questions"])
    code_count = sum(1 for q in rubric["questions"] if q.get("grading_type") == "code")
    print(f"[OK] {output_path}")
    print(f"     课程: {rubric['exam']['name']} | {q_count}道题 | 满分{rubric['exam']['total_score']}")
    print(f"     题型: {code_count}道代码 + {q_count - code_count}道LLM")
    for q in rubric["questions"]:
        kws = q.get("topic_keywords", [])
        labels = [sl.get("label", "") for sl in q.get("submission_labels", [])]
        print(f"     Q{q['id']} {q['name']}({q['max_score']}分) [{q.get('grading_type','?')}] "
              f"关键词={kws[:5]} 标签={labels}")

    import shutil
    if os.path.isdir("output/_rubric_temp"):
        shutil.rmtree("output/_rubric_temp", ignore_errors=True)

    return rubric


def _fix_criteria_sum(q: dict):
    criteria = q.get("criteria", [])
    if not criteria: return
    ms = q.get("max_score", 0)
    if ms <= 0: return
    cs = sum(c.get("max", 0) for c in criteria)
    if cs == ms: return
    if cs <= 0: return
    for c in criteria:
        c["max"] = max(1, int(c["max"] * ms / cs))
    diff = ms - sum(c["max"] for c in criteria)
    if diff != 0 and criteria:
        criteria[0]["max"] += diff
    print(f"  [FIX] Q{q.get('id','?')} criteria {cs}→{ms}")


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从评分标准docx生成rubric.json")
    parser.add_argument("docx", help="评分标准.docx")
    parser.add_argument("-o", "--output", default="data/rubric.json", help="输出路径")
    args = parser.parse_args()
    if not os.path.exists(args.docx):
        print(f"文件不存在: {args.docx}")
        sys.exit(1)
    parse_rubric_docx(args.docx, args.output)
