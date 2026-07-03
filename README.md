# 阅卷系统

用 LLM + 纯代码自动批阅 Word 试卷。支持文字/图像/视频/Excel/智能体多种题型。

## 快速开始

```bash
pip install -r requirements.txt

# 设 API Key
set DEEPSEEK_KEY=sk-xxx          # Windows
export DEEPSEEK_KEY=sk-xxx       # Mac/Linux

# 放试卷：data/papers/班级名/*.docx
# 运行 CLI
python main.py

# 或 Web 界面
streamlit run app.py
```

## 换试卷只需三步

1. 准备评分标准 .docx → 阅卷页上传，AI 自动解析
2. 放试卷到 `data/papers/班级名/`
3. 点击「开始阅卷」

## 目录结构

```
data/
  rubric.json              ← AI 解析后的评分标准
  papers/                  ← 试卷放这里
    数媒2501/
      张三.docx
output/                    ← 阅卷结果
  数媒2501/
    个人成绩/ 评分明细_张三.xlsx
    评分汇总_数媒2501.xlsx
```

## 配置

复制 `config.example.yaml` 为 `config.yaml`：

```yaml
llm:
  provider: deepseek          # deepseek / anthropic / openai
  model: deepseek-chat
grading:
  mode: relaxed               # relaxed宽松 / normal标准 / strict严格 / 自定义
database:
  type: sqlite                # sqlite 零配置
```

## 评分题型

| 类型 | 评分方式 | 说明 |
|------|---------|------|
| text | LLM 文字评分 | 文本生成、文案创作等 |
| vision | LLM 视觉评分 | 图像/视频题，视频自动提取4帧送 LLM |
| code | pandas 数据检查 | Excel 数据处理，去重/填空/格式化/排序 |
| hybrid | LLM + 元数据 | 智能体搭建，检查人设/截图/链接 |

## 评分档位

档位由系统自动检测（切题关键词 + 素材完整度），控制该题得分乘数范围：

| 档位 | 含义 | 默认范围 |
|------|------|---------|
| 贴合主题 | 内容紧扣主题、素材齐全 | 95%-100% |
| 有视频/有截图/有链接 | 对应素材存在 | 85%-100% |
| 跑题 | 内容偏离主题 | 35%-55% |
| 无视频/无截图/无链接 | 对应素材缺失 | 30%-50% |
| 素材不足 | 多项关键素材缺失 | 10%-25% |
| 敷衍 | 仅有极少内容 | 20%-35% |
| 空 | 实质性未作答 | 0% |

档位可在「评分配置」页自由调整，支持另存为自定义预设。

## 评分模式 vs 题目权重

- **档位**：控制单题内给分宽松度。例如 20 分题「贴合主题」档在宽松下给 19-20 分
- **权重**：即每题 max_score，决定该题在总分中的占比
- 最终总分 = Σ(题目i × 档位ratio)，两者独立

## CLI 批量模式

```bash
python main.py --workers 8 --check
```

| 参数 | 说明 |
|------|------|
| `--workers N` | 并行线程数（默认 4，设 1 为串行） |
| `--check` | 阅卷后自动查重 |
| `--config` | 指定配置文件 |
| `--rubric` | 指定评分标准 .docx |

系统会自动缓存相同 prompt+model 的 LLM 结果，省 token 也更快。

## Web 界面

```
streamlit run app.py
```

- **阅卷**：上传评分标准 → 扫描班级 → 一键阅卷
- **评分配置**：调整档位、题目权重、数据检查规则
- **历史结果**：查看成绩分布、下载汇总/明细/查重报告

## 查重

五维交叉验证：文档元数据 + 文本相似度 + 图片 MD5 + Excel 指纹 + 编辑时间线。

## 移植

```bash
pip install -r requirements.txt
# 复制 data/ config.yaml 到新环境即可
```
