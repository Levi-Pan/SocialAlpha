#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 15:03
# software:Vscode
# brief :启动新闻采集清洗并保存本地 MVP 结果

import argparse
import logging
import os
import sys


PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_PATH not in sys.path:
    sys.path.insert(0, PROJECT_PATH)

from crawler.news_pipeline import run_news_pipeline
from private_module.private_log import configure_logging


def main(argv=None):
    """
    解析新闻采集入口参数并启动业务流程。

    :param argv: 参数列表，为空时读取命令行
    :return: 无
    """
    configure_logging()
    argparse.ArgumentParser(description="采集新闻与社媒公开来源").parse_args(argv)
    try:
        run_news_pipeline()
    except (RuntimeError, ValueError, TypeError, KeyError, OSError):
        logging.getLogger(__name__).error("新闻采集清洗失败", exc_info=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
