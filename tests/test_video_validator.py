"""
video_validator.py 测试 —— MP4 视频验证
覆盖：格式验证、时长提取、分辨率提取、编码格式、错误处理
"""
import os
import struct
import pytest
from src.video_validator import validate, quick_check


# ============================================================
#  构建测试用 MP4 数据的工厂函数
# ============================================================

def _make_ftyp_box(major_brand=b"isom"):
    """构造 ftyp box"""
    body = major_brand + b"\x00\x00\x00\x00" + b"isom\x00\x00\x00\x00"
    size = 8 + len(body)
    return struct.pack(">I", size) + b"ftyp" + body


def _make_moov_box(timescale=1000, duration=5000, has_video=True,
                   width=1920, height=1080, codec=b"avc1"):
    """构造 moov box（含 mvhd + trak）"""
    mvhd = _make_mvhd(timescale, duration)
    traks = b""
    if has_video:
        traks += _make_trak(b"vide", width, height, codec)
    moov_body = mvhd + traks
    size = 8 + len(moov_body)
    return struct.pack(">I", size) + b"moov" + moov_body


def _make_mvhd(timescale=1000, duration=5000):
    """构造 mvhd box (version 0)"""
    body = (
        b"\x00"                          # version
        + b"\x00\x00\x00"                # flags
        + b"\x00\x00\x00\x00"            # creation_time
        + b"\x00\x00\x00\x00"            # modification_time
        + struct.pack(">I", timescale)   # timescale
        + struct.pack(">I", duration)    # duration
        + b"\x00\x01\x00\x00"            # rate
        + b"\x01\x00\x00\x00"            # volume
        + b"\x00" * 76                   # matrix + 预留
    )
    size = 8 + len(body)
    return struct.pack(">I", size) + b"mvhd" + body


def _make_trak(handler_type=b"vide", width=1920, height=1080, codec=b"avc1"):
    """构造 trak box"""
    # tkhd
    tkhd_body = (
        b"\x00"                          # version
        + b"\x00\x00\x07"                # flags
        + b"\x00\x00\x00\x00"            # creation_time
        + b"\x00\x00\x00\x00"            # modification_time
        + b"\x00\x00\x00\x01"            # track_id
        + b"\x00\x00\x00\x00"            # reserved
        + b"\x00\x00\x00\x00"            # duration (in mvhd timescale)
        + b"\x00" * 8                    # reserved
        + b"\x00\x00\x00\x00"            # layer + alternate_group
        + b"\x00\x00\x00\x00"            # volume + reserved
        + b"\x00\x01\x00\x00" * 9        # matrix
        + struct.pack(">I", width << 16)  # width (16.16 fixed-point)
        + struct.pack(">I", height << 16) # height (16.16 fixed-point)
    )
    tkhd_size = 8 + len(tkhd_body)
    tkhd = struct.pack(">I", tkhd_size) + b"tkhd" + tkhd_body

    # hdlr
    hdlr_body = (
        b"\x00"                          # version
        + b"\x00\x00\x00"                # flags
        + b"\x00\x00\x00\x00"            # pre_defined
        + handler_type                   # handler_type (vide/soun)
        + b"\x00\x00\x00\x00"            # reserved
        + b"\x00\x00\x00\x00"            # reserved
        + b"\x00\x00\x00\x00"            # reserved
        + b"VideoHandler\x00"            # name
    )
    hdlr_size = 8 + len(hdlr_body)
    hdlr = struct.pack(">I", hdlr_size) + b"hdlr" + hdlr_body

    # stsd (含编码格式)
    entry_body = (
        b"\x00\x00\x00\x01"              # entry_count
        + struct.pack(">I", 16 + len(codec) + 12)  # entry_size (简化)
        + codec.ljust(4, b"\x00")        # codec (4-byte)
        + b"\x00" * 6                    # reserved
        + b"\x00\x01"                    # data_reference_index
        + b"\x00" * 8                    # 简化其余
    )
    stsd_body = b"\x00" + b"\x00\x00\x00" + entry_body
    stsd_size = 8 + len(stsd_body)
    stsd = struct.pack(">I", stsd_size) + b"stsd" + stsd_body

    trak_body = tkhd + hdlr + stsd
    trak_size = 8 + len(trak_body)
    return struct.pack(">I", trak_size) + b"trak" + trak_body


def _write_mp4(path, boxes):
    """将多个 box 写入文件，自动填充至 >1KB 通过大小检查"""
    with open(path, 'wb') as f:
        for box in boxes:
            f.write(box)
        # 填充至 >1024 字节
        total = sum(len(b) for b in boxes)
        if total < 1100:
            f.write(b'\x00' * (1100 - total))


