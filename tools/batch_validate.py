"""Batch validation — extraction + judgment only (no LLM calls)."""
import sys, os, json, yaml, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.extractor import extract
from src.preprocessor import process
from src.utils import load_rubric
from src.grader import _should_use_vision, _is_truly_empty
from src.grader import _build_content_desc, _detect_tier

PAPERS = [
    r"C:\baidunetdiskdownload\dome2401\216102050204崔宗岳\216102050204崔宗岳.docx",
    r"C:\baidunetdiskdownload\dome2401\255307010101刘伟宇\255307010101刘伟宇.docx",
    r"C:\baidunetdiskdownload\dome2401\255307010102桂忠豪\255307010102桂忠豪.docx",
    r"C:\baidunetdiskdownload\dome2401\255307010103吉才创\255307010103吉才创.docx",
    r"C:\baidunetdiskdownload\dome2401\255307010104彭炫桢\255307010104彭炫桢.docx",
]

with open("config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
rubric = load_rubric("data/rubric.json")

for strategy in ["text_only", "paid_vision"]:
    config = {
        "vision_strategy": strategy,
        "grading": cfg.get("grading", {}),
        "image": cfg.get("image", {}),
        "model_router": cfg.get("model_router", {}),
    }
    print(f"\n{'#'*80}")
    print(f"#  策略: {strategy}")
    print(f"{'#'*80}")

    for docx_path in PAPERS:
        name = os.path.basename(os.path.dirname(docx_path))
        paper = extract(docx_path, "output/test")
        clean = process(paper, rubric, config)
        print(f"\n  {'─'*50}")
        print(f"  {name}")
        print(f"  {'─'*50}")

        for q in rubric["questions"]:
            qk = f"q{q['id']}"
            qd = clean.get(qk, {})
            gtype = q.get("grading_type", "text")

            # Core judgments
            is_empty = _is_truly_empty(qd, gtype, strategy)
            use_vis = _should_use_vision(gtype, config)
            content = _build_content_desc(qd, q)

            # Material detection
            scr = qd.get("has_screenshot", False)
            vid = qd.get("has_video", False)
            xls = qd.get("has_excel_file", False)
            link = bool(qd.get("bot_link"))
            link_ok = qd.get("link_reachable", None)

            # Tier detection
            tier = _detect_tier(qd, q, config)

            persona = len(str(qd.get("persona_text", "")))
            prompt = len(str(qd.get("prompt_text", "")))

            status = []
            if is_empty: status.append("EMPTY")
            if scr: status.append("SCR")
            if vid: status.append("VID")
            if xls: status.append("XLS")
            if link: status.append(f"LINK({'OK' if link_ok else '?' if link_ok is None else 'DEAD'})")
            if not status: status.append("NO_MATERIAL")

            print(f"  Q{q['id']} {q['name']:<8s} | {' '.join(status):<25s} | tier={tier:<15s} | empty={is_empty} vis={use_vis} | prompt={prompt}字 persona={persona}字")
