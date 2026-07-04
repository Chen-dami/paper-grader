"""
评分引擎 —— 多题型分发 + 档位系统化 + 规则引擎结构化输出
"""
import os, re, yaml, json
import pandas as pd
from . import model_router as router
from .video_frame_extractor import extract_frames as _extract_video_frames


# ============================================================
#  主入口
# ============================================================
def grade(q_data: dict, question: dict, config: dict) -> dict:
    gtype = question.get("grading_type", "text")
    criteria = question["criteria"]
    max_score = question["max_score"]

    try:
        # 客观题先做确定性的规则检查
        if gtype in ("multiple_choice", "true_false", "fill_blank"):
            result = _grade_exact_match(q_data, question)
            return result

        if gtype == "code":
            rule_result = _grade_code(q_data, question, config)
            return rule_result

        # 主观题：空判 → 档位 → LLM评分
        if _is_truly_empty(q_data, gtype):
            return _zero_score(criteria, max_score, "内容为空")

        tier = _detect_tier(q_data, question, config)
        tier_config = _get_tier_config_extended(tier, config)
        use_vision = gtype == "vision"

        result = _grade_llm(q_data, question, tier, tier_config, config, use_vision)

        total = sum(result.get(f"得分_{c['id']}_{c['name']}", 0) for c in criteria)
        result["总分"] = min(total, max_score)
    except Exception as e:
        result = _zero_score(criteria, max_score, f"评分异常: {e}")
    return result


# ============================================================
#  客观题：精确匹配
# ============================================================
def _grade_exact_match(q_data: dict, question: dict) -> dict:
    criteria = question["criteria"]
    max_score = question["max_score"]
    gtype = question.get("grading_type", "multiple_choice")
    answer_key = question.get("answer_key", {})   # {"正确答案": "A", "分值": 5, "部分分": {...}}

    student_answer = _extract_answer(q_data, gtype)
    result = {"切题判断": "客观题", "tokens_in": 0, "tokens_out": 0, "raw_response": f"exact_match:{gtype}"}

    # 选择题 / 判断题
    if gtype in ("multiple_choice", "true_false"):
        correct = answer_key.get("正确答案", "")
        if isinstance(correct, list):  # 多选
            if isinstance(student_answer, list):
                matched = set(s.upper() for s in student_answer) == set(c.upper() for c in correct)
            else:
                matched = False
        else:  # 单选
            matched = str(student_answer).upper().strip() == str(correct).upper().strip()

        if matched:
            score = answer_key.get("分值", max_score)
            for c in criteria:
                result[f"得分_{c['id']}_{c['name']}"] = score if c["id"] == criteria[0]["id"] else 0
            result["评语"] = "答案正确"
            result["总分"] = score
        else:
            partial = answer_key.get("部分分", 0)
            for c in criteria:
                result[f"得分_{c['id']}_{c['name']}"] = 0
            result["评语"] = f"答案错误（正确答案：{correct}）"
            result["总分"] = partial
        return result

    # 填空题
    if gtype == "fill_blank":
        blanks = answer_key.get("答案", {})  # {"1": "人工智能", "2": ["AI", "人工智能"]}
        total_score = 0
        for i, c in enumerate(criteria):
            blank_key = str(i + 1)
            correct_answers = blanks.get(blank_key, "")
            if isinstance(correct_answers, str):
                correct_answers = [correct_answers]
            student_ans = student_answer.get(blank_key, "") if isinstance(student_answer, dict) else str(student_answer)
            is_correct = any(
                _fuzzy_match(str(student_ans), str(ans)) for ans in correct_answers
            )
            sc = c["max"] if is_correct else 0
            result[f"得分_{c['id']}_{c['name']}"] = sc
            total_score += sc
        result["评语"] = f"填空得分 {total_score}/{max_score}"
        result["总分"] = total_score
        return result

    # 简答题：按知识点踩分点
    if gtype == "short_answer":
        key_points = question.get("key_points", [])  # [{"keyword": "...", "score": 3}, ...]
        all_text = _collect_text(q_data, gtype)
        total_score = 0
        comments = []
        for kp in key_points:
            kw = kp.get("keyword", "")
            pts = kp.get("score", 0)
            if kw and kw in all_text:
                total_score += pts
                comments.append(f"+{pts}: 包含「{kw}」")
            else:
                comments.append(f"0: 缺少「{kw}」")
        result["评语"] = "；".join(comments[:6])
        result["总分"] = min(total_score, max_score)
        for i, c in enumerate(criteria):
            if i < len(key_points):
                result[f"得分_{c['id']}_{c['name']}"] = min(key_points[i].get("score", 0), c["max"])
            else:
                result[f"得分_{c['id']}_{c['name']}"] = 0
        return result

    return _zero_score(criteria, max_score, "不支持的客观题类型")


