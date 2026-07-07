"""
测试基础设施 —— 共享 fixtures、mock 工具、测试数据工厂。
"""
import os
import sys
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pandas as pd
from docx import Document
from docx.shared import Inches

# 确保 src 在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent))

# ============================================================
#  临时目录 fixtures
# ============================================================

@pytest.fixture
def tmp_dir():
    """独立的临时工作目录（测试完自动清理）"""
    d = tempfile.mkdtemp(prefix="aigrader_test_")
    old_cwd = os.getcwd()
    os.chdir(d)
    yield d
    os.chdir(old_cwd)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def tmp_output_dir(tmp_dir):
    """临时 output 目录"""
    p = os.path.join(tmp_dir, "output")
    os.makedirs(p, exist_ok=True)
    return p


@pytest.fixture
def tmp_papers_dir(tmp_dir):
    """临时试卷目录"""
    p = os.path.join(tmp_dir, "data", "papers")
    os.makedirs(p, exist_ok=True)
    return p


# ============================================================
#  评分标准 (rubric) fixtures
# ============================================================

@pytest.fixture
def sample_rubric():
    """一份完整的示例评分标准"""
    return {
        "exam": {
            "name": "人工智能基础实践",
            "semester": "2025-2026学年第二学期",
            "total_score": 100,
        },
        "questions": [
            {
                "id": 1,
                "name": "文本生成",
                "max_score": 15,
                "grading_type": "text",
                "topic_keywords": ["毕业季", "三亚", "种草文案"],
                "submission_labels": [
                    {"label": "提示词", "field": "prompt_text"},
                    {"label": "生成结果截图", "field": "result_text", "type": "image"},
                ],
                "criteria": [
                    {"id": "1-1", "name": "主题契合度", "max": 5, "desc": "文案紧密围绕主题"},
                    {"id": "1-2", "name": "文案内容适配", "max": 5, "desc": "适合小红书发布"},
                    {"id": "1-3", "name": "提交完整性", "max": 5, "desc": "提示词和截图完整"},
                ],
            },
            {
                "id": 2,
                "name": "图像设计",
                "max_score": 20,
                "grading_type": "vision",
                "topic_keywords": ["文昌", "航天", "海报"],
                "submission_labels": [
                    {"label": "提示词", "field": "prompt_text"},
                    {"label": "海报设计图", "field": "result_text", "type": "image"},
                ],
                "criteria": [
                    {"id": "2-1", "name": "主题契合度", "max": 5, "desc": "海报紧扣航天主题"},
                    {"id": "2-2", "name": "工具使用合理性", "max": 5, "desc": "正确使用AI平台"},
                    {"id": "2-3", "name": "设计创意与完整性", "max": 5, "desc": "海报有创意和冲击力"},
                    {"id": "2-4", "name": "提交完整性", "max": 5, "desc": "提示词和设计图完整"},
                ],
            },
            {
                "id": 3,
                "name": "视频创作",
                "max_score": 20,
                "grading_type": "vision",
                "topic_keywords": ["海南黎锦", "非遗", "短视频"],
                "submission_labels": [
                    {"label": "生成图片的提示词", "field": "image_prompt"},
                    {"label": "生成视频的提示词", "field": "video_prompt"},
                ],
                "criteria": [
                    {"id": "3-1", "name": "主题契合度", "max": 4, "desc": "聚焦黎锦特色"},
                    {"id": "3-2", "name": "图片生成质量", "max": 4, "desc": "纹理清晰构图完整"},
                    {"id": "3-3", "name": "人物服饰与背景", "max": 4, "desc": "传统黎族服饰"},
                    {"id": "3-4", "name": "配音与整体效果", "max": 4, "desc": "配音合适"},
                    {"id": "3-5", "name": "提交材料完整性", "max": 4, "desc": "提交内容完整"},
                ],
            },
            {
                "id": 4,
                "name": "数据处理",
                "max_score": 20,
                "grading_type": "code",
                "topic_keywords": [],
                "submission_labels": [
                    {"label": "提示词", "field": "prompt_text"},
                    {"label": "处理好的Excel表格", "field": "result_text", "type": "file"},
                ],
                "data_checks": {
                    "fillna": {"column": "销售金额", "method": "formula"},
                    "dedup": {"scope": "全表完全重复"},
                    "date_format": {"column": "销售日期", "format": "YYYY-MM-DD"},
                    "sort": {"column": "销售日期", "order": "asc"},
                },
                "criteria": [
                    {"id": "4-1", "name": "缺失值处理", "max": 5, "desc": "填写销售金额空值"},
                    {"id": "4-2", "name": "重复项处理", "max": 5, "desc": "删除重复记录"},
                    {"id": "4-3", "name": "格式统一与排序", "max": 5, "desc": "日期格式统一排序"},
                    {"id": "4-4", "name": "提交完整性", "max": 5, "desc": "提交材料完整"},
                ],
            },
            {
                "id": 5,
                "name": "智能体搭建",
                "max_score": 25,
                "grading_type": "hybrid",
                "topic_keywords": ["校园失物招领", "智能体", "扣子平台"],
                "submission_labels": [
                    {"label": "智能体人设与回复逻辑文本内容", "field": "persona_text"},
                    {"label": "智能体发布后的链接", "field": "result_text", "type": "url"},
                ],
                "criteria": [
                    {"id": "5-1", "name": "人设与回复逻辑", "max": 7, "desc": "人设逻辑完整"},
                    {"id": "5-2", "name": "知识库配置", "max": 7, "desc": "知识库正确导入"},
                    {"id": "5-3", "name": "智能体功能完善性", "max": 6, "desc": "功能完善"},
                    {"id": "5-4", "name": "提交完整性", "max": 5, "desc": "提交内容完整"},
                ],
            },
        ],
    }


