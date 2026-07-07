"""
直接测试智谱 GLM-4V-Flash API 调用，捕获详细错误
"""
import os, sys, json, base64, io, traceback
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openai import OpenAI
from src.video_frame_extractor import extract_frames

ZHIPU_KEY = os.environ.get("ZHIPU_KEY", "")
BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
MODEL = "glm-4v-flash"

print("=" * 60)
print("  智谱 GLM-4V-Flash 直接测试")
print("=" * 60)
print(f"  API Key: {'已设置 (' + ZHIPU_KEY[:8] + '...)' if ZHIPU_KEY else '❌ 未设置!'}")
print(f"  Base URL: {BASE_URL}")
print(f"  Model: {MODEL}")

client = OpenAI(api_key=ZHIPU_KEY, base_url=BASE_URL)

# ============================================================
# Test 1: 纯文本调用
# ============================================================
print(f"\n--- Test 1: 纯文本调用 ---")
try:
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=100,
        temperature=0.0,
        messages=[{"role": "user", "content": "请回复'连通性测试通过'"}],
    )
    print(f"  ✅ 成功！")
    print(f"  回复: {response.choices[0].message.content[:100]}")
    print(f"  tokens: {response.usage.prompt_tokens if response.usage else '?'}")
except Exception as e:
    print(f"  ❌ 失败: {e}")
    traceback.print_exc()

# ============================================================
# Test 2: 视觉调用（用视频帧）
# ============================================================
print(f"\n--- Test 2: 视觉调用（视频帧） ---")
video_path = r"output\diagnose_q3\216102050204崔宗岳\embeddings\oleObject1.mp4"
print(f"  视频路径: {video_path}")
print(f"  视频存在: {os.path.exists(video_path)}")

frames = extract_frames(video_path, num_frames=2)
print(f"  提取帧: {len(frames)} 张")
for f in frames:
    print(f"    {f} ({os.path.getsize(f)/1024:.1f}KB)")

if frames:
    content = [{"type": "text", "text": "请描述这张图片中的内容，包括人物、服饰、背景等。用中文简要回答。"}]
    for fp in frames[:2]:
        with open(fp, "rb") as f:
            img_data = base64.standard_b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(fp)[1].lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
        mime = mime_map.get(ext, "image/jpeg")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{img_data}"}
        })

    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=512,
            temperature=0.3,
            messages=[{"role": "user", "content": content}],
        )
        print(f"  ✅ 视觉调用成功！")
        print(f"  回复: {response.choices[0].message.content[:500]}")
        print(f"  tokens: {response.usage.prompt_tokens if response.usage else '?'}")
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        traceback.print_exc()

# ============================================================
# Test 3: 带 detail 参数（模拟当前代码）
# ============================================================
print(f"\n--- Test 3: 带 detail='low' 参数（模拟当前代码） ---")
if frames:
    content3 = [{"type": "text", "text": "请描述这张图片。用中文简要回答。"}]
    for fp in frames[:2]:
        with open(fp, "rb") as f:
            img_data = base64.standard_b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(fp)[1].lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
        mime = mime_map.get(ext, "image/jpeg")
        content3.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime};base64,{img_data}",
                "detail": "low",  # ← OpenAI 特有参数
            }
        })

    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=512,
            temperature=0.3,
            messages=[{"role": "user", "content": content3}],
        )
        print(f"  ✅ 带 detail 参数调用成功！")
        print(f"  回复: {response.choices[0].message.content[:500]}")
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        traceback.print_exc()

# ============================================================
# Test 4: 4张图（模拟实际评分场景）
# ============================================================
print(f"\n--- Test 4: 4张图 + 评分 prompt（模拟实际评分） ---")
all_frames = extract_frames(video_path, num_frames=4)
print(f"  帧数: {len(all_frames)}")

if all_frames:
    prompt = """你是考试评分专家。根据题目要求和评分标准，对学生的提交内容打分。

题目：视频创作（满分20分）
题目要求：运用生成式人工智能，在豆包等AI平台先创作高清黎锦特写图像，再以此素材制作身着同款黎锦纹样服饰的人物出镜短视频。

评分标准：
  1. 主题契合度与文化准确性（4分）
  2. 图片生成质量（4分）
  3. 人物服饰与背景（4分）
  4. 配音与整体效果（4分）
  5. 提交完整性（4分）

检测到的材料：有文字内容, 有截图, 有视频文件

学生提交内容：
图片提示词：高清微距特写，海南传统黎锦局部，经典大力神图腾纹样...
视频文件：已提交（10.1秒, 720x1280, avc1）

输出 JSON（不要markdown）：
{
  "得分_3-1_主题契合度与文化准确性": <int>,
  "得分_3-2_图片生成质量": <int>,
  "得分_3-3_人物服饰与背景": <int>,
  "得分_3-4_配音与整体效果": <int>,
  "得分_3-5_提交完整性": <int>,
  "总分": <int>,
  "评语": "<30字>"
}"""

    content4 = [{"type": "text", "text": prompt}]
    for fp in all_frames:
        with open(fp, "rb") as f:
            img_data = base64.standard_b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(fp)[1].lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
        mime = mime_map.get(ext, "image/jpeg")
        content4.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{img_data}"}
        })

    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=2048,
            temperature=0.3,
            messages=[{"role": "user", "content": content4}],
        )
        print(f"  ✅ 评分调用成功！")
        print(f"  模型: {response.model}")
        raw = response.choices[0].message.content
        print(f"  原始返回: {raw}")
        print(f"  tokens: {response.usage.prompt_tokens if response.usage else '?'} in / {response.usage.completion_tokens if response.usage else '?'} out")
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        traceback.print_exc()

# ============================================================
# Test 5: 模拟 model_router 的调用方式
# ============================================================
print(f"\n--- Test 5: 模拟 model_router._build_vision_content 的调用 ---")
from src.model_router import _build_vision_content

if all_frames:
    try:
        content5 = _build_vision_content(prompt, all_frames)
        print(f"  Content 数组长度: {len(content5)}")
        for i, item in enumerate(content5):
            if item["type"] == "text":
                print(f"  [{i}] text: {item['text'][:80]}...")
            else:
                url = item.get("image_url", {}).get("url", "")
                print(f"  [{i}] image: {url[:80]}... (detail={item.get('image_url', {}).get('detail', 'not set')})")

        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=2048,
            temperature=0.3,
            messages=[{"role": "user", "content": content5}],
        )
        print(f"  ✅ 模拟 router 调用成功！")
        print(f"  模型: {response.model}")
        raw = response.choices[0].message.content
        print(f"  原始返回: {raw}")
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        traceback.print_exc()

print(f"\n{'=' * 60}")
print(f"  测试完成")
print(f"{'=' * 60}")
