"""从视频中提取代表性帧，供 LLM 视觉评分使用。"""
import os
import tempfile


def extract_frames(video_path: str, num_frames: int = 4, output_dir: str = None) -> list:
    if not video_path or not os.path.exists(video_path):
        return []

    try:
        import cv2
    except ImportError:
        return []

    cap, tmp_path = _open_video(video_path)
    if cap is None:
        return []

    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames < 1:
            return []

        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="vframes_")

        frames = []
        for i in range(num_frames):
            target = int(total_frames * (i + 0.5) / num_frames)
            target = min(target, total_frames - 1)
            cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
            h, w = frame.shape[:2]
            if max(w, h) > 1024:
                scale = 1024 / max(w, h)
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
            out_path = os.path.join(output_dir, f"frame_{i+1:02d}.jpg")
            cv2.imwrite(out_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            frames.append(out_path)

        return frames
    finally:
        cap.release()
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _open_video(video_path: str):
    """打开视频，返回 (VideoCapture, temp_path_or_None)。包装头文件会创建临时文件。"""
    import cv2

    cap = cv2.VideoCapture(video_path)
    if cap.isOpened() and cap.get(cv2.CAP_PROP_FRAME_COUNT) > 0:
        return cap, None
    cap.release()

    # 跳过包装头：从 ftyp 前4字节（size字段）开始截取
    with open(video_path, "rb") as f:
        data = f.read()
    ftyp_idx = data.find(b"ftyp", 0, 4096)
    if ftyp_idx < 4:
        return None, None
    mp4_start = ftyp_idx - 4
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.write(data[mp4_start:])
    tmp.close()
    cap = cv2.VideoCapture(tmp.name)
    if cap.isOpened() and cap.get(cv2.CAP_PROP_FRAME_COUNT) > 0:
        return cap, tmp.name
    cap.release()
    os.unlink(tmp.name)
    return None, None
