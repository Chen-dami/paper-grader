"""
通用评分引擎 —— 根据 rubric.json 中每道题的 grading_type 自动分发。
两层判定：主题档位（贴合主题/跑题/敷衍/空） + 素材标记（可叠加扣分）。
"""
import os, re
import pandas as pd
from . import llm


def grade(q_data: dict, question: dict, config: dict) -> dict:
    """通用评分入口。"""
    gtype = question.get("grading_type", "text")
    criteria = question["criteria"]
    max_score = question["max_score"]

    # ---- 1. 空提交检测 ----
    if _is_empty(q_data, gtype):
        return _zero_score(criteria, max_score, "内容为空")

    # ---- 2. 两层判定 ----
    tier = _detect_tier(q_data, question)
    flags = _detect_flags(q_data, question)

    # ---- 3. 按类型分发 ----
    if gtype == "code":
        result = _grade_code(q_data, question, tier, flags, config)
    elif gtype == "vision":
        result = _grade_llm(q_data, question, tier, flags, config, use_vision=True)
    else:  # text / hybrid
        result = _grade_llm(q_data, question, tier, flags, config, use_vision=False)

    # ---- 4. 汇总 ----
    total = sum(result.get(f"得分_{c['id']}_{c['name']}", 0) for c in criteria)
    result["总分"] = min(total, max_score)
    return result


# ============================================================
#  主题档位判定（互斥）
# ============================================================

def _detect_tier(q_data: dict, question: dict) -> str:
    """返回主题档位：贴合主题 / 跑题 / 敷衍 / 空"""
    keywords = question.get("topic_keywords", [])
    gtype = question.get("grading_type", "text")

    all_text = _collect_text(q_data, gtype)

    # 关键词匹配（至少2个）
    if keywords:
        matched = [kw for kw in keywords if kw in all_text]
        if len(keywords) >= 2:
            has_topic = len(matched) >= 2
        else:
            has_topic = len(matched) >= 1
    else:
        has_topic = True

    if not has_topic:
        return "跑题"

    has_substance = len(all_text.strip()) > _substance_threshold(gtype)
    if not has_substance:
        return "敷衍"

    return "贴合主题"


# ============================================================
#  素材标记判定（可叠加）
# ============================================================

def _detect_flags(q_data: dict, question: dict) -> list:
    """返回素材缺失标记列表，如 ["无视频", "仅截图"]"""
    flags = []
    gtype = question.get("grading_type", "text")
    name = question.get("name", "")

    # 仅截图标记（所有题型都可能）
    if q_data.get("result_is_screenshot"):
        flags.append("仅截图")

    # vision 题：检查图像和视频
    if gtype == "vision":
        has_images = bool(
            q_data.get("generated_images") or
            q_data.get("reference_image") or
            q_data.get("generated_image")
        )
        has_video = bool(q_data.get("has_video") and q_data.get("video_path"))

        if not has_images:
            flags.append("无图像")
        if "视频" in name and not has_video:
            flags.append("无视频")

    # code 题：检查 Excel/表格
    if gtype == "code":
        if not (q_data.get("excel_path") or q_data.get("has_excel_file")):
            flags.append("无表格")

    # hybrid 题：检查链接
    if gtype == "hybrid":
        bot_link = q_data.get("bot_link", "")
        if not bot_link or "http" not in str(bot_link):
            flags.append("无链接")

    return flags


def _effective_ratio(tier: str, flags: list, config: dict) -> tuple:
    """计算有效分数比例 (ratio_min, ratio_max)"""
    tiers_cfg = config.get("grading", {}).get("tiers", {})
    penalties = config.get("grading", {}).get("material_penalties", {})

    t = tiers_cfg.get(tier, {"ratio_min": 0.5, "ratio_max": 0.7})
    base_min = t.get("ratio_min", 0.5)
    base_max = t.get("ratio_max", 0.7)

    total_penalty = sum(penalties.get(f, 0.0) for f in flags)

    eff_min = max(0.05, base_min - total_penalty)
    eff_max = max(0.1, base_max - total_penalty)
    return eff_min, eff_max


# ============================================================
#  空提交检测
# ============================================================