def _extract_answer(q_data: dict, gtype: str):
    """从学生提交中提取答案"""
    prompt_text = str(q_data.get("prompt_text", ""))
    result_text = str(q_data.get("result_text", ""))
    all_text = (prompt_text + " " + result_text).strip()

    # 选择题：匹配 A/B/C/D/ABCD 模式
    if gtype in ("multiple_choice", "true_false"):
        # 多选模式
        multi = re.findall(r'[A-Da-d]{2,}', all_text)
        if multi:
            return list(multi[0].upper())
        # 单选模式
        single = re.findall(r'\b([A-Da-d])\b', all_text)
        if single:
            return single[-1].upper()
        return all_text[:10]

    # 填空题：按行或编号分割
    if gtype == "fill_blank":
        lines = [l.strip() for l in all_text.split("\n") if l.strip()]
        if len(lines) <= 1:
            return all_text
        answers = {}
        for i, line in enumerate(lines):
            answers[str(i + 1)] = line
        return answers

    return all_text


def _fuzzy_match(student_ans: str, correct_ans: str) -> bool:
    """模糊匹配：忽略大小写、空格、标点差异"""
    def normalize(s):
        return re.sub(r'[\s，,。\.！!？?：:；;、""''「」]', '', s.lower())
    return normalize(student_ans) == normalize(correct_ans)


# ============================================================
#  档位系统化配置
# ============================================================
def _get_tier_config_extended(tier: str, config: dict) -> dict:
    """
    返回档位的扩展配置，影响 temperature / 评分粒度 / 评语风格 / prompt 结构
    """
    tiers_cfg = config.get("grading", {}).get("tiers", {})
    ti = tiers_cfg.get(tier, {"ratio_min": 0.5, "ratio_max": 1.0})

    # 档位 → 评分参数联动
    tier_params = {
        "贴合主题": {
            "temperature": 0.3, "max_tokens": 2048,
            "granularity": "精细",
            "feedback_style": "建设性",
            "emphasis": "精细区分优秀与良好，指出亮点和优化空间",
        },
        "跑题": {
            "temperature": 0.35, "max_tokens": 1536,
            "granularity": "粗粒",
            "feedback_style": "引导性",
            "emphasis": "学生偏离主题，对可挽回的基础部分给少量分，完全无关给0分",
        },
        "敷衍": {
            "temperature": 0.4, "max_tokens": 1024,
            "granularity": "粗粒",
            "feedback_style": "简短",
            "emphasis": "学生仅做了极少内容，只在有实质内容的项给少量分，其余给0分",
        },
        "空": {
            "temperature": 0.0, "max_tokens": 256,
            "granularity": "无",
            "feedback_style": "无",
            "emphasis": "未提交内容，所有项给0分",
        },
        "素材不足": {
            "temperature": 0.35, "max_tokens": 1536,
            "granularity": "粗粒",
            "feedback_style": "告知性",
            "emphasis": "关键素材缺失，评估已有部分质量，缺失项给0分，已有部分在低分段给分",
        },
    }

    # 有素材/无素材的通用档位
    if "有" in tier or "无" in tier:
        tp = {
            "temperature": 0.3, "max_tokens": 1536,
            "granularity": "标准",
            "feedback_style": "标准",
            "emphasis": f"关注对应素材的{'存在情况' if '有' in tier else '缺失情况'}，{'素材完整可给高分' if '有' in tier else '素材缺失应在对应评分项扣分'}",
        }
    else:
        tp = tier_params.get(tier, {
            "temperature": 0.3, "max_tokens": 1536,
            "granularity": "标准",
            "feedback_style": "标准",
            "emphasis": "根据内容完整度和质量合理分配分数",
        })

    tp["ratio_min"] = ti.get("ratio_min", 0.5)
    tp["ratio_max"] = ti.get("ratio_max", 1.0)
    tp["desc"] = ti.get("desc", "")
    return tp


