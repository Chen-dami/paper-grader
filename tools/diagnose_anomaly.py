"""Diagnose suspicious scores without LLM calls — just show extraction + prompt."""
import sys, os, yaml
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.extractor import extract
from src.preprocessor import process
from src.utils import load_rubric
from src.grader import _build_content_desc, _build_rule_context, _is_truly_empty, _should_use_vision
from src.grader_strategies import apply_strategy
import src.model_router as router

with open("config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
rubric = load_rubric("data/rubric.json")

# 张玉婷 Q2 anomaly
BASE = r"C:\baidunetdiskdownload\软件2501"
student = "255102030102张玉婷"
docx = os.path.join(BASE, student, student + ".docx")

config = {"vision_strategy": "text_only", "grading": cfg.get("grading",{}),
          "image": cfg.get("image",{}), "model_router": cfg.get("model_router",{})}
paper = extract(docx, "output/test")
clean = process(paper, rubric, config)

for q in rubric["questions"]:
    qk = f"q{q['id']}"
    qd = clean.get(qk, {})
    gtype = q.get("grading_type", "text")
    is_empty = _is_truly_empty(qd, gtype, "text_only")

    print(f"\n{'='*60}")
    print(f"Q{q['id']} {q['name']} ({q['max_score']}分) [{gtype}] empty={is_empty}")
    print(f"{'='*60}")

    # Show extracted data (safe encoding)
    def safe_str(s, n=200):
        r = str(s)[:n]
        return r.encode('ascii', errors='replace').decode('ascii')
    for key in ["prompt_text", "result_text", "persona_text"]:
        val = str(qd.get(key, ""))
        if val.strip():
            print(f"  {key}: {len(val)}字 -> {safe_str(val)}")
        else:
            print(f"  {key}: 空")
    print(f"  all_table_text: {len(str(qd.get('all_table_text','')))}字")
    print(f"  has_screenshot: {qd.get('has_screenshot')}")
    print(f"  generated_images: {len(qd.get('generated_images',[]))}")
    print(f"  has_video: {qd.get('has_video')} path: {bool(qd.get('video_path'))}")
    print(f"  has_excel: {qd.get('has_excel_file')}")
    print(f"  bot_link: '{qd.get('bot_link','')[:100]}'")

    # Show content_desc (what LLM sees)
    desc = _build_content_desc(qd, q)
    print(f"\n  [LLM sees - content_desc ({len(desc)}字)]:")
    for line in desc.split("\n")[:12]:
        print(f"    {safe_str(line, 150)}")

    # Show rule context
    ctx = _build_rule_context(qd, q)
    if ctx:
        print(f"\n  [rule_ctx ({len(ctx)}字)]: {safe_str(ctx, 300)}")