def _is_empty(q_data: dict, gtype: str) -> bool:
    if gtype == "code":
        has_file = bool(q_data.get("excel_path") or q_data.get("has_excel_file"))
        has_screenshot = bool(q_data.get("has_screenshot"))
        return not has_file and not has_screenshot

    text_fields = ["prompt_text", "result_text", "image_prompt", "video_prompt",
                   "persona_text", "all_table_text"]
    all_text = ""
    for key in text_fields:
        val = q_data.get(key, "")
        if isinstance(val, str):
            all_text += val

    if gtype == "vision":
        has_images = bool(q_data.get("generated_images") or q_data.get("reference_image"))
        return len(all_text.strip()) < 10 and not has_images

    return len(all_text.strip()) < 10


def _zero_score(criteria: list, max_score: int, msg: str) -> dict:
    result = {"总分": 0, "评语": msg, "tokens_in": 0, "tokens_out": 0,
              "raw_response": "empty", "切题判断": "空"}
    for c in criteria:
        result[f"得分_{c['id']}_{c['name']}"] = 0
    return result


# ============================================================
#  文本收集
# ============================================================

def _collect_text(q_data: dict, gtype: str) -> str:
    parts = []
    for key in ["prompt_text", "result_text", "image_prompt", "video_prompt",
                "persona_text", "all_table_text"]:
        val = q_data.get(key, "")
        if isinstance(val, str):
            parts.append(val)
    return " ".join(parts)


def _substance_threshold(gtype: str) -> int:
    if gtype == "code":
        return 10
    elif gtype == "vision":
        return 40
    else:
        return 50


# ============================================================
#  纯代码评分（code 类型）
# ============================================================

def _grade_code(q_data: dict, question: dict, tier: str, flags: list,
                config: dict) -> dict:
    criteria = question["criteria"]
    data_checks = question.get("data_checks") or {}
    mode = config.get("grading", {}).get("mode", "relaxed")
    tiers_cfg = config.get("grading", {}).get("tiers", {})

    excel_path = q_data.get("excel_path", "")
    has_screenshot = q_data.get("has_screenshot", False)

    eff_min, _ = _effective_ratio(tier, flags, config)

    scores = {}
    reasons = {}

    if excel_path and os.path.exists(excel_path):
        try:
            df = pd.read_excel(excel_path)
            scores, reasons = _run_data_checks(df, criteria, data_checks, mode)
        except Exception as e:
            for c in criteria:
                scores[c["id"]] = _tier_base(c["max"], eff_min) - 1
                reasons[c["id"]] = f"Excel读取失败({str(e)[:50]})"
    else:
        for c in criteria:
            if has_screenshot:
                scores[c["id"]] = _tier_base(c["max"], eff_min)
                reasons[c["id"]] = "未找到Excel，根据截图给基础分"
            else:
                scores[c["id"]] = max(1, _tier_base(c["max"], eff_min) - 2)
                reasons[c["id"]] = "未提交Excel文件"

    prompt_text = q_data.get("prompt_text", "")
    prompt_cid = None
    for c in criteria:
        if "提示词" in c.get("name", "") or "材料" in c.get("name", ""):
            prompt_cid = c["id"]
            break

    if prompt_cid:
        if not prompt_text and has_screenshot:
            scores[prompt_cid] = max(scores.get(prompt_cid, 0),
                                     _tier_base(criteria[-1]["max"], eff_min))
            reasons[prompt_cid] = "提示词缺失，有截图给基础分"
        elif not prompt_text and not has_screenshot:
            scores[prompt_cid] = 0
            reasons[prompt_cid] = "未提交提示词和截图"

    total = sum(scores.get(c["id"], 0) for c in criteria)
    total = min(total, question["max_score"])

    comments = []
    flag_text = _flag_text(flags)
    for c in criteria:
        s = scores.get(c["id"], 0)
        if s >= c["max"]:
            comments.append(f"{c['name']}[OK]")
        elif s >= c["max"] * 0.6:
            comments.append(f"{c['name']}基本完成")
        else:
            comments.append(f"{c['name']}需加强")

    result = {
        "总分": total,
        "评语": "；".join(comments[:4]),
        "tokens_in": 0, "tokens_out": 0,
        "raw_response": f"code_graded:{tier}|{','.join(flags)}",
        "切题判断": f"{tier}" + (f" {flag_text}" if flag_text else ""),
    }
    for c in criteria:
        result[f"得分_{c['id']}_{c['name']}"] = scores.get(c["id"], 0)

    return result


