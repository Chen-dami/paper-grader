"""Batch grade all 5 papers with paid_vision strategy (5 images)."""
import sys, os, json, yaml
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.extractor import extract
from src.preprocessor import process
from src.utils import load_rubric
from src.grader import grade, _should_use_vision, _is_truly_empty

PAPERS = [
    (r"C:\baidunetdiskdownload\dome2401\216102050204崔宗岳\216102050204崔宗岳.docx", "崔宗岳"),
    (r"C:\baidunetdiskdownload\dome2401\255307010101刘伟宇\255307010101刘伟宇.docx", "刘伟宇"),
    (r"C:\baidunetdiskdownload\dome2401\255307010102桂忠豪\255307010102桂忠豪.docx", "桂忠豪"),
    (r"C:\baidunetdiskdownload\dome2401\255307010103吉才创\255307010103吉才创.docx", "吉才创"),
    (r"C:\baidunetdiskdownload\dome2401\255307010104彭炫桢\255307010104彭炫桢.docx", "彭炫桢"),
]

STRATEGY = "paid_vision"

with open("config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
rubric = load_rubric("data/rubric.json")
config = {
    "vision_strategy": STRATEGY,
    "grading": cfg.get("grading", {}),
    "image": cfg.get("image", {}),
    "model_router": cfg.get("model_router", {}),
}

print(f"Strategy: {STRATEGY} | Vision model: {cfg['model_router']['vision_model']}")
print(f"{'='*70}")

results = {}

for docx_path, name in PAPERS:
    print(f"\n--- {name} ---")
    try:
        paper = extract(docx_path, "output/test")
        clean = process(paper, rubric, config)
    except Exception as e:
        print(f"  EXTRACT ERROR: {e}")
        continue

    scores = {}
    total = 0
    for q in rubric["questions"]:
        qk = f"q{q['id']}"
        qd = clean.get(qk, {})
        gtype = q.get("grading_type", "text")
        is_empty = _is_truly_empty(qd, gtype, STRATEGY)
        use_vis = _should_use_vision(gtype, config)
        imgs = len(qd.get("generated_images", []))

        try:
            r = grade(qd, q, config)
            score = r.get("总分", 0)
            total += score
            model = r.get("_model_used", "?")
            vis_note = f"vis={use_vis} imgs={imgs}" if use_vis else ""
            parts = []
            for c in q["criteria"]:
                key = "得分_" + c["id"] + "_" + c["name"]
                parts.append(c["name"] + "=" + str(r.get(key, "?")) + "/" + str(c["max"]))
            details = " | ".join(parts)
            print(f"  Q{q['id']} {q['name']:<8s} {score:>2}/{q['max_score']:<2} empty={is_empty} {vis_note} [{model}]")
            print(f"         {details}")
            scores[f"q{q['id']}"] = score
        except Exception as e:
            print(f"  Q{q['id']} ERROR: {e}")
            scores[f"q{q['id']}"] = 0

    print(f"  >>> {name}: {total}/100")
    results[name] = {"total": total, "scores": scores}

# Final comparison table
print(f"\n{'='*80}")
print(f"  PAID VISION ({STRATEGY}) - FINAL RESULTS")
print(f"{'='*80}")
print(f"{'Student':<8} {'Q1':>4} {'Q2':>4} {'Q3':>4} {'Q4':>4} {'Q5':>4} {'TOTAL':>6}")
print("-" * 42)
for name, data in results.items():
    s = data["scores"]
    print(f"{name:<8} {s.get('q1',0):>4} {s.get('q2',0):>4} {s.get('q3',0):>4} {s.get('q4',0):>4} {s.get('q5',0):>4} {data['total']:>6}")
