#!/usr/bin/env python3
"""
测试智谱视觉模型的图片数量上限
用法:
  python tools/test_image_limit.py              # 测试 glm-4v-flash
  python tools/test_image_limit.py --model glm-4.6v-flash  # 测试指定模型
  python tools/test_image_limit.py --model glm-4v
"""
import os, sys, base64, io, argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openai import OpenAI
from PIL import Image

ZHIPU_KEY = os.environ.get("ZHIPU_KEY", "")
BASE_URL = "https://open.bigmodel.cn/api/paas/v4"


def create_test_image(color: str, path: str, size: tuple = (200, 200)):
    """创建纯色测试图片"""
    img = Image.new("RGB", size, color=color)
    img.save(path, "PNG")
    return path


def make_vision_content(prompt: str, image_paths: list) -> list:
    """构建视觉 content 数组"""
    content = [{"type": "text", "text": prompt}]
    for img_path in image_paths:
        with open(img_path, "rb") as f:
            img_data = base64.standard_b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(img_path)[1].lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg"}
        mime = mime_map.get(ext, "image/png")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{img_data}"},
        })
    return content


def test_with_n_images(model: str, n: int, client: OpenAI) -> tuple[bool, str]:
    """测试发送 n 张图片"""
    tmp_dir = os.path.join(os.path.dirname(__file__) or ".", "_test_imgs")
    os.makedirs(tmp_dir, exist_ok=True)

    colors = ["red", "green", "blue", "yellow", "purple", "orange",
              "pink", "cyan", "magenta", "lime"]
    paths = []
    for i in range(n):
        c = colors[i % len(colors)]
        p = os.path.join(tmp_dir, f"test_{i}.png")
        create_test_image(c, p)
        paths.append(p)

    prompt = f"我发送了{n}张纯色图片。请告诉我：1)你看到了几张图片？2)每张图片分别是什么颜色？请用JSON回复：{{\"count\": {n}, \"colors\": [\"颜色列表\"]}}"

    try:
        content = make_vision_content(prompt, paths)
        response = client.chat.completions.create(
            model=model,
            max_tokens=200,
            temperature=0.0,
            messages=[{"role": "user", "content": content}],
        )
        result = response.choices[0].message.content[:300]
        tokens = response.usage.prompt_tokens if response.usage else 0
        return True, f"✅ {n}张图 — tokens:{tokens} — 回复:{result[:200]}"
    except Exception as e:
        return False, f"❌ {n}张图失败 — {str(e)[:200]}"

    finally:
        for p in paths:
            try:
                os.remove(p)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description="测试视觉模型图片数量上限")
    parser.add_argument("--model", "-m", type=str, default="glm-4v-flash",
                        help="模型名称，如 glm-4v-flash, glm-4.6v-flash, glm-4v")
    parser.add_argument("--max", type=int, default=6,
                        help="最多测试几张图 (默认6)")
    args = parser.parse_args()

    model = args.model
    print("=" * 60)
    print(f"  模型图片数量上限测试")
    print(f"  模型: {model}")
    print(f"  Key: {'已设置' if ZHIPU_KEY else '❌ 未设置!'}")
    print("=" * 60)

    if not ZHIPU_KEY:
        print("\n❌ 请先设置环境变量: set ZHIPU_KEY=你的API_KEY")
        sys.exit(1)

    client = OpenAI(api_key=ZHIPU_KEY, base_url=BASE_URL)

    # 先测试文本连通
    print(f"\n-- 文本连通性 --")
    try:
        r = client.chat.completions.create(
            model=model, max_tokens=50, temperature=0.0,
            messages=[{"role": "user", "content": "回复OK"}],
        )
        print(f"  ✅ 文本OK: {r.choices[0].message.content[:50]}")
    except Exception as e:
        print(f"  ❌ 文本失败: {e}")
        sys.exit(1)

    # 逐步测试图片数量
    print(f"\n-- 图片数量测试（1~{args.max}张）--")
    limit = None
    for n in range(1, args.max + 1):
        ok, msg = test_with_n_images(model, n, client)
        print(f"  {msg}")
        if not ok and limit is None:
            limit = n - 1  # 上一次成功的就是上限

    print(f"\n{'=' * 60}")
    if limit is not None:
        print(f"  📊 {model} 图片上限: {limit} 张")
    elif limit is None:
        print(f"  📊 {model} 图片上限: ≥{args.max} 张（测试范围内全部成功）")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
