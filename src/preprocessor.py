"""
预处理器 —— 通用表格匹配 + 内容提取。
不再硬编码表格索引和主题关键词，一切从 rubric.json 驱动。
格式匹配失败时用 LLM 兜底。
"""
import os, re, json
from PIL import Image


def process(paper_data: dict, rubric: dict, config: dict) -> dict:
    """
    输入 extractor 的原始输出 + rubric + config，输出清洗后的结构化数据。

    返回:
    {
        "student": {"学号": "", "姓名": "", "班级": ""},
        "q1": {"prompt_text":..., "result_text":..., ...},
        "q2": {...}, ...
        "all_images": [...],
    }
    """
    max_width = config.get("image", {}).get("max_width", 768)
    quality = config.get("image", {}).get("quality", 75)
    skip_below = config.get("image", {}).get("skip_below_kb", 50)

    # 缩图
    images = []
    for img_path, w, h, size in paper_data.get("images", []):
        if size < skip_below * 1024:
            continue
        resized_path = _resize_image(img_path, max_width, quality)
        if resized_path:
            images.append((resized_path, w, h))

    # 嵌入文件
    excel_files = [f for f, ext in paper_data.get("embedded_files", [])
                   if ext in ['.xlsx', '.xls']]
    video_files = [f for f, ext in paper_data.get("embedded_files", [])
                   if ext in ['.mp4', '.avi', '.mov', '.wmv', '.webm', '.mkv']]

    tables = paper_data.get("tables", [])
    paragraphs = paper_data.get("paragraphs", [])

    # ---- 通用表格匹配：为每道题找内容表 ----
    table_map = _match_tables_to_questions(tables, rubric)

    # 如果匹配失败，LLM 兜底
    if not table_map or len(table_map) < len(rubric["questions"]):
        table_map = _llm_fallback_extraction(tables, rubric, config)

    # ---- 提取各题内容 ----
    result = {
        "student": paper_data.get("student_info", {}),
        "paper_dir": paper_data.get("paper_dir", ""),
        "all_images": images,
    }

    for q in rubric["questions"]:
        qid = q["id"]
        content_tables = table_map.get(qid, [])
        q_data = _extract_question(content_tables, q, images,
                                    excel_files, video_files, paragraphs)
        result[f"q{qid}"] = q_data

    return result


# ============================================================
#  表格匹配
# ============================================================

def _match_tables_to_questions(tables: list, rubric: dict) -> dict:
    """
    扫描所有表格，为每道题匹配内容表。

    策略：
    1. 找"标题表"：包含题目名称或"第X题"的小表
    2. 标题表之后的第一个大表（>2行）视为内容表
    3. 如果找不到标题表，用所有非得分表作为兜底

    返回: {question_id: [content_table_rows, ...]}
    """
    mapping = {}
    questions = rubric["questions"]

    # 先标记跳过表（得分汇总表：含"题号/得分/总分/阅卷"等）
    skip_indices = set()
    for ti, table in enumerate(tables):
        first_row = " ".join(str(c) for c in (table[0] if table else []))
        if any(kw in first_row for kw in ["题号", "得分", "总分", "阅卷人", "阅卷"]):
            if len(table) <= 3:
                skip_indices.add(ti)

    # 为每道题找标题表 + 内容表
    for q in questions:
        qid = q["id"]
        qname = q.get("name", "")
        title_idx = None

        for ti, table in enumerate(tables):
            if ti in skip_indices:
                continue
            first_row = " ".join(str(c) for c in (table[0] if table else []))
            # 匹配条件：包含题目名 OR 包含"第X题"模式
            if _matches_question(first_row, qid, qname) and len(table) <= 2:
                title_idx = ti
                break

        # 取标题表之后的内容表
        if title_idx is not None:
            content_tables = []
            for ti in range(title_idx + 1, len(tables)):
                if ti in skip_indices:
                    break  # 遇到下一个标题表/得分表就停
                if len(tables[ti]) > 2:
                    content_tables.append(tables[ti])
                elif len(tables[ti]) <= 2:
                    # 可能是下一题的标题表
                    first_row = " ".join(str(c) for c in (tables[ti][0] if tables[ti] else []))
                    if any(_matches_question(first_row, oq["id"], oq.get("name", ""))
                           for oq in questions if oq["id"] != qid):
                        break
            if content_tables:
                mapping[qid] = content_tables

    return mapping


def _matches_question(text: str, qid: int, qname: str) -> bool:
    """检查文本是否匹配某道题（支持模糊匹配）"""
    if not text.strip():
        return False

    # 1. 精确子串匹配
    if qname and qname in text:
        return True

    # 2. 部分匹配：题目名的字 50% 以上出现在 text 中
    if qname and len(qname) >= 2:
        hits = sum(1 for ch in qname if ch in text)
        if hits / len(qname) >= 0.5:
            return True

    # 3. 中文数字序号匹配
    cn_nums = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    if qid < len(cn_nums):
        patterns = [
            f"第{qid}题", f"题{cn_nums[qid]}",
            f"{cn_nums[qid]}、", f"({cn_nums[qid]})",
            f"（{cn_nums[qid]}）",
        ]
        if any(p in text for p in patterns):
            return True

    return False


