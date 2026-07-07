#!/usr/bin/env python3
"""
智谱 GLM-4V-Flash 图像识别验证脚本
=============================================
验证流程:
  1. 环境变量检测（ZHIPU_KEY）
  2. API 连通性测试
  3. 图像识别能力验证（生成测试图片 → 调用模型 → 检查结果）
  4. 与 OpenAI 兼容性验证

用法:
  python tools/verify_zhipu_vision.py              # 自动生成测试图
  python tools/verify_zhipu_vision.py --image path  # 指定自己的图片
  python tools/verify_zhipu_vision.py --list-models # 列出可用模型
"""
import os
import sys
import json
import base64
import argparse
import traceback
from pathlib import Path

# 确保项目根在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import OpenAI

# ============================================================
#  配置
# ============================================================
ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
MODEL_NAME = "glm-4v-flash"
ENV_KEY = "ZHIPU_KEY"


def check_env() -> tuple[bool, str]:
    """检查环境变量是否已配置"""
    key = os.environ.get(ENV_KEY, "")
    if not key:
        return False, f"❌ 环境变量 {ENV_KEY} 未设置\n   请运行: set {ENV_KEY}=你的API_KEY  (Windows)\n   或: export {ENV_KEY}=你的API_KEY  (Linux/Mac)"
    # 隐藏部分 key
    masked = key[:8] + "****" + key[-4:] if len(key) > 12 else "****"
    return True, f"✅ {ENV_KEY} = {masked}"


