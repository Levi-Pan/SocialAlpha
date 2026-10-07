#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/7 10:21
# software:Vscode
# brief :采集币种社区订阅和官方公告并记录来源可用状态

import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser

import requests

from crawler.news_crawler import parse_news_feed
from private_module.project_config import load_local_environment


logger = logging.getLogger(__name__)


class TelegramMessageParser(HTMLParser):
    """提取公开频道文本与原帖时间；重写 HTMLParser 的标签和文本回调。"""

    def __init__(self, channel):
        """
        初始化频道消息解析状态。

        :param channel: 配置中的频道名称
        :return: 无
        """
        super().__init__(convert_charrefs=True)
        self.channel = channel
        self.messages = []
        self.current = None
        self.div_depth = 0
        self.text_depth = None

    def handle_starttag(self, tag, attrs):
        """
        标记消息正文和发布时间，忽略转发头、观看量及页面导航。

        :param tag: 标签名
        :param attrs: 标签属性列表
        :return: 无
        """
        attrs = dict(attrs)
        if tag == "div":
            self.div_depth += 1
        if attrs.get("data-post", "").startswith(self.channel + "/"):
            if self.current is not None:
                self.messages.append(self.current)
            self.current = {"post": attrs["data-post"], "fragments": [], "publish_time": None}
        if self.current is None:
            return
        if tag == "div" and "tgme_widget_message_text" in attrs.get("class", "").split():
            self.text_depth = self.div_depth
        if tag == "time" and attrs.get("datetime") and self.current["publish_time"] is None:
            self.current["publish_time"] = attrs["datetime"]
        if tag == "br" and self.text_depth is not None:
            self.current["fragments"].append("\n")

    def handle_endtag(self, tag):
        """
        结束正文区域，保持嵌套标签深度。

        :param tag: 标签名
        :return: 无
        """
        if tag == "div":
            if self.text_depth == self.div_depth:
                self.text_depth = None
            self.div_depth -= 1

    def handle_data(self, data):
        """
        只保存公告正文。

        :param data: 可见文本
        :return: 无
        """
        if self.current is not None and self.text_depth is not None:
            self.current["fragments"].append(data)


def parse_telegram_page(page, feed, fetched_at, limit):
    """
    解析公开 Telegram 频道，媒体无正文或缺少原始时间的消息跳过。

    :param page: 页面 HTML 文本
    :param feed: 频道及来源配置
    :param fetched_at: UTC 采集时间
    :param limit: 最大条数
    :return: 按原始发布时间倒序排列的记录
    """
    parser = TelegramMessageParser(feed["channel"])
    parser.feed(page)
    parser.close()
    messages = parser.messages + ([parser.current] if parser.current else [])
    records = []
    for message in messages:
        content = "".join(message["fragments"]).strip()
        if not content or not message["publish_time"]:
            continue
        records.append({"platform": feed["platform"], "source": feed["source"],
                        "content_kind": feed["content_kind"], "author": feed["channel"],
                        "title": content.splitlines()[0][:160], "content": content,
                        "publish_time": message["publish_time"], "fetched_at": fetched_at,
                        "url": feed["url"].split("/s/")[0] + "/" + message["post"],
                        "score": None, "comments": None})
    records.sort(key=lambda record: datetime.fromisoformat(record["publish_time"]), reverse=True)
    return records[:limit]


def read_public_source(session, feed, config):
    """
    有界读取公开来源，HTTP 错误交给调用层处理，不自动重试限流。

    :param session: 公共 HTTP 会话
    :param feed: 来源配置
    :param config: 超时与响应大小限制
    :return: 响应字节及编码
    """
    with session.get(feed["url"], timeout=config["timeout"], stream=True) as response:
        response.raise_for_status()
        chunks = []
        total_bytes = 0
        for chunk in response.iter_content(chunk_size=65536):
            total_bytes += len(chunk)
            if total_bytes > config["max_response_bytes"]:
                raise ValueError("社媒来源响应超过大小限制")
            chunks.append(chunk)
        return b"".join(chunks), response.encoding or "utf-8"


