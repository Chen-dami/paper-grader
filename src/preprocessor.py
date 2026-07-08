"""
预处理器 —— 通用表格匹配 + 内容提取。
不再硬编码表格索引和主题关键词，一切从 rubric.json 驱动。
格式匹配失败时用 LLM 兜底。
"""
import os, re, json
from PIL import Image
from .video_validator import quick_check as validate_video


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

    # 缩图 + 保留位置信息
    # 图片元组格式: (local_path, width, height, size_bytes, order_idx, table_idx)
    images = []
    for t in paper_data.get("images", []):
        if len(t) < 4:
            continue
        img_path, w, h, size = t[0], t[1], t[2], t[3]
        order_idx = t[4] if len(t) >= 5 else -1
        table_idx = t[5] if len(t) >= 6 else -1
        if size < skip_below * 1024:
            continue
        resized_path = _resize_image(img_path, max_width, quality)
        if resized_path:
            images.append((resized_path, w, h, order_idx, table_idx))

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

    # ---- 计算每道题在文档中的表格索引（用于图片按题分配） ----
    q_table_indices = _compute_question_positions(tables, table_map)

    # ---- 提取各题内容 ----
    result = {
        "student": paper_data.get("student_info", {}),
        "paper_dir": paper_data.get("paper_dir", ""),
        "all_images": [(p, w, h) for p, w, h, _, _ in images],  # 兼容旧格式
    }

    for q in rubric["questions"]:
        qid = q["id"]
        content_tables = table_map.get(qid, [])
        try:
            q_data = _extract_question(content_tables, q, images,
                                        excel_files, video_files, paragraphs,
                                        q_table_indices.get(qid, set()))
        except Exception:
            q_data = {
                "prompt_text": "", "result_text": "", "image_prompt": "",
                "video_prompt": "", "persona_text": "", "has_screenshot": False,
                "has_video": False, "video_path": "", "has_excel_file": False,
                "excel_path": "", "bot_link": "", "result_is_screenshot": False,
                "all_table_text": "", "generated_images": [], "reference_image": None,
            }
        result[f"q{qid}"] = q_data

    return result


# ============================================================
#  表格匹配
# ============================================================

