"""
阅卷系统
用法: python main.py
目录结构: data/papers/班级名/*.docx
输出:   output/班级名/评分明细_学号_姓名.xlsx  +  评分汇总_班级名.xlsx

换试卷只需:
  1. python tools/import_rubric.py data/新评分标准.docx
  2. 放试卷到 data/papers/班级名/
  3. python main.py
"""
import os, sys, glob, json, time, argparse, yaml
from concurrent.futures import ThreadPoolExecutor, as_completed

from src import db, llm
from src.extractor import extract
from src.preprocessor import process
from src.grader import grade, extract_scores
from src.reporter import class_summary_report, print_stats


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_rubric(path: str = "data/rubric.json") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def grade_one(paper_path: str, rubric: dict, config: dict, out_dir: str) -> dict | None:
    """评一份试卷"""
    try:
        paper = extract(paper_path, out_dir)
        clean = process(paper, rubric, config)
        student = paper["student_info"]
    except Exception:
        return None

    total = 0
    all_scores = {}
    tokens_in = tokens_out = 0

    for q in rubric["questions"]:
        qid = q["id"]
        qk = f"q{qid}"
        if qk not in clean:
            continue
        r = grade(clean[qk], q, config)
        all_scores[qid] = r
        total += r.get("总分", 0)
        tokens_in += r.get("tokens_in", 0)
        tokens_out += r.get("tokens_out", 0)

    # 存数据库
    pid = db.save_paper(
        student.get("学号", "?"), student.get("姓名", "?"), student.get("班级", ""),
        os.path.basename(paper_path), {"path": paper_path}
    )
    for q in rubric["questions"]:
        qid = q["id"]
        r = all_scores.get(qid, {})
        if not r:
            continue
        scores_list = extract_scores(r, q)
        for s in scores_list:
            db.save_score(pid, qid, q["name"],
                          s["criterion_id"], s["criterion_name"],
                          s["score"], s["max_score"])
        if r.get("raw_response") and r.get("tokens_in", 0) > 0:
            db.save_audit(pid, qid, config["llm"].get("model", ""),
                          r["tokens_in"], r["tokens_out"], r["raw_response"])

    comments = " | ".join(str(all_scores.get(q["id"], {}).get("评语", ""))
                          for q in rubric["questions"])
    db.update_paper(pid, total, "done", comments[:200])

    # 清理临时文件
    import shutil
    paper_tmp = paper.get("paper_dir", "")
    if paper_tmp and os.path.isdir(paper_tmp):
        shutil.rmtree(paper_tmp, ignore_errors=True)

    criteria_scores = {}
    for q in rubric["questions"]:
        qid = q["id"]
        qs = all_scores.get(qid, {})
        c_scores = {}
        for c in q["criteria"]:
            key = f"得分_{c['id']}_{c['name']}"
            c_scores[c["id"]] = {"name": c["name"], "score": qs.get(key, 0), "max": c["max"]}
        criteria_scores[str(qid)] = c_scores

    result = {
        "student_id": student.get("学号", "?"),
        "student_name": student.get("姓名", "?"),
        "class_name": student.get("班级", ""),
        "total_score": total,
        "tokens": (tokens_in, tokens_out),
        "_criteria": criteria_scores,
    }
    for q in rubric["questions"]:
        qid = q["id"]
        result[f"q{qid}_score"] = all_scores.get(qid, {}).get("总分", 0)

    return result


