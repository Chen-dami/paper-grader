"""
抄袭检测模块 — 五维交叉验证。
- 元数据: Application ID / TotalTime / revision / creator / 时间线
- 文本: 各题提示词余弦相似度
- 图片: MD5 哈希
- Excel: 数据指纹
- 综合: 加权评分 + 可疑对列表
"""
import os, json, hashlib, re
from datetime import datetime
from collections import defaultdict
from difflib import SequenceMatcher
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


def check_all(papers_dir: str, grading_results: list, output_path: str = "output/查重报告.xlsx"):
    """主入口：对试卷目录下所有 docx 做全面查重"""
    docx_files = _find_docx(papers_dir)
    if len(docx_files) < 2:
        print("  查重需要至少2份试卷")
        return

    print(f"\n  查重：{len(docx_files)} 份试卷...")

    # 1. 提取元数据
    meta_list = [_extract_meta(f) for f in docx_files]

    # 2. 提取所有文本（提示词）
    text_map = _extract_texts(docx_files)

    # 3. 提取图片哈希
    img_map = _extract_image_hashes(docx_files)

    # 4. 提取 Excel 指纹
    excel_map = _extract_excel_fingerprints(docx_files)

    # 5. 两两比对
    pairs = []
    n = len(docx_files)
    for i in range(n):
        for j in range(i + 1, n):
            score, reasons = _compare_pair(
                meta_list[i], meta_list[j],
                text_map.get(docx_files[i], {}), text_map.get(docx_files[j], {}),
                img_map.get(docx_files[i], []), img_map.get(docx_files[j], []),
                excel_map.get(docx_files[i], ""), excel_map.get(docx_files[j], ""),
            )
            if score > 0:
                pairs.append({
                    "file_a": os.path.basename(docx_files[i]),
                    "file_b": os.path.basename(docx_files[j]),
                    "student_a": meta_list[i].get("creator", "?"),
                    "student_b": meta_list[j].get("creator", "?"),
                    "score": score,
                    "reasons": reasons,
                })

    pairs.sort(key=lambda x: x["score"], reverse=True)

    # 6. 生成报告
    _generate_report(pairs, meta_list, output_path)
    return pairs


# ============================================================
#  元数据提取
# ============================================================

def _find_docx(directory: str) -> list:
    """递归找所有 docx"""
    files = []
    for root, _, names in os.walk(directory):
        for n in names:
            if n.endswith('.docx') and not n.startswith('~$'):
                files.append(os.path.join(root, n))
    return sorted(files)


