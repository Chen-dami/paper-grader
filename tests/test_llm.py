"""
llm.py 测试 —— LLM 调用封装
覆盖：初始化、缓存机制、JSON解析、费用估算
"""
import os
import json
import pytest
from unittest.mock import patch, MagicMock

import src.llm as llm_mod


class TestJsonParsing:
    """_parse_json 三层兜底"""

    def test_parse_valid_json(self):
        result = llm_mod._parse_json('{"总分": 15, "评语": "不错"}')
        assert result["总分"] == 15
        assert result["评语"] == "不错"

    def test_parse_json_with_markdown_block(self):
        text = '''```json
{"总分": 13, "得分_1-1_主题契合度": 4}
```'''
        result = llm_mod._parse_json(text)
        assert result["总分"] == 13

    def test_parse_json_with_markdown_no_tag(self):
        text = '''```
{"总分": 13, "得分_1-1_主题契合度": 4}
```'''
        result = llm_mod._parse_json(text)
        assert result["总分"] == 13

    def test_parse_json_embedded_in_text(self):
        text = '一些前置文字 {"总分": 10, "评语": "及格"} 一些后置文字'
        result = llm_mod._parse_json(text)
        assert result["总分"] == 10

    def test_parse_nested_json(self):
        text = '''```json
{
  "得分_1-1_主题契合度": 5,
  "得分_1-2_文案内容适配": 4,
  "总分": 14,
  "评语": "主题把握准确，文案适配度好"
}
```'''
        result = llm_mod._parse_json(text)
        assert result["得分_1-1_主题契合度"] == 5
        assert result["总分"] == 14

    def test_parse_invalid_json_fallback(self):
        text = '这完全不是JSON格式的文本'
        result = llm_mod._parse_json(text)
        assert result.get("总分", 0) == 0
        assert "parse_error" in result or result.get("总分") == 0

    def test_parse_empty_string(self):
        result = llm_mod._parse_json("")
        assert result.get("总分", 0) == 0


class TestInitLLM:
    """LLM 初始化"""

    def test_init_deepseek_detects_no_vision(self):
        """DeepSeek 初始化自动标记无视觉能力"""
        config = {"provider": "deepseek", "api_key": "sk-test", "base_url": ""}
        llm_mod.init_llm(config)
        assert llm_mod._vision_available is False

    @patch.dict(os.environ, {"DEEPSEEK_KEY": "sk-env-test"})
    def test_init_reads_key_from_env(self):
        """从环境变量读取 API Key"""
        config = {"provider": "deepseek", "api_key": "", "base_url": ""}
        llm_mod.init_llm(config)

    def test_init_sets_config(self):
        config = {"provider": "deepseek", "api_key": "sk-test", "base_url": "https://custom.api"}
        llm_mod.init_llm(config)
        assert llm_mod._config["provider"] == "deepseek"


class TestCache:
    """LLM 结果缓存"""

    def setup_method(self):
        llm_mod.clear_cache()

    def test_cache_hit_on_second_call(self):
        """相同 prompt+model 第二次命中缓存"""
        with patch.object(llm_mod, '_call_text') as mock_call:
            mock_call.return_value = {
                "content": '{"总分": 15}', "tokens_in": 100, "tokens_out": 50,
            }
            llm_mod._config = {"model": "deepseek-chat", "provider": "deepseek"}

            # 第一次调用
            r1 = llm_mod.grade_with_text("测试prompt", 1)
            # 第二次调用（相同参数）
            r2 = llm_mod.grade_with_text("测试prompt", 1)

            # 第二次应该命中缓存
            assert r2["raw_response"].startswith("[cached]")
            # 实际 API 只调了一次
            assert mock_call.call_count == 1

    def test_different_prompt_different_cache(self):
        """不同 prompt 不命中缓存"""
        with patch.object(llm_mod, '_call_text') as mock_call:
            mock_call.return_value = {
                "content": '{"总分": 15}', "tokens_in": 100, "tokens_out": 50,
            }
            llm_mod._config = {"model": "deepseek-chat", "provider": "deepseek"}

            llm_mod.grade_with_text("prompt A", 1)
            llm_mod.grade_with_text("prompt B", 2)

            # 两次不同 prompt，各调一次 API
            assert mock_call.call_count == 2

    def test_cache_stats(self):
        """缓存统计"""
        llm_mod.clear_cache()
        stats = llm_mod.cache_stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_clear_cache(self):
        """清空缓存"""
        with patch.object(llm_mod, '_call_text') as mock_call:
            mock_call.return_value = {
                "content": '{"总分": 15}', "tokens_in": 100, "tokens_out": 50,
            }
            llm_mod._config = {"model": "deepseek-chat", "provider": "deepseek"}
            llm_mod.grade_with_text("test", 1)

            assert llm_mod.cache_stats()["size"] == 1

            llm_mod.clear_cache()
            assert llm_mod.cache_stats()["size"] == 0


