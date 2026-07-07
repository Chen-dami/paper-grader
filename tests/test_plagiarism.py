"""
plagiarism.py 测试 —— 抄袭检测
覆盖：级别分类、元数据提取、两两比对、报告生成、查重入口
"""
import os
import json
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from src.plagiarism import (
    classify_level, check_all, run,
    PLAG_LEVELS, _compare_pair, _extract_meta,
    _extract_texts, _extract_image_hashes, _extract_excel_fingerprints,
    _generate_report, _merge_scores, _find_meta, _student_label,
    _find_docx, _col_letter,
)


class TestClassifyLevel:
    """可疑度分数 → 级别分类"""

    def test_normal(self):
        level = classify_level(50)
        assert level["key"] == "normal"
        assert level["label"] == "✅ 正常"

    def test_suspicious(self):
        level = classify_level(150)
        assert level["key"] == "suspicious"
        assert level["label"] == "⚠️ 可疑"

    def test_high(self):
        level = classify_level(250)
        assert level["key"] == "high"
        assert level["label"] == "🔴 高度可疑"

    def test_confirmed(self):
        level = classify_level(350)
        assert level["key"] == "confirmed"
        assert level["label"] == "🚫 确认抄袭"

    def test_boundary_100(self):
        """边界值：100 → 可疑"""
        level = classify_level(100)
        assert level["key"] == "suspicious"

    def test_boundary_200(self):
        """边界值：200 → 高度可疑"""
        level = classify_level(200)
        assert level["key"] == "high"

    def test_boundary_300(self):
        """边界值：300 → 确认抄袭"""
        level = classify_level(300)
        assert level["key"] == "confirmed"

    def test_zero(self):
        level = classify_level(0)
        assert level["key"] == "normal"