def _match_tables_to_questions(tables: list, rubric: dict) -> dict:
    """
    两轮匹配：先精确子串，再字符级模糊。每个表头只分配给得分最高的题。
    """
    mapping = {}
    questions = rubric["questions"]

    # 标记跳过表（仅跳过含"题号"或"总分"的得分汇总表，不过滤含"得分"的题目表头）
    skip_indices = set()
    for ti, table in enumerate(tables):
        first_row = " ".join(str(c) for c in (table[0] if table else []))
        if ("题号" in first_row or "总分" in first_row) and len(table) <= 3:
            skip_indices.add(ti)

    def _match_score(text, qid, qname):
        """返回匹配分数：2=精确子串, 1=模糊>=50%, 1=数字序号, 0=不匹配"""
        if qname and len(qname) >= 2 and qname in text:
            return 2
        if qname and len(qname) >= 2:
            hits = sum(1 for ch in qname if ch in text)
            if hits / len(qname) >= 0.5:
                return 1
        cn_nums = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
        if qid < len(cn_nums):
            for p in [f"第{qid}题", f"题{cn_nums[qid]}",
                       f"{cn_nums[qid]}、", f"({cn_nums[qid]})", f"（{cn_nums[qid]}）"]:
                if p in text:
                    return 1
        return 0

    # 收集所有候选表头及其匹配
    candidates = []  # [(ti, qid, score)]
    for ti, table in enumerate(tables):
        if ti in skip_indices or len(table) > 2:
            continue
        first_row = " ".join(str(c) for c in (table[0] if table else []))
        best_q, best_score = None, 0
        for q in questions:
            s = _match_score(first_row, q["id"], q.get("name", ""))
            if s > best_score:
                best_q, best_score = q["id"], s
        if best_q and best_score > 0:
            candidates.append((ti, best_q, best_score))

    # 每个题取最高分的表头（如有同分取第一个）
    used_titles = set()
    for q in questions:
        qid = q["id"]
        best_ti, best_score = None, 0
        for ti, cqid, score in candidates:
            if ti in used_titles: continue
            if cqid == qid and score > best_score:
                best_ti, best_score = ti, score
        if best_ti is not None:
            used_titles.add(best_ti)
            # 取标题表之后的内容表
            content_tables = []
            for ti2 in range(best_ti + 1, len(tables)):
                if ti2 in skip_indices: break
                if ti2 in used_titles: break
                first_row = " ".join(str(c) for c in (tables[ti2][0] if tables[ti2] else []))
                # 检查是否是另一道题的表头
                other_match = False
                for q2 in questions:
                    if q2["id"] != qid and _match_score(first_row, q2["id"], q2.get("name", "")) > 0:
                        other_match = True
                        break
                if other_match and len(tables[ti2]) <= 2:
                    break
                if len(tables[ti2]) > 2:
                    content_tables.append(tables[ti2])
            if content_tables:
                mapping[qid] = content_tables

    # 兜底：未匹配的题按文档顺序分配剩余表头
    unmatched_qs = [q for q in questions if q["id"] not in mapping]
    unused_headers = [
        (ti, table) for ti, table in enumerate(tables)
        if ti not in skip_indices and len(table) <= 2 and ti not in used_titles
    ]
    unused_headers.sort(key=lambda x: x[0])
    for i, q in enumerate(unmatched_qs):
        if i < len(unused_headers):
            ti, _ = unused_headers[i]
            used_titles.add(ti)
            content_tables = []
            for ti2 in range(ti + 1, len(tables)):
                if ti2 in skip_indices: break
                if ti2 in used_titles: break
                if len(tables[ti2]) > 2:
                    content_tables.append(tables[ti2])
                elif len(tables[ti2]) <= 2:
                    break
            if content_tables:
                mapping[q["id"]] = content_tables

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
                      video_files: list, paragraphs: list,
                      question_table_indices: set = None) -> dict:
    """
    从内容表中提取该题的所有字段。
    使用 question.submission_labels 指导提取。

    images: [(path, w, h, order_idx, table_idx), ...]
    question_table_indices: 属于本题的 tables 索引集合
    """
    qid = question["id"]
    qname = question.get("name", "")
    gtype = question.get("grading_type", "text")
    labels = question.get("submission_labels", [])
    if question_table_indices is None:
        question_table_indices = set()

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
        "video_info": "",
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
    # 按题分配图片（解决多vision题共享图片Bug #1）
    # images 格式: [(path, w, h, order_idx, table_idx), ...]
    question_images = []      # 属于本题的图片
    other_question_images = []  # 属于其他题的图片
    unassigned_images = []     # 无法确定归属的图片（table_idx == -1）

    for img in images:
        if len(img) < 5:
            # 旧版兼容
            path, w, h = img[0], img[1], img[2]
            question_images.append((path, w, h))
            continue
        path, w, h, order_idx, table_idx = img[0], img[1], img[2], img[3], img[4]
        if table_idx >= 0 and question_table_indices:
            if table_idx in question_table_indices:
                question_images.append((path, w, h))
            else:
                other_question_images.append((path, w, h))
        else:
            # table_idx == -1: 无法确定归属（图片在段落中但没表格上下文）
            # 或 question_table_indices 为空：表格匹配失败，回退到全部分配
            unassigned_images.append((path, w, h))

    # 如果无法按表格分配（表格匹配失败、或旧版图片格式），回退：全给本题
    if not question_images and not other_question_images and unassigned_images:
        question_images = unassigned_images
    elif unassigned_images:
        # 无法确定的图片也分配给本题（宁可多给不可漏掉）
        question_images.extend(unassigned_images)

    # 截图检测（按本题图片数，解决跨题污染Bug #3）
    # 注意：不能用 _has_label 简单匹配"截图"二字，因为模板标签也含有"截图"
    # 只有在以下情况才认为有截图：
    # 1. 实际检测到 >= 1 张属于本题的图片
    # 2. 表格行中有"截图"标签，且同行有其他单元格有学生填写的内容(>20字)
    has_screenshot_from_images = len(question_images) >= 1
    has_screenshot_from_labels = _has_screenshot_evidence(all_rows)
    result["has_screenshot"] = has_screenshot_from_images or has_screenshot_from_labels

    # 视频检测 —— 仅 vision 类型且名称含"视频"的题目分配
    _needs_video = (gtype == "vision" and ("视频" in qname or "video" in qname.lower()))
    if video_files and _needs_video:
        vpath = video_files[0]
        is_valid, vinfo = validate_video(vpath)
        result["has_video"] = is_valid
        result["video_path"] = vpath if is_valid else ""
        result["video_info"] = vinfo if is_valid else f"无效视频: {vinfo}"
    elif video_files and not _needs_video:
        # 从段落文字兜底（仅当题目明确提及视频）
        para_has_video = False
        for i, text in paragraphs:
            if any(ext in text.lower() for ext in ['.mp4', '.avi', '.mov']):
                para_has_video = True
                break
        if para_has_video and _needs_video:
            result["has_video"] = True

    # Excel 检测 —— 仅 code 类型分配（数据处理题）
    # hybrid 类型若 submission_labels 中有明确的文件上传才分配
    _needs_excel = (
        gtype == "code" or
        (gtype == "hybrid" and any(
            "excel" in sl.get("label", "").lower() or
            sl.get("type", "") == "file"
            for sl in labels
        ))
    )
    if excel_files and _needs_excel:
        # 智能选择学生作业Excel（而非题目模板或无关文件）
        import pandas as pd
        scored = []  # [(path, score), ...]
        for xf in excel_files:
            fname = os.path.basename(xf).lower()
            score = 0
            # 加分项：文件名暗示是学生处理结果
            if any(kw in fname for kw in ['处理', '完成', '答案', '作业']):
                score += 10
            # 扣分项：文件名暗示是题目模板
            if any(kw in fname for kw in ['题目', '试题', '原始', '汇总表']):
                score -= 20
            if '校园' in fname or '失物' in fname:
                score -= 30  # 这是Q5的知识库文件，不是Q4作业
            # 加分项：Excel 内有 Q4 相关字段
            try:
                df = pd.read_excel(xf, nrows=0)  # 只读表头
                cols = [str(c).lower() for c in df.columns]
                if any(kw in ' '.join(cols) for kw in ['销售金额', '销售日期', '商品']):
                    score += 30  # 强烈匹配Q4
                if any(kw in fname for kw in ['数据', '销售']) or any(kw in ' '.join(cols) for kw in ['数据', '销售']):
                    score += 5
            except Exception:
                pass
            # 加分项：文件较大（学生的处理结果通常比题目模板大）
            try:
                size_kb = os.path.getsize(xf) / 1024
                if size_kb > 50:
                    score += 5
            except Exception:
                pass
            scored.append((xf, score))

        # 选最高分，但至少要有基本文件匹配才认
        scored.sort(key=lambda x: x[1], reverse=True)
        best_path, best_score = scored[0]
        if best_score >= 0:  # 有基本可信度
            result["has_excel_file"] = True
            result["excel_path"] = best_path
        else:
            # 全是无关文件（如只有Q5的汇总表和题目模板）
            result["has_excel_file"] = False
            result["excel_path"] = ""

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

    # 链接可达性检测（异步检查链接是否真实可访问）
    if result["bot_link"] and "http" in str(result["bot_link"]):
        result["link_reachable"] = _check_url_reachable(result["bot_link"])
    else:
        result["link_reachable"] = None

    # ---- 图片分配（给 vision 类题目） ----
    if gtype == "vision":
        valid_imgs = [(p, w, h) for p, w, h in question_images
                       if w > 200 and h > 200]

        # 智能排序：优先选生成图（接近正方形），截图/全屏图排后面
        # 截图特征：宽高比 > 1.5 或 < 0.67（16:9, 16:10, 4:3 等）
        # 生成图特征：接近正方形（0.8 ~ 1.25）
        def _img_priority(item):
            _p, w, h = item
            area = w * h
            # 宽高比越接近1越好
            ratio = w / max(h, 1)
            if ratio < 1:
                ratio = 1 / ratio
            # 接近正方形 -> ratio_near_1 接近 0（好）
            ratio_near_1 = abs(ratio - 1.0)
            # 截图惩罚：宽高比偏离大 -> 分数降低
            screenshot_penalty = 3.0 if ratio_near_1 > 0.3 else 0.0
            # 最终分数：面积大 + 接近正方形 = 高分
            return area - (screenshot_penalty * area * 0.5)

        valid_imgs.sort(key=_img_priority, reverse=True)
        all_paths = [p for p, w, h in valid_imgs]

        # 前3张作为生成图候选，第4张作为参考图
        result["generated_images"] = all_paths[:3]
        if len(all_paths) > 3:
            result["reference_image"] = all_paths[3]

    return result


