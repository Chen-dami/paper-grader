"""Batch grade all 5 papers with free_vision strategy."""
import sys, os, json, yaml, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.extractor import extract
from src.preprocessor import process
from src.utils import load_rubric
from src.grader import grade, _should_use_vision, _is_truly_empty
from src.grader_strategies import apply_strategy

PAPERS = [
    r"C:\baidunetdiskdownload\dome2401\216102050204崔宗岳\216102050204崔宗岳.docx",
    r"C:\baidunetdiskdownload\dome2401\255307010101刘伟宇\255307010101刘伟宇.docx",
    r"C:\baidunetdiskdownload\dome2401\255307010102桂忠豪\255307010102桂忠豪.docx",
    r"C:\baidunetdiskdownload\dome2401\255307010103吉才创\255307010103吉才创.docx",
    r"C:\baidunetdiskdownload\dome2401\255307010104彭炫桢\255307010104彭炫桢.docx",
]

STRATEGY = "free_vision"

with open("config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
rubric = load_rubric("data/rubric.json")
config = {
    "vision_strategy": STRATEGY,
    "grading": cfg.get("grading", {}),
    "image": cfg.get("image", {}),
    "model_router": cfg.get("model_router", {}),
}

results = {}

for docx_path in PAPERS:
    folder = os.path.basename(os.path.dirname(docx_path))
    name = folder[11:] if len(folder) > 11 else folder  # strip student ID prefix
    sid = folder[:10] if len(folder) >= 10 else folder

    print(f"\n{'='*60}")
    print(f"  {name} ({sid})")
    print(f"{'='*60}")

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

        # Vision questions: show image info
        imgs = qd.get("generated_images", [])
        img_info = ""
        if use_vis and imgs:
            # describe_images will limit to 1 image for free_vision
            img_info = f" ({len(imgs)} images available, vision will see 1)"

        try:
            r = grade(qd, q, config)
            score = r.get("总分", 0)
            total += score
            model = r.get("_model_used", "?")
            tier = r.get("tier", "?")
            parts = []
            for c in q["criteria"]:
                key = "得分_" + c["id"] + "_" + c["name"]
                parts.append(c["name"] + "=" + str(r.get(key, "?")) + "/" + str(c["max"]))
            details = " | ".join(parts)
            print(f"  Q{q['id']} {q['name']:<8s} {score:>2}/{q['max_score']:<2} [{model}] empty={is_empty} vis={use_vis}{img_info}")
            print(f"         {details}")
            scores[f"q{q['id']}"] = score
        except Exception as e:
            print(f"  Q{q['id']} {q['name']:<8s} ERROR: {e}")
            scores[f"q{q['id']}"] = 0

    print(f"  >>> TOTAL: {total}/100")
    results[name] = {"total": total, "scores": scores}

# Summary
print(f"\n{'='*70}")
print(f"  FREE VISION ({STRATEGY}) - FINAL SUMMARY")
print(f"{'='*70}")
header = f"{'Student':<12} {'Q1':>4} {'Q2':>4} {'Q3':>4} {'Q4':>4} {'Q5':>4} {'TOTAL':>6}"
print(header)
print("-" * len(header))
for name, data in results.items():
    s = data["scores"]
    print(f"{name:<12} {s.get('q1',0):>4} {s.get('q2',0):>4} {s.get('q3',0):>4} {s.get('q4',0):>4} {s.get('q5',0):>4} {data['total']:>6}")
