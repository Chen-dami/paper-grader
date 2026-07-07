"""
阅卷页
"""
import streamlit as st
import os, sys, tempfile, shutil, time, zipfile, io, glob
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import llm, db
from src.extractor import extract, extract_from_student_folder
from src.preprocessor import process
from src.grader import grade, extract_scores
from src.reporter import class_summary_report

from src.ui_style import inject; inject()

if not st.session_state.get("authenticated", False):
    st.warning("请先在首页登录")
    st.stop()

st.title("阅卷")

# 持久化偏好
import json as _json
_PREFS_FILE = os.path.join("data", "prefs.json")


def _load_prefs():
    try:
        with open(_PREFS_FILE, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {}


def _save_prefs(d):
    os.makedirs("data", exist_ok=True)
    with open(_PREFS_FILE, "w", encoding="utf-8") as f:
        _json.dump(d, f, ensure_ascii=False)


_prefs = _load_prefs()
if "papers_root" not in st.session_state:
    st.session_state.papers_root = _prefs.get("papers_root", "data/papers")
if "grading_mode" not in st.session_state:
    st.session_state.grading_mode = _prefs.get("grading_mode", "relaxed")

# ---- 评分标准 ----
st.subheader("第一步：选择评分标准")

rubric_path = st.session_state.get("rubric_path", "data/rubric.json")
has_rubric = os.path.exists(rubric_path)

c1, c2 = st.columns([1, 2])
with c1:
    rubric_file = st.file_uploader("上传评分标准文档", type=["docx", "doc", "ppt", "pptx"],
                                    help="支持 Word / PowerPoint。上传后自动解析。", key="rubric_up")
with c2:
    if has_rubric:
        from src.utils import load_rubric as lr
        rubric = lr(rubric_path)
        if rubric:
            e = rubric.get("exam", {})
            qs = rubric.get("questions", [])
            st.success(f"{e.get('name','?')} | {len(qs)}道题 | 满分{e.get('total_score',100)}")
            with st.expander("题目列表"):
                gt = {"text": "文字", "vision": "图像/视频", "code": "纯代码", "hybrid": "智能体"}
                for q in qs:
                    st.caption(f"Q{q['id']} {q['name']} ({q['max_score']}分) [{gt.get(q.get('grading_type',''),'?')}]")
    else:
        st.info("请上传评分标准文档")

if rubric_file and not st.session_state.get("_parsing_done", False):
    fname = rubric_file.name.lower()
    suffix = os.path.splitext(fname)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(rubric_file.getvalue())
        rubric_tmp = tmp.name
    try:
        # 确保 LLM 拿到 key（优先 session state，其次环境变量）
        from src.utils import build_runtime_config
        rcfg = build_runtime_config()
        key = rcfg.get("llm", {}).get("api_key", "")
        if key:
            os.environ["DEEPSEEK_KEY"] = key
        llm.init_llm(rcfg.get("llm", {}))

        with st.spinner("正在解析评分标准..."):
            from tools.import_rubric import parse_rubric_docx
            parse_rubric_docx(rubric_tmp, rubric_path)
        from src.utils import load_rubric as lr
        rubric = lr(rubric_path)
        if rubric:
            st.session_state.rubric = rubric
            st.session_state.rubric_path = rubric_path
            st.session_state._parsing_done = True
            st.success(f"评分标准已解析：{rubric['exam']['name']} -- {len(rubric['questions'])}道题")
            st.rerun()
    except Exception as e:
        st.error(f"解析失败: {e}")
        st.session_state._parsing_done = True
    finally:
        os.unlink(rubric_tmp)

if not has_rubric:
    st.stop()

import re

# ---- 试卷 ----
st.divider()
st.subheader("第二步：选择试卷")

tab1, tab2 = st.tabs(["文件夹扫描", "直接上传"])
paper_files = []   # [(docx_path, display_name, supplementary_files), ...]
class_name = ""

with tab1:
    papers_root = st.text_input(
        "试卷根目录",
        value=st.session_state.get("papers_root", "data/papers"),
        help="包含多个班级文件夹的父目录",
        key="papers_root_input"
    )
    st.session_state.papers_root = papers_root
    if papers_root != _prefs.get("papers_root", ""):
        _prefs["papers_root"] = papers_root
        _save_prefs(_prefs)

    if st.button("扫描班级", type="primary", use_container_width=True):
        st.session_state.scan_done = True
        st.rerun()

    scan_done = st.session_state.get("scan_done", False)
    if scan_done and os.path.isdir(papers_root):
        CLASS_RE = re.compile(r'^[一-鿿_a-zA-Z]+\d{2,}')
        all_dirs = sorted([
            d for d in os.listdir(papers_root)
            if os.path.isdir(os.path.join(papers_root, d))
        ])

        class_entries = []  # [(dirname, is_class_like, paper_count, student_folders, loose_docx)]
        for d in all_dirs:
            dp = os.path.join(papers_root, d)
            is_class = bool(CLASS_RE.match(d))
            student_folders = []  # [(folder_name, docx_path, supp_files)]
            loose_docx = []       # [(path, basename)]

            for entry in sorted(os.listdir(dp)):
                ep = os.path.join(dp, entry)
                if entry.startswith('~$'):
                    continue
                if os.path.isdir(ep):
                    # 学生文件夹 —— 找 docx + 收集辅助文件
                    docx_found = []
                    images = []
                    excels = []
                    for f in os.listdir(ep):
                        fp = os.path.join(ep, f)
                        if f.startswith('~$'):
                            continue
                        if f.lower().endswith('.docx'):
                            docx_found.append(fp)
                        elif f.lower().endswith(('.png', '.jpg', '.jpeg')):
                            images.append(fp)
                        elif f.lower().endswith(('.xlsx', '.xls')):
                            excels.append(fp)
                    if docx_found:
                        docx_found.sort(key=lambda x: os.path.getsize(x), reverse=True)
                        student_folders.append((entry, docx_found[0], {
                            "images": images, "excel": excels
                        }))
                elif entry.lower().endswith('.docx'):
                    loose_docx.append((ep, entry))

            total = len(student_folders) + len(loose_docx)
            if total > 0:
                class_entries.append((d, is_class, total, student_folders, loose_docx))

        if not class_entries:
            st.warning("该目录下未找到任何班级（需包含 .docx 试卷）")
        else:
            # 初始化勾选状态
            # 初始化：用 checkbox key 直接存状态
            for name, is_class, total, _, _ in class_entries:
                ck_name = f"ck_{name}"
                if ck_name not in st.session_state:
                    st.session_state[ck_name] = is_class

            st.caption(f"检测到 {len(class_entries)} 个候选班级：")

            # 全选/全不选/反选
            cc1, cc2, cc3, cc4 = st.columns([1, 1, 1, 3])
            with cc1:
                if st.button("全选", key="sel_all"):
                    for name, _, _, _, _ in class_entries:
                        st.session_state[f"ck_{name}"] = True
                    st.rerun()
            with cc2:
                if st.button("全不选", key="sel_none"):
                    for name, _, _, _, _ in class_entries:
                        st.session_state[f"ck_{name}"] = False
                    st.rerun()
            with cc3:
                if st.button("反选", key="sel_inv"):
                    for name, _, _, _, _ in class_entries:
                        st.session_state[f"ck_{name}"] = not st.session_state.get(f"ck_{name}", False)
                    st.rerun()

            selected_classes = []
            for name, is_class, total, sfolders, ldocx in class_entries:
                checked = st.checkbox(
                    f"{name}（{total}份试卷）",
                    key=f"ck_{name}"
                )
                if checked:
                    selected_classes.append((name, sfolders, ldocx))

            if selected_classes:
                class_names_list = []
                for cname, sfolders, ldocx in selected_classes:
                    class_names_list.append(cname)
                    for folder_name, docx_path, supp in sfolders:
                        display = f"{cname}/{folder_name}"
                        paper_files.append((docx_path, display, supp))
                    for dpath, dname in ldocx:
                        display = f"{cname}/{dname}"
                        paper_files.append((dpath, display, None))
                class_name = " + ".join(c[0] for c in selected_classes)
                st.session_state._class_names_list = class_names_list
                st.success(f"已选 {len(selected_classes)} 个班级，共 {len(paper_files)} 份试卷")

with tab2:
    uploaded = st.file_uploader("拖拽上传试卷", type=["docx"], accept_multiple_files=True, key="pup")
    cn2 = st.text_input("班级名", value="默认班级", key="cn2")
    if uploaded:
        tmp_dir = os.path.join("data", "papers", cn2 or "默认班级")
        os.makedirs(tmp_dir, exist_ok=True)
        found = []
        for uf in uploaded:
            safe = uf.name.replace(" ", "_")
            dest = os.path.join(tmp_dir, safe)
            with open(dest, "wb") as f:
                f.write(uf.getvalue())
            found.append((dest, safe))
        paper_files = [(p, n, None) for p, n in found]
        class_name = cn2 or "默认班级"
        st.success(f"已接收 {len(found)} 份试卷 -> 班级：{class_name}")

# ---- 视觉题评分方式 ----
vision_questions = []
if has_rubric:
    rubric = lr(rubric_path)
    if rubric:
        vision_questions = [q for q in rubric.get("questions", [])
                           if q.get("grading_type") in ("vision", "hybrid")]

if vision_questions:
    st.divider()
    st.subheader("视觉题评分方式")
    st.caption("勾选 = AI识别图片 | 取消 = 老师自己看图（AI只看文字）")
    for q in vision_questions:
        key = f"ai_vision_q{q['id']}"
        st.session_state.setdefault(key, True)  # 默认AI识别
        st.checkbox(
            f"Q{q['id']} {q['name']} ({q['max_score']}分) — AI识别图片",
            value=st.session_state[key],
            key=key,
        )

# ---- 阅卷 ----
st.divider()
st.subheader("第三步：开始阅卷")

check_plag = st.checkbox("阅卷后自动查重", value=True)
can_run = bool(paper_files)

if st.button("开始阅卷", type="primary", disabled=not can_run, use_container_width=True) and paper_files:
    from src.utils import build_runtime_config, load_rubric as lr
    from src.plagiarism import PLAG_LEVELS
    from collections import defaultdict
    config = build_runtime_config()
    rubric = lr(rubric_path)
    st.session_state.rubric = rubric

    key = os.environ.get("DEEPSEEK_KEY", "") or st.session_state.get("api_key_input", "")
    # 确保 model_router 能读取到 Key（写入环境变量）
    if key and not os.environ.get("DEEPSEEK_KEY"):
        os.environ["DEEPSEEK_KEY"] = key
    has_zhipu = bool(os.environ.get("ZHIPU_KEY", ""))
    if not key and not has_zhipu:
        st.error("请先在侧边栏设置 API Key（DeepSeek 或智谱至少配一个）")
        st.stop()

    config["llm"]["api_key"] = key
    # 注入视觉策略（从 config.yaml，UI 已保存）
    vision_strategy = config.get("model_router", {}).get("vision_strategy", "paid_vision")
    config["vision_strategy"] = vision_strategy
    # 按题跳过视觉：ai_vision_q{id}=False 的题老师自己看图
    skip_vision_ids = {
        q["id"] for q in vision_questions
        if not st.session_state.get(f"ai_vision_q{q['id']}", True)
    }
    if skip_vision_ids:
        st.info(f"已设为老师看图：Q{', Q'.join(str(i) for i in sorted(skip_vision_ids))}")

    llm.init_llm(config.get("llm", {}))
    db.init_db(config.get("database", {}))

    if "questions" not in rubric:
        st.error("评分标准解析异常，缺少题目信息。请重新上传评分标准文档。")
        st.stop()

    # ---- 按班级分组 ----
    by_class = defaultdict(list)
    for item in paper_files:
        pp, fn, supp = item
        cn = fn.split("/")[0]  # 从 display 路径提取班级名
        by_class[cn].append(item)

    all_class_results = {}   # {cn: [results]}
    all_class_failed = {}    # {cn: [failed]}
    plag_summary = {}        # {cn: {"pairs": int, "auto_zero": int}}
    global_total = len(paper_files)
    global_done = 0

    # ---- 逐班阅卷 ----
    for cn, class_papers in by_class.items():
        out_dir = os.path.join("output", cn)
        safe_class = cn
        results = []
        failed = []

        st.divider()
        st.subheader(f"📊 班级：{cn}（{len(class_papers)} 份）")

        bar = st.progress(0)
        stat = st.empty()

        for i, (pp, fn, supp) in enumerate(class_papers):
            stat.text(f"评阅中 ({i+1}/{len(class_papers)}): {fn}")
            try:
                paper = extract_from_student_folder(pp, out_dir, supp)
                clean = process(paper, rubric, config)
                student = paper["student_info"]
            except Exception as e:
                failed.append(f"{fn}: {e}")
                bn = os.path.splitext(os.path.basename(pp))[0]
                td = os.path.join(out_dir, bn)
                if os.path.isdir(td):
                    shutil.rmtree(td, ignore_errors=True)
                bar.progress((i + 1) / len(class_papers))
                global_done += 1
                continue

            total_score = 0
            all_scores = {}
            model_summary = {}
            for q in rubric["questions"]:
                qid = q["id"]
                qk = f"q{qid}"
                if qk not in clean: continue
                try:
                    r = grade(clean[qk], q, config,
                             force_no_vision=(qid in skip_vision_ids))
                    all_scores[qid] = r
                    total_score += r.get("总分", 0)
                    # 记录模型使用（用于降级警告）
                    mu = r.get("_model_used", "unknown")
                    model_summary[mu] = model_summary.get(mu, 0) + 1
                except Exception as e:
                    all_scores[qid] = {"总分": 0, "评语": f"评分异常: {e}", "切题判断": "错误"}
                    model_summary["error"] = model_summary.get("error", 0) + 1
                    stat.text(f"Q{qid}评分异常 ({i+1}/{len(class_papers)}): {fn} -- {e}")

            pt = paper.get("paper_dir", "")
            if pt and os.path.isdir(pt):
                shutil.rmtree(pt, ignore_errors=True)

            q_scores = {}
            for q in rubric["questions"]:
                q_scores[f"q{q['id']}_score"] = all_scores.get(q["id"], {}).get("总分", 0)
            criteria = {}
            for q in rubric["questions"]:
                qid = q["id"]
                qs = all_scores.get(qid, {})
                c_scores = {}
                for c in q["criteria"]:
                    key = f"得分_{c['id']}_{c['name']}"
                    c_scores[c["id"]] = {"name": c["name"], "score": qs.get(key, 0), "max": c["max"]}
                criteria[str(qid)] = c_scores
            results.append({
                "student_id": student.get("学号", "?"),
                "student_name": student.get("姓名", "?"),
                "student_id_alias": student.get("学号", "?"),
                **q_scores,
                **{q["name"]: all_scores.get(q["id"], {}).get("总分", 0) for q in rubric["questions"]},
                "total_score": total_score,
                "总分": total_score,
                "文件名": fn,
                "_criteria": criteria,
                "_model_used_summary": model_summary,
                "class_name": cn,
                "_source_file": os.path.basename(pp),  # 用于查重匹配
            })
            bar.progress((i + 1) / len(class_papers))
            global_done += 1

        # 批量清理残留
        for d in os.listdir(out_dir) if os.path.isdir(out_dir) else []:
            dp = os.path.join(out_dir, d)
            if os.path.isdir(dp) and d not in ("个人成绩",):
                imgs = os.path.join(dp, "images")
                embs = os.path.join(dp, "embeddings")
                if os.path.isdir(imgs) or os.path.isdir(embs):
                    shutil.rmtree(dp, ignore_errors=True)

        # ---- 核查提醒 ----
        review_items = []
        for r in results:
            criteria = r.get("_criteria", {})
            for qid_str, crits in criteria.items():
                for cid, cd in crits.items():
                    if cd.get("score", 0) == 0 and cd.get("max", 0) > 0:
                        review_items.append(f"{r.get('student_name','?')} Q{qid_str} {cd['name']}: 0/{cd['max']}分")
        if review_items:
            with st.expander(f"🔍 核查提醒：{len(review_items)} 个评分项为0分", expanded=len(review_items) <= 10):
                for item in review_items[:50]:
                    st.caption(item)
                if len(review_items) > 50:
                    st.caption(f"... 还有 {len(review_items) - 50} 项")

        # ---- 模型使用摘要 ----
        _model_used_count = {}
        _has_fallback = False
        for r in results:
            for q in rubric["questions"]:
                qid = q["id"]
                qs = r.get("_criteria", {}).get(str(qid), {})
                # 从 all_scores 拿 _model_used
                pass
            mu = r.get("_model_used_summary", {})
            for m, c in mu.items():
                _model_used_count[m] = _model_used_count.get(m, 0) + c
                if "fallback" in m or "error" in m:
                    _has_fallback = True

        if _has_fallback:
            with st.expander("⚠️ 模型调用降级提醒", expanded=True):
                st.warning(
                    "部分题目使用了降级模型（主模型调用失败后自动切换）。\n"
                    "这可能影响评分准确性。建议在「评分配置 → 模型路由」中检查 API Key 配置。"
                )

        if failed:
            stat.text(f"✅ {cn} 完成！成功 {len(results)}/{len(class_papers)}，失败 {len(failed)}")
            with st.expander(f"⚠ {len(failed)} 份提取失败"):
                for f in failed:
                    st.caption(f)
        else:
            stat.text(f"✅ {cn} 完成！共 {len(results)} 份")

        # ---- 查重（班级内） ----
        auto_zero_files = set()
        plag_pairs_count = 0
        if check_plag and len(class_papers) >= 2:
            with st.spinner(f"🔍 {cn} 查重中..."):
                from src.plagiarism import check_all as run_plag
                plag_rpt = os.path.join(out_dir, "查重报告.xlsx")
                # 查重目录：优先 data/papers/<班级名>，否则从实际试卷路径反推
                pdir = os.path.join("data", "papers", cn)
                if not os.path.isdir(pdir) and class_papers:
                    # 取第一份试卷的实际父目录作为查重范围
                    first_pp = class_papers[0][0]
                    pdir = os.path.dirname(first_pp)
                    # 如果是学生子文件夹，再往上一级（班级根目录）
                    if os.path.basename(pdir) not in ["", cn] and not os.path.basename(pdir).startswith(cn):
                        parent = os.path.dirname(pdir)
                        if os.path.isdir(parent):
                            pdir = parent
                if os.path.isdir(pdir):
                    st.caption(f"查重范围：{pdir}")
                    pairs, auto_zero = run_plag(pdir, results, plag_rpt)
                    if pairs:
                        plag_pairs_count = len(pairs)
                        auto_zero_files = auto_zero
                        # 级别统计
                        level_counts = defaultdict(int)
                        for p in pairs:
                            level_counts[p.get("level", "normal")] += 1
                        st.info(
                            f"查重结果：{len(pairs)} 对可疑 | "
                            + " | ".join(f"{PLAG_LEVELS.get(k,{}).get('label',k)}: {v}对"
                                         for k, v in sorted(level_counts.items()))
                        )
                        if auto_zero_files:
                            st.error(f"🚫 {len(auto_zero_files)} 名学生确认抄袭（可疑度≥300），总分已清零！")
                    else:
                        st.success("未发现可疑抄袭")
                else:
                    st.warning(f"查重目录不存在：{pdir}，跳过查重")

        # ---- 自动判零 ----
        if auto_zero_files:
            for r in results:
                src = r.get("_source_file", "")
                if src in auto_zero_files:
                    r["total_score"] = 0
                    r["总分"] = 0
                    r["_auto_zero"] = True
                    for q in rubric["questions"]:
                        r[q["name"]] = 0
                        r[f"q{q['id']}_score"] = 0

        plag_summary[cn] = {"pairs": plag_pairs_count, "auto_zero": len(auto_zero_files)}

        # ---- 生成班级得分表 ----
        if results:
            summary_data = []
            for r in results:
                item = {"student_id": r.get("student_id", r.get("学号", "")),
                        "student_name": r.get("student_name", r.get("姓名", "")),
                        "class_name": cn, "total_score": r.get("total_score", r.get("总分", 0)),
                        "_criteria": r.get("_criteria", {})}
                for q in rubric["questions"]:
                    item[f"q{q['id']}_score"] = r.get(q["name"], r.get(f"q{q['id']}_score", 0))
                summary_data.append(item)
            class_summary_report(summary_data, rubric, out_dir, safe_class)

        all_class_results[cn] = results
        all_class_failed[cn] = failed

    # ---- 所有班级完成 ----
    st.session_state.grading_results = all_class_results
    st.session_state.current_class = " + ".join(by_class.keys())
    st.session_state._plag_summary = plag_summary

    # ---- LLM 错误检测 ----
    total_llm_errors = 0
    for cn, results in all_class_results.items():
        for r in results:
            ms = r.get("_model_used_summary", {})
            total_llm_errors += ms.get("none(error)", 0)
    if total_llm_errors > 0:
        st.error(f"LLM 调用失败 {total_llm_errors} 次！请检查 API Key 是否有效。"
                 f"所有 LLM 评分的题目将显示为 0 分。"
                 f"请在「评分配置 → 模型路由」中点击「检测API Key」确认。")

    st.divider()
    st.subheader("📊 成绩总览")

    for cn, results in all_class_results.items():
        if not results:
            continue

        auto_count = sum(1 for r in results if r.get("_auto_zero"))
        st.markdown(f"### {cn}（{len(results)} 人" + (f"，🚫 {auto_count} 人判零" if auto_count else "") + "）")

        df = pd.DataFrame(results)
        df = df.sort_values("总分", ascending=False).reset_index(drop=True)
        df.index = range(1, len(df) + 1)
        df.index.name = "序号"

        def hl(v):
            if isinstance(v, (int, float)):
                if v >= 90: return "background-color: #C6EFCE; font-weight: bold"
                if v < 60: return "background-color: #FFC7CE; font-weight: bold"
            return ""

        display_cols = ["student_id", "student_name", "总分"] + [q["name"] for q in rubric["questions"]]
        display_cols = [c for c in display_cols if c in df.columns]
        df_display = df[display_cols]

        styled = df_display.style.map(hl, subset=["总分"])
        if auto_count:
            # 给判零行加背景色
            zero_idx = set(df.index[df["_auto_zero"] == True].tolist()) if "_auto_zero" in df.columns else set()

            def row_style(row):
                return ["background-color: #FFD7D7" if row.name in zero_idx else ""] * len(row)
            styled = styled.apply(row_style, axis=1)

        st.dataframe(styled, use_container_width=True,
                     height=min(400, 35 * len(df) + 38))

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("平均分", f"{df['总分'].mean():.1f}")
        m2.metric("最高分", f"{df['总分'].max()}")
        m3.metric("最低分", f"{df['总分'].min()}")
        m4.metric("及格率", f"{(df['总分'] >= 60).sum() / len(df) * 100:.0f}%")

        # 下载按钮
        out_dir = os.path.join("output", cn)
        dl1, dl2 = st.columns(2)
        with dl1:
            sp = os.path.join(out_dir, f"评分汇总_{cn}.xlsx")
            if os.path.exists(sp):
                with open(sp, "rb") as f:
                    st.download_button(f"📥 得分表_{cn}", f.read(),
                                       file_name=f"评分汇总_{cn}.xlsx", key=f"dl1_{cn}")
            else:
                st.caption("得分表未生成")
        with dl2:
            plag_rpt = os.path.join(out_dir, "查重报告.xlsx")
            if os.path.exists(plag_rpt):
                with open(plag_rpt, "rb") as f:
                    st.download_button(f"📥 查重报告_{cn}", f.read(),
                                       file_name=f"查重报告_{cn}.xlsx", key=f"dl2_{cn}")
            else:
                plag_files = glob.glob(os.path.join(out_dir, "查重报告_*.xlsx"))
                if plag_files:
                    zb2 = io.BytesIO()
                    with zipfile.ZipFile(zb2, "w", zipfile.ZIP_DEFLATED) as zf:
                        for pf in plag_files:
                            zf.write(pf, os.path.basename(pf))
                    st.download_button(f"📥 查重报告(ZIP)_{cn}", zb2.getvalue(),
                                       file_name=f"查重报告_{cn}.zip", key=f"dlzip_{cn}")
                else:
                    st.caption("查重报告：未生成")
        st.markdown("---")