@pytest.fixture
def sample_config():
    """示例配置"""
    return {
        "llm": {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "max_tokens": 2048,
            "temperature": 0.3,
        },
        "vision_strategy": "paid_vision",  # 默认策略
        "grading": {
            "mode": "normal",
            "pass_line": 60,
            "tiers": {
                "贴合主题": {"ratio_min": 0.8, "ratio_max": 1.0, "desc": ""},
                "跑题": {"ratio_min": 0.35, "ratio_max": 0.55, "desc": ""},
                "敷衍": {"ratio_min": 0.2, "ratio_max": 0.35, "desc": ""},
                "空": {"ratio_min": 0.0, "ratio_max": 0.0, "desc": ""},
                "素材不足": {"ratio_min": 0.3, "ratio_max": 0.5, "desc": ""},
                "有视频": {"ratio_min": 0.9, "ratio_max": 1.0, "desc": ""},
                "无视频": {"ratio_min": 0.3, "ratio_max": 0.5, "desc": ""},
                "有截图": {"ratio_min": 0.9, "ratio_max": 1.0, "desc": ""},
                "无截图": {"ratio_min": 0.3, "ratio_max": 0.5, "desc": ""},
                "有表格": {"ratio_min": 0.9, "ratio_max": 1.0, "desc": ""},
                "无表格": {"ratio_min": 0.3, "ratio_max": 0.5, "desc": ""},
                "有链接": {"ratio_min": 0.9, "ratio_max": 1.0, "desc": ""},
                "无链接": {"ratio_min": 0.3, "ratio_max": 0.5, "desc": ""},
            },
        },
        "image": {"max_width": 768, "quality": 75, "skip_below_kb": 50},
    }


# ============================================================
#  试卷数据 fixtures
# ============================================================

@pytest.fixture
def sample_paragraphs():
    """模拟 Word 段落提取结果"""
    return [
        (0, "学号：255102030101  姓名：张三  班级：软件2501"),
        (1, ""),
        (2, "题目一：文本生成"),
        (3, "提示词：请帮我写一篇关于毕业季到三亚旅游的小红书种草文案"),
        (4, "生成结果截图：（已提交在下方）"),
    ]


@pytest.fixture
def sample_tables():
    """模拟 Word 表格提取结果"""
    return [
        # 表格0：文本生成题
        [
            ["提示词", "生成结果", "生成结果截图"],
            [
                "请帮我写一篇关于毕业季到三亚旅游的小红书种草文案，300字以内",
                "🎓毕业季来三亚，这份青春不散场！三亚的夏天是毕业旅行最好的打开方式...",
                "（截图）",
            ],
        ],
        # 表格1：图像设计题
        [
            ["提示词", "海报设计图"],
            [
                "设计一张中国文昌航天发射场任务纪念宣传海报，风格科幻",
                "（图片）",
            ],
        ],
    ]


