"""
通用评分引擎 —— 根据 rubric.json 中每道题的 grading_type 自动分发。
替代原来的 5 个独立 grader 文件。

grading_type:
  - "code"   : 纯代码评分（pandas/excel检查），零 token
  - "text"   : 代码定档 + LLM 文字评分
  - "vision" : 代码定档 + LLM 视觉评分
  - "hybrid" : 代码定档 + LLM 文字评分 + 可选实测
"""
import os, re
import pandas as pd
from . import llm


def grade(q_data: dict, question: dict, config: dict) -> dict:
    """
    通用评分入口。

    参数:
        q_data: preprocessor 输出的单题数据 {"prompt_text":..., "result_text":..., ...}
        question: rubric.json 中该题的配置（含 grading_type, topic_keywords, criteria 等）
        config: 全局配置

    返回:
        {"总分": int, "评语": str, "得分_X-Y_XXX": int, ...}
    """
    gtype = question.get("grading_type", "text")
    criteria = question["criteria"]
    max_score = question["max_score"]

    # ---- 1. 空提交检测 ----
    if _is_empty(q_data, gtype):
        return _zero_score(criteria, max_score, "内容为空")

    # ---- 2. 代码定档 ----
    tier = _detect_tier(q_data, question, config)

    # ---- 3. 按类型分发 ----
    if gtype == "code":
        result = _grade_code(q_data, question, tier, config)
    elif gtype == "vision":
        result = _grade_llm(q_data, question, tier, config, use_vision=True)
    else:  # text / hybrid
        result = _grade_llm(q_data, question, tier, config, use_vision=False)

    # ---- 4. 汇总 ----
    total = sum(result.get(f"得分_{c['id']}_{c['name']}", 0) for c in criteria)
    result["总分"] = min(total, max_score)
    return result


# ============================================================
#  空提交检测
# ============================================================

def _is_empty(q_data: dict, gtype: str) -> bool:
    """判断是否为空提交"""
    if gtype == "code":
        # code 类：没有 Excel 文件也没有截图
        has_file = bool(q_data.get("excel_path") or q_data.get("has_excel_file"))
        has_screenshot = bool(q_data.get("has_screenshot"))
        return not has_file and not has_screenshot

    # text/vision/hybrid：检查所有文本字段
    text_fields = ["prompt_text", "result_text", "image_prompt", "video_prompt",
                   "persona_text", "all_table_text"]
    all_text = ""
    for key in text_fields:
        val = q_data.get(key, "")
        if isinstance(val, str):
            all_text += val

    # vision 类额外检查图片
    if gtype == "vision":
        has_images = bool(q_data.get("generated_images") or q_data.get("reference_image"))
        return len(all_text.strip()) < 10 and not has_images

    return len(all_text.strip()) < 10


def _zero_score(criteria: list, max_score: int, msg: str) -> dict:
    """返回零分结果"""
    result = {"总分": 0, "评语": msg, "tokens_in": 0, "tokens_out": 0,
              "raw_response": "empty", "切题判断": "空"}
    for c in criteria:
        result[f"得分_{c['id']}_{c['name']}"] = 0
    return result


# ============================================================
#  切题检测（代码定档）
# ============================================================

def _detect_tier(q_data: dict, question: dict, config: dict) -> str:
    """
    用 topic_keywords 判断贴合主题/跑题/敷衍/空。
    返回档位名（如 "贴合主题", "跑题", "敷衍"）。
    """
    keywords = question.get("topic_keywords", [])
    gtype = question.get("grading_type", "text")
    name = question.get("name", "")

    # 收集所有文本
    all_text = _collect_text(q_data, gtype)

    # ---- 关键词匹配（至少 2 个，降低误判） ----
    has_topic = False
    if keywords:
        matched = [kw for kw in keywords if kw in all_text]
        if len(keywords) >= 2:
            has_topic = len(matched) >= 2
        else:
            has_topic = len(matched) >= 1
    else:
        # 没有配置关键词 → 默认算切题
        has_topic = True

    has_substance = len(all_text.strip()) > _substance_threshold(gtype)

    # ---- 特殊检查 ----
    has_video = bool(q_data.get("has_video") and q_data.get("video_path"))
    has_link = bool(q_data.get("bot_link") and "http" in str(q_data.get("bot_link", "")))
    result_is_screenshot = bool(q_data.get("result_is_screenshot"))
    has_images = bool(q_data.get("generated_images") or q_data.get("reference_image")
                      or q_data.get("generated_image"))

    if not has_topic:
        return "跑题"
    elif not has_substance:
        return "敷衍"

    # vision 类素材检查（优先级：全缺 > 无视频 > 无图）
    if gtype == "vision":
        video_expected = "视频" in name
        if video_expected and not has_video and not has_images:
            return "无素材"
        elif video_expected and not has_video:
            return "无视频"
        elif not has_images:
            return "无图像"

    if result_is_screenshot:
        return "仅截图"
    elif gtype == "hybrid" and not has_link and has_topic:
        return "无链接"
    else:
        return "贴合主题"


