"""Batch debug_grade on both problematic papers with text_only strategy."""
import sys, os, json, yaml
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.extractor import extract
from src.preprocessor import process
from src.utils import load_rubric
from src.grader import grade, _should_use_vision, _is_truly_empty

PAPERS = [
    r"C:\baidunetdiskdownload\dome2401\255307010103吉才创\255307010103吉才创.docx",
    r"C:\baidunetdiskdownload\dome2401\255307010102桂忠豪\255307010102桂忠豪.docx",
]
STRATEGY = "text_only"

with open("config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
rubric = load_rubric("data/rubric.json")
config = {
    "vision_strategy": STRATEGY,
    "grading": cfg.get("grading", {}),
    "image": cfg.get("image", {}),
    "model_router": cfg.get("model_router", {}),
}

for docx_path in PAPERS:
    name = os.path.basename(os.path.dirname(docx_path))
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")

    paper = extract(docx_path, "output/debug_trace")
    clean = process(paper, rubric, config)
    print(f"  表格:{len(paper['tables'])}  图片:{len(paper['images'])}  嵌入:{len(paper['embedded_files'])}")

    # Critical checks first
    print(f"\n  [关键判断]")
    for q in rubric["questions"]:
        qk = f"q{q['id']}"
        qd = clean.get(qk, {})
        gtype = q.get("grading_type", "text")
        is_empty = _is_truly_empty(qd, gtype, STRATEGY)
        use_vis = _should_use_vision(gtype, config)
        scr = qd.get("has_screenshot", False)
        vid = qd.get("has_video", False)
        xls = qd.get("has_excel_file", False)
        link = "Y" if qd.get("bot_link") else "N"
        persona = len(str(qd.get("persona_text", "")))
        prompt = len(str(qd.get("prompt_text", "")))
        print(f"  Q{q['id']} {q['name']:<8s} empty={is_empty} | scr={scr} vid={vid} xls={xls} link={link} | prompt={prompt}字 persona={persona}字 | vision={use_vis}")

    # Full grading
    print(f"\n  [评分结果]")
    import src.model_router as router
    original_call = router.call_model
    captured = []

    def debug_call(prompt, **kw):
        captured.append(prompt)
        return original_call(prompt=prompt, **kw)

    router.call_model = debug_call
    total = 0
    try:
        for q in rubric["questions"]:
            qk = f"q{q['id']}"
            qd = clean.get(qk, {})
            r = grade(qd, q, config)
            score = r.get("总分", 0)
            total += score
            details = " | ".join(f"{c['name']}={r.get(f'得分_{c[\"id\"]}_{c[\"name\"]}', '?')}/{c['max']}" for c in q["criteria"])
            print(f"  Q{q['id']} {q['name']}: {score}/{q['max_score']}  [{details}]")
            # Show key parts of prompt
            if captured:
                p = captured[-1]
                # Find tier decision
                for line in p.split("\n"):
                    if "档位" in line or "空" == line.strip()[:1] or "is_empty" in line.lower():
                        print(f"       > {line.strip()[:200]}")
    finally:
        router.call_model = original_call
    print(f"  >>> 总分: {total}/100")