# ============================================================
#  通用文本提取工具
# ============================================================

def _extract_text_by_label(rows: list, labels: list) -> str:
    """根据标签关键词从行中提取最长文本"""
    _LABEL_KW = ["截图", "链接", "提交", "文件", "图片", "视频"]
    for ri, row in enumerate(rows):
        row_str = " ".join(str(c) for c in row)
        for kw in labels:
            if kw in row_str:
                # 先在当前行找长文本
                texts = [str(c) for c in row if len(str(c)) > 20]
                if texts:
                    return max(texts, key=len)
                # 当前行没有，检查后续行（跨行内容）
                for next_row in rows[ri + 1:ri + 4]:
                    next_texts = [str(c) for c in next_row if len(str(c)) > 5]
                    # 只跳过明显是标签的短行（≤25字且含标签关键词），不跳过内容行
                    non_label = [t for t in next_texts
                                 if len(t) > 25 or not any(kw2 in t for kw2 in _LABEL_KW)]
                    if non_label:
                        return max(non_label, key=len)
                return ""  # 标签找到但无内容 → 返回空
    # 没找到任何标签 → 兜底返回最长文本
    return _longest_text(rows)


def _extract_content_after_label(rows: list, keywords: list) -> str:
    """找标签行后面的实际内容行"""
    # 长文本不检查关键词过滤（如 persona_text 可能含"提交"等词）
    _SKIP_KW = ["截图", "链接", "文件", "图片", "视频"]  # 去掉"提交"：persona_text经常含此词
    for i, row in enumerate(rows):
        row_str = " ".join(str(c) for c in row)
        for kw in keywords:
            if kw not in row_str:
                continue
            # 策略1：优先取后续行的内容（跨行布局）
            for j in range(i + 1, min(i + 3, len(rows))):
                for c in rows[j]:
                    s = str(c).strip()
                    if s and len(s) > 5:
                        # 长文本(>50字)不检查关键词，短文本才检查
                        if len(s) > 50 or not any(kw2 in s for kw2 in _SKIP_KW):
                            return s
            # 策略2：后续行无内容，从同单元格提取（标签+内容在同一格）
            if len(row_str) > len(kw) + 10:
                idx = row_str.find(kw)
                if idx >= 0:
                    after = row_str[idx + len(kw):].strip()
                    after = after.lstrip("：:：、。， ")
                    if len(after) > 3:
                        return after
            return ""
    return ""