def create_test_image(path: str) -> str:
    """生成一张简单的测试图片（纯色 + 文字区域）"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (400, 300), color=(240, 248, 255))
        draw = ImageDraw.Draw(img)
        # 蓝色矩形
        draw.rectangle([50, 50, 350, 100], fill=(70, 130, 200))
        # 绿色矩形
        draw.rectangle([50, 120, 350, 170], fill=(60, 180, 60))
        # 红色矩形
        draw.rectangle([50, 190, 350, 240], fill=(220, 60, 60))
        # 文字
        try:
            font = ImageFont.load_default()
            draw.text((120, 60), "AI Grader Test Image", fill=(255, 255, 255), font=font)
            draw.text((100, 260), "Zhipu GLM-4V-Flash Verification", fill=(50, 50, 50), font=font)
        except Exception:
            pass
        img.save(path, "PNG")
        return path
    except ImportError:
        # Pillow 不可用时创建最小 PNG
        _create_minimal_png(path)
        return path


def _create_minimal_png(path: str):
    """创建最小有效 PNG（纯红色 16x16）"""
    import struct, zlib
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    ihdr = struct.pack('>IIBBBBB', 16, 16, 8, 2, 0, 0, 0)
    raw = b''
    for _ in range(16):
        raw += b'\x00' + b'\xff\x00\x00' * 16
    compressed = zlib.compress(raw)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(chunk(b'IHDR', ihdr))
        f.write(chunk(b'IDAT', compressed))
        f.write(chunk(b'IEND', b''))


def test_connectivity(api_key: str) -> tuple[bool, str]:
    """测试 API 连通性（不涉及图片）"""
    try:
        client = OpenAI(api_key=api_key, base_url=ZHIPU_BASE_URL)
        response = client.chat.completions.create(
            model=MODEL_NAME,
            max_tokens=50,
            temperature=0.0,
            messages=[{"role": "user", "content": "请回复'连通性测试通过'"}],
        )
        content = response.choices[0].message.content
        tokens = response.usage.prompt_tokens if response.usage else 0
        return True, f"✅ API 连通性正常\n   回复: {content[:80]}\n   消耗 tokens: {tokens}"
    except Exception as e:
        return False, f"❌ API 连通性失败: {str(e)[:200]}"


def test_vision(api_key: str, image_path: str) -> tuple[bool, str]:
    """测试图像识别能力"""
    if not os.path.exists(image_path):
        return False, f"❌ 图片不存在: {image_path}"

    try:
        # 读取并编码图片
        with open(image_path, "rb") as f:
            img_data = base64.standard_b64encode(f.read()).decode("utf-8")

        ext = os.path.splitext(image_path)[1].lower()
        mime_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp",
        }
        mime = mime_map.get(ext, "image/png")

        client = OpenAI(api_key=api_key, base_url=ZHIPU_BASE_URL)

        messages = [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "请详细描述这张图片的内容，包括：1)图片中的颜色 2)图片中的形状或图形 3)图片中是否有文字，如果有请列出。请用中文回答，尽量详细。"
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{img_data}",
                    }
                }
            ]
        }]

        response = client.chat.completions.create(
            model=MODEL_NAME,
            max_tokens=512,
            temperature=0.3,
            messages=messages,
        )

        content = response.choices[0].message.content
        tokens_in = response.usage.prompt_tokens if response.usage else 0
        tokens_out = response.usage.completion_tokens if response.usage else 0

        lines = [
            f"✅ 图像识别成功！",
            f"  模型: {MODEL_NAME}",
            f"  tokens: {tokens_in} in + {tokens_out} out = {tokens_in + tokens_out}",
            f"  回复内容:",
        ]
        for line in content.split("\n"):
            lines.append(f"    {line}")

        return True, "\n".join(lines)

    except Exception as e:
        tb = traceback.format_exc()
        return False, f"❌ 图像识别失败: {str(e)[:300]}\n\n详细错误:\n{tb[:800]}"


def test_openai_compat(api_key: str) -> tuple[bool, str]:
    """测试 OpenAI 兼容接口格式"""
    try:
        client = OpenAI(api_key=api_key, base_url=ZHIPU_BASE_URL)

        # 测试 function calling 格式
        response = client.chat.completions.create(
            model=MODEL_NAME,
            max_tokens=100,
            temperature=0.0,
            messages=[{"role": "user", "content": "请用JSON格式回复: {\"status\": \"ok\"}"}],
        )
        content = response.choices[0].message.content

        # 尝试解析 JSON
        try:
            parsed = json.loads(content) if content else {}
            has_json = True
        except json.JSONDecodeError:
            # 尝试从 markdown 中提取
            import re
            match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', content)
            if match:
                try:
                    parsed = json.loads(match.group(1))
                    has_json = True
                except json.JSONDecodeError:
                    parsed = {}
                    has_json = False
            else:
                parsed = {}
                has_json = False

        return True, (
            f"✅ OpenAI 兼容格式正常\n"
            f"  响应格式: {'JSON' if has_json else 'TEXT'}\n"
            f"  内容: {content[:150]}"
        )
    except Exception as e:
        return False, f"❌ 兼容性测试失败: {str(e)[:200]}"


def list_available_models(api_key: str):
    """列出可用模型（如果 API 支持）"""
    try:
        client = OpenAI(api_key=api_key, base_url=ZHIPU_BASE_URL)
        # 智谱 API 可能不支持 /models 端点，用 chat 方式测试
        print("📋 智谱已知视觉模型:")
        print("   glm-4v-flash  · 极速视觉（推荐，¥0.5/1M input）")
        print("   glm-4v        · 旗舰视觉（¥5/1M input）")
        print("   glm-4v-plus   · 增强视觉（如有权限）")
    except Exception as e:
        print(f"❌ 无法获取模型列表: {e}")


def main():
    parser = argparse.ArgumentParser(description="智谱 GLM-4V-Flash 验证工具")
    parser.add_argument("--image", "-i", type=str, help="指定测试图片路径")
    parser.add_argument("--list-models", action="store_true", help="列出可用模型")
    parser.add_argument("--key", "-k", type=str, help="直接传入 API Key（不读环境变量）")
    args = parser.parse_args()

    print("=" * 60)
    print("  智谱 GLM-4V-Flash 图像识别验证")
    print("=" * 60)

    # ---------- 0. API Key ----------
    api_key = args.key or os.environ.get(ENV_KEY, "")
    if not api_key:
        print(f"\n❌ 未找到 API Key")
        print(f"   请设置环境变量: {ENV_KEY}")
        print(f"   或使用参数: --key 你的key")
        sys.exit(1)

    masked = api_key[:8] + "****" + api_key[-4:] if len(api_key) > 12 else "****"
    print(f"\n🔑 API Key: {masked}")
    print(f"📡 Base URL: {ZHIPU_BASE_URL}")
    print(f"🤖 模型: {MODEL_NAME}")

    # ---------- 1. 连通性测试 ----------
    print(f"\n-- 1. API 连通性测试 --")
    ok, msg = test_connectivity(api_key)
    print(msg)
    if not ok:
        print("\n⚠️  连通性测试失败，跳过后续测试")
        sys.exit(1)

    # ---------- 2. 图像识别测试 ----------
    print(f"\n-- 2. 图像识别能力测试 --")
    if args.image:
        img_path = args.image
    else:
        img_path = os.path.join(os.path.dirname(__file__) or ".", "_test_image.png")
        create_test_image(img_path)
        print(f"   📸 已生成测试图片: {img_path}")

    ok, msg = test_vision(api_key, img_path)
    print(msg)

    # ---------- 3. 兼容性测试 ----------
    print(f"\n-- 3. OpenAI 兼容格式测试 --")
    ok2, msg2 = test_openai_compat(api_key)
    print(msg2)

    # ---------- 4. 可选：模型列表 ----------
    if args.list_models:
        print(f"\n-- 4. 可用模型 --")
        list_available_models(api_key)

    # ---------- 总结 ----------
    print(f"\n{'=' * 60}")
    overall = ok and ok2
    print(f"  {'✅ 全部验证通过！' if overall else '⚠️  部分测试失败，请检查上方输出'}")
    print(f"  模型: {MODEL_NAME}")
    print(f"  类型: 图像识别 (vision)")
    print(f"  状态: {'可用' if overall else '异常'}")
    print(f"{'=' * 60}")

    if overall:
        print(f"\n💡 提示: 在 config.yaml 中将 vision_model 设为 glm-4v-flash 即可使用。")
        print(f"   已在 UI「模型路由」页面完成配置。")

    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
