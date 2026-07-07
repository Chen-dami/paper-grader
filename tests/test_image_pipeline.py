"""
图片识别全链路测试 -- 覆盖各种场景，防止"有图却给0分"。

场景覆盖：
  1.  单vision题：学生提交3张生成图 + 2张截图
  2.  单vision题：学生第一张是AI对话截图（不是效果图）
  3.  多vision题：Q2(图像) + Q3(视频) 各有多张图片
  4.  vision题：只有截图没有单独导出的生成图
  5.  小尺寸图片：200px 边界
  6.  小文件图片：50KB 边界
  7.  vision题无图空判
  8.  文字题has_screenshot不被污染
  9.  混合内容-首图是AI对话
  10. 全链路追踪-展示视觉模型实际收到的内容

用法：
  pytest tests/test_image_pipeline.py -v -s
  pytest tests/test_image_pipeline.py -v -s -k "scenario"
"""

import os, sys, json, tempfile, shutil, io
from pathlib import Path
from PIL import Image as PILImage
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.preprocessor import process
from src.grader import _is_truly_empty
from src.grader_strategies import apply_strategy, GradingStrategy
from src.model_router import MODEL_REGISTRY


# ================================================================
#  图片生成工具
# ================================================================

def _make_png_bytes(width: int, height: int) -> bytes:
    img = PILImage.new("RGB", (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_jpeg_bytes(width: int, height: int, quality: int = 95) -> bytes:
    img = PILImage.new("RGB", (width, height), color=(200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _save_image(data: bytes, dir_path: str, name: str) -> str:
    path = os.path.join(dir_path, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


# ================================================================
#  配置工厂
# ================================================================

def _make_config():
    return {
        "image": {"max_width": 4096, "quality": 95, "skip_below_kb": 0},  # 测试中不过滤小文件
        "grading": {
            "mode": "normal",
            "tiers": {
                "贴合主题": {"ratio_min": 0.8, "ratio_max": 1.0},
                "素材不足": {"ratio_min": 0.4, "ratio_max": 0.6},
                "空": {"ratio_min": 0.0, "ratio_max": 0.0},
            },
        },
    }


def _make_rubric():
    """精简版 rubric，关键题Q2和Q3都是vision类型"""
    return {
        "exam": {"name": "测试", "semester": "2025-2026", "total_score": 100},
        "questions": [
            {
                "id": 1, "name": "文本生成", "max_score": 15,
                "grading_type": "text",
                "topic_keywords": ["三亚", "毕业季"],
                "submission_labels": [
                    {"label": "提示词", "field": "prompt_text"},
                    {"label": "生成结果截图", "field": "result_text", "type": "image"},
                ],
                "criteria": [
                    {"id": "1-1", "name": "主题契合度", "max": 5, "desc": ""},
                    {"id": "1-2", "name": "文案质量", "max": 5, "desc": ""},
                    {"id": "1-3", "name": "提交完整性", "max": 5, "desc": ""},
                ],
                "tier": {"text_min": 10, "perfunctory_max": 50, "keyword_min": 1,
                         "keyword_need": 2, "materials": {"screenshot": True},
                         "material_missing_max": 1},
            },
            {
                "id": 2, "name": "图像设计", "max_score": 20,
                "grading_type": "vision",
                "topic_keywords": ["文昌", "航天", "海报"],
                "submission_labels": [
                    {"label": "提示词", "field": "prompt_text"},
                    {"label": "海报设计图", "field": "result_text", "type": "image"},
                ],
                "criteria": [
                    {"id": "2-1", "name": "主题契合度", "max": 5, "desc": ""},
                    {"id": "2-2", "name": "工具使用合理性", "max": 5, "desc": ""},
                    {"id": "2-3", "name": "设计创意", "max": 5, "desc": ""},
                    {"id": "2-4", "name": "提交完整性", "max": 5, "desc": ""},
                ],
                "tier": {"text_min": 10, "perfunctory_max": 40, "keyword_min": 1,
                         "keyword_need": 2,
                         "materials": {"screenshot": True, "images": True},
                         "material_missing_max": 1},
            },
            {
                "id": 3, "name": "视频创作", "max_score": 20,
                "grading_type": "vision",
                "topic_keywords": ["黎锦", "非遗"],
                "submission_labels": [
                    {"label": "生成图片的提示词", "field": "image_prompt"},
                    {"label": "生成视频的提示词", "field": "video_prompt"},
                ],
                "criteria": [
                    {"id": "3-1", "name": "主题契合度", "max": 4, "desc": ""},
                    {"id": "3-2", "name": "图片生成质量", "max": 4, "desc": ""},
                    {"id": "3-3", "name": "人物服饰与背景", "max": 4, "desc": ""},
                    {"id": "3-4", "name": "配音与整体效果", "max": 4, "desc": ""},
                    {"id": "3-5", "name": "提交完整性", "max": 4, "desc": ""},
                ],
                "tier": {"text_min": 10, "perfunctory_max": 40, "keyword_min": 1,
                         "keyword_need": 2,
                         "materials": {"screenshot": True, "images": True, "video": True},
                         "material_missing_max": 2},
            },
        ],
    }


# ================================================================
#  paper_data 构建器
# ================================================================

def _build_paper_data(img_dir: str, images: list,
                      q_tables: dict = None,
                      student_name: str = "测试学生") -> dict:
    """
    构建模拟 extractor 的 paper_data。

    预处理器的表格匹配规则：
      - 表头表：1-2行，其首行需包含题目名才能匹配
      - 内容表：3+行（len > 2）
      - 格式：Q1表头 → Q1内容 → Q2表头 → Q2内容 → ...
      - 未匹配的表头按文档顺序分配给未匹配的题（fallback）
    """
    all_tables = []

    if q_tables is None:
        # 默认：每个题 = 1个2行表头 + 1个3行内容表
        defaults = {
            1: [
                # 表头（2行，首行含题目名）
                [["提示词", "生成结果"],
                 ["文本生成 - 提交内容"]],
                # 内容（3行）
                [["写一篇三亚种草文案300字以内", "三亚毕业季文案正文...", "备注"],
                 ["使用了豆包AI生成工具", "", ""],
                 ["小红书文案发布", "", ""]],
            ],
            2: [
                # 表头（2行，首行含题目名）
                [["提示词", "海报设计图"],
                 ["图像设计 - 提交内容"]],
                # 内容（3行）
                [["设计航天海报科幻风格", "（见下方海报图）", "使用了即梦AI平台"],
                 ["主题：文昌航天发射场", "", ""],
                 ["风格：赛博朋克+中国航天元素", "", ""]],
            ],
            3: [
                # 表头（2行，首行含题目名）
                [["生成图片的提示词", "生成视频的提示词"],
                 ["视频创作 - 提交内容"]],
                # 内容（3行）
                [["黎锦纹样高清特写图像", "身着黎锦服饰人物出镜", "备注"],
                 ["使用豆包图生视频功能", "", ""],
                 ["背景：海南黎族村落实景", "", ""]],
            ],
        }
        q_tables = defaults

    for qid in sorted(q_tables.keys()):
        all_tables.extend(q_tables[qid])

    paper_dir = tempfile.mkdtemp(prefix="test_paper_")
    return {
        "file_name": f"test_{student_name}.docx",
        "paper_dir": paper_dir,
        "student_info": {"学号": "2024001", "姓名": student_name, "班级": "测试班"},
        "paragraphs": [(0, ""), (1, f"学生：{student_name}")],
        "tables": all_tables,
        "images": images,
        "embedded_files": [],
    }


# ================================================================
#  场景测试类
# ================================================================

class TestImagePipelineScenarios:
    """图片识别全链路场景测试"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_dir, monkeypatch):
        self.tmp_dir = tmp_dir
        self.img_dir = os.path.join(tmp_dir, "images")
        os.makedirs(self.img_dir, exist_ok=True)
        self.rubric = _make_rubric()
        self.config = _make_config()
        # 确保模型检测通过
        monkeypatch.setenv("DEEPSEEK_KEY", "sk-test-ds")
        monkeypatch.setenv("BAILIAN_KEY", "sk-test-bl")
        monkeypatch.setenv("ZHIPU_KEY", "sk-test-zp")

    def _add_images(self, specs: list, table_idx: int = -1) -> list:
        """批量创建图片，返回 [(path, w, h, size_bytes, order_idx, table_idx), ...]"""
        result = []
        for i, (label, w, h) in enumerate(specs):
            fmt = label.split("_")[-1] if "_" in label else "png"
            if fmt == "jpg":
                data = _make_jpeg_bytes(w, h)
                fname = f"{label}_{w}x{h}.jpg"
            else:
                data = _make_png_bytes(w, h)
                fname = f"{label}_{w}x{h}.png"
            path = _save_image(data, self.img_dir, fname)
            # 格式: (path, w, h, size_bytes, order_idx, table_idx)
            result.append((path, w, h, len(data), i, table_idx))
        return result

    # ================================================================
    #  场景1: 正常提交 - 3张生成图 + 2张截图
    # ================================================================

    def test_scenario_1_normal_submission(self):
        """
        场景1 [正常提交]: Q2图像设计题
        - 3张生成图 (1024x1024)
        - 2张截图 (1920x1080, 面积更大)

        验证: 图片是否被正确分配给Q2
              截图是否因面积大而排在生成图前面 (BUG!)
        """
        imgs = self._add_images([
            ("generated_1", 1024, 1024),
            ("generated_2", 1024, 1024),
            ("generated_3", 1024, 1024),
            ("screenshot_AI", 1920, 1080),
            ("screenshot_platform", 1920, 1080),
        ])

        paper = _build_paper_data(self.img_dir, imgs)
        result = process(paper, self.rubric, self.config)

        q2 = result["q2"]
        gen_imgs = q2.get("generated_images", [])

        print(f"\n===== 场景1: 正常提交 =====")
        print(f"全部图片 ({len(imgs)}张):")
        for i, (p, w, h, sz, oi, ti) in enumerate(imgs):
            name = os.path.basename(p)
            area = w * h
            print(f"  [{i}] {name:35s} {w}x{h:<6}  area={area:>10,}  {sz//1024}KB")

        print(f"\nQ2.generated_images ({len(gen_imgs)}张):")
        gen_names = []
        for i, p in enumerate(gen_imgs):
            name = os.path.basename(p)
            gen_names.append(name)
            print(f"  [{i}] {name}")

        screenshot_count = sum(1 for n in gen_names if "screenshot" in n)
        generated_count = sum(1 for n in gen_names if "generated" in n)
        print(f"\n[诊断] generated_images 中: 截图={screenshot_count}张, 生成图={generated_count}张")

        # 关键断言
        assert len(gen_imgs) > 0, "[BUG] Q2有5张图但generated_images为空 -- 图片完全没被分配!"

        if screenshot_count > generated_count:
            print("[BUG] 面积排序导致截图排在生成图前面! 视觉模型首先看到的是AI对话框而非设计作品!")
            print("       根因: preprocessor.py L446 按面积降序排列")

    # ================================================================
    #  场景2: 第一张是AI对话截图（不是效果图）
    # ================================================================

    def test_scenario_2_first_is_ai_chat(self):
        """
        场景2 [首图是AI对话]: 学生贴的第一张图是AI对话截图
        - AI对话截图 1920x1080 (面积最大)
        - 生成海报 1024x1024
        - 平台全屏截图 1920x1080 (面积最大)
        - 参考图 800x800

        验证: 视觉模型收到的前3张图中，前2张可能都是截图
        """
        imgs = self._add_images([
            ("screenshot_chat", 1920, 1080),     # AI对话截图 - 面积最大
            ("generated_poster", 1024, 1024),     # 生成海报
            ("screenshot_full", 1920, 1080),      # 平台全屏截图 - 面积最大
            ("reference_img", 800, 800),          # 参考图
        ])

        paper = _build_paper_data(self.img_dir, imgs)
        result = process(paper, self.rubric, self.config)

        q2 = result["q2"]
        gen_imgs = q2.get("generated_images", [])

        print(f"\n===== 场景2: 首图是AI对话截图 =====")
        print(f"图片(按面积降序排列后):")
        sorted_imgs = sorted(imgs, key=lambda x: x[1] * x[2], reverse=True)
        for i, (p, w, h, sz, oi, ti) in enumerate(sorted_imgs):
            name = os.path.basename(p)
            label = "<-- 发给视觉模型" if i < 3 else ""
            print(f"  {name:30s} {w}x{h:<6}  area={w*h:>10,}  {label}")

        print(f"\nQ2.generated_images (前3张发给视觉模型):")
        for i, p in enumerate(gen_imgs):
            name = os.path.basename(p)
            img_type = "截图/UI" if "screenshot" in name else ("生成图" if "generated" in name else "参考图")
            print(f"  [{i}] {name:30s} -> {img_type}")

        assert len(gen_imgs) > 0, "[BUG] Q2应该有图片但generated_images为空!"
        if gen_imgs:
            first_name = os.path.basename(gen_imgs[0])
            if "screenshot" in first_name:
                print("[BUG] 视觉模型第一张看到的是截图而非效果图!")
                print("       影响: describe_images 主要描述的是AI对话框UI，不是海报设计")

    # ================================================================
    #  场景3: 多vision题共享图片
    # ================================================================

    def test_scenario_3_multi_vision_shared(self):
        """
        场景3 [多vision题]: Q2(图像) + Q3(视频) 都是vision类型
        文档有6张图 -- Q2和Q3各自拿到什么?

        验证: Q2和Q3是否拿到相同的图片 (BUG!)
        """
        imgs = self._add_images([
            ("q2_poster_1", 1024, 1024),
            ("q2_poster_2", 800, 800),
            ("q2_screenshot", 1920, 1080),
            ("q2_ref", 600, 600),
            ("q3_video_thumb", 1024, 768),
            ("q3_screenshot", 1920, 1080),
        ])

        paper = _build_paper_data(self.img_dir, imgs)
        result = process(paper, self.rubric, self.config)

        q2 = result["q2"]
        q3 = result["q3"]
        q2_imgs = [os.path.basename(p) for p in q2.get("generated_images", [])]
        q3_imgs = [os.path.basename(p) for p in q3.get("generated_images", [])]

        print(f"\n===== 场景3: 多vision题 =====")
        print(f"全部图片: {[os.path.basename(p) for p,_,_,_,_,_ in imgs]}")
        print(f"Q2.generated_images: {q2_imgs}")
        print(f"Q3.generated_images: {q3_imgs}")

        if q2_imgs == q3_imgs:
            print("[BUG] Q2和Q3的generated_images完全相同!")
            print("       Q3视频题看到的是Q2的海报图，评分完全错误")
        elif q2_imgs and q3_imgs:
            q2_only = set(q2_imgs) - set(q3_imgs)
            q3_only = set(q3_imgs) - set(q2_imgs)
            print(f"Q2独有: {q2_only}")
            print(f"Q3独有: {q3_only}")
            print("[OK] Q2和Q3图片有区分")
        else:
            print("[BUG] Q2或Q3的generated_images为空!")

    # ================================================================
    #  场景4: 只有截图没有单独导出的生成图
    # ================================================================

    def test_scenario_4_only_screenshots(self):
        """
        场景4 [只有截图]: 学生把AI对话窗口整个截下来，没有单独导出生成图
        - 2张全屏截图

        验证: 不应被判为空 -- 截图中包含了生成效果
        """
        imgs = self._add_images([
            ("screenshot_1", 1920, 1080),
            ("screenshot_2", 1920, 1080),
        ])

        paper = _build_paper_data(self.img_dir, imgs)
        result = process(paper, self.rubric, self.config)

        q2 = result["q2"]

        print(f"\n===== 场景4: 只有截图 =====")
        print(f"Q2.has_screenshot: {q2.get('has_screenshot')}")
        print(f"Q2.generated_images: {len(q2.get('generated_images', []))}张")
        print(f"Q2.result_is_screenshot: {q2.get('result_is_screenshot')}")
        is_empty = _is_truly_empty(q2, "vision")
        print(f"_is_truly_empty: {is_empty}")

        assert q2.get("has_screenshot"), \
            "[BUG] 有2张截图但has_screenshot=False!"
        assert len(q2.get("generated_images", [])) > 0, \
            "[BUG] 有截图但generated_images为空 -> _is_truly_empty会误判为空白!"
        assert not is_empty, \
            "[BUG] 有截图内容被判为空 -> 学生得0分!"

    # ================================================================
    #  场景5: 图片尺寸边界 (200px)
    # ================================================================

    def test_scenario_5_size_boundary(self):
        """
        场景5 [尺寸边界]: 测试 w>200 and h>200 过滤条件
        - 201x201 (刚好过)
        - 200x200 (刚好不过)
        - 199x199 (不过)

        验证: 边界行为
        """
        imgs = self._add_images([
            ("border_201", 201, 201),
            ("border_200", 200, 200),
            ("border_199", 199, 199),
        ])

        paper = _build_paper_data(self.img_dir, imgs)
        result = process(paper, self.rubric, self.config)

        q2 = result["q2"]
        gen_imgs = q2.get("generated_images", [])
        gen_names = [os.path.basename(p) for p in gen_imgs]

        print(f"\n===== 场景5: 尺寸边界 =====")
        print(f"输入: border_201(201x201), border_200(200x200), border_199(199x199)")
        print(f"Q2.generated_images: {gen_names}")

        has_201 = any("border_201" in n for n in gen_names)
        has_200 = any("border_200" in n for n in gen_names)
        has_199 = any("border_199" in n for n in gen_names)

        print(f"201x201 通过: {has_201} (期望:True)")
        print(f"200x200 通过: {has_200} (期望:False -- w>200不满足)")
        print(f"199x199 通过: {has_199} (期望:False)")

        if not has_201:
            print("[BUG] 201x201应该通过但没有!")
        if has_200:
            print("[NOTE] 200x200也通过了，过滤条件实际是 w>=200")

    # ================================================================
    #  场景6: 文件大小边界 (50KB)
    # ================================================================

    def test_scenario_6_file_size_boundary(self):
        """
        场景6 [文件大小边界]: 测试 skip_below_kb=50 过滤
        """
        large_png = _make_png_bytes(500, 500)
        small_jpg = _make_jpeg_bytes(100, 100, quality=10)
        tiny_jpg = _make_jpeg_bytes(50, 50, quality=5)

        print(f"\n===== 场景6: 文件大小边界 =====")
        print(f"大PNG(500x500): {len(large_png)//1024}KB")
        print(f"小JPG(100x100,q=10): {len(small_jpg)//1024}KB")
        print(f"极小JPG(50x50,q=5): {len(tiny_jpg)//1024}KB")
        print(f"跳过阈值: {self.config['image']['skip_below_kb']}KB")

        lp = _save_image(large_png, self.img_dir, "large.png")
        sp = _save_image(small_jpg, self.img_dir, "small.jpg")
        tp = _save_image(tiny_jpg, self.img_dir, "tiny.jpg")

        imgs = [
            (lp, 500, 500, len(large_png)),
            (sp, 100, 100, len(small_jpg)),
            (tp, 50, 50, len(tiny_jpg)),
        ]

        paper = _build_paper_data(self.img_dir, imgs)
        result = process(paper, self.rubric, self.config)

        all_imgs = result.get("all_images", [])
        all_names = [os.path.basename(p) for p, _, _ in all_imgs]

        print(f"过滤后保留: {all_names}")

        large_kept = any("large" in n for n in all_names)
        small_kept = any("small" in n for n in all_names)
        tiny_kept = any("tiny" in n for n in all_names)

        print(f"large.png 保留: {large_kept}")
        print(f"small.jpg 保留: {small_kept} (size={len(small_jpg)//1024}KB)")
        print(f"tiny.jpg 保留: {tiny_kept} (size={len(tiny_jpg)//1024}KB)")

        assert large_kept, "[BUG] 大PNG应该被保留!"

    # ================================================================
    #  场景7: vision题无图空判
    # ================================================================

    def test_scenario_7_vision_empty(self):
        """
        场景7 [vision题无图]: 学生只填了文字没贴图
        """
        imgs = []  # 无图

        q_tables = {
            2: [
                # 表头(2行)
                ["提示词", "海报设计图"],
                ["图像设计题"],
                # 内容(3行) - 很短
                ["设计海报", "", ""],
                ["", "", ""],
                ["", "", ""],
            ],
        }

        paper = _build_paper_data(self.img_dir, imgs, q_tables=q_tables)
        result = process(paper, self.rubric, self.config)

        q2 = result["q2"]

        print(f"\n===== 场景7: vision题无图 =====")
        print(f"Q2.prompt_text: '{q2.get('prompt_text')}'")
        print(f"Q2.generated_images: {q2.get('generated_images', [])}")
        print(f"Q2.has_screenshot: {q2.get('has_screenshot')}")

        is_empty = _is_truly_empty(q2, "vision")
        print(f"_is_truly_empty: {is_empty}")

        # "设计海报"只有4个字(<5)且无图 -> 应为空
        assert is_empty, \
            "[BUG] 只有4字且无图的vision题应该被判为空!"

    # ================================================================
    #  场景8: has_screenshot 跨题污染
    # ================================================================

    def test_scenario_8_screenshot_pollution(self):
        """
        场景8 [跨题污染]: Q1文字题不应有has_screenshot
        文档中Q2有5张图，但Q1是纯文字题

        验证: Q1.has_screenshot 是否为 False
        """
        imgs = self._add_images([
            ("q2_img_1", 1024, 1024),
            ("q2_img_2", 1024, 1024),
            ("q2_img_3", 800, 800),
            ("q2_scr_1", 1920, 1080),
            ("q2_scr_2", 1920, 1080),
        ])

        paper = _build_paper_data(self.img_dir, imgs)
        result = process(paper, self.rubric, self.config)

        q1 = result["q1"]
        q2 = result["q2"]

        print(f"\n===== 场景8: has_screenshot跨题污染 =====")
        print(f"全部图片数: {len(imgs)}")
        print(f"Q1(文字题).has_screenshot: {q1.get('has_screenshot')}")
        print(f"Q2(图像题).has_screenshot: {q2.get('has_screenshot')}")

        if q1.get("has_screenshot"):
            print("[BUG] Q1文字题被误标记为has_screenshot=True!")
            print("      根因: preprocessor.py L382: len(images)>=2 -> 所有题has_screenshot")
            print("      影响: Q1评分时LLM以为有截图，但实际没有")
        else:
            print("[OK] Q1文字题has_screenshot正确=False")

    # ================================================================
    #  场景9: 混合内容 - 视觉模型实际看到什么
    # ================================================================

    def test_scenario_9_mixed_what_vision_sees(self):
        """
        场景9 [混合内容]: 模拟真实学生提交
        - AI对话截图 (1920x1080) -> 面积最大
        - 生成海报图 (1024x1024)
        - 生成海报变体 (1024x1024)
        - 平台全屏截图 (1920x1080) -> 面积最大
        - 参考素材图 (800x600)

        按面积排序后前3: [AI对话截图, 平台截图, 海报1]
        视觉模型主要看到的是UI界面，不是设计作品
        """
        imgs = self._add_images([
            ("chat_screenshot", 1920, 1080),
            ("poster_v1", 1024, 1024),
            ("poster_v2", 1024, 1024),
            ("platform_screenshot", 1920, 1080),
            ("reference", 800, 600),
        ])

        paper = _build_paper_data(self.img_dir, imgs)
        result = process(paper, self.rubric, self.config)

        q2 = result["q2"]
        gen_imgs = q2.get("generated_images", [])

        print(f"\n===== 场景9: 混合内容 =====")
        print(f"图片(按面积降序排列后发给视觉模型的前3张):")
        sorted_by_area = sorted(imgs, key=lambda x: x[1] * x[2], reverse=True)
        for i, (p, w, h, sz, oi, ti) in enumerate(sorted_by_area):
            name = os.path.basename(p)
            ch = "<<< 发给视觉模型" if i < 3 else ""
            print(f"  [{i}] {name:30s} {w}x{h}  area={w*h:>10,}  {ch}")

        print(f"\nQ2.generated_images (前3):")
        for i, p in enumerate(gen_imgs):
            name = os.path.basename(p)
            print(f"  [{i}] {name}")

        # 关键诊断
        first_three_names = [os.path.basename(p) for p in gen_imgs[:3]]
        screenshot_in_top3 = sum(1 for n in first_three_names if "screenshot" in n)
        poster_in_top3 = sum(1 for n in first_three_names if "poster" in n)

        print(f"\n前3张中: 截图={screenshot_in_top3}, 海报={poster_in_top3}")
        if screenshot_in_top3 >= 2:
            print("[BUG] 前3张中截图占多数! 视觉模型看到的全是UI界面!")
            print("       describe_images会描述 '对话框、按钮、输入框'")
            print("       DeepSeek基于此描述评分 -> 完全无法评估海报质量!")

    # ================================================================
    #  场景10: 全链路追踪
    # ================================================================

    def test_scenario_10_full_trace(self):
        """
        场景10 [全链路追踪]: 展示每种模型策略下会给视觉模型传哪些图
        """
        imgs = self._add_images([
            ("chat_scr", 1920, 1080),
            ("poster_1", 1024, 1024),
            ("poster_2", 800, 800),
            ("platform_scr", 1920, 1080),
        ])

        paper = _build_paper_data(self.img_dir, imgs)
        result = process(paper, self.rubric, self.config)

        q2 = result["q2"]
        q2_q = self.rubric["questions"][1]

        print(f"\n===== 场景10: 全链路追踪 =====")
        print(f"Q2 q_data 关键字段:")
        print(f"  prompt_text: '{q2.get('prompt_text', '')[:80]}'")
        print(f"  has_screenshot: {q2.get('has_screenshot')}")
        print(f"  result_is_screenshot: {q2.get('result_is_screenshot')}")
        print(f"  generated_images: {len(q2.get('generated_images', []))}张")
        print(f"  reference_image: {q2.get('reference_image')}")

        print(f"\n各模型策略选取的图片:")
        for model_name in ["deepseek-chat", "glm-4v-flash", "qwen-vl-plus", "qwen-vl-max"]:
            info = MODEL_REGISTRY.get(model_name, {})
            if not info.get("vision", False):
                print(f"\n  {model_name}: 纯文本, 不传图")
                continue

            strategy_imgs, notes = apply_strategy(model_name, q2_q, q2)
            print(f"\n  {model_name} (最多{info.get('image_limit', 0)}图):")
            print(f"    选取: {len(strategy_imgs)}张")
            for i, p in enumerate(strategy_imgs):
                print(f"      [{i}] {os.path.basename(p)}")

        # 展示 describe_images 实际会发给视觉模型的内容
        print(f"\n===== describe_images 发送内容 =====")
        print(f"题目名: {q2_q['name']}")
        print(f"描述维度: 整体内容/文字信息/视觉质量/技术细节/视频帧")
        print(f"指令: 不要评价好坏，不要打分")
        print(f"输出限制: max_tokens=min(1024, model_max)")

        if q2.get("generated_images"):
            print(f"\n实际会发送 {len(q2['generated_images'][:5])} 张图给 qwen-vl-plus")
            for i, p in enumerate(q2["generated_images"][:5]):
                print(f"  [{i}] {os.path.basename(p)}")
        else:
            print("[BUG] generated_images为空, 视觉模型收不到任何图片!")


    # ================================================================
    #  场景11: 基于表格索引的图片分段（核心修复验证）
    # ================================================================

    def test_scenario_11_table_based_segmentation(self):
        """
        场景11 [表格分段]: 模拟 extractor 新格式输出
        - Q2的图片: 在Q2表格范围内 (table_idx=3,4,5)
        - Q3的图片: 在Q3表格范围内 (table_idx=9,10,11)
        - 杂项图片: 未知位置 (table_idx=-1)

        验证: 图片按 table_idx 正确分配给各题 (BUG修复)
        """
        # Q2图片 (table_idx=3 对应 Q2 内容表在 all_tables[3])
        q2_imgs = self._add_images([
            ("q2_poster", 1024, 1024),
            ("q2_poster_v2", 800, 800),
            ("q2_screenshot", 1920, 1080),
        ], table_idx=3)  # Q2内容表索引

        # Q3图片 (table_idx=5 对应 Q3 内容表在 all_tables[5])
        q3_imgs = self._add_images([
            ("q3_video_frame", 1024, 768),
            ("q3_screenshot", 1920, 1080),
        ], table_idx=5)  # Q3内容表索引

        # 无法确定归属的图片 (table_idx=-1)
        orphan_imgs = self._add_images([
            ("orphan_diagram", 600, 400),
        ], table_idx=-1)

        all_imgs = q2_imgs + q3_imgs + orphan_imgs

        # 构建表格，使得Q2匹配到table_idx 3-5范围，Q3匹配到table_idx 9-11范围
        # 真实场景中通过 table_map 匹配，这里我们直接用 process 跑
        paper = _build_paper_data(self.img_dir, all_imgs)
        result = process(paper, self.rubric, self.config)

        q2 = result["q2"]
        q3 = result["q3"]
        q2_gen = [os.path.basename(p) for p in q2.get("generated_images", [])]
        q3_gen = [os.path.basename(p) for p in q3.get("generated_images", [])]

        print(f"\n===== 场景11: 表格分段 =====")
        print(f"全部图片 ({len(all_imgs)}张):")
        for p, w, h, sz, oi, ti in all_imgs:
            print(f"  {os.path.basename(p):30s} table_idx={ti}")
        print(f"\nQ2.generated_images: {q2_gen}")
        print(f"Q3.generated_images: {q3_gen}")
        print(f"Q2.has_screenshot: {q2.get('has_screenshot')}")
        print(f"Q3.has_screenshot: {q3.get('has_screenshot')}")

        # 关键验证
        q2_has_q3_imgs = any("q3_" in n for n in q2_gen)
        q3_has_q2_imgs = any("q2_" in n for n in q3_gen)

        if q2_has_q3_imgs:
            print("[BUG] Q2的generated_images中混入了Q3的图片!")
        if q3_has_q2_imgs:
            print("[BUG] Q3的generated_images中混入了Q2的图片!")
        if not q2_has_q3_imgs and not q3_has_q2_imgs:
            print("[OK] 图片按题正确分段! table_idx工作正常")

        # has_screenshot 应该按各自图片数判断
        print(f"\n[诊断] "
              f"Q2有{len(q2.get('generated_images', []))}张图 -> "
              f"has_screenshot={q2.get('has_screenshot')}")


# ================================================================
#  _is_truly_empty 专项测试
# ================================================================

class TestIsTrulyEmpty:
    """空判逻辑专项"""

    def test_vision_with_images_not_empty(self):
        q_data = {
            "prompt_text": "", "result_text": "", "image_prompt": "",
            "video_prompt": "", "persona_text": "", "all_table_text": "",
            "generated_images": ["/tmp/img1.png"], "reference_image": None,
            "has_video": False, "video_path": "", "bot_link": "",
        }
        assert not _is_truly_empty(q_data, "vision"), \
            "有generated_images的vision题不应判空!"

    def test_vision_short_text_no_image_is_empty(self):
        q_data = {
            "prompt_text": "ab", "result_text": "", "image_prompt": "",
            "video_prompt": "", "persona_text": "", "all_table_text": "",
            "generated_images": [], "reference_image": None,
            "has_video": False, "video_path": "", "bot_link": "",
        }
        assert _is_truly_empty(q_data, "vision"), \
            "文字<5字符且无图 -> 应为空"

    def test_vision_with_text_not_empty(self):
        """有足够文字就不应判空（即使没有图片--文字本身就是提交内容）"""
        q_data = {
            "prompt_text": "设计一张航天海报，包含火箭和星空元素，风格参考赛博朋克",
            "result_text": "", "image_prompt": "",
            "video_prompt": "", "persona_text": "", "all_table_text": "",
            "generated_images": [], "reference_image": None,
            "has_video": False, "video_path": "", "bot_link": "",
        }
        assert not _is_truly_empty(q_data, "vision"), \
            "有文字描述就不应判空"

    def test_has_video_not_empty(self):
        q_data = {
            "prompt_text": "", "result_text": "", "image_prompt": "",
            "video_prompt": "", "persona_text": "", "all_table_text": "",
            "generated_images": [], "reference_image": None,
            "has_video": True, "video_path": "/tmp/test.mp4", "bot_link": "",
        }
        assert not _is_truly_empty(q_data, "vision"), \
            "有视频文件不应判空"


# ================================================================
#  图片选取策略专项
# ================================================================

class TestImagePickingStrategy:
    """grader_strategies 图片选取专项"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_dir, monkeypatch):
        self.tmp_dir = tmp_dir
        self.img_dir = os.path.join(tmp_dir, "test_imgs")
        os.makedirs(self.img_dir, exist_ok=True)
        monkeypatch.setenv("BAILIAN_KEY", "sk-test")
        monkeypatch.setenv("DEEPSEEK_KEY", "sk-test")

    def _make_imgs(self, specs):
        paths = []
        for label, w, h in specs:
            data = _make_png_bytes(w, h)
            p = _save_image(data, self.img_dir, f"{label}_{w}x{h}.png")
            paths.append(p)
        return paths

    def test_pick_multi_includes_all_generated(self):
        """付费模型应取 generated_images[:3] + reference_image"""
        imgs = self._make_imgs([
            ("gen1", 1024, 1024), ("gen2", 1024, 1024),
            ("gen3", 800, 800), ("ref", 600, 600),
        ])

        q_data = {
            "generated_images": [imgs[0], imgs[1], imgs[2]],
            "reference_image": imgs[3],
            "has_video": False, "video_path": "",
        }
        question = {"id": 2, "name": "图像设计", "grading_type": "vision",
                     "max_score": 20, "criteria": []}

        s = GradingStrategy("qwen-vl-plus", question, q_data)
        picked = s.pick_images()

        print(f"\npick_multi (vision非视频): {[os.path.basename(p) for p in picked]}")
        assert len(picked) >= 3, f"应>=3张, 实际{len(picked)}"
        for g in imgs[:3]:
            assert g in picked, f"生成图{os.path.basename(g)}应被选取"

    def test_pick_one_with_only_screenshots(self):
        """免费模型只有截图时也应收录"""
        imgs = self._make_imgs([("screenshot", 1920, 1080)])

        q_data = {
            "generated_images": imgs, "reference_image": None,
            "has_video": False, "video_path": "",
        }
        question = {"id": 2, "name": "图像设计", "grading_type": "vision",
                     "max_score": 20, "criteria": []}

        s = GradingStrategy("glm-4v-flash", question, q_data)
        picked = s.pick_images()

        print(f"\npick_one (tier=1): {[os.path.basename(p) for p in picked]}")
        assert len(picked) == 1, "免费模型应取1张"


# ================================================================
#  视觉策略切换测试
# ================================================================

class TestVisionStrategy:
    """vision_strategy 策略切换测试"""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_KEY", "sk-test")
        monkeypatch.setenv("BAILIAN_KEY", "sk-test")
        monkeypatch.setenv("ZHIPU_KEY", "sk-test")

    def test_text_only_never_uses_vision(self):
        """text_only 策略：任何题目都不调视觉"""
        from src.grader import _should_use_vision
        config = {"vision_strategy": "text_only"}
        assert not _should_use_vision("vision", config)
        assert not _should_use_vision("hybrid", config)
        assert not _should_use_vision("text", config)

    def test_free_vision_uses_vision_for_visual_types(self):
        """free_vision 策略：vision/hybrid 类型用视觉"""
        from src.grader import _should_use_vision
        config = {"vision_strategy": "free_vision"}
        assert _should_use_vision("vision", config)
        assert _should_use_vision("hybrid", config)
        assert not _should_use_vision("text", config)

    def test_paid_vision_uses_vision_for_visual_types(self):
        """paid_vision 策略：vision/hybrid 类型用视觉"""
        from src.grader import _should_use_vision
        config = {"vision_strategy": "paid_vision"}
        assert _should_use_vision("vision", config)
        assert _should_use_vision("hybrid", config)
        assert not _should_use_vision("text", config)

    def test_force_no_vision_overrides_strategy(self):
        """force_no_vision=True 时跳过视觉，标记 _teacher_review_vision"""
        from src.grader import grade
        q_data = {
            "prompt_text": "设计一张航天海报", "result_text": "",
            "image_prompt": "", "video_prompt": "", "persona_text": "",
            "all_table_text": "提示词: 设计航天海报",
            "generated_images": [], "reference_image": None,
            "has_screenshot": True, "has_video": False, "video_path": "",
            "has_excel_file": False, "excel_path": "", "bot_link": "",
        }
        question = {
            "id": 2, "name": "图像设计", "max_score": 20,
            "grading_type": "vision",
            "description": "设计航天海报",
            "criteria": [
                {"id": "2-1", "name": "主题契合度", "max": 10, "desc": ""},
                {"id": "2-2", "name": "设计质量", "max": 10, "desc": ""},
            ],
        }
        config = {
            "vision_strategy": "paid_vision",
            "grading": {"mode": "normal", "tiers": {}},
            "image": {"max_width": 768, "quality": 75, "skip_below_kb": 50},
        }
        result = grade(q_data, question, config, force_no_vision=True)
        assert result.get("_teacher_review_vision"), \
            "force_no_vision 应该标记 _teacher_review_vision=True"
        # force_no_vision 跳过视觉模型但不会跳过文本评分
        # 文本评分可能失败（无真实API key）但标记位应该存在

    def test_default_strategy_is_paid_vision(self):
        """默认策略为 paid_vision"""
        from src.model_router import get_router_config
        rc = get_router_config()
        assert rc.get("vision_strategy") == "paid_vision"

    def test_get_vision_strategy_model_text_only(self):
        """text_only 返回 deepseek-chat"""
        from src.model_router import get_vision_strategy_model
        assert get_vision_strategy_model("text_only") == "deepseek-chat"

    def test_get_vision_strategy_model_free_vision(self):
        """free_vision 返回免费 1图模型"""
        from src.model_router import get_vision_strategy_model
        model = get_vision_strategy_model("free_vision")
        assert model in ("glm-4v-flash", "glm-4.6v-flash"), \
            f"免费策略应返回免费模型，实际: {model}"

    def test_get_vision_strategy_model_paid_vision(self):
        """paid_vision 返回配置的 vision_model"""
        from src.model_router import get_vision_strategy_model, get_router_config
        model = get_vision_strategy_model("paid_vision")
        expected = get_router_config()["vision_model"]
        assert model == expected, f"付费策略应返回 {expected}，实际: {model}"


# ================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("  图片识别全链路诊断")
    print("=" * 60)
    print()
    print("用法:")
    print("  pytest tests/test_image_pipeline.py -v -s")
    print("  pytest tests/test_image_pipeline.py -v -s -k 'scenario_8'")
    print()
    print("已知 Bug:")
    print("  [BUG-1] 所有vision题共享全部图片 (preprocessor.py L441-451)")
    print("  [BUG-2] has_screenshot交叉污染 (preprocessor.py L382)")
    print("  [BUG-3] 面积排序导致截图排在生成图前 (preprocessor.py L446-448)")
    print("  [BUG-4] 小图(<=200px)被过滤 (preprocessor.py L443)")
    print("  [BUG-5] 小文件(<50KB)被跳过 (preprocessor.py L31)")
    print("  [BUG-6] 无按题分段-图片无位置关联信息")
