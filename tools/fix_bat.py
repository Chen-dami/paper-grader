import os

ROOT = os.path.join(os.path.dirname(__file__), "..")

bat_files = ["setup.bat", "一键安装.bat", "启动阅卷系统.bat", "更新.bat"]

for name in bat_files:
    path = os.path.join(ROOT, name)
    if not os.path.exists(path):
        print(f"  SKIP {name} (not found)")
        continue
    # read as UTF-8, write as GBK
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except:
        # maybe already GBK?
        with open(path, "r", encoding="gbk") as f:
            content = f.read()

    with open(path, "w", encoding="gbk") as f:
        f.write(content)
    print(f"  OK   {name} -> GBK")

print("Done.")
