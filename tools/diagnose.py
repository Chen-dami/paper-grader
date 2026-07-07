"""
诊断脚本：展示提取→预处理→档位→评分的完整链路
包括 LLM 视觉评分返回的原始内容（如 API Key 可用）
"""
import os, sys, json, base64, io
# 强制 UTF-8 输出避免 Windows GBK 乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.extractor import extract
from src.preprocessor import process
from src.grader import (
    grade, _detect_tier, _get_tier_config_extended,
    _grade_code, _grade_llm, _build_llm_prompt_v2,
    _build_content_desc, _collect_images, _build_rule_context,
    _collect_text, _run_data_checks_structured,
)
from src import model_router as router
from src.utils import load_rubric, load_config

# 不用 Streamlit 的 session_state
config = load_config("config.yaml")
rubric = load_rubric("data/rubric.json")

# 找一份真实试卷
PAPER_PATH = r"data\papers\电商2501\255102030101_李杰鸿\255102030101李杰鸿.docx"
if not os.path.exists(PAPER_PATH):
    # 兜底
    for root, dirs, files in os.walk("data/papers"):
        for f in files:
            if f.endswith(".docx") and not f.startswith("~$"):
                PAPER_PATH = os.path.join(root, f)
                break
        else:
            continue
        break

print("=" * 70)
print("  诊断脚本 -- 完整评分链路追踪")
print("=" * 70)

# ============================================================
# STEP 1: 文档提取
# ============================================================
print(f"\n{'='*70}")
print(f"STEP 1: 文档提取")
print(f"文件: {PAPER_PATH}")
print(f"{'='*70}")

paper = extract(PAPER_PATH, output_dir="output")
print(f"  学生: {paper['student_info']}")
print(f"  段落数: {len(paper['paragraphs'])}")
print(f"  表格数: {len(paper['tables'])}")
for ti, t in enumerate(paper['tables']):
    print(f"    表格{ti}: {len(t)}行 × {len(t[0]) if t else 0}列")
    for ri, row in enumerate(t[:5]):  # 前5行
        print(f"      row{ri}: {[str(c)[:50] for c in row]}")
    if len(t) > 5:
        print(f"      ... (共{len(t)}行)")

print(f"  图片数: {len(paper['images'])}")
for img in paper['images'][:5]:
    print(f"    {img[0]} | {img[1]}x{img[2]} | {img[3]}bytes")

print(f"  嵌入文件数: {len(paper['embedded_files'])}")
for ef in paper['embedded_files']:
    print(f"    {ef[0]} ({ef[1]})")

# ============================================================
# STEP 2: 预处理
# ============================================================
print(f"\n{'='*70}")
print(f"STEP 2: 预处理 → 题目匹配 + 字段提取")
print(f"{'='*70}")

preprocessed = process(paper, rubric, config)
print(f"  学生: {preprocessed['student']}")
print(f"  图片(缩略后): {len(preprocessed['all_images'])} 张")

for q in rubric["questions"]:
    qid = q["id"]
    qd = preprocessed.get(f"q{qid}", {})
    print(f"\n  ┌─ Q{qid} [{q['name']}] ({q['grading_type']})")
    for k, v in qd.items():
        if k == "generated_images":
            print(f"  │ generated_images: {len(v) if isinstance(v, list) else v} 张")
        elif isinstance(v, str) and len(str(v)) > 100:
            print(f"  │ {k}: {str(v)[:80]}...")
        elif isinstance(v, str) and not v:
            pass  # 跳过空字段
        else:
            print(f"  │ {k}: {v}")
    print(f"  └─ 总文本: {len(_collect_text(qd, q['grading_type']))} chars")

# ============================================================
# STEP 3: 档位检测
# ============================================================
print(f"\n{'='*70}")
print(f"STEP 3: 档位检测")
print(f"{'='*70}")

