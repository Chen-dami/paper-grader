"""
grader.py 测试 —— 评分引擎核心
覆盖：客观题 (选择/判断/填空/简答)、档位检测（新API）、
      code评分（结构化输出）、LLM评分、档位联动参数
"""
import os, json
import pytest
from unittest.mock import patch, MagicMock

from src.grader import (
    grade, _detect_tier, _is_truly_empty, _zero_score,
    _grade_code, _grade_llm, _grade_exact_match,
    _build_content_desc, _collect_images,
    _get_tier_config_extended,
    _flag_match,
    _run_data_checks_structured, _check_one_structured,
    extract_scores, _collect_text, _extract_answer, _fuzzy_match,
)


# ============================================================
#  客观题
# ============================================================
class TestExactMatchGrading:
    """客观题评分"""

    def test_single_choice_correct(self):
        q_data = {"prompt_text": "B", "result_text": ""}
        question = {
            "id": 1, "name": "选择题", "max_score": 5,
            "grading_type": "multiple_choice",
            "answer_key": {"正确答案": "B", "分值": 5},
            "criteria": [{"id": "1-1", "name": "答案", "max": 5}],
        }
        result = _grade_exact_match(q_data, question)
        assert result["总分"] == 5
        assert "正确" in result["评语"]

    def test_single_choice_wrong(self):
        q_data = {"prompt_text": "C", "result_text": ""}
        question = {
            "id": 1, "name": "选择题", "max_score": 5,
            "grading_type": "multiple_choice",
            "answer_key": {"正确答案": "B", "分值": 5, "部分分": 0},
            "criteria": [{"id": "1-1", "name": "答案", "max": 5}],
        }
        result = _grade_exact_match(q_data, question)
        assert result["总分"] == 0
        assert "错误" in result["评语"]

    def test_true_false_correct(self):
        q_data = {"prompt_text": "对", "result_text": ""}
        question = {
            "id": 2, "name": "判断题", "max_score": 2,
            "grading_type": "true_false",
            "answer_key": {"正确答案": "对", "分值": 2},
            "criteria": [{"id": "2-1", "name": "判断", "max": 2}],
        }
        result = _grade_exact_match(q_data, question)
        assert result["总分"] == 2

    def test_fill_blank(self):
        q_data = {"prompt_text": "人工智能", "result_text": ""}
        question = {
            "id": 3, "name": "填空题", "max_score": 10,
            "grading_type": "fill_blank",
            "answer_key": {"答案": {"1": "人工智能", "2": "机器学习"}},
            "criteria": [
                {"id": "3-1", "name": "第一空", "max": 5},
                {"id": "3-2", "name": "第二空", "max": 5},
            ],
        }
        result = _grade_exact_match(q_data, question)
        assert result["总分"] == 5  # 答对一个

    def test_short_answer_with_key_points(self):
        q_data = {"prompt_text": "这是关于人工智能和机器学习的回答", "result_text": ""}
        question = {
            "id": 4, "name": "简答题", "max_score": 10,
            "grading_type": "short_answer",
            "key_points": [
                {"keyword": "人工智能", "score": 5},
                {"keyword": "机器学习", "score": 5},
            ],
            "criteria": [
                {"id": "4-1", "name": "知识点1", "max": 5},
                {"id": "4-2", "name": "知识点2", "max": 5},
            ],
        }
        result = _grade_exact_match(q_data, question)
        assert result["总分"] == 10

    def test_short_answer_missing_keywords(self):
        q_data = {"prompt_text": "这是无关回答", "result_text": ""}
        question = {
            "id": 4, "name": "简答题", "max_score": 10,
            "grading_type": "short_answer",
            "key_points": [{"keyword": "人工智能", "score": 10}],
            "criteria": [{"id": "4-1", "name": "知识点", "max": 10}],
        }
        result = _grade_exact_match(q_data, question)
        assert result["总分"] == 0
        assert "缺" in result["评语"]