@pytest.fixture
def sample_paper_data(sample_paragraphs, sample_tables):
    """模拟 extractor 输出的完整试卷数据"""
    return {
        "file_name": "255102030101张三.docx",
        "paper_dir": "/tmp/test_output/255102030101张三",
        "student_info": {"学号": "255102030101", "姓名": "张三", "班级": "软件2501"},
        "paragraphs": sample_paragraphs,
        "tables": sample_tables,
        "images": [],
        "embedded_files": [],
    }


@pytest.fixture
def sample_q_data_text():
    """模拟一道文本题的 q_data（评分引擎输入）"""
    return {
        "prompt_text": "请帮我写一篇关于毕业季到三亚旅游的小红书种草文案，300字以内",
        "result_text": "🎓毕业季来三亚，这份青春不散场！三亚的夏天是毕业旅行最好的打开方式，这里有碧海蓝天、椰风海韵...",
        "image_prompt": "",
        "video_prompt": "",
        "persona_text": "",
        "has_screenshot": True,
        "has_video": False,
        "video_path": "",
        "has_excel_file": False,
        "excel_path": "",
        "bot_link": "",
        "generated_images": [],
        "reference_image": None,
        "all_table_text": "提示词 生成结果 请帮我写一篇关于毕业季...",
    }


@pytest.fixture
def sample_q_data_vision():
    """模拟一道 vision 题的 q_data"""
    return {
        "prompt_text": "设计一张中国文昌航天发射场任务纪念宣传海报，风格科幻",
        "result_text": "",
        "image_prompt": "",
        "video_prompt": "",
        "persona_text": "",
        "has_screenshot": True,
        "has_video": False,
        "video_path": "",
        "has_excel_file": False,
        "excel_path": "",
        "bot_link": "",
        "generated_images": ["/tmp/img1.png", "/tmp/img2.png"],
        "reference_image": None,
        "all_table_text": "提示词 海报设计图 设计一张...",
    }


@pytest.fixture
def sample_q_data_empty():
    """模拟一道空题"""
    return {
        "prompt_text": "",
        "result_text": "",
        "image_prompt": "",
        "video_prompt": "",
        "persona_text": "",
        "has_screenshot": False,
        "has_video": False,
        "video_path": "",
        "has_excel_file": False,
        "excel_path": "",
        "bot_link": "",
        "generated_images": [],
        "reference_image": None,
        "all_table_text": "",
    }


# ============================================================
#  Excel 数据 fixtures（数据处理题）
# ============================================================

@pytest.fixture
def sample_excel_df():
    """模拟学生提交的处理后 Excel"""
    return pd.DataFrame({
        "销售日期": pd.to_datetime(["2024-06-01", "2024-06-01", "2024-06-02"]),
        "商品名称": ["矿泉水", "方便面", "矿泉水"],
        "销售金额": [2.0, 5.0, 2.0],
    })


@pytest.fixture
def sample_excel_with_issues():
    """包含问题的 Excel：有空值、有重复、日期格式不统一、未排序"""
    return pd.DataFrame({
        "销售日期": ["2024/06/03", "2024/06/01", "2024/06/01"],
        "商品名称": ["矿泉水", "方便面", "方便面"],
        "销售金额": [2.0, None, 5.0],
    })


@pytest.fixture
def sample_excel_path(tmp_dir, sample_excel_df):
    """创建一个实际的 Excel 文件供测试使用"""
    p = os.path.join(tmp_dir, "test_data.xlsx")
    sample_excel_df.to_excel(p, index=False)
    return p


@pytest.fixture
def sample_excel_issues_path(tmp_dir, sample_excel_with_issues):
    """创建有问题数据的 Excel 文件"""
    p = os.path.join(tmp_dir, "test_data_issues.xlsx")
    sample_excel_with_issues.to_excel(p, index=False)
    return p


# ============================================================
#  Mock LLM fixtures
# ============================================================

