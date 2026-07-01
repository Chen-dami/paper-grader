"""
共享工具函数 —— 页面和 app.py 都从这里 import，避免循环导入
"""
import os, hashlib, yaml, json

DEFAULT_PASSWORD_HASH = "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9"


def hpw(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()


def load_teacher() -> tuple[str, str]:
    """返回 (password_hash, teacher_name)"""
    pf = "data/.teacher_pwd"
    if os.path.exists(pf):
        with open(pf, encoding="utf-8") as f:
            ls = f.read().strip().split("\n")
            if len(ls) >= 2:
                return ls[0].strip(), ls[1].strip()
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
