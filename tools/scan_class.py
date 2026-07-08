"""Scan an entire class directory — extraction summary only (no LLM)."""
import sys, os, yaml, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.extractor import extract
from src.preprocessor import process
from src.utils import load_rubric
from src.grader import _is_truly_empty, _should_use_vision

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("class_dir", help="Path to class directory")
args = parser.parse_args()

with open("config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
rubric = load_rubric("data/rubric.json")

class_dir = args.class_dir
class_name = os.path.basename(class_dir)

print(f"Class: {class_name}")
print(f"{'='*80}")

results = []
for entry in sorted(os.listdir(class_dir)):
    full = os.path.join(class_dir, entry)
    if not os.path.isdir(full):
        continue
    docx_files = glob.glob(os.path.join(full, "*.docx"))
    if not docx_files:
        continue

    docx = docx_files[0]
    folder_name = entry
    student_id = folder_name[:10] if len(folder_name) >= 10 else folder_name
    student_name = folder_name[10:] if len(folder_name) > 10 else ""

    try:
        config = {'vision_strategy': 'text_only', 'grading': cfg.get('grading',{}),
                  'image': cfg.get('image',{}), 'model_router': cfg.get('model_router',{})}
        paper = extract(docx, "output/test")
        clean = process(paper, rubric, config)

        row = {"name": student_name, "id": student_id, "folder": folder_name}
        for q in rubric["questions"]:
            qk = f"q{q['id']}"
            qd = clean.get(qk, {})
            gtype = q.get("grading_type", "text")
            row[f"q{q['id']}_empty"] = _is_truly_empty(qd, gtype, "text_only")
            row[f"q{q['id']}_scr"] = qd.get("has_screenshot", False)
            row[f"q{q['id']}_imgs"] = len(qd.get("generated_images", []))
            row[f"q{q['id']}_vid"] = qd.get("has_video", False)
            row[f"q{q['id']}_xls"] = qd.get("has_excel_file", False)
            row[f"q{q['id']}_link"] = bool(qd.get("bot_link"))
            row[f"q{q['id']}_prompt"] = len(str(qd.get("prompt_text", "")))
            row[f"q{q['id']}_persona"] = len(str(qd.get("persona_text", "")))
            row[f"q{q['id']}_table"] = len(str(qd.get("all_table_text", "")))
        results.append(row)

        # One-line summary
        empty_qs = [str(q['id']) for q in rubric['questions'] if row.get(f"q{q['id']}_empty")]
        empty_str = f" EMPTY: Q{','.join(empty_qs)}" if empty_qs else ""
        materials = []
        for q in rubric['questions']:
            qid = q['id']
            m = []
            if row[f"q{qid}_scr"]: m.append("scr")
            if row[f"q{qid}_vid"]: m.append("vid")
            if row[f"q{qid}_xls"]: m.append("xls")
            if row[f"q{qid}_link"]: m.append("link")
            if row[f"q{qid}_prompt"] > 20: m.append(f"prompt{row[f'q{qid}_prompt']}")
            if row[f"q{qid}_persona"] > 20: m.append(f"persona{row[f'q{qid}_persona']}")
            materials.append(f"Q{qid}:{','.join(m) if m else '-'}")
        print(f"{student_name:<6} | {' | '.join(materials)}{empty_str}")
    except Exception as e:
        print(f"{entry}: ERROR - {e}")

# Summary stats
print(f"\n{'='*80}")
print(f"Summary: {len(results)} papers scanned")
if results:
    # Count empty questions
    for qid in [1,2,3,4,5]:
        empty_count = sum(1 for r in results if r.get(f"q{qid}_empty"))
        print(f"  Q{qid} empty: {empty_count}/{len(results)}")