class TestExtractAnswer:
    """答案提取"""

    def test_extract_single_choice(self):
        assert _extract_answer({"prompt_text": "B", "result_text": ""}, "multiple_choice") == "B"

    def test_extract_from_result_text(self):
        ans = _extract_answer({"prompt_text": "", "result_text": "答案是 A"}, "multiple_choice")
        assert ans == "A"

    def test_extract_multi_choice(self):
        ans = _extract_answer({"prompt_text": "ABD", "result_text": ""}, "multiple_choice")
        assert ans == ["A", "B", "D"]

    def test_extract_fill_blank_single(self):
        ans = _extract_answer({"prompt_text": "人工智能", "result_text": ""}, "fill_blank")
        assert ans == "人工智能"

    def test_fuzzy_match_ignore_case_space(self):
        assert _fuzzy_match("Artificial Intelligence", "artificial intelligence") is True
        assert _fuzzy_match("AI", "ai") is True

    def test_fuzzy_match_ignore_punctuation(self):
        assert _fuzzy_match("对", "对") is True


# ============================================================
#  空判 / 零分
# ============================================================
class TestIsTrulyEmpty:
    def test_text_empty(self):
        q_data = {"prompt_text": "", "result_text": "", "image_prompt": "",
                  "video_prompt": "", "persona_text": "", "has_screenshot": False,
                  "generated_images": [], "has_video": False, "video_path": "", "bot_link": ""}
        assert _is_truly_empty(q_data, "text") is True

    def test_text_with_content(self):
        q_data = {"prompt_text": "Hello world", "result_text": "", "image_prompt": "",
                  "video_prompt": "", "persona_text": "", "has_screenshot": False,
                  "generated_images": [], "has_video": False, "video_path": "", "bot_link": ""}
        assert _is_truly_empty(q_data, "text") is False

    def test_code_no_file_no_screenshot(self):
        assert _is_truly_empty({"excel_path": "", "has_excel_file": False, "has_screenshot": False}, "code") is True

    def test_code_with_screenshot(self):
        assert _is_truly_empty({"excel_path": "", "has_excel_file": False, "has_screenshot": True}, "code") is False

    def test_with_media_not_empty(self):
        q_data = {"prompt_text": "", "result_text": "", "image_prompt": "",
                  "video_prompt": "", "persona_text": "",
                  "generated_images": ["/tmp/a.png"], "has_video": False,
                  "video_path": "", "bot_link": ""}
        assert _is_truly_empty(q_data, "text") is False


class TestZeroScore:
    def test_structure(self):
        criteria = [{"id": "1-1", "name": "主题", "max": 5}]
        result = _zero_score(criteria, 5, "空")
        assert result["总分"] == 0
        assert result["得分_1-1_主题"] == 0


