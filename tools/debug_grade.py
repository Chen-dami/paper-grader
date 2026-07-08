"""
评分调试工具 — 显示每次 LLM 请求的完整内容和返回结果
用法: python tools/debug_grade.py <docx路径>
"""
import os, sys, json, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.extractor import extract
from src.preprocessor import process
from src.utils import load_rubric


def debug_grade(docx_path: str, strategy: str = "text_only"):
    import yaml
    with open("config.yaml", "r", encoding="utf-8") as f:
        yaml_config = yaml.safe_load(f)

    paper = extract(docx_path, "output/debug_trace")
    rubric = load_rubric("data/rubric.json")
    config = {
        "vision_strategy": strategy,
        "grading": yaml_config.get("grading", {}),
        "image": yaml_config.get("image", {}),
        "model_router": yaml_config.get("model_router", {}),
    }
    clean = process(paper, rubric, config)

    sep = "=" * 70

    print(sep)
    print(f"  评分调试 — {os.path.basename(docx_path)}")
    print(f"  学生: {paper['student_info']}")
    print(f"  策略: {strategy} | 模式: {config['grading'].get('mode', '?')}")
    print(f"  表格: {len(paper['tables'])}个 | 图片: {len(paper['images'])}张 | 嵌入文件: {len(paper['embedded_files'])}个")
    print(sep)

    from src.grader import grade, _should_use_vision, _is_truly_empty

    total_all = 0
    for q in rubric["questions"]:
        qid = q["id"]
        qk = f"q{qid}"
        qd = clean.get(qk, {})

        print(f"\n{'─'*60}")
        print(f"Q{qid} {q['name']} ({q['max_score']}分) [{q.get('grading_type','?')}]")
        print(f"{'─'*60}")

        # 显示提取的原始数据
        print(f"  [数据提取]")
        # 安全打印（避免 GBK 编码崩溃）
        def _safe(s, n=150):
            t = str(s)[:n]
            return t.encode('ascii', errors='replace').decode('ascii')
        print(f"    prompt_text: {len(str(qd.get('prompt_text','')))}字 -> {_safe(qd.get('prompt_text',''))}")
        print(f"    result_text: {len(str(qd.get('result_text','')))}字 -> {_safe(qd.get('result_text',''))}")
        if q.get('grading_type') == 'hybrid':
            print(f"    persona_text: {len(str(qd.get('persona_text','')))}字 -> {_safe(qd.get('persona_text',''))}")
        print(f"    all_table_text: {len(str(qd.get('all_table_text','')))}字")
        print(f"    has_screenshot: {qd.get('has_screenshot')}")
        print(f"    generated_images: {len(qd.get('generated_images',[]))}张")
        print(f"    has_video: {qd.get('has_video')}, path: {bool(qd.get('video_path'))}")
        print(f"    has_excel: {qd.get('has_excel_file')}, path: {bool(qd.get('excel_path'))}")
        print(f"    bot_link: '{qd.get('bot_link','')[:100]}'")
        print(f"    link_reachable: {qd.get('link_reachable')}")

        use_vision = _should_use_vision(q.get('grading_type', 'text'), config)
        is_empty = _is_truly_empty(qd, q.get('grading_type', 'text'), strategy)
        print(f"  [判断] _is_truly_empty={is_empty} | _should_use_vision={use_vision}")

        # Hook into call_model to capture prompt
        import src.model_router as router
        original_call = router.call_model

        captured_prompt = []

        def debug_call_model(prompt, task_type="text", images=None, question_score=10,
                             temperature=None, max_tokens=None, **kw):
            captured_prompt.append(prompt)
            return original_call(prompt=prompt, task_type=task_type, images=images,
                                 question_score=question_score, temperature=temperature,
                                 max_tokens=max_tokens, **kw)

        router.call_model = debug_call_model

        try:
            result = grade(qd, q, config)
        finally:
            router.call_model = original_call

        total = result.get("总分", 0)
        total_all += total

        # 显示 LLM 请求和响应
        if captured_prompt:
            p = captured_prompt[0]
            print(f"\n  [LLM请求] ({len(p)}字符)")
            # 只显示关键部分
            for line in p.split("\n"):
                line = line.strip()
                if any(kw in line for kw in ["材料证据报告", "要求提交", "模式", "策略", "铁律",
                                              "题目：", "评分标准：", "档位判定", "总分", "评语"]):
                    print(f"    > {line[:150]}")
                elif line.startswith("- "):
                    print(f"      {line[:150]}")

        print(f"\n  [LLM响应] raw_response前200字: {str(result.get('raw_response',''))[:200]}")
        print(f"  [评分结果] 总分={total}/{q['max_score']} | 评语: {result.get('评语','')}")
        print(f"  [模型] {result.get('_model_used','?')}")
        for c in q["criteria"]:
            key = f"得分_{c['id']}_{c['name']}"
            print(f"    {c['name']}: {result.get(key, '?')}/{c['max']}")

    print(f"\n{'='*60}")
    print(f"  总分: {total_all}/100")
    print(f"{'='*60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", help="学生 docx 文件路径")
    parser.add_argument("--strategy", default="text_only",
                        choices=["text_only", "free_vision", "paid_vision"])
    args = parser.parse_args()
    debug_grade(args.docx, args.strategy)
