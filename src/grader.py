"""
评分引擎 -- 多题型分发 + LLM驱动评分 + 视频保底
"""
import os, re, json
import pandas as pd
from . import model_router as router
from .video_frame_extractor import extract_frames as _extract_video_frames


# ============================================================
#  视觉策略检测
# ============================================================
def _should_use_vision(gtype: str, config: dict) -> bool:
    """根据视觉策略 + 题目类型决定是否使用视觉模型"""
    rc = router.get_router_config()
    strategy = config.get("vision_strategy") or rc.get("vision_strategy", "paid_vision")

    if strategy == "text_only":
        return False  # 纯文字模式：永远不用视觉
    # free_vision / paid_vision: vision/hybrid 类型用视觉
    return gtype in ("vision", "hybrid")


# ============================================================
#  主入口
# ============================================================
def grade(q_data: dict, question: dict, config: dict,
          force_no_vision: bool = False) -> dict:
    gtype = question.get("grading_type", "text")
    criteria = question["criteria"]
    max_score = question["max_score"]

    try:
        if gtype in ("multiple_choice", "true_false", "fill_blank", "short_answer"):
            return _grade_exact_match(q_data, question)

        if gtype == "code":
            return _grade_code(q_data, question, config)

        # text / vision / hybrid: 空判 → LLM一步评分
        strategy = config.get("vision_strategy", "paid_vision")
        if _is_truly_empty(q_data, gtype, strategy):
            return _zero_score(criteria, max_score, "内容为空")

        use_vision = _should_use_vision(gtype, config) and not force_no_vision
        result = _grade_llm(q_data, question, config, use_vision)

        total = sum(result.get(f"得分_{c['id']}_{c['name']}", 0) for c in criteria)
        result["总分"] = min(total, max_score)
        if force_no_vision:
            result["_teacher_review_vision"] = True
    except Exception as e:
        result = _zero_score(criteria, max_score, f"评分异常: {e}")
    return result


# ============================================================
#  客观题
# ============================================================
def _grade_exact_match(q_data: dict, question: dict) -> dict:
    criteria = question["criteria"]
    max_score = question["max_score"]
    gtype = question.get("grading_type", "multiple_choice")
    answer_key = question.get("answer_key", {})

    student_answer = _extract_answer(q_data, gtype)
    result = {"切题判断": "客观题", "tokens_in": 0, "tokens_out": 0, "raw_response": f"exact_match:{gtype}"}

    if gtype in ("multiple_choice", "true_false"):
        correct = answer_key.get("正确答案", "")
        if isinstance(correct, list):
            matched = isinstance(student_answer, list) and set(s.upper() for s in student_answer) == set(c.upper() for c in correct)
        else:
            matched = str(student_answer).upper().strip() == str(correct).upper().strip()

        if matched:
            score = answer_key.get("分值", max_score)
            for c in criteria:
                result[f"得分_{c['id']}_{c['name']}"] = score if c["id"] == criteria[0]["id"] else 0
            result["评语"] = "答案正确"; result["总分"] = score
        else:
            partial = answer_key.get("部分分", 0)
            for c in criteria:
                result[f"得分_{c['id']}_{c['name']}"] = 0
            result["评语"] = f"答案错误（正确答案：{correct}）"; result["总分"] = partial
        return result

    if gtype == "fill_blank":
        blanks = answer_key.get("答案", {})
        total_score = 0
        for i, c in enumerate(criteria):
            blank_key = str(i + 1)
            correct_answers = blanks.get(blank_key, "")
            if isinstance(correct_answers, str):
                correct_answers = [correct_answers]
            student_ans = student_answer.get(blank_key, "") if isinstance(student_answer, dict) else str(student_answer)
            is_correct = any(_fuzzy_match(str(student_ans), str(ans)) for ans in correct_answers)
            sc = c["max"] if is_correct else 0
            result[f"得分_{c['id']}_{c['name']}"] = sc; total_score += sc
        result["评语"] = f"填空得分 {total_score}/{max_score}"; result["总分"] = total_score
        return result

    if gtype == "short_answer":
        key_points = question.get("key_points", [])
        all_text = _collect_text(q_data, gtype)
        total_score = 0; comments = []
        for kp in key_points:
            kw = kp.get("keyword", ""); pts = kp.get("score", 0)
            if kw and kw in all_text:
                total_score += pts; comments.append(f"+{pts}: {kw}")
            else:
                comments.append(f"0: 缺{kw}")
        result["评语"] = "；".join(comments[:6]); result["总分"] = min(total_score, max_score)
        for i, c in enumerate(criteria):
            result[f"得分_{c['id']}_{c['name']}"] = min(key_points[i].get("score", 0), c["max"]) if i < len(key_points) else 0
        return result

    return _zero_score(criteria, max_score, "不支持的客观题类型")


