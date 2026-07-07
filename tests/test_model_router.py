"""
model_router.py 测试 —— 多模型路由层
覆盖：MODEL_REGISTRY、路由逻辑、客户端管理、可用性检测、视觉内容构建
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import model_router as router


class TestModelRegistry:
    """MODEL_REGISTRY 模型注册表"""

    def test_glm_4v_flash_registered(self):
        """glm-4v-flash 已注册"""
        assert "glm-4v-flash" in router.MODEL_REGISTRY
        info = router.MODEL_REGISTRY["glm-4v-flash"]
        assert info["provider"] == "openai_compat"
        assert info["vision"] is True
        assert info["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
        assert info["env_key"] == "ZHIPU_KEY"
        assert info["strength"] == "cheap_vision"

    def test_glm_4v_registered(self):
        """glm-4v 保留注册"""
        assert "glm-4v" in router.MODEL_REGISTRY
        info = router.MODEL_REGISTRY["glm-4v"]
        assert info["vision"] is True
        assert info["env_key"] == "ZHIPU_KEY"
        assert info["strength"] == "multimodal"

    def test_all_vision_models_have_vision_true(self):
        """所有 vision-capable 模型 vision=True"""
        for name, info in router.MODEL_REGISTRY.items():
            if info.get("strength") in ("multimodal", "cheap_vision"):
                assert info["vision"] is True, f"{name} 应标记 vision=True"

    def test_registry_has_required_fields(self):
        """每个模型都有必需字段"""
        required = ["provider", "vision", "max_tokens", "base_url", "env_key", "strength"]
        for name, info in router.MODEL_REGISTRY.items():
            for field in required:
                assert field in info, f"{name} 缺少字段 {field}"

    def test_glm_models_same_env_key(self):
        """glm-4v 和 glm-4v-flash 使用相同环境变量"""
        flash_key = router.MODEL_REGISTRY["glm-4v-flash"]["env_key"]
        standard_key = router.MODEL_REGISTRY["glm-4v"]["env_key"]
        assert flash_key == standard_key == "ZHIPU_KEY"

    def test_glm_4v_flash_cheaper_than_glm_4v(self):
        """glm-4v-flash 费用低于 glm-4v"""
        flash_cost = router.MODEL_REGISTRY["glm-4v-flash"]["cost_per_1M_input"]
        standard_cost = router.MODEL_REGISTRY["glm-4v"]["cost_per_1M_input"]
        assert flash_cost < standard_cost, "glm-4v-flash 应比 glm-4v 便宜"


class TestRouterConfig:
    """路由配置加载"""

    def test_get_router_config_returns_expected_keys(self):
        """返回完整配置"""
        rc = router.get_router_config()
        expected_keys = [
            "text_model", "vision_model", "reasoning_model",
            "tier_model", "vision_fallback", "text_fallback",
            "high_value_threshold", "high_value_model",
        ]
        for k in expected_keys:
            assert k in rc, f"缺少配置键 {k}"

    def test_default_vision_model_is_qwen_vl_plus(self):
        """默认视觉模型为 qwen-vl-plus（阿里云性价比最高）"""
        rc = router.get_router_config()
        assert rc["vision_model"] == "qwen-vl-plus"

    def test_vision_fallback_includes_glm_4v_flash(self):
        """视觉 fallback 包含 glm-4v-flash"""
        rc = router.get_router_config()
        assert "glm-4v-flash" in rc["vision_fallback"]

    def test_vision_fallback_includes_glm_4v(self):
        """视觉 fallback 仍保留 glm-4v"""
        rc = router.get_router_config()
        assert "glm-4v" in rc["vision_fallback"]


class TestModelAvailable:
    """模型可用性检测"""

    @patch.dict(os.environ, {"ZHIPU_KEY": "test-key-123"}, clear=True)
    def test_glm_models_available_with_key(self):
        """设置 ZHIPU_KEY 后两个模型都可用"""
        assert router._model_available("glm-4v-flash") is True
        assert router._model_available("glm-4v") is True

    @patch.dict(os.environ, {}, clear=True)
    def test_glm_models_unavailable_without_key(self):
        """未设置 key 时不可用"""
        # 清除所有可能的环境变量
        for k in list(os.environ.keys()):
            if k in ("DEEPSEEK_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                      "BAILIAN_KEY", "ZHIPU_KEY"):
                os.environ.pop(k, None)
        assert router._model_available("glm-4v-flash") is False
        assert router._model_available("glm-4v") is False


class TestAvailableModels:
    """available_models 列表"""

    @patch.dict(os.environ, {"ZHIPU_KEY": "test", "DEEPSEEK_KEY": "test"}, clear=True)
    def test_glm_models_in_available_list(self):
        """有 API key 时模型出现在可用列表"""
        models = router.available_models()
        names = [m["name"] for m in models]
        assert "glm-4v-flash" in names
        assert "glm-4v" in names

    @patch.dict(os.environ, {}, clear=True)
    def test_no_models_without_keys(self):
        """无 key 时返回空列表"""
        models = router.available_models()
        assert len(models) == 0


class TestModelCapabilities:
    """model_capabilities 能力矩阵"""

    def test_zhipu_provider_has_vision(self):
        """智谱 provider 标记有视觉能力"""
        caps = router.model_capabilities()
        assert "openai_compat" in caps
        assert caps["openai_compat"]["vision"] is True


class TestRouteModel:
    """路由逻辑"""

    @patch.dict(os.environ, {"ZHIPU_KEY": "test-key", "DEEPSEEK_KEY": "test-key"}, clear=True)
    def test_route_vision_task_falls_back_to_glm_4v(self):
        """视觉任务：无BAILIAN_KEY时fallback到智谱glm-4v"""
        model_name, info = router.route_model("vision", question_score=10)
        # 默认 qwen-vl-plus 不可用（无BAILIAN_KEY）→ fallback glm-4v
        assert model_name == "glm-4v"
        assert info["vision"] is True
        assert info["provider"] == "openai_compat"


class TestBuildVisionContent:
    """视觉 content 构建"""

    def test_build_vision_content_text_only(self):
        """纯文本提示"""
        content = router._build_vision_content("描述这张图", [])
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "描述这张图"

    def test_build_vision_content_with_image(self, tmp_dir):
        """包含图片"""
        # 创建测试 PNG
        img_path = os.path.join(tmp_dir, "test.png")
        _create_test_png(img_path)

        content = router._build_vision_content("描述", [img_path])
        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"
        # detail 参数已移除（OpenAI专属，会导致智谱等API报错）
        assert "data:image/png;base64," in content[1]["image_url"]["url"]

    def test_build_vision_content_skips_missing(self):
        """跳过不存在的图片"""
        content = router._build_vision_content("描述", ["/nonexistent/img.png"])
        assert len(content) == 1
        assert content[0]["type"] == "text"


class TestGetClient:
    """客户端管理"""

    @patch.dict(os.environ, {"ZHIPU_KEY": "test-key"}, clear=True)
    def test_get_client_for_glm_models(self):
        """glm 模型共享客户端（相同 base_url + key 可能缓存）"""
        client = router._get_client("glm-4v-flash")
        assert client is not None
        assert client.api_key == "test-key"

    def test_get_client_unknown_model_raises(self):
        """未注册模型抛异常"""
        with pytest.raises(ValueError, match="未注册的模型"):
            router._get_client("nonexistent-model")


class TestCallModel:
    """统一调用接口"""

    @patch.dict(os.environ, {"ZHIPU_KEY": "test-key"}, clear=True)
    @patch.object(router, '_get_client')
    def test_call_vision_with_glm(self, mock_get_client):
        """使用智谱视觉模型调用（回退到glm-4v，因无BAILIAN_KEY）"""
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = '{"总分": 18, "评语": "很好"}'
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 500
        mock_response.usage.completion_tokens = 100
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = router.call_model(
            prompt="评分：请评鉴这张海报",
            task_type="vision",
            images=[],
            question_score=10,
        )

        assert result["content"] == '{"总分": 18, "评语": "很好"}'
        # 无BAILIAN_KEY → 回退到glm-4v
        assert result["model_used"] == "glm-4v"
        assert result["tokens_in"] == 500
        assert result["tokens_out"] == 100

    @patch.dict(os.environ, {"ZHIPU_KEY": "test-key", "DEEPSEEK_KEY": "test-key"}, clear=True)
    @patch.object(router, '_get_client')
    def test_call_fallback_on_api_error(self, mock_get_client):
        """API 错误时 fallback 到 deepseek-chat"""
        mock_glm = MagicMock()
        mock_glm.chat.completions.create.side_effect = Exception("API 500 error")

        mock_ds = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = '{"总分": 10, "评语": "降级评分"}'
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 200
        mock_response.usage.completion_tokens = 50
        mock_ds.chat.completions.create.return_value = mock_response

        # route_model 返回 glm-4v（无BAILIAN_KEY时fallback链的第一个可用模型）
        mock_get_client.side_effect = lambda name: {
            "glm-4v": mock_glm, "glm-4v-flash": mock_glm, "deepseek-chat": mock_ds
        }[name]

        result = router.call_model(
            prompt="评分",
            task_type="vision",
            images=[],
            question_score=10,
        )

        # 应该降级到 deepseek-chat
        assert "fallback" in result["model_used"] or result["model_used"] == "deepseek-chat(fallback)"
        assert result["content"] == '{"总分": 10, "评语": "降级评分"}'


def _create_test_png(path):
    """创建最小 PNG 文件（仅用于测试编码）"""
    import struct, zlib
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    ihdr = struct.pack('>IIBBBBB', 16, 16, 8, 2, 0, 0, 0)
    raw = b''
    for y in range(16):
        raw += b'\x00' + b'\xff\x00\x00' * 16  # red pixels
    compressed = zlib.compress(raw)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(chunk(b'IHDR', ihdr))
        f.write(chunk(b'IDAT', compressed))
        f.write(chunk(b'IEND', b''))
