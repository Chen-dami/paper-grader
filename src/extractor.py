"""
Word 文档解析器 —— 把 .docx 拆成结构化数据。
输出：文字段落、表格内容、图片路径、嵌入文件路径。
"""
import os
import json
import zipfile
import shutil
from docx import Document


def extract(docx_path: str, output_dir: str = "output") -> dict:
    """
    解析一份 docx 试卷，返回结构化字典。

    返回结构：
    {
        "file_name": "xxx.docx",
        "student_info": {"学号": "", "姓名": "", "班级": ""},
        "paragraphs": [(index, text), ...],
        "tables": [[{cell_text}, ...], ...],   # 每个表格是一行行数据
        "images": [(local_path, width, height, size_bytes), ...],
        "embedded_files": [(local_path, ext), ...],
    }
    """
    file_name = os.path.basename(docx_path)
    paper_dir = os.path.join(output_dir, os.path.splitext(file_name)[0])
    img_dir = os.path.join(paper_dir, "images")
    embed_dir = os.path.join(paper_dir, "embeddings")
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(embed_dir, exist_ok=True)

    doc = Document(docx_path)

    # ---- 1. 提取文字段落 ----
    paragraphs = []
    for i, p in enumerate(doc.paragraphs):
        text = p.text.strip()
        paragraphs.append((i, text))

    # ---- 2. 提取表格 ----
    tables = []
    for table in doc.tables:
        rows = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows.append(cells)
        tables.append(rows)

    # ---- 3. 提取图片 ----
    images = []
    with zipfile.ZipFile(docx_path, 'r') as z:
        for name in z.namelist():
            if 'media' in name and not name.endswith('/'):
                data = z.read(name)
                fname = os.path.basename(name)
                local_path = os.path.join(img_dir, fname)

                # 跳过重复提取
                if not os.path.exists(local_path):
                    with open(local_path, 'wb') as f:
                        f.write(data)

                # 读取图片尺寸
                width, height = _get_image_size(data, fname)
                images.append((local_path, width, height, len(data)))

    # ---- 4. 提取嵌入文件（OLE 对象） ----
    embedded_files = []
    with zipfile.ZipFile(docx_path, 'r') as z:
        for name in z.namelist():
            if 'embedding' in name.lower() and not name.endswith('/'):
                data = z.read(name)
                fname = os.path.basename(name)
                local_path = os.path.join(embed_dir, fname)

                if not os.path.exists(local_path):
                    with open(local_path, 'wb') as f:
                        f.write(data)

                # 尝试提取嵌套的 Office 文件
                nested = _extract_ole(data, embed_dir, fname)
                if nested:
                    embedded_files.append((nested, os.path.splitext(nested)[1]))

    # ---- 5. 解析学生信息 ----
    student_info = _parse_student_info(paragraphs, tables)

    return {
        "file_name": file_name,
        "paper_dir": paper_dir,
        "student_info": student_info,
        "paragraphs": paragraphs,
        "tables": tables,
        "images": images,
        "embedded_files": embedded_files,
    }


def _get_image_size(data: bytes, fname: str) -> tuple:
    """从 PNG/JPEG 二进制数据中读取宽高"""
    import struct
    try:
        if fname.lower().endswith('.png'):
            w = struct.unpack('>I', data[16:20])[0]
            h = struct.unpack('>I', data[20:24])[0]
            return w, h
        elif fname.lower().endswith(('.jpg', '.jpeg')):
            # JPEG 尺寸解析较复杂，简化处理
            return 0, 0
        else:
            return 0, 0
    except Exception:
        return 0, 0


def _extract_ole(data: bytes, output_dir: str, base_name: str) -> str | None:
    """
    从 OLE 对象中提取嵌套文件（Office 文档或视频）。
    优先从 Ole10Native 流提取原始数据，再检测类型。
    """
    # 1. 先尝试提取 Ole10Native 原始文件数据（真正的嵌入文件在这里）
    native = _try_extract_ole_native(data)

    # 2. 如果取到了 native，检测类型
    if native and len(native) > 100:
        # 视频检测（ftyp 可能在 OLE 包装头之后，搜索前 500 字节）
        head500 = native[:500]
        if b'ftyp' in head500:
            ext = '.mp4'
        elif head500[:4] == b'RIFF':
            ext = '.avi'
        else:
            # 尝试从原始 OLE 数据中找 ZIP（Office 文件）
            ext = _detect_ole_ext(data)

        out_path = os.path.join(output_dir, base_name.replace('.bin', ext))
        if not os.path.exists(out_path):
            with open(out_path, 'wb') as f:
                f.write(native)
        return out_path

    # 3. 没有 Ole10Native，从原始数据扫描
    for sig, ext in [(b'ftyp', '.mp4'), (b'RIFF', '.avi'), (b'moov', '.mov')]:
        idx = data.find(sig, 4, 512)
        if idx > 0:
            out_path = os.path.join(output_dir, base_name.replace('.bin', ext))
            if not os.path.exists(out_path):
                with open(out_path, 'wb') as f:
                    f.write(data)
            return out_path

    # 4. ZIP 头 → Office 文件
    idx = data.find(b'PK\x03\x04')
    if idx >= 4:
        zip_data = data[idx:]
        if zip_data[:4] == b'PK\x03\x04':
            ext = _detect_office_ext(zip_data)
            out_path = os.path.join(output_dir, base_name.replace('.bin', ext))
            if not os.path.exists(out_path):
                with open(out_path, 'wb') as f:
                    f.write(zip_data)
            return out_path

    return None


