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

    if st.button("👤 个人信息", use_container_width=True):
        st.session_state.dialog_type = "profile"
    if st.button("❓ 常见问题", use_container_width=True):
        st.session_state.dialog_type = "faq"
    if st.button("📖 使用说明", use_container_width=True):
        st.session_state.dialog_type = "guide"

    st.divider()

    if st.button("🚪 退出登录", use_container_width=True):
        st.session_state.authenticated = False
        tf = "data/.session_token"
        if os.path.exists(tf): os.remove(tf)
        st.rerun()


if "dialog_type" not in st.session_state:
    st.session_state.dialog_type = None

_dtype = st.session_state.dialog_type
if _dtype is not None:
    st.session_state.dialog_type = None
    if _dtype == "profile":
        _open_profile_dialog(teacher)
    elif _dtype == "faq":
        _open_faq_dialog()
    elif _dtype == "guide":
        _open_guide_dialog()


@st.dialog("个人信息", width="small")
def _open_profile_dialog(teacher_name):
    uname = st.session_state.get("username", "admin")
    users = load_users()
    u = users.get(uname, {})
    st.text_input("用户名", value=uname, disabled=True)
    st.text_input("角色", value=u.get("role", "teacher"), disabled=True)
    new_display = st.text_input("显示名", value=u.get("display_name", uname))
    col1, col2 = st.columns(2)
    with col1:
        new_pw = st.text_input("新密码", type="password", placeholder="留空不修改")
    with col2:
        confirm_pw = st.text_input("确认密码", type="password", placeholder="再次输入")
    if st.button("保存", type="primary", use_container_width=True):
        if new_pw and new_pw != confirm_pw:
            st.error("两次密码不一致")
        elif new_pw and len(new_pw) < 6:
            st.error("密码至少6位")
        else:
            if new_pw:
                save_user(uname, new_pw, new_display.strip() or uname, u.get("role", "teacher"))
            else:
                import json
                users2 = load_users()
                users2[uname]["display_name"] = new_display.strip() or uname
                with open("data/users.json", "w", encoding="utf-8") as f:
                    json.dump(users2, f, ensure_ascii=False, indent=2)
            st.session_state.teacher_name = f"{new_display.strip() or uname}老师"
            st.success("已保存")
            st.rerun()


@st.dialog("常见问题", width="large")
def _open_faq_dialog():
    faq_items = [
        ("如何导入评分标准？", "在「阅卷」页上传 .docx 评分标准文档，系统通过 AI 自动解析题目、评分项和提交要求。"),
        ("支持哪些试卷格式？", "仅支持 .docx 格式。试卷放入 `data/papers/班级名/` 文件夹，系统自动扫描识别。"),
        ("评分模式有什么区别？", "**宽松**：有做就给分，鼓励为主。\n\n**标准**：平衡给分，正常评判。\n\n**严格**：有错必扣，高标准要求。\n\n**自定义**：可自由设置各档位的分数比例。"),
        ("评分模式和题目权重是什么关系？",
         "**档位**控制答题质量→得分的乘数范围。例如20分题，「贴合主题」档在宽松模式下给 18-20 分，严格模式下给 15-20 分。\n\n"
         "**权重**即每道题的 `max_score`，决定该题在总分中的占比。例如 Q1=15分（15%），Q5=25分（25%）→ Q5 对总分影响更大。\n\n"
         "**最终总分 = Σ(题目i × 档位ratio)**，档位管单题给分高不高，权重管题目重不重要，二者独立。"),
        ("查重怎么用？", "阅卷时勾选「自动查重」，完成后在结果页下载查重报告。支持元数据、文本、图片、Excel 多维比对。"),
        ("大批量阅卷怎么加速？", "命令行模式支持多线程并行：`python main.py --workers 8`。系统还会自动缓存相同的 LLM 评分请求，省 token 也更快。"),
    ]
    search = st.text_input("搜索", placeholder="输入关键词过滤...", key="faq_search")
    items = faq_items if not search else [
        (q, a) for q, a in faq_items if search.lower() in q.lower() or search.lower() in a.lower()
    ]
    if not items:
        st.caption("未找到匹配的问题")
    for q, a in items:
        with st.expander(q):
            st.markdown(a)


@st.dialog("使用说明", width="large")
def _open_guide_dialog():
    st.markdown("""
| 步骤 | 操作 |
|------|------|
| 1. 导入评分标准 | 阅卷页 → 上传 .docx 评分标准文档 |
| 2. 准备试卷 | 将 .docx 放入 `data/papers/班级名/` |
| 3. 开始阅卷 | 选择班级 → 点击「开始阅卷」 |
| 4. 查看结果 | 历史结果页查看成绩分布和明细 |
| 5. 导出报告 | 下载班级汇总 / 个人明细(ZIP) / 查重报告 |

- 评分标准只需导入一次，换班级直接阅卷
- 命令行批量：`python main.py --workers 4 --check`
""")
