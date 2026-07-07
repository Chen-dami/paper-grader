# AI 智能阅卷系统

LLM 驱动的多题型、多模态作业自动批阅系统。支持文字/图像/视频/Excel/智能体五种题型，五维抄袭检测，**两阶段评分流水线（视觉描述 → 文本评分）省 70-90% API 费用**。

---

## 快速开始

```
1. 双击 "一键安装.bat" → 等待3-5分钟
2. 配置 API Key（打开 cmd 执行）:
   setx DEEPSEEK_KEY "你的DeepSeek Key"      ← 必需（文本评分）
   setx BAILIAN_KEY "你的阿里云Key"           ← 推荐（视觉描述）
   setx ZHIPU_KEY "你的智谱Key"              ← 可选（免费视觉备选）
3. 双击 "启动阅卷系统.bat" → 浏览器自动打开 http://localhost:8501
4. 进入「评分配置 → 模型路由」→ 点击「🔍 检测API Key」
```

> 详细说明见 [`部署指南.md`](部署指南.md)

## 评分流水线（省钱核心）

```
学生作业 .docx
    │
    ├─→ 提取图片/视频帧
    │       │
    │       ▼
    │   视觉模型（Qwen-VL-Plus / GLM-4V-Flash）
    │   只描述不评分："看到了什么"
    │   输出 ~150 tokens ≈ ¥0.0007
    │       │
    │       ▼ 文字描述
    │       │
    └─→ 提取文字内容 ──→ DeepSeek-Chat
                         综合描述+文字 → 评分 JSON
                         输出 ~500 tokens ≈ ¥0.002

对比：让视觉模型直接评分 → 输出 ~2000 tokens ≈ ¥0.03/次
两阶段方案 → ~¥0.003/次，省 90%
```

## API Key 配置

| 平台 | 环境变量名 | 用途 | 模型 | 费用 |
|------|-----------|------|------|------|
| DeepSeek | `DEEPSEEK_KEY` | **文本评分（必需）** | deepseek-chat | ¥1/1M入 ¥4/1M出 |
| 阿里云 | `BAILIAN_KEY` | 视觉描述（推荐） | qwen-vl-plus | ¥1.5/1M入 ¥4.5/1M出 |
| 阿里云 | `BAILIAN_KEY` | 旗舰视觉 | qwen-vl-max | ¥3/1M入 ¥12/1M出 |
| 智谱 | `ZHIPU_KEY` | 免费视觉备选 | glm-4v-flash | 🆓 免费（限1图） |
| OpenAI | `OPENAI_API_KEY` | 可选 | gpt-4o | $2.5/1M入 |

> **两个 Key 即可全覆盖**：DeepSeek（文本评分）+ 阿里云/智谱任一个（视觉描述）。
> 一个都没有也能跑，但视觉题只能看文字判断。见 `.env.example`。

### 获取 API Key

| 平台 | 注册地址 | 说明 |
|------|---------|------|
| DeepSeek | [platform.deepseek.com](https://platform.deepseek.com) | 充值即用，极便宜 |
| 阿里云百炼 | [bailian.console.aliyun.com](https://bailian.console.aliyun.com) | 开通即送额度 |
| 智谱 | [open.bigmodel.cn](https://open.bigmodel.cn) | glm-4v-flash **免费** |

## 评分题型

| 类型 | 评分方式 | 说明 |
|------|---------|------|
| text | DeepSeek 文字评分 | 文本生成、文案创作 |
| vision | 视觉描述 + DeepSeek 评分 | 海报设计、视频创作（自动提取帧） |
| code | pandas 规则引擎 | Excel 数据处理（零 LLM 费用） |
| hybrid | DeepSeek + 元数据 | 智能体搭建 |
| multiple_choice / true_false / fill_blank / short_answer | 精确匹配 + 关键词 | 客观题 |

## 目录结构

```
ai-grader/
├── 一键安装.bat          # 全自动安装向导
├── setup.bat             # 环境安装
├── 启动阅卷系统.bat      # 日常启动
├── 更新.bat              # Git 自动更新
├── 给AI的安装提示词.txt   # 复制给 AI 教你安装
├── 部署指南.md            # 详细部署文档
├── app.py                # Web 入口 (Streamlit)
├── main.py               # CLI 入口
├── config.yaml           # 配置（模型路由/评分模式/档位）
├── data/                 # 试卷 + 评分标准 + 用户数据
├── output/               # 评分结果
├── src/                  # 源代码
├── tests/                # 单元测试
└── tools/                # 诊断/验证工具
```

## 常见问题

### Q: 启动后看不到模型？评分失败？
**A:** 进入「评分配置 → 模型路由」→ 点击「🔍 检测API Key」按钮。系统**不会自动检测**（避免被安全软件标记为危险应用），需要手动点击。

### Q: 视觉题（视频/海报）得分很低或0分？
**A:** 检查「模型路由」页是否有视觉模型可用。如果没有视觉模型 API Key，系统只能用文字判断。至少配一个：阿里云 `BAILIAN_KEY` 或智谱 `ZHIPU_KEY`。

### Q: API 费用大概多少？
**A:** 一份试卷（4道题）约 ¥0.01-0.03。视觉题因为需要视觉模型描述图片，稍贵一点。代码题零费用。

### Q: 免费方案能用吗？
**A:** 可以。DeepSeek（文本）\+ 智谱 glm-4v-flash（视觉，免费）即可覆盖全部功能。但 glm-4v-flash 每道题只能看 1 张图，视频题评估可能不够全面。

### Q: 为什么视觉模型不直接评分？
**A:** 视觉模型输出 token 很贵（是 DeepSeek 的 3-10 倍）。两阶段流水线让视觉模型只"描述看到了什么"（输出 ~150 tokens），然后 DeepSeek 根据描述打分（输出 ~500 tokens），省 70-90% 费用。

### Q: 查重怎么用？
**A:** 阅卷时勾选「阅卷后自动查重」。可疑度 ≥300 自动判零。查重报告在 output/班级名/ 下。

### Q: 如何批量评分？
**A:** 命令行：`python main.py --workers 8 --check`

### Q: 换电脑怎么迁移？
**A:** 复制整个文件夹到新电脑，双击「一键安装.bat」。`data/` 和 `output/` 目录需保留，`.venv/` 不需要复制。

## 查重

五维交叉验证：文档元数据 + 文本相似度 + 图片 MD5 + Excel 指纹 + 编辑时间线。
自动分类：正常 / 可疑 / 高度可疑 / 确认抄袭（自动判零）。

## 更新

```bash
# 作者: git push
# 用户: 双击 更新.bat
```