# ============================================================
#  档位检测（新 API: 3 参数）
# ============================================================
class TestTierDetection:
    @pytest.fixture
    def config(self, sample_config):
        return sample_config

    def test_empty(self, sample_q_data_empty, config):
        question = {"id": 1, "name": "文本", "grading_type": "text", "topic_keywords": []}
        assert _detect_tier(sample_q_data_empty, question, config) == "空"

    def test_perfunctory(self, config):
        q_data = {"prompt_text": "短", "result_text": "", "image_prompt": "",
                  "video_prompt": "", "persona_text": "", "all_table_text": ""}
        question = {"id": 1, "name": "文本", "grading_type": "text", "topic_keywords": []}
        tier = _detect_tier(q_data, question, config)
        assert tier in ("敷衍", "空")

    def test_off_topic(self, config):
        q_data = {"prompt_text": "无关内容" * 20, "result_text": "更多无关",
                  "image_prompt": "", "video_prompt": "", "persona_text": "","all_table_text": ""}
        question = {"id": 1, "name": "文本", "grading_type": "text",
                    "topic_keywords": ["毕业季", "三亚", "种草"]}
        assert _detect_tier(q_data, question, config) == "跑题"

    def test_on_topic(self, config):
        """关键词匹配 + 足够长文本 → 不跑题不敷衍"""
        q_data = {
            "prompt_text": "毕业季来三亚旅游种草文案推荐，这是足够长的文本内容" * 3,
            "result_text": "三亚旅行攻略内容很多", "image_prompt": "", "video_prompt": "",
            "persona_text": "", "all_table_text": "",
        }
        question = {"id": 1, "name": "文本生成", "grading_type": "text",
                    "topic_keywords": ["毕业季", "三亚", "种草"]}
        tier = _detect_tier(q_data, question, config)
        assert tier not in ("空", "敷衍", "跑题")

    def test_vision_with_media_skips_keyword(self, config):
        q_data = {"prompt_text": "无关" * 10, "result_text": "", "image_prompt": "",
                  "video_prompt": "", "persona_text": "", "all_table_text": "",
                  "generated_images": ["/tmp/a.png"], "reference_image": None,
                  "has_video": False, "video_path": ""}
        question = {"id": 2, "name": "图像设计", "grading_type": "vision",
                    "topic_keywords": ["文昌", "航天"]}
        assert _detect_tier(q_data, question, config) != "跑题"

    def test_insufficient_materials(self, config):
        """多项素材缺失 → 素材不足"""
        long_text = "海南黎锦非遗短视频" * 30
        q_data = {"prompt_text": long_text, "result_text": "", "image_prompt": "",
                  "video_prompt": "", "persona_text": "", "all_table_text": "",
                  "has_screenshot": False, "generated_images": [],
                  "has_video": False, "video_path": ""}
        question = {"id": 3, "name": "视频创作", "grading_type": "vision",
                    "topic_keywords": ["海南黎锦"],
                    "tier": {"text_min": 10, "perfunctory_max": 40, "keyword_min": 1, "keyword_need": 2,
                             "materials": {"screenshot": True, "images": True, "video": True},
                             "material_missing_max": 2}}
        tier = _detect_tier(q_data, question, config)
        assert tier in ("素材不足", "敷衍", "无视频")


class TestTierConfigExtended:
    def test_on_topic_params(self, sample_config):
        tc = _get_tier_config_extended("贴合主题", sample_config)
        assert tc["temperature"] == 0.3
        assert tc["ratio_min"] > 0.5
        assert tc["max_tokens"] == 2048

    def test_off_topic_params(self, sample_config):
        tc = _get_tier_config_extended("跑题", sample_config)
        assert tc["ratio_max"] <= 0.7
        assert tc["temperature"] == 0.3

    def test_empty_params(self, sample_config):
        tc = _get_tier_config_extended("空", sample_config)
        assert tc["ratio_min"] == 0.0
        assert tc["ratio_max"] == 0.0


# ============================================================
#  素材检测
# ============================================================
class TestMaterials:
    """素材检测 -- rubric 驱动的新 API"""
    def test_flag_match_has_screenshot_when_declared(self):
        mat_cfg = {"screenshot": True}
        mat = {"screenshot": True}
        assert _flag_match("有截图", mat_cfg, mat) is True

    def test_flag_match_no_screenshot_when_declared(self):
        mat_cfg = {"screenshot": True}
        mat = {"screenshot": False}
        assert _flag_match("无截图", mat_cfg, mat) is True

    def test_flag_match_ignores_undeclared_material(self):
        mat_cfg = {"screenshot": False, "video": True}  # screenshot not declared
        mat = {"screenshot": True, "video": True}
        assert _flag_match("有截图", mat_cfg, mat) is False  # 未声明 screenshot，不匹配

    def test_materials_from_rubric_tier_config(self, sample_config):
        """素材规则从 rubric question.tier.materials 读取"""
        q_data = {
            "prompt_text": "测试内容" * 20, "result_text": "", "image_prompt": "",
            "video_prompt": "", "persona_text": "", "all_table_text": "",
            "has_screenshot": True, "generated_images": [],
            "has_video": False, "video_path": "",
        }
        question = {
            "id": 1, "name": "文本", "grading_type": "text",
            "topic_keywords": ["测试"],
            "tier": {
                "text_min": 10, "perfunctory_max": 50, "keyword_min": 1, "keyword_need": 1,
                "materials": {"screenshot": True, "video": False},
                "material_missing_max": 1,
            },
        }
        tier = _detect_tier(q_data, question, sample_config)
        assert tier == "有截图"


