"""
LLM 调用封装 —— 支持 DeepSeek / Anthropic / OpenAI 兼容 API。
DeepSeek 不支持视觉，图像题自动降级为纯文字评分（提示词为主）。
"""
import json
import os
import re
import hashlib
import base64
from openai import OpenAI


_client = None
_config = {}
_vision_available = True


def init_llm(config: dict):
    """初始化 LLM 客户端，支持 DeepSeek / Anthropic / OpenAI 兼容 API"""
    global _client, _config, _vision_available
    _config = config

    provider = config.get("provider", "deepseek")
    api_key = config.get("api_key", "")
    base_url = config.get("base_url", "")

    # 自动从环境变量读取 key
    if not api_key:
        if provider == "deepseek":
            api_key = os.environ.get("DEEPSEEK_KEY", "")
        elif provider == "anthropic":
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        elif provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "")

    # 自动设置 base_url
    if not base_url:
        if provider == "deepseek":
            base_url = "https://api.deepseek.com/v1"
        elif provider == "openai":
            base_url = "https://api.openai.com/v1"

    _client = OpenAI(api_key=api_key, base_url=base_url)

    # 视觉能力检测
    if provider in ("deepseek",):
        _vision_available = False
        print("   [info] 当前模型不支持视觉，图像题将用纯文字评分（提示词为主）")
    else:
        _vision_available = True


def _call_text(prompt: str, model: str = None, max_tokens: int = None) -> dict:
    """调用纯文字 LLM（OpenAI 兼容格式）"""
    if model is None:
        model = _config.get("model", "deepseek-chat")
    if max_tokens is None:
        max_tokens = _config.get("max_tokens", 2048)

    response = _client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=_config.get("temperature", 0.3),
        messages=[{"role": "user", "content": prompt}],
    )

    return {
        "content": response.choices[0].message.content,
        "tokens_in": response.usage.prompt_tokens or 0,
        "tokens_out": response.usage.completion_tokens or 0,
    }


def _call_vision(prompt: str, image_paths: list, model: str = None,
                 max_tokens: int = None) -> dict:
    """调用视觉 LLM。如当前 provider 不支持视觉，自动降级为纯文字。"""
    if not _vision_available:
        return _call_text(prompt + "\n\n（注：当前模型不支持图像输入，请仅根据提示词文本评分，图像相关得分项给基础分）", model, max_tokens)

    if model is None:
        model = _config.get("vision_model", _config.get("model", "deepseek-chat"))
    if max_tokens is None:
        max_tokens = _config.get("max_tokens", 2048)

    # 构建 content 数组（OpenAI 格式）
    content = [{"type": "text", "text": prompt}]

    for img_path in image_paths:
        if not os.path.exists(img_path):
            continue
        with open(img_path, "rb") as f:
            img_data = base64.standard_b64encode(f.read()).decode("utf-8")

        ext = os.path.splitext(img_path)[1].lower()
        mime = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp",
        }.get(ext, "image/png")

        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime};base64,{img_data}",
                "detail": "low",   # 低分辨率，省 token
            }
        })

    response = _client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=_config.get("temperature", 0.3),
        messages=[{"role": "user", "content": content}],
    )

    return {
        "content": response.choices[0].message.content,
        "tokens_in": response.usage.prompt_tokens or 0,
        "tokens_out": response.usage.completion_tokens or 0,
    }


def grade_with_text(prompt: str, question_id: int) -> dict:
    """纯文字评分"""
    result = _call_text(prompt)
    scores = _parse_json(result["content"])
    return {
        **scores,
        "tokens_in": result["tokens_in"],
        "tokens_out": result["tokens_out"],
        "raw_response": result["content"],
    }


def grade_with_vision(prompt: str, image_paths: list, question_id: int) -> dict:
    """视觉评分（不支持视觉时自动降级为纯文字）"""
    result = _call_vision(prompt, image_paths)
    scores = _parse_json(result["content"])
    return {
        **scores,
        "tokens_in": result["tokens_in"],
        "tokens_out": result["tokens_out"],
        "raw_response": result["content"],
    }


def _parse_json(text: str) -> dict:
    """从 LLM 回复中提取 JSON"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {"总分": 0, "评语": f"JSON解析失败: {text[:150]}...", "parse_error": True}


def hash_prompt(prompt: str) -> str:
    return hashlib.md5(prompt.encode()).hexdigest()[:12]


def tokens_cost(tokens_in: int, tokens_out: int) -> float:
    """估算费用（美元）"""
    provider = _config.get("provider", "deepseek")
    if provider == "deepseek":
        # deepseek-chat: ¥1 / ¥4 per 1M tokens ≈ $0.14 / $0.55
        return round((tokens_in * 0.14 + tokens_out * 0.55) / 1_000_000, 4)
    elif provider == "anthropic":
        return round((tokens_in * 3 + tokens_out * 15) / 1_000_000, 4)
    else:
        # OpenAI gpt-4o-mini approximate
        return round((tokens_in * 0.15 + tokens_out * 0.6) / 1_000_000, 4)