def _extract_answer(q_data: dict, gtype: str):
    prompt_text = str(q_data.get("prompt_text", ""))
    result_text = str(q_data.get("result_text", ""))
    all_text = (prompt_text + " " + result_text).strip()

    if gtype in ("multiple_choice", "true_false"):
        multi = re.findall(r'[A-Da-d]{2,}', all_text)
        if multi: return list(multi[0].upper())
        single = re.findall(r'\b([A-Da-d])\b', all_text)
        if single: return single[-1].upper()
        return all_text[:10]

    if gtype == "fill_blank":
        lines = [l.strip() for l in all_text.split("\n") if l.strip()]
        if len(lines) <= 1: return all_text
        answers = {}
        for i, line in enumerate(lines):
            answers[str(i + 1)] = line
        return answers

    return all_text


def _fuzzy_match(student_ans: str, correct_ans: str) -> bool:
    def normalize(s):
        return re.sub(r'[\s，,。\.！!？?：:；;、""''「」]', '', s.lower())
    return normalize(student_ans) == normalize(correct_ans)


# ============================================================
#  空判
# ============================================================
def _is_truly_empty(q_data, gtype, strategy="paid_vision"):
    """
    判断题目是否真正为空（学生没有提交任何实质内容）。

    策略差异:
    - text_only: 宽松 —— has_screenshot/has_excel_file 也算媒体证据，
      宁可给分不可漏杀（系统看不到图，不能说学生没交）
    - free_vision/paid_vision: 标准 —— 需要实质文字或可验证媒体才判非空
    """
    if gtype == "code":
        return not (q_data.get("excel_path") or q_data.get("has_excel_file") or q_data.get("has_screenshot"))

    student_text = ""
    for k in ["prompt_text", "result_text", "image_prompt", "video_prompt", "persona_text"]:
        val = q_data.get(k, "")
        if isinstance(val, str):
            student_text += val
        elif isinstance(val, list):
            student_text += " ".join(str(v) for v in val if isinstance(v, str))

    # all_table_text 单独处理：模板标签通常 <20字，学生内容通常 >20字
    all_table = str(q_data.get("all_table_text", ""))
    long_lines = [l for l in all_table.split("\n") if len(l.strip()) > 20]
    if long_lines:
        student_text += "\n".join(long_lines)

    # text_only: has_screenshot/has_excel_file 也算证据（系统看不到图但不能说学生没交）
    # paid/free: 需要可验证的媒体（generated_images/视频/链接）
    if strategy == "text_only":
        has_media = (
            q_data.get("generated_images") or q_data.get("reference_image") or
            q_data.get("has_screenshot") or
            (q_data.get("has_video") and q_data.get("video_path")) or
            bool(q_data.get("bot_link") and "http" in str(q_data.get("bot_link", ""))) or
            q_data.get("has_excel_file")
        )
    else:
        has_media = (
            q_data.get("generated_images") or q_data.get("reference_image") or
            (q_data.get("has_video") and q_data.get("video_path")) or
            bool(q_data.get("bot_link") and "http" in str(q_data.get("bot_link", "")))
        )

    return len(student_text.strip()) < 5 and not has_media


def _zero_score(criteria, max_score, msg):
    result = {"总分": 0, "评语": msg, "tokens_in": 0, "tokens_out": 0, "raw_response": "empty", "切题判断": "空"}
    for c in criteria:
        result[f"得分_{c['id']}_{c['name']}"] = 0
    return result


def _collect_text(q_data, gtype):
    parts = []
    for key in ["prompt_text", "result_text", "image_prompt", "video_prompt", "persona_text", "all_table_text"]:
        val = q_data.get(key, "")
        if isinstance(val, str):
            parts.append(val)
        elif isinstance(val, list):
            parts.append(" ".join(str(v) for v in val if isinstance(v, str)))
    return " ".join(parts)


