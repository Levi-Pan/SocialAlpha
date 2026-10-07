#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 20:05
# software:Vscode
# brief :采集六币种已完成日线并合并保存历史行情

import argparse
import logging
import os
import sys


PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_PATH not in sys.path:
    sys.path.insert(0, PROJECT_PATH)

from market_data.market_pipeline import run_market_pipeline
from private_module.private_log import configure_logging


def main(argv=None):
    """
    解析行情采集入口参数并启动业务流程。

    :param argv: 参数列表，为空时读取命令行
    :return: 无
    """
    configure_logging()
    argparse.ArgumentParser(description="采集并保存已完成日线行情").parse_args(argv)
    try:
        run_market_pipeline()
    except (RuntimeError, ValueError, TypeError, KeyError, OSError):
        logging.getLogger(__name__).error("日线行情流程失败", exc_info=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
