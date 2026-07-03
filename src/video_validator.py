"""
文件级 MP4 视频验证器 —— 纯 Python 实现，不依赖 ffmpeg。

解析 ISO Base Media File Format (MP4) 容器结构：
- ftyp: 文件类型验证
- moov/mvhd: 时长和时间刻度
- trak/tkhd: 轨道类型和分辨率
- stsd: 编码格式（avc1/hvc1/mp4v 等）

返回:
{
    "is_valid": bool,
    "duration_seconds": float | None,
    "width": int | None,
    "height": int | None,
    "has_video_track": bool,
    "has_audio_track": bool,
    "codec": str | None,
    "error": str | None,
}
"""
import struct
import os


def validate(video_path: str) -> dict:
    """
    验证 MP4 文件的完整性和视频轨道的存在性。

    返回结构化字典，即使文件无效也不会抛出异常。
    """
    result = {
        "is_valid": False,
        "duration_seconds": None,
        "width": None,
        "height": None,
        "has_video_track": False,
        "has_audio_track": False,
        "codec": None,
        "error": None,
    }

    if not video_path or not os.path.exists(video_path):
        result["error"] = "文件不存在"
        return result

    file_size = os.path.getsize(video_path)
    if file_size < 1024:  # 小于 1KB 不可能是有效视频
        result["error"] = f"文件过小 ({file_size} bytes)"
        return result

    try:
        with open(video_path, "rb") as f:
            data = f.read()
    except (PermissionError, OSError) as e:
        result["error"] = f"无法读取: {e}"
        return result

    if len(data) < 1024:
        result["error"] = "文件太小，无有效 MP4 头"
        return result

    # 1. 查找 ftyp box（可能在包装头之后，搜索前 2KB）
    ftyp_offset = data.find(b"ftyp", 0, 2048)
    if ftyp_offset < 3:  # 需要前面有 4 字节的 size 字段
        result["error"] = "不是有效的 MP4 文件（找不到 ftyp box）"
        return result

    # ftyp box 结构: [4字节size][4字节'ftyp'][major_brand][minor_version][compatible_brands...]
    ftyp_size = struct.unpack_from(">I", data, ftyp_offset - 4)[0]
    if ftyp_size < 12 or ftyp_offset - 4 + ftyp_size > len(data):
        result["error"] = f"ftyp box 大小异常 ({ftyp_size})"
        return result

    # 验证 ftyp 后面的字节是合理的 major brand（4个可打印字符）
    major_brand = data[ftyp_offset + 4:ftyp_offset + 8]
    if not major_brand.isalnum():
        result["error"] = f"ftyp 后不是有效的 major brand ({major_brand!r})"
        return result

    result["is_valid"] = True

    # 2. 查找 moov box
    moov_offset = data.find(b"moov", ftyp_offset)
    if moov_offset < 0:
        result["error"] = "缺少 moov box（视频可能未完整保存）"
        result["is_valid"] = False
        return result

    moov_size = struct.unpack_from(">I", data, moov_offset - 4)[0]
    moov_data = data[moov_offset - 4:moov_offset - 4 + moov_size]

    # 3. 解析 mvhd（时长）
    mvhd_offset = moov_data.find(b"mvhd")
    if mvhd_offset >= 0 and mvhd_offset + 24 <= len(moov_data):
        version = moov_data[mvhd_offset + 4]  # 4 bytes after 'mvhd'
        if version == 0 and mvhd_offset + 24 <= len(moov_data):
            timescale = struct.unpack_from(">I", moov_data, mvhd_offset + 16)[0]
            duration = struct.unpack_from(">I", moov_data, mvhd_offset + 20)[0]
        elif version == 1 and mvhd_offset + 32 <= len(moov_data):
            timescale = struct.unpack_from(">I", moov_data, mvhd_offset + 24)[0]
            duration = struct.unpack_from(">Q", moov_data, mvhd_offset + 28)[0]
        else:
            timescale, duration = 0, 0

        if timescale > 0:
            result["duration_seconds"] = round(duration / timescale, 1)

    # 4. 遍历 trak box 检查视频/音频轨道
    _parse_tracks(moov_data, result)

    # 5. 没有视频轨道 → 标记无效
    if result["is_valid"] and not result["has_video_track"]:
        result["error"] = "文件中无视频轨道"

    return result


