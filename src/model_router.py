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
        "image_limit": 0,
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
        "image_limit": 0,
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
        "image_limit": 10,
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
        "image_limit": 5,
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
        "image_limit": 20,
        "cost_per_1M_input": 3.0,
        "cost_per_1M_output": 15.0,
        "base_url": "https://api.anthropic.com/v1",
        "env_key": "ANTHROPIC_API_KEY",
        "strength": "multimodal",
        "description": "Claude Sonnet · 视觉+长文评分",
    },
    "qwen-vl-plus": {
        "provider": "openai_compat",
        "vision": True,
        "max_tokens": 32768,
        "image_limit": 5,
        "cost_per_1M_input": 1.5,     # RMB（降价后约0.3）
        "cost_per_1M_output": 4.5,    # RMB（降价后约0.9）
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env_key": "BAILIAN_KEY",
        "strength": "cheap_vision",
        "description": "Qwen-VL-Plus · 高性价比视觉，5图",
    },
    "qwen-vl-max": {
        "provider": "openai_compat",
        "vision": True,
        "max_tokens": 32768,
        "image_limit": 10,
        "cost_per_1M_input": 3.0,     # RMB（降价后约0.6）
        "cost_per_1M_output": 12.0,   # RMB（降价后约2.4）
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env_key": "BAILIAN_KEY",
        "strength": "multimodal",
        "description": "Qwen-VL-Max · 旗舰视觉，10图，能力强",
    },
    "glm-4v-flash": {
        "provider": "openai_compat",
        "vision": True,
        "max_tokens": 1024,           # 智谱限制：max_tokens ∈ [1, 1024]
        "image_limit": 1,             # 智谱限制：仅支持单张图片
        "cost_per_1M_input": 0.5,     # RMB · ¥0.5/1M (实际免费)
        "cost_per_1M_output": 2.0,    # RMB · ¥2/1M (实际免费)
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "env_key": "ZHIPU_KEY",
        "strength": "cheap_vision",
        "description": "GLM-4V-Flash · 免费，仅1图，输出1K",
    },
    "glm-4.6v-flash": {
        "provider": "openai_compat",
        "vision": True,
        "max_tokens": 1024,           # 待验证，保守设1024
        "image_limit": 1,             # 待验证，Flash版通常限1图
        "cost_per_1M_input": 0.0,     # 免费
        "cost_per_1M_output": 0.0,    # 免费
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "env_key": "ZHIPU_KEY",
        "strength": "cheap_vision",
        "description": "GLM-4.6V-Flash · 免费视觉，能力待验证",
    },
    "glm-4v": {
        "provider": "openai_compat",
        "vision": True,
        "max_tokens": 4096,           # 智谱旗舰视觉
        "image_limit": 5,             # 智谱旗舰：最多5张
        "cost_per_1M_input": 5.0,     # RMB
        "cost_per_1M_output": 5.0,
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "env_key": "ZHIPU_KEY",
        "strength": "multimodal",
        "description": "GLM-4V · 付费旗舰，5图，输出4K",
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
        # 视觉题模型（阿里云 qwen-vl-plus 5图，性价比最高）
        "vision_model": rc.get("vision_model", "qwen-vl-plus"),
        # 深度推理模型
        "reasoning_model": rc.get("reasoning_model", "deepseek-reasoner"),
        # 档位判定模型（轻量）
        "tier_model": rc.get("tier_model", "deepseek-chat"),
        # fallback 链
        "vision_fallback": rc.get("vision_fallback", ["qwen-vl-max", "glm-4v", "glm-4v-flash"]),
        "text_fallback": rc.get("text_fallback", ["deepseek-chat"]),
        # 大分值题阈值（超过此分用高级模型）
        "high_value_threshold": rc.get("high_value_threshold", 25),
        "high_value_model": rc.get("high_value_model", "qwen-vl-max"),
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
#  底层调用（模块级，供 call_model 和 describe_images 共用）
# ============================================================
def _try_call_api(name: str, msgs: list, max_tokens: int = 4096, temperature: float = 0.3):
    """用指定模型调用 API，返回原始 response 对象"""
    info = MODEL_REGISTRY.get(name, {})
    cl = _get_client(name)
    mt = min(max_tokens, info.get("max_tokens", 4096))
    return cl.chat.completions.create(
        model=name, max_tokens=mt, temperature=temperature, messages=msgs,
    )


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
    失败时依次尝试 fallback 链中的视觉模型，最后降级到文本。
    """
    import sys as _sys

    model_name, model_info = route_model(task_type, question_score)
    has_vision = model_info.get("vision", False)

    if max_tokens is None:
        max_tokens = min(model_info.get("max_tokens", 4096), 4096)
    else:
        # 钳制到模型实际支持的上限
        model_max = model_info.get("max_tokens", 4096)
        max_tokens = min(max_tokens, model_max)
    if temperature is None:
        temperature = 0.3

    # 视觉题但模型不支持
    if task_type == "vision" and not has_vision:
        prompt += "\n\n（当前模型不支持图像输入，请仅根据文本描述评分，视觉相关项给基础分。在评语中注明：因模型能力限制，未实际查看图像。）"

    # 按模型能力限制图片数量
    if images and has_vision and task_type == "vision":
        img_limit = model_info.get("image_limit", 5)
        if img_limit > 0 and len(images) > img_limit:
            images = images[:img_limit]

    # 构建消息
    if images and has_vision and task_type == "vision":
        content = _build_vision_content(prompt, images)
        messages = [{"role": "user", "content": content}]
    else:
        messages = [{"role": "user", "content": prompt}]

    try:
        response = _try_call_api(model_name, messages, max_tokens, temperature)
        return {
            "content": response.choices[0].message.content,
            "tokens_in": response.usage.prompt_tokens if response.usage else 0,
            "tokens_out": response.usage.completion_tokens if response.usage else 0,
            "model_used": model_name,
        }
    except Exception as e:
        print(f"[model_router] {model_name} 调用失败: {str(e)[:200]}", file=_sys.stderr)

        # 视觉题：依次尝试 fallback 链中的视觉模型
        if task_type == "vision" and images:
            rc = get_router_config()
            for fb_name in rc.get("vision_fallback", []):
                if fb_name == model_name:
                    continue
                info = MODEL_REGISTRY.get(fb_name, {})
                if not info.get("vision"):
                    continue
                if not _model_available(fb_name):
                    continue
                # 按 fallback 模型能力重新限制图片
                fb_limit = info.get("image_limit", 5)
                fb_images = images[:fb_limit] if fb_limit > 0 and len(images) > fb_limit else images
                try:
                    fb_msgs = [{"role": "user", "content": _build_vision_content(prompt, fb_images)}]
                    response = _try_call_api(fb_name, fb_msgs, max_tokens, temperature)
                    print(f"[model_router] 回退到 {fb_name} 成功", file=_sys.stderr)
                    return {
                        "content": response.choices[0].message.content,
                        "tokens_in": response.usage.prompt_tokens if response.usage else 0,
                        "tokens_out": response.usage.completion_tokens if response.usage else 0,
                        "model_used": f"{fb_name}(fallback)",
                    }
                except Exception as e2:
                    print(f"[model_router] fallback {fb_name} 也失败: {str(e2)[:200]}", file=_sys.stderr)

        # 最后降级为文本模型
        if model_name != "deepseek-chat":
            try:
                response = _try_call_api("deepseek-chat", [{"role": "user", "content": prompt}], max_tokens, temperature)
                return {
                    "content": response.choices[0].message.content,
                    "tokens_in": response.usage.prompt_tokens if response.usage else 0,
                    "tokens_out": response.usage.completion_tokens if response.usage else 0,
                    "model_used": "deepseek-chat(fallback)",
                }
            except Exception as e2:
                print(f"[model_router] fallback deepseek-chat 也失败: {str(e2)[:200]}", file=_sys.stderr)
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
            }
        })
    return content


# ============================================================
#  两阶段评分 Stage 1：视觉模型描述图片（省钱核心）
# ============================================================
def describe_images(images: list, question_name: str = "", question_score: int = 10) -> str:
    """
    让视觉模型描述图片内容，只返回文字描述，不做评分。

    这是两阶段评分流水线的第一阶段：
      Stage 1: 视觉模型看图 → 输出文字描述（输入token贵但输出少）
      Stage 2: DeepSeek文本模型 → 根据描述评分（输出token极便宜）

    失败时自动 fallback，全挂返回空字符串。
    """
    import sys as _sys

    if not images:
        return ""

    rc = get_router_config()
    model_name = rc["vision_model"]

    # 大分值用高级模型
    if question_score >= rc["high_value_threshold"]:
        model_name = rc["high_value_model"]

    # 检查并 fallback
    if not _model_available(model_name):
        found = False
        for fb in rc.get("vision_fallback", []):
            if _model_available(fb) and MODEL_REGISTRY.get(fb, {}).get("vision"):
                model_name = fb
                found = True
                break
        if not found:
            print(f"[model_router] 无可用的视觉模型，跳过图片描述", file=_sys.stderr)
            return ""

    info = MODEL_REGISTRY.get(model_name, {})
    img_limit = info.get("image_limit", 5)
    if img_limit > 0 and len(images) > img_limit:
        images = images[:img_limit]

    desc_prompt = f"""请详细描述以下图片的内容。这是一道「{question_name}」题的学生作业提交截图、生成图或视频帧。

请按以下方面客观描述（不要评价好坏，不要打分）：
1. **整体内容**：看到了什么主题、场景、元素
2. **文字信息**：图片中出现的所有文字、标题、标签
3. **视觉质量**：配色、排版、清晰度、设计风格
4. **技术细节**：图片尺寸、格式等可见信息
5. **如果是视频帧**：人物服饰、背景环境、画面构图、光线"""

    content = _build_vision_content(desc_prompt, images)
    messages = [{"role": "user", "content": content}]

    def _try_desc(name, msgs):
        info = MODEL_REGISTRY.get(name, {})
        mt = min(1024, info.get("max_tokens", 1024))  # 描述不需要长输出
        return _try_call_api(name, msgs, max_tokens=mt, temperature=0.2)

    try:
        response = _try_desc(model_name, messages)
        desc = response.choices[0].message.content
        tokens = response.usage.prompt_tokens if response.usage else 0
        print(f"[model_router] 视觉描述完成 ({model_name}, {len(images)}图, {tokens} tokens入)", file=_sys.stderr)
        return desc
    except Exception as e:
        print(f"[model_router] 视觉描述失败 ({model_name}): {str(e)[:200]}", file=_sys.stderr)

        # Fallback 链
        for fb_name in rc.get("vision_fallback", []):
            if fb_name == model_name:
                continue
            fb_info = MODEL_REGISTRY.get(fb_name, {})
            if not fb_info.get("vision"):
                continue
            if not _model_available(fb_name):
                continue
            fb_limit = fb_info.get("image_limit", 5)
            fb_images = images[:fb_limit] if fb_limit > 0 and len(images) > fb_limit else images
            try:
                fb_msgs = [{"role": "user", "content": _build_vision_content(desc_prompt, fb_images)}]
                response = _try_desc(fb_name, fb_msgs)
                desc = response.choices[0].message.content
                print(f"[model_router] 视觉描述 fallback {fb_name} 成功", file=_sys.stderr)
                return desc
            except Exception as e2:
                print(f"[model_router] 视觉描述 fallback {fb_name} 也失败: {str(e2)[:200]}", file=_sys.stderr)

        return ""


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
                "image_limit": info.get("image_limit", 0),
                "max_tokens": info.get("max_tokens", 0),
                "cost_per_1M_input": info.get("cost_per_1M_input", 0),
                "description": info["description"],
            })
    return available


def available_keys() -> dict[str, bool]:
    """返回各平台 API Key 是否已配置"""
    return {
        "DeepSeek": bool(os.environ.get("DEEPSEEK_KEY", "")),
        "智谱(GLM)": bool(os.environ.get("ZHIPU_KEY", "")),
        "阿里云(Qwen)": bool(os.environ.get("BAILIAN_KEY", "")),
        "OpenAI": bool(os.environ.get("OPENAI_API_KEY", "")),
        "Anthropic": bool(os.environ.get("ANTHROPIC_API_KEY", "")),
    }


def model_tier_label(name: str) -> str:
    """模型能力的简短标签，给下拉框用"""
    info = MODEL_REGISTRY.get(name, {})
    if not info:
        return name
    if not info.get("vision", False):
        return "📝 纯文本"
    img = info.get("image_limit", 0)
    free = "🆓" if info.get("cost_per_1M_input", 1) == 0 else "💰"
    if img <= 1:
        return f"{free} 视觉·{img}图"
    return f"{free} 视觉·{img}图"


def models_for_dropdown() -> list[tuple[str, str]]:
    """
    返回下拉框选项列表 [(model_name, display_label), ...]
    只显示当前环境已配置Key的模型；一个都没有的话显示全部（让用户知道需要配Key）
    """
    avail = available_models()
    if avail:
        result = []
        for m in avail:
            label = f"{m['name']}  [{model_tier_label(m['name'])}]"
            result.append((m["name"], label))
        return result
    # 全都没Key → 显示所有模型 + 提示
    return [(name, f"{name} (需配Key)") for name in MODEL_REGISTRY]


def get_fallback_chain(current_model: str, task_type: str = "vision") -> list[str]:
    """
    获取当前模型失败后的降级链路。
    返回可依次尝试的模型名列表。
    """
    rc = get_router_config()
    chain = []
    if task_type == "vision":
        for fb in rc.get("vision_fallback", []):
            if fb != current_model and _model_available(fb):
                chain.append(fb)
    # 最后总是可以降级到纯文本
    if "deepseek-chat" not in chain and _model_available("deepseek-chat"):
        chain.append("deepseek-chat")
    return chain


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
