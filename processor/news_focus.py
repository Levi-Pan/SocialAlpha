#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 15:29
# software:Vscode
# brief :识别六币种相关新闻并标记重点对象和事件

import re
from datetime import datetime, timedelta, timezone


def contains_term(text, term):
    """
    识别独立英文关键词或中文短语，避免缩写匹配单词片段。

    :param text: 新闻文本
    :param term: 关键词
    :return: 是否命中
    """
    pattern = re.escape(term)
    if term.isascii():
        pattern = r"(?<!\w)" + pattern + r"(?!\w)"
    return re.search(pattern, text, re.IGNORECASE) is not None


def classify_news_focus(record, config, now=None):
    """
    标记重点对象、相关币种和重大事件，并过滤过期及无关新闻。

    :param record: 清洗后的新闻
    :param config: 包含 focus 和 max_age_hours 的分析配置
    :param now: 当前 UTC 时间，为空时自动获取
    :return: 规则筛选结果字典，priority 越小优先级越高
    """
    now = now or datetime.now(timezone.utc)
    published = datetime.fromisoformat(record["publish_time"])
    if published.tzinfo is None:
        raise ValueError("新闻发布时间必须含时区")
    title = record["title"]
    text = title + " " + record["content"]
    focus = config["focus"]
    symbols = [symbol for symbol, aliases in focus["symbol_aliases"].items()
               if any(contains_term(text, alias) for alias in aliases)]
    entities = [entity for entity, aliases in focus["priority_entities"].items()
                if any(contains_term(text, alias) for alias in aliases)]
    if "Strategy" not in entities and (any(
        re.search(r"\bStrategy\s+" + re.escape(term) + r"\b", text)
        for term in focus["strategy_company_terms"]
    ) or re.search(r"(?:^|[.!?]\s+)Strategy['’]s\b", text)):
        if any(contains_term(text, term) for term in focus["strategy_context"]):
            entities.append("Strategy")
    events = [term for term in focus["major_event_terms"] if contains_term(text, term)]
    if published > now + timedelta(minutes=5):
        reason = "future_publish_time"
    elif now - published > timedelta(hours=config["max_age_hours"]):
        reason = "outside_time_window"
    elif record.get("content_kind") == "community" and any(
        re.search(pattern, title, re.IGNORECASE) for pattern in config.get("community_exclude_patterns", [])
    ):
        reason = "low_information_community_post"
    elif entities:
        reason = "priority_entity"
    elif symbols and (events or not focus.get("require_major_event", False)):
        reason = "tracked_symbol_major_event" if events else "tracked_symbol_news"
    else:
        reason = "not_in_focus"
    selected = reason in ("priority_entity", "tracked_symbol_major_event", "tracked_symbol_news")
    return {"selected": selected, "reason": reason, "entities": entities, "symbols": symbols,
            "event_terms": events, "priority": 1,
            "attribution": {"community": "community_post", "official": "official_post"}.get(
                record.get("content_kind"), "media_report")}