class TestComparePair:
    """两两比对算法"""

    def test_file_md5_identical(self, sample_meta_list):
        """文件MD5完全相同 → 直接350+"""
        m1, m2 = sample_meta_list[0].copy(), sample_meta_list[0].copy()
        m2["file"] = "张三_copy.docx"
        score, reasons, flags = _compare_pair(m1, m2, {}, {}, [], [], "", "")
        assert score >= 350
        assert any("MD5" in r for r in reasons)

    def test_same_application(self, sample_meta_list):
        """同电脑 → +30"""
        m1 = sample_meta_list[0].copy()
        m2 = sample_meta_list[1].copy()
        m2["application"] = m1["application"]  # 设为相同
        score, reasons, flags = _compare_pair(m1, m2, {}, {}, [], [], "", "")
        assert any("同电脑" in r for r in reasons)

    def test_time_disparity(self, sample_meta_list):
        """编辑时长悬殊 → +15"""
        m1 = {"file": "张三.docx", "total_time": 120, "file_md5": "a"}
        m2 = {"file": "李四.docx", "total_time": 2, "file_md5": "b"}
        score, reasons, flags = _compare_pair(m1, m2, {}, {}, [], [], "", "")
        assert any("编辑时长悬殊" in r for r in reasons)

    def test_short_edit_flag(self):
        """编辑时长过短 → flags"""
        m1 = {"file": "张三.docx", "total_time": 3, "file_md5": "a"}
        m2 = {"file": "李四.docx", "total_time": 15, "file_md5": "b"}
        _, _, flags = _compare_pair(m1, m2, {}, {}, [], [], "", "")
        assert any("编辑时长仅3min" in f for f in flags)

    def test_low_revision_flag(self):
        """revision过低 → flags"""
        m1 = {"file": "张三.docx", "revision": 2, "total_time": 5, "file_md5": "a"}
        m2 = {"file": "李四.docx", "revision": 10, "total_time": 20, "file_md5": "b"}
        _, _, flags = _compare_pair(m1, m2, {}, {}, [], [], "", "")
        assert any("revision=2" in f for f in flags)

    def test_text_high_similarity(self):
        """文本高度相似"""
        m1 = {"file": "A.docx", "total_time": 30, "file_md5": "a"}
        m2 = {"file": "B.docx", "total_time": 25, "file_md5": "b"}
        t1 = {"q_all": "完全相同的文本内容ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 5}
        t2 = {"q_all": "完全相同的文本内容ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 5}
        score, reasons, _ = _compare_pair(m1, m2, t1, t2, [], [], "", "")
        # 完全相同 → 相似度 > 0.95
        assert score >= 80
        assert any("相同" in r for r in reasons)

    def test_text_moderate_similarity(self):
        """文本中度相似"""
        m1 = {"file": "A.docx", "total_time": 30, "file_md5": "a"}
        m2 = {"file": "B.docx", "total_time": 25, "file_md5": "b"}
        base = "这是测试文本" * 20
        t1 = {"q_all": base + "AAA独特内容" * 5}
        t2 = {"q_all": base + "BBB独特内容" * 5}
        score, reasons, _ = _compare_pair(m1, m2, t1, t2, [], [], "", "")
        # 大部分相同但尾部不同 → 相似度在 0.70-0.95 之间
        assert score > 0  # 至少有加分

    def test_image_md5_shared(self):
        """共享图片"""
        m1 = {"file": "A.docx", "total_time": 30, "file_md5": "a"}
        m2 = {"file": "B.docx", "total_time": 30, "file_md5": "b"}
        im1 = ["hash1", "hash2", "hash3"]
        im2 = ["hash1", "hash4", "hash5"]
        score, reasons, _ = _compare_pair(m1, m2, {}, {}, im1, im2, "", "")
        assert any("图片完全相同" in r for r in reasons)

    def test_excel_fingerprint_match(self):
        """Excel指纹一致"""
        m1 = {"file": "A.docx", "total_time": 30, "file_md5": "a"}
        m2 = {"file": "B.docx", "total_time": 30, "file_md5": "b"}
        score, reasons, _ = _compare_pair(m1, m2, {}, {}, [], [], "fp123", "fp123")
        assert any("Excel" in r for r in reasons)

    def test_no_issues_returns_zero(self):
        """完全无问题返回 0"""
        m1 = {"file": "A.docx", "total_time": 60, "file_md5": "a",
              "application": "app1", "revision": 50}
        m2 = {"file": "B.docx", "total_time": 55, "file_md5": "b",
              "application": "app2", "revision": 45}
        score, reasons, flags = _compare_pair(m1, m2, {}, {}, [], [], "", "")
        assert score == 0
        assert len(flags) == 0


class TestMergeScores:
    """合并评分结果到元数据"""

    def test_merge_by_filename(self, sample_meta_list):
        grading_results = [
            {
                "_source_file": "255102030101张三.docx",
                "total_score": 85, "student_id": "", "student_name": "",
            }
        ]
        _merge_scores(sample_meta_list, grading_results)
        assert sample_meta_list[0].get("total_score") == 85

    def test_merge_no_match(self, sample_meta_list):
        grading_results = [
            {"_source_file": "nonexistent.docx", "total_score": 100}
        ]
        _merge_scores(sample_meta_list, grading_results)
        # 不匹配的不影响
        assert sample_meta_list[0].get("total_score") is None


class TestFindMeta:
    """查找元数据"""

    def test_find_existing(self, sample_meta_list):
        m = _find_meta(sample_meta_list, "255102030101张三.docx")
        assert m is not None
        assert m["student_name"] == "张三"

    def test_find_nonexistent(self, sample_meta_list):
        m = _find_meta(sample_meta_list, "nonexistent.docx")
        assert m is None


class TestStudentLabel:
    """学生标签"""

    def test_with_both(self):
        m = {"student_id": "255102030101", "student_name": "张三"}
        assert "255102030101" in _student_label(m)
        assert "张三" in _student_label(m)

    def test_with_id_only(self):
        m = {"student_id": "255102030101", "student_name": ""}
        assert _student_label(m) == "255102030101"

    def test_fallback_to_file(self):
        m = {"student_id": "", "student_name": "", "file": "unknown.docx"}
        assert _student_label(m) == "unknown.docx"

    def test_none_returns_question(self):
        assert _student_label(None) == "?"


class TestColLetter:
    """列号→字母"""

    def test_single_letter(self):
        assert _col_letter(1) == "A"
        assert _col_letter(26) == "Z"

    def test_double_letter(self):
        assert _col_letter(27) == "AA"
        assert _col_letter(52) == "AZ"

    def test_triple_letter(self):
        assert _col_letter(703) == "AAA"


class TestFindDocx:
    """递归查找 docx"""

    def test_find_docx(self, tmp_papers_dir):
        """在试卷目录中递归查找"""
        # 创建测试文件
        cls_dir = os.path.join(tmp_papers_dir, "软件2501")
        stu_dir = os.path.join(cls_dir, "255102030101_张三")
        os.makedirs(stu_dir)
        Path(os.path.join(stu_dir, "test.docx")).touch()
        Path(os.path.join(stu_dir, "~$temp.docx")).touch()  # 临时文件应排除

        files = _find_docx(tmp_papers_dir)
        docx_names = [os.path.basename(f) for f in files]
        assert "test.docx" in docx_names
        assert "~$temp.docx" not in docx_names


class TestCheckAll:
    """check_all 主入口"""

    def test_less_than_two_files(self, tmp_papers_dir, tmp_output_dir):
        """少于2份试卷直接返回"""
        pairs, auto_zero = check_all(tmp_papers_dir, [], os.path.join(tmp_output_dir, "查重报告.xlsx"))
        assert pairs == []
        assert auto_zero == set()

    def test_with_two_files_generates_report(self, tmp_papers_dir, tmp_output_dir):
        """2份试卷生成报告"""
        # 创建两份 docx
        cls_dir = os.path.join(tmp_papers_dir, "软件2501")
        d1 = os.path.join(cls_dir, "255102030101_张三")
        d2 = os.path.join(cls_dir, "255102030102_李四")
        os.makedirs(d1); os.makedirs(d2)
        _create_fake_docx(os.path.join(d1, "255102030101张三.docx"))
        _create_fake_docx(os.path.join(d2, "255102030102李四.docx"))

        pairs, auto_zero = check_all(tmp_papers_dir, [],
                                     os.path.join(tmp_output_dir, "查重报告.xlsx"))
        assert isinstance(pairs, list)
        assert isinstance(auto_zero, set)
        # 报告文件应该生成
        assert os.path.exists(os.path.join(tmp_output_dir, "查重报告.xlsx"))


class TestExtractMeta:
    """元数据提取"""

    def test_extract_meta_from_docx(self, tmp_dir):
        """从真实 docx 提取元数据"""
        docx_path = os.path.join(tmp_dir, "test.docx")
        _create_fake_docx(docx_path)
        meta = _extract_meta(docx_path)
        assert meta["file"] == "test.docx"
        assert isinstance(meta["file_md5"], str)
        assert len(meta["file_md5"]) == 32

    def test_extract_student_info_from_filename(self, tmp_dir):
        """从文件名提取学号姓名"""
        docx_path = os.path.join(tmp_dir, "255102030103王五.docx")
        _create_fake_docx(docx_path)
        meta = _extract_meta(docx_path)
        assert meta["student_id"] == "255102030103"
        assert meta["student_name"] == "王五"


class TestExtractTexts:
    """文本提取"""

    def test_extract_texts_from_docx(self, tmp_dir):
        docx_path = os.path.join(tmp_dir, "test.docx")
        _create_fake_docx(docx_path, paragraphs=["第一段", "第二段"])
        text_map = _extract_texts([docx_path])
        assert docx_path in text_map
        assert "第一段" in text_map[docx_path]["q_all"]


def _create_fake_docx(path, paragraphs=None):
    """创建测试 docx"""
    from docx import Document
    doc = Document()
    for p in (paragraphs or ["测试内容"]):
        doc.add_paragraph(p)
    doc.save(path)
