"""Quick scan all 5 papers — extraction data summary."""
import sys, os, json, yaml, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.extractor import extract
from src.preprocessor import process
from src.utils import load_rubric

BASE = r"C:\baidunetdiskdownload\dome2401"

with open("config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

rubric = load_rubric("data/rubric.json")
config = {
    "vision_strategy": "text_only",
    "grading": cfg.get("grading", {}),
    "image": cfg.get("image", {}),
    "model_router": cfg.get("model_router", {}),
}

for folder in sorted(os.listdir(BASE)):
    full = os.path.join(BASE, folder)
    if not os.path.isdir(full):
        continue
    docx_files = glob.glob(os.path.join(full, "*.docx"))
    if not docx_files:
        continue
    docx = docx_files[0]
    print(f"\n{'='*60}")
    print(f"  {folder}")
    print(f"{'='*60}")

    try:
        paper = extract(docx, "output/test")
        clean = process(paper, rubric, config)
    except Exception as e:
        print(f"  ERROR: {e}")
        continue

    total_imgs = len(paper.get("images", []))
    total_embed = len(paper.get("embedded_files", []))
    print(f"  表格:{len(paper.get('tables',[]))}  图片:{total_imgs}  嵌入文件:{total_embed}")

    for q in rubric["questions"]:
        qk = f"q{q['id']}"
        qd = clean.get(qk, {})
        prompt_len = len(str(qd.get("prompt_text", "")))
        persona_len = len(str(qd.get("persona_text", "")))
        table_len = len(str(qd.get("all_table_text", "")))
        imgs = len(qd.get("generated_images", []))
        hs = qd.get("has_screenshot", False)
        hv = qd.get("has_video", False)
        he = qd.get("has_excel_file", False)
        link = "Y" if qd.get("bot_link") else "N"
        print(f"  Q{q['id']} {q['name']:<8s} | scr={hs} | img={imgs} | vid={hv} | xls={he} | link={link} | prompt={prompt_len}字 | persona={persona_len}字 | table={table_len}字")

    student_info = paper.get("student_info", {})
    print(f"  学号:{student_info.get('id','?')}  姓名:{student_info.get('name','?')}")
