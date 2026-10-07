# SocialAlpha

SocialAlpha 是一个开发中的 Python 项目，计划结合社交媒体、新闻和加密货币行情，探索文本清洗、情绪与事件分析、实验性交易信号、回测和可视化。

## 代码结构与统一启动

从项目根目录统一启动，默认使用本地数据生成报告，不采集、不调用模型：

```powershell
& D:/Anaconda/python.exe "D:/code Python/SocialAlpha/main.py"
```

刷新并分析时仍使用 `--refresh-news --analyze --limit 10` 等现有参数。原有 `app/pipeline_run.py`、`app/news_run.py`、`app/market_run.py` 和 `app/analyze_news_run.py` 命令继续可用，均支持 `--help`。

| 位置 | 职责 |
| --- | --- |
| `main.py`、`app/` | 启动、参数解析、日志设置和入口异常处理 |
| `pipeline/research_pipeline.py` | 编排各步骤；分别组装报告、保存结果和执行可选回测 |
| `crawler/news_pipeline.py`、`crawler/*_crawler.py` | 新闻与社媒采集、滚动窗口合并、来源状态保存 |
| `processor/` | 文本清洗、相关性筛选、均衡排队、模型分析和缓存预算 |
| `market_data/` | 行情采集、历史合并与价格数据校验 |
| `reporting/`、`signals/`、`backtest/` | 报告计算与展示、研究信号、历史验证 |
| `private_module/` | 统一配置加载、绝对路径、原子保存和日志初始化 |

业务模块直接调用业务模块，不依赖 `app/`。`private_module/project_config.py` 统一加载配置并注入共享币种定义；配置每次独立读取，运行时改动不会写回配置文件。文件保存统一使用 `private_module/project_io.py`，日志初始化统一使用 `private_module/private_log.py`。

| 配置文件 | 编辑内容 |
| --- | --- |
| `assets_config.json` | 币种列表及别名，唯一维护位置 |
| `news_config.json` | 媒体来源、采集数量和保留窗口 |
| `social_config.json` | 社区及官方账号、X 开关和来源状态路径 |
| `analysis_config.json` | 模型请求额度、筛选、排队和提示词 |
| `pipeline_config.json` | 报告与信号输出、评分阈值和回测成本 |
| `market_config.json` | 行情接口、报价资产和历史天数 |
| `reddit_config.json` | 独立 Reddit OAuth 工具参数，与公开订阅采集分开 |

币种顺序取 `assets_config.json` 中 `symbol_aliases` 的键顺序；新闻、分析和流程配置由统一加载器注入币种字段，业务代码不应直接解析这三份 JSON 来获取币种。现有缓存指纹、评分公式、请求额度、输出路径和数据格式延续原有行为。

## 当前实现

- `crawler/reddit_crawler.py`：手动获取 r/Bitcoin 的热门帖子，默认最多 20 条，输出前 5 条。
- 抓取字段包括作者、标题、正文、评分、评论数量、发布时间和链接；当前不抓取评论正文。
- `crawler/news_crawler.py`：采集 CoinDesk 和 Cointelegraph，并支持 RSS 2.0 与 Atom 订阅，不访问文章全文。
- `crawler/social_crawler.py`：采集 ETH、SOL、XRP、DOGE 的 Reddit 公开订阅和 BNB Chain Telegram 官方公告；X 官方 API 为可选接入。
- `processor/news_processor.py`：清洗 HTML、过滤无效条目、按规范链接去重、统一 UTC 发布时间，识别 BTC、ETH、SOL、XRP、DOGE、BNB 别名。
- `processor/news_focus.py`：保留六币种相关新闻（包括普通涨跌报道），标记 Strategy/CZ 和重大事件，过滤超出 48 小时时间窗口或无关内容。
- `processor/news_analyzer.py`：使用 LLM 结构化输出新闻情绪、事件类型、币种、摘要、判断依据和主观置信度；通过校验才保存成功结果。
- 新闻 LLM 分析已经完成真实在线调用验证。
- `reporting/daily_report.py`：生成六币种日报，保留事件、证据链接、重点对象动态和数据覆盖；不新增模型调用。
- `signals/sentiment_signal.py`：把情绪指标转换为可用于研究的长仓/现金假设，数据不足时不生成目标仓位。
- `market_data/market_loader.py`：校验真实历史行情 JSON，拒绝重复时点、无时区日期和非法价格。
- `market_data/market_fetcher.py`：通过无需密钥的 Binance 公共接口获取六币种 USDT 现货已完成日线。
- `reporting/market_report.py`：在日报中展示最新已完成日线收盘价格、单日涨跌幅及缺失/过期状态。
- `backtest/sentiment_backtest.py`：独立币种回测引擎，包含费用、滑点、净值与最大回撤，严格按信号可用时间对齐。
- `pipeline/research_pipeline.py`：统一业务流程，`main.py` 和 `app/pipeline_run.py` 共用启动参数。用户画像、网页看板和交易执行尚未接入。

