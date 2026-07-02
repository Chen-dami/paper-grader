"""
通用评分引擎 —— 根据 rubric.json 中每道题的 grading_type 自动分发。
"""
import os, re
import pandas as pd
from . import llm


def grade(q_data: dict, question: dict, config: dict) -> dict:
    gtype = question.get("grading_type", "text")
    criteria = question["criteria"]
    max_score = question["max_score"]

    if _is_empty(q_data, gtype):
        return _zero_score(criteria, max_score, "内容为空")

    tier = _detect_tier(q_data, question)

    if gtype == "code":
        result = _grade_code(q_data, question, tier, config)
    elif gtype == "vision":
        result = _grade_llm(q_data, question, tier, config, use_vision=True)
    else:
        result = _grade_llm(q_data, question, tier, config, use_vision=False)

    total = sum(result.get(f"得分_{c['id']}_{c['name']}", 0) for c in criteria)
    result["总分"] = min(total, max_score)
    return result


def _detect_tier(q_data: dict, question: dict) -> str:
    """检测档位：按优先级返回，先匹配的生效"""
    keywords = question.get("topic_keywords", [])
    gtype = question.get("grading_type", "text")
    name = question.get("name", "")
    all_text = _collect_text(q_data, gtype)
    tiers_cfg = _get_tier_config()

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
        matched = [kw for kw in keywords if kw in all_text]
        need = 2 if len(keywords) >= 2 else 1
        if len(matched) < need:
            return "跑题"

    # 4. 素材检查（按配置顺序）
    has_video = bool(q_data.get("has_video") and q_data.get("video_path"))
    has_images = bool(q_data.get("generated_images") or q_data.get("reference_image") or q_data.get("generated_image"))
    has_screenshot = bool(q_data.get("has_screenshot"))
    has_excel = bool(q_data.get("excel_path") or q_data.get("has_excel_file"))
    has_link = bool(q_data.get("bot_link") and "http" in str(q_data.get("bot_link", "")))

    for tk in tiers_cfg:
        if tk in ("空", "敷衍", "跑题", "贴合主题"):
            continue
        if _flag_match(tk, gtype, name, has_video, has_images, has_screenshot, has_excel, has_link):
            return tk

    return "贴合主题"


def _flag_match(tk, gtype, name, has_video, has_images, has_screenshot, has_excel, has_link):
    """检查某个素材标记是否匹配当前提交"""
    if tk in ("有视频", "无视频") and gtype == "vision" and "视频" in name:
        return (tk == "有视频" and has_video) or (tk == "无视频" and not has_video)
    if tk in ("有图像", "无图像") and gtype == "vision":
        return (tk == "有图像" and has_images) or (tk == "无图像" and not has_images)
    if tk in ("有截图", "无截图"):
        return (tk == "有截图" and has_screenshot) or (tk == "无截图" and not has_screenshot)
    if tk in ("有表格", "无表格") and gtype == "code":
        return (tk == "有表格" and has_excel) or (tk == "无表格" and not has_excel)
    if tk in ("有链接", "无链接") and gtype == "hybrid":
        return (tk == "有链接" and has_link) or (tk == "无链接" and not has_link)
    return False


_tiers_cache = None

