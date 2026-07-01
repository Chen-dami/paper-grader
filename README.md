# 阅卷系统

用 LLM + 纯代码自动批阅 Word 试卷。支持文字/图像/视频/Excel/智能体多种题型。

## 快速开始

```bash
pip install -r requirements.txt

# 设 API Key
set DEEPSEEK_KEY=sk-xxx          # Windows
export DEEPSEEK_KEY=sk-xxx       # Mac/Linux

# 放试卷：data/papers/班级名/*.docx
# 运行
python main.py
```

## 目录结构

```
data/papers/          ← 试卷放这里
    数媒2501/
        张三.docx
        李四.docx
    数媒2502/
        ...

output/               ← 阅卷结果
    数媒2501/
        个人成绩/
            评分明细_张三.xlsx
        评分汇总_数媒2501.xlsx
```

## 配置

复制 `config.example.yaml` 为 `config.yaml`，按需修改：

```yaml
llm:
  provider: deepseek          # deepseek / anthropic / openai
  model: deepseek-chat
grading:
  mode: relaxed               # relaxed=宽松 / normal=标准 / strict=严格
database:
  type: sqlite                # sqlite=零配置 / mysql=需配密码
```

## 评分题型

| 题号 | 类型 | 满分 | 评分方式 |
|------|------|------|---------|
| 一 | 文本生成 | 15 | 代码检测关键词，直接算分 |
| 二 | 图像生成 | 20 | 代码定档 + LLM 打分 |
| 三 | 视频生成 | 20 | 代码定档 + 视频文件检测 + LLM 打分 |
| 四 | 数据处理 | 20 | 纯 pandas 检测，零 token |
| 五 | 智能体开发 | 25 | 代码定档 + LLM 打分 |

## 评分档位

| 情况 | 给分 |
|------|------|
| 切题 + 内容充实 | 满分 |
| 切题 + 内容一般 | 75% |
| 跑题但有内容 | 50% |
| 空的没写 | 0 |