class TestHashPrompt:
    """prompt 哈希"""

    def test_hash_stability(self):
        """相同 prompt 哈希一致"""
        h1 = llm_mod.hash_prompt("测试文本")
        h2 = llm_mod.hash_prompt("测试文本")
        assert h1 == h2

    def test_hash_different(self):
        """不同 prompt 哈希不同"""
        h1 = llm_mod.hash_prompt("AAA")
        h2 = llm_mod.hash_prompt("BBB")
        assert h1 != h2


class TestTokensCost:
    """费用估算"""

    def test_deepseek_cost(self):
        llm_mod._config = {"provider": "deepseek"}
        cost = llm_mod.tokens_cost(1000000, 1000000)
        assert cost > 0

    def test_anthropic_cost(self):
        llm_mod._config = {"provider": "anthropic"}
        cost = llm_mod.tokens_cost(1000000, 1000000)
        assert cost > 0

    def test_openai_cost(self):
        llm_mod._config = {"provider": "openai"}
        cost = llm_mod.tokens_cost(1000000, 1000000)
        assert cost > 0

    def test_zero_tokens(self):
        """零 token 费用为零"""
        cost = llm_mod.tokens_cost(0, 0)
        assert cost == 0.0


class TestCallText:
    """_call_text API 调用"""

    @patch('src.llm._client')
    def test_call_text_returns_structured(self, mock_client):
        """返回结构化结果"""
        mock_choice = MagicMock()
        mock_choice.message.content = '{"test": "ok"}'
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_client.chat.completions.create.return_value = mock_response

        llm_mod._config = {"model": "deepseek-chat", "provider": "deepseek",
                          "max_tokens": 2048, "temperature": 0.3}

        result = llm_mod._call_text("测试prompt")
        assert result["content"] == '{"test": "ok"}'
        assert result["tokens_in"] == 100
        assert result["tokens_out"] == 50


class TestCallVision:
    """_call_vision API 调用"""

    def test_vision_degraded_when_unavailable(self):
        """视觉不可用时降级"""
        llm_mod._vision_available = False
        llm_mod._config = {"model": "deepseek-chat", "provider": "deepseek",
                          "max_tokens": 2048, "temperature": 0.3}

        with patch.object(llm_mod, '_call_text') as mock_text:
            mock_text.return_value = {
                "content": '{"总分": 10}', "tokens_in": 100, "tokens_out": 50,
            }
            result = llm_mod._call_vision("prompt", ["/tmp/img.png"])
            assert result["content"] == '{"总分": 10}'

    @patch('src.llm._client')
    def test_call_vision_with_images(self, mock_client, tmp_dir):
        """有图片时正常调用视觉 API"""
        llm_mod._vision_available = True
        llm_mod._config = {"model": "gpt-4o", "provider": "openai",
                          "max_tokens": 2048, "temperature": 0.3}

        # 创建测试图片
        img_path = os.path.join(tmp_dir, "test.png")
        _create_test_png(img_path)

        mock_choice = MagicMock()
        mock_choice.message.content = '{"总分": 18}'
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 500
        mock_response.usage.completion_tokens = 100
        mock_client.chat.completions.create.return_value = mock_response

        result = llm_mod._call_vision("测试prompt", [img_path])
        assert result["content"] == '{"总分": 18}'
        assert result["tokens_in"] == 500


def _create_test_png(path):
    """创建测试 PNG"""
    with open(path, 'wb') as f:
        f.write(
            b'\x89PNG\r\n\x1a\n'
            b'\x00\x00\x00\rIHDR'
            b'\x00\x00\x00\x10'
            b'\x00\x00\x00\x10'
            b'\x08\x02\x00\x00\x00'
            b'\x00\x00\x00\x00'
        )