def _parse_tracks(moov_data: bytes, result: dict):
    """遍历 moov 中所有 trak box，提取轨道信息。

    moov box 结构: [4B size][4B 'moov'][children...]
    跳过 moov header (前 8 字节) 后遍历子 box。
    """
    # 直接搜索所有 trak box（避免 box 层级嵌套问题）
    search_start = 8  # 跳过 moov header
    while search_start < len(moov_data) - 12:
        trak_pos = moov_data.find(b"trak", search_start)
        if trak_pos < 0:
            break
        # trak box 的 size 在前 4 字节
        if trak_pos >= 4:
            trak_size = struct.unpack_from(">I", moov_data, trak_pos - 4)[0]
            if 12 <= trak_size <= len(moov_data) - (trak_pos - 4):
                _parse_trak(moov_data[trak_pos - 4:trak_pos - 4 + trak_size], result)
        search_start = trak_pos + 4


def _parse_trak(trak_data: bytes, result: dict):
    """解析单个 trak box"""
    # 查找 hdlr（处理器类型）—— 先判断轨道类型
    hdlr_offset = trak_data.find(b"hdlr")
    if hdlr_offset < 0:
        return

    # handler_type 在 hdlr box 内偏移 12 字节处
    # hdlr box: [4B size][4B 'hdlr'][1B ver][3B flags][4B pre][4B type]
    if hdlr_offset + 16 > len(trak_data):
        return
    handler_type = trak_data[hdlr_offset + 12:hdlr_offset + 16]

    if handler_type == b"vide":
        result["has_video_track"] = True
    elif handler_type == b"soun":
        result["has_audio_track"] = True
        return  # 音频轨道不需要提取分辨率

    # 提取分辨率（仅视频轨道）
    tkhd_offset = trak_data.find(b"tkhd")
    if tkhd_offset >= 0:
        version = trak_data[tkhd_offset + 4]  # version after 'tkhd'
        # tkhd v0: width at +80, height at +84 (16.16 fixed-point)
        # tkhd v1: width at +92, height at +96
        if version == 0 and tkhd_offset + 88 <= len(trak_data):
            w = struct.unpack_from(">I", trak_data, tkhd_offset + 80)[0] >> 16
            h = struct.unpack_from(">I", trak_data, tkhd_offset + 84)[0] >> 16
        elif version == 1 and tkhd_offset + 100 <= len(trak_data):
            w = struct.unpack_from(">I", trak_data, tkhd_offset + 92)[0] >> 16
            h = struct.unpack_from(">I", trak_data, tkhd_offset + 96)[0] >> 16
        else:
            w, h = 0, 0
        if w > 0:
            result["width"] = w
        if h > 0:
            result["height"] = h

    # 提取编码格式（stsd box）
    stsd_offset = trak_data.find(b"stsd")
    if stsd_offset >= 0 and stsd_offset + 20 <= len(trak_data):
        # stsd box: [4B size][4B 'stsd'][1B ver][3B flags][4B entry_count]
        # first entry:  [4B entry_size][4B codec][...]
        # codec at stsd_offset + 16 (skip: 4B flags + 4B ver + 4B count + 4B entry_size)
        codec_start = stsd_offset + 16
        codec = trak_data[codec_start:codec_start + 4]
        codec_str = codec.decode("ascii", errors="replace").strip("\x00")
        if codec_str and codec_str[0].isalpha():
            result["codec"] = codec_str


# ============================================================
#  快速检查（用于阅卷流程中的轻量判断）
# ============================================================

def quick_check(video_path: str) -> tuple[bool, str]:
    """
    快速检查视频文件是否有效。
    返回 (is_valid, message)
    """
    info = validate(video_path)
    if info["is_valid"] and info["has_video_track"]:
        msg_parts = []
        if info["duration_seconds"] is not None:
            msg_parts.append(f"{info['duration_seconds']}秒")
        if info["width"] and info["height"]:
            msg_parts.append(f"{info['width']}x{info['height']}")
        if info["codec"]:
            msg_parts.append(info["codec"])
        return True, ", ".join(msg_parts) if msg_parts else "有效"
    return False, info.get("error", "未知错误")
