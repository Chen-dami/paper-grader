"""重构 grader.py：移除硬编码，改为 rubric 驱动"""
import re

PATH = r"src\grader.py"
with open(PATH, "r", encoding="utf-8") as f:
    code = f.read()

# === 替换 _detect_tier 和相关函数 ===
new_detect = """def _detect_tier(q_data: dict, question: dict, config: dict) -> str:
    \"\"\"档位检测 -- 完全由 rubric 驱动，无硬编码。\"\"\"
    keywords = question.get("topic_keywords", [])
    gtype = question.get("grading_type", "text")
    all_text = _collect_text(q_data, gtype)
    tiers_cfg = list((config.get("grading", {}) or {}).get("tiers", {}).keys())

    # 从 rubric 读取每题独立的档位规则（向后兼容，无 tier 字段用默认值）
    tc = question.get("tier", {})
    text_min = tc.get("text_min", 10)
    perfunctory_max = tc.get("perfunctory_max", 50)
    kw_min = tc.get("keyword_min", 1)
    kw_need = tc.get("keyword_need", 2)
    mat_cfg = tc.get("materials", {})
    missing_max = tc.get("material_missing_max", 1)

    # 素材状态
    has_video = bool(q_data.get("has_video") and q_data.get("video_path"))
    has_images = bool(q_data.get("generated_images") or q_data.get("reference_image") or q_data.get("generated_image"))
    has_screenshot = bool(q_data.get("has_screenshot"))
    has_excel = bool(q_data.get("excel_path") or q_data.get("has_excel_file"))
    has_link = bool(q_data.get("bot_link") and "http" in str(q_data.get("bot_link", "")))

    mat = {"video": has_video, "images": has_images, "screenshot": has_screenshot,
           "excel": has_excel, "link": has_link}

    # 1. empty
    if gtype == "code":
        if not has_excel and not has_screenshot:
            return "空"
    else:
        if len(all_text.strip()) < text_min and not (has_images or has_video or has_screenshot):
            return "空"

    # 2. perfunctory
    if len(all_text.strip()) <= perfunctory_max:
        return "敷衍"

    # 3. off-topic (media present skips keyword check)
    if keywords and kw_min > 0:
        has_media = has_images or has_video
        if not (gtype == "vision" and has_media):
            matched = [kw for kw in keywords if kw in all_text]
            need = kw_need if len(keywords) >= kw_need else kw_min
            if len(matched) < need:
                return "跑题"

    # 4. material insufficiency (driven by rubric tier.materials)
    if mat_cfg:
        required = [k for k, v in mat_cfg.items() if v]
        missing = [k for k in required if not mat.get(k, True)]
        if len(missing) >= missing_max:
            return "素材不足" if "素材不足" in tiers_cfg else "敷衍"

    # 5. material flag matching (有X/无X tiers)
    for tk in tiers_cfg:
        if tk in ("空", "敷衍", "跑题", "贴合主题", "素材不足"):
            continue
        if _flag_match(tk, mat_cfg, mat):
            return tk

    return "贴合主题"


def _flag_match(tk: str, mat_cfg: dict, mat: dict) -> bool:
    \"\"\"Check if a material flag tier matches. Driven by mat_cfg declaration.\"\"\"
    tier_map = {
        "有截图": ("screenshot", True),  "无截图": ("screenshot", False),
        "有图像": ("images", True),      "无图像": ("images", False),
        "有视频": ("video", True),       "无视频": ("video", False),
        "有表格": ("excel", True),       "无表格": ("excel", False),
        "有链接": ("link", True),        "无链接": ("link", False),
    }
    if tk in tier_map:
        mat_key, expect = tier_map[tk]
        if mat_cfg.get(mat_key):  # only match if rubric declares this material
            return mat.get(mat_key, False) == expect
    return False
"""

# Find the _detect_tier function start and the _flag_match end
# Replace from "def _detect_tier" through the end of _flag_match (before the next section comment)
pattern = r'def _detect_tier\(.*?def _flag_match\(.*?(?=\n# ====|$)'
match = re.search(pattern, code, re.DOTALL)
if not match:
    print("ERROR: Could not find _detect_tier / _flag_match block")
    sys.exit(1)

# Also remove _get_required_materials and _material_present if they exist
code = re.sub(r'\ndef _get_required_materials\(.*?(?=\ndef |\n# ====|$)', '', code, flags=re.DOTALL)
code = re.sub(r'\ndef _material_present\(.*?(?=\ndef |\n# ====|$)', '', code, flags=re.DOTALL)

# Replace
code = code.replace(match.group(0), new_detect)

# Also fix _check_one_structured to use data_checks keys directly
# The old function matches criteria by Chinese name keywords - we keep backward compat
# but also read from data_checks keys directly

with open(PATH, "w", encoding="utf-8") as f:
    f.write(code)

print("grader.py refactored: _detect_tier now rubric-driven")
print("Removed: _get_required_materials, _material_present (merged into _detect_tier)")
print("_flag_match simplified: reads from rubric tier.materials declaration")