def main():
    parser = argparse.ArgumentParser(description="阅卷系统")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--papers-dir", default="data/papers")
    parser.add_argument("--rubric", default="", help="评分标准.docx（首次使用自动生成rubric.json）")
    parser.add_argument("--check", action="store_true", help="阅卷后自动查重")
    parser.add_argument("--workers", type=int, default=4, help="并行处理线程数（默认4，设为1则为串行）")
    args = parser.parse_args()

    config = load_config(args.config)

    # 评分标准：如果是 docx 就自动转 json
    if args.rubric and args.rubric.endswith('.docx'):
        print(f"检测到评分标准 docx，正在转换...")
        from tools.import_rubric import parse_rubric_docx
        parse_rubric_docx(args.rubric, "data/rubric.json")

    rubric = load_rubric()
    llm.init_llm(config.get("llm", {}))
    db.init_db(config.get("database", {}))

    # 扫描班级文件夹
    papers_dir = args.papers_dir
    if not os.path.isdir(papers_dir):
        print(f"目录不存在: {papers_dir}")
        sys.exit(1)

    class_dirs = [d for d in os.listdir(papers_dir)
                  if os.path.isdir(os.path.join(papers_dir, d))]
    if not class_dirs:
        class_dirs = ["."]
        paper_files = {'.': sorted(glob.glob(os.path.join(papers_dir, "*.docx")))}
    else:
        paper_files = {}
        for cls in class_dirs:
            files = sorted(glob.glob(os.path.join(papers_dir, cls, "*.docx")))
            if files:
                paper_files[cls] = files

    total_papers = sum(len(v) for v in paper_files.values())
    if total_papers == 0:
        print("没有找到试卷。请将 .docx 放入 data/papers/班级名/ 下")
        sys.exit(1)

    provider = config["llm"].get("model", "?")
    mode = config.get("grading", {}).get("mode", "relaxed")
    q_count = len(rubric["questions"])
    n_workers = max(1, args.workers)
    print(f"阅卷系统 | {provider} | {mode} | {q_count}题 | {total_papers}份 | {n_workers}线程\n")

    t0 = time.time()
    all_results = []

    # 收集所有待评试卷
    all_papers = []  # [(cls_name, docx_path, out_dir), ...]
    for cls_name in sorted(paper_files.keys()):
        files = paper_files[cls_name]
        if not files:
            continue
        cls_label = cls_name if cls_name != "." else os.path.basename(os.path.abspath(papers_dir))
        out_dir = os.path.join("output", cls_label)
        for f in files:
            all_papers.append((cls_label, f, out_dir))

    # 批量预检查：提前提取，标记明显空白的试卷
    print(f"预检查 {len(all_papers)} 份试卷...")
    valid_papers = []  # [(cls_label, docx_path, out_dir, paper_data, clean_data), ...]
    skip_count = 0
    for cls_label, f, out_dir in all_papers:
        try:
            paper = extract(f, out_dir)
            clean = process(paper, rubric, config)
            # 检查是否全部题目都为空
            all_empty = True
            for q in rubric["questions"]:
                qk = f"q{q['id']}"
                if qk in clean:
                    qd = clean[qk]
                    text_fields = ["prompt_text", "result_text", "image_prompt",
                                   "video_prompt", "persona_text", "all_table_text"]
                    total_text = "".join(str(qd.get(k, "")) for k in text_fields)
                    has_media = qd.get("has_video") or qd.get("has_screenshot") or qd.get("has_excel_file")
                    if len(total_text.strip()) >= 10 or has_media:
                        all_empty = False
                        break
            if all_empty:
                skip_count += 1
                # 空白试卷直接给 0 分
                student = paper.get("student_info", {})
                zero_result = {
                    "student_id": student.get("学号", "?"),
                    "student_name": student.get("姓名", "?"),
                    "class_name": cls_label,
                    "total_score": 0,
                }
                for q in rubric["questions"]:
                    zero_result[f"q{q['id']}_score"] = 0
                all_results.append(zero_result)
                # 清理临时文件
                import shutil
                pt = paper.get("paper_dir", "")
                if pt and os.path.isdir(pt):
                    shutil.rmtree(pt, ignore_errors=True)
            else:
                valid_papers.append((cls_label, f, out_dir))
                # 清理提取的临时文件（评分时会重新提取）
                import shutil
                pt = paper.get("paper_dir", "")
                if pt and os.path.isdir(pt):
                    shutil.rmtree(pt, ignore_errors=True)
        except Exception:
            # 提取失败的试卷仍进入评分流程（可能是格式特殊）
            valid_papers.append((cls_label, f, out_dir))

    if skip_count > 0:
        print(f"  预检查跳过 {skip_count} 份空白试卷（直接0分）")

    # 按班级分组
    class_papers = {}  # {cls_label: [(docx_path, out_dir), ...]}
    for cls_label, f, out_dir in valid_papers:
        class_papers.setdefault(cls_label, []).append((f, out_dir))

    for cls_label in sorted(class_papers.keys()):
        papers = class_papers[cls_label]
        out_dir = papers[0][1]  # all share same out_dir
        print(f"  {cls_label}: {len(papers)}人  ", end="", flush=True)

        class_results = []
        t_cls = time.time()

        if n_workers > 1 and len(papers) > 1:
            # 并行评阅
            with ThreadPoolExecutor(max_workers=n_workers) as executor:
                futures = {
                    executor.submit(grade_one, f, rubric, config, out_dir): (i, f)
                    for i, (f, _) in enumerate(papers)
                }
                for future in as_completed(futures):
                    i, f = futures[future]
                    try:
                        r = future.result()
                        if r:
                            class_results.append(r)
                            all_results.append(r)
                    except Exception as e:
                        print(f"\n  [ERR] {os.path.basename(f)}: {e}")

                    # 进度
                    done = len(class_results)
                    pct = done / len(papers)
                    bar = "|" + "=" * int(pct * 15) + ">" + " " * (15 - int(pct * 15)) + "|"
                    elapsed = time.time() - t_cls
                    per_paper = elapsed / max(1, done)
                    print(f"\r  {cls_label}: {len(papers)}人 {bar} {done}/{len(papers)} | {per_paper:.1f}s/份", end="")
        else:
            # 串行评阅
            for i, (f, _) in enumerate(papers):
                r = grade_one(f, rubric, config, out_dir)
                if r:
                    class_results.append(r)
                    all_results.append(r)

                step = max(1, len(papers) // 20)
                if (i + 1) % step == 0 or i == len(papers) - 1:
                    pct = (i + 1) / len(papers)
                    bar = "|" + "=" * int(pct * 15) + ">" + " " * (15 - int(pct * 15)) + "|"
                    elapsed = time.time() - t_cls
                    per_paper = elapsed / (i + 1)
                    print(f"\r  {cls_label}: {len(papers)}人 {bar} {i+1}/{len(papers)} | {per_paper:.1f}s/份", end="")

        # 班级汇总
        if class_results:
            class_summary_report(class_results, rubric, out_dir, cls_label)
            avg = sum(r["total_score"] for r in class_results) / len(class_results)
            print(f"\r  {cls_label}: {len(papers)}人 | 平均{avg:.0f}分 | 汇总表已生成  ", flush=True)

            # 班级内查重
            if args.check and len(papers) >= 2:
                from src.plagiarism import run as check_run
                cls_papers_dir = os.path.join(papers_dir, cls_label) if cls_label != "." else papers_dir
                check_run(cls_papers_dir, out_dir)

    # 总览
    if not all_results:
        print("\n无成功评阅的试卷")
        return

    total_time = time.time() - t0
    print(f"\n总计: {len(all_results)}/{total_papers}份 | 耗时 {total_time/60:.1f}分钟 | 平均 {total_time/len(all_results):.1f}s/份")
    stats = db.get_statistics()
    print_stats(stats)

    # 缓存统计
    cs = llm.cache_stats()
    print(f"  LLM缓存: {cs['size']}条 | 命中{cs['hits']}次 ({cs['hit_rate']})")

    print(f"\n输出目录: output/")


if __name__ == "__main__":
    main()