# ============================================================
#  LLM 兜底提取
# ============================================================

def _llm_fallback_extraction(tables: list, rubric: dict, config: dict) -> dict:
    """
    当规则匹配失败时，把所有表格文本发给 LLM，让它标注每道题的内容。
    只在首次调用时执行（结果缓存到 paper 级别）。
    """
    from . import llm as llm_mod

    # 构建表格文本摘要
    table_texts = []
    for ti, table in enumerate(tables):
        rows_text = []
        for row in table:
            cells = [str(c).strip() for c in row if str(c).strip()]
            if cells:
                rows_text.append(" | ".join(cells))
        table_texts.append(f"[表格{ti}] ({len(table)}行):\n" + "\n".join(rows_text[:20]))

    # 构建题目列表
    q_list = []
    for q in rubric["questions"]:
        labels = [sl.get("label", "") for sl in q.get("submission_labels", [])]
        q_list.append(f"Q{q['id']} {q['name']}({q['max_score']}分): 需要提取 {', '.join(labels) if labels else '所有文本'}")

    prompt = f"""你是试卷内容提取工具。从以下 Word 文档表格中提取每道题的学生提交内容。

题目列表：
{chr(10).join(q_list)}

试卷表格内容：
{chr(10).join(table_texts[:10])}

请输出严格 JSON（不要 markdown）：
{{
  "questions": [
    {{
      "id": 1,
      "prompt_text": "学生的提示词文本（如有）",
      "result_text": "学生的生成结果文本（如有）",
      "has_screenshot": true/false,
      "has_video": true/false,
      "has_link": true/false
    }},
    ...
  ]
}}

规则：
- 空内容用 "" 表示
- 只提取学生实际填写的内容，不要提取题目说明
- 如果内容在图片/截图中不可读，has_screenshot=true, 文本可为空"""

    try:
        result = llm_mod.grade_with_text(prompt, 0)
        raw = result.get("raw_response", "")
        data = _parse_json(raw)

        # 将 LLM 结果转为 table_map 格式
        mapping = {}
        for q_item in data.get("questions", []):
            qid = q_item.get("id", 0)
            if qid:
                # 构造伪表格供 _extract_question 使用
                fake_table = []
                for key in ["prompt_text", "result_text", "image_prompt", "video_prompt", "persona_text"]:
                    val = q_item.get(key, "")
                    if val:
                        fake_table.append([f"{key}: {val}"])
                if fake_table:
                    mapping[qid] = [fake_table]
                # 把 LLM 提取的元数据暂存
        return mapping
    except Exception:
        return {}


