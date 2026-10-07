#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/7 10:50
# software:Vscode
# brief :编排新闻社媒采集、窗口内合并和结果保存

import logging
import os
from datetime import datetime, timedelta, timezone

from crawler.news_crawler import fetch_news_posts
from crawler.social_crawler import fetch_social_posts
from private_module.project_config import load_project_config
from private_module.project_io import project_path, read_json, write_json_atomic
from processor.news_processor import clean_news_posts


logger = logging.getLogger(__name__)


def run_news_pipeline():
    """
    执行新闻采集清洗并原子替换输出，失败时保留旧结果。

    :return: 清洗后的新闻列表
    """
    config = load_project_config("news")
    raw_records = []
    try:
        raw_records.extend(fetch_news_posts(config))
    except RuntimeError:
        logger.error("媒体来源全部失败，继续尝试社媒来源", exc_info=True)
    social_config = load_project_config("social")
    social_records, social_statuses = fetch_social_posts(social_config)
    raw_records.extend(social_records)
    write_json_atomic(project_path(social_config["status_parts"]), social_statuses)
    records = clean_news_posts(raw_records, config["symbol_aliases"])
    if not records:
        raise RuntimeError("本次无有效新闻，不覆盖旧结果")
    output_path = project_path(config["output_parts"])
    # 保留窗口内旧条目，避免订阅翻页或单源失败使已分析新闻消失。
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.get("retention_hours", 48))
    retained = {}
    if os.path.exists(output_path):
        for record in read_json(output_path):
            if datetime.fromisoformat(record["publish_time"]).astimezone(timezone.utc) >= cutoff:
                retained[record["id"]] = record
    for record in records:
        if datetime.fromisoformat(record["publish_time"]).astimezone(timezone.utc) >= cutoff:
            retained[record["id"]] = record
    records = sorted(retained.values(), key=lambda record: datetime.fromisoformat(record["publish_time"]), reverse=True)
    if not records:
        raise RuntimeError("窗口内无有效新闻，不覆盖旧结果")
    write_json_atomic(output_path, records)
    logger.info("已保存 %s 条新闻：%s", len(records), output_path)
    for symbol in config["symbol_aliases"]:
        media_count = sum(symbol in record["mention_symbol"] and record.get("content_kind", "media") != "community"
                          for record in records)
        community_count = sum(symbol in record["mention_symbol"] and record.get("content_kind") == "community"
                              for record in records)
        logger.info("%s：新闻与官方公告 %s 条；社区帖子 %s 条（尚未模型分析）", symbol, media_count, community_count)
    for record in records[:5]:
        logger.info("%s | %s | %s", record["publish_time"], record["mention_symbol"], record["title"])
    return records

