"""
模型分级评分策略

根据所选模型的能力（图片数、视觉支持）自动调整评分行为：
  - Tier 0: 纯文本 — 不传图，靠文字+文件存在性判断
  - Tier 1: 免费视觉(1图) — 每道题传1张关键图
  - Tier 2: 付费视觉(5图) — 每道题传多图，全面评估

用法:
  from .grader_strategies import get_strategy, apply_strategy
  strategy = get_strategy(model_name, question)
  images = strategy.pick_images(q_data)      # 智能选图
  prompt += strategy.prompt_notes()           # 能力声明
"""

from __future__ import annotations
import os, re


# ============================================================
#  模型能力分级
# ============================================================

def get_model_tier(model_name: str) -> int:
    """
    返回模型能力级别：
      0 = 纯文本（无视觉）
      1 = 免费视觉（1图，输出≤1K）
      2 = 付费视觉（≥5图）
    """
    from .model_router import MODEL_REGISTRY
    info = MODEL_REGISTRY.get(model_name, {})
    if not info.get("vision", False):
        return 0
    img_lim = info.get("image_limit", 0)
    if img_lim <= 1:
        return 1
    return 2


def get_model_display(model_name: str) -> str:
    """模型能力的简短描述，给下拉框用"""
    tier = get_model_tier(model_name)
    from .model_router import MODEL_REGISTRY
    info = MODEL_REGISTRY.get(model_name, {})
    img = info.get("image_limit", 0)
    free = "🆓" if info.get("cost_per_1M_input", 1) == 0 else "💰"
    labels = {0: "纯文本", 1: f"{free}视觉·{img}图", 2: f"{free}视觉·{img}图"}
    return labels.get(tier, "?")


def get_available_tiers() -> dict[int, list[str]]:
    """返回当前环境各能力级别可用的模型列表"""
    from .model_router import MODEL_REGISTRY
    tiers: dict[int, list[str]] = {0: [], 1: [], 2: []}
    for name, info in MODEL_REGISTRY.items():
        key = os.environ.get(info.get("env_key", ""), "")
        if not key:
            continue
        tier = get_model_tier(name)
        tiers[tier].append(name)
    return tiers


# ============================================================
#  策略核心：按题目类型 + 模型能力 → 图片选取 + Prompt说明
# ============================================================

