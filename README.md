# SocialAlpha

SocialAlpha 是一个开发中的 Python 项目，计划结合社交媒体、新闻和加密货币行情，探索文本清洗、情绪与事件分析、实验性交易信号、回测和可视化。

## 当前实现

- `crawler/reddit_crawler.py`：手动获取 r/Bitcoin 的热门帖子，默认最多 20 条，输出前 5 条。
- 抓取字段包括作者、标题、正文、评分、评论数量、发布时间和链接；当前不抓取评论正文。
- 清洗、用户分析、LLM 分析、交易信号和回测尚未实现。

## 运行

在项目目录安装依赖并运行：

```powershell
python -m pip install -r requirements.txt
python crawler/reddit_crawler.py
```

当前原型使用匿名 Reddit JSON 接口，可能返回 `403 Blocked`。运行说明不代表抓取已经可用；后续需要确认获准的数据访问方式，并按审批结果接入认证。

## 配置和数据

本地 `.env`、虚拟环境、运行数据和日志不纳入 Git。请勿提交 API 密钥、账户凭据或采集到的原始内容。

LLM 处理、数据保留和作者层面的分析仍需明确设计和允许范围；当前项目不提供实盘交易功能。
