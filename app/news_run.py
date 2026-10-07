#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 15:03
# software:Vscode
# brief :启动新闻采集清洗并保存本地 MVP 结果

import json
import logging
import os
import sys
import tempfile


PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_PATH not in sys.path:
    sys.path.insert(0, PROJECT_PATH)

from crawler.news_crawler import fetch_news_posts
from processor.news_processor import clean_news_posts


logger = logging.getLogger(__name__)


def run_news_pipeline():
    """
    执行新闻采集清洗并原子替换输出，失败时保留旧结果。

    :return: 清洗后的新闻列表
    """
    with open(os.path.join(PROJECT_PATH, "config", "news_config.json"), encoding="utf-8") as config_file:
        config = json.load(config_file)
    records = clean_news_posts(fetch_news_posts(config), config["symbol_aliases"])
    if not records:
        raise RuntimeError("本次无有效新闻，不覆盖旧结果")
    output_path = os.path.join(PROJECT_PATH, *config["output_parts"])
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(output_path),
                                         suffix=".tmp", delete=False) as output_file:
            temporary_path = output_file.name
            json.dump(records, output_file, ensure_ascii=False, indent=2)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)
    logger.info("已保存 %s 条新闻：%s", len(records), output_path)
    for record in records[:5]:
        logger.info("%s | %s | %s", record["publish_time"], record["mention_symbol"], record["title"])
    return records


if __name__ == "__main__":
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run_news_pipeline()
    except (RuntimeError, ValueError, KeyError, OSError):
        logger.error("新闻采集清洗失败", exc_info=True)
        raise SystemExit(1)
