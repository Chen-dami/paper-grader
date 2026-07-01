"""
首页
"""
import streamlit as st
import os, sys, glob

sys.path.insert(0, os.path.dirname(__file__))
from src.ui_style import inject; inject()

pc = sum(1 for _, _, fs in os.walk("data/papers") for f in fs
         if f.endswith('.docx') and not f.startswith('~$'))
od = len(glob.glob("output/*/评分汇总_*.xlsx")) if os.path.exists("output") else 0

teacher = st.session_state.teacher_name

# 品牌 logo 名
st.markdown("""
<div style="text-align:center; margin-top:32px; margin-bottom:4px;">
    <span style="font-family:'STSong','SimSun','Microsoft YaHei',serif;
                 font-size:2.8rem; font-weight:700; color:#2C2416;
                 letter-spacing:0.1em;">阅卷系统</span>
</div>
""", unsafe_allow_html=True)
st.caption(f"欢迎，{teacher}老师 👋")

st.markdown("<br>", unsafe_allow_html=True)

c1, c2, c3 = st.columns(3)
with c1:
    with st.container(border=True):
        st.markdown("### 📝 阅卷")
        st.caption("上传评分标准和试卷，一键评分。")
        st.success("评分标准已就绪" if os.path.exists(st.session_state.rubric_path) else "请先上传评分标准")
with c2:
    with st.container(border=True):
        st.markdown("### ⚙️ 评分配置")
        st.caption("题目分值、评分权重、档位百分比。")
        st.metric("待阅试卷", f"{pc} 份")
with c3:
    with st.container(border=True):
        st.markdown("### 📊 历史结果")
        st.caption("历次成绩、分布图、查重报告。")
        st.metric("已阅班级", f"{od} 个")