def _collect_text(q_data: dict, gtype: str) -> str:
    """收集题目中所有文本内容"""
    parts = []
    for key in ["prompt_text", "result_text", "image_prompt", "video_prompt",
                "persona_text", "all_table_text"]:
        val = q_data.get(key, "")
        if isinstance(val, str):
            parts.append(val)
    return " ".join(parts)


def _substance_threshold(gtype: str) -> int:
    """不同题型的内容阈值"""
    if gtype == "code":
        return 10
    elif gtype == "vision":
        return 40
    else:
        return 50


# ============================================================
#  纯代码评分（code 类型）
# ============================================================

def _grade_code(q_data: dict, question: dict, tier: str, config: dict) -> dict:
    """
    纯代码评分：用 pandas 检查 Excel 数据。
    零 LLM 调用，根据 data_checks 和 tier 算分。
    """
    criteria = question["criteria"]
    data_checks = question.get("data_checks") or {}
    mode = config.get("grading", {}).get("mode", "relaxed")
    tiers_cfg = config.get("grading", {}).get("tiers", {})

    excel_path = q_data.get("excel_path", "")
    has_screenshot = q_data.get("has_screenshot", False)

    scores = {}
    reasons = {}

    if excel_path and os.path.exists(excel_path):
        try:
            df = pd.read_excel(excel_path)
            scores, reasons = _run_data_checks(df, criteria, data_checks, mode)
        except Exception as e:
            for c in criteria:
                scores[c["id"]] = _tier_base_score(c["max"], tier, tiers_cfg, mode) - 1
                reasons[c["id"]] = f"Excel读取失败({str(e)[:50]})"
    else:
        # 无 Excel 文件
        for c in criteria:
            if has_screenshot:
                scores[c["id"]] = _tier_base_score(c["max"], tier, tiers_cfg, mode)
                reasons[c["id"]] = "未找到Excel文件，根据截图给基础分"
            else:
                scores[c["id"]] = 1
                reasons[c["id"]] = "未提交Excel文件，无截图"

    # 检查提示词
    prompt_text = q_data.get("prompt_text", "")
    prompt_cid = None
    for c in criteria:
        if "提示词" in c.get("name", "") or "材料" in c.get("name", ""):
            prompt_cid = c["id"]
            break

    if prompt_cid:
        if not prompt_text and has_screenshot:
            scores[prompt_cid] = max(scores.get(prompt_cid, 0), _tier_base_score(criteria[-1]["max"], tier, tiers_cfg, mode))
            reasons[prompt_cid] = "提示词文本缺失，但有截图，给基础分"
        elif not prompt_text and not has_screenshot:
            scores[prompt_cid] = 0
            reasons[prompt_cid] = "未提交提示词和截图"

    # 计算总分
    total = sum(scores.get(c["id"], 0) for c in criteria)
    total = min(total, question["max_score"])

    # 生成评语
    comments = []
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
        "tokens_in": 0,
        "tokens_out": 0,
        "raw_response": f"code_graded:{tier}",
        "切题判断": tier,
    }
    for c in criteria:
        result[f"得分_{c['id']}_{c['name']}"] = scores.get(c["id"], 0)

    return result


