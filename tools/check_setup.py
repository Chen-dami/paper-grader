"""
环境检查工具 —— 验证阅卷系统是否正确配置。
用法：python tools/check_setup.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_python():
    v = sys.version_info
    ok = v >= (3, 10)
    print(f"  {'✅' if ok else '❌'} Python {v.major}.{v.minor}.{v.micro}" + (
        "" if ok else "  (需要 ≥3.10)"))
    return ok


def check_deps():
    deps = {
        "docx": "python-docx",
        "pandas": "pandas",
        "openpyxl": "openpyxl",
        "PIL": "Pillow",
        "yaml": "PyYAML",
        "openai": "openai",
        "streamlit": "streamlit",
        "olefile": "olefile",
        "cv2": "opencv-python-headless",
    }
    all_ok = True
    for mod, pkg in deps.items():
        try:
            __import__(mod)
            print(f"  ✅ {pkg}")
        except ImportError:
            print(f"  ❌ {pkg} 未安装 — pip install {pkg}")
            all_ok = False
    return all_ok


def check_dirs():
    dirs = ["data", "data/papers", "output", "tools"]
    all_ok = True
    for d in dirs:
        if os.path.isdir(d):
            cnt = len(os.listdir(d)) if os.path.isdir(d) else 0
            print(f"  ✅ {d}/ (存在, {cnt} 项)")
        else:
            os.makedirs(d, exist_ok=True)
            print(f"  ⚠️ {d}/ (已自动创建)")
    return all_ok


def check_config():
    config_path = "config.yaml"
    if not os.path.exists(config_path):
        print(f"  ❌ config.yaml 不存在 — 请从模板复制")
        return False
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        has_key = bool(cfg.get("llm", {}).get("api_key", ""))
        print(f"  ✅ config.yaml 存在")
        print(f"  {'✅' if has_key else '⚠️'} API Key{' 已配置' if has_key else ' 未配置（可在侧边栏设置）'}")
        mode = cfg.get("grading", {}).get("mode", "relaxed")
        print(f"  ℹ️  评分模式: {mode}")
        tiers = cfg.get("grading", {}).get("tiers", {})
        print(f"  ℹ️  档位配置: {len(tiers)} 个")
        return True
    except Exception as e:
        print(f"  ❌ config.yaml 解析失败: {e}")
        return False


def check_papers():
    papers_dir = "data/papers"
    if not os.path.isdir(papers_dir):
        print(f"  ⚠️ data/papers/ 不存在，请创建并放入试卷")
        return True
    docx_count = 0
    class_count = 0
    for root, _, files in os.walk(papers_dir):
        docx_files = [f for f in files if f.endswith('.docx') and not f.startswith('~$')]
        docx_count += len(docx_files)
        if root != papers_dir and docx_files:
            class_count += 1
    print(f"  ℹ️  {class_count} 个班级目录, {docx_count} 份 .docx 试卷")
    if docx_count == 0:
        print(f"  ⚠️ 未检测到试卷，请将 .docx 放入 data/papers/班级名/")
    return True


def main():
    print("=" * 50)
    print("  阅卷系统 — 环境检查")
    print("=" * 50)

    checks = [
        ("Python 版本", check_python),
        ("依赖包", check_deps),
        ("目录结构", check_dirs),
        ("配置文件", check_config),
        ("试卷文件", check_papers),
    ]

    results = []
    for name, fn in checks:
        print(f"\n📌 {name}:")
        results.append(fn())

    print("\n" + "=" * 50)
    if all(results):
        print("  ✅ 所有检查通过，系统就绪！")
        print("  启动 Web 界面：streamlit run app.py")
        print("  命令行批量：python main.py --workers 4")
    else:
        print("  ⚠️ 部分检查未通过，请根据上述提示修复")
    print("=" * 50)


if __name__ == "__main__":
    main()
