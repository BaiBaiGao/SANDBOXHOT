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
信源（免费）            笔记本（本地）                                        GitHub
───────────            ──────────────────────────────────────────           ──────────
AIHOT 同款 18 个 RSS ┐
arXiv 定向检索 ×4    │   ① 去重 → ② 关键词预筛（零额度）
OpenAlex 期刊 ×3     ├─▶ → ③ 批量精选（便宜模型，8 条/次）              ─▶  docs/  ─▶ Pages 网站
HN / GitHub / 游戏   ┘   → ④ 速读卡（只做高分论文/应用）
                         → ⑤ 日报/周报（每天一次，写作更强的模型）
                         → ⑥ 聚簇 + 热度 → 生成静态 JSON 与 RSS
```

| 栏目 | 内容 | 侧重措施 |
|---|---|---|
| 学术论文 | arXiv、期刊、会议：LLM 社会仿真、生成式智能体、兵棋推演、人类行为模拟、沙盒环境 | 7 个专门的学术检索源；入选门槛 45（商业是 60）；有速读卡；首页排第一、篇幅最大 |
| 实际应用 | 政府、军事、城市、公共卫生、金融、供应链、教育中的推演和仿真实践 | 入选门槛 45；有速读卡；首页排第二 |
| 商业 / 游戏 / 平台工具 | 公司与融资、AI NPC 与模拟游戏、开源框架与模拟器 | 正常门槛，首页合并展示 |

**信源**：`group: "aihot"` 的 18 个 RSS 和 AIHOT 开源仓库 `industry/sources.json` 一致。另外加了 arXiv、OpenAlex、Hacker News、GitHub 和 Game Developer，用来补强学术和应用。AIHOT 的 X 和微信公众号信源要额外的抓取服务，这里没有加。全部配置在 [`config/sources.json`](config/sources.json)，把 `enabled` 改成 `false` 就能停用一个源。

## 额度策略（同济平台 Free 套餐：每周 1000 积分，所有模型共用）

额度规则来自你提供的《同济大学人工智能平台 API 调用与学生额度指南》，单价写在 [`config/settings.json`](config/settings.json)。

1. **能不用模型就不用。** 去重和关键词预筛都在本地完成。只有同时涉及“仿真/推演”和“AI/智能体”的内容才会发给模型。通用 AI 新闻大多在这一步被挡掉。
2. **一条内容只调用一次模型。** 相关性判断、领域分类、打分、中文标题和摘要合并成一次请求（AIHOT 要分好几次）。每次请求处理 8 条，处理过的内容不会重复发送，被筛掉的也会记下来。
3. **请求前缀固定，方便命中缓存。** 系统提示词每批完全相同，日期放在用户消息里。DeepSeek-V4.1-Flash 命中缓存的输入只收 0.4 积分/百万 tokens，未命中是 20。
4. **按任务选模型，并关闭不必要的思考。**

   | 任务 | 模型（按顺序回退） | 思考 | 估算 |
   |---|---|---|---|
   | 批量精选 | DeepSeek-V4.1-Flash → MiMo-V2.6-Flash → Qwen3.8-Flash-Next | none | 约 0.024 积分/条 |
   | 速读卡（分数 ≥68 的论文/应用） | DeepSeek-V4.1-Flash → MiMo-V2.6-Flash | none | 约 0.06 积分/张 |
   | 日报 / 周报 | GLM-5.3 → MiMo-V2.6-Pro → DeepSeek-V4.1-Flash | low | 约 2 / 3 积分/份 |

   按每天 60 条候选、8 张速读卡估算，**一周约 30 积分（周额度的 3%）**。省下来的额度主要用在速读卡和日报这些读者真正需要的地方。
5. **硬上限，防止意外。** 用量按滚动 7 天统计（不假设平台在哪一天重置）。流水线每周最多用 500 积分，留 500 积分给你自己手动调用。单次运行最多 25 积分。用量到 60% 时停写速读卡，到 90% 时日报改用规则版。
6. **出错就停，不空耗。** 401、403、429 或连不上平台（校外没连 VPN）时，本次运行立即停止调用模型。模型 ID 不对或返回 404 时自动换下一个模型。
7. **离线也能更新。** 模型不可用超过 36 小时，候选内容会按关键词分数先上线，标为“规则”。之后有额度时自动改写成模型精选。

查看本地账本：`py run.py budget`。实际扣费以平台的[消费明细](https://agi.tongji.edu.cn/system/model-usage)为准，平台只保留 7 天明细。

## 一键更新程序（双击运行）

仓库根目录的 `SANDBOXHOT-update.cmd` 是一个双击就能运行的更新程序：

- **第一次双击**：把 API Key 存进本地 `.env`，注册每 4 小时自动运行一次的 Windows 计划任务，然后立即更新一次。
- **之后每次双击**：立即更新一次，最后显示本周额度用量和日志位置。
- 需要连着校园网或学校 VPN。连不上时会直接结束，不消耗积分。

GitHub 上这个文件里**没有 Key**（`SBH_KEY` 留空，第一次运行时会提示你输入）。你本地那份带 Key 的副本请命名为 `SANDBOXHOT-update.local.cmd`，`*.local.cmd` 已被 `.gitignore` 忽略，不会上传，也不会被提交前的密钥检查拦下。

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