# ============================================================
#  档位检测（规则引擎用，code类型保留）
# ============================================================
def _detect_tier(q_data: dict, question: dict, config: dict) -> str:
    # 先检查是否真正为空（无实质内容），避免模板标签触发高分段位
    gtype = question.get("grading_type", "text")
    strategy = config.get("vision_strategy", "paid_vision")
    if _is_truly_empty(q_data, gtype, strategy):
        return "空"

    keywords = question.get("topic_keywords", [])
    all_text = _collect_text(q_data, gtype)
    tiers_cfg = list((config.get("grading", {}) or {}).get("tiers", {}).keys())

    tc = question.get("tier", {})
    text_min = tc.get("text_min", 10)
    perfunctory_max = tc.get("perfunctory_max", 50)
    kw_min = tc.get("keyword_min", 1)
    kw_need = tc.get("keyword_need", 2)
    mat_cfg = tc.get("materials", {})
    missing_max = tc.get("material_missing_max", 1)

    has_video = bool(q_data.get("has_video") and q_data.get("video_path"))
    has_images = bool(q_data.get("generated_images") or q_data.get("reference_image") or q_data.get("generated_image"))
    has_screenshot = bool(q_data.get("has_screenshot"))
    has_excel = bool(q_data.get("excel_path") or q_data.get("has_excel_file"))
    has_link = bool(q_data.get("bot_link") and "http" in str(q_data.get("bot_link", "")))
    mat = {"video": has_video, "images": has_images, "screenshot": has_screenshot, "excel": has_excel, "link": has_link}

    if gtype == "code":
        if not has_excel and not has_screenshot: return "空"
    else:
        if len(all_text.strip()) < text_min and not (has_images or has_video or has_screenshot): return "空"

    if len(all_text.strip()) <= perfunctory_max: return "敷衍"

    if keywords and kw_min > 0:
        has_media = has_images or has_video
        if not (gtype == "vision" and has_media):
            matched = [kw for kw in keywords if kw in all_text]
            need = kw_need if len(keywords) >= kw_need else kw_min
            if len(matched) < need: return "跑题"

    if mat_cfg:
        required = [k for k, v in mat_cfg.items() if v]
        missing = [k for k in required if not mat.get(k, True)]
        if len(missing) >= missing_max:
            return "素材不足" if "素材不足" in tiers_cfg else "敷衍"

    for tk in tiers_cfg:
        if tk in ("空", "敷衍", "跑题", "贴合主题", "素材不足"): continue
        if _flag_match(tk, mat_cfg, mat): return tk

    return "贴合主题"


def _get_tier_config_extended(tier: str, config: dict) -> dict:
    tiers_cfg = config.get("grading", {}).get("tiers", {})
    ti = tiers_cfg.get(tier, {"ratio_min": 0.5, "ratio_max": 1.0})
    return {"ratio_min": ti.get("ratio_min", 0.5), "ratio_max": ti.get("ratio_max", 1.0),
            "temperature": 0.3, "max_tokens": 2048, "desc": ti.get("desc", "")}


def _flag_match(tk: str, mat_cfg: dict, mat: dict) -> bool:
    tier_map = {
        "有截图": ("screenshot", True), "无截图": ("screenshot", False),
        "有图像": ("images", True), "无图像": ("images", False),
        "有视频": ("video", True), "无视频": ("video", False),
        "有表格": ("excel", True), "无表格": ("excel", False),
        "有链接": ("link", True), "无链接": ("link", False),
    }
    if tk in tier_map:
        mat_key, expect = tier_map[tk]
        if mat_cfg.get(mat_key):
            return mat.get(mat_key, False) == expect
    return False


# ============================================================
#  Code 评分
# ============================================================
def _grade_code(q_data: dict, question: dict, config: dict) -> dict:
    criteria = question["criteria"]
    data_checks = question.get("data_checks") or {}
    tier = _detect_tier(q_data, question, config)
    tc = _get_tier_config_extended(tier, config)
    base_ratio = tc.get("ratio_min", 0.5)
    excel_path = q_data.get("excel_path", "")
    has_screenshot = q_data.get("has_screenshot", False)
    rule_results = []; scores = {}; reasons = {}

    if excel_path and isinstance(excel_path, str) and os.path.exists(excel_path):
        try:
            df = pd.read_excel(excel_path)
            scores, reasons, rule_results = _run_data_checks_structured(df, criteria, data_checks)
            for c in criteria:
                sc = scores.get(c["id"], 0)
                if sc < c["max"]: sc = max(sc, int(c["max"] * base_ratio) - 1)
                scores[c["id"]] = sc
        except PermissionError as e:
            for c in criteria:
                scores[c["id"]] = max(1, int(c["max"] * base_ratio))
                reasons[c["id"]] = f"文件被占用({str(e)[:40]})"
        except Exception as e:
            for c in criteria:
                scores[c["id"]] = max(1, int(c["max"] * base_ratio) - 1)
                reasons[c["id"]] = f"读取失败({str(e)[:50]})"
    else:
        no_file_ratio = 0.3 if has_screenshot else 0.0
        for c in criteria:
            scores[c["id"]] = int(c["max"] * no_file_ratio)
            reasons[c["id"]] = f"未提交Excel文件（核心交付物缺失），有截图仅给{int(no_file_ratio*100)}%基础分" if has_screenshot else "未提交Excel文件和截图，无法评分"

    prompt_text = q_data.get("prompt_text", "")
    for c in criteria:
        if "提示词" in c.get("name", "") or "材料" in c.get("name", ""):
            if not prompt_text and has_screenshot:
                scores[c["id"]] = max(scores.get(c["id"], 0), int(c["max"] * base_ratio))
                reasons[c["id"]] = "提示词缺失，有截图给基础分"
            elif not prompt_text and not has_screenshot:
                scores[c["id"]] = 0; reasons[c["id"]] = "未提交提示词和截图"

    total = min(sum(scores.get(c["id"], 0) for c in criteria), question["max_score"])
    comments = []
    for r in rule_results:
        icon = {"pass": "", "warn": "", "fail": ""}.get(r.get("status", ""), "")
        comments.append(f"{icon}{r['check']}: {r['detail']}")

    result = {"总分": total, "评语": "；".join(comments[:5]) if comments else "规则引擎评估完成",
              "tokens_in": 0, "tokens_out": 0, "raw_response": f"code_graded:{tier}",
              "切题判断": tier, "_rule_results": rule_results}
    for c in criteria:
        result[f"得分_{c['id']}_{c['name']}"] = scores.get(c["id"], 0)
    return result


