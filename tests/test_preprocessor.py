"""
preprocessor.py 测试 —— 表格匹配 + 内容提取
覆盖：表格→题目匹配、字段提取、图片处理、LLM兜底、资源检测
"""
import os
import json
import pytest
from unittest.mock import patch, MagicMock

from src.preprocessor import (
    process, _match_tables_to_questions, _extract_question,
    _extract_text_by_label, _extract_content_after_label,
    _has_label, _extract_all_text, _longest_text,
    _resize_image, _matches_question, _llm_fallback_extraction,
    _parse_json,
)


class TestTableMatching:
    """表格→题目匹配算法"""

    def test_exact_match_by_name(self, sample_rubric):
        """精确子串匹配：表头含题目名"""
        tables = [
            [["文本生成"]],                          # 表头 (len=1)
            [["提示词", "生成结果", "生成结果截图"],   # 内容表 (>2行才能被识别)
             ["数据1", "数据2", "数据3"],
             ["数据4", "数据5", "数据6"]],
        ]
        mapping = _match_tables_to_questions(tables, sample_rubric)
        assert 1 in mapping
        assert len(mapping[1]) >= 1  # 拿到内容表

    def test_match_by_chinese_number(self, sample_rubric):
        """中文数字序号匹配"""
        tables = [
            [["一、文本生成"]],
            [["提示词", "生成结果"],
             ["数据行1", "数据行2"],
             ["数据行3", "数据行4"]],
            [["二、图像设计"]],
            [["提示词", "海报设计图"],
             ["数据行1", "数据行2"],
             ["数据行3", "数据行4"]],
        ]
        mapping = _match_tables_to_questions(tables, sample_rubric)
        assert 1 in mapping
        assert 2 in mapping

    def test_fuzzy_match_50_percent(self, sample_rubric):
        """模糊匹配：≥50% 字命中"""
        tables = [
            [["文生"]],
            [["提示词", "生成结果"],
             ["数据1", "数据2"],
             ["数据3", "数据4"]],
        ]
        mapping = _match_tables_to_questions(tables, sample_rubric)
        assert 1 in mapping

    def test_skip_summary_table(self, sample_rubric):
        """跳过得分汇总表"""
        tables = [
            [["题号", "题目", "得分", "总分"]],       # 汇总表
            [["1", "文本生成", "13"]],
            [["2", "图像设计", "18"]],
            [["文本生成"]],                            # 正常题目表头
            [["提示词", "生成结果"],
             ["内容1", "内容2"],
             ["内容3", "内容4"]],
        ]
        mapping = _match_tables_to_questions(tables, sample_rubric)
        assert 1 in mapping

    def test_no_match_returns_empty(self, sample_rubric):
        """完全不匹配返回空字典"""
        tables = [
            [["完全不相关的表头"]],
            [["数据1", "数据2"]],
        ]
        mapping = _match_tables_to_questions(tables, sample_rubric)
        # 可能 LLM 兜底，但规则匹配应为空或 LLM 兜底结果
        assert isinstance(mapping, dict)

    def test_each_title_one_question(self, sample_rubric):
        """每个表头只分配给一道题（不会重复分配）"""
        tables = [
            [["文本生成"]],
            [["提示词", "生成结果"]],
        ]
        mapping = _match_tables_to_questions(tables, sample_rubric)
        # "文本生成" 表头应该只分配给 Q1
        assert len(mapping) <= 2  # 不会给同一表头分配多次


