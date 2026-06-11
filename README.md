# pubmed-digest

每天自动从 PubMed 抓取前一天发表的医学论文，调用 DeepSeek AI 按 **AITDA 结构**生成适配多平台的短视频脚本，供数字人朗读使用。

支持平台：抖音 / 视频号 / 小红书

---

## 快速开始

### 1. 安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -r requirements.txt
```

### 2. 配置

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # macOS / Linux
```

编辑 `.env`，至少填写：

```env
DEEPSEEK_API_KEY=你的密钥
PUBMED_EMAIL=任意邮箱（NCBI 要求，无需注册）
```

### 3. 运行

```bash
# 生成昨天的脚本，所有平台，输出到 stdout
python main.py

# 指定日期
python main.py --date 2026-05-28

# 只生成视频号版
python main.py --platform shipinghao

# 保存到文件（以日期命名，如 2026-05-28.txt）
python main.py --outdir ./output

# 专题模式：查睡眠专题最近 7 天的论文（新增）
python main.py --topic sleep --days 7

# 专题模式 + 指定输出
python main.py --topic "gut microbiome" --days 14 --outdir ./output

# 专题模式也可通过 .env 配置，无需每次输入命令行参数
```

---

## 命令行参数

| 参数 | 说明 | 默认值 |
|---|---|---|
| `--date YYYY-MM-DD` | 目标日期 | 昨天 |
| `--platform` | `douyin` / `shipinghao` / `xiaohongshu` / `all` | 读取 `PLATFORMS` 配置 |
| `--outdir DIR` | 输出目录，同时保存文件并打印到 stdout | 读取 `OUTPUT_DIR` 配置 |
| `--topic KEYWORD` | 专题关键词（如 `sleep`），开启专题+时间范围查询 | 读取 `PUBMED_TOPIC` 配置 |
| `--days N` | 回溯天数（与 `--topic` 配合使用） | 读取 `PUBMED_DAYS_BACK` 配置（默认 1） |

---

## 配置项（.env）

### 必填

| 变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `PUBMED_EMAIL` | 任意邮箱，NCBI E-utilities 要求提供 |

### 可选

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名称 |
| `PUBMED_API_KEY` | 空 | PubMed API Key，可提升速率至 10次/秒（[免费申请](https://www.ncbi.nlm.nih.gov/account/)） |
| `OUTPUT_DIR` | 空（仅打印 stdout） | 脚本文件保存目录 |
| `PUBMED_MAX_RESULTS` | `30` | 每次最多抓取的论文篇数 |
| `PLATFORMS` | `all` | 生成哪些平台；`all` 或逗号分隔：`douyin,shipinghao,xiaohongshu` |
| `DOUYIN_WORDS` | `240` | 抖音脚本总字数（推荐 150–300，对应 30–60 秒） |
| `SHIPINGHAO_WORDS` | `300` | 视频号脚本总字数（推荐 250–450，对应 60–90 秒） |
| `XIAOHONGSHU_WORDS` | `210` | 小红书脚本总字数（推荐 150–250，对应 30–50 秒） |
| `PUBMED_TOPIC` | 空 | 专题关键词（如 `sleep`），开启专题查询模式；空=使用默认综合健康查询 |
| `PUBMED_DAYS_BACK` | `1` | 回溯天数（配合 `PUBMED_TOPIC` 使用） |

---

## AITDA 结构

每篇论文生成以下六部分：

| 段落 | 比例 | 说明 |
|---|---|---|
| ▶ 钩子 Hook | 10% | 强烈反问 / 反常识悬念，让人停下来 |
| ▶ 兴趣 Interest | 25% | 贴近日常生活，引发共鸣 |
| ▶ 信任 Trust | 31% | 引用论文发现，注明期刊名和年份 |
| ▶ 欲望 Desire | 25% | 转化为对普通人的健康意义 |
| ▶ 行动 Action | 余数 ≈ 9% | 引导互动 + 固定免责声明 |
| ▶ 完整串讲 | — | 五段整合为一段连续文字，可直接交给数字人朗读 |

各段字数根据 `*_WORDS` 配置按比例自动计算，总和精确等于配置值。

**视频号 300 字示例：** 钩子 30 / 兴趣 75 / 信任 93 / 欲望 75 / 行动 27

---

## 输出格式示例

```
=== PubMed 每日健康科普脚本（AITDA 结构）===
日期：2026年05月28日
检索论文数：3 篇
生成平台：视频号
========================================

========================================
  视频号  |  约90秒  |  300字  （钩子30/兴趣75/信任93/欲望75/行动27）
========================================

【第1篇】
▶ 钩子
你身体里的"隐形指挥官"，竟然在偷偷指挥免疫细胞对抗肿瘤？
▶ 兴趣
...
▶ 信任
...
▶ 欲望
...
▶ 行动
...如有健康问题，请咨询专业医生。
▶ 完整串讲
...（五段整合为可直接朗读的连续文字）
来源：《Gut microbes》2026 | https://pubmed.ncbi.nlm.nih.gov/42207498/
```

---

## 合规规则

System Prompt 内置 13 条内容红线，以下内容不会出现在生成结果中：

- 具体药物名称（处方药 / 非处方药 / 中草药 / 保健品品牌）
- 手术 / 医疗操作描述
- 剂量、用法用量等服用指导
- 化疗 / 放疗等临床治疗方案
- 诊断性表述（"你患有…" / "确诊"）
- 治愈 / 根治宣称
- 绝对化用语（"最佳" / "100% 有效"）
- 恐吓性表述
- 替代就医暗示
- 医疗器械推荐
- 夸大研究结论（"科学已证明"）
- 儿童 / 孕妇等特殊人群具体建议
- 疫苗相关争议内容

行动段结尾固定追加：**如有健康问题，请咨询专业医生。**

---

## 项目结构

```
pubmed-digest/
├── main.py               # CLI 入口
├── digest_generator.py   # 核心调度：抓取 → 生成 → 格式化
├── pubmed_client.py      # PubMed E-utilities 客户端
├── ai_client.py          # DeepSeek API 封装
├── config.py             # 配置加载（.env → dataclass）
├── requirements.txt      # 依赖：biopython / openai / python-dotenv / requests
├── .env                  # 本地配置（已加入 .gitignore，勿提交）
└── .env.example          # 配置模板
```
