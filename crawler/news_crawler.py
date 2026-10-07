#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 15:03
# software:Vscode
# brief :采集公开新闻 RSS 并保留来源及采集时间

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests


logger = logging.getLogger(__name__)


def parse_news_feed(feed_content, source, fetched_at, limit):
    """
    解析 RSS 2.0 新闻条目，不访问文章全文。

    :param feed_content: RSS XML 字节数据
    :param source: 来源标识
    :param fetched_at: UTC 采集时间字符串
    :param limit: 当前来源最多读取的条目数量
    :return: 原始新闻字典列表
    """
    if b"<!DOCTYPE" in feed_content.upper() or b"<!ENTITY" in feed_content.upper():
        raise ValueError("RSS 含不支持的 DTD 或实体声明")
    root = ET.fromstring(feed_content)
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("新闻源不是支持的 RSS 2.0 格式")
    records = []
    for item in root.findall("./channel/item")[:limit]:
        records.append({
            "platform": "news",
            "source": source,
            "author": item.findtext("author") or item.findtext("{http://purl.org/dc/elements/1.1/}creator"),
            "title": item.findtext("title", ""),
            "content": item.findtext("description", ""),
            "publish_time": item.findtext("pubDate"),
            "fetched_at": fetched_at,
            "url": item.findtext("link", ""),
            "score": None,
            "comments": None,
        })
    return records


def fetch_news_posts(config):
    """
    读取配置中的新闻源，单源失败继续采集，全部失败则报错。

    :param config: 新闻源、请求限制和超时配置
    :return: 原始新闻字典列表
    """
    records = []
    successful_sources = 0
    with requests.Session() as session:
        session.headers.update({"User-Agent": config["user_agent"]})
        for feed in config["feeds"]:
            try:
                with session.get(feed["url"], timeout=config["timeout"], stream=True) as response:
                    response.raise_for_status()
                    chunks = []
                    total_bytes = 0
                    for chunk in response.iter_content(chunk_size=65536):
                        total_bytes += len(chunk)
                        if total_bytes > config["max_feed_bytes"]:
                            raise ValueError("新闻源响应超过大小限制")
                        chunks.append(chunk)
                fetched_at = datetime.now(timezone.utc).isoformat()
                source_records = parse_news_feed(
                    b"".join(chunks), feed["source"], fetched_at, config["limit_per_source"]
                )
                records.extend(source_records)
                successful_sources += 1
                logger.info("来源 %s：采集 %s 条新闻", feed["source"], len(source_records))
            except (requests.RequestException, ET.ParseError, ValueError):
                logger.error("新闻源 %s 采集失败", feed["source"], exc_info=True)
    if not successful_sources:
        raise RuntimeError("所有新闻源采集失败，本次不生成输出文件")
    return records
