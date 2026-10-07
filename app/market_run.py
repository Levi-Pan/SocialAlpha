#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 20:05
# software:Vscode
# brief :采集六币种已完成日线并合并保存历史行情

import logging
import os
import sys

import requests


PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_PATH not in sys.path:
    sys.path.insert(0, PROJECT_PATH)

from market_data.market_fetcher import fetch_daily_market
from market_data.market_loader import validate_market_records
from private_module.project_io import project_path, read_json, write_json_atomic


logger = logging.getLogger(__name__)


def run_market_pipeline():
    """
    获取配置币种的真实日线，全源成功后才合并并原子保存。

    :return: 已保存的行情字典列表
    """
    pipeline_config = read_json(project_path(["config", "pipeline_config.json"]))
    market_config = read_json(project_path(["config", "market_config.json"]))
    output_path = project_path(pipeline_config["market_parts"])
    try:
        new_records = fetch_daily_market(market_config, pipeline_config["symbols"])
    except requests.RequestException:
        logger.error("公共行情采集失败，保留原有行情文件", exc_info=True)
        raise RuntimeError("公共行情接口请求失败，请检查网络或接口访问权限") from None
    previous_records = read_json(output_path) if os.path.exists(output_path) else []
    validate_market_records(previous_records)
    merged = {(record["symbol"], record["timestamp"]): record for record in previous_records}
    merged.update({(record["symbol"], record["timestamp"]): record for record in new_records})
    records = sorted(merged.values(), key=lambda record: (record["symbol"], record["timestamp"]))
    validate_market_records(records)
    write_json_atomic(output_path, records)
    logger.info("已保存 %s 条已完成日线行情：%s", len(records), output_path)
    return records


if __name__ == "__main__":
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run_market_pipeline()
    except (ValueError, TypeError, KeyError, RuntimeError, OSError):
        logger.error("日线行情流程失败", exc_info=True)
        raise SystemExit(1)