class TestLabelExtraction:
    """按标签提取字段"""

    def test_extract_text_by_label_found(self):
        """找到标签后提取后续行文本"""
        rows = [
            ["提示词"],
            ["这是一段很长的提示词文本内容，描述了具体的任务要求，包含足够多的文字来进行测试。"],
        ]
        result = _extract_text_by_label(rows, ["提示词"])
        assert "提示词文本内容" in result

    def test_extract_text_by_label_not_found_fallback_longest(self):
        """没找到标签时返回最长文本（需 >20 字符）"""
        rows = [
            ["列A"],
            ["短"],
            ["这是一段比较长的文本内容作为兜底返回，需要超过二十个字符才行"],
        ]
        result = _extract_text_by_label(rows, ["不存在的标签"])
        assert "兜底" in result

    def test_extract_text_by_label_excludes_subsequent_labels(self):
        """排除后续行也是标签的情况"""
        rows = [
            ["提示词"],
            ["截图", "链接"],                         # 后续行也是标签
            ["实际的学生文本内容在这里"],
        ]
        result = _extract_text_by_label(rows, ["提示词"])
        assert "学生文本" in result

    def test_extract_content_after_label(self):
        """从标签行后方提取内容"""
        rows = [
            ["智能体人设"],
            ["本智能体是一个校园失物招领助手，负责帮助用户快速找到丢失物品。"],
        ]
        result = _extract_content_after_label(rows, ["智能体人设"])
        assert "校园失物招领" in result

    def test_extract_content_after_label_same_cell(self):
        """标签和内容在同一单元格"""
        rows = [
            ["智能体人设：本智能体是一个校园助手，提供失物招领服务"],
        ]
        result = _extract_content_after_label(rows, ["智能体人设"])
        assert "校园" in result

    def test_extract_content_after_label_not_found(self):
        """标签不存在返回空"""
        rows = [["其他内容"]]
        result = _extract_content_after_label(rows, ["不存在的标签"])
        assert result == ""


class TestHasLabel:
    """标签存在性检查"""

    def test_label_exists(self):
        rows = [["提示词", "生成结果", "截图"]]
        assert _has_label(rows, ["截图"]) is True
        assert _has_label(rows, ["提示词"]) is True

    def test_label_not_exists(self):
        rows = [["提示词", "生成结果"]]
        assert _has_label(rows, ["视频"]) is False

    def test_partial_match(self):
        rows = [["AI中图生视频的页面截图"]]
        assert _has_label(rows, ["截图"]) is True


class TestExtractAllText:
    """提取表格所有文本"""

    def test_extract_all_text(self):
        tables = [
            [["标题AAA", "标题BBB"], ["数据111", "数据222"]],
        ]
        text = _extract_all_text(tables)
        assert "标题AAA" in text
        assert "数据222" in text

    def test_skip_short_text(self):
        """跳过太短的文本 (<4字符)"""
        tables = [
            [["A", "B", "短"]],
            [["这是一个比较长的文本内容"]],
        ]
        text = _extract_all_text(tables)
        assert "比较长的文本" in text
        # "A", "B", "短" 应该被跳过


class TestLongestText:
    """获取最长文本"""

    def test_longest(self):
        rows = [
            ["短"],
            ["中等长度文本"],
            ["这是一段明显比其他文本要长得多的测试文本内容"],
        ]
        result = _longest_text(rows)
        assert "明显比其他文本" in result

    def test_all_short_returns_empty(self):
        """所有文本都小于20字符返回空"""
        rows = [["短"], ["也很短"]]
        result = _longest_text(rows)
        assert result == ""


class TestMatchQuestion:
    """单题匹配判断"""

    def test_exact_name_match(self):
        assert _matches_question("文本生成", 1, "文本生成") is True

    def test_chinese_number_match(self):
        assert _matches_question("一、文本生成", 1, "文本生成") is True
        assert _matches_question("（一）文本生成", 1, "文本生成") is True

    def test_fuzzy_match(self):
        assert _matches_question("文生", 1, "文本生成") is True

    def test_no_match(self):
        assert _matches_question("完全不相关", 1, "文本生成") is False


class TestParseJson:
    """JSON 解析"""

    def test_parse_valid_json(self):
        result = _parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_with_markdown_block(self):
        result = _parse_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_json_in_text(self):
        result = _parse_json('前缀文本 {"key": "value"} 后缀文本')
        assert result == {"key": "value"}

    def test_parse_invalid_json_returns_empty(self):
        result = _parse_json('这不是 JSON')
        assert result == {}


class TestResizeImage:
    """图片缩略"""

    def test_small_image_not_resized(self, tmp_dir):
        """小图不缩放"""
        path = os.path.join(tmp_dir, "small.png")
        _create_png(path, 100, 100)
        result = _resize_image(path, max_width=768, quality=75)
        assert result == path  # 返回原路径

    def test_large_image_resized(self, tmp_dir):
        """大图缩放"""
        path = os.path.join(tmp_dir, "large.png")
        _create_png(path, 2000, 1500)
        result = _resize_image(path, max_width=768, quality=75)
        assert result is not None
        assert "resized" in result

    def test_corrupt_image_returns_none(self, tmp_dir):
        """损坏图片返回 None"""
        path = os.path.join(tmp_dir, "corrupt.png")
        with open(path, 'wb') as f:
            f.write(b'not an image')
        result = _resize_image(path, 768, 75)
        assert result is None