def _has_label(rows: list, keywords: list) -> bool:
    """检查表格中是否存在某个标签"""
    for row in rows:
        row_str = " ".join(str(c) for c in row)
        if any(kw in row_str for kw in keywords):
            return True
    return False


def _has_screenshot_evidence(rows: list) -> bool:
    """
    检查是否有截图的实际证据（不仅是模板标签）。
    需要：行中有"截图"关键词，且同一行的其他单元格有学生填写的实质内容。
    只检查同行内 — 模板标签如"知识库预览页截图："后面空白的不算。
    注意：标签本身通常<20字，所以只看同行其他单元格是否有长内容。
    """
    for row in rows:
        row_str = " ".join(str(c) for c in row)
        if not any(kw in row_str for kw in ["截图", "屏幕截图"]):
            continue
        # 同行中除了标签单元格之外，还有其他单元格有实质内容(>20字)
        for c in row:
            s = str(c).strip()
            if len(s) > 20 and not any(kw in s for kw in ["截图", "屏幕截图"]):
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


def _compute_question_positions(tables: list, table_map: dict) -> dict:
    """
    计算每道题在文档中的表格索引范围（用于图片按题分配）。
    返回: {qid: set_of_table_indices}

    每个图片带有一个 table_idx（所属表格在 doc.tables 中的索引），
    通过判断 table_idx 是否在本题的索引集合中来分配图片。

    范围不仅包括内容表，还包括前后各一个表格（覆盖表头表等）。
    """
    positions = {}
    table_id_to_idx = {id(t): i for i, t in enumerate(tables)}

    for qid, ctables in table_map.items():
        if not ctables:
            positions[qid] = set()
            continue
        idx_set = set()
        for ct in ctables:
            idx = table_id_to_idx.get(id(ct))
            if idx is not None:
                idx_set.add(idx)
        if idx_set:
            # 扩展范围：前后各加1个表格（覆盖表头表、图注等）
            expanded = set()
            for idx in idx_set:
                expanded.add(idx)
                if idx > 0:
                    expanded.add(idx - 1)
                if idx < len(tables) - 1:
                    expanded.add(idx + 1)
            positions[qid] = expanded
        else:
            positions[qid] = set()

    return positions


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


# ============================================================
#  链接可达性检测
# ============================================================
def _check_url_reachable(url: str, timeout: int = 5) -> bool | None:
    """检测链接是否真实可访问。返回 True/False/None(无法判断)"""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(url, method='HEAD')
        req.add_header('User-Agent', 'Mozilla/5.0')
        resp = urllib.request.urlopen(req, timeout=timeout)
        return 200 <= resp.status < 400
    except urllib.error.HTTPError as e:
        # 有些平台 HEAD 不支持但对 GET 返回 200
        return 200 <= e.code < 400 or e.code == 403  # 403 = 存在但没权限
    except Exception:
        return None  # 网络不可达时不扣分，仅标记为未知
