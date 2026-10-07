#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 15:42
# software:Vscode
# brief :读取并校验带时区的历史收盘行情

import json
import math
import os
from datetime import datetime, timezone


def parse_aware_timestamp(value):
    """校验时间并转换为 UTC。

    :param value: 带时区的 ISO 时间字符串
    :return: UTC 时间对象
    """
    if not isinstance(value, str):
        raise ValueError("时间必须是带时区的 ISO 字符串")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"无效 ISO 时间：{value}") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"时间缺少时区：{value}")
    return timestamp.astimezone(timezone.utc)


def validate_market_records(records):
    """校验历史行情并按币种及时间排序。

    :param records: 含 symbol、timestamp、close 的字典列表
    :return: 标准化行情列表，时间为 UTC ISO 字符串
    """
    if not isinstance(records, list):
        raise ValueError("历史行情 JSON 顶层必须为列表")
    normalized = []
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("每条行情必须为字典")
        symbol = record.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("行情 symbol 不能为空")
        symbol = symbol.strip().upper()
        timestamp = parse_aware_timestamp(record.get("timestamp"))
        close = record.get("close")
        if isinstance(close, bool) or not isinstance(close, (int, float)):
            raise ValueError(f"{symbol} close 必须是数值")
        if not math.isfinite(close) or close <= 0:
            raise ValueError(f"{symbol} close 必须是有限正数")
        key = (symbol, timestamp)
        if key in seen:
            raise ValueError(f"重复行情：{symbol} {timestamp.isoformat()}")
        seen.add(key)
        normalized.append({"symbol": symbol, "timestamp": timestamp.isoformat(), "close": float(close)})
    return sorted(normalized, key=lambda record: (record["symbol"], record["timestamp"]))


def load_market_data(path):
    """读取人工提供的历史行情，不联网也不生成替代数据。

    :param path: 历史 JSON 文件的绝对路径
    :return: 经过校验并排序的行情列表
    """
    path = os.fspath(path)
    if not os.path.isabs(path):
        raise ValueError("历史行情必须使用绝对路径")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"尚未提供历史行情文件：{path}；请准备真实收盘行情后再回测")
    with open(path, "r", encoding="utf-8-sig") as market_file:
        return validate_market_records(json.load(market_file))