def _detect_ole_ext(data: bytes) -> str:
    """从 OLE 原始数据中检测嵌入文件类型"""
    for sig, ext in [(b'ftyp', '.mp4'), (b'RIFF', '.avi'), (b'moov', '.mov')]:
        if sig in data[4:512]:
            return ext
    # 检查 ZIP
    idx = data.find(b'PK\x03\x04')
    if idx >= 4:
        return _detect_office_ext(data[idx:])
    return '.bin'


def _detect_office_ext(zip_data: bytes) -> str:
    """从 ZIP 内容判断是哪种 Office 文件"""
    head = zip_data[:5000]
    if b'xl/' in head:
        return '.xlsx'
    elif b'word/' in head:
        return '.docx'
    elif b'ppt/' in head:
        return '.pptx'
    return '.zip'


def _try_extract_ole_native(data: bytes) -> bytes | None:
    """
    从 OLE2 复合文档的 Ole10Native 流中提取原始嵌入文件。
    使用 olefile 库解析 OLE2 结构。
    """
    if data[:8] != b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        return None
    try:
        import olefile
        ole = olefile.OleFileIO(data)
        # 查找 Ole10Native 流
        for s in ole.listdir():
            if 'Ole10Native' in '/'.join(s):
                raw = ole.openstream(s).read()
                ole.close()
                # Ole10Native 结构：4字节大小 + 嵌入文件数据
                if len(raw) > 8:
                    import struct
                    size = struct.unpack_from('<I', raw, 0)[0]
                    if 100 < size < len(raw):
                        return raw[4:4 + size]
                    # 有时候原生数据直接从 offset 4 开始
                    return raw[4:]
                return raw
        ole.close()
    except Exception:
        pass
    return None


def extract_from_student_folder(docx_path: str, output_dir: str = "output",
                                supplementary_files: dict | None = None) -> dict:
    """
    从学生文件夹提取试卷 —— 正常解析 docx，同时将文件夹中的
    辅助文件（图片、Excel）注入到提取结果中。

    supplementary_files = {
        "images": ["/path/to/img1.png", ...],
        "excel": ["/path/to/data.xlsx", ...],
    }
    """
    paper = extract(docx_path, output_dir)
    paper_dir = paper["paper_dir"]

    if supplementary_files:
        img_dir = os.path.join(paper_dir, "images")
        embed_dir = os.path.join(paper_dir, "embeddings")
        os.makedirs(img_dir, exist_ok=True)
        os.makedirs(embed_dir, exist_ok=True)

        # 注入文件夹中的独立图片
        for img_path in supplementary_files.get("images", []):
            if not os.path.exists(img_path):
                continue
            fname = os.path.basename(img_path)
            dest = os.path.join(img_dir, fname)
            if not os.path.exists(dest):
                shutil.copy2(img_path, dest)
            size = os.path.getsize(dest)
            w, h = _get_image_size(open(dest, "rb").read(), fname)
            paper["images"].append((dest, w, h, size))

        # 注入文件夹中的独立 Excel
        for xlsx_path in supplementary_files.get("excel", []):
            if not os.path.exists(xlsx_path):
                continue
            fname = os.path.basename(xlsx_path)
            dest = os.path.join(embed_dir, fname)
            if not os.path.exists(dest):
                shutil.copy2(xlsx_path, dest)
            paper["embedded_files"].append((dest, os.path.splitext(fname)[1]))

    return paper


def _parse_student_info(paragraphs: list, tables: list) -> dict:
    """从段落和表格中提取学生信息"""
    info = {"学号": "", "姓名": "", "班级": ""}

    # 从段落中查找
    for i, text in paragraphs:
        if '班级' in text and '姓名' in text and '学号' in text:
            # 尝试解析 "班级  数媒2501  姓名  李杰鸿  学号 255102030101"
            import re
            for field in ['班级', '姓名', '学号']:
                pattern = rf'{field}\s*(\S+)'
                m = re.search(pattern, text)
                if m:
                    info[field] = m.group(1).strip()
            break

    # 从表格中查找
    if not info.get("学号"):
        for table in tables:
            for row in table:
                row_text = ' '.join(row)
                if '学号' in row_text or '姓名' in row_text:
                    # 尝试解析
                    for i, cell in enumerate(row):
                        if '学号' in cell and i + 1 < len(row):
                            info['学号'] = row[i + 1].strip()
                        if '姓名' in cell and i + 1 < len(row):
                            info['姓名'] = row[i + 1].strip()
                        if '班级' in cell and i + 1 < len(row):
                            info['班级'] = row[i + 1].strip()
    return info