def _parse_json(text: str) -> dict:
    """从文本中提取 JSON"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


# ============================================================
#  内容提取
# ============================================================

def _extract_question(content_tables: list, question: dict,
                      images: list, excel_files: list,
                      video_files: list, paragraphs: list) -> dict:
    """
    从内容表中提取该题的所有字段。
    使用 question.submission_labels 指导提取。
    """
    qid = question["id"]
    qname = question.get("name", "")
    gtype = question.get("grading_type", "text")
    labels = question.get("submission_labels", [])

    # 合并内容表的所有行
    all_rows = []
    for table in content_tables:
        all_rows.extend(table)

    # 用 labels 映射提取
    result = {
        "prompt_text": "",
        "result_text": "",
        "image_prompt": "",
        "video_prompt": "",
        "persona_text": "",
        "has_screenshot": False,
        "has_video": False,
        "video_path": "",
        "has_excel_file": False,
        "excel_path": "",
        "bot_link": "",
        "result_is_screenshot": False,
        "all_table_text": _extract_all_text(content_tables),
    }

    # 根据 submission_labels 提取
    for sl in labels:
        label = sl.get("label", "")
        field = sl.get("field", "")
        sl_type = sl.get("type", "text")

        if sl_type == "text_or_image":
            # 先尝试提取文本，检查是否只是截图
            text = _extract_content_after_label(all_rows, [label])
            if text:
                result[field] = text
            # 检查是否有截图标记
            if "截图" in label or _has_label(all_rows, ["截图", "生成结果"]):
                result["result_is_screenshot"] = True
        elif field == "prompt" or field == "prompt_text":
            result["prompt_text"] = _extract_text_by_label(all_rows, [label])
        elif field == "result" or field == "result_text":
            result["result_text"] = _extract_text_by_label(all_rows, [label])
        elif field == "image_prompt":
            result["image_prompt"] = _extract_text_by_label(all_rows, [label])
        elif field == "video_prompt":
            result["video_prompt"] = _extract_text_by_label(all_rows, [label])
        elif field == "persona_text":
            result["persona_text"] = _extract_content_after_label(all_rows, [label])

    # 如果没有 label 配置，用启发式规则
    if not labels:
        result["prompt_text"] = _extract_text_by_label(all_rows, ["提示词", "prompt"])
        result["result_text"] = _extract_text_by_label(all_rows, ["生成结果", "结果", "文案"])
        result["all_table_text"] = _extract_all_text(content_tables)

    # ---- 通用资源提取 ----
    # 截图检测
    result["has_screenshot"] = len(images) >= 2 or _has_label(all_rows, ["截图", "screen"])

    # 视频检测 —— 取最大的文件
    if video_files:
        result["has_video"] = True
        best = max(video_files, key=lambda p: os.path.getsize(p) if os.path.exists(p) else 0)
        result["video_path"] = best
    # 从段落文字兜底
    for i, text in paragraphs:
        if any(ext in text.lower() for ext in ['.mp4', '.avi', '.mov']):
            result["has_video"] = True
            break

    # Excel 检测 —— 取最大的文件（处理后的通常更大）
    if excel_files:
        result["has_excel_file"] = True
        best = max(excel_files, key=lambda p: os.path.getsize(p) if os.path.exists(p) else 0)
        result["excel_path"] = best

    # 链接检测
    for i, text in paragraphs:
        if "http" in text:
            urls = re.findall(r'https?://[^\s]+', text)
            if urls:
                result["bot_link"] = urls[0]
                break
    # 也从表格中找
    if not result["bot_link"]:
        for row in all_rows:
            for c in row:
                s = str(c)
                if "http" in s:
                    urls = re.findall(r'https?://[^\s]+', s)
                    if urls:
                        result["bot_link"] = urls[0]
                        break

    # ---- 图片分配（给 vision 类题目） ----
    if gtype == "vision":
        # 方形大图作为生成图
        square_imgs = [(p, w, h) for p, w, h in images if (w == h and w >= 500) or (0.7 < w/h < 1.3 and w >= 1000)]
        gen_imgs = [p for p, w, h in square_imgs[:3]]
        if gen_imgs:
            result["generated_images"] = gen_imgs
        ref_imgs = [p for p, w, h in square_imgs[3:4]]
        if ref_imgs:
            result["reference_image"] = ref_imgs[0]

    return result


# ============================================================
#  通用文本提取工具
# ============================================================

def _extract_text_by_label(rows: list, labels: list) -> str:
    """根据标签关键词从行中提取最长文本"""
    for row in rows:
        row_str = " ".join(str(c) for c in row)
        for kw in labels:
            if kw in row_str:
                texts = [str(c) for c in row if len(str(c)) > 20]
                if texts:
                    return max(texts, key=len)
    # 没找到标签，返回最长文本
    return _longest_text(rows)


def _extract_content_after_label(rows: list, keywords: list) -> str:
    """找标签行后面的实际内容行"""
    for i, row in enumerate(rows):
        row_str = " ".join(str(c) for c in row)
        for kw in keywords:
            if kw in row_str and len(row_str) < 120:
                # 标签行找到，取后续行的内容
                for j in range(i + 1, min(i + 3, len(rows))):
                    for c in rows[j]:
                        s = str(c).strip()
                        if s and len(s) > 5:
                            # 排除也是标签的行
                            if not any(kw2 in s for kw2 in ["截图", "链接", "提交", "文件"]):
                                return s
                return ""
    return ""


def _has_label(rows: list, keywords: list) -> bool:
    """检查表格中是否存在某个标签"""
    for row in rows:
        row_str = " ".join(str(c) for c in row)
        if any(kw in row_str for kw in keywords):
            return True
    return False


def _extract_all_text(tables: list) -> str:
    """提取表格所有文本"""
    texts = []
    for table in tables:
        for row in table:
            for c in row:
                s = str(c).strip()
                if s and len(s) > 3:
                    texts.append(s)
    return "\n".join(texts)


def _longest_text(rows: list) -> str:
    """返回表格中最长的文本"""
    all_text = []
    for row in rows:
        for c in row:
            s = str(c).strip()
            if len(s) > 20:
                all_text.append(s)
    return max(all_text, key=len) if all_text else ""


# ============================================================
#  图片处理
# ============================================================

def _resize_image(img_path: str, max_width: int, quality: int) -> str | None:
    """缩小图片，返回新路径"""
    try:
        img = Image.open(img_path)
        w, h = img.size
        if w <= max_width:
            return img_path
        new_h = int(h * max_width / w)
        img = img.resize((max_width, new_h), Image.LANCZOS)
        new_path = img_path.rsplit(".", 1)[0] + "_resized.jpg"
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(new_path, "JPEG", quality=quality)
        return new_path
    except Exception:
        return None