# ============================================================
#  档位检测
# ============================================================
def _detect_tier(q_data: dict, question: dict, config: dict) -> str:
    keywords = question.get("topic_keywords", [])
    gtype = question.get("grading_type", "text")
    name = question.get("name", "")
    all_text = _collect_text(q_data, gtype)
    tiers_cfg = list((config.get("grading", {}) or {}).get("tiers", {}).keys())

    # 1. 空
    if gtype == "code":
        has_file = bool(q_data.get("excel_path") or q_data.get("has_excel_file"))
        if not has_file and not q_data.get("has_screenshot"):
            return "空"
    else:
        if len(all_text.strip()) < 10:
            if gtype == "vision":
                if not (q_data.get("generated_images") or q_data.get("reference_image")):
                    return "空"
            else:
                return "空"

    # 2. 敷衍
    threshold = {"code": 10, "vision": 40}.get(gtype, 50)
    if len(all_text.strip()) <= threshold:
        return "敷衍"

    # 3. 跑题
    if keywords:
        has_media = bool(q_data.get("generated_images") or q_data.get("reference_image") or
                         q_data.get("has_video") or q_data.get("generated_image"))
        if gtype == "vision" and has_media:
            pass
        else:
            matched = [kw for kw in keywords if kw in all_text]
            need = 2 if len(keywords) >= 2 else 1
            if len(matched) < need:
                return "跑题"

    # 4. 素材检查
    has_video = bool(q_data.get("has_video") and q_data.get("video_path"))
    has_images = bool(q_data.get("generated_images") or q_data.get("reference_image") or q_data.get("generated_image"))
    has_screenshot = bool(q_data.get("has_screenshot"))
    has_excel = bool(q_data.get("excel_path") or q_data.get("has_excel_file"))
    has_link = bool(q_data.get("bot_link") and "http" in str(q_data.get("bot_link", "")))

    required_materials = _get_required_materials(gtype, name, question)
    if required_materials:
        missing = [m for m in required_materials if not _material_present(m, has_video, has_images, has_screenshot, has_excel, has_link)]
        if len(missing) >= 2:
            return "素材不足" if "素材不足" in tiers_cfg else "敷衍"

    for tk in tiers_cfg:
        if tk in ("空", "敷衍", "跑题", "贴合主题", "素材不足"):
            continue
        if _flag_match(tk, gtype, name, has_video, has_images, has_screenshot, has_excel, has_link):
            return tk

    return "贴合主题"