def _run_data_checks_structured(df: pd.DataFrame, criteria: list, data_checks: dict) -> tuple:
    scores, reasons, rule_results = {}, {}, []
    for c in criteria:
        name = c.get("name", ""); cid = c["id"]
        if "缺失" in name or "空值" in name: check = "fillna"
        elif "重复" in name or "去重" in name: check = "dedup"
        elif "格式" in name or "日期" in name or "排序" in name: check = "date_sort"
        elif "提交" in name or "完整" in name: check = "materials"
        elif "提示词" in name or "材料" in name: check = "materials"
        else: check = "generic"
        s, r, rr = _check_one_structured(df, c, check, data_checks)
        scores[cid], reasons[cid] = s, r; rule_results.append(rr)
    return scores, reasons, rule_results


def _check_one_structured(df, criterion, check, data_checks) -> tuple:
    ms = criterion["max"]
    if check == "dedup":
        n = df.duplicated().sum()
        if n == 0: return ms, f"去重正确，共{len(df)}行无重复", {"check": "去重检查", "status": "pass", "detail": f"0条重复，共{len(df)}行"}
        if n <= 3: s = max(1, ms - 2); return s, f"残留{n}条重复", {"check": "去重检查", "status": "warn", "detail": f"残留{n}条重复"}
        s = max(0, ms - 3); return s, f"残留{n}条重复", {"check": "去重检查", "status": "fail", "detail": f"残留{n}条重复"}
    elif check == "fillna":
        cfg = data_checks.get("fillna", {})
        pat = cfg.get("column_pattern", "") or cfg.get("column", "")
        col = _find_column(df, pat) if pat else None
        if col:
            nc = df[col].isna().sum()
            if nc == 0: return ms, f"「{col}」无空值", {"check": "空值检查", "status": "pass", "detail": f"「{col}」0空值"}
            if nc <= 3: s = max(1, ms - 2); return s, f"「{col}」残留{nc}空值", {"check": "空值检查", "status": "warn", "detail": f"「{col}」{nc}空值"}
            s = max(0, ms - 3); return s, f"「{col}」残留{nc}空值", {"check": "空值检查", "status": "fail", "detail": f"「{col}」{nc}空值"}
        return max(1, ms - 1), "未找到目标列", {"check": "空值检查", "status": "warn", "detail": "未找到目标列"}
    elif check == "date_sort":
        cfg = data_checks.get("date_format", {})
        pat = cfg.get("column_pattern", "") or cfg.get("column", "") or "日期|时间|date"
        col = _find_column(df, pat)
        if not col: return max(1, ms - 1), "未找到日期列", {"check": "日期格式", "status": "warn", "detail": "未找到日期列"}
        ss = df[col].dropna().astype(str)
        fmt_ok = ss.str.match(r'\d{4}[/-]\d{1,2}[/-]\d{1,2}').sum()
        rate = fmt_ok / len(ss) if len(ss) > 0 else 0
        df_dedup = df.drop_duplicates()
        try:
            sv = pd.to_datetime(df_dedup[col], errors='coerce').dropna()
            sorted_ok = all(sv.iloc[i] <= sv.iloc[i+1] for i in range(len(sv)-1))
        except Exception: sorted_ok = False
        if rate >= 0.95 and sorted_ok: return ms, f"日期格式统一({rate:.0%})且已排序", {"check": "日期格式", "status": "pass", "detail": f"统一率{rate:.0%}，已排序"}
        if rate >= 0.95: s = max(1, ms - 2); return s, f"日期格式OK但未排序", {"check": "日期格式", "status": "warn", "detail": f"统一率{rate:.0%}，未排序"}
        if sorted_ok: s = max(1, ms - 2); return s, f"已排序但日期格式不统一({rate:.0%})", {"check": "日期格式", "status": "warn", "detail": f"已排序，统一率{rate:.0%}"}
        s = max(0, ms - 3); return s, f"日期格式{rate:.0%}统一且未排序", {"check": "日期格式", "status": "fail", "detail": f"统一率{rate:.0%}，未排序"}
    elif check == "materials": return ms, "提交完整", {"check": "提交完整性", "status": "pass", "detail": "提交完整"}
    else: return ms, "通过", {"check": "通用检查", "status": "pass", "detail": "通过"}


