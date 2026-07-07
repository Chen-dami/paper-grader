"""
Q3 视频题诊断脚本 —— 完整链路追踪
用法: python tools/diagnose_q3.py
"""
import os, sys, json, io

# 强制 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.extractor import extract
from src.preprocessor import process
from src.grader import (
    grade, _grade_llm, _build_content_desc, _collect_images,
    _is_truly_empty, _collect_text,
)
from src import model_router as router
from src.utils import load_rubric, load_config

config = load_config("config.yaml")
rubric = load_rubric("data/rubric.json")

PAPER_PATH = r"C:\baidunetdiskdownload\dome2401\216102050204崔宗岳\216102050204崔宗岳.docx"

print("=" * 70)
print("  Q3 视频题诊断脚本")
print("=" * 70)

# ============================================================
# STEP 1: 文档提取
# ============================================================
print(f"\n{'='*70}")
print(f"STEP 1: 文档提取")
print(f"文件: {PAPER_PATH}")
print(f"文件存在: {os.path.exists(PAPER_PATH)}")
print(f"{'='*70}")

paper = extract(PAPER_PATH, output_dir="output/diagnose_q3")
print(f"学生: {paper['student_info']}")
print(f"段落数: {len(paper['paragraphs'])}")
print(f"表格数: {len(paper['tables'])}")
for ti, t in enumerate(paper['tables']):
    print(f"  表格{ti}: {len(t)}行 × {len(t[0]) if t else 0}列")
    for ri, row in enumerate(t[:8]):
        print(f"    row{ri}: {[str(c)[:80] for c in row]}")
    if len(t) > 8:
        print(f"    ... (共{len(t)}行)")

print(f"\n图片数: {len(paper['images'])}")
for i, img in enumerate(paper['images']):
    print(f"  图片{i}: {img[0]}")
    print(f"         尺寸: {img[1]}x{img[2]}, 大小: {img[3]}bytes")

print(f"\n嵌入文件数: {len(paper['embedded_files'])}")
for ef in paper['embedded_files']:
    size_mb = os.path.getsize(ef[0]) / (1024*1024) if os.path.exists(ef[0]) else 0
    print(f"  {ef[0]} ({ef[1]}) - {size_mb:.1f}MB")

# ============================================================
# STEP 2: 预处理
# ============================================================
print(f"\n{'='*70}")
print(f"STEP 2: 预处理 → Q3 数据提取")
print(f"{'='*70}")

preprocessed = process(paper, rubric, config)
q3 = [q for q in rubric["questions"] if q["id"] == 3][0]
q3d = preprocessed.get("q3", {})

print(f"\nQ3 [{q3['name']}] ({q3['grading_type']}) 满分{q3['max_score']}")
print(f"  评分标准:")
for c in q3["criteria"]:
    print(f"    {c['id']} {c['name']}: {c['max']}分 - {c.get('desc','')}")

print(f"\n  提取到的数据:")
for k, v in q3d.items():
    if k in ("all_table_text",):
        continue
    if k == "generated_images":
        if isinstance(v, list):
            print(f"    {k}: {len(v)} 张")
            for gi in v:
                print(f"      → {gi}")
        else:
            print(f"    {k}: {v}")
    elif isinstance(v, str) and len(str(v)) > 200:
        print(f"    {k}: {str(v)[:200]}...")
    elif isinstance(v, str) and not v:
        pass
    else:
        print(f"    {k}: {v}")

all_text = _collect_text(q3d, q3["grading_type"])
print(f"\n  总文本长度: {len(all_text.strip())} chars")
print(f"  文本预览: {all_text[:300]}")

# ============================================================
# STEP 3: 空判检查
# ============================================================
print(f"\n{'='*70}")
print(f"STEP 3: 空判检查")
print(f"{'='*70}")

is_empty = _is_truly_empty(q3d, q3["grading_type"])
print(f"  _is_truly_empty → {is_empty}")
has_media = (
    q3d.get("generated_images") or q3d.get("reference_image") or
    (q3d.get("has_video") and q3d.get("video_path")) or
    bool(q3d.get("bot_link") and "http" in str(q3d.get("bot_link", "")))
)
print(f"  has_media: {has_media}")
print(f"  has_video: {q3d.get('has_video')}")
print(f"  video_path: {q3d.get('video_path', '')[:100]}")
print(f"  video_info: {q3d.get('video_info', '')}")
print(f"  generated_images: {bool(q3d.get('generated_images'))}")
print(f"  has_screenshot: {q3d.get('has_screenshot')}")

