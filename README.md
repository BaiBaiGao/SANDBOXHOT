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

## 关于作者

**Bianco**，同济大学土木工程学院 × 米兰理工大学能源学院双学位博士生。我一直对用 LLM 做多智能体仿真感兴趣，尤其是在假想的极端情况下：不同个体面对不同的基础设施条件和外界干扰会怎样反应，通过推演计算提前看到由人引发的极端情况，辅助管理者决策。

欢迎做 sandbox simulation based on LLM agents 的同仁交流：xiaobaihao6666 [at] tongji.edu.cn · hao.bai [at] polimi.it

网站参考了数字生命卡兹克的 [AIHOT](https://github.com/KKKKhazix/AIHOT) 和 [khazix-skills](https://github.com/KKKKhazix/khazix-skills) 等仓库，主要借助 Codex 和 Claude 搭建。

## 它怎么工作

```
云端 GitHub Actions（每 4 小时，不用 Key）           笔记本（校园网/VPN 内，每 4 小时，用同济 Key）
──────────────────────────────────────           ─────────────────────────────────────────────
AIHOT 同款 RSS + 公众号 ┐                           ① 批量精选 + 双评复核
arXiv 定向检索 ×9（含 2023 年以来的历史回填）│          ② 中文精读（全文梳理、为什么值得看、主题、资源、验证强度）
OpenAlex 期刊 ×3        ├─▶ 去重、关键词预筛、规则版 ─▶  ③ 相关推荐（embedding）与事件综述
HN / GitHub / 游戏      ┘   发布网站  ◀──合并──────────   ④ 日报（今日必读）/ 周报
                                    data/enrichments.json  ⑤ 主题研判（每主题每周）/ 横纵专题报告（每周 1–3 篇）
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

流水线每周最多用 **800 积分**（滚动 7 天统计），剩下 200 留给你自己手动调用。单价写在 [`config/settings.json`](config/settings.json)。

| 任务 | 模型（按顺序回退） | 大约花费 |
|---|---|---|
| 批量精选 | DeepSeek-V4.1-Flash → MiMo-V2.6-Flash → Qwen3.8-Flash-Next（不思考） | 0.02–0.03 积分/条 |
| 双评复核（40–65 分的边界条目） | Qwen3.8-27B → GLM-5.3-Flash（不思考） | 约 0.05 积分/条 |
| 中文精读（所有入选条目） | GLM-5.3（思考 low） → MiMo-V2.6-Pro | 约 0.7–1 积分/篇 |
| 速读卡（≥55 分的学术/应用） | GLM-5.3 → MiMo-V2.6-Pro | 约 0.7–1 积分/张 |
| 相关推荐 | Qwen3-Embedding（256 维） | 几乎为 0 |
| 事件综述、日报 | GLM-5.3 | 1–3 积分/份 |
| 周报、主题研判、横纵专题 | Kimi-K3.1-Pro（512K 上下文） → GLM-5.3 | 研判约 3 积分/个，专题约 15 积分/篇 |

**匀速花费**：每天目标是 800 ÷ 7 ≈ 114 积分。每次运行按下面的顺序做：

精选 → 双评 → 新条目精读 → 相关推荐 → 事件综述 → 日报/周报 → 主题研判 → 横纵专题 → 新条目速读卡 → 历史回填（精读和速读卡）

- 近 24 小时花费超过目标的 120% 时，只做精选。
- 历史回填只在花费低于目标时进行，用来把剩余额度变成文献库。
- 单次运行最多 70 积分、最长 45 分钟。
- 每一步都会保存结果，中途断网也不会白花额度。

其他保护和以前一样：
- 401、403、429 或连不上平台时，本次运行立即停止调用模型。
- 模型返回的内容解析失败 2 次后，不再重试。
- 模型不可用时，网站照常用规则更新。

按每天 6 次运行估算，一周会花到接近 800 积分。如果笔记本每天只在线一两次，花得会少一些：800 是上限，不保证每周都能花满。

查看本地账本：`py run.py budget`（会显示每日进度）。实际扣费以平台的[消费明细](https://agi.tongji.edu.cn/system/model-usage)为准。

## 一键更新程序（双击运行）

仓库根目录的 `SANDBOXHOT-update.cmd` 是一个双击就能运行的更新程序：

- **第一次双击**：把 API Key 存进本地 `.env`，注册每 4 小时自动运行一次的 Windows 计划任务，然后立即更新一次。
- **之后每次双击**：立即更新一次，最后显示本周额度用量和日志位置。
- 需要连着校园网或学校 VPN。连不上时会直接结束，不消耗积分。

GitHub 上这个文件里**没有 Key**（`SBH_KEY` 留空，第一次运行时会提示你输入）。你本地那份带 Key 的副本请命名为 `SANDBOXHOT-update.local.cmd`，`*.local.cmd` 已被 `.gitignore` 忽略，不会上传，也不会被提交前的密钥检查拦下。

### 云端连同济 VPN（GitHub Actions，不需要开电脑）

`.github/workflows/enrich.yml` 每 4 小时在 GitHub 的服务器上用开源的 `openconnect --protocol=array`（同济 VPN 用的 Array Networks 协议）连上同济 VPN，运行和笔记本完全相同的 `python run.py enrich`，然后断开 VPN，只提交 `data/enrichments.json` 和额度账本 `data/cloud-usage.json`，再触发网站发布。

需要在仓库 **Settings → Secrets and variables → Actions → New repository secret** 里添加：

| 名称 | 内容 |
|---|---|
| `TONGJI_API_KEY` | 同济 API Key |
| `TONGJI_VPN_USER` | 统一身份认证账号 |
| `TONGJI_VPN_PASS` | 统一身份认证密码 |
| `TONGJI_VPN_HOST`（可选） | VPN 地址，默认 `vpn.tongji.cn`；和笔记本 `.env` 里的 `TONGJI_VPN_HOST` 一致即可 |
| `TONGJI_VPN_IP`（可选） | VPN 服务器的 IP，默认 `202.120.189.34`。在国外解析 `vpn.tongji.cn` 会得到另一台没有登录页的服务器，所以固定用笔记本 MotionPro 日志里 `set_host_ip` 显示的地址 |
| `TONGJI_VPN_METHOD`（可选） | VPN 登录的认证方式名。在笔记本 PowerShell 里运行 `Select-String -Path "$env:LOCALAPPDATA\MotionPro\Log\*.log" -Pattern "method name" \| Select-Object -Last 3`，取 `method name:` 后面的值；为空就不用添加 |

GitHub Secrets 是加密保存的，不会出现在仓库里，也会在运行日志里自动打码。没添加时这个任务会自动跳过。

- **额度**：云端的用量记在 `data/cloud-usage.json`，笔记本运行时也会把它算进滚动 7 天用量，两边合计不超过上限。
- **确认云端能用之后，建议停用笔记本的计划任务**，避免两边同时提交 `enrichments.json`：

```bash
powershell -Command "Unregister-ScheduledTask -TaskName SANDBOXHOT -Confirm:$false"
```

- **风险**：GitHub 的服务器在国外，学校可能拦截境外登录或自动化登录；学校开启短信验证后也会失效。失败时网站照常按规则更新，笔记本方案随时可以恢复。

### 自动连接同济 VPN（MotionPro）

不在校园网时，`update.ps1` 会先用 MotionPro 的命令行模式连上同济 VPN，调用完同济 API 后再断开，最后推送到 GitHub。

- **判断是否在校内**：`agi.tongji.edu.cn` 解析到 10.67.x.x 就算在校内，这时不连 VPN，也不会替你断开。
- **连接方式**：`MotionPro.exe -connect <地址> 443 <账号> <密码> 0 0 0 1`，参考 [tongji-motionpro-vpn](https://github.com/ranranxuejie/tongji-motionpro-vpn) 的实测。最多等 3 分钟，看到 “Array Networks SSL VPN” 接口拿到地址就算连上。
- **断开**：只断开脚本自己连的 VPN；出错或中途中断也会断开，下次运行会补断。
- **不需要短信验证码**的账号才能用（命令行模式不支持二次验证）。
- 加 `-NoVpn` 参数可以关闭这个功能。

第一次用之前，在仓库目录运行一次下面的命令，保存 VPN 账号。密码用 Windows DPAPI 加密后存进本机 `.env`，只有你这个 Windows 账户在这台电脑上能解开，不会上传：

```bash
powershell -ExecutionPolicy Bypass -File scripts\set_vpn.ps1
```

它会问是否立即测试一次“连接 → 断开”。之后可以随时查看状态：

```bash
powershell -ExecutionPolicy Bypass -File scripts\vpn.ps1 status
```

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
