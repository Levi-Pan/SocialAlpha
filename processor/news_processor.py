#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 15:03
# software:Vscode
# brief :清洗新闻文本并统一时间、识别币种和去重

import hashlib
import html
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


logger = logging.getLogger(__name__)


class NewsTextParser(HTMLParser):
    """提取 HTML 文本，忽略脚本与样式内容，无继承业务方法需要修改。"""

    def __init__(self):
        """
        初始化文本片段和忽略状态。

        :return: 无
        """
        super().__init__(convert_charrefs=True)
        self.fragments = []
        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        """
        处理标签并标记脚本或样式区域。

        :param tag: 标签名
        :param attrs: 标签属性
        :return: 无
        """
        if tag in ("script", "style"):
            self.ignored_depth += 1
        if not self.ignored_depth:
            self.fragments.append(" ")

    def handle_endtag(self, tag):
        """
        结束忽略区域并分隔文本。

        :param tag: 标签名
        :return: 无
        """
        if tag in ("script", "style") and self.ignored_depth:
            self.ignored_depth -= 1
        if not self.ignored_depth:
            self.fragments.append(" ")

    def handle_data(self, data):
        """
        收集可见文本。

        :param data: 文本片段
        :return: 无
        """
        if not self.ignored_depth:
            self.fragments.append(data)


def clean_text(text):
    """
    去除 HTML 标签并折叠空白字符。

    :param text: 原始文本或空值
    :return: 清洗后的文本
    """
    parser = NewsTextParser()
    parser.feed(text or "")
    parser.close()
    return re.sub(r"\s+", " ", html.unescape("".join(parser.fragments))).strip()


def normalize_url(url):
    """
    标准化新闻链接并移除常见跟踪参数，保留业务查询参数。

    :param url: 原始链接
    :return: 标准化 HTTP 或 HTTPS 链接
    """
    parts = urlsplit((url or "").strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError("新闻链接缺少有效 HTTP/HTTPS 地址")
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in ("fbclid", "gclid")]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(sorted(query)), ""))


def clean_news_posts(records, symbol_aliases):
    """
    统一新闻结构，按规范链接去重，识别币种并转换 UTC 时间。

    :param records: 原始新闻列表
    :param symbol_aliases: 币种与别名配置
    :return: 清洗后的新闻列表
    """
    cleaned = []
    seen_urls = set()
    for record in records:
        try:
            title = clean_text(record.get("title"))
            if not title:
                raise ValueError("新闻标题为空")
            url = normalize_url(record.get("url"))
            if url in seen_urls:
                continue
            try:
                published = datetime.fromisoformat((record.get("publish_time") or "").replace("Z", "+00:00"))
            except ValueError:
                published = parsedate_to_datetime(record.get("publish_time") or "")
            if published.tzinfo is None:
                raise ValueError("发布时间没有时区")
            content = clean_text(record.get("content"))
            mention_symbol = [symbol for symbol, aliases in symbol_aliases.items()
                              if any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)",
                                               title + " " + content, re.IGNORECASE) for alias in aliases)]
            cleaned.append({
                "id": hashlib.sha256(url.encode("utf-8")).hexdigest(),
                "platform": record.get("platform", "news"),
                "content_kind": record.get("content_kind", "media"),
                "source": record["source"],
                "author": clean_text(record.get("author")) or None,
                "title": title,
                "content": content,
                "publish_time": published.astimezone(timezone.utc).isoformat(),
                "fetched_at": record["fetched_at"],
                "score": record.get("score"),
                "comments": record.get("comments"),
                "url": url,
                "mention_symbol": mention_symbol,
            })
            seen_urls.add(url)
        except (ValueError, TypeError, KeyError, OverflowError):
            logger.warning("跳过无效新闻条目，来源：%s", record.get("source"), exc_info=True)
    logger.info("清洗完成：原始 %s 条，保留 %s 条", len(records), len(cleaned))
    return cleaned