def _extract_meta(docx_path: str) -> dict:
    """提取 docx 内部元数据"""
    meta = {"file": os.path.basename(docx_path), "path": docx_path,
            "created": "", "modified": "", "creator": "", "lastModifiedBy": "",
            "revision": 0, "total_time": 0, "application": "", "company": ""}

    try:
        with ZipFile(docx_path, 'r') as z:
            if 'docProps/core.xml' in z.namelist():
                root = ET.fromstring(z.read('docProps/core.xml'))
                ns = {'dc': 'http://purl.org/dc/elements/1.1/',
                      'dcterms': 'http://purl.org/dc/terms/',
                      'cp': 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties'}
                meta['created'] = _text(root, './/dcterms:created', ns) or ""
                meta['modified'] = _text(root, './/dcterms:modified', ns) or ""
                meta['creator'] = _text(root, './/dc:creator', ns) or ""
                meta['lastModifiedBy'] = _text(root, './/cp:lastModifiedBy', ns) or ""
                rev = _text(root, './/cp:revision', ns)
                meta['revision'] = int(rev) if rev and rev.isdigit() else 0

            if 'docProps/app.xml' in z.namelist():
                root2 = ET.fromstring(z.read('docProps/app.xml'))
                ns2 = {'': 'http://schemas.openxmlformats.org/officeDocument/2006/extended-properties'}
                tt = _text(root2, './/TotalTime', ns2)
                meta['total_time'] = int(tt) if tt and tt.isdigit() else 0
                meta['application'] = _text(root2, './/Application', ns2) or ""
                meta['company'] = _text(root2, './/Company', ns2) or ""
    except Exception:
        pass

    # 学生信息从文件名推测：255102030101李杰鸿.docx
    fname = os.path.splitext(meta["file"])[0]
    sid_match = re.search(r'(\d{11,12})', fname)
    meta["student_id"] = sid_match.group(1) if sid_match else ""
    name_match = re.search(r'[一-鿿]{2,4}', fname)
    meta["student_name"] = name_match.group(0) if name_match else ""

    return meta


def _text(el, xpath, ns):
    found = el.find(xpath, ns)
    return found.text if found is not None else None


# ============================================================
#  文本提取
# ============================================================

def _extract_texts(docx_files: list) -> dict:
    """从每份 docx 提取各题提示词文本"""
    text_map = {}
    for f in docx_files:
        try:
            from docx import Document
            doc = Document(f)
            texts = {"q_all": ""}
            # 取所有表格中的长文本
            for ti, table in enumerate(doc.tables):
                for row in table.rows:
                    for cell in row.cells:
                        t = cell.text.strip()
                        if len(t) > 30:
                            texts["q_all"] += t + "\n"
                            # 按题号归类
                            qid = _guess_question(ti)
                            texts.setdefault(f"q{qid}", "")
                            texts[f"q{qid}"] += t + "\n"
            text_map[f] = texts
        except Exception:
            text_map[f] = {}
    return text_map


def _guess_question(table_index: int) -> int:
    """根据表格位置猜测题号"""
    mapping = {2: 1, 4: 2, 6: 3, 8: 4, 10: 5}
    return mapping.get(table_index, 0)


# ============================================================
#  图片哈希
# ============================================================

def _extract_image_hashes(docx_files: list) -> dict:
    """提取每份 docx 中所有图片的 MD5"""
    img_map = {}
    for f in docx_files:
        hashes = []
        try:
            with ZipFile(f, 'r') as z:
                for name in z.namelist():
                    if 'media' in name and not name.endswith('/'):
                        data = z.read(name)
                        if len(data) > 5000:  # 跳过装饰小图
                            hashes.append(hashlib.md5(data).hexdigest())
        except Exception:
            pass
        img_map[f] = hashes
    return img_map


# ============================================================
#  Excel 指纹
# ============================================================

def _extract_excel_fingerprints(docx_files: list) -> dict:
    """提取嵌入 Excel 的数据指纹"""
    excel_map = {}
    for f in docx_files:
        try:
            with ZipFile(f, 'r') as z:
                for name in z.namelist():
                    if 'embedding' in name.lower() and not name.endswith('/'):
                        data = z.read(name)
                        # 找内嵌的 xlsx
                        idx = data.find(b'PK\x03\x04')
                        if idx > 4 and b'xl/' in data[idx:idx + 5000]:
                            xlsx_data = data[idx:]
                            try:
                                import io
                                df = pd.read_excel(io.BytesIO(xlsx_data))
                                # 指纹：行数 + 列名 + 前5行的值
                                fp = f"{len(df)}r_{len(df.columns)}c_"
                                fp += hashlib.md5(df.head(5).to_csv(index=False).encode()).hexdigest()[:12]
                                excel_map[f] = fp
                            except Exception:
                                pass
        except Exception:
            pass
    return excel_map


# ============================================================
#  两两比对
# ============================================================

def _compare_pair(m1: dict, m2: dict, t1: dict, t2: dict,
                  im1: list, im2: list, e1: str, e2: str) -> tuple:
    """对比一对试卷，返回 (score, reasons)"""
    score = 0
    reasons = []

    # --- 元数据 ---
    # 同一台电脑（Application ID 相同）
    if m1.get("application") and m2.get("application"):
        if m1["application"] == m2["application"]:
            score += 30
            reasons.append(f"同电脑: WPS ID一致({m1['application'][-20:]})")

    # TotalTime 悬殊
    t1_val = m1.get("total_time", 0)
    t2_val = m2.get("total_time", 0)
    if max(t1_val, t2_val) > 30 and min(t1_val, t2_val) < 5:
        name_low = os.path.splitext(m1["file"])[0] if t1_val < 5 else os.path.splitext(m2["file"])[0]
        score += 15
        reasons.append(f"编辑时长悬殊: {t1_val}min vs {t2_val}min → {name_low}疑似没做")

    # revision 太低
    if m1.get("revision", 99) <= 5 and t1_val < 10:
        score += 10
        reasons.append(f"{os.path.splitext(m1['file'])[0]} revision={m1['revision']} 疑似只改了名字")
    if m2.get("revision", 99) <= 5 and t2_val < 10:
        score += 10
        reasons.append(f"{os.path.splitext(m2['file'])[0]} revision={m2['revision']} 疑似只改了名字")

    # 时间线：B在A之后短时间内保存
    if m1.get("modified") and m2.get("modified"):
        try:
            t_a = datetime.fromisoformat(m1["modified"].replace('Z', '+00:00'))
            t_b = datetime.fromisoformat(m2["modified"].replace('Z', '+00:00'))
            diff_min = abs((t_b - t_a).total_seconds()) / 60
            if diff_min < 10:
                score += 10
                reasons.append(f"保存时间接近: 相差{diff_min:.0f}分钟")
        except Exception:
            pass

    # --- 文本相似度 ---
    if t1 and t2:
        all1 = t1.get("q_all", "")
        all2 = t2.get("q_all", "")
        if all1 and all2 and len(all1) > 100 and len(all2) > 100:
            sim = SequenceMatcher(None, all1, all2).ratio()
            if sim > 0.85:
                score += int(sim * 30)
                reasons.append(f"全文相似度 {sim:.0%}")
            elif sim > 0.7:
                score += int(sim * 15)
                reasons.append(f"全文相似度偏高 {sim:.0%}")

        # 逐题比对
        for qk in ["q1", "q2", "q3", "q5"]:
            if qk in t1 and qk in t2 and len(t1[qk]) > 50 and t1[qk] == t2[qk]:
                score += 25
                reasons.append(f"{qk}提示词完全相同")

    # --- 图片 MD5 ---
    shared_imgs = set(im1) & set(im2)
    if shared_imgs:
        score += 30 * len(shared_imgs)
        reasons.append(f"图片MD5相同: {len(shared_imgs)}张")

    # --- Excel 指纹 ---
    if e1 and e2 and e1 == e2:
        score += 20
        reasons.append("Excel数据指纹一致")

    return score, reasons


# ============================================================
#  报告生成
# ============================================================

def _generate_report(pairs: list, meta_list: list, output_path: str):
    """生成查重 Excel 报告"""
    wb = Workbook()

    # Sheet 1: 可疑对
    ws = wb.active
    ws.title = "可疑对"

    headers = ["可疑度", "学生A", "学生B", "分数A", "分数B",
               "Application同?", "编辑时长(min)", "revision",
               "文本相似", "图片重复", "Excel同?", "详细原因"]
    hfont = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
    hfill = PatternFill(start_color="C00000", end_color="C00000", fill_type="solid")
    border = Border(left=Side(style="thin"), right=Side(style="thin"),
                    top=Side(style="thin"), bottom=Side(style="thin"))
    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    yellow_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")

    for col, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = hfont; c.fill = hfill; c.border = border

    for i, p in enumerate(pairs):
        row = i + 2
        score = p["score"]
        # 颜色
        fill = red_fill if score >= 50 else yellow_fill if score >= 25 else None

        m1 = _find_meta(meta_list, p["file_a"])
        m2 = _find_meta(meta_list, p["file_b"])

        values = [
            score,
            _student_label(m1), _student_label(m2),
            m1.get("total_score", "") if m1 else "", m2.get("total_score", "") if m2 else "",
            "是" if (m1 and m2 and m1.get("application") == m2.get("application")) else "",
            f"{m1.get('total_time', 0)}/{m2.get('total_time', 0)}" if m1 and m2 else "",
            f"{m1.get('revision', 0)}/{m2.get('revision', 0)}" if m1 and m2 else "",
            _extract_reason(p["reasons"], "相似"),
            _extract_reason(p["reasons"], "图片"),
            "是" if "Excel数据指纹一致" in str(p["reasons"]) else "",
            "; ".join(p["reasons"]),
        ]
        for col, v in enumerate(values, 1):
            c = ws.cell(row=row, column=col, value=v)
            c.border = border
            if fill:
                c.fill = fill

    for col in range(1, len(headers) + 1):
        ws.column_dimensions[chr(64 + min(col, 26))].width = 15
    ws.column_dimensions['L'].width = 60

    # Sheet 2: 元数据总览
    ws2 = wb.create_sheet("元数据")
    mheaders = ["文件名", "学号", "Application ID(尾20)", "创建时间", "修改时间",
                "作者", "最后编辑者", "编辑时长(min)", "revision", "总分"]
    for col, h in enumerate(mheaders, 1):
        c = ws2.cell(row=1, column=col, value=h)
        c.font = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        c.border = border

    for i, m in enumerate(meta_list):
        row = i + 2
        vals = [
            m.get("file", ""), m.get("student_id", ""),
            m.get("application", "")[-20:], m.get("created", ""), m.get("modified", ""),
            m.get("creator", ""), m.get("lastModifiedBy", ""),
            m.get("total_time", 0), m.get("revision", 0),
            m.get("total_score", ""),
        ]
        for col, v in enumerate(vals, 1):
            c = ws2.cell(row=row, column=col, value=v)
            c.border = border
            # 低编辑时长标红
            if col == 8 and isinstance(v, (int, float)) and v < 10:
                c.fill = red_fill
            if col == 9 and isinstance(v, (int, float)) and v <= 5:
                c.fill = red_fill

    for col in range(1, len(mheaders) + 1):
        ws2.column_dimensions[chr(64 + min(col, 26))].width = 20

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    wb.save(output_path)
    print(f"  查重报告: {output_path}")


def _find_meta(meta_list: list, filename: str) -> dict | None:
    for m in meta_list:
        if m.get("file") == filename:
            return m
    return None


def _student_label(meta: dict | None) -> str:
    if not meta:
        return "?"
    sid = meta.get("student_id", "")
    name = meta.get("student_name", "")
    return f"{sid}{name}" if sid or name else meta.get("file", "?")


def _extract_reason(reasons: list, keyword: str) -> str:
    for r in reasons:
        if keyword in r:
            return r[:40]
    return ""


# ============================================================
#  main.py 调用入口
# ============================================================

def run(papers_dir: str = "data/papers", output_dir: str = "output") -> list:
    """供 main.py 调用的入口。查重报告存入 output_dir 下。"""
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, "查重报告.xlsx")
    return check_all(papers_dir, [], report_path)