# ============================================================
#  Code 评分（新 API: 3参数）
# ============================================================
class TestCodeGrading:
    def test_with_excel(self, tmp_dir, sample_excel_path, sample_config):
        q_data = {"excel_path": sample_excel_path, "has_screenshot": True, "prompt_text": "test"}
        question = {
            "id": 4, "name": "数据处理", "max_score": 20,
            "grading_type": "code",
            "criteria": [
                {"id": "4-1", "name": "缺失值处理", "max": 5},
                {"id": "4-2", "name": "重复项处理", "max": 5},
                {"id": "4-3", "name": "格式统一与排序", "max": 5},
                {"id": "4-4", "name": "提交完整性", "max": 5},
            ],
            "data_checks": {"fillna": {"column": "销售金额"}, "dedup": {},
                           "date_format": {"column": "销售日期"}},
        }
        result = _grade_code(q_data, question, sample_config)
        assert 0 <= result["总分"] <= 20

    def test_without_excel_has_screenshot(self, sample_config):
        q_data = {"excel_path": "", "has_screenshot": True, "prompt_text": ""}
        question = {"id": 4, "name": "数据处理", "max_score": 20,
                    "criteria": [{"id": "4-1", "name": "缺失值处理", "max": 5}],
                    "data_checks": {}, "grading_type": "code"}
        result = _grade_code(q_data, question, sample_config)
        assert result["总分"] >= 1  # 有截图给基础分


class TestDataChecksStructured:
    def test_dedup_clean(self, sample_excel_df):
        c = {"id": "x", "name": "重复项处理", "max": 5}
        s, r, rr = _check_one_structured(sample_excel_df, c, "dedup", {})
        assert s == 5
        assert rr["status"] == "pass"

    def test_dedup_with_dupes(self):
        import pandas as pd
        df = pd.DataFrame({"A": [1, 1, 2], "B": [1, 1, 3]})
        c = {"id": "x", "name": "重复项处理", "max": 5}
        s, r, rr = _check_one_structured(df, c, "dedup", {})
        assert s < 5
        assert rr["status"] in ("warn", "fail")

    def test_fillna_clean(self, sample_excel_df):
        c = {"id": "x", "name": "缺失值处理", "max": 5}
        s, r, rr = _check_one_structured(sample_excel_df, c, "fillna",
                                         {"fillna": {"column_pattern": "销售金额"}})
        assert s == 5
        assert rr["status"] == "pass"

    def test_date_sorted(self, sample_excel_df):
        c = {"id": "x", "name": "格式统一与排序", "max": 5}
        s, r, rr = _check_one_structured(sample_excel_df, c, "date_sort",
                                         {"date_format": {"column_pattern": "销售日期"}})
        assert rr["status"] in ("pass", "warn")


