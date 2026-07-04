"""
多模型路由层 -- 能力声明 + 按任务类型分发 + fallback 链 + 费用控制
"""
import os, yaml, json
from openai import OpenAI


# ============================================================
#  模型能力声明
# ============================================================
MODEL_REGISTRY = {
    "deepseek-chat": {
        "provider": "deepseek",
        "vision": False,
        "max_tokens": 65536,
        "cost_per_1M_input": 1.0,    # RMB
        "cost_per_1M_output": 4.0,
        "base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_KEY",
        "strength": "text",           # text | vision | code
        "description": "DeepSeek-V3 · 纯文本能力强，极便宜",
    },
    "deepseek-reasoner": {
        "provider": "deepseek",
        "vision": False,
        "max_tokens": 65536,
        "cost_per_1M_input": 4.0,
        "cost_per_1M_output": 16.0,
        "base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_KEY",
        "strength": "reasoning",
        "description": "DeepSeek-R1 · 深度推理",
    },
    "gpt-4o": {
        "provider": "openai",
        "vision": True,
        "max_tokens": 128000,
        "cost_per_1M_input": 2.5,     # USD
        "cost_per_1M_output": 10.0,
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "strength": "multimodal",
        "description": "GPT-4o · 视觉+文本全能",
    },
    "gpt-4o-mini": {
        "provider": "openai",
        "vision": True,
        "max_tokens": 128000,
        "cost_per_1M_input": 0.15,
        "cost_per_1M_output": 0.6,
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "strength": "cheap_vision",
        "description": "GPT-4o-mini · 轻量视觉，初筛/档位判定",
    },
    "claude-sonnet-4-6": {
        "provider": "anthropic",
        "vision": True,
        "max_tokens": 200000,
        "cost_per_1M_input": 3.0,
        "cost_per_1M_output": 15.0,
        "base_url": "https://api.anthropic.com/v1",
        "env_key": "ANTHROPIC_API_KEY",
        "strength": "multimodal",
        "description": "Claude Sonnet · 视觉+长文评分",
    },
    "qwen-vl-max": {
        "provider": "openai_compat",
        "vision": True,
        "max_tokens": 32768,
        "cost_per_1M_input": 3.0,     # RMB
        "cost_per_1M_output": 12.0,
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env_key": "DASHSCOPE_API_KEY",
        "strength": "multimodal",
        "description": "Qwen-VL-Max · 国内合规，视觉能力强",
    },
    "glm-4v": {
        "provider": "openai_compat",
        "vision": True,
        "max_tokens": 128000,
        "cost_per_1M_input": 5.0,     # RMB
        "cost_per_1M_output": 5.0,
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "env_key": "ZHIPUAI_API_KEY",
        "strength": "multimodal",
        "description": "GLM-4V · 国内备选视觉模型",
    },
}


# ============================================================
#  路由配置（从 config.yaml 读取，覆盖默认）
# ============================================================
def load_router_config():
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}
    return cfg.get("model_router", {})


def get_router_config():
    """返回当前生效的路由配置"""
    rc = load_router_config()
    return {
        # 文本题模型（便宜优先）
        "text_model": rc.get("text_model", "deepseek-chat"),
        # 视觉题模型（能力优先）
        "vision_model": rc.get("vision_model", "gpt-4o-mini"),
        # 深度推理模型
        "reasoning_model": rc.get("reasoning_model", "deepseek-reasoner"),
        # 档位判定模型（轻量便宜）
        "tier_model": rc.get("tier_model", "gpt-4o-mini"),
        # fallback 链
        "vision_fallback": rc.get("vision_fallback", ["gpt-4o", "qwen-vl-max", "glm-4v"]),
        "text_fallback": rc.get("text_fallback", ["deepseek-chat"]),
        # 大分值题阈值（超过此分用高级模型）
        "high_value_threshold": rc.get("high_value_threshold", 20),
        "high_value_model": rc.get("high_value_model", "gpt-4o"),
    }


# ============================================================
#  客户端管理（懒加载 + 缓存）
# ============================================================
_clients = {}


def _get_client(model_name: str) -> OpenAI:
    """获取或创建模型客户端"""
    if model_name in _clients:
        return _clients[model_name]

    info = MODEL_REGISTRY.get(model_name)
    if not info:
        raise ValueError(f"未注册的模型: {model_name}")

    api_key = os.environ.get(info["env_key"], "")
    base_url = info.get("base_url", "")

    client = OpenAI(api_key=api_key, base_url=base_url)
    _clients[model_name] = client
    return client