for q in rubric["questions"]:
    qid = q["id"]
    gtype = q["grading_type"]
    qd = preprocessed.get(f"q{qid}", {})

    # 客观题跳过档位
    if gtype in ("multiple_choice", "true_false", "fill_blank", "short_answer"):
        print(f"\n  Q{qid} [{q['name']}] → {gtype} (客观题，跳过档位)")
        continue

    tier = _detect_tier(qd, q, config)
    tc = _get_tier_config_extended(tier, config)
    ratio = f"{tc['ratio_min']*100:.0f}% ~ {tc['ratio_max']*100:.0f}%"
    all_text = _collect_text(qd, gtype)

    print(f"\n  Q{qid} [{q['name']}] ({gtype})")
    print(f"    文本长度: {len(all_text.strip())} chars")
    print(f"    有截图: {qd.get('has_screenshot')}")
    print(f"    有视频: {qd.get('has_video')}, 路径: {qd.get('video_path','')[:50]}")
    print(f"    有图: {bool(qd.get('generated_images'))}")
    print(f"    有Excel: {bool(qd.get('excel_path'))}")
    print(f"    有链接: {bool(qd.get('bot_link'))}")
    print(f"    ↓ 判定档位: 【{tier}】")
    print(f"      得分范围: {ratio} (满分{int(q['max_score'])} → {int(q['max_score']*tc['ratio_min'])}~{int(q['max_score']*tc['ratio_max'])}分)")
    print(f"      temperature: {tc.get('temperature')}, 粒度: {tc.get('granularity')}, 评语风格: {tc.get('feedback_style')}")
    print(f"      指引: {tc.get('emphasis','')[:80]}")

# ============================================================
# STEP 4: Q4 数据处理规则引擎演示
# ============================================================
print(f"\n{'='*70}")
print(f"STEP 4: Q4 数据处理 — 规则引擎详情")
print(f"{'='*70}")

q4 = [q for q in rubric["questions"] if q["id"] == 4][0]
q4d = preprocessed.get("q4", {})
excel_path = q4d.get("excel_path", "")
print(f"  Excel 路径: {excel_path}")
print(f"  有截图: {q4d.get('has_screenshot')}")

if excel_path and os.path.exists(excel_path):
    import pandas as pd
    df = pd.read_excel(excel_path)
    print(f"\n  原始数据 ({len(df)}行 × {len(df.columns)}列):")
    print(f"  列名: {list(df.columns)}")
    print(df.to_string(max_rows=15))

    print(f"\n  ── 规则引擎执行 ──")
    print(f"  data_checks 配置: {json.dumps(q4['data_checks'], ensure_ascii=False, indent=4)}")

    scores, reasons, rule_results = _run_data_checks_structured(df, q4["criteria"], q4["data_checks"])

    for r in rule_results:
        icon = {"pass": "[OK]", "warn": "[WARN]", "fail": "[FAIL]"}.get(r['status'], '?')
        print(f"  {icon} {r['check']}: {r['detail']}")

    print(f"\n  评分结果:")
    for c in q4["criteria"]:
        print(f"    {c['name']}(max={c['max']}): 得分={scores.get(c['id'],0)}, 原因={reasons.get(c['id'],'')}")

    # 构建注入 LLM 的规则上下文
    q4d_copy = q4d.copy()
    q4d_copy["_rule_results"] = rule_results
    rule_ctx = _build_rule_context(q4d_copy, q4)
    print(f"\n  ── 注入 LLM prompt 的规则上下文 ──")
    print(rule_ctx)

    # 模拟完整评分结果
    tier4 = _detect_tier(q4d, q4, config)
    print(f"\n  档位: {tier4}")
    result4 = _grade_code(q4d, q4, config)
    print(f"  最终总分: {result4['总分']}/{q4['max_score']}")
    print(f"  评语: {result4['评语']}")
else:
    print("  ⚠️ 未找到 Excel 文件，将用截图给基础分模式")
    tier4 = _detect_tier(q4d, q4, config)
    result4 = _grade_code(q4d, q4, config)
    print(f"  档位: {tier4}")
    print(f"  最终总分: {result4['总分']}/{q4['max_score']}")
    print(f"  评语: {result4['评语']}")