## 框架与统一入口

```mermaid
flowchart LR
    A[新闻 RSS] --> B[文本清洗与去重]
    B --> C[币种相关性筛选与重点对象标记]
    C --> D[LLM 分析与缓存]
    D --> E[六币种日报]
    E --> F[研究信号与时点历史]
    G[真实历史行情 JSON] --> H[含成本的回测]
    F --> H
```

默认复用已保存的新闻分析，只生成报告与研究信号，不联网、不调用模型：

```powershell
& D:/Anaconda/python.exe "D:/code Python/SocialAlpha/app/pipeline_run.py"
```

需要刷新新闻并分析时显式开启：

```powershell
& D:/Anaconda/python.exe "D:/code Python/SocialAlpha/app/pipeline_run.py" --refresh-news --analyze --limit 5
```

回测接口检查：

```powershell
& D:/Anaconda/python.exe "D:/code Python/SocialAlpha/app/pipeline_run.py" --backtest
```

刷新行情并生成情绪与价格对照日报（不调用 LLM）：

```powershell
& D:/Anaconda/python.exe "D:/code Python/SocialAlpha/app/pipeline_run.py" --refresh-market
```

同时刷新新闻、行情和分析时，使用 `--refresh-news --refresh-market --analyze`。单独行情入口是 `app/market_run.py`。

`config/pipeline_config.json` 统一配置输出路径、报告窗口、研究阈值和回测成本。当前是手动入口，不会创建定时任务。报告窗口默认为最近 24 小时，至少 2 条置信度不低于 0.5 且上下文充分的分析才标为足够覆盖；未知或无新闻不能视为中性结论。情绪分数是文章总体倾向的汇总，多币种文章不代表每个币种有独立的价格方向判断。

输出均位于被 Git 忽略的 `data/`：

| 文件 | 用途 |
| --- | --- |
| `daily_report.md` / `daily_report.json` | 可阅读日报和结构化结果 |
| `signals_latest.json` | 六币种当前研究信号，缺数据时仓位为 null |
| `signals_history.json` | 每次实际生成的带时点信号，用于后续历史验证 |
| `market_daily.json` | 公共接口采集并持续合并的真实收盘行情 |
| `backtest_result.json` | 可选回测结果；没有行情时明确标记 missing_market_data |

行情为 JSON 列表，包含 `symbol`（币种）、`timestamp`（带时区 ISO 周期结束时间）、`close`（有限正数的真实收盘价），采集记录还保留 OHLC、成交量、报价币种、来源和采集时间。配置在 `config/market_config.json`，默认每次获取最近 90 根已完成 UTC 日线，按币种和周期结束时点与历史文件合并。任一币种请求或校验失败则不替换旧文件，不混用其他报价币种。

价格以 USDT 计价，不称为美元实时现价；日报涨跌幅为相邻已完成日线的收盘价变化，不是滚动 24 小时 ticker。缺少两根连续日线时涨跌幅为空，最新收盘超过 36 小时标为过期。Binance 日线 close time 是结束前最后一毫秒，本项目保存加一毫秒后的周期结束时间，未完成日线不会进入回测。接口说明见 [Binance 公共行情文档](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md)。没有足够历史时点信号时仍不展示收益数字，历史行情不会使今天的情绪变成过去已知的信息。

研究信号使用配置阈值：有效情绪高于正阈值时分配研究仓位，其余有效信号为现金；默认最大单币种研究权重为六分之一，总权重不超过 1。它是待检验的策略假设，没有证明有效，也不连接下单。回测结果是独立币种结果，不是六币种组合绩效。仅在信号 `as_of` 严格早于收盘时才允许用于下一段收益；今天采集和分析的新闻不能倒填到历史日期。当前刚开始积累真实信号，完整历史回测仍需要数据。

