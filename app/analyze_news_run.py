#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 15:08
# software:Vscode
# brief :启动新闻情绪事件分析并提供离线预览参数

import argparse
import logging
import os
import sys


PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_PATH not in sys.path:
    sys.path.insert(0, PROJECT_PATH)

from processor.news_analyzer import run_analysis_pipeline


if __name__ == "__main__":
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="新闻情绪与事件分析")
    parser.add_argument("--limit", type=int, default=None, help="本次最多调用模型的新闻数量")
    parser.add_argument("--dry-run", action="store_true", help="离线检查，不调用模型、不写结果")
    args = parser.parse_args()
    try:
        run_analysis_pipeline(limit=args.limit, dry_run=args.dry_run)
    except (RuntimeError, ValueError, KeyError, TypeError, OSError):
        logging.getLogger(__name__).error("新闻分析失败", exc_info=True)
        raise SystemExit(1)