# ============================================================
# STEP 4: 图片收集
# ============================================================
print(f"\n{'='*70}")
print(f"STEP 4: 图片收集（会传给视觉模型）")
print(f"{'='*70}")

images = _collect_images(q3d)
print(f"  收集到 {len(images)} 张图片:")
for i, img in enumerate(images):
    if os.path.exists(str(img)):
        size_kb = os.path.getsize(str(img)) / 1024
        print(f"    [{i}] {img} ({size_kb:.1f}KB)")
    else:
        print(f"    [{i}] {img} (不存在!)")

# ============================================================
# STEP 5: Prompt 构建
# ============================================================
print(f"\n{'='*70}")
print(f"STEP 5: LLM Prompt 展示")
print(f"{'='*70}")

content_desc = _build_content_desc(q3d, q3)
print(f"\n  content_desc ({len(content_desc)} chars):")
for line in content_desc.split("\n"):
    print(f"    {line[:150]}")

# 手动构建完整 prompt（和 _grade_llm 中一样）
criteria = q3["criteria"]
max_score = q3["max_score"]
description = q3.get("description", q3.get("name", ""))
criteria_text = "\n".join(
    f"  {i+1}. {c['name']}（{c['max']}分）：{c.get('desc','')}"
    for i, c in enumerate(criteria)
)

has_text = len(str(q3d.get("prompt_text", "")) + str(q3d.get("result_text", ""))) > 30
has_screenshot = q3d.get("has_screenshot", False)
has_images = bool(q3d.get("generated_images") or q3d.get("reference_image"))
has_video = bool(q3d.get("has_video") and q3d.get("video_path"))
has_excel = bool(q3d.get("excel_path"))
has_link = bool(q3d.get("bot_link") and "http" in str(q3d.get("bot_link", "")))
material_hints = []
if has_text: material_hints.append("有文字内容")
if has_screenshot: material_hints.append("有截图")
if has_images: material_hints.append("有生成图片")
if has_video: material_hints.append("有视频文件")
if has_excel: material_hints.append("有Excel文件")
if has_link: material_hints.append("有发布链接")

mode = (config.get("grading", {}) or {}).get("mode", "relaxed")
mode_map = {
    "relaxed": "【宽松模式】材料齐全且内容正确 = 满分。不要无故扣分。有明显问题才扣。",
    "normal": "【标准模式】材料齐全 = 满分。质量有瑕疵才扣分。",
    "strict": "【严格模式】只有确实优秀才满分。一般质量在70%-90%范围。",
}
mode_guidance = mode_map.get(mode, mode_map["relaxed"])

score_keys = "\n".join(f'  "得分_{c["id"]}_{c["name"]}": <int>,' for c in criteria)
prompt = f"""你是考试评分专家。根据题目要求和评分标准，对学生的提交内容打分。

题目：{q3['name']}（满分{max_score}分）
题目要求：{description[:800]}

评分标准：
{criteria_text}

{mode_guidance}

检测到的材料：{', '.join(material_hints) if material_hints else '无'}

学生提交内容：
{content_desc[:2000]}

输出 JSON（不要markdown）：
{{{{
  "档位判定": "<材料齐全/材料不足/敷衍/空>",
{score_keys}
  "总分": <int>,
  "评语": "<30字>"
}}}}

注意：材料齐全且内容正确即给满分，不要无故扣分。没提交的项给0分。"""

print(f"\n  === 完整 Prompt ({len(prompt)} chars) ===")
print(prompt[:3000])
if len(prompt) > 3000:
    print(f"  ... (截断，共{len(prompt)}字符)")

# ============================================================
# STEP 6: 模型路由信息
# ============================================================
print(f"\n{'='*70}")
print(f"STEP 6: 模型路由")
print(f"{'='*70}")

rc = router.get_router_config()
print(f"  vision_model: {rc['vision_model']}")
print(f"  high_value_threshold: {rc['high_value_threshold']}")
print(f"  high_value_model: {rc['high_value_model']}")
print(f"  vision_fallback: {rc['vision_fallback']}")
print(f"  Q3 max_score={max_score} → {'使用high_value_model' if max_score >= rc['high_value_threshold'] else '使用vision_model'}")