## 运行

在项目目录安装依赖并运行：

```powershell
python -m pip install -r requirements.txt
python crawler/reddit_crawler.py
```

抓取代码使用应用级 OAuth（`client_credentials`），需要获批且支持该认证方式的 Reddit 应用。将 `.env.example` 中的三项配置追加到本地 `.env`，保留已有配置，填写真实的 client ID、client secret 和包含本人 Reddit 用户名的 User-Agent。

业务默认值和接口地址位于 `config/reddit_config.json`。脚本缺少配置时会直接报错；401、403 和 429 会分别提示认证、访问权限和限流问题。令牌不写入文件，每次运行重新获取。尚未使用真实凭据验证在线访问，OAuth 接入不保证审批前可以抓取。

## 配置和数据

### 新闻 MVP（无需 Reddit 凭据）

```powershell
& D:/Anaconda/python.exe "D:/code Python/SocialAlpha/app/news_run.py"
```

新闻源、超时、数量和输出路径配置在 `config/news_config.json`，币种别名统一在 `config/assets_config.json`。默认每个来源读取最多 30 条，手动运行一次后结束，不启动定时采集。结果为项目绝对路径下的 `data/news_clean.json`，保留最近 48 小时内的旧记录并按规范链接合并新记录，避免订阅翻页或单源失败丢失已分析新闻；全部来源失败或窗口内没有有效新闻时保留旧文件。单个来源失败时记录错误并继续其他来源。

字段包括 `id`、`platform`、`source`、`content_kind`、`author`、`title`、`content`、`publish_time`、`fetched_at`、`score`、`comments`、`url`、`mention_symbol`。`content` 是媒体摘要或社媒原帖文本；没有点赞和评论数时使用 `null`；无法识别币种时返回空列表。去重使用相同规范链接，不按相似标题合并不同文章，也不将跨平台转帖宣称为独立事件。`fetched_at` 记录实际采集时间，发布时间不代表该数据在历史回测中已可获得。

### 社媒来源

`config/social_config.json` 管理社媒来源，可用顶层 `enabled: false` 关闭。默认采集 r/ethereum、r/ethtrader、r/solana、r/XRP、r/dogecoin 的最新 Atom 订阅，以及 `https://t.me/s/bnbchain` 公开公告页面。Reddit 订阅无需本地 OAuth 配置，但可能返回 403/429；不会切换代理绕过限制，也不会立即重试。来源失败独立记录，不阻断其他来源。

`data/social_source_status.json` 保存每次来源状态、采集条数、采集时间和可用的最新发布时间；HTTP 失败记录状态码。读取成功不代表窗口内有新消息，过期公告不会被改写成今天的新闻。采集日志按币种分别展示新闻/官方公告数和社区帖子数，数量尚未经过模型质量校验。

`content_kind` 为 `media`（媒体）、`official`（官方原帖）或 `community`（社区观点）。日报的有效新闻与研究信号使用媒体和官方原帖；社区观点单独显示在“社区情绪”及原帖依据中，不增加有效新闻数。问候、连续每日喊单和固定讨论标题由配置规则过滤；币种相关性仍依据正文明确提及判断，不因帖子来自某币种社区就强制归类。