# ============================================================
#  纯代码评分 (code 类型)
# ============================================================
def _grade_code(q_data: dict, question: dict, config: dict) -> dict:
    criteria = question["criteria"]
    data_checks = question.get("data_checks") or {}
    tier = _detect_tier(q_data, question, config)
    tc = _get_tier_config_extended(tier, config)
    base_ratio = tc.get("ratio_min", 0.5)

    excel_path = q_data.get("excel_path", "")
    has_screenshot = q_data.get("has_screenshot", False)

    # 规则引擎执行 + 结果结构化
    rule_results = []   # [{check, status, detail, score_deduct}]
    scores = {}
    reasons = {}

    if excel_path and isinstance(excel_path, str) and os.path.exists(excel_path):
        try:
            df = pd.read_excel(excel_path)
            scores, reasons, rule_results = _run_data_checks_structured(df, criteria, data_checks)
            # 用规则结果计算得分
            for c in criteria:
                sc = scores.get(c["id"], 0)
                if sc < c["max"]:
                    sc = max(sc, int(c["max"] * base_ratio) - 1)
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
        for c in criteria:
            if has_screenshot:
                scores[c["id"]] = max(1, int(c["max"] * base_ratio))
                reasons[c["id"]] = "未找到Excel，根据截图给基础分"
            else:
                scores[c["id"]] = max(1, int(c["max"] * base_ratio) - 2)
                reasons[c["id"]] = "未提交Excel文件"

    # 提示词/完整性检查
    prompt_text = q_data.get("prompt_text", "")
    for c in criteria:
        if "提示词" in c.get("name", "") or "材料" in c.get("name", ""):
            if not prompt_text and has_screenshot:
                scores[c["id"]] = max(scores.get(c["id"], 0), int(c["max"] * base_ratio))
                reasons[c["id"]] = "提示词缺失，有截图给基础分"
            elif not prompt_text and not has_screenshot:
                scores[c["id"]] = 0
                reasons[c["id"]] = "未提交提示词和截图"

    total = min(sum(scores.get(c["id"], 0) for c in criteria), question["max_score"])

    # 构建结构化评论
    comments = []
    for r in rule_results:
        icon = {"pass": "", "warn": "", "fail": ""}
        comments.append(f"{icon.get(r.get('status',''),'')}{r['check']}: {r['detail']}")

    result = {
        "总分": total,
        "评语": "；".join(comments[:5]) if comments else "规则引擎评估完成",
        "tokens_in": 0, "tokens_out": 0,
        "raw_response": f"code_graded:{tier}",
        "切题判断": tier,
        "_rule_results": rule_results,
    }
    for c in criteria:
        result[f"得分_{c['id']}_{c['name']}"] = scores.get(c["id"], 0)
    return result


def _run_data_checks_structured(df: pd.DataFrame, criteria: list, data_checks: dict) -> tuple:
    """执行数据检查并返回结构化结果（用于注入 LLM prompt）"""
    scores, reasons, rule_results = {}, {}, []
    for c in criteria:
        name = c.get("name", "")
        cid = c["id"]
        if "缺失" in name or "空值" in name:
            check = "fillna"
        elif "重复" in name or "去重" in name:
            check = "dedup"
        elif "格式" in name or "日期" in name or "排序" in name:
            check = "date_sort"
        elif "提交" in name or "完整" in name:
            check = "materials"
        elif "提示词" in name or "材料" in name:
            check = "materials"
        else:
            check = "generic"
        s, r, rr = _check_one_structured(df, c, check, data_checks)
        scores[cid], reasons[cid] = s, r
        rule_results.append(rr)
    return scores, reasons, rule_results


