#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/7 10:50
# software:Vscode
# brief :编排行情采集、历史合并校验和原子保存

import logging
import os

import requests

from market_data.market_fetcher import fetch_daily_market
from market_data.market_loader import validate_market_records
from private_module.project_config import load_project_config
from private_module.project_io import project_path, read_json, write_json_atomic


logger = logging.getLogger(__name__)


def run_market_pipeline():
    """
    获取配置币种的真实日线，全源成功后才合并并原子保存。

    :return: 已保存的行情字典列表
    """
    pipeline_config = load_project_config("pipeline")
    market_config = load_project_config("market")
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

