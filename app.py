"""
阅卷系统 -- 导航入口
"""
import streamlit as st
import os, sys, glob, time, yaml

sys.path.insert(0, os.path.dirname(__file__))

st.set_page_config(page_title="阅卷系统", page_icon="📝", layout="wide",
                   initial_sidebar_state="expanded")

from src.ui_style import inject; inject()
from src.utils import hpw, load_users, verify_user, save_user, _ensure_users_file

# ============================================================
#  session 初始化
# ============================================================
for k, v in {
    "authenticated": False, "teacher_name": "", "grading_mode": "relaxed",
    "rubric": None, "rubric_path": "data/rubric.json",
    "api_key_input": os.environ.get("DEEPSEEK_KEY", ""),
    "current_class": "", "grading_results": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# 自动登录
if not st.session_state.authenticated:
    tf = "data/.session_token"
    if os.path.exists(tf):
        try:
            with open(tf) as f:
                td = f.read().strip().split("\n")
                if len(td) >= 2 and time.time() - float(td[0]) < 86400:
                    username = td[1]
                    users = load_users()
                    u = users.get(username, {})
                    st.session_state.authenticated = True
                    st.session_state.teacher_name = f"{u.get('display_name', username)}老师"
                    st.session_state.username = username
        except:
            pass

json_files = glob.glob("data/*.json")
if json_files:
    st.session_state.rubric_path = json_files[0]

# ============================================================
#  登录页
# ============================================================
if not st.session_state.authenticated:
    st.title("阅卷系统")
    c = st.columns([1, 2, 1])
    with c[1]:
        st.markdown("---")
        st.subheader("教师登录")
        username = st.text_input("用户名", placeholder="请输入用户名")
        pw = st.text_input("密码", type="password", placeholder="请输入密码")
        if st.button("登 录", type="primary", use_container_width=True):
            if username and pw:
                result = verify_user(username, pw)
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
            elif not username:
                st.error("请输入用户名")
            else:
                st.error("请输入密码")
        _ensure_users_file()
        st.caption("默认账号: admin / admin123")
    st.stop()

# ============================================================
#  已登录
# ============================================================
teacher = st.session_state.teacher_name

# ===== 侧边栏上方：导航 =====
PAGES = {
    "主页": st.Page("home.py", title="主页", icon="🏠"),
    "阅卷": st.Page("pages/1_grading.py", title="阅卷", icon="📝"),
    "评分配置": st.Page("pages/2_config.py", title="评分配置", icon="⚙️"),
    "历史结果": st.Page("pages/3_results.py", title="历史结果", icon="📊"),
}
pg = st.navigation(list(PAGES.values()), position="sidebar")
pg.run()

# ===== 侧边栏下方：工具区 =====
with st.sidebar:
    st.divider()

    # 评分模式快速切换
    cur_mode = st.session_state.get("grading_mode", "relaxed")
    mode_names = {"relaxed": "宽松", "normal": "标准", "strict": "严格", "custom": "自定义"}

    # 读 config 看有没有自定义预设
    config_path = "config.yaml"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except Exception:
        cfg = {}
    custom_presets = cfg.get("custom_presets") or {}
    all_modes = ["relaxed", "normal", "strict"] + list(custom_presets.keys()) + ["custom"]
    if cur_mode not in all_modes:
        cur_mode = "relaxed"

    mode_labels = {}
    for m in all_modes:
        if m in mode_names:
            mode_labels[m] = mode_names[m]
        elif m in custom_presets:
            mode_labels[m] = f"⭐ {m}"
        else:
            mode_labels[m] = m

    new_mode = st.selectbox(
        "评分模式",
        all_modes,
        index=all_modes.index(cur_mode),
        format_func=lambda x: mode_labels.get(x, x),
        key="sidebar_mode"
    )
    if new_mode != cur_mode:
        st.session_state.grading_mode = new_mode
        cfg.setdefault("grading", {})["mode"] = new_mode
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        st.rerun()

    st.divider()

    # 个人信息
    with st.expander("👤 个人信息"):
        st.caption(f"姓名：{teacher}")
        st.caption(f"角色：阅卷老师")
        st.caption(f"当前模式：{mode_labels.get(cur_mode, cur_mode)}")
        new_pw = st.text_input("修改密码", type="password", key="sb_pwd")
        if new_pw and st.button("确认修改", key="sb_pwd_btn"):
            uname = st.session_state.get("username", "admin")
            users = load_users()
            u = users.get(uname, {})
            save_user(uname, new_pw, u.get("display_name", uname), u.get("role", "teacher"))
            st.success("密码已修改")

    # 常见问题
    with st.expander("❓ 常见问题"):
        st.caption("**Q: 如何导入评分标准？**")
        st.caption("A: 在「阅卷」页上传 .docx 评分标准文档，系统自动解析。")
        st.caption("**Q: 支持哪些试卷格式？**")
        st.caption("A: .docx 格式。将试卷放入 data/papers/班级名/ 下。")
        st.caption("**Q: 评分模式有什么区别？**")
        st.caption("A: 宽松→有做就给分；标准→平衡；严格→有错必扣。")
        st.caption("**Q: 查重怎么用？**")
        st.caption("A: 阅卷时勾选「自动查重」，完成后下载查重报告。")

    # 使用说明
    with st.expander("📖 使用说明"):
        st.caption("**1. 导入评分标准** → 阅卷页上传评分标准文档")
        st.caption("**2. 准备试卷** → 放入 data/papers/班级名/ 文件夹")
        st.caption("**3. 开始阅卷** → 选择班级 → 点击开始阅卷")
        st.caption("**4. 查看结果** → 历史结果页查看成绩分布和明细")
        st.caption("**5. 导出** → 下载班级汇总 / 个人明细 / 查重报告")
        st.caption(f"API: DeepSeek | 数据库: SQLite | 默认端口: 8501")

    st.divider()

    # 退出
    if st.button("🚪 退出登录", use_container_width=True):
        st.session_state.authenticated = False
        tf = "data/.session_token"
        if os.path.exists(tf): os.remove(tf)
        st.rerun()
