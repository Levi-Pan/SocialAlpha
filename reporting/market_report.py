#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 20:06
# software:Vscode
# brief :汇总已完成日线收盘价和每日变动并标记行情时效

import math
from datetime import datetime, timedelta, timezone


def _aware_time(value):
    """
    解析带有时区的观察时刻或日线结束时刻。

    :param value: datetime 或 ISO 时间字符串
    :return: UTC datetime，非法值返回 None
    """
    try:
        parsed_time = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed_time.astimezone(timezone.utc) if parsed_time.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _positive_number(value):
    """
    解析有限且为正的价格或时长。

    :param value: 待解析数字
    :return: 浮点数，非法值返回 None
    """
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def build_market_comparison(prices, symbols, as_of, config):
    """
    对指定币种汇总已完成日线，不使用未来价格或实时行情。

    :param prices: 包含 symbol、timestamp、close 的日线记录列表
    :param symbols: 待展示币种列表
    :param as_of: 带时区的观察时间
    :param config: 计价资产、行情有效期和期望日线间隔配置
    :return: 包含币种收盘价、日变动及数据状态的报告
    """
    observed_at = _aware_time(as_of)
    if observed_at is None:
        raise ValueError("行情观察时间必须包含有效时区")
    max_age_hours = _positive_number(config["max_age_hours"])
    expected_interval_hours = _positive_number(config["expected_interval_hours"])
    if max_age_hours is None or expected_interval_hours is None:
        raise ValueError("行情有效期和日线间隔必须为有限正数")
    tracked_symbols = list(dict.fromkeys(symbols))
    candles = {symbol: {} for symbol in tracked_symbols}
    rejected_rows = 0
    duplicate_rows = 0
    for row in prices:
        symbol = row.get("symbol")
        if symbol not in candles:
            continue
        timestamp = _aware_time(row.get("timestamp"))
        close = _positive_number(row.get("close"))
        if timestamp is None or close is None:
            rejected_rows += 1
            continue
        if timestamp > observed_at:
            continue
        if timestamp in candles[symbol]:
            if candles[symbol][timestamp] != close:
                raise ValueError(f"{symbol} 同一日线时刻存在冲突收盘价：{timestamp.isoformat()}")
            duplicate_rows += 1
            continue
        candles[symbol][timestamp] = close
    coins = []
    expected_interval = timedelta(hours=expected_interval_hours)
    for symbol in tracked_symbols:
        ordered_candles = sorted(candles[symbol].items())
        coin = {"symbol": symbol, "latest_close": None, "latest_timestamp": None, "day_change_percent": None, "status": "missing_data"}
        if ordered_candles:
            latest_timestamp, latest_close = ordered_candles[-1]
            coin.update(latest_close=latest_close, latest_timestamp=latest_timestamp.isoformat())
            if observed_at - latest_timestamp > timedelta(hours=max_age_hours):
                coin["status"] = "stale"
            elif len(ordered_candles) < 2 or latest_timestamp - ordered_candles[-2][0] != expected_interval:
                coin["status"] = "insufficient_history"
            else:
                coin.update(status="ready", day_change_percent=(latest_close / ordered_candles[-2][1] - 1) * 100)
        coins.append(coin)
    return {
        "as_of": observed_at.isoformat(),
        "source": "Binance spot",
        "quote_asset": config["quote_asset"],
        "coins": coins,
        "rejected_rows": rejected_rows,
        "duplicate_rows": duplicate_rows,
        "methodology": {
            "max_age_hours": max_age_hours,
            "expected_interval_hours": expected_interval_hours,
            "price": "价格是最近一根已完成 UTC 日线的收盘价，不是实时行情；timestamp 为日线结束后的首个时刻。",
            "change": "日变动仅使用连续两根已完成日线的收盘价；缺失、间隔不连续或过期时不计算。",
            "quote": f"价格计价单位为 {config['quote_asset']}；USDT 不等同于 USD。",
        },
    }


def render_market_comparison_markdown(comparison):
    """
    将日线行情报告渲染为 Markdown 表格。

    :param comparison: build_market_comparison 返回的报告
    :return: 标有计价单位及行情时效的 Markdown 文本
    """
    quote_asset = str(comparison["quote_asset"]).replace("|", "\\|")
    status_labels = {"ready": "可用", "insufficient_history": "历史不足或日线不连续", "stale": "行情过期", "missing_data": "无行情"}
    lines = ["## 已完成日线行情", "", f"来源：{comparison['source']}；观察时刻：{comparison['as_of']}", "", f"| 币种 | 最近收盘价（{quote_asset}） | 日变动 | 日线完成时刻（UTC） | 状态 |", "| --- | ---: | ---: | --- | --- |"]
    for coin in comparison["coins"]:
        close_text = "—" if coin["latest_close"] is None else f"{coin['latest_close']:,.8f}".rstrip("0").rstrip(".")
        change_text = "—" if coin["day_change_percent"] is None else f"{coin['day_change_percent']:+.2f}%"
        symbol = str(coin["symbol"]).replace("|", "\\|")
        lines.append(f"| {symbol} | {close_text} | {change_text} | {coin['latest_timestamp'] or '—'} | {status_labels[coin['status']]} |")
    lines.extend(["", comparison["methodology"]["price"], "", comparison["methodology"]["change"], "", comparison["methodology"]["quote"], ""])
    return "\n".join(lines)