def _check_one_structured(df, criterion, check, data_checks) -> tuple:
    ms = criterion["max"]
    if check == "dedup":
        n = df.duplicated().sum()
        if n == 0:
            return ms, f"去重正确，共{len(df)}行无重复", {"check": "去重检查", "status": "pass", "detail": f"0条重复，共{len(df)}行"}
        if n <= 3:
            s = max(1, ms - 2)
            return s, f"残留{n}条重复", {"check": "去重检查", "status": "warn", "detail": f"残留{n}条重复"}
        s = max(0, ms - 3)
        return s, f"残留{n}条重复", {"check": "去重检查", "status": "fail", "detail": f"残留{n}条重复"}

    elif check == "fillna":
        cfg = data_checks.get("fillna", {})
        pat = cfg.get("column_pattern", "") or cfg.get("column", "")
        col = _find_column(df, pat) if pat else None
        if col:
            nc = df[col].isna().sum()
            if nc == 0:
                return ms, f"「{col}」无空值", {"check": "空值检查", "status": "pass", "detail": f"「{col}」0空值"}
            if nc <= 3:
                s = max(1, ms - 2)
                return s, f"「{col}」残留{nc}空值", {"check": "空值检查", "status": "warn", "detail": f"「{col}」{nc}空值"}
            s = max(0, ms - 3)
            return s, f"「{col}」残留{nc}空值", {"check": "空值检查", "status": "fail", "detail": f"「{col}」{nc}空值"}
        return max(1, ms - 1), "未找到目标列", {"check": "空值检查", "status": "warn", "detail": "未找到目标列"}

    elif check == "date_sort":
        cfg = data_checks.get("date_format", {})
        pat = cfg.get("column_pattern", "") or cfg.get("column", "") or "日期|时间|date"
        col = _find_column(df, pat)
        if not col:
            return max(1, ms - 1), "未找到日期列", {"check": "日期格式", "status": "warn", "detail": "未找到日期列"}
        ss = df[col].dropna().astype(str)
        fmt_ok = ss.str.match(r'\d{4}[/-]\d{1,2}[/-]\d{1,2}').sum()
        rate = fmt_ok / len(ss) if len(ss) > 0 else 0
        df_dedup = df.drop_duplicates()
        try:
            sv = pd.to_datetime(df_dedup[col], errors='coerce').dropna()
            sorted_ok = all(sv.iloc[i] <= sv.iloc[i+1] for i in range(len(sv)-1))
        except Exception:
            sorted_ok = False
        if rate >= 0.95 and sorted_ok:
            return ms, f"日期格式统一({rate:.0%})且已排序", {"check": "日期格式", "status": "pass", "detail": f"统一率{rate:.0%}，已排序"}
        if rate >= 0.95:
            s = max(1, ms - 2)
            return s, f"日期格式OK但未排序", {"check": "日期格式", "status": "warn", "detail": f"统一率{rate:.0%}，未排序"}
        if sorted_ok:
            s = max(1, ms - 2)
            return s, f"已排序但日期格式不统一({rate:.0%})", {"check": "日期格式", "status": "warn", "detail": f"已排序，统一率{rate:.0%}"}
        s = max(0, ms - 3)
        return s, f"日期格式{rate:.0%}统一且未排序", {"check": "日期格式", "status": "fail", "detail": f"统一率{rate:.0%}，未排序"}

    elif check == "materials":
        return ms, "提交完整", {"check": "提交完整性", "status": "pass", "detail": "提交完整"}

    else:
        return ms, "通过", {"check": "通用检查", "status": "pass", "detail": "通过"}


# ============================================================
#  LLM 评分（text / vision / hybrid）
# ============================================================
def _grade_llm(q_data, question, tier, tier_config, config, use_vision=False):
    criteria = question["criteria"]
    max_score = question["max_score"]
    rmin, rmax = tier_config["ratio_min"], tier_config["ratio_max"]

    content_desc = _build_content_desc(q_data, question)
    rule_ctx = _build_rule_context(q_data, question)

    prompt = _build_llm_prompt_v2(
        question, criteria, tier, tier_config, rmin, rmax,
        content_desc, rule_ctx, max_score
    )

    task_type = "vision" if use_vision else "text"
    images = _collect_images(q_data) if use_vision else None

    try:
        llm_result = router.call_model(
            prompt=prompt,
            task_type=task_type,
            images=images,
            question_score=max_score,
            temperature=tier_config.get("temperature", 0.3),
            max_tokens=tier_config.get("max_tokens", 2048),
        )

        parsed = _parse_json(llm_result["content"])
        parsed["切题判断"] = tier
        parsed["tokens_in"] = llm_result["tokens_in"]
        parsed["tokens_out"] = llm_result["tokens_out"]
        parsed["raw_response"] = llm_result["content"]
        parsed["_model_used"] = llm_result.get("model_used", "unknown")
        return parsed

    except Exception as e:
        result = _zero_score(criteria, max_score, f"LLM调用失败: {e}")
        result["切题判断"] = tier
        return result


def _build_rule_context(q_data, question) -> str:
    """构建规则引擎的客观检查上下文（结构化注入 LLM prompt）"""
    if question.get("grading_type") != "code":
        return ""
    rule_results = q_data.get("_rule_results") or question.get("_rule_results")
    if not rule_results:
        return ""

    lines = ["客观检查结果（规则引擎自动验证）："]
    for r in rule_results:
        icon = {"pass": "OK", "warn": "WARN", "fail": "FAIL"}.get(r.get("status", ""), "?")
        lines.append(f"  [{icon}] {r['check']}: {r['detail']}")
    return "\n".join(lines)