class TestGradeMain:
    """grade() 主入口"""

    def test_grade_multiple_choice_dispatches(self):
        q_data = {"prompt_text": "B"}
        question = {
            "id": 0, "name": "选择", "max_score": 5,
            "grading_type": "multiple_choice",
            "answer_key": {"正确答案": "B", "分值": 5},
            "criteria": [{"id": "0-1", "name": "答案", "max": 5}],
        }
        result = grade(q_data, question, {})
        assert result["总分"] == 5

    def test_grade_empty_returns_zero(self, sample_q_data_empty):
        question = {
            "id": 1, "name": "文本", "max_score": 15,
            "grading_type": "text", "topic_keywords": [],
            "criteria": [{"id": "1-1", "name": "评分项", "max": 5}],
        }
        result = grade(sample_q_data_empty, question, {"grading": {"tiers": {"空": {"ratio_min": 0, "ratio_max": 0}}}})
        assert result["总分"] == 0

    @patch('src.grader.router.call_model')
    def test_grade_text_llm(self, mock_router, sample_q_data_text, sample_config):
        mock_router.return_value = {
            "content": json.dumps({
                "得分_1-1_主题契合度": 4, "得分_1-2_文案内容适配": 4,
                "得分_1-3_提交完整性": 5, "总分": 13, "评语": "不错",
            }), "tokens_in": 100, "tokens_out": 50, "model_used": "deepseek-chat",
        }
        question = {
            "id": 1, "name": "文本生成", "max_score": 15,
            "grading_type": "text",
            "topic_keywords": ["毕业季", "三亚", "种草"],
            "criteria": [
                {"id": "1-1", "name": "主题契合度", "max": 5},
                {"id": "1-2", "name": "文案内容适配", "max": 5},
                {"id": "1-3", "name": "提交完整性", "max": 5},
            ],
        }
        result = grade(sample_q_data_text, question, sample_config)
        assert "总分" in result
        assert "切题判断" in result


class TestExtractScores:
    def test_standard(self):
        result = {"得分_1-1_主题": 4, "得分_1-2_内容": 3, "总分": 7}
        question = {"criteria": [
            {"id": "1-1", "name": "主题", "max": 5},
            {"id": "1-2", "name": "内容", "max": 5},
        ]}
        scores = extract_scores(result, question)
        assert len(scores) == 2
        assert scores[0]["score"] == 4


class TestContentDesc:
    def test_with_video(self):
        q_data = {"prompt_text": "", "result_text": "", "image_prompt": "",
                  "video_prompt": "", "persona_text": "",
                  "has_video": True, "video_path": "/tmp/t.mp4",
                  "video_info": "30秒 1920x1080 avc1", "bot_link": "", "has_screenshot": False}
        desc = _build_content_desc(q_data, {"name": "视频"})
        assert "30秒" in desc

    def test_with_link(self):
        q_data = {"prompt_text": "", "result_text": "", "image_prompt": "",
                  "video_prompt": "", "persona_text": "",
                  "has_video": False, "video_path": "", "bot_link": "https://bot.co",
                  "has_screenshot": False}
        desc = _build_content_desc(q_data, {"name": "智能体"})
        assert "https://bot.co" in desc

    def test_missing_link(self):
        q_data = {"prompt_text": "", "result_text": "", "image_prompt": "",
                  "video_prompt": "", "persona_text": "",
                  "has_video": False, "video_path": "", "bot_link": "", "has_screenshot": False}
        desc = _build_content_desc(q_data, {"name": "智能体搭建"})
        assert "无" in desc


class TestCollectImages:
    def test_generated_images(self, tmp_dir):
        p1 = os.path.join(tmp_dir, "a.png")
        p2 = os.path.join(tmp_dir, "b.png")
        _create_mini_png(p1); _create_mini_png(p2)
        q_data = {"generated_images": [p1, p2]}
        imgs = _collect_images(q_data)
        assert len(imgs) == 2

    def test_legacy_single_field(self, tmp_dir):
        p = os.path.join(tmp_dir, "old.png")
        _create_mini_png(p)
        q_data = {"generated_image": p, "generated_images": []}
        imgs = _collect_images(q_data)
        assert len(imgs) == 1


def _create_mini_png(path):
    from PIL import Image
    Image.new('RGB', (10, 10), color='blue').save(path, 'PNG')