class GradingStrategy:
    """单道题的评分策略"""
    def __init__(self, model_name: str, question: dict, q_data: dict):
        self.model = model_name
        self.tier = get_model_tier(model_name)
        self.q = question
        self.qd = q_data
        self.gtype = question.get("grading_type", "text")
        self.qname = question.get("name", "")

    # ---- 图片选取 ----

    def pick_images(self) -> list[str]:
        """根据模型能力和题目类型，智能选取应该传给模型的图片"""
        if self.tier == 0:
            return []   # 纯文本，不传图

        if self.tier == 1:
            return self._pick_one()

        return self._pick_multi()

    def _pick_one(self) -> list[str]:
        """免费模型：选1张最有代表性的图"""
        gen = self._get_generated()
        if gen:
            return [gen[0]]          # 第一张生成图
        ref = self.qd.get("reference_image", "")
        if ref and os.path.exists(str(ref)):
            return [str(ref)]
        frames = self._get_video_frames(1)
        if frames:
            return [frames[0]]       # 视频第一帧
        return []

    def _pick_multi(self) -> list[str]:
        """付费模型：按题目类型智能分配"""
        gtype = self.gtype
        is_video_q = "视频" in self.qname

        if gtype == "text":
            return self._limit(self._get_generated()[:1])        # 1张截图即可
        elif is_video_q:
            # 视频题：生成图 + 视频帧 + 截图
            imgs = self._get_generated()[:2]
            imgs += self._get_video_frames(3)
            return self._limit(imgs)
        elif gtype == "vision" and not is_video_q:
            # 图像题：生成图 + 截图
            imgs = self._get_generated()[:3]
            ref = self.qd.get("reference_image", "")
            if ref and os.path.exists(str(ref)):
                imgs.append(str(ref))
            return self._limit(imgs)
        elif gtype == "hybrid":
            # 智能体题：生成图（知识库截图等）
            imgs = self._get_generated()[:4]
            return self._limit(imgs)
        elif gtype == "code":
            return []   # 代码题规则引擎，不传图
        return self._limit(self._get_generated()[:2])

    def _get_generated(self) -> list[str]:
        imgs = []
        for k in ["generated_images", "reference_image", "generated_image"]:
            v = self.qd.get(k, "")
            if isinstance(v, list):
                imgs.extend([str(x) for x in v])
            elif isinstance(v, str) and v:
                imgs.append(str(v))
        return [i for i in imgs if i and os.path.exists(i)]

    def _get_video_frames(self, n: int) -> list[str]:
        if self.qd.get("has_video") and self.qd.get("video_path"):
            from .video_frame_extractor import extract_frames as _ef
            try:
                return _ef(self.qd["video_path"], num_frames=n)
            except Exception:
                return []
        return []

    def _limit(self, imgs: list[str]) -> list[str]:
        from .model_router import MODEL_REGISTRY
        limit = MODEL_REGISTRY.get(self.model, {}).get("image_limit", 5)
        return imgs[:limit]

    # ---- Prompt 能力声明 ----

    def prompt_notes(self) -> str:
        """根据模型能力，在评分prompt中加入能力声明和评分指引"""
        if self.tier == 0:
            return self._notes_text_only()
        elif self.tier == 1:
            return self._notes_free_vision()
        return self._notes_paid_vision()

    def _notes_text_only(self) -> str:
        base = (
            "\n【模型能力说明】当前使用纯文本模型，**无法查看任何图片或视频**。\n"
            "评分指引：\n"
            "- 文本内容（提示词、描述等）正常评分，无需扣分\n"
        )
        if "视频" in self.qname:
            base += (
                "- 检查学生是否提交了视频文件（看文本中是否有视频相关描述或路径信息）\n"
                "- 服饰/背景/配音等视觉项：以提示词/描述文字为准，描述详细合理即给满分\n"
                "- 图片质量项：以图片提示词为准，描述清晰详细即给满分\n"
            )
        elif self.gtype == "vision":
            base += (
                "- 视觉设计项：以提示词/描述文字为准，描述吻合主题即给满分\n"
                "- 无法验证实际图片质量，只要文字描述合理就不扣分\n"
            )
        elif self.gtype == "hybrid":
            base += (
                "- 检查文本中是否包含发布链接\n"
                "- 知识库配置等：以人设文本为准\n"
            )
        return base

    def _notes_free_vision(self) -> str:
        from .model_router import MODEL_REGISTRY
        img_limit = MODEL_REGISTRY.get(self.model, {}).get("image_limit", 1)
        base = (
            f"\n【模型能力说明】当前为免费视觉模型，最多可查看 **{img_limit} 张图片**。\n"
            "评分指引：\n"
            "- 可见的图片正常评估\n"
            "- 不可见的素材（如音频、多图对比等）：以文字描述为准，描述合理即给分\n"
        )
        if "视频" in self.qname:
            base += (
                "- 视频帧仅1张，无法全面判断动态效果和配音\n"
                "- 服饰/背景：以可见帧 + 提示词综合判断\n"
                "- 配音/整体效果：以视频提示词描述为准，描述合理即满分\n"
            )
        return base

    def _notes_paid_vision(self) -> str:
        from .model_router import MODEL_REGISTRY
        img_limit = MODEL_REGISTRY.get(self.model, {}).get("image_limit", 5)
        has_frames = bool(self._get_video_frames(1))
        frame_note = ""
        if "视频" in self.qname and not has_frames:
            frame_note = (
                "\n⚠️ 视频帧提取失败（视频格式可能不兼容），"
                "请以文字描述为准判断视频内容，描述合理即给分。"
            )
        return (
            f"\n【模型能力说明】当前为付费视觉模型，最多可查看 **{img_limit} 张图片**。\n"
            "评分指引：全面评估所有可见素材，客观公正打分。"
            f"{frame_note}"
        )

    # ---- 提交完整性检测（避免空判） ----

    def check_materials_text(self) -> dict[str, bool]:
        """纯文本能检测到的素材"""
        result = {
            "has_text": len(str(self.qd.get("prompt_text", "")) + str(self.qd.get("result_text", ""))) > 30,
            "has_image_prompt": bool(self.qd.get("image_prompt", "")),
            "has_video_prompt": bool(self.qd.get("video_prompt", "")),
            "has_video_file": bool(self.qd.get("has_video")),
            "has_link": bool(self.qd.get("bot_link") and "http" in str(self.qd.get("bot_link", ""))),
            "has_screenshot": bool(self.qd.get("has_screenshot")),
        }
        result["video_mentioned"] = (
            result["has_video_prompt"] or
            result["has_video_file"] or
            ("mp4" in str(self.qd.get("all_table_text", "")).lower())
        )
        return result


# ============================================================
#  便捷接口
# ============================================================

def get_strategy(model_name: str, question: dict, q_data: dict) -> GradingStrategy:
    """获取指定模型+题目+学生数据的策略"""
    return GradingStrategy(model_name, question, q_data)


def apply_strategy(model_name: str, question: dict, q_data: dict) -> tuple[list[str], str]:
    """
    一站式：返回 (应传图片列表, 能力声明文本)
    供 grader._grade_llm 直接调用
    """
    s = get_strategy(model_name, question, q_data)
    return s.pick_images(), s.prompt_notes()