def _build_llm_prompt_v2(question, criteria, tier, tier_config, rmin, rmax,
                          content_desc, rule_ctx, max_score):
    sr_lo = int(max_score * rmin)
    sr_hi = int(max_score * rmax)

    cl = []
    for i, c in enumerate(criteria):
        cl.append(f"  {i+1}. {c['name']}（{c['max']}分）：{c.get('desc','')}")

    guidance = _tier_guidance_v2(tier, tier_config)

    parts = [
        f"你是考试评分专家。根据档位和评分标准严格分配各评分项分数。",
        f"",
        f"题目：{question['name']}（满分{max_score}分）",
        f"评分项：",
    ]
    parts.extend(cl)
    parts.append(f"")
    parts.append(f"档位：{tier}" + (f"（{tier_config.get('desc','')}）" if tier_config.get('desc') else ""))
    parts.append(f"总分范围：{sr_lo} ~ {sr_hi} 分（{int(rmin*100)}% ~ {int(rmax*100)}%）")
    parts.append(f"评分粒度：{tier_config.get('granularity','标准')}")
    parts.append(f"评语风格：{tier_config.get('feedback_style','标准')}")
    parts.append(f"")
    parts.append(guidance)

    if rule_ctx:
        parts.append(f"")
        parts.append(rule_ctx)
        parts.append(f"请基于以上客观结果 + 学生提交内容，综合评分。")

    parts.append(f"")
    parts.append(f"学生提交：")
    parts.append(content_desc[:1500])
    parts.append(f"")
    parts.append(f"输出 JSON（不要markdown）：")
    score_items = ", ".join([f'"得分_{question["id"]}-{c["id"]}_{c["name"]}":<int>' for c in criteria])
    parts.append(f'{{{{{score_items},"总分":<int>,"评语":"<{tier_config.get("max_tokens",1024)//len(criteria)//3}字>"}}}}')
    parts.append(f"")
    parts.append(f"铁则：")
    parts.append(f"- 总分必须在 {sr_lo} 到 {sr_hi} 之间")
    parts.append(f"- 学生完全没涉及的评分项必须给 0 分")
    parts.append(f"- 各项得分不超过该项满分")

    return "\n".join(parts)


def _tier_guidance_v2(tier, tc) -> str:
    """档位系统化指引 —— 影响评分侧重 + 评语风格 + 打分粒度"""
    g = tc.get("granularity", "标准")
    fs = tc.get("feedback_style", "标准")
    emp = tc.get("emphasis", "")

    granularity_guide = {
        "精细": "请仔细区分各评分项的完成质量，在优秀范围内合理区分满分和接近满分。",
        "标准": "按评分标准逐项评判，质量高的给高分，基本完成的给中等分。",
        "粗粒": "只需判断基本要求是否完成，有做给基础分，完全没做给0分。",
        "无": "所有评分项给0分。",
    }

    feedback_guide = {
        "建设性": "给出具体的建设性评语，指出亮点和可优化空间。",
        "引导性": "简短评语，指出主要问题方向即可。",
        "告知性": "告知缺失项和分数结果，不必展开分析。",
        "简短": "一句简短评语。",
        "标准": "根据得分情况给出适当评语。",
        "无": "不生成评语。",
    }

    return f"""评分指引：
{granularity_guide.get(g, granularity_guide['标准'])}
{feedback_guide.get(fs, feedback_guide['标准'])}
{emp}"""


# ============================================================
#  辅助函数
# ============================================================
def _is_truly_empty(q_data, gtype):
    if gtype == "code":
        return not (q_data.get("excel_path") or q_data.get("has_excel_file") or q_data.get("has_screenshot"))
    student_text = "".join(str(q_data.get(k, "")) for k in
        ["prompt_text", "result_text", "image_prompt", "video_prompt", "persona_text"])
    has_media = (
        q_data.get("generated_images") or
        q_data.get("reference_image") or
        (q_data.get("has_video") and q_data.get("video_path")) or
        bool(q_data.get("bot_link") and "http" in str(q_data.get("bot_link", "")))
    )
    return len(student_text.strip()) < 5 and not has_media


def _zero_score(criteria, max_score, msg):
    result = {"总分": 0, "评语": msg, "tokens_in": 0, "tokens_out": 0,
              "raw_response": "empty", "切题判断": "空"}
    for c in criteria:
        result[f"得分_{c['id']}_{c['name']}"] = 0
    return result


