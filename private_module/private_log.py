#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/7 10:49
# software:Vscode
# brief :统一命令行日志等级、输出格式和终端编码

import logging
import sys


def configure_logging(level=logging.INFO):
    """
    在启动入口设置日志和 UTF-8 终端输出，业务模块不重复初始化。

    :param level: 标准日志等级
    :return: 无
    """
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")