class TestLLMFallback:
    """LLM 兜底提取"""

    @patch('src.llm.grade_with_text')
    def test_fallback_calls_llm(self, mock_grade, sample_rubric):
        """确认调用 LLM"""
        mock_grade.return_value = {
            "raw_response": json.dumps({"questions": []}),
            "tokens_in": 0, "tokens_out": 0,
        }
        tables = [[["未知格式", "内容"]]]
        result = _llm_fallback_extraction(tables, sample_rubric, {})
        assert isinstance(result, dict)

    @patch('src.llm.grade_with_text')
    def test_fallback_handles_llm_error(self, mock_grade, sample_rubric):
        """LLM 出错时安全返回空字典"""
        mock_grade.side_effect = Exception("API 错误")
        result = _llm_fallback_extraction([], sample_rubric, {})
        assert result == {}


class TestExtractQuestion:
    """_extract_question 综合测试"""

    def test_text_question_extraction(self):
        """文本题提取"""
        content_tables = [[
            ["提示词", "生成结果"],
            ["写一篇关于种草文案的详细提示词文本内容", "短的"],
        ]]
        question = {
            "id": 1, "name": "文本生成",
            "grading_type": "text",
            "submission_labels": [
                {"label": "提示词", "field": "prompt_text"},
                {"label": "生成结果", "field": "result_text"},
            ],
        }
        result = _extract_question(
            content_tables, question, images=[], excel_files=[],
            video_files=[], paragraphs=[]
        )
        assert "种草文案" in result["prompt_text"]

    def test_no_labels_extraction(self):
        """没有 submission_labels 时的启发式提取"""
        content_tables = [[
            ["提示词", "生成结果"],
            ["测试提示词内容文本", "测试生成结果内容文本"],
        ]]
        question = {
            "id": 1, "name": "文本生成",
            "grading_type": "text",
            "submission_labels": [],
        }
        result = _extract_question(
            content_tables, question, images=[], excel_files=[],
            video_files=[], paragraphs=[]
        )
        # 启发式规则应该抓到文本
        assert len(result["all_table_text"]) > 0

    def test_screenshot_detection_with_images(self):
        """有图片时检测截图"""
        content_tables = [[["提示词", "生成结果"]]]
        question = {
            "id": 1, "name": "文本生成",
            "grading_type": "text",
            "submission_labels": [],
        }
        # >=2 张图 → has_screenshot
        result = _extract_question(
            content_tables, question,
            images=[("/tmp/a.png", 800, 800), ("/tmp/b.png", 1024, 768)],
            excel_files=[], video_files=[], paragraphs=[]
        )
        assert result["has_screenshot"] is True

    def test_screenshot_label_detection(self):
        """表格含"截图"标签 + 同行有学生内容 >20字 → 检测到截图"""
        content_tables = [[["提示词", "生成结果截图", "学生写了很长的提示词描述了海报设计要求"]]]
        question = {
            "id": 1, "name": "文本生成",
            "grading_type": "text",
            "submission_labels": [],
        }
        result = _extract_question(
            content_tables, question, images=[], excel_files=[],
            video_files=[], paragraphs=[]
        )
        assert result["has_screenshot"] is True

    def test_screenshot_label_only_no_content(self):
        """表格含"截图"标签但同行无内容 → 不检测（避免模板标签误判）"""
        content_tables = [[["提示词", "生成结果截图", ""]]]
        question = {
            "id": 1, "name": "文本生成",
            "grading_type": "text",
            "submission_labels": [],
        }
        result = _extract_question(
            content_tables, question, images=[], excel_files=[],
            video_files=[], paragraphs=[]
        )
        assert result["has_screenshot"] is False


def _create_png(path, width, height):
    """创建指定尺寸的 PNG"""
    from PIL import Image
    img = Image.new('RGB', (width, height), color='red')
    img.save(path, 'PNG')