def _get_tier_config():
    """读取 config.yaml 中的档位列表（缓存）"""
    global _tiers_cache
    if _tiers_cache is not None:
        return _tiers_cache
    try:
        import yaml
        with open("config.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        _tiers_cache = list(cfg.get("grading", {}).get("tiers", {}).keys())
    except Exception:
        _tiers_cache = []
    return _tiers_cache


def _is_empty(q_data: dict, gtype: str) -> bool:
    if gtype == "code":
        has_file = bool(q_data.get("excel_path") or q_data.get("has_excel_file"))
        return not has_file and not q_data.get("has_screenshot")
    text_fields = ["prompt_text", "result_text", "image_prompt", "video_prompt",
                   "persona_text", "all_table_text"]
    all_text = "".join(str(q_data.get(k, "")) for k in text_fields)
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


def _collect_text(q_data: dict, gtype: str) -> str:
    parts = []
    for key in ["prompt_text", "result_text", "image_prompt", "video_prompt",
                "persona_text", "all_table_text"]:
        val = q_data.get(key, "")
        if isinstance(val, str):
            parts.append(val)
    return " ".join(parts)


# ============================================================
#  纯代码评分（code 类型）
# ============================================================

def _grade_code(q_data: dict, question: dict, tier: str, config: dict) -> dict:
    criteria = question["criteria"]
    data_checks = question.get("data_checks") or {}
    mode = config.get("grading", {}).get("mode", "relaxed")
    tiers_cfg = config.get("grading", {}).get("tiers", {})
    ti = tiers_cfg.get(tier, {"ratio_min": 0.5, "ratio_max": 0.7})
    base_ratio = ti.get("ratio_min", 0.5)

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

    prompt_text = q_data.get("prompt_text", "")
    for c in criteria:
        if "提示词" in c.get("name", "") or "材料" in c.get("name", ""):
            if not prompt_text and has_screenshot:
                scores[c["id"]] = max(scores.get(c["id"], 0), int(c["max"] * base_ratio))
                reasons[c["id"]] = "提示词缺失，有截图给基础分"
            elif not prompt_text and not has_screenshot:
                scores[c["id"]] = 0
                reasons[c["id"]] = "未提交提示词和截图"

    total = sum(scores.get(c["id"], 0) for c in criteria)
    total = min(total, question["max_score"])

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
        "tokens_in": 0, "tokens_out": 0,
        "raw_response": f"code_graded:{tier}",
        "切题判断": tier,
    }
    for c in criteria:
        result[f"得分_{c['id']}_{c['name']}"] = scores.get(c["id"], 0)
    return result


def _run_data_checks(df: pd.DataFrame, criteria: list, data_checks: dict,
                     mode: str) -> tuple:
    scores, reasons = {}, {}
    checks = []
    if data_checks.get("dedup"): checks.append("dedup")
    if data_checks.get("fillna"): checks.append("fillna")
    if data_checks.get("date_format"): checks.append("date_format")
    if data_checks.get("sort"): checks.append("sort")
    checks.append("materials")
    for i, c in enumerate(criteria):
        chk = checks[i] if i < len(checks) else "generic"
        s, r = _check_one(df, c, chk, data_checks, mode)
        scores[c["id"]], reasons[c["id"]] = s, r
    return scores, reasons


def _check_one(df, criterion, check, data_checks, mode):
    ms = criterion["max"]
    if check == "dedup":
        n = df.duplicated().sum()
        if n == 0: return ms, f"去重正确，共{len(df)}行无重复"
        if n <= 3: return ms - 1 if mode == "relaxed" else max(1, ms - 2), f"残留{n}条重复"
        return _base(ms, mode), f"残留{n}条重复"
    elif check == "fillna":
        cfg = data_checks.get("fillna", {})
        pat = cfg.get("column_pattern", "") if isinstance(cfg, dict) else str(cfg)
        col = _find_column(df, pat) if pat else None
        if col:
            nc = df[col].isna().sum()
            if nc == 0: return ms, f"「{col}」无空值"
            if nc <= 3: return ms - 1 if mode == "relaxed" else max(1, ms - 2), f"「{col}」残留{nc}空值"
            return _base(ms, mode), f"「{col}」残留{nc}空值"
        return _base(ms, mode), "未找到目标列"
    elif check == "date_format":
        cfg = data_checks.get("date_format", {})
        pat = cfg.get("column_pattern", "日期|时间|date") if isinstance(cfg, dict) else "日期|时间|date"
        col = _find_column(df, pat)
        if col:
            ss = df[col].dropna().astype(str)
            rate = ss.str.match(r'\d{4}-\d{2}-\d{2}').sum() / len(ss) if len(ss) > 0 else 0
            if rate >= 0.95: return ms, f"日期统一{rate:.0%}"
            if rate >= 0.7: return ms - 1 if mode == "relaxed" else max(1, ms - 2), f"日期{rate:.0%}统一"
            return _base(ms, mode), f"日期统一不足{rate:.0%}"
        return _base(ms, mode), "未找到日期列"
    elif check == "sort":
        cfg = data_checks.get("sort", {})
        pat = cfg.get("column_pattern", "日期|时间|date") if isinstance(cfg, dict) else "日期|时间|date"
        col = _find_column(df, pat)
        if col:
            try:
                sv = pd.to_datetime(df[col], errors='coerce').dropna()
                if all(sv.iloc[i] <= sv.iloc[i+1] for i in range(len(sv)-1)):
                    return ms, f"「{col}」排序正确"
                return _base(ms, mode), f"「{col}」未排序"
            except Exception:
                return _base(ms, mode), "排序检查失败"
        return _base(ms, mode), "未找到排序列"
    else:
        return _base(ms, mode), "通过"