def _run_data_checks(df: pd.DataFrame, criteria: list, data_checks: dict,
                     mode: str) -> tuple:
    """执行数据检查项，返回 (scores_dict, reasons_dict)"""
    scores = {}
    reasons = {}

    # 将 criteria 按顺序分配检查项
    checks = []
    if data_checks.get("dedup"):
        checks.append("dedup")
    if data_checks.get("fillna"):
        checks.append("fillna")
    if data_checks.get("date_format"):
        checks.append("date_format")
    if data_checks.get("sort"):
        checks.append("sort")
    # 最后一个 criterion 通常是"材料完整"
    checks.append("materials")

    for i, c in enumerate(criteria):
        check = checks[i] if i < len(checks) else "generic"
        s, r = _check_one(df, c, check, data_checks, mode)
        scores[c["id"]] = s
        reasons[c["id"]] = r

    return scores, reasons


def _check_one(df: pd.DataFrame, criterion: dict, check: str,
               data_checks: dict, mode: str) -> tuple:
    """执行单项检查"""
    max_s = criterion["max"]

    if check == "dedup":
        dup_rows = df.duplicated().sum()
        total_rows = len(df)
        if dup_rows == 0:
            return max_s, f"去重正确，共{total_rows}行，无重复"
        elif dup_rows <= 3:
            return max_s - 1 if mode == "relaxed" else max(1, max_s - 2), f"残留{dup_rows}条重复"
        elif dup_rows <= 10:
            return _base(max_s, mode), f"残留{dup_rows}条重复，去重不彻底"
        else:
            return max(_base(max_s, mode) - 1, 1), f"残留{dup_rows}条重复，效果差"

    elif check == "fillna":
        cfg = data_checks.get("fillna", {})
        pattern = cfg.get("column_pattern", "") if isinstance(cfg, dict) else str(cfg)
        col = _find_column(df, pattern) if pattern else None
        if col:
            null_count = df[col].isna().sum()
            if null_count == 0:
                return max_s, f"「{col}」列无空值，补全正确"
            elif null_count <= 3:
                return max_s - 1 if mode == "relaxed" else max(1, max_s - 2), f"「{col}」残留{null_count}个空值"
            else:
                return _base(max_s, mode), f"「{col}」残留{null_count}个空值"
        else:
            return _base(max_s, mode), "未找到目标列，无法验证"

    elif check == "date_format":
        cfg = data_checks.get("date_format", {})
        pattern = cfg.get("column_pattern", "日期|时间|date") if isinstance(cfg, dict) else "日期|时间|date"
        fmt = cfg.get("format", "YYYY-MM-DD") if isinstance(cfg, dict) else "YYYY-MM-DD"
        col = _find_column(df, pattern)
        if col:
            date_strs = df[col].dropna().astype(str)
            match_count = date_strs.str.match(r'\d{4}-\d{2}-\d{2}').sum()
            match_rate = match_count / len(date_strs) if len(date_strs) > 0 else 0
            if match_rate >= 0.95:
                return max_s, f"日期格式统一，{match_rate:.0%}符合{fmt}"
            elif match_rate >= 0.7:
                return max_s - 1 if mode == "relaxed" else max(1, max_s - 2), f"日期格式大部分统一（{match_rate:.0%}）"
            else:
                return _base(max_s, mode), f"日期格式统一度不足（{match_rate:.0%}）"
        else:
            return _base(max_s, mode), "未找到日期列，无法验证"

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

    else:  # materials / generic
        return _base(max_s, mode), "材料检查通过"


def _find_column(df: pd.DataFrame, pattern: str) -> str | None:
    """根据正则模式查找列名"""
    for col in df.columns:
        if re.search(pattern, str(col)):
            return col
    return None


def _base(max_score: int, mode: str) -> int:
    """基础分"""
    if mode == "relaxed":
        return max(2, int(max_score * 0.6))
    return 0


def _tier_base_score(max_score: int, tier: str, tiers_cfg: dict, mode: str) -> int:
    """根据档位获取基础分"""
    tier_info = tiers_cfg.get(tier, {})
    ratio = tier_info.get("ratio_min", 0.5)
    return max(1, int(max_score * ratio))


# ============================================================
#  LLM 评分（text / vision / hybrid 类型）
# ============================================================