def _find_column(df, pattern):
    for c in df.columns:
        if re.search(pattern, str(c)): return c
    return None


# ============================================================
#  LLM 评分（text / vision / hybrid）
# ============================================================
def _grade_llm(q_data, question, config, use_vision=False):
    """
    两阶段评分流水线（省钱核心）：
      Stage 1: 视觉模型看图 → 输出文字描述（输入token贵，但输出极短）
      Stage 2: DeepSeek 文本模型 → 根据描述评分（输入/输出都极便宜）

    相比让视觉模型直接评分，省了视觉模型昂贵的输出 token 费用。
    """
    from .grader_strategies import apply_strategy

    criteria = question["criteria"]
    max_score = question["max_score"]
    gtype = question.get("grading_type", "text")
    description = question.get("description", question.get("name", ""))
    submission_labels = question.get("submission_labels", [])

    # ---- 解析题目提交要求（从 submission_labels 提取必须材料） ----
    required_materials = []
    for sl in submission_labels:
        label = sl.get("label", "")
        sl_type = sl.get("type", "")
        field = sl.get("field", "")
        if sl_type in ("image",) or "截图" in label or "图" in label:
            required_materials.append({"type": "screenshot", "label": label})
        elif sl_type in ("video",) or "视频" in label:
            required_materials.append({"type": "video", "label": label})
        elif sl_type in ("file",) or "Excel" in label or "表格" in label:
            required_materials.append({"type": "excel", "label": label})
        elif sl_type in ("url",) or "链接" in label:
            required_materials.append({"type": "link", "label": label})
        elif field in ("prompt_text",) or "提示词" in label:
            required_materials.append({"type": "prompt_text", "label": label})
        elif field in ("persona_text",) or "人设" in label or "逻辑" in label:
            required_materials.append({"type": "persona_text", "label": label})

    content_desc = _build_content_desc(q_data, question)
    rule_ctx = _build_rule_context(q_data, question)

    criteria_text = "\n".join(
        f"  {i+1}. {c['name']}（{c['max']}分）：{c.get('desc','')}"
        for i, c in enumerate(criteria)
    )

    # ---- 材料证据检测（精确量化） ----
    prompt_text_len = len(str(q_data.get("prompt_text", "")))
    result_text_len = len(str(q_data.get("result_text", "")))
    persona_text_len = len(str(q_data.get("persona_text", "")))
    total_text_len = prompt_text_len + result_text_len + persona_text_len
    has_substantial_text = total_text_len > 30  # 实质性文字内容
    has_short_text = 5 <= total_text_len <= 30   # 只有简短文字

    has_screenshot = q_data.get("has_screenshot", False)
    has_images = bool(q_data.get("generated_images") or q_data.get("reference_image"))
    img_count = len(q_data.get("generated_images", []))
    if q_data.get("reference_image"):
        img_count += 1

    has_video = bool(q_data.get("has_video") and q_data.get("video_path"))
    has_excel = bool(q_data.get("excel_path"))
    bot_link = q_data.get("bot_link", "")
    has_link = bool(bot_link and "http" in str(bot_link))
    link_reachable = q_data.get("link_reachable")  # True/False/None

    # 构建材料证据报告
    evidence_lines = []
    evidence_lines.append(f"- 文字内容: {'有' if has_substantial_text else ('简短' if has_short_text else '无')} (提示词{prompt_text_len}字, 结果{result_text_len}字, 人设{persona_text_len}字)")
    if has_screenshot and not has_images:
        evidence_lines.append(f"- 截图: 有（学生表格中标注了截图位置，截图存在但图片文件未单独提取）")
    elif has_screenshot:
        evidence_lines.append(f"- 截图: 有（检测到{img_count}张图片）")
    else:
        evidence_lines.append(f"- 截图: 无")
    evidence_lines.append(f"- 生成图片: {'有(' + str(img_count) + '张)' if has_images else '无'}")
    evidence_lines.append(f"- 视频文件: {'有' if has_video else '无'}")
    evidence_lines.append(f"- Excel文件: {'有' if has_excel else '无'}")
    if has_link:
        lr_text = "可访问" if link_reachable is True else ("不可访问" if link_reachable is False else "未检测")
        evidence_lines.append(f"- 发布链接: 有 ({lr_text})")
    else:
        evidence_lines.append(f"- 发布链接: 无")
    evidence_report = "\n".join(evidence_lines)

    # 构建要求清单（该题需要提交什么）
    req_lines = []
    for rm in required_materials:
        req_lines.append(f"- {rm['label']} [{rm['type']}]")
    requirements_text = "\n".join(req_lines) if req_lines else "- 无特殊要求"

    # ---- 模式引导 ----
    mode = (config.get("grading", {}) or {}).get("mode", "relaxed")
    mode_rules = {
        "relaxed": (
            "【宽松模式】\n"
            "- 提交了必须材料 + 内容基本正确 → 80-100%\n"
            "- 缺少部分材料但有替代 → 50-70%\n"
            "- 完全没提交 → 0"
        ),
        "normal": (
            "【标准模式】\n"
            "- 所有必须材料齐全 + 质量好 → 90-100%\n"
            "- 缺少1项材料 → 最高70%\n"
            "- 缺少2项及以上材料 → 最高50%\n"
            "- 无实质内容 → 0"
        ),
        "strict": (
            "【严格模式】\n"
            "- 只有确实优秀才满分\n"
            "- 缺少任何必须材料 → 最高60%\n"
            "- 内容敷衍 → 最高30%\n"
            "- 材料有但质量差 → 50-70%\n"
            "- 无实质内容 → 0"
        ),
    }
    mode_guidance = mode_rules.get(mode, mode_rules["normal"])

    # ================================================================
    #  Stage 1: 视觉模型描述图片
    # ================================================================
    vision_description = ""
    vision_model_used = ""
    strategy = (config.get("vision_strategy")
                or router.get_router_config().get("vision_strategy", "paid_vision"))

    vision_model = router.get_vision_strategy_model(strategy)
    _, prompt_notes = apply_strategy(vision_model, question, q_data)

    if use_vision:
        strategy_images, _ = apply_strategy(vision_model, question, q_data)
        if strategy_images:
            vision_description = router.describe_images(
                images=strategy_images,
                question_name=question['name'],
                question_score=max_score,
                force_model=vision_model,
            )
            if vision_description:
                vision_model_used = vision_model
            else:
                vision_description = "（视觉模型不可用）"

    # ================================================================
    #  Stage 2: 构建评分 prompt（基于证据的分级评分）
    # ================================================================
    # 策略评分规则
    strategy_rules = ""
    if strategy == "text_only":
        strategy_rules = """
【纯文字模式 — 系统无法查看图片/视频，但这不是学生的错】
核心原则：学生提交了材料但因技术限制无法验证 → 应得满分。
- 只要材料证据报告显示某项材料存在（截图有、链接有、文字有等）→ 对应评分项应给满分
- 不要因为"看不到图片"而扣分 — 这是系统限制，学生已经提交了
- 评分时假设学生提交的图片/视频/截图质量合格
- 只在确实没有任何提交痕迹时才给低分（如：完全没有文字、没有截图标记、没有链接）

具体标准：
- 有详细的提示词/描述文字 → 说明学生认真完成了设计工作 → 视觉设计项给 90-100%
- 有截图标记 → 截图已提交 → 提交完整性给 90-100%
- 有链接且可访问 → 链接正常 → 满分
- 有视频文件标记 → 视频已提交 → 视频相关项给 90-100%
- 人设文字详细 → 智能体设计完整 → 给 90-100%

只在以下情况扣分：
- 完全没有文字内容 → 0
- 文字明显偏题 → 按偏离程度扣分
- 完全没有截图/链接标记 → 缺失项给0
"""
    elif strategy == "free_vision":
        strategy_rules = """
【免费视觉模式 — 仅能查看1张图片】
- 可见的图片正常评估
- 不可见图片：以提示词/描述文字为证据，描述详细即给满分
- 不要因为只能看1张图而扣分 — 这是系统限制
"""
    else:  # paid_vision
        strategy_rules = """
【付费视觉模式 — 可查看多张图片，全面评估】
- 所有可见图片正常评估
- 如有图片格式问题不可见，以文字描述为准
"""
    if gtype == "text":
        strategy_rules = """
【文本评分模式】
- 根据所有可用文字内容（提示词、生成结果、表格原文等）综合评估质量
- 检查学生提交内容中的完整度：是否有提示词 + 是否有生成文案/结果
- 如果表格原文中包含生成结果文本 → 正常评分（评估主题契合、内容质量）
- 如果只有提示词没有生成结果 → 提交完整性扣分（但提示词质量本身正常评）
- 不要凭空猜测截图中的内容，但表格原文中明确写出的文字应作为评分依据
"""

    # 智能体特殊规则
    hybrid_rules = ""
    if gtype == "hybrid":
        hybrid_rules = """
【智能体/混合题特殊规则】
- 人设/回复逻辑：检查文字质量
  - 文字 > 100 字且结构清晰 → 90-100%
  - 文字 30-100 字 → 60-90%
  - 文字 < 30 字 → 0-50%
- 知识库/截图：相信材料证据报告
  - 截图=有 → 截图已提交，给 90-100%
  - 截图=无 → 该项给 0
- 功能完善性：根据文字描述判断
  - 有功能介绍文字 → 80-100%
  - 无描述 → 0-30%
- 发布链接：根据材料证据判断
  - 链接有且可访问 → 90-100%
  - 链接有但不可访问 → 50-70%
  - 无链接 → 0
"""

    # 构建 vision_section
    vision_section = ""
    if vision_description:
        vision_section = f"""
【图片/视频帧描述（由视觉模型 {vision_model_used} 生成）】
{vision_description[:2000]}

（以上为视觉模型描述，请结合实际文字内容综合评分。）
"""
    elif use_vision:
        vision_section = "\n【注意】视觉模型不可用，无法查看图片/视频帧。\n"

    score_keys = "\n".join(f'  "得分_{c["id"]}_{c["name"]}": <int>,' for c in criteria)
    prompt = f"""你是严格的考试评分专家。必须基于提交材料的实际证据评分，不能凭空给分。

题目：{question['name']}（满分{max_score}分）
题目要求：{description[:800]}

评分标准：
{criteria_text}

【提交材料证据报告】
{evidence_report}

【该题要求提交的材料】
{requirements_text}

{mode_guidance}

{strategy_rules}
{hybrid_rules}
{vision_section}
学生提交内容：
{content_desc[:2000]}
{rule_ctx}

输出 JSON（不要markdown，不要注释）：
{{{{
  "档位判定": "<材料齐全/材料不足/敷衍/空>",
{score_keys}
  "总分": <int>,
  "评语": "<30字，指出缺失材料和扣分原因>"
}}}}

评分铁律（按优先级执行）：
1. 材料证据报告显示某项存在 → 学生已提交 → 应给满分或接近满分
2. 系统无法查看图片/视频是技术限制，不是学生的错 → 不要因此扣分
3. 只有在确实没有任何提交痕迹（无文字+无截图标记+无链接+无文件）时才给0
4. 学生有详细文字描述 = 学生认真完成了作业 = 应得高分"""

    try:
        # 始终用文本模型评分（便宜），视觉模型只负责描述
        llm_result = router.call_model(
            prompt=prompt, task_type="text",
            question_score=max_score, temperature=0.3, max_tokens=2048,
        )
        parsed = _parse_json(llm_result["content"])
        parsed["切题判断"] = parsed.get("档位判定", "材料齐全")
        parsed["tokens_in"] = llm_result["tokens_in"]
        parsed["tokens_out"] = llm_result["tokens_out"]
        parsed["raw_response"] = llm_result["content"]
        # 标记两阶段流水线
        if vision_model_used:
            parsed["_model_used"] = f"{vision_model_used}→deepseek-chat"
        else:
            parsed["_model_used"] = llm_result.get("model_used", "deepseek-chat")

        # 视频题后处理：有视频文件 → 服饰/背景/配音/音乐满分（AI无法精确评估）
        if has_video and question.get("grading_type") == "vision":
            for c in criteria:
                name = c.get("name", ""); key = f"得分_{c['id']}_{name}"
                if any(kw in name for kw in ["服饰", "背景", "配音", "音乐", "音效", "音频", "整体效果"]):
                    parsed[key] = c["max"]

        return parsed

    except Exception as e:
        result = _zero_score(criteria, max_score, f"LLM调用失败: {e}")
        return result


