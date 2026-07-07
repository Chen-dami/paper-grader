"""
阅卷系统 -- 导航入口
"""
import streamlit as st
import os, sys, glob, time, yaml

sys.path.insert(0, os.path.dirname(__file__))

st.set_page_config(page_title="阅卷系统", page_icon=":material/edit_note:", layout="wide",
                   initial_sidebar_state="expanded")

from src.ui_style import inject; inject()
from src.utils import load_users, verify_user, _ensure_users_file

# ============================================================
#  session
# ============================================================
_defaults = {
    "authenticated": False,
    "teacher_name": "",
    "grading_mode": "relaxed",
    "rubric": None,
    "rubric_path": "data/rubric.json",
    "api_key_input": os.environ.get("DEEPSEEK_KEY", ""),
    "current_class": "",
    "grading_results": None,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

if not st.session_state.authenticated:
    token_file = "data/.session_token"
    if os.path.exists(token_file):
        try:
            with open(token_file) as f:
                parts = f.read().strip().split("\n")
                if len(parts) >= 2 and time.time() - float(parts[0]) < 86400:
                    username = parts[1]
                    user_info = load_users().get(username, {})
                    st.session_state.authenticated = True
                    st.session_state.teacher_name = f"{user_info.get('display_name', username)}老师"
                    st.session_state.username = username
        except Exception:
            pass

_json_files = glob.glob("data/*.json")
if _json_files:
    st.session_state.rubric_path = _json_files[0]

# ============================================================
#  登录页
# ============================================================
if not st.session_state.authenticated:
    st.title("阅卷系统")
    col = st.columns([1, 2, 1])
    with col[1]:
        st.markdown("---")
        st.subheader("教师登录")
        username = st.text_input("用户名", placeholder="请输入用户名")
        password = st.text_input("密码", type="password", placeholder="请输入密码")
        if st.button("登 录", type="primary", use_container_width=True):
            if not username:
                st.error("请输入用户名")
            elif not password:
                st.error("请输入密码")
            else:
                result = verify_user(username, password)
                if result:
                    display_name, role = result
                    st.session_state.authenticated = True
                    st.session_state.teacher_name = f"{display_name}老师"
                    st.session_state.username = username
                    os.makedirs("data", exist_ok=True)
                    with open("data/.session_token", "w") as f:
                        f.write(f"{time.time()}\n{username}")
                    st.rerun()
                else:
                    st.error("用户名或密码错误")
        _ensure_users_file()
        st.caption("默认账号: admin / admin123")
    st.stop()

# ============================================================
#  已登录
# ============================================================
teacher = st.session_state.teacher_name

PAGES = {
    "主页":     st.Page("home.py", title="主页", icon=":material/home:"),
    "阅卷":     st.Page("pages/1_grading.py", title="阅卷", icon=":material/assignment:"),
    "评分配置": st.Page("pages/2_config.py", title="评分配置", icon=":material/settings:"),
    "历史结果": st.Page("pages/3_results.py", title="历史结果", icon=":material/bar_chart:"),
    "AI助手":   st.Page("pages/4_ai_assistant.py", title="AI 助手", icon=":material/smart_toy:"),
    "数据分析": st.Page("pages/5_analytics.py", title="数据分析", icon=":material/analytics:"),
    "学生查询": st.Page("pages/6_student_portal.py", title="学生查询", icon=":material/search:"),
    "个人信息": st.Page("pages/7_profile.py", title="个人信息", icon=":material/person:"),
}

# ============================================================
#  侧边栏（必须在 pg.run() 之前，否则多页导航下会消失）
# ============================================================
with st.sidebar:
    st.caption(teacher)

    cur_mode = st.session_state.get("grading_mode", "relaxed")
    mode_names = {"relaxed": "宽松", "normal": "标准", "strict": "严格", "custom": "自定义"}

    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}

    custom_presets = cfg.get("custom_presets") or {}
    all_modes = ["relaxed", "normal", "strict"] + list(custom_presets.keys()) + ["custom"]
    if cur_mode not in all_modes:
        cur_mode = "relaxed"

    mode_labels = {m: mode_names.get(m, m) for m in all_modes}

    new_mode = st.selectbox(
        "评分模式", all_modes,
        index=all_modes.index(cur_mode),
        format_func=lambda x: mode_labels.get(x, x),
        key="sidebar_mode",
    )
    if new_mode != cur_mode:
        st.session_state.grading_mode = new_mode
        cfg.setdefault("grading", {})["mode"] = new_mode
        with open("config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        st.rerun()

    st.divider()

    if st.button("常见问题", use_container_width=True):
        st.session_state.dialog_type = "faq"
    if st.button("使用说明", use_container_width=True):
        st.session_state.dialog_type = "guide"

    st.divider()

    if st.button("退出登录", use_container_width=True):
        st.session_state.authenticated = False
        token_file = "data/.session_token"
        if os.path.exists(token_file):
            os.remove(token_file)
        st.rerun()

pg = st.navigation(list(PAGES.values()), position="sidebar")
pg.run()


# ============================================================
#  Dialogs
# ============================================================
from src.dialogs import show_faq, show_guide


@st.dialog("常见问题", width="large")
def _open_faq():
    show_faq()


@st.dialog("使用说明", width="large")
def _open_guide():
    show_guide()


if "dialog_type" not in st.session_state:
    st.session_state.dialog_type = None

_dtype = st.session_state.dialog_type
if _dtype is not None:
    st.session_state.dialog_type = None
    if _dtype == "faq":
        _open_faq()
    elif _dtype == "guide":
        _open_guide()