def _grade_llm(q_data: dict, question: dict, tier: str, config: dict,
               use_vision: bool = False) -> dict:
    """
    代码定档 + LLM 打分。
    构建 prompt 让 LLM 在档位范围内分配各 criterion 分数。
    """
    criteria = question["criteria"]
    max_score = question["max_score"]
    tiers_cfg = config.get("grading", {}).get("tiers", {})
    tier_info = tiers_cfg.get(tier, {"ratio_min": 0.5, "ratio_max": 1.0, "desc": ""})

    ratio_min = tier_info.get("ratio_min", 0.9)
    ratio_max = tier_info.get("ratio_max", 1.0)
    tier_desc = tier_info.get("desc", "")

    # 构建学生内容描述
    content_desc = _build_content_desc(q_data, question)

    # 构建评分 prompt
    prompt = _build_llm_prompt(question, criteria, tier, tier_desc,
                                ratio_min, ratio_max, content_desc, max_score)

    # 调 LLM
    if use_vision:
        images = _collect_images(q_data)
        if images:
            result = llm.grade_with_vision(prompt, images, question["id"])
        else:
            result = llm.grade_with_text(prompt, question["id"])
    else:
        result = llm.grade_with_text(prompt, question["id"])

    result["切题判断"] = tier
    return result


def _build_content_desc(q_data: dict, question: dict) -> str:
    """构建学生提交内容的文字描述"""
    parts = []
    name = question.get("name", "")

    for key in ["prompt_text", "result_text", "image_prompt", "video_prompt",
                "persona_text"]:
        val = q_data.get(key, "")
        if isinstance(val, str) and val.strip():
            label = _field_label(key)
            parts.append(f"{label}：{val.strip()[:300]}")

    # 特殊标记
    if q_data.get("has_video") and q_data.get("video_path"):
        parts.append("视频文件：已提交")
    elif "视频" in name:
        parts.append("视频文件：未检测到")

    if q_data.get("bot_link") and "http" in str(q_data.get("bot_link", "")):
        parts.append(f"发布链接：{q_data['bot_link']}")
    elif "智能体" in name or "agent" in name.lower():
        parts.append("发布链接：无")

    if q_data.get("has_screenshot"):
        parts.append("截图：有")

    return "\n".join(parts) if parts else "（无内容）"


def _field_label(key: str) -> str:
    """字段名 → 中文标签"""
    return {
        "prompt_text": "提示词", "result_text": "生成结果",
        "image_prompt": "图片提示词", "video_prompt": "视频提示词",
        "persona_text": "人设/逻辑", "all_table_text": "完整内容",
    }.get(key, key)


def _collect_images(q_data: dict) -> list:
    """收集题目中的图片路径"""
    images = []
    for key in ["generated_images", "reference_image", "generated_image"]:
        val = q_data.get(key)
        if isinstance(val, list):
            images.extend(val)
        elif isinstance(val, str) and val:
            images.append(val)
    return [img for img in images if img and os.path.exists(str(img))]


def _build_llm_prompt(question: dict, criteria: list, tier: str, tier_desc: str,
                      ratio_min: float, ratio_max: float, content_desc: str,
                      max_score: int) -> str:
    """构建 LLM 评分 prompt"""
    score_range = f"{int(max_score * ratio_min)}-{int(max_score * ratio_max)}"

    criteria_lines = []
    for i, c in enumerate(criteria):
        criteria_lines.append(f"{i+1}. {c['name']}（{c['max']}分）：{c.get('desc','')}")

    return f"""评分机器人。档位已定，只分配分数。

题目：{question['name']}（满分{max_score}分）
评分标准：
{chr(10).join(criteria_lines)}

档位：**{tier}**（{tier_desc}）
分数范围：{score_range}分

学生提交内容：
{content_desc[:1500]}

请直接输出 JSON（不要 markdown 代码块）：
{{"得分_{question['id']}-1_{criteria[0]['name']}":<int>,"得分_{question['id']}-2_{criteria[1]['name']}":<int>,...,"总分":<int>,"评语":"<简短评语>"}}

要求：
- 各 criterion 得分在 0-{max(c['max'] for c in criteria)} 之间
- 总分在 {score_range} 之间
- 评语不超过15字"""


# ============================================================
#  分数提取（供 main.py 调 db.save_score）
# ============================================================

def extract_scores(result: dict, question: dict) -> list:
    """从评分结果中提取各 criterion 分数列表"""
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