def _build_rule_context(q_data, question) -> str:
    if question.get("grading_type") != "code": return ""
    rule_results = q_data.get("_rule_results") or question.get("_rule_results")
    if not rule_results: return ""
    lines = ["客观检查结果（规则引擎自动验证）："]
    for r in rule_results:
        icon = {"pass": "OK", "warn": "WARN", "fail": "FAIL"}.get(r.get("status", ""), "?")
        lines.append(f"  [{icon}] {r['check']}: {r['detail']}")
    return "\n".join(lines)


def _build_content_desc(q_data, question):
    parts = []; name = question.get("name", ""); gtype = question.get("grading_type", "text")
    has_real_content = False
    missing_key_fields = []  # 追踪哪些关键字段缺失
    # 根据题型决定哪些字段是"关键输出字段"（缺失时需要补充表格原文）
    key_output_fields = {"result_text"}  # 所有题型都关注生成结果
    if gtype == "hybrid":
        key_output_fields.add("persona_text")
    if gtype == "vision":
        key_output_fields.update({"image_prompt", "video_prompt"})

    for key, label in [("prompt_text", "提示词"), ("result_text", "生成结果"),
                        ("image_prompt", "图片提示词"), ("video_prompt", "视频提示词"),
                        ("persona_text", "人设/逻辑")]:
        val = q_data.get(key, "")
        text = ""
        if isinstance(val, str): text = val.strip()
        elif isinstance(val, list): text = " ".join(str(v) for v in val if isinstance(v, str)).strip()
        if text:
            parts.append(f"{label}：{text[:300]}")
            has_real_content = True
        elif key in key_output_fields:
            missing_key_fields.append(label)

    if q_data.get("has_video") and q_data.get("video_path"):
        vinfo = q_data.get("video_info", "")
        quality_hint = ""
        if vinfo:
            import re as _re
            dur_match = _re.search(r'(\d+\.?\d*)\s*秒', vinfo)
            if dur_match:
                dur_sec = float(dur_match.group(1))
                if dur_sec >= 30: quality_hint = "【制作精良】时长达30秒以上，完成度很高"
                elif dur_sec >= 10: quality_hint = "【用心制作】超过10秒，内容较丰富"
            vframes = _extract_video_frames(q_data["video_path"], num_frames=4)
            if vframes: quality_hint += "（已提取视频关键帧供视觉评估，可通过帧图判断人物服饰、背景、画面质量）"
        parts.append(f"视频文件：已提交（{vinfo}）{quality_hint}" if vinfo else f"视频文件：已提交{quality_hint}")
    elif "视频" in name:
        parts.append("视频文件：未检测到（该题需要提交视频）")

    bot_link = q_data.get("bot_link", "")
    bot_link_str = bot_link if isinstance(bot_link, str) else (
        " ".join(str(v) for v in bot_link) if isinstance(bot_link, list) else str(bot_link))
    if bot_link_str and "http" in bot_link_str:
        lr = q_data.get("link_reachable")
        link_status = "（链接可访问）" if lr is True else ("（链接不可访问或无效！）" if lr is False else "")
        parts.append(f"发布链接：{bot_link_str}{link_status}")
    elif "智能体" in name:
        parts.append("发布链接：无")

    if q_data.get("has_screenshot"): parts.append("截图：有")

    # 关键改进：即使提取到部分字段，也追加表格原文让LLM自己找遗漏的内容
    # 之前只在 has_real_content=False 时才发送，导致Q1等题丢失生成结果
    all_table = q_data.get("all_table_text", "")
    if isinstance(all_table, list): all_table = " ".join(str(v) for v in all_table if isinstance(v, str))
    elif not isinstance(all_table, str): all_table = str(all_table)
    all_table = all_table.strip()

    if not has_real_content:
        # 完全没有提取到内容 → 表格原文作为主体
        if all_table:
            parts.append(f"学生提交内容：{all_table[:800]}")
    elif missing_key_fields and all_table:
        # 提取到了部分字段，但关键输出字段缺失（如生成结果、人设文本）
        # → 追加表格原文让LLM补救查找
        parts.append(f"【补充：表格原文（以下字段缺失: {', '.join(missing_key_fields)}，请从原文中查找）】\n{all_table[:800]}")

    return "\n".join(parts) if parts else "（无内容）"


def _collect_images(q_data):
    imgs = []
    for k in ["generated_images", "reference_image", "generated_image"]:
        v = q_data.get(k)
        if isinstance(v, list): imgs.extend(v)
        elif isinstance(v, str) and v: imgs.append(v)
    if q_data.get("has_video") and q_data.get("video_path"):
        vframes = _extract_video_frames(q_data["video_path"], num_frames=3)
        imgs.extend(vframes)
    # 收集后交给 model_router 按各模型 image_limit 钳制
    return [i for i in imgs if i and os.path.exists(str(i))]


def _parse_json(text):
    try: return json.loads(text)
    except json.JSONDecodeError: pass
    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if match:
        try: return json.loads(match.group(1))
        except json.JSONDecodeError: pass
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try: return json.loads(match.group(0))
        except json.JSONDecodeError: pass
    return {"总分": 0, "评语": "JSON解析失败", "parse_error": True}


def extract_scores(result: dict, question: dict) -> list:
    scores = []
    for c in question["criteria"]:
        key = f"得分_{c['id']}_{c['name']}"
        scores.append({"criterion_id": c["id"], "criterion_name": c["name"],
                       "score": result.get(key, 0), "max_score": c["max"]})
    return scores