def _run_data_checks(df: pd.DataFrame, criteria: list, data_checks: dict,
                     mode: str) -> tuple:
    scores = {}
    reasons = {}
    checks = []
    if data_checks.get("dedup"):
        checks.append("dedup")
    if data_checks.get("fillna"):
        checks.append("fillna")
    if data_checks.get("date_format"):
        checks.append("date_format")
    if data_checks.get("sort"):
        checks.append("sort")
    checks.append("materials")

    for i, c in enumerate(criteria):
        check = checks[i] if i < len(checks) else "generic"
        s, r = _check_one(df, c, check, data_checks, mode)
        scores[c["id"]] = s
        reasons[c["id"]] = r
    return scores, reasons


def _check_one(df: pd.DataFrame, criterion: dict, check: str,
               data_checks: dict, mode: str) -> tuple:
    max_s = criterion["max"]

    if check == "dedup":
        dup_rows = df.duplicated().sum()
        total_rows = len(df)
        if dup_rows == 0:
            return max_s, f"去重正确，共{total_rows}行无重复"
        elif dup_rows <= 3:
            return max_s - 1 if mode == "relaxed" else max(1, max_s - 2), f"残留{dup_rows}条重复"
        elif dup_rows <= 10:
            return _base(max_s, mode), f"残留{dup_rows}条重复"
        else:
            return max(_base(max_s, mode) - 1, 1), f"残留{dup_rows}条重复"

    elif check == "fillna":
        cfg = data_checks.get("fillna", {})
        pattern = cfg.get("column_pattern", "") if isinstance(cfg, dict) else str(cfg)
        col = _find_column(df, pattern) if pattern else None
        if col:
            null_count = df[col].isna().sum()
            if null_count == 0:
                return max_s, f"「{col}」无空值，补全正确"
            elif null_count <= 3:
                return max_s - 1 if mode == "relaxed" else max(1, max_s - 2), f"「{col}」残留{null_count}个空值"
            else:
                return _base(max_s, mode), f"「{col}」残留{null_count}个空值"
        else:
            return _base(max_s, mode), "未找到目标列"

    elif check == "date_format":
        cfg = data_checks.get("date_format", {})
        pattern = cfg.get("column_pattern", "日期|时间|date") if isinstance(cfg, dict) else "日期|时间|date"
        col = _find_column(df, pattern)
        if col:
            date_strs = df[col].dropna().astype(str)
            match_count = date_strs.str.match(r'\d{4}-\d{2}-\d{2}').sum()
            match_rate = match_count / len(date_strs) if len(date_strs) > 0 else 0
            if match_rate >= 0.95:
                return max_s, f"日期格式统一{match_rate:.0%}"
            elif match_rate >= 0.7:
                return max_s - 1 if mode == "relaxed" else max(1, max_s - 2), f"日期格式{match_rate:.0%}统一"
            else:
                return _base(max_s, mode), f"日期格式统一度不足{match_rate:.0%}"
        else:
            return _base(max_s, mode), "未找到日期列"

    elif check == "sort":
        cfg = data_checks.get("sort", {})
        pattern = cfg.get("column_pattern", "日期|时间|date") if isinstance(cfg, dict) else "日期|时间|date"
        col = _find_column(df, pattern)
        if col:
            try:
                sorted_vals = pd.to_datetime(df[col], errors='coerce').dropna()
                is_sorted = all(sorted_vals.iloc[i] <= sorted_vals.iloc[i + 1]
                                for i in range(len(sorted_vals) - 1))
                if is_sorted:
                    return max_s, f"按「{col}」排序正确"
                else:
                    return _base(max_s, mode), f"「{col}」未正确排序"
            except Exception:
                return _base(max_s, mode), "排序检查失败"
        else:
            return _base(max_s, mode), "未找到排序列"

    else:  # materials
        return _base(max_s, mode), "材料检查通过"


def _find_column(df: pd.DataFrame, pattern: str) -> str | None:
    for col in df.columns:
        if re.search(pattern, str(col)):
            return col
    return None


def _base(max_score: int, mode: str) -> int:
    if mode == "relaxed":
        return max(2, int(max_score * 0.6))
    return 0


def _tier_base(max_score: int, eff_min: float) -> int:
    return max(1, int(max_score * eff_min))


# ============================================================
#  LLM 评分（text / vision / hybrid 类型）
# ============================================================