def _find_column(df, pattern):
    for c in df.columns:
        if re.search(pattern, str(c)): return c
    return None


def _base(max_score, mode):
    return max(2, int(max_score * 0.6)) if mode == "relaxed" else 0


# ============================================================
#  LLM 评分（text / vision / hybrid 类型）
# ============================================================

def _grade_llm(q_data, question, tier, config, use_vision=False):
    criteria = question["criteria"]
    max_score = question["max_score"]
    tiers_cfg = config.get("grading", {}).get("tiers", {})
    ti = tiers_cfg.get(tier, {"ratio_min": 0.5, "ratio_max": 1.0, "desc": ""})
    rmin, rmax = ti.get("ratio_min", 0.5), ti.get("ratio_max", 1.0)

    content_desc = _build_content_desc(q_data, question)
    prompt = _build_llm_prompt(question, criteria, tier, ti.get("desc", ""),
                                rmin, rmax, content_desc, max_score)

    if use_vision:
        images = _collect_images(q_data)
        result = llm.grade_with_vision(prompt, images, question["id"]) if images else llm.grade_with_text(prompt, question["id"])
    else:
        result = llm.grade_with_text(prompt, question["id"])

    result["切题判断"] = tier
    return result


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
        parts.append("视频文件：已提交")
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
    return [i for i in imgs if i and os.path.exists(str(i))]


def _build_llm_prompt(question, criteria, tier, desc, rmin, rmax, content_desc, max_score):
    sr = f"{int(max_score * rmin)}-{int(max_score * rmax)}"
    cl = []
    for i, c in enumerate(criteria):
        cl.append(f"{i+1}. {c['name']}（{c['max']}分）：{c.get('desc','')}")
    return f"""评分机器人。在档位范围内分配各评分项分数。

题目：{question['name']}（满分{max_score}分）
评分标准：
{chr(10).join(cl)}

档位：{tier}{'（'+desc+'）' if desc else ''}
分数范围：{sr}分

学生提交：
{content_desc[:1500]}

直接输出 JSON（不要 markdown）：
{{"得分_{question['id']}-1_{criteria[0]['name']}":<int>,"得分_{question['id']}-2_{criteria[1]['name']}":<int>,...,"总分":<int>,"评语":"<15字>"}}

- 各项得分 0-{max(c['max'] for c in criteria)}
- 总分在 {sr} 之间"""


def extract_scores(result: dict, question: dict) -> list:
    scores = []
    for c in question["criteria"]:
        key = f"得分_{c['id']}_{c['name']}"
        scores.append({"criterion_id": c["id"], "criterion_name": c["name"],
                       "score": result.get(key, 0), "max_score": c["max"]})
    return scores
