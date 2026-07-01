"""
历史结果页
"""
import streamlit as st
import os, sys, glob, io, zipfile
import pandas as pd
from openpyxl import load_workbook

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.ui_style import inject; inject()

if not st.session_state.get("authenticated", False):
    st.warning("请先在首页登录")
    st.stop()

st.title("历史结果")

if not os.path.exists("output"):
    st.info("还没有阅卷记录")
    st.stop()

class_dirs = []
for d in os.listdir("output"):
    path = os.path.join("output", d)
    if os.path.isdir(path) and os.path.exists(os.path.join(path, f"评分汇总_{d}.xlsx")):
        class_dirs.append(d)

if not class_dirs:
    st.info("output/ 下没有找到评分汇总")
    st.stop()

selected = st.selectbox("选择班级", class_dirs, index=len(class_dirs) - 1)
out_dir = os.path.join("output", selected)
summary_path = os.path.join(out_dir, f"评分汇总_{selected}.xlsx")
check_path = os.path.join(out_dir, "查重报告.xlsx")
personal_dir = os.path.join(out_dir, "个人成绩")

@st.cache_data(ttl=10)
def load_summary(path):
    wb = load_workbook(path)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(min_row=4, values_only=True))
    if not rows: return pd.DataFrame()
    headers = [str(h) if h else "" for h in rows[0]]
    data = []
    for row in rows[1:]:
        vals = [v for v in row]
        if vals and any(v is not None for v in vals):
            data.append(vals)
    df = pd.DataFrame(data, columns=headers)
    if len(df) > 0:
        df = df[df.iloc[:, 0].apply(lambda x: str(x).strip() not in ["", "平均分"])]
    return df

df = load_summary(summary_path)
if df is None or df.empty:
    st.warning("无法加载成绩数据")
    st.stop()

score_cols = [c for c in df.columns if c not in ["序号", "学号", "姓名", "等级"]]
for c in score_cols:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")

total_col = "总分"
if total_col not in df.columns:
    total_col = score_cols[-1] if score_cols else None

st.subheader(f"{selected} -- 成绩概览")
mc = st.columns(5)
with mc[0]: st.metric("学生数", len(df))
with mc[1]:
    if total_col and total_col in df.columns:
        st.metric("平均分", f"{df[total_col].mean():.1f}")
with mc[2]:
    if total_col and total_col in df.columns:
        st.metric("最高分", f"{df[total_col].max():.0f}")
with mc[3]:
    if total_col and total_col in df.columns:
        st.metric("最低分", f"{df[total_col].min():.0f}")
with mc[4]:
    if total_col and total_col in df.columns:
        pr = (df[total_col] >= 60).sum() / len(df) * 100
        st.metric("及格率", f"{pr:.0f}%")

st.divider()
cc1, cc2 = st.columns(2)
with cc1:
    st.subheader("分数段分布")
    if total_col and total_col in df.columns:
        scores = df[total_col].dropna()
        bands = {"90-100": 0, "80-89": 0, "70-79": 0, "60-69": 0, "<60": 0}
        for s in scores:
            if s >= 90: bands["90-100"] += 1
            elif s >= 80: bands["80-89"] += 1
            elif s >= 70: bands["70-79"] += 1
            elif s >= 60: bands["60-69"] += 1
            else: bands["<60"] += 1
        st.bar_chart(pd.DataFrame({"分数段": list(bands.keys()), "人数": list(bands.values())}).set_index("分数段"),
                     use_container_width=True)
with cc2:
    st.subheader("各题平均得分率")
    q_cols = [c for c in score_cols if "总分" not in str(c) and "等级" not in str(c)]
    if q_cols:
        import re
        q_rates = {}
        for qc in q_cols:
            if qc in df.columns and pd.api.types.is_numeric_dtype(df[qc]):
                mm = re.search(r'\((\d+)\)', str(qc))
                qmax = int(mm.group(1)) if mm else df[qc].max()
                if qmax > 0: q_rates[qc] = df[qc].mean() / qmax * 100
        if q_rates:
            st.bar_chart(pd.DataFrame({"题目": list(q_rates.keys()), "得分率(%)": list(q_rates.values())}).set_index("题目"),
                         use_container_width=True)

st.divider()
st.subheader("学生成绩表")
st.dataframe(df, use_container_width=True, hide_index=True, height=min(500, 35 * len(df) + 38))

st.divider()
st.subheader("个人明细")
if os.path.exists(personal_dir):
    pf = sorted([f for f in os.listdir(personal_dir) if f.endswith(".xlsx")])
    if pf:
        sf = st.selectbox("选择学生", pf)
        if sf:
            wb = load_workbook(os.path.join(personal_dir, sf))
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                vals = [str(v) if v is not None else "" for v in row]
                text = " | ".join(v for v in vals if v)
                if text.strip():
                    st.text(text)

st.divider()
st.subheader("下载")
dl1, dl2, dl3 = st.columns(3)
with dl1:
    if os.path.exists(summary_path):
        with open(summary_path, "rb") as f:
            st.download_button("班级汇总", f.read(), file_name=f"评分汇总_{selected}.xlsx")
with dl2:
    if os.path.exists(personal_dir):
        zb = io.BytesIO()
        with zipfile.ZipFile(zb, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in os.listdir(personal_dir):
                if f.endswith(".xlsx"):
                    zf.write(os.path.join(personal_dir, f), f)
        st.download_button("个人明细(ZIP)", zb.getvalue(), file_name=f"个人明细_{selected}.zip")
with dl3:
    if os.path.exists(check_path):
        with open(check_path, "rb") as f:
            st.download_button("查重报告", f.read(), file_name=f"查重报告_{selected}.xlsx")