# ============================================================
#  核心路由
# ============================================================
def route_model(task_type: str, question_score: int = 10) -> tuple:
    """
    按任务类型 + 题目分值选择最优模型。

    返回: (model_name, model_info_dict)
    """
    rc = get_router_config()

    if task_type == "vision":
        primary = rc["vision_model"]
        # 大分值用高级模型
        if question_score >= rc["high_value_threshold"]:
            primary = rc["high_value_model"]
        # 检查 primary 是否可用
        if _model_available(primary):
            return primary, MODEL_REGISTRY.get(primary, {})
        # fallback 链
        for fb in rc["vision_fallback"]:
            if _model_available(fb):
                return fb, MODEL_REGISTRY.get(fb, {})
        # 全挂：降级纯文字
        return "deepseek-chat", MODEL_REGISTRY["deepseek-chat"]

    elif task_type == "tier_detection":
        model = rc["tier_model"]
        if _model_available(model):
            return model, MODEL_REGISTRY.get(model, {})
        return "deepseek-chat", MODEL_REGISTRY["deepseek-chat"]

    elif task_type == "reasoning":
        model = rc["reasoning_model"]
        if _model_available(model):
            return model, MODEL_REGISTRY.get(model, {})
        return "deepseek-chat", MODEL_REGISTRY["deepseek-chat"]

    else:  # text
        model = rc["text_model"]
        # 大分值用高级模型
        if question_score >= rc["high_value_threshold"]:
            model = rc["high_value_model"]
        if _model_available(model):
            return model, MODEL_REGISTRY.get(model, {})
        for fb in rc["text_fallback"]:
            if _model_available(fb):
                return fb, MODEL_REGISTRY.get(fb, {})
        return "deepseek-chat", MODEL_REGISTRY["deepseek-chat"]


def _model_available(model_name: str) -> bool:
    """检查模型是否可用（环境变量已配置）"""
    info = MODEL_REGISTRY.get(model_name)
    if not info:
        return False
    api_key = os.environ.get(info["env_key"], "")
    return bool(api_key)


# ============================================================
#  统一调用接口
# ============================================================
def call_model(
    prompt: str,
    task_type: str = "text",
    images: list = None,
    question_score: int = 10,
    temperature: float = None,
    max_tokens: int = None,
) -> dict:
    """
    统一 LLM 调用入口。
    根据 task_type 自动路由模型，视觉题传入 images 列表。
    """
    model_name, model_info = route_model(task_type, question_score)
    client = _get_client(model_name)
    has_vision = model_info.get("vision", False)

    if max_tokens is None:
        max_tokens = min(model_info.get("max_tokens", 4096), 4096)
    if temperature is None:
        temperature = 0.3

    # 视觉题但模型不支持
    if task_type == "vision" and not has_vision:
        prompt += "\n\n（当前模型不支持图像输入，请仅根据文本描述评分，视觉相关项给基础分。在评语中注明：因模型能力限制，未实际查看图像。）"

    # 构建消息
    if images and has_vision and task_type == "vision":
        content = _build_vision_content(prompt, images)
        messages = [{"role": "user", "content": content}]
    else:
        messages = [{"role": "user", "content": prompt}]

    try:
        response = client.chat.completions.create(
            model=model_name,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages,
        )
        return {
            "content": response.choices[0].message.content,
            "tokens_in": response.usage.prompt_tokens if response.usage else 0,
            "tokens_out": response.usage.completion_tokens if response.usage else 0,
            "model_used": model_name,
        }
    except Exception as e:
        # 尝试 fallback: 降级为 deepseek text
        if model_name != "deepseek-chat":
            try:
                client2 = _get_client("deepseek-chat")
                response = client2.chat.completions.create(
                    model="deepseek-chat",
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                )
                return {
                    "content": response.choices[0].message.content,
                    "tokens_in": response.usage.prompt_tokens if response.usage else 0,
                    "tokens_out": response.usage.completion_tokens if response.usage else 0,
                    "model_used": "deepseek-chat(fallback)",
                }
            except Exception:
                pass
        return {
            "content": f'{{"总分": 0, "评语": "LLM调用失败: {str(e)[:100]}"}}',
            "tokens_in": 0,
            "tokens_out": 0,
            "model_used": "none(error)",
        }


def _build_vision_content(prompt: str, image_paths: list) -> list:
    """构建视觉模型的 content 数组"""
    import base64 as b64
    content = [{"type": "text", "text": prompt}]
    for img_path in image_paths:
        if not os.path.exists(img_path):
            continue
        with open(img_path, "rb") as f:
            img_data = b64.standard_b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(img_path)[1].lower()
        mime_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp",
        }
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_map.get(ext, 'image/png')};base64,{img_data}",
                "detail": "low",
            }
        })
    return content


# ============================================================
#  可用性检测
# ============================================================
def available_models() -> list:
    """返回当前环境可用的模型列表"""
    available = []
    for name, info in MODEL_REGISTRY.items():
        if os.environ.get(info["env_key"], ""):
            available.append({
                "name": name,
                "vision": info["vision"],
                "description": info["description"],
            })
    return available


def model_capabilities() -> dict:
    """返回各 provider 的能力矩阵"""
    caps = {}
    for name, info in MODEL_REGISTRY.items():
        provider = info["provider"]
        if provider not in caps:
            caps[provider] = {"vision": False, "max_tokens": 0}
        caps[provider]["vision"] = caps[provider]["vision"] or info["vision"]
        caps[provider]["max_tokens"] = max(caps[provider]["max_tokens"], info["max_tokens"])
    return caps
