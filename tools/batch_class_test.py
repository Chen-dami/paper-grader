"""Batch test a class with one strategy."""
import sys, os, yaml, glob, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.extractor import extract
from src.preprocessor import process
from src.utils import load_rubric
from src.grader import grade, _is_truly_empty, _should_use_vision

parser = argparse.ArgumentParser()
parser.add_argument("class_dir")
parser.add_argument("--strategy", default="text_only")
parser.add_argument("--limit", type=int, default=0, help="Max papers (0=all)")
parser.add_argument("--ids", default="", help="Comma-separated student IDs to test")
args = parser.parse_args()

with open("config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
rubric = load_rubric("data/rubric.json")
config = {"vision_strategy": args.strategy, "grading": cfg.get("grading",{}),
          "image": cfg.get("image",{}), "model_router": cfg.get("model_router",{})}
target_ids = set(args.ids.split(",")) if args.ids else None

strategy = args.strategy
papers = []
for entry in sorted(os.listdir(args.class_dir)):
    full = os.path.join(args.class_dir, entry)
    if not os.path.isdir(full): continue
    docx_files = glob.glob(os.path.join(full, "*.docx"))
    if not docx_files: continue
    sid = entry.split('-')[0] if '-' in entry else entry  # 取-前的数字
    # 如果全是数字直接当学号；否则取前缀数字部分
    if not sid.isdigit():
        import re
        m = re.match(r'(\d+)', entry)
        sid = m.group(1) if m else entry[:12]
    name = entry[len(sid):].lstrip('-') if entry.startswith(sid) else entry
    if target_ids and sid not in target_ids: continue
    papers.append((docx_files[0], name, sid))

if args.limit > 0:
    papers = papers[:args.limit]

print(f"Strategy: {strategy} | Papers: {len(papers)}")
print(f"{'='*70}")

all_results = []
for docx, name, sid in papers:
    try:
        paper = extract(docx, "output/test")
        clean = process(paper, rubric, config)
    except Exception as e:
        print(f"  {name}: EXTRACT ERROR {e}")
        continue

    scores = {}
    total = 0
    details = []
    for q in rubric["questions"]:
        qk = f"q{q['id']}"
        qd = clean.get(qk, {})
        gtype = q.get("grading_type", "text")
        try:
            r = grade(qd, q, config)
            score = r.get("总分", 0)
            total += score
            scores[f"q{q['id']}"] = score
            details.append(f"Q{q['id']}={score}/{q['max_score']}")
        except Exception as e:
            scores[f"q{q['id']}"] = 0
            details.append(f"Q{q['id']}=ERR")

    print(f"  {name:<8} {total:>3}/100  {' | '.join(details)}")
    all_results.append({"name": name, "id": sid, "total": total, "scores": scores})

# Stats
if all_results:
    totals = [r["total"] for r in all_results]
    print(f"\n  Avg: {sum(totals)/len(totals):.0f}  Min: {min(totals)}  Max: {max(totals)}  Spread: {max(totals)-min(totals)}")
    # Score distribution
    buckets = {"90+": 0, "80-89": 0, "70-79": 0, "60-69": 0, "<60": 0}
    for t in totals:
        if t >= 90: buckets["90+"] += 1
        elif t >= 80: buckets["80-89"] += 1
        elif t >= 70: buckets["70-79"] += 1
        elif t >= 60: buckets["60-69"] += 1
        else: buckets["<60"] += 1
    print(f"  Dist: {' | '.join(f'{k}:{v}' for k,v in buckets.items())}")
