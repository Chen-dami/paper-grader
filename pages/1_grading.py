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
from src.reporter import individual_report, class_summary_report

from src.ui_style import inject; inject()

if not st.session_state.get("authenticated", False):
    st.warning("请先在首页登录")
    st.stop()

st.title("阅卷")

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

if rubric_file:
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
            st.success(f"评分标准已解析：{rubric['exam']['name']} -- {len(rubric['questions'])}道题")
            st.rerun()
    except Exception as e:
        st.error(f"解析失败: {e}")
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
            ck_key = f"class_ck_{papers_root}"
            if ck_key not in st.session_state:
                st.session_state[ck_key] = {}
            for name, is_class, total, _, _ in class_entries:
                if name not in st.session_state[ck_key]:
                    st.session_state[ck_key][name] = is_class  # 符合命名规则的默认勾选

            st.caption(f"检测到 {len(class_entries)} 个候选班级：")

            # 全选/全不选/反选
            cc1, cc2, cc3, cc4 = st.columns([1, 1, 1, 3])
            with cc1:
                if st.button("全选", key="sel_all"):
                    for name, _, _, _, _ in class_entries:
                        st.session_state[ck_key][name] = True
                    st.rerun()
            with cc2:
                if st.button("全不选", key="sel_none"):
                    for name, _, _, _, _ in class_entries:
                        st.session_state[ck_key][name] = False
                    st.rerun()
            with cc3:
                if st.button("反选", key="sel_inv"):
                    for name, _, _, _, _ in class_entries:
                        st.session_state[ck_key][name] = not st.session_state[ck_key].get(name, False)
                    st.rerun()

            selected_classes = []
            for name, is_class, total, sfolders, ldocx in class_entries:
                tag = "🎓" if is_class else "📂"
                checked = st.checkbox(
                    f"{tag} {name}（{total}份试卷）",
                    value=st.session_state[ck_key].get(name, False),
                    key=f"ck_{name}"
                )
                st.session_state[ck_key][name] = checked
                if checked:
                    selected_classes.append((name, sfolders, ldocx))

            if selected_classes:
                for cname, sfolders, ldocx in selected_classes:
                    for folder_name, docx_path, supp in sfolders:
                        display = f"{cname}/{folder_name}"
                        paper_files.append((docx_path, display, supp))
                    for dpath, dname in ldocx:
                        display = f"{cname}/{dname}"
                        paper_files.append((dpath, display, None))
                class_name = " + ".join(c[0] for c in selected_classes)
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

# ---- 阅卷 ----
st.divider()
st.subheader("第三步：开始阅卷")

check_plag = st.checkbox("阅卷后自动查重", value=True)
can_run = bool(paper_files)

if st.button("开始阅卷", type="primary", disabled=not can_run, use_container_width=True) and paper_files:
    from src.utils import build_runtime_config, load_rubric as lr
    config = build_runtime_config()
    rubric = lr(rubric_path)
    st.session_state.rubric = rubric

    key = os.environ.get("DEEPSEEK_KEY", "") or st.session_state.api_key_input
    if not key:
        st.error("请先在侧边栏设置 API Key")
        st.stop()

    config["llm"]["api_key"] = key
    llm.init_llm(config.get("llm", {}))
    db.init_db(config.get("database", {}))

    out_dir = os.path.join("output", class_name.replace(" + ", "_"))
    safe_class = class_name.replace(" + ", "_")
    results = []
    bar = st.progress(0)
    stat = st.empty()
    total = len(paper_files)

    for i, (pp, fn, supp) in enumerate(paper_files):
        stat.text(f"评阅中 ({i+1}/{total}): {fn}")
        try:
            paper = extract_from_student_folder(pp, out_dir, supp)
            clean = process(paper, rubric, config)
            student = paper["student_info"]
        except Exception as e:
            stat.text(f"提取失败 ({i+1}/{total}): {fn} -- {e}")
            bar.progress((i + 1) / total)
            continue

        total_score = 0
        all_scores = {}
        for q in rubric["questions"]:
            qid = q["id"]
            qk = f"q{qid}"
            if qk not in clean: continue
            r = grade(clean[qk], q, config)
            all_scores[qid] = r
            total_score += r.get("总分", 0)

        individual_report(student, all_scores, rubric, out_dir)

        pt = paper.get("paper_dir", "")
        if pt and os.path.isdir(pt):
            shutil.rmtree(pt, ignore_errors=True)

        results.append({
            "学号": student.get("学号", "?"),
            "姓名": student.get("姓名", "?"),
            **{q["name"]: all_scores.get(q["id"], {}).get("总分", 0) for q in rubric["questions"]},
            "总分": total_score,
            "文件名": fn,
        })
        bar.progress((i + 1) / total)

    stat.text(f"阅卷完成！共 {len(results)} 份")

    if results:
        summary_data = []
        for r in results:
            item = {"student_id": r["学号"], "student_name": r["姓名"],
                    "class_name": class_name, "total_score": r["总分"]}
            for q in rubric["questions"]:
                item[f"q{q['id']}_score"] = r.get(q["name"], 0)
            summary_data.append(item)
        class_summary_report(summary_data, rubric, out_dir, safe_class)

        if check_plag and len(paper_files) >= 2:
            with st.spinner("查重中..."):
                pdc = os.path.join("data", "papers", class_name)
                if os.path.isdir(pdc):
                    from src.plagiarism import run as check_run
                    check_run(pdc, out_dir)

    st.session_state.grading_results = results
    st.session_state.current_class = class_name

    st.divider()
    st.subheader("成绩总览")

    if results:
        df = pd.DataFrame(results)
        df = df.sort_values("总分", ascending=False).reset_index(drop=True)
        df.index = range(1, len(df) + 1)
        df.index.name = "序号"

        def hl(v):
            if isinstance(v, (int, float)):
                if v >= 90: return "background-color: #C6EFCE; font-weight: bold"
                if v < 60: return "background-color: #FFC7CE; font-weight: bold"
            return ""

        st.dataframe(df.style.map(hl, subset=["总分"]), use_container_width=True,
                     height=min(400, 35 * len(df) + 38))

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("平均分", f"{df['总分'].mean():.1f}")
        m2.metric("最高分", f"{df['总分'].max()}")
        m3.metric("最低分", f"{df['总分'].min()}")
        m4.metric("及格率", f"{(df['总分'] >= 60).sum() / len(df) * 100:.0f}%")

        st.divider()
        dl1, dl2, dl3 = st.columns(3)
        with dl1:
            sp = os.path.join(out_dir, f"评分汇总_{safe_class}.xlsx")
            if os.path.exists(sp):
                with open(sp, "rb") as f:
                    st.download_button("班级汇总", f.read(), file_name=f"评分汇总_{safe_class}.xlsx")
        with dl2:
            pdir = os.path.join(out_dir, "个人成绩")
            if os.path.exists(pdir):
                zb = io.BytesIO()
                with zipfile.ZipFile(zb, "w", zipfile.ZIP_DEFLATED) as zf:
                    for f in os.listdir(pdir):
                        if f.endswith(".xlsx"):
                            zf.write(os.path.join(pdir, f), f)
                st.download_button("个人明细(ZIP)", zb.getvalue(), file_name=f"个人明细_{safe_class}.zip")
        with dl3:
            cp = os.path.join(out_dir, "查重报告.xlsx")
            if os.path.exists(cp):
                with open(cp, "rb") as f:
                    st.download_button("查重报告", f.read(), file_name=f"查重报告_{safe_class}.xlsx")