model_name, model_info = router.route_model("vision", max_score)
print(f"  实际路由到: {model_name}")
print(f"  模型信息: vision={model_info.get('vision')}, max_tokens={model_info.get('max_tokens')}")
print(f"  API Key 环境变量: {model_info.get('env_key')} = {'已设置' if os.environ.get(model_info.get('env_key','')) else '❌ 未设置!'}")

# ============================================================
# STEP 7: 实际 LLM 调用
# ============================================================
print(f"\n{'='*70}")
print(f"STEP 7: 实际 LLM 调用")
print(f"{'='*70}")

has_key = (
    os.environ.get("ZHIPU_KEY", "") or
    os.environ.get("DEEPSEEK_KEY", "") or
    os.environ.get("OPENAI_API_KEY", "") or
    os.environ.get("ANTHROPIC_API_KEY", "") or
    os.environ.get("BAILIAN_KEY", "")
)
if not has_key:
    print("  ❌ 未配置任何 API Key！请在环境变量中设置 Key。")
    print("     运行: set ZHIPU_KEY=你的智谱API_KEY")
else:
    print(f"  ✅ 检测到 API Key 配置")

    try:
        llm_result = router.call_model(
            prompt=prompt,
            task_type="vision",
            images=images,
            question_score=max_score,
            temperature=0.3,
            max_tokens=2048,
        )
        print(f"\n  模型: {llm_result['model_used']}")
        print(f"  tokens: {llm_result['tokens_in']}入 / {llm_result['tokens_out']}出")
        print(f"\n  === LLM 原始返回 ===")
        print(llm_result['content'])
        print(f"  === 原始返回结束 ===")

        # 尝试解析
        from src.grader import _parse_json
        parsed = _parse_json(llm_result['content'])
        print(f"\n  === JSON 解析结果 ===")
        print(json.dumps(parsed, ensure_ascii=False, indent=2))

        # 检查各维度得分
        if "parse_error" in parsed:
            print(f"\n  ❌ JSON 解析失败！这是0分的原因！")
        else:
            total_llm = sum(
                parsed.get(f"得分_{c['id']}_{c['name']}", 0)
                for c in criteria
            )
            print(f"\n  LLM 返回总分: {parsed.get('总分', '?')} (计算值: {total_llm})")

            # 后处理模拟
            if has_video and q3.get("grading_type") == "vision":
                print(f"\n  === 后处理（有视频的vision题自动给满分项） ===")
                for c in criteria:
                    name = c.get("name", "")
                    key = f"得分_{c['id']}_{name}"
                    old_val = parsed.get(key, 0)
                    if any(kw in name for kw in ["服饰", "背景", "配音", "音乐", "音效", "音频", "整体效果"]):
                        parsed[key] = c["max"]
                        print(f"    {key}: {old_val} → {c['max']} (后处理满分)")
                    else:
                        print(f"    {key}: {old_val} (保持不变)")

                total_after = sum(
                    parsed.get(f"得分_{c['id']}_{c['name']}", 0)
                    for c in criteria
                )
                print(f"\n  后处理后总分: {total_after}/{max_score}")

    except Exception as e:
        import traceback
        print(f"\n  ❌ LLM 调用异常: {e}")
        traceback.print_exc()

# ============================================================
# STEP 8: 完整 grade() 调用
# ============================================================
print(f"\n{'='*70}")
print(f"STEP 8: 完整 grade() 调用结果")
print(f"{'='*70}")

try:
    result = grade(q3d, q3, config)
    print(f"  总分: {result.get('总分', '?')}/{max_score}")
    print(f"  评语: {result.get('评语', '')}")
    print(f"  切题判断: {result.get('切题判断', '')}")
    print(f"  raw_response: {result.get('raw_response', '')[:300]}")
    print(f"  使用模型: {result.get('_model_used', '?')}")
    print(f"\n  各维度得分:")
    for c in criteria:
        key = f"得分_{c['id']}_{c['name']}"
        print(f"    {c['name']}: {result.get(key, 0)}/{c['max']}")
except Exception as e:
    import traceback
    print(f"  ❌ 评分异常: {e}")
    traceback.print_exc()

print(f"\n{'='*70}")
print(f"  诊断完成")
print(f"{'='*70}")