X 默认关闭，账号列表为 ethereum、ethereumfndn、solana、XRPLF、dogecoin、BNBCHAIN。如需启用，将 `x.enabled` 设为 `true`，在本地 `.env` 中填写 `X_BEARER_TOKEN`，需要具有只读接口权限的 X API 凭据。接口使用 [账号查询](https://docs.x.com/x-api/users/get-user-by-username) 和 [账号原创帖子](https://docs.x.com/x-api/users/get-posts)，排除转发和回复；缺少凭据时明确跳过。X 在线访问尚未验证，仅完成模拟接口测试。

此本地 JSON 输出用于个人 MVP，不属于正式交易部标准数据源部署。文件被 Git 忽略，不会上传仓库。

### 新闻情绪与事件分析

在本地 `.env` 追加 `OPENAI_API_KEY` 和 `OPENAI_MODEL`，模型需要支持 Responses API 及严格 JSON Schema 输出。`OPENAI_BASE_URL` 可留空以使用官方接口；其他服务商必须支持这两项能力。仅向模型发送新闻标题、摘要、来源和发布时间，不发送作者信息。现有 Reddit 配置无需修改。

先离线检查，然后小批量调用：

```powershell
& D:/Anaconda/python.exe "D:/code Python/SocialAlpha/app/analyze_news_run.py" --dry-run
& D:/Anaconda/python.exe "D:/code Python/SocialAlpha/app/analyze_news_run.py" --limit 5
```

默认每次最多请求 5 条，当前每日上限已关闭（`daily_max_requests: null`）。可通过 `--limit` 指定本次处理条数；如果以后将每日上限设为正整数，提高 `--limit` 不会绕过每日上限。六币种相关新闻均可进入分析，包括普通涨跌报道；`focus.require_major_event: false` 表示重大事件关键词只作标记，不是入选门槛。分析按 `selection` 配置优先处理日报窗口内、已有有效分析较少的币种（用于排队的覆盖计数包含社区有效分析，报告计分仍分开）；选择后增加预计覆盖，避免单币占满额度。同等覆盖优先新闻与官方公告，再按时间排序，Strategy/CZ 不影响排队优先级。预计覆盖不是分析成功保证，下一次运行会重新计算。规则命中只是候选，不表示事实已核实。新闻涉及 Ripple 公司或 Binance 不一定与 XRP、BNB 直接相关，模型需进一步判断。

重点对象的作用在情绪汇总权重：`config/pipeline_config.json` 的 `report.default_news_weight` 默认为 1，`report.entity_weights` 中 Strategy 和 CZ 均为 1.25。有效评分使用 `Σ(情绪值 × 置信度 × 重要性权重) / Σ(置信度 × 重要性权重)`；同一文章出现多个重点对象只取最大权重，不相乘、不增加样本数。涉及重点对象的媒体报道不等于其本人提出买卖建议。该汇总是新闻情绪分数，不是币价涨跌概率。

参数在 `config/analysis_config.json`：`daily_max_requests` 为每日上限，`max_age_hours` 为新闻时间窗口，`focus` 为重点对象、币种和事件关键词，`selection` 为均衡排队窗口和置信度门槛，`community_exclude_patterns` 为低信息社区标题规则。归因分别为 `media_report`、`official_post`、`community_post`，不能把媒体转述或社区帖子当作本人推荐。

结果写入 `data/news_analysis.json`；`success`、`failed`、`pending`、`filtered` 分别表示成功、失败、未分析和规则过滤。失败条目不填充假结果，每次尝试均消耗请求额度，不自动重试。`data/analysis_usage.json` 保存每日请求次数及接口实际返回的 input/output/total tokens；首次迁移计入旧结果中已记录的调用，用量无法追溯的标为未知，不将其计为零消耗。调用前先预占额度，中断时保守计入次数。账本仅覆盖本项目，不是服务商账户账单，也不能恢复未记录的历史调用。

`data/analysis_cache.json` 保留成功的历史分析缓存，即使新闻暂时从 RSS 快照消失，再次出现仍可复用。缓存按新闻 ID、实际输入、模型、服务地址、提示词及输出结构校验；这些信息变更时会重新分析，仍受每日额度限制。当前版本扩展币种并精简提示词，因此旧版本缓存不会直接匹配。每次请求后保存进度，当前结果文件仅保留当前新闻快照。运行锁阻止并发修改；异常断电可能遗留 `data/analysis.lock`，确认任务已停止后才可移除。勿删除用量账本或缓存来绕过限额。

情绪选项为 `positive/negative/neutral/mixed/unknown`，事件类型为 `regulation/security/adoption/market/macro/technology/other/unknown`。`confidence` 是模型主观确定性，不是涨跌概率；`insufficient_context` 标记摘要信息不足。保留采集时间和实际分析时间，以便后续研究数据可用性。当前结果不能直接作为买卖指令，也尚未进行效果评估。

本地 `.env`、虚拟环境、运行数据和日志不纳入 Git。请勿提交 API 密钥、账户凭据或采集到的原始内容。

LLM 处理、数据保留和作者层面的分析仍需明确设计和允许范围；当前项目不提供实盘交易功能。
