"""
极简 CSS —— 边框 + 配色 + Material Icons 修复
"""
import streamlit as st


def inject():
    st.markdown("""
    <style>
    /* ===== Material Icons 修复 ===== */
    .material-icons, .material-symbols-outlined,
    .material-symbols-sharp, .material-symbols-rounded {
        font: 0/0 a !important;
        color: transparent !important;
        text-shadow: none !important;
        overflow: hidden !important;
    }
    button[data-testid="stSidebarCollapseButton"] {
        position: relative !important;
        min-width: 32px !important; min-height: 32px !important;
    }
    button[data-testid="stSidebarCollapseButton"]::before {
        content: "";
        position: absolute; top: 50%; left: 50%;
        transform: translate(-50%, -50%);
        width: 0; height: 0;
        border-top: 5px solid transparent;
        border-bottom: 5px solid transparent;
        border-right: 7px solid #666;
    }
    [data-testid="stDeployButton"] { display: none !important; }
    #MainMenu { visibility: hidden !important; }
    footer { visibility: hidden !important; }

    /* ===== 全局边框 ===== */
    .stApp { background-color: #F7F5F0; }
    .stTextInput input, .stTextArea textarea,
    [data-baseweb="select"] [class*="select"], [data-baseweb="input"],
    [data-baseweb="select"] > div {
        border: 1px solid #D1CCC3 !important;
        border-radius: 6px !important;
        background-color: #fff !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #4A7C59 !important;
        box-shadow: 0 0 0 2px #E8F0EA !important;
    }
    .stNumberInput input, [data-baseweb="number-input"] input {
        border: 1px solid #D1CCC3 !important;
        border-radius: 6px !important;
        background-color: #fff !important;
    }
    [data-baseweb="popover"] { background-color: #fff !important; }
    [data-baseweb="menu"] { background-color: #fff !important; }
    ul[data-baseweb="menu"] li {
        background-color: #fff !important;
        border-bottom: 1px solid #F2EFE9 !important;
    }
    ul[data-baseweb="menu"] li:hover { background-color: #E8F0EA !important; }
    .stContainer, [data-testid="stExpander"], [data-testid="stForm"],
    [data-testid="stExpander"] details {
        border: 1px solid #D1CCC3 !important;
        border-radius: 8px !important;
    }
    hr, .stDivider { border-color: #D1CCC3 !important; }

    /* ===== 侧边栏 ===== */
    section[data-testid="stSidebar"] {
        border-right: 1px solid #D1CCC3 !important;
        background-color: #F7F5F0 !important;
    }
    /* 侧边栏内间距紧凑 */
    section[data-testid="stSidebar"] .stExpander {
        border: none !important;
        margin-bottom: 2px !important;
    }
    section[data-testid="stSidebar"] .stExpander details {
        border: none !important;
    }
    section[data-testid="stSidebar"] .stSelectbox label {
        font-size: 0.85rem !important;
    }
    section[data-testid="stSidebar"] .stButton > button {
        font-size: 0.9rem !important;
    }

    /* ===== 按钮 ===== */
    .stButton > button {
        background-color: #4A7C59 !important; color: #fff !important;
        border: none !important; border-radius: 6px !important;
    }
    .stButton > button:hover { background-color: #3D6B4A !important; }
    .stButton > button[kind="secondary"] {
        background-color: #fff !important; color: #4A7C59 !important;
        border: 1px solid #4A7C59 !important;
    }
    .stButton > button[kind="secondary"]:hover { background-color: #E8F0EA !important; }
    .stProgress > div > div { background-color: #4A7C59 !important; }

    /* ===== 状态 ===== */
    .stSuccess { background-color: #E8F0EA !important; color: #4A7C59 !important; }
    .stWarning { background-color: #FBF5E8 !important; color: #8B6914 !important; }
    .stError  { background-color: #FDF0ED !important; color: #C0392B !important; }
    </style>
    """, unsafe_allow_html=True)