@pytest.fixture
def mock_llm_text_response():
    """模拟 LLM 文字评分返回"""
    return {
        "得分_1-1_主题契合度": 4,
        "得分_1-2_文案内容适配": 4,
        "得分_1-3_提交完整性": 5,
        "总分": 13,
        "评语": "主题把握准确，文案适配度好，提交完整",
    }


@pytest.fixture
def mock_llm_vision_response():
    """模拟 LLM 视觉评分返回"""
    return {
        "得分_2-1_主题契合度": 5,
        "得分_2-2_工具使用合理性": 4,
        "得分_2-3_设计创意与完整性": 4,
        "得分_2-4_提交完整性": 5,
        "总分": 18,
        "评语": "设计紧扣主题，创意表现良好",
    }


@pytest.fixture
def mock_llm_empty_response():
    """模拟 LLM 对空题的评分返回"""
    return {
        "得分_1-1_主题契合度": 0,
        "得分_1-2_文案内容适配": 0,
        "得分_1-3_提交完整性": 0,
        "总分": 0,
        "评语": "内容为空或未提交",
    }


@pytest.fixture
def mock_openai_client(mock_llm_text_response):
    """模拟 OpenAI 客户端"""
    mock = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(mock_llm_text_response, ensure_ascii=False)
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage.prompt_tokens = 500
    mock_response.usage.completion_tokens = 200
    mock.chat.completions.create.return_value = mock_response
    return mock


# ============================================================
#  查重测试 fixtures
# ============================================================

@pytest.fixture
def sample_meta_list():
    """模拟查重元数据列表"""
    return [
        {
            "file": "255102030101张三.docx",
            "path": "/tmp/papers/255102030101张三.docx",
            "file_md5": "abc123def456",
            "created": "2024-06-01T10:00:00Z",
            "modified": "2024-06-15T14:30:00Z",
            "creator": "张三",
            "lastModifiedBy": "张三",
            "revision": 45,
            "total_time": 120,
            "application": "Microsoft Word",
            "student_id": "255102030101",
            "student_name": "张三",
        },
        {
            "file": "255102030102李四.docx",
            "path": "/tmp/papers/255102030102李四.docx",
            "file_md5": "xyz789ghi012",
            "created": "2024-06-01T10:05:00Z",
            "modified": "2024-06-15T14:35:00Z",
            "creator": "李四",
            "lastModifiedBy": "李四",
            "revision": 3,
            "total_time": 3,
            "application": "WPS Office",
            "student_id": "255102030102",
            "student_name": "李四",
        },
    ]


# ============================================================
#  DB module mock
# ============================================================

@pytest.fixture(autouse=True)
def disable_db():
    """所有测试默认禁用数据库，避免 SQLite 文件残留"""
    import src.db as db_mod
    old = db_mod.DB_ENABLED
    db_mod.DB_ENABLED = False
    yield
    db_mod.DB_ENABLED = old


# ============================================================
#  评分结果 fixtures
# ============================================================

@pytest.fixture
def sample_grading_results():
    """模拟批改结果列表"""
    return [
        {
            "student_id": "255102030101",
            "student_name": "张三",
            "class_name": "软件2501",
            "total_score": 78,
            "file_name": "255102030101张三.docx",
            "_source_file": "255102030101张三.docx",
            "_criteria": {
                "1": {
                    "1-1": {"score": 4, "max": 5, "reason": "主题把握准确"},
                    "1-2": {"score": 4, "max": 5, "reason": "文案适配度好"},
                    "1-3": {"score": 5, "max": 5, "reason": "提交完整"},
                },
                "4": {
                    "4-1": {"score": 5, "max": 5, "reason": "去重正确"},
                    "4-2": {"score": 5, "max": 5, "reason": "空值处理正确"},
                },
            },
            "q1_score": 13,
            "q4_score": 10,
        },
        {
            "student_id": "255102030102",
            "student_name": "李四",
            "class_name": "软件2501",
            "total_score": 55,
            "file_name": "255102030102李四.docx",
            "_source_file": "255102030102李四.docx",
            "_criteria": {
                "1": {
                    "1-1": {"score": 2, "max": 5, "reason": "部分偏题"},
                    "1-2": {"score": 3, "max": 5, "reason": "文案一般"},
                    "1-3": {"score": 2, "max": 5, "reason": "截图缺失"},
                },
            },
            "q1_score": 7,
        },
    ]