def _collect_text(q_data, gtype):
    parts = []
    for key in ["prompt_text", "result_text", "image_prompt", "video_prompt",
                "persona_text", "all_table_text"]:
        val = q_data.get(key, "")
        if isinstance(val, str):
            parts.append(val)
    return " ".join(parts)


def _get_required_materials(gtype, name, question):
    materials = []
    if gtype == "vision" and "视频" in name:
        materials.extend(["video", "images", "screenshot"])
    elif gtype == "vision":
        materials.extend(["images", "screenshot"])
    elif gtype == "code":
        materials.extend(["excel", "screenshot"])
    elif gtype == "hybrid":
        materials.extend(["screenshot", "link"])
        if "知识库" in str(question.get("description", "")):
            materials.append("excel")
    return materials


def _material_present(mat, has_video, has_images, has_screenshot, has_excel, has_link):
    return {
        "video": has_video, "images": has_images,
        "screenshot": has_screenshot, "excel": has_excel, "link": has_link,
    }.get(mat, True)


def _flag_match(tk, gtype, name, has_video, has_images, has_screenshot, has_excel, has_link):
    if tk in ("有视频", "无视频") and gtype == "vision" and "视频" in name:
        return (tk == "有视频" and has_video) or (tk == "无视频" and not has_video)
    if tk in ("有图像", "无图像") and gtype == "vision":
        return (tk == "有图像" and has_images) or (tk == "无图像" and not has_images)
    if tk in ("有截图", "无截图"):
        return (tk == "有截图" and has_screenshot) or (tk == "无截图" and not has_screenshot)
    if tk in ("有表格", "无表格") and gtype == "code":
        return (tk == "有表格" and has_excel) or (tk == "无表格" and not has_excel)
    if tk in ("有链接", "无链接"):
        if gtype == "hybrid" or "智能体" in name:
            return (tk == "有链接" and has_link) or (tk == "无链接" and not has_link)
    return False


def _build_content_desc(q_data, question):
    parts = []
    name = question.get("name", "")
    for key, label in [("prompt_text", "提示词"), ("result_text", "生成结果"),
                        ("image_prompt", "图片提示词"), ("video_prompt", "视频提示词"),
                        ("persona_text", "人设/逻辑")]:
        val = q_data.get(key, "")
        if isinstance(val, str) and val.strip():
            parts.append(f"{label}：{val.strip()[:300]}")

    if q_data.get("has_video") and q_data.get("video_path"):
        vinfo = q_data.get("video_info", "")
        parts.append(f"视频文件：已提交（{vinfo}）" if vinfo else "视频文件：已提交")
    elif "视频" in name:
        parts.append("视频文件：未检测到")

    if q_data.get("bot_link") and "http" in str(q_data.get("bot_link", "")):
        parts.append(f"发布链接：{q_data['bot_link']}")
    elif "智能体" in name:
        parts.append("发布链接：无")

    if q_data.get("has_screenshot"):
        parts.append("截图：有")

    return "\n".join(parts) if parts else "（无内容）"


def _collect_images(q_data):
    imgs = []
    for k in ["generated_images", "reference_image", "generated_image"]:
        v = q_data.get(k)
        if isinstance(v, list): imgs.extend(v)
        elif isinstance(v, str) and v: imgs.append(v)
    if q_data.get("has_video") and q_data.get("video_path"):
        vframes = _extract_video_frames(q_data["video_path"], num_frames=4)
        imgs.extend(vframes)
    return [i for i in imgs if i and os.path.exists(str(i))]


def _find_column(df, pattern):
    for c in df.columns:
        if re.search(pattern, str(c)): return c
    return None


def _parse_json(text):
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
    return {"总分": 0, "评语": f"JSON解析失败", "parse_error": True}


def extract_scores(result: dict, question: dict) -> list:
    scores = []
    for c in question["criteria"]:
        key = f"得分_{c['id']}_{c['name']}"
        scores.append({"criterion_id": c["id"], "criterion_name": c["name"],
                       "score": result.get(key, 0), "max_score": c["max"]})
    return scores
