"""
共享工具函数 —— 页面和 app.py 都从这里 import，避免循环导入
"""
import os, hashlib, yaml, json

DEFAULT_PASSWORD_HASH = "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9"


def hpw(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()


USERS_PATH = "data/users.json"


def _ensure_users_file():
    """确保 users.json 存在，首次运行自动生成默认 admin 账号"""
    if not os.path.exists(USERS_PATH):
        os.makedirs(os.path.dirname(USERS_PATH), exist_ok=True)
        default = {
            "admin": {
                "password_hash": DEFAULT_PASSWORD_HASH,
                "display_name": "admin",
                "role": "admin"
            }
        }
        with open(USERS_PATH, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)


def load_users() -> dict:
    """读取用户表 {username: {password_hash, display_name, role}}"""
    _ensure_users_file()
    with open(USERS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_user(username: str, password: str) -> tuple[str, str] | None:
    """
    验证用户名密码，返回 (display_name, role) 或 None
    """
    users = load_users()
    user = users.get(username)
    if user and user.get("password_hash") == hpw(password):
        return user.get("display_name", username), user.get("role", "teacher")
    return None


def save_user(username: str, password: str, display_name: str, role: str = "teacher"):
    """新增或更新用户"""
    users = load_users()
    users[username] = {
        "password_hash": hpw(password),
        "display_name": display_name,
        "role": role,
    }
    with open(USERS_PATH, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def load_teacher() -> tuple[str, str]:
    """
    兼容旧接口 —— 返回 (password_hash, teacher_name)
    从 users.json 取第一个 admin 用户
    """
    users = load_users()
    for uname, udata in users.items():
        if udata.get("role") == "admin":
            return udata["password_hash"], udata["display_name"]
    # fallback
    return DEFAULT_PASSWORD_HASH, "教师"


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_rubric(path: str = "data/rubric.json") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_runtime_config(config_path: str = "config.yaml") -> dict:
    """将 config.yaml + session_state 合并为运行时配置"""
    import streamlit as st
    config = load_config(config_path)
    key = os.environ.get("DEEPSEEK_KEY", "") or st.session_state.get("api_key_input", "")
    config.setdefault("llm", {})["api_key"] = key
    mode = st.session_state.get("grading_mode", config.get("grading", {}).get("mode", "relaxed"))
    config.setdefault("grading", {})["mode"] = mode
    return config