def _grade_llm(q_data: dict, question: dict, tier: str, flags: list,
                config: dict, use_vision: bool = False) -> dict:
    criteria = question["criteria"]
    max_score = question["max_score"]

    eff_min, eff_max = _effective_ratio(tier, flags, config)
    tier_desc = config.get("grading", {}).get("tiers", {}).get(tier, {}).get("desc", "")

    content_desc = _build_content_desc(q_data, question, flags)
    prompt = _build_llm_prompt(question, criteria, tier, flags, tier_desc,
                                eff_min, eff_max, content_desc, max_score)

    if use_vision:
        images = _collect_images(q_data)
        if images:
            result = llm.grade_with_vision(prompt, images, question["id"])
        else:
            result = llm.grade_with_text(prompt, question["id"])
    else:
        result = llm.grade_with_text(prompt, question["id"])

    flag_text = _flag_text(flags)
    result["切题判断"] = f"{tier}" + (f" {flag_text}" if flag_text else "")
    return result


def _flag_text(flags: list) -> str:
    return "、".join(flags) if flags else ""


def _build_content_desc(q_data: dict, question: dict, flags: list) -> str:
    parts = []
    name = question.get("name", "")

    for key in ["prompt_text", "result_text", "image_prompt", "video_prompt",
                "persona_text"]:
        val = q_data.get(key, "")
        if isinstance(val, str) and val.strip():
            label = _field_label(key)
            parts.append(f"{label}：{val.strip()[:300]}")

    if q_data.get("has_video") and q_data.get("video_path"):
        parts.append("视频文件：已提交")
    elif "无视频" in flags:
        parts.append("视频文件：未检测到")

    if q_data.get("bot_link") and "http" in str(q_data.get("bot_link", "")):
        parts.append(f"发布链接：{q_data['bot_link']}")
    elif "无链接" in flags:
        parts.append("发布链接：无")

    if q_data.get("has_screenshot"):
        parts.append("截图：有")
    if "无图像" in flags:
        parts.append("生成图片：未检测到")
    if "无表格" in flags:
        parts.append("Excel表格：未检测到")
    if "仅截图" in flags:
        parts.append("注意：结果仅为截图，非原始文本")

    return "\n".join(parts) if parts else "（无内容）"


def _field_label(key: str) -> str:
    return {
        "prompt_text": "提示词", "result_text": "生成结果",
        "image_prompt": "图片提示词", "video_prompt": "视频提示词",
        "persona_text": "人设/逻辑", "all_table_text": "完整内容",
    }.get(key, key)


def _collect_images(q_data: dict) -> list:
    images = []
    for key in ["generated_images", "reference_image", "generated_image"]:
        val = q_data.get(key)
        if isinstance(val, list):
            images.extend(val)
        elif isinstance(val, str) and val:
            images.append(val)
    return [img for img in images if img and os.path.exists(str(img))]


def _build_llm_prompt(question: dict, criteria: list, tier: str, flags: list,
                      tier_desc: str, ratio_min: float, ratio_max: float,
                      content_desc: str, max_score: int) -> str:
    score_range = f"{int(max_score * ratio_min)}-{int(max_score * ratio_max)}"

    criteria_lines = []
    for i, c in enumerate(criteria):
        criteria_lines.append(f"{i+1}. {c['name']}（{c['max']}分）：{c.get('desc','')}")

    flag_line = ""
    if flags:
        flag_line = f"\n素材问题：{'、'.join(flags)}（已从基础分中扣除相应比例）"

    return f"""评分机器人。档位已定，请在此范围内分配各评分项分数。

题目：{question['name']}（满分{max_score}分）
评分标准：
{chr(10).join(criteria_lines)}

主题档位：**{tier}**（{tier_desc}）
分数范围：{score_range}分{flag_line}

学生提交内容：
{content_desc[:1500]}

请直接输出 JSON（不要 markdown 代码块）：
{{"得分_{question['id']}-1_{criteria[0]['name']}":<int>,"得分_{question['id']}-2_{criteria[1]['name']}":<int>,...,"总分":<int>,"评语":"<简短评语>"}}

要求：
- 各 criterion 得分在 0-{max(c['max'] for c in criteria)} 之间
- 总分在 {score_range} 之间
- 评语不超过15字"""


# ============================================================
#  分数提取
# ============================================================

def extract_scores(result: dict, question: dict) -> list:
    scores = []
    for c in question["criteria"]:
        key = f"得分_{c['id']}_{c['name']}"
        scores.append({
            "criterion_id": c["id"],
            "criterion_name": c["name"],
            "score": result.get(key, 0),
            "max_score": c["max"],
        })
    return scores