# ============================================================
# STEP 5: LLM prompt 展示（不实际调用，展示发送给 AI 的内容）
# ============================================================
print(f"\n{'='*70}")
print(f"STEP 5: LLM Prompt 展示（发送给 AI 的评分指令）")
print(f"{'='*70}")

# Q2 vision 题 prompt
q2 = [q for q in rubric["questions"] if q["id"] == 2][0]
q2d = preprocessed.get("q2", {})
tier2 = _detect_tier(q2d, q2, config)
tc2 = _get_tier_config_extended(tier2, config)
content_desc2 = _build_content_desc(q2d, q2)
images2 = _collect_images(q2d)

prompt2 = _build_llm_prompt_v2(
    q2, q2["criteria"], tier2, tc2,
    tc2["ratio_min"], tc2["ratio_max"],
    content_desc2, "", q2["max_score"]
)

print(f"\n  ┌─ Q2 图像设计 (vision) LLM Prompt ─────────────────────")
print(f"  │ 档位: {tier2}")
print(f"  │ 图片数: {len(images2)}")
for img in images2[:3]:
    size_kb = os.path.getsize(img) / 1024 if os.path.exists(str(img)) else 0
    print(f"  │   → {img} ({size_kb:.1f} KB)")
print(f"  └{'─'*60}")
for line in prompt2.split("\n")[:35]:
    print(f"  │ {line}")
print(f"  │ ... (共{len(prompt2)}字符)")

# Q1 text 题 prompt
q1 = [q for q in rubric["questions"] if q["id"] == 1][0]
q1d = preprocessed.get("q1", {})
tier1 = _detect_tier(q1d, q1, config)
tc1 = _get_tier_config_extended(tier1, config)
content_desc1 = _build_content_desc(q1d, q1)

prompt1 = _build_llm_prompt_v2(
    q1, q1["criteria"], tier1, tc1,
    tc1["ratio_min"], tc1["ratio_max"],
    content_desc1, "", q1["max_score"]
)

print(f"\n  ┌─ Q1 文本生成 (text) LLM Prompt ────────────────────────")
print(f"  │ 档位: {tier1}")
print(f"  └{'─'*60}")
for line in prompt1.split("\n")[:30]:
    print(f"  │ {line}")
print(f"  │ ... (共{len(prompt1)}字符)")

# ============================================================
# STEP 6: 尝试真实 LLM 调用（如果 API Key 有配置）
# ============================================================
print(f"\n{'='*70}")
print(f"STEP 6: 尝试真实 LLM 调用")
print(f"{'='*70}")

api_key = config.get("llm", {}).get("api_key", "") or os.environ.get("DEEPSEEK_KEY", "")
if not api_key:
    print("  ⚠️ 未配置 API Key，跳过实际 LLM 调用。")
    print("  设置: set DEEPSEEK_KEY=sk-xxx")
else:
    print(f"  ✅ API Key 已配置 ({api_key[:10]}...)")

    # 先尝试调用 Q1（文本题）
    print(f"\n  ── Q1 文本生成 实际评分 ──")
    try:
        result_text = router.call_model(prompt1, task_type="text", question_score=q1["max_score"])
        print(f"  模型: {result_text['model_used']}")
        print(f"  tokens: {result_text['tokens_in']}入 / {result_text['tokens_out']}出")
        print(f"  原始返回:")
        print(f"  {result_text['content'][:500]}")
    except Exception as e:
        print(f"  ❌ 调用失败: {e}")

    # 尝试调用 Q2（视觉题），如果有图片
    if images2:
        print(f"\n  ── Q2 图像设计 视觉评分 ──")
        try:
            result_vision = router.call_model(
                prompt2, task_type="vision", images=images2[:5],
                question_score=q2["max_score"]
            )
            print(f"  模型: {result_vision['model_used']}")
            print(f"  tokens: {result_vision['tokens_in']}入 / {result_vision['tokens_out']}出")
            print(f"  原始返回:")
            print(f"  {result_vision['content'][:500]}")
        except Exception as e:
            print(f"  ❌ 视觉调用失败 (可能当前模型不支持): {e}")

print(f"\n{'='*70}")
print(f"  诊断完成")
print(f"{'='*70}")
