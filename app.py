"""
阅卷系统 -- 导航入口
"""
import streamlit as st
import os, sys, glob, time, yaml

sys.path.insert(0, os.path.dirname(__file__))

st.set_page_config(page_title="阅卷系统", page_icon="📝", layout="wide",
                   initial_sidebar_state="expanded")

from src.ui_style import inject; inject()
from src.utils import hpw, load_users, verify_user, save_user, _ensure_users_file

# ============================================================
#  session 初始化
# ============================================================
for k, v in {
    "authenticated": False, "teacher_name": "", "grading_mode": "relaxed",
    "rubric": None, "rubric_path": "data/rubric.json",
    "api_key_input": os.environ.get("DEEPSEEK_KEY", ""),
    "current_class": "", "grading_results": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# 自动登录
if not st.session_state.authenticated:
    tf = "data/.session_token"
    if os.path.exists(tf):
        try:
            with open(tf) as f:
                td = f.read().strip().split("\n")
                if len(td) >= 2 and time.time() - float(td[0]) < 86400:
                    username = td[1]
                    users = load_users()
                    u = users.get(username, {})
                    st.session_state.authenticated = True
                    st.session_state.teacher_name = f"{u.get('display_name', username)}老师"
                    st.session_state.username = username
        except:
            pass

json_files = glob.glob("data/*.json")
if json_files:
    st.session_state.rubric_path = json_files[0]

# ============================================================
#  登录页
# ============================================================
if not st.session_state.authenticated:
    st.title("阅卷系统")
    c = st.columns([1, 2, 1])
    with c[1]:
        st.markdown("---")
        st.subheader("教师登录")
        username = st.text_input("用户名", placeholder="请输入用户名")
        pw = st.text_input("密码", type="password", placeholder="请输入密码")
        if st.button("登 录", type="primary", use_container_width=True):
            if username and pw:
                result = verify_user(username, pw)
                if result:
                    display_name, role = result
                    st.session_state.authenticated = True
                    st.session_state.teacher_name = f"{display_name}老师"
                    st.session_state.username = username
                    os.makedirs("data", exist_ok=True)
                    with open("data/.session_token", "w") as f:
                        f.write(f"{time.time()}\n{username}")
                    st.rerun()
                else:
                    st.error("用户名或密码错误")
            elif not username:
                st.error("请输入用户名")
            else:
                st.error("请输入密码")
        _ensure_users_file()
        st.caption("默认账号: admin / admin123")
    st.stop()

# ============================================================
#  已登录
# ============================================================
teacher = st.session_state.teacher_name

# ===== 侧边栏上方：导航 =====
PAGES = {
    "主页": st.Page("home.py", title="主页", icon="🏠"),
    "阅卷": st.Page("pages/1_grading.py", title="阅卷", icon="📝"),
    "评分配置": st.Page("pages/2_config.py", title="评分配置", icon="⚙️"),
    "历史结果": st.Page("pages/3_results.py", title="历史结果", icon="📊"),
}
pg = st.navigation(list(PAGES.values()), position="sidebar")
pg.run()

# ===== 侧边栏下方：工具区 =====
with st.sidebar:
    st.divider()

    # 评分模式快速切换
    cur_mode = st.session_state.get("grading_mode", "relaxed")
    mode_names = {"relaxed": "宽松", "normal": "标准", "strict": "严格", "custom": "自定义"}

    # 读 config 看有没有自定义预设
    config_path = "config.yaml"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except Exception:
        cfg = {}
    custom_presets = cfg.get("custom_presets") or {}
    all_modes = ["relaxed", "normal", "strict"] + list(custom_presets.keys()) + ["custom"]
    if cur_mode not in all_modes:
        cur_mode = "relaxed"

    mode_labels = {}
    for m in all_modes:
        if m in mode_names:
            mode_labels[m] = mode_names[m]
        elif m in custom_presets:
            mode_labels[m] = f"⭐ {m}"
        else:
            mode_labels[m] = m

    new_mode = st.selectbox(
        "评分模式",
        all_modes,
        index=all_modes.index(cur_mode),
        format_func=lambda x: mode_labels.get(x, x),
        key="sidebar_mode"
    )
    if new_mode != cur_mode:
        st.session_state.grading_mode = new_mode
        cfg.setdefault("grading", {})["mode"] = new_mode
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        st.rerun()

    st.divider()

    if st.button("👤 个人信息", use_container_width=True):
        st.session_state.dialog_type = "profile"
    if st.button("❓ 常见问题", use_container_width=True):
        st.session_state.dialog_type = "faq"
    if st.button("📖 使用说明", use_container_width=True):
        st.session_state.dialog_type = "guide"

    st.divider()

    if st.button("🚪 退出登录", use_container_width=True):
        st.session_state.authenticated = False
        tf = "data/.session_token"
        if os.path.exists(tf): os.remove(tf)
        st.rerun()


# ============================================================
#  Dialog 函数定义（必须在调用之前）
# ============================================================

@st.dialog("个人信息", width="small")
def _open_profile_dialog(teacher_name):
    uname = st.session_state.get("username", "admin")
    users = load_users()
    u = users.get(uname, {})
    st.text_input("用户名", value=uname, disabled=True)
    st.text_input("角色", value=u.get("role", "teacher"), disabled=True)
    new_display = st.text_input("显示名", value=u.get("display_name", uname))
    col1, col2 = st.columns(2)
    with col1:
        new_pw = st.text_input("新密码", type="password", placeholder="留空不修改")
    with col2:
        confirm_pw = st.text_input("确认密码", type="password", placeholder="再次输入")
    if st.button("保存", type="primary", use_container_width=True):
        if new_pw and new_pw != confirm_pw:
            st.error("两次密码不一致")
        elif new_pw and len(new_pw) < 6:
            st.error("密码至少6位")
        else:
            if new_pw:
                save_user(uname, new_pw, new_display.strip() or uname, u.get("role", "teacher"))
            else:
                import json
                users2 = load_users()
                users2[uname]["display_name"] = new_display.strip() or uname
                with open("data/users.json", "w", encoding="utf-8") as f:
                    json.dump(users2, f, ensure_ascii=False, indent=2)
            st.session_state.teacher_name = f"{new_display.strip() or uname}老师"
            st.success("已保存")
            st.rerun()


@st.dialog("常见问题", width="large")
def _open_faq_dialog():
    st.markdown("## ❓ 常见问题")
    st.markdown("---")

    faq_items = [
        ("如何导入评分标准？",
         "在「阅卷」页第一步，上传 **.docx** 或 **.ppt** 格式的评分标准文档，系统通过 AI 自动解析出：\n"
         "- 考试名称\n- 题目列表（题号、名称、满分）\n- 每道题的评分项（criteria）及各自满分\n\n"
         "解析完成后页面会显示题目概览，确认无误即可开始阅卷。"),
        ("支持哪些试卷格式？",
         "仅支持 **.docx** 格式的 Word 文档。试卷需要放在 `data/papers/班级名/` 目录下，支持两种组织方式：\n\n"
         "**方式一：散放**\n```\ndata/papers/电商2501/\n├── 张三.docx\n├── 李四.docx\n└── ...\n```\n\n"
         "**方式二：子文件夹（可附带辅助文件）**\n```\ndata/papers/电商2501/\n├── 张三/\n│   ├── 试卷.docx\n│   ├── 截图.png\n│   └── 数据.xlsx\n└── ...\n```\n\n"
         "辅助文件（图片、Excel）会自动关联到对应题目。"),
        ("评分模式（宽松/标准/严格）有什么区别？",
         "三种模式控制档位（Tier）的分数比例范围，影响「答题质量 → 实际得分」的映射：\n\n"
         "| 模式 | 特点 | 适用场景 |\n|------|------|----------|\n"
         "| 宽松 | 有做就给高分，档位比例偏高 | 练习、平时作业 |\n"
         "| 标准 | 平衡给分，正常评判 | 期中/期末考试 |\n"
         "| 严格 | 高标准要求，有错必扣 | 竞赛选拔、证书考核 |\n\n"
         "也可以在「评分配置」页创建自定义预设，自由设定各档位的 ratio_min ~ ratio_max。"),
        ("档位（Tiers）和题目权重是什么关系？",
         "两者独立，互不影响：\n\n"
         "**档位（Tier）**：控制单道题的「答题质量 → 实际得分」映射。\n"
         "- 例：一道 20 分的题，「贴合主题」档 ratio=0.95~1.0 → 实际得分 19~20\n"
         "- 同题「跑题」档 ratio=0.35~0.55 → 实际得分 7~11\n\n"
         "**题目权重**：即该题的 `max_score`，由评分标准文档定义。\n"
         "- 例：Q1=15分（占15%），Q5=25分（占25%）→ Q5 对总分影响更大\n\n"
         "**最终总分 = Σ(题目i × 档位ratio)**，档位决定单题给分高低，权重决定题目在总分中的占比。"),
        ("查重是怎么工作的？",
         "查重采用**五维交叉验证**，加权综合评分：\n\n"
         "1. **元数据**（30分）：检测 Application ID（WPS/Office 设备指纹）、编辑时长（TotalTime ≤ 5分钟且 revision ≤ 5 → 疑似只改名字）、保存时间线（相差 <10 分钟 → 可疑）\n"
         "2. **文本相似度**（30分）：各题提示词全文对比，相似度 > 85% 加分\n"
         "3. **图片 MD5**（30分/张）：完全相同的图片直接判定为抄袭\n"
         "4. **Excel 指纹**（20分）：数据行数+列名+前5行内容哈希对比\n"
         "5. **综合评分**：\n"
         "   - < 100 分 → ✅ 正常，忽略\n"
         "   - 100~200 分 → ⚠️ 可疑，建议人工复核\n"
         "   - 200~300 分 → 🔴 高度可疑，重点审查\n"
         "   - ≥ 300 分 → 🚫 确认抄袭，**自动判零分**"),
        ("为什么我传了3份试卷还不能查重？",
         "查重需要同一班级内有 **≥ 2 份试卷**，且试卷需位于 `data/papers/` 下的实际目录中。\n\n"
         "**排查步骤**：\n"
         "1. 确认阅卷时勾选了「阅卷后自动查重」\n"
         "2. 确认使用的是「文件夹扫描」模式（上传模式查重路径可能不匹配）\n"
         "3. 检查 `data/papers/班级名/` 目录确实存在且有 ≥2 个 .docx 文件\n"
         "4. 查看阅卷结果页的查重报告下载区是否有提示"),
        ("大批量阅卷怎么加速？",
         "**方法一：命令行多线程**\n```bash\npython main.py --workers 8\n```\n默认4线程，可根据 CPU 核心数调整。\n\n"
         "**方法二：LLM 缓存**\n系统自动缓存相同 prompt+model 的评分结果。同一道题、相同内容只调一次 API，后续直接复用。阅卷完成后自动清缓存。\n\n"
         "**方法三：批量预检查**\n命令行模式会自动跳过明显空白的试卷，减少无效 API 调用。"),
        ("试卷里有视频/图片，系统能识别吗？",
         "能，系统具备完整的多媒体识别能力：\n\n"
         "**图片**：\n- 自动提取 Word 内嵌图片，缩放至 768px 后发送给视觉 LLM 评分\n- 跳过过小的装饰图（< 50KB）\n\n"
         "**视频（MP4）**：\n- 纯 Python 解析 MP4 容器元数据（时长、分辨率、编码格式），无需 ffmpeg\n- 使用 OpenCV 抽取 4 帧关键画面发送给 LLM 辅助评分\n- 视频验证失败不会导致崩溃，自动降级为无视频处理\n\n"
         "**依赖**：仅需 `opencv-python-headless`，已在 requirements.txt 中。"),
        ("为什么某道题明明是空的还给了分？",
         "系统采用**保守判空**策略，避免误杀：\n\n"
         "1. 只有学生确实没填任何内容（文本 < 5字符 **且** 无图片/视频/链接/**且** 排除表格标签文字）→ 直接判 0 分\n"
         "2. 如果表格中有标签文字但无实质内容，系统会正确识别为空\n"
         "3. 如果 LLM 提取到了疑似内容但不确定，会发送给 LLM 做最终判断\n\n"
         "如果发现误判（有内容的题被判了0分），可以在「核查提醒」展开区查看并人工复核。"),
        ("保存 Excel 报告时报错 'Permission denied'？",
         "说明 Excel 文件正在被 Microsoft Excel 或 WPS 打开。\n\n"
         "**解决**：关闭 Excel/WPS 窗口后点击重试即可。系统会给出明确的提示「文件已在 Excel 中打开，请关闭后重试」，不会自动覆盖或产生混乱的临时文件。"),
        ("评分标准可以修改吗？",
         "可以。在「评分配置」页可以：\n"
         "- 调整各档位的分数比例（ratio_min ~ ratio_max）\n"
         "- 添加自定义评分预设（如「适当严格」）\n"
         "- 修改后点击「保存配置」生效（有绿色 Toast 提示）\n"
         "- 不满意可「重置默认值」恢复出厂设置"),
        ("系统能导出什么报告？",
         "| 报告 | 格式 | 内容 |\n|------|------|------|\n"
         "| 班级得分表 | .xlsx | 每学生每道题得分 + 各评分项明细 + 班级平均分 |\n"
         "| 查重报告 | .xlsx | 可疑对列表（可疑度+原因）+ 元数据总览（编辑时长/revision/设备ID） |\n\n"
         "导出位置：`output/班级名/` 目录下。Web 界面可直接下载，CLI 模式自动生成。"),
        ("如何更新/升级系统？",
         "```bash\ngit pull\npip install -r requirements.txt\n```\n"
         "配置文件（config.yaml）和评分标准（data/rubric.json）不会因升级丢失。自定义预设保存在 config.yaml 中，升级前建议备份。"),
    ]
    search = st.text_input("🔍 搜索", placeholder="输入关键词过滤...", key="faq_search")
    items = faq_items if not search else [
        (q, a) for q, a in faq_items if search.lower() in q.lower() or search.lower() in a.lower()
    ]
    if not items:
        st.warning("未找到匹配的问题，请尝试其他关键词")
    for q, a in items:
        with st.expander(q):
            st.markdown(a)


@st.dialog("使用说明", width="large")
def _open_guide_dialog():
    st.markdown("## 📖 使用说明")
    st.markdown("---")

    st.markdown("### 🚀 快速开始")
    st.markdown("""
| 步骤 | 操作 | 说明 |
|------|------|------|
| ① | **导入评分标准** | 阅卷页 → 第一步上传 .docx 评分标准文档，AI 自动解析题目和评分项 |
| ② | **准备试卷** | 将学生 .docx 放入 `data/papers/班级名/` 目录（支持子文件夹） |
| ③ | **选择班级** | 阅卷页 → 第二步扫描/上传试卷，勾选要评的班级 |
| ④ | **开始阅卷** | 阅卷页 → 第三步点击「开始阅卷」，等待进度条完成 |
| ⑤ | **查看 & 下载** | 成绩总览、统计指标、下载班级得分表和查重报告 |
""")

    st.markdown("### 📂 试卷目录结构")
    st.markdown("""
```
ai-grader/
├── data/
│   └── papers/              ← 试卷根目录
│       ├── 电商2501/         ← 班级文件夹（含数字自动识别为班级）
│       │   ├── 255102030101张三.docx
│       │   ├── 李四/          ← 学生子文件夹（可含辅助文件）
│       │   │   ├── 试卷.docx
│       │   │   ├── 截图.png
│       │   │   └── 数据.xlsx
│       │   └── ...
│       └── 软件2501/
│           └── ...
├── output/                   ← 阅卷输出
│   ├── 电商2501/
│   │   ├── 评分汇总_电商2501.xlsx
│   │   └── 查重报告.xlsx
│   └── 软件2501/
│       └── ...
├── config.yaml               ← 主配置文件
├── requirements.txt
├── app.py                    ← Web 界面入口
└── main.py                   ← CLI 命令行入口
```

- **班级识别**：文件夹名包含数字（如 `电商2501`、`Class01`）自动勾选，纯文字文件夹需手动勾选
- **辅助文件**：学生子文件夹内的图片和 Excel 自动关联到对应题目
""")

    st.markdown("### ⚙️ 评分模式配置")
    st.markdown("""
侧边栏可快速切换评分模式，也可在「评分配置」页精细调整：

| 模式 | 特点 | 适用场景 |
|------|------|----------|
| 宽松 | 有做就给高分，档位比例偏高 | 练习、平时作业 |
| 标准 | 平衡给分，正常评判 | 期中/期末考试 |
| 严格 | 高标准要求，有错必扣 | 竞赛选拔、证书考核 |
| ⭐ 自定义 | 自由设定各档位比例范围 | 特殊需求 |

在「评分配置」页可以创建自己的预设（如"适当严格"），保存后在侧边栏直接切换。
""")

    st.markdown("### 🔍 查重功能说明")
    st.markdown("""
阅卷时勾选「阅卷后自动查重」，系统自动对每个班级做五维查重分析：

| 维度 | 检测内容 | 满分 |
|------|----------|------|
| 元数据 | 设备指纹（Application ID）、编辑时长、修订次数、保存时间 | 55分 |
| 文本相似度 | 各题提示词全文对比 | 30分 |
| 图片 MD5 | 完全相同的图片 → 抄袭 | 30分/张 |
| Excel 指纹 | 数据行数+列名+前5行哈希 | 20分 |

**查重结果分级**：

| 可疑度 | 级别 | 处理建议 |
|--------|------|----------|
| < 100 分 | ✅ 正常 | 无需处理，自动忽略 |
| 100 ~ 200 分 | ⚠️ 可疑 | 建议人工复核 |
| 200 ~ 300 分 | 🔴 高度可疑 | 重点审查 |
| ≥ 300 分 | 🚫 确认抄袭 | **自动判零分，总分清零** |

查重报告在阅卷结果页下载，含「可疑对」（配对详情+原因）和「元数据」（每份试卷的编辑统计）两个 Sheet。
""")

    st.markdown("### 💻 命令行批量阅卷")
    st.markdown("""
适用于大批量阅卷场景，无需打开浏览器：

```bash
# 基本用法（使用 config.yaml 中的配置）
python main.py

# 指定并发线程数（默认4，建议不超过 CPU 核心数）
python main.py --workers 8

# 指定试卷目录和输出目录
python main.py --papers data/papers --output output/

# 仅运行查重（不重新阅卷）
python main.py --check
```

命令行模式特性：
- 自动跳过明显空白的试卷，减少 API 浪费
- 多线程并行处理，速度提升显著
- LLM 结果自动缓存，相同内容不重复调 API
- 完成后在 `output/` 下生成和 Web 界面相同的报告
""")

    st.markdown("### ❗ 常见问题排查")
    st.markdown("""
| 问题现象 | 可能原因 | 解决方法 |
|----------|----------|----------|
| 解析评分标准失败 | 文档格式不标准或非 .docx | 确认文件格式正确，含明确题目名称和评分项 |
| 阅卷报 API 错误 | Key 未设置/余额不足/网络问题 | 检查侧边栏 API Key，确认 DeepSeek 账户余额 |
| Excel 保存 Permission denied | 文件已在 Excel/WPS 中打开 | **关闭 Excel 窗口后重试** |
| 查重报告未生成 | 不足2份试卷或班级目录不匹配 | 确认 ≥2 份试卷且使用文件夹扫描模式 |
| 某题得分明显异常 | LLM 判断偏差或内容提取错误 | 查看「核查提醒」展开区，人工复核 0 分项 |
| 视频/图片未识别 | 格式特殊或内嵌方式不标准 | 系统已适配常见格式和 OLE 嵌入，不支持的格式自动降级 |
| 文件名为 ~$ 开头被跳过 | 这是 Office 临时锁文件 | 正常现象，系统自动跳过临时文件 |
""")

    st.markdown("### 📊 输出文件一览")
    st.markdown("""
```
output/
└── 班级名/
    ├── 评分汇总_班级名.xlsx    ← 班级得分表
    │   ├── Sheet「得分表」：每学生每题得分 + 各评分项明细 + 平均行
    │   └── 三行表头：大题（合并）→ 得分项名 → 满分
    └── 查重报告.xlsx            ← 查重结果
        ├── Sheet「可疑对」：配对详情 + 可疑度 + 原因
        └── Sheet「元数据」：每份试卷的编辑统计
```

**提示**：所有配置（评分标准、预设、API Key）只需设置一次，换班级直接阅卷即可。班级之间完全独立，互不影响。
""")

    st.caption("💡 还有问题？点击侧边栏「常见问题」或查看项目 README.md。")


# ============================================================
#  Dialog 触发逻辑（在所有函数定义之后）
# ============================================================

if "dialog_type" not in st.session_state:
    st.session_state.dialog_type = None

_dtype = st.session_state.dialog_type
if _dtype is not None:
    st.session_state.dialog_type = None
    if _dtype == "profile":
        _open_profile_dialog(teacher)
    elif _dtype == "faq":
        _open_faq_dialog()
    elif _dtype == "guide":
        _open_guide_dialog()
