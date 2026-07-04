"""
个人信息 -- 头像 + 账号管理
"""
import streamlit as st
import os, sys, json
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.ui_style import inject; inject()
from src.utils import load_users, save_user, verify_user

if not st.session_state.get("authenticated", False):
    st.warning("请先登录")
    st.stop()

st.title("个人信息")

uname = st.session_state.get("username", "admin")
users = load_users()
user = users.get(uname, {})
display_name = user.get("display_name", uname)
role = user.get("role", "teacher")

AVATAR_DIR = os.path.join("data", "avatars")
os.makedirs(AVATAR_DIR, exist_ok=True)
AVATAR_PATH = os.path.join(AVATAR_DIR, f"{uname}.png")

# ============================================================
#  横向布局：头像 + 基本信息
# ============================================================
col_avatar, col_info = st.columns([1, 3])

with col_avatar:
    if os.path.exists(AVATAR_PATH):
        st.image(AVATAR_PATH, width=140)
    else:
        initial = display_name[0] if display_name else uname[0]
        st.markdown(f"""
        <div style="width:140px;height:140px;border-radius:50%;
        background:linear-gradient(135deg,#4A7C59,#6B9E7A);
        display:flex;align-items:center;justify-content:center;
        color:#fff;font-size:56px;font-weight:bold;
        border:3px solid #E8E4DA;margin:0 auto;">
        {initial}
        </div>
        """, unsafe_allow_html=True)

    uploaded = st.file_uploader("上传头像", type=["png", "jpg", "jpeg", "webp"],
                                label_visibility="collapsed")
    if uploaded:
        try:
            img = Image.open(uploaded).convert("RGB")
            w, h = img.size
            sz = min(w, h)
            left, top = (w - sz) // 2, (h - sz) // 2
            img = img.crop((left, top, left + sz, top + sz))
            img = img.resize((256, 256), Image.LANCZOS)
            img.save(AVATAR_PATH, "PNG")
            st.success("头像已更新")
            st.rerun()
        except Exception as e:
            st.error(f"上传失败: {e}")

    if os.path.exists(AVATAR_PATH):
        if st.button("删除头像", use_container_width=True):
            os.remove(AVATAR_PATH)
            st.rerun()

with col_info:
    st.subheader("基本信息")

    st.caption("用户名")
    st.text_input("u", value=uname, disabled=True, label_visibility="collapsed")

    st.caption("角色")
    st.text_input("r", value=role, disabled=True, label_visibility="collapsed")

    st.caption("显示名称")
    new_name = st.text_input("dn", value=display_name, label_visibility="collapsed",
                             placeholder="输入显示名称")

    if new_name != display_name:
        if st.button("保存显示名", type="primary"):
            users2 = load_users()
            users2[uname]["display_name"] = new_name.strip() or uname
            with open("data/users.json", "w", encoding="utf-8") as f:
                json.dump(users2, f, ensure_ascii=False, indent=2)
            st.session_state.teacher_name = f"{new_name.strip() or uname}老师"
            st.success("已保存")
            st.rerun()

# ============================================================
#  修改密码
# ============================================================
st.divider()
st.subheader("修改密码")

pw_col1, pw_col2, pw_col3 = st.columns(3)
with pw_col1:
    old_pw = st.text_input("当前密码", type="password", placeholder="输入当前密码")
with pw_col2:
    new_pw = st.text_input("新密码", type="password", placeholder="至少6位")
with pw_col3:
    confirm_pw = st.text_input("确认新密码", type="password", placeholder="再次输入")

if st.button("修改密码", type="primary"):
    if not old_pw:
        st.error("请输入当前密码")
    elif not new_pw:
        st.error("请输入新密码")
    elif len(new_pw) < 6:
        st.error("新密码至少6位")
    elif new_pw != confirm_pw:
        st.error("两次密码不一致")
    elif not verify_user(uname, old_pw):
        st.error("当前密码错误")
    else:
        save_user(uname, new_pw, new_name.strip() or display_name, role)
        st.success("密码已修改，请重新登录")
        st.session_state.authenticated = False
        tf = "data/.session_token"
        if os.path.exists(tf):
            os.remove(tf)
        st.rerun()

st.divider()
st.caption(f"登录方式：本地账号 | 数据目录：{os.path.abspath('data')}")
