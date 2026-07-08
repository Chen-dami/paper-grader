"""
阅卷会话覆盖设置 —— AI 助手可通过自然语言修改，阅卷页读取。
与 config.yaml 的关系：config.yaml 是默认值，overrides 是本次会话的临时覆盖。
"""
import streamlit as st

# st.session_state 键名
OVERRIDES_KEY = "grading_overrides"

# 可覆盖的设置项及其选项
AVAILABLE_OVERRIDES = {
    "vision_strategy": {
        "label": "视觉策略",
        "options": ["paid_vision", "free_vision", "text_only"],
        "option_labels": {
            "paid_vision": "付费视觉（5张图，最准）",
            "free_vision": "免费视觉（1张图，零费用）",
            "text_only": "纯文字（不看图，最快）",
        },
    },
    "mode": {
        "label": "评分模式",
        "options": ["strict", "normal", "relaxed"],
        "option_labels": {
            "strict": "严格",
            "normal": "适中",
            "relaxed": "宽松",
        },
    },
}


def init_overrides():
    """初始化会话覆盖（如果不存在）"""
    if OVERRIDES_KEY not in st.session_state:
        st.session_state[OVERRIDES_KEY] = {}


def get_overrides() -> dict:
    """获取当前会话的所有覆盖设置"""
    init_overrides()
    return st.session_state[OVERRIDES_KEY]


def set_override(key: str, value):
    """设置一个覆盖项"""
    init_overrides()
    if key in AVAILABLE_OVERRIDES and value in AVAILABLE_OVERRIDES[key]["options"]:
        st.session_state[OVERRIDES_KEY][key] = value
        return True
    return False


def clear_overrides():
    """清除所有覆盖，恢复 config.yaml 默认"""
    st.session_state[OVERRIDES_KEY] = {}


def clear_override(key: str):
    """清除单个覆盖项"""
    if OVERRIDES_KEY in st.session_state:
        st.session_state[OVERRIDES_KEY].pop(key, None)


def get_effective_config(yaml_config: dict) -> dict:
    """
    合并 config.yaml + 会话覆盖，返回生效的配置。
    阅卷页和评分函数应使用此函数获取配置。
    """
    overrides = get_overrides()
    result = dict(yaml_config)  # shallow copy

    # 合并 vision_strategy
    if "vision_strategy" in overrides:
        result["vision_strategy"] = overrides["vision_strategy"]

    # 合并 grading mode
    if "mode" in overrides:
        grading = dict(result.get("grading", {}))
        grading["mode"] = overrides["mode"]
        result["grading"] = grading

    return result


def has_overrides() -> bool:
    """是否有任何覆盖设置"""
    return bool(get_overrides())


def describe_overrides() -> str:
    """人类可读的覆盖描述"""
    overrides = get_overrides()
    if not overrides:
        return "无覆盖，使用 config.yaml 默认设置"

    parts = []
    for key, info in AVAILABLE_OVERRIDES.items():
        if key in overrides:
            val = overrides[key]
            label = info["option_labels"].get(val, val)
            parts.append(f"{info['label']} → {label}")

    return "；".join(parts) if parts else "无覆盖"
