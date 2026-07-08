"""模拟更新.bat的复制逻辑，验证跳过保护是否正确"""
import os, shutil, tempfile

tmp = tempfile.mkdtemp(prefix='update-test-')
src = os.path.join(tmp, 'paper-grader-master')
dest = os.path.join(tmp, 'project')

# 1. 创建「当前项目」模拟
os.makedirs(f'{dest}/src', exist_ok=True)
os.makedirs(f'{dest}/pages', exist_ok=True)
os.makedirs(f'{dest}/data', exist_ok=True)
os.makedirs(f'{dest}/output', exist_ok=True)
with open(f'{dest}/app.py', 'w') as f: f.write('OLD VERSION v1.0')
with open(f'{dest}/config.yaml', 'w') as f: f.write('old config')
with open(f'{dest}/data/rubric.json', 'w') as f: f.write('my rubric')
with open(f'{dest}/output/result.xlsx', 'w') as f: f.write('student scores')
with open(f'{dest}/.env', 'w') as f: f.write('MY_REAL_API_KEY=secret')

# 2. 创建「新版」模拟（GitHub zip 解压结果）
os.makedirs(f'{src}/src', exist_ok=True)
os.makedirs(f'{src}/pages', exist_ok=True)
os.makedirs(f'{src}/data', exist_ok=True)
os.makedirs(f'{src}/output', exist_ok=True)
with open(f'{src}/app.py', 'w') as f: f.write('NEW VERSION v2.0')
with open(f'{src}/config.yaml', 'w') as f: f.write('new config')
with open(f'{src}/src/grader.py', 'w') as f: f.write('NEW GRADER')
with open(f'{src}/data/new-rubric.json', 'w') as f: f.write('new rubric from template')
with open(f'{src}/output/new-result.txt', 'w') as f: f.write('would overwrite scores!')
with open(f'{src}/.env', 'w') as f: f.write('TEMPLATE_API_KEY=change_me')

# 3. 执行复制逻辑
SKIP_DIRS = {'data', 'output', '.venv', '__pycache__', '.pytest_cache', '.git'}
SKIP_FILES = {'.env'}

print("=" * 60)
print("  模拟 更新.bat 文件复制逻辑")
print("=" * 60)

errors = []

for item in os.listdir(src):
    src_item = os.path.join(src, item)
    if os.path.isdir(src_item):
        if item in SKIP_DIRS:
            print(f"  SKIP dir:  {item}/  (保留用户数据)")
        else:
            target = os.path.join(dest, item)
            if os.path.exists(target):
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(src_item, target)
            print(f"  COPY dir:  {item}/")
    else:
        if item in SKIP_FILES:
            print(f"  SKIP file: {item}  (保留用户API Key)")
        else:
            shutil.copy2(src_item, dest)
            print(f"  COPY file: {item}")

os.makedirs(f'{dest}/data', exist_ok=True)
os.makedirs(f'{dest}/output', exist_ok=True)

# 4. 验证
print()
print("=" * 60)
print("  验证结果")
print("=" * 60)

tests = [
    ("app.py 已更新", open(f'{dest}/app.py').read(), "NEW VERSION v2.0"),
    ("config.yaml 已更新", open(f'{dest}/config.yaml').read(), "new config"),
    ("src/grader.py 已复制", open(f'{dest}/src/grader.py').read(), "NEW GRADER"),
    ("data/rubric.json 保留", open(f'{dest}/data/rubric.json').read(), "my rubric"),
    ("output/result.xlsx 保留", open(f'{dest}/output/result.xlsx').read(), "student scores"),
    (".env API Key 保留", open(f'{dest}/.env').read(), "MY_REAL_API_KEY=secret"),
]

all_ok = True
for desc, actual, expected in tests:
    ok = actual == expected
    status = "PASS" if ok else "FAIL"
    if not ok: all_ok = False; errors.append(f"{desc}: expected={expected!r} got={actual!r}")
    print(f"  [{status}] {desc}")

# 5. 检查不应该出现的
if os.path.exists(f'{dest}/output/new-result.txt'):
    print("  [FAIL] output/new-result.txt 被覆盖了！（应该跳过output/）")
    all_ok = False
else:
    print("  [PASS] output/ 目录未被新版覆盖")

print()
if all_ok:
    print(">>> 全部通过！更新逻辑正确。")
else:
    print(">>> 存在问题:")
    for e in errors:
        print(f"    {e}")

shutil.rmtree(tmp, ignore_errors=True)
