# SANDBOXHOT

## 线上更新

[打开 SANDBOXHOT](https://baibaigao.github.io/SANDBOXHOT/)。更新分两部分：

| 谁 | 做什么 | 用不用同济 Key |
|---|---|---|
| GitHub Actions（云端，每 4 小时） | 采集信源、本地关键词规则精选、合并模型结果、发布网站 | 不用。云端连不上只对校园网/VPN 开放的同济平台，Key 也不能放进公开仓库 |
| 你的笔记本（连校园网或 VPN，每 4 小时） | `scripts\update.ps1` → `py run.py enrich`：用同济 API 给云端采集的条目做模型精选、中文标题摘要、速读卡和日报，只把结果写进 `data/enrichments.json` 并推送 | 用。Key 只存在笔记本的 `.env` 里 |

笔记本一推送，Actions 就会自动重新构建网站，标着“规则”的条目随之变成模型精选。笔记本关机或在校外时，网站照常用规则更新，等下次连上再补。两边写的是不同的文件，不会产生 git 冲突。

机器之心和量子位使用 Wechat2RSS 的公开订阅。公众号条目沿用相关性筛选，仅展示标题、短摘要和原文链接。

**AI 智能体 × 沙盘推演 / 仿真资讯合集。** 收集用 AI 智能体做沙盘推演、仿真、模拟的学术论文、实际应用、商业、游戏和平台资讯，比通用 AI 新闻站更看重**学术论文**和**实际应用**。

- 网站地址（开启 GitHub Pages 后）：`https://baibaigao.github.io/SANDBOXHOT/`
- 思路参考 [AIHOT](https://github.com/KKKKhazix/AIHOT)：采集、预筛、打分、中文标题摘要、事件聚簇、热度排序、日报周报。
- 和 AIHOT 的区别：**没有服务器、数据库、后台和登录**。所有访客看到同一个静态网站。你的笔记本定时跑一个纯 Python 脚本，生成网页后推送到 GitHub，由 GitHub Pages 免费托管。

## 它怎么工作

```
云端 GitHub Actions（每 4 小时，不用 Key）           笔记本（校园网/VPN 内，每 4 小时，用同济 Key）
──────────────────────────────────────           ─────────────────────────────────────────────
AIHOT 同款 RSS + 公众号 ┐                           ① 批量精选 + 双评复核
arXiv 定向检索 ×9（含 2023 年以来的历史回填）│          ② 中文精读（全文梳理、为什么值得看、主题、资源、验证强度）
OpenAlex 期刊 ×3        ├─▶ 去重、关键词预筛、规则版 ─▶  ③ 相关推荐（embedding）与事件综述
HN / GitHub / 游戏      ┘   发布网站  ◀──合并──────────   ④ 日报（今日必读）/ 周报
                                    data/enrichments.json  ⑤ 主题研判（每主题每周）/ 横纵专题报告（每周 1–2 篇）
                                                           ⑥ 速读卡，余额回填历史论文
```

网站栏目：

| 页面 | 内容 |
|---|---|
| 首页 | 今日必读 3 篇（附推荐理由）、日报、热点、主题导航、学术论文、实际应用、最新专题、商业/游戏/平台 |
| 学术论文 / 实际应用 / 商业 / 游戏 / 平台工具 | 按领域列出，可搜索、按时间与分数排序，“全部”里含历史回填的论文 |
| 条目详情 | 中文精读、为什么值得看、速读卡、验证强度、代码与数据链接、原文摘要、同一事件的其他报道、相关研究 |
| 主题（13 个） | 社会与舆论仿真、生成式智能体、兵棋推演、政策推演、经济金融、人类行为与合成样本、城市交通、公共卫生、组织谈判、世界模型与沙盒、评测与可信度、游戏 NPC、开源框架。每个主题有每周研判 |
| 专题研究 | 参考卡兹克的“横纵分析法”：纵轴讲一个方向是怎么走到今天的，横轴对比今天的主要路线和框架，交汇处给出判断 |
| 资源库 | 从入选内容里整理的代码、数据集、基准、模型链接（只收原文里出现过的链接） |
| 日报 / 周报 | 今日必读、学术前沿、落地应用、商业游戏平台、方法动向、可复用资源 |
| llms.txt / api/latest.json | 给 Agent 读的公开接口 |

学术和应用的侧重：入选门槛 45 分（商业 60 分），有速读卡，首页排在最前、篇幅最大，arXiv 检索式最多。

**信源**：`group: "aihot"` 的 18 个 RSS 和 AIHOT 开源仓库 `industry/sources.json` 一致；另外加了 arXiv、OpenAlex、Hacker News、GitHub、Game Developer 和两个公众号。全部配置在 [`config/sources.json`](config/sources.json)，主题在 [`config/topics.json`](config/topics.json)。

## 额度策略（同济平台 Free 套餐：每周 1000 积分，所有模型共用）

流水线每周最多用 **500 积分**（滚动 7 天统计），另外 500 留给你自己。单价写在 [`config/settings.json`](config/settings.json)。

| 任务 | 模型（按顺序回退） | 大约花费 |
|---|---|---|
| 批量精选 | DeepSeek-V4.1-Flash → MiMo-V2.6-Flash → Qwen3.8-Flash-Next（不思考） | 0.02–0.03 积分/条 |
| 双评复核（40–65 分的边界条目） | Qwen3.8-27B → GLM-5.3-Flash（不思考） | 约 0.05 积分/条 |
| 中文精读（所有入选条目） | GLM-5.3（思考 low） → MiMo-V2.6-Pro | 约 0.7–1 积分/篇 |
| 速读卡（≥55 分的学术/应用） | GLM-5.3 → MiMo-V2.6-Pro | 约 0.7–1 积分/张 |
| 相关推荐 | Qwen3-Embedding（256 维） | 几乎为 0 |
| 事件综述、日报 | GLM-5.3 | 1–3 积分/份 |
| 周报、主题研判、横纵专题 | Kimi-K3.1-Pro（512K 上下文） → GLM-5.3 | 研判约 3 积分/个，专题约 15 积分/篇 |

**匀速花费**：每天目标是 500 ÷ 7 ≈ 71 积分。每次运行按下面的顺序做：

精选 → 双评 → 新条目精读 → 相关推荐 → 事件综述 → 日报/周报 → 主题研判 → 横纵专题 → 新条目速读卡 → 历史回填（精读和速读卡）

- 近 24 小时花费超过目标的 120% 时，只做精选。
- 历史回填只在花费低于目标时进行，用来把剩余额度变成文献库。
- 单次运行最多 45 积分、最长 40 分钟。
- 每一步都会保存结果，中途断网也不会白花额度。

其他保护和以前一样：
- 401、403、429 或连不上平台时，本次运行立即停止调用模型。
- 模型返回的内容解析失败 2 次后，不再重试。
- 模型不可用时，网站照常用规则更新。

按每天 6 次运行估算，一周会花到接近 500 积分。如果笔记本每天只在线一两次，花得会少一些：500 是上限，不保证每周都能花满。

查看本地账本：`py run.py budget`（会显示每日进度）。实际扣费以平台的[消费明细](https://agi.tongji.edu.cn/system/model-usage)为准。

## 一键更新程序（双击运行）

仓库根目录的 `SANDBOXHOT-update.cmd` 是一个双击就能运行的更新程序：

- **第一次双击**：把 API Key 存进本地 `.env`，注册每 4 小时自动运行一次的 Windows 计划任务，然后立即更新一次。
- **之后每次双击**：立即更新一次，最后显示本周额度用量和日志位置。
- 需要连着校园网或学校 VPN。连不上时会直接结束，不消耗积分。

GitHub 上这个文件里**没有 Key**（`SBH_KEY` 留空，第一次运行时会提示你输入）。你本地那份带 Key 的副本请命名为 `SANDBOXHOT-update.local.cmd`，`*.local.cmd` 已被 `.gitignore` 忽略，不会上传，也不会被提交前的密钥检查拦下。

### 自动连接同济 VPN（准备中）

计划让更新程序在每次运行时自动打开 MotionPro、连上同济 VPN，调用完模型后再断开。MotionPro 在 Windows 上没有命令行接口，需要先在你的电脑上检测它的窗口结构：

```bash
powershell -ExecutionPolicy Bypass -File scripts\vpn_probe.ps1
```

这个脚本只读取信息，不会连接、点击或修改任何东西。按提示操作三步，然后把 `state\vpn_probe.txt` 的内容发给 Claude。

## 在笔记本上安装（Windows）

需要 Git 和 Python 3.10 以上（只用标准库，**不需要 pip 安装任何包**）。

**1. 只克隆最新版本**

```bash
git clone --depth 1 https://github.com/BaiBaiGao/SANDBOXHOT.git
```

```bash
cd SANDBOXHOT
```

**2. 在本机保存 API Key。** Key 只写进本地的 `.env`，这个文件已被 `.gitignore` 忽略，不会上传 GitHub。

```bash
powershell -ExecutionPolicy Bypass -File scripts\set_key.ps1
```

**3. 连上校园网或学校 VPN，验证 Key 和授权模型。** 这一步只查询模型列表，不消耗积分。

```bash
py run.py check
```

**4. 第一次补精选**（会给云端已有的条目全部过一遍模型，每次最多 160 条）

```bash
powershell -ExecutionPolicy Bypass -File scripts\update.ps1
```

**5. 本地预览**（可选），然后打开 http://localhost:8000

```bash
py run.py serve
```

**6. 定时自动更新**（每 4 小时一次，电脑开机并登录时运行）

```bash
powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1
```

网站已经由 GitHub Actions 部署到 Pages，不需要再设置。

### “电脑端只保留最新的版本”是怎么做到的

- 第 1 步用 `--depth 1` 克隆，本地不下载历史。
- 每次更新都先 `git pull`，网站文件直接覆盖，不保留旧版本或备份。
- `update.ps1` 每 7 天把本地仓库瘦身一次：推送成功后重新浅拉取最新提交，并清掉本地的旧对象。完整历史只保存在 GitHub 上。`.env` 和 `state\` 不受影响。
- 条目库自动清理：被筛掉的内容 30 天后删除，入选内容保留 365 天，网站只展示最近 180 天。

## 常用命令

| 命令 | 作用 |
|---|---|
| `py run.py enrich` | 笔记本模式：只用同济 API 补模型精选，写 `data/enrichments.json`（`update.ps1` 会调用它） |
| `py run.py update` | 完整流程：采集、精选、生成网站（云端 Actions 用 `--no-llm` 运行它） |
| `py run.py update --no-llm` | 完全不调用模型，零额度 |
| `py run.py update --force` | 忽略抓取间隔，所有信源立即抓取 |
| `py run.py budget` | 查看滚动 7 天用量，按模型和用途分开列出 |
| `py run.py check` | 检查 Key 和授权模型列表 |
| `py run.py guard` | 检查将要提交的文件里有没有 API Key |
| `py run.py build` | 用已有数据重新生成网站 |
| `py -m unittest discover -s tests` | 运行测试（用假模型服务器，不消耗额度） |

## 目录

```
config/      sources.json 信源 · keywords.json 预筛词表 · settings.json 模型/单价/额度/门槛
prompts/     triage.md 精选 · brief.md 速读卡 · digest.md 日报周报（改标准不用改代码）
sandboxhot/  采集、预筛、模型调用、额度账本、聚簇、日报、站点生成
docs/        静态网站（GitHub Pages 发布目录）
data/        条目库（提交到 GitHub，不含密钥）
state/       本地额度账本与运行状态（被 git 忽略）
scripts/     Windows 脚本：保存密钥、一键更新、注册计划任务
```

## 密钥安全

- 仓库里没有任何真实 API Key。代码只从本地 `.env` 或环境变量 `TONGJI_API_KEY` 读取。
- `.env` 和 `state/` 都在 `.gitignore` 里。`update.ps1` 提交前会运行 `py run.py guard`，发现 `sk-...` 格式的字符串就中止提交。GitHub Actions 每次推送也会再检查一遍。
- 只提交 `docs/` 和 `data/` 两个目录。
