#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 15:43
# software:Vscode
# brief :统一启动新闻研究报告信号及可选回测流程

import argparse
import logging
import os
import sys


PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_PATH not in sys.path:
    sys.path.insert(0, PROJECT_PATH)

from pipeline.research_pipeline import run_pipeline
from private_module.private_log import configure_logging


logger = logging.getLogger(__name__)


def main(argv=None):
    """
    解析启动参数并调用研究流程。

    :param argv: 参数列表，为空时读取命令行
    :return: 无
    """
    configure_logging()
    parser = argparse.ArgumentParser(description="SocialAlpha 新闻研究框架")
    parser.add_argument("--refresh-news", action="store_true", help="刷新公开新闻 RSS")
    parser.add_argument("--analyze", action="store_true", help="调用 LLM 分析新增候选，会产生 API 消耗")
    parser.add_argument("--limit", type=int, default=None, help="本次最多请求模型条数")
    parser.add_argument("--backtest", action="store_true", help="使用已保存的行情和时点信号回测")
    parser.add_argument("--refresh-market", action="store_true", help="采集六币种已完成日线，不消耗 LLM API")
    args = parser.parse_args(argv)
    try:
        run_pipeline(args.refresh_news, args.analyze, args.backtest, args.limit, args.refresh_market)
    except (ValueError, TypeError, KeyError, RuntimeError, OSError):
        logger.error("研究流程失败", exc_info=True)
        raise SystemExit(1)



if __name__ == "__main__":
    main()