def fetch_x_account(session, account, config, x_config, bearer_token, fetched_at):
    """
    通过官方只读 API 获取账号原创帖子，不抓取转发或回复。

    :param session: HTTP 会话
    :param account: 官方账号名称
    :param config: 超时配置
    :param x_config: X 接口配置
    :param bearer_token: 从环境变量读取的访问令牌
    :param fetched_at: UTC 采集时间
    :return: 社媒记录列表
    """
    if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", account):
        raise ValueError("X 账号格式无效")
    headers = {"Authorization": "Bearer " + bearer_token}
    response = session.get(x_config["api_base_url"] + "/users/by/username/" + account,
                           headers=headers, timeout=config["timeout"])
    response.raise_for_status()
    user_id = response.json()["data"]["id"]
    response = session.get(x_config["api_base_url"] + "/users/" + user_id + "/tweets",
                           headers=headers, params={"max_results": x_config["max_results"],
                                                    "post.fields": "created_at", "exclude": "retweets,replies"},
                           timeout=config["timeout"])
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise ValueError("X 返回接口错误，未使用部分结果")
    return [{"platform": "x", "source": "x_" + account, "content_kind": "official",
             "author": account, "title": post["text"].splitlines()[0][:160], "content": post["text"],
             "publish_time": post["created_at"], "fetched_at": fetched_at,
             "url": x_config["post_base_url"] + "/" + account + "/status/" + post["id"],
             "score": None, "comments": None} for post in payload.get("data", [])]


def fetch_social_posts(config):
    """
    独立采集各社媒来源，失败记录状态，不阻断其他来源或输出虚构帖子。

    :param config: 社媒来源及请求配置
    :return: 记录列表和包含原始采集时间的来源状态列表
    """
    if not config.get("enabled", True):
        return [], []
    records = []
    statuses = []
    fetched_at = datetime.now(timezone.utc).isoformat()
    with requests.Session() as session:
        session.headers.update({"User-Agent": config["user_agent"]})
        for feed in config["feeds"] + config["telegram_channels"]:
            try:
                content, encoding = read_public_source(session, feed, config)
                if feed["platform"] == "telegram":
                    source_records = parse_telegram_page(content.decode(encoding), feed, fetched_at,
                                                         config["limit_per_source"])
                else:
                    source_records = parse_news_feed(content, feed["source"], fetched_at,
                                                     config["limit_per_source"])
                    for record in source_records:
                        record.update(platform=feed["platform"], content_kind=feed["content_kind"])
                if not source_records:
                    raise ValueError("来源没有可解析的文本条目")
                records.extend(source_records)
                statuses.append({"source": feed["source"], "status": "success", "count": len(source_records),
                                 "latest_publish_time": max(record["publish_time"] for record in source_records),
                                 "fetched_at": fetched_at})
                logger.info("社媒来源 %s：采集 %s 条", feed["source"], len(source_records))
            except (requests.RequestException, ET.ParseError, ValueError, KeyError, TypeError) as error:
                statuses.append({"source": feed["source"], "status": "failed", "count": 0,
                                 "http_status": getattr(getattr(error, "response", None), "status_code", None),
                                 "fetched_at": fetched_at})
                logger.error("社媒来源 %s 采集失败", feed["source"], exc_info=True)
        x_config = config["x"]
        load_local_environment()
        bearer_token = os.getenv(x_config["bearer_token_env"], "").strip()
        if not x_config["enabled"] or not bearer_token:
            statuses.append({"source": "x", "status": "disabled" if not x_config["enabled"] else "missing_credentials",
                             "count": 0, "fetched_at": fetched_at})
            logger.info("X 官方 API 已跳过：%s", "配置未启用" if not x_config["enabled"] else "缺少访问令牌")
        else:
            for account in x_config["accounts"]:
                try:
                    source_records = fetch_x_account(session, account, config, x_config, bearer_token, fetched_at)
                    records.extend(source_records)
                    statuses.append({"source": "x_" + account, "status": "success", "count": len(source_records),
                                     "fetched_at": fetched_at})
                except (requests.RequestException, ValueError, KeyError, TypeError):
                    statuses.append({"source": "x_" + account, "status": "failed", "count": 0, "fetched_at": fetched_at})
                    logger.error("X 来源 %s 采集失败", account, exc_info=True)
    return records, statuses