# ============================================================
#  测试类
# ============================================================

class TestValidate:
    """validate() 主函数"""

    def test_valid_video(self, tmp_dir):
        """有效 MP4 视频"""
        path = os.path.join(tmp_dir, "valid.mp4")
        _write_mp4(path, [
            _make_ftyp_box(),
            _make_moov_box(timescale=1000, duration=5000, has_video=True),
        ])
        result = validate(path)
        assert result["is_valid"] is True
        assert result["has_video_track"] is True
        assert result["duration_seconds"] == pytest.approx(5.0, 0.1)
        assert result["width"] == 1920
        assert result["height"] == 1080
        assert result["codec"] == "avc1"

    def test_no_video_track_warns(self, tmp_dir):
        """无视频轨道 → 标记"""
        path = os.path.join(tmp_dir, "audio_only.mp4")
        _write_mp4(path, [
            _make_ftyp_box(),
            _make_moov_box(has_video=False),
        ])
        result = validate(path)
        assert "无视频轨道" in str(result.get("error", ""))

    def test_file_not_exists(self):
        """文件不存在"""
        result = validate("/nonexistent/path.mp4")
        assert result["is_valid"] is False
        assert "不存在" in result["error"]

    def test_file_too_small(self, tmp_dir):
        """文件太小"""
        path = os.path.join(tmp_dir, "tiny.mp4")
        with open(path, 'wb') as f:
            f.write(b'\x00' * 512)
        result = validate(path)
        assert result["is_valid"] is False
        assert "太小" in result.get("error", "") or "小" in result.get("error", "")

    def test_not_mp4(self, tmp_dir):
        """非 MP4 文件"""
        path = os.path.join(tmp_dir, "text.txt")
        with open(path, 'w') as f:
            f.write("这不是视频文件")
        result = validate(path)
        assert result["is_valid"] is False

    def test_missing_moov(self, tmp_dir):
        """缺少 moov box"""
        path = os.path.join(tmp_dir, "no_moov.mp4")
        _write_mp4(path, [_make_ftyp_box()])
        result = validate(path)
        assert result["is_valid"] is False
        assert "moov" in str(result.get("error", "")).lower()

    def test_different_resolution(self, tmp_dir):
        """不同分辨率"""
        path = os.path.join(tmp_dir, "720p.mp4")
        _write_mp4(path, [
            _make_ftyp_box(),
            _make_moov_box(width=1280, height=720),
        ])
        result = validate(path)
        assert result["width"] == 1280
        assert result["height"] == 720

    def test_different_codec(self, tmp_dir):
        """不同编码格式"""
        path = os.path.join(tmp_dir, "h265.mp4")
        _write_mp4(path, [
            _make_ftyp_box(),
            _make_moov_box(codec=b"hvc1"),
        ])
        result = validate(path)
        assert result["codec"] == "hvc1"

    def test_short_duration(self, tmp_dir):
        """短视频"""
        path = os.path.join(tmp_dir, "short.mp4")
        _write_mp4(path, [
            _make_ftyp_box(),
            _make_moov_box(timescale=1000, duration=2000),
        ])
        result = validate(path)
        assert result["duration_seconds"] == pytest.approx(2.0, 0.1)

    def test_audio_track_detected(self, tmp_dir):
        """检测音频轨道"""
        path = os.path.join(tmp_dir, "video_audio.mp4")
        moov_with_audio = (
            _make_mvhd(1000, 5000) +
            _make_trak(b"vide", 1920, 1080, b"avc1") +
            _make_trak(b"soun", 0, 0, b"mp4a")
        )
        moov_size = 8 + len(moov_with_audio)
        moov = struct.pack(">I", moov_size) + b"moov" + moov_with_audio
        _write_mp4(path, [_make_ftyp_box(), moov])

        result = validate(path)
        assert result["has_audio_track"] is True


class TestQuickCheck:
    """quick_check 快速检查"""

    def test_valid_returns_true_and_message(self, tmp_dir):
        path = os.path.join(tmp_dir, "valid.mp4")
        _write_mp4(path, [_make_ftyp_box(), _make_moov_box()])
        ok, msg = quick_check(path)
        assert ok is True
        assert len(msg) > 0

    def test_invalid_returns_false_and_error(self, tmp_dir):
        path = os.path.join(tmp_dir, "bad.mp4")
        with open(path, 'wb') as f:
            f.write(b'not a video\x00' * 100)
        ok, msg = quick_check(path)
        assert ok is False
        assert len(msg) > 0

    def test_nonexistent_file(self):
        ok, msg = quick_check("/nonexistent/path.mp4")
        assert ok is False
