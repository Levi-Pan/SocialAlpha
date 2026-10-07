#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 20:05
# software:Vscode
# brief :采集币安公开日线并剔除尚未收盘的行情

import math
from datetime import datetime, timezone

import requests


def _finite_number(value, field, positive=False):
    """校验 API 返回的价格或成交量。

    :param value: 数字或数字字符串
    :param field: 字段名称
    :param positive: 是否要求严格正数
    :return: 有限浮点数
    """
    if isinstance(value, bool):
        raise ValueError(f"行情 {field} 不能为布尔值")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"行情 {field} 不是有效数字") from error
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(f"行情 {field} 必须为有限{'正数' if positive else '非负数'}")
    return number


def _parse_daily_klines(rows, symbol, quote_asset, available_at, fetched_at):
    """解析完整 UTC 日线，不把开盘时间当成收盘信息可用时间。

    :param rows: 币安 K 线数组列表
    :param symbol: 基础资产简称
    :param quote_asset: 报价资产简称
    :param available_at: 交易所服务器参考时间
    :param fetched_at: 实际采集时间
    :return: 时间排序后的已收盘日线字典列表
    """
    if not isinstance(rows, list):
        raise ValueError(f"{symbol} 日线响应必须为列表")
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, list) or len(row) < 8:
            raise ValueError(f"{symbol} 日线字段不足")
        if any(isinstance(row[index], bool) or not isinstance(row[index], int) for index in (0, 6)):
            raise ValueError(f"{symbol} 日线时间必须为整数毫秒")
        if row[0] < 0 or row[0] % 86400000 != 0 or row[6] + 1 - row[0] != 86400000:
            raise ValueError(f"{symbol} 行情不是完整 UTC 日线时间区间")
        period_end = datetime.fromtimestamp((row[6] + 1) / 1000, tz=timezone.utc)
        if period_end in seen:
            raise ValueError(f"{symbol} 日线时间重复：{period_end.isoformat()}")
        seen.add(period_end)
        prices = {name: _finite_number(row[index], name, positive=True) for index, name in enumerate(("open", "high", "low", "close"), start=1)}
        volume = _finite_number(row[5], "volume")
        quote_volume = _finite_number(row[7], "quote_volume")
        if not prices["low"] <= min(prices["open"], prices["close"]) <= max(prices["open"], prices["close"]) <= prices["high"]:
            raise ValueError(f"{symbol} 日线 OHLC 高低价不一致")
        if period_end <= available_at:
            result.append({
                "symbol": symbol, "timestamp": period_end.isoformat(), **prices,
                "volume": volume, "quote_volume": quote_volume,
                "quote_asset": quote_asset, "source": "binance_spot",
                "fetched_at": fetched_at.isoformat(),
            })
    return sorted(result, key=lambda record: record["timestamp"])


def fetch_daily_market(config, symbols, now=None):
    """获取各币种最近完整日线，任一失败则整次报错并由调用方保留旧文件。

    :param config: 公共行情地址、日线周期、历史天数、超时和 User-Agent 配置
    :param symbols: 基础资产简称列表，如 BTC、ETH
    :param now: 测试用带时区参考时间，默认请求交易所服务器时间
    :return: 按币种和收盘可用时间排序的日线列表，不写文件
    """
    history_days = config["history_days"]
    if isinstance(history_days, bool) or not isinstance(history_days, int) or not 1 <= history_days <= 999:
        raise ValueError("history_days 必须为 1 到 999 的整数")
    if config["interval"] != "1d":
        raise ValueError("当前采集器仅支持 UTC 1d 日线")
    if config["klines_path"] != "/api/v3/klines" or config["time_path"] != "/api/v3/time":
        raise ValueError("行情采集仅允许公开 K 线与服务器时间接口")
    if not isinstance(symbols, list) or not symbols or any(not isinstance(symbol, str) or not symbol.strip().isascii() or not symbol.strip().isalnum() for symbol in symbols):
        raise ValueError("symbols 必须是非空资产简称列表")
    symbols = [symbol.strip().upper() for symbol in symbols]
    if len(set(symbols)) != len(symbols):
        raise ValueError("symbols 不允许重复")
    quote_asset = config["quote_asset"]
    if not isinstance(quote_asset, str) or not quote_asset.isascii() or not quote_asset.isalnum():
        raise ValueError("quote_asset 必须为资产简称")
    quote_asset = quote_asset.upper()
    base_url = config["base_url"].rstrip("/")
    fetched_at = datetime.now(timezone.utc)
    with requests.Session() as session:
        session.headers.update({"User-Agent": config["user_agent"]})
        if now is None:
            response = session.get(base_url + config["time_path"], timeout=config["timeout"])
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or isinstance(payload.get("serverTime"), bool) or not isinstance(payload.get("serverTime"), int) or payload["serverTime"] < 0:
                raise ValueError("服务器时间响应缺少有效 serverTime")
            available_at = datetime.fromtimestamp(payload["serverTime"] / 1000, tz=timezone.utc)
        else:
            if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("参考时间 now 必须为带时区 datetime")
            available_at = now.astimezone(timezone.utc)
        records = []
        for symbol in symbols:
            response = session.get(
                base_url + config["klines_path"],
                params={"symbol": symbol + quote_asset, "interval": config["interval"], "limit": history_days + 1, "endTime": int(available_at.timestamp() * 1000), "timeZone": "0"},
                timeout=config["timeout"],
            )
            response.raise_for_status()
            daily_records = _parse_daily_klines(response.json(), symbol, quote_asset, available_at, fetched_at)
            if not daily_records:
                raise ValueError(f"{symbol} 没有返回任何已收盘日线，本次不覆盖旧行情")
            records.extend(daily_records[-history_days:])
    return sorted(records, key=lambda record: (record["symbol"], record["timestamp"]))
