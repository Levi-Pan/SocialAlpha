#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 15:42
# software:Vscode
# brief :根据已知时间的情绪信号执行独立币种历史回测

import math

from market_data.market_loader import parse_aware_timestamp, validate_market_records


def _validate_signals(signals, symbols):
    """校验历史信号并按可用时间排序。

    :param signals: 含 symbol、as_of、target_weight 的历史列表
    :param symbols: 允许回测的币种列表
    :return: 每个币种对应的已排序信号列表
    """
    if not isinstance(signals, list):
        raise ValueError("历史信号必须为列表")
    grouped = {symbol: [] for symbol in symbols}
    seen = set()
    for signal in signals:
        if not isinstance(signal, dict):
            raise ValueError("每条信号必须为字典")
        symbol = signal.get("symbol")
        if not isinstance(symbol, str):
            raise ValueError("信号 symbol 必须为字符串")
        symbol = symbol.strip().upper()
        if symbol not in grouped:
            raise ValueError(f"信号币种未在配置中：{symbol}")
        as_of = parse_aware_timestamp(signal.get("as_of"))
        target_weight = signal.get("target_weight")
        if isinstance(target_weight, bool) or not isinstance(target_weight, (int, float)):
            raise ValueError("信号 target_weight 必须为数值")
        if not math.isfinite(target_weight) or not 0 <= target_weight <= 1:
            raise ValueError("信号 target_weight 必须在 0 到 1 之间")
        if (symbol, as_of) in seen:
            raise ValueError(f"同一币种可用时间有重复信号：{symbol} {as_of.isoformat()}")
        seen.add((symbol, as_of))
        grouped[symbol].append({"as_of": as_of, "target_weight": float(target_weight)})
    for symbol in grouped:
        grouped[symbol].sort(key=lambda signal: signal["as_of"])
    return grouped


def _simulate_symbol(bars, signals, cost_rate):
    """以严格晚于信号可用时间的收盘价调仓。

    :param bars: 单币种按时间排序的行情
    :param signals: 单币种按可用时间排序的信号
    :param cost_rate: 手续费和滑点的单边合计比例
    :return: 初始净值为 1 的独立多头现金回测结果
    """
    equity = 1.0
    current_weight = 0.0
    target_weight = 0.0
    signal_index = 0
    trades = 0
    cumulative_cost = 0.0
    peak_equity = 1.0
    max_drawdown = 0.0
    equity_curve = [{"timestamp": bars[0]["timestamp"], "equity": equity}]
    for bar_index in range(len(bars) - 1):
        timestamp = parse_aware_timestamp(bars[bar_index]["timestamp"])
        while signal_index < len(signals) and signals[signal_index]["as_of"] < timestamp:
            target_weight = signals[signal_index]["target_weight"]
            signal_index += 1
        risky_value = equity * current_weight
        desired_difference = target_weight * equity - risky_value
        # 求解费用后的目标权重，避免从现金重复扣费导致满仓现金为负。
        denominator = 1 + cost_rate * target_weight if desired_difference >= 0 else 1 - cost_rate * target_weight
        cost = cost_rate * abs(desired_difference) / denominator
        turnover_value = abs(target_weight * (equity - cost) - risky_value)
        if turnover_value > 1e-12:
            trades += 1
        cumulative_cost += cost
        equity -= cost
        peak_equity = max(peak_equity, equity)
        max_drawdown = max(max_drawdown, 1 - equity / peak_equity)
        price_return = bars[bar_index + 1]["close"] / bars[bar_index]["close"] - 1
        portfolio_growth = 1 + target_weight * price_return
        equity *= portfolio_growth
        current_weight = target_weight * (1 + price_return) / portfolio_growth
        peak_equity = max(peak_equity, equity)
        max_drawdown = max(max_drawdown, 1 - equity / peak_equity)
        equity_curve.append({"timestamp": bars[bar_index + 1]["timestamp"], "equity": equity})
    return {
        "status": "ready", "bars": len(bars), "trades": trades,
        "total_return": equity - 1, "max_drawdown": max_drawdown,
        "costs": cumulative_cost, "equity_curve": equity_curve,
    }


def run_sentiment_backtest(signals, prices, config):
    """回测真实历史信号，缺少历史时不提供绩效数字。

    :param signals: 可用时间真实记录的历史信号列表
    :param prices: 历史收盘行情列表
    :param config: symbols、fee_bps、slippage_bps 配置
    :return: 每币种独立结果、状态与方法说明
    """
    symbols = config.get("symbols")
    if not isinstance(symbols, list) or not symbols or any(not isinstance(symbol, str) or not symbol.strip() for symbol in symbols):
        raise ValueError("回测配置 symbols 必须为非空币种列表")
    symbols = [symbol.strip().upper() for symbol in symbols]
    if len(set(symbols)) != len(symbols):
        raise ValueError("回测配置 symbols 不允许重复")
    fee_bps = config.get("fee_bps", 10)
    slippage_bps = config.get("slippage_bps", 5)
    for name, value in (("fee_bps", fee_bps), ("slippage_bps", slippage_bps)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} 必须为非负有限数值")
    cost_rate = (fee_bps + slippage_bps) / 10000
    if cost_rate >= 1:
        raise ValueError("单边交易成本必须小于 100%")
    normalized_prices = validate_market_records(prices)
    grouped_signals = _validate_signals(signals, symbols)
    results = {}
    for symbol in symbols:
        bars = [record for record in normalized_prices if record["symbol"] == symbol]
        if len(bars) < 2:
            results[symbol] = {"status": "insufficient_history", "bars": len(bars)}
        elif not grouped_signals[symbol]:
            results[symbol] = {"status": "no_signals", "bars": len(bars)}
        elif grouped_signals[symbol][0]["as_of"] >= parse_aware_timestamp(bars[-2]["timestamp"]):
            results[symbol] = {"status": "insufficient_signal_history", "bars": len(bars)}
        else:
            results[symbol] = _simulate_symbol(bars, grouped_signals[symbol], cost_rate)
    return {
        "status": "ready" if any(result["status"] == "ready" for result in results.values()) else "insufficient_history",
        "symbols": results,
        "cost_config": {"fee_bps": fee_bps, "slippage_bps": slippage_bps},
        "assumptions": [
            "研究用途，各币种独立从单位现金开始，不代表组合收益或实盘成交。",
            "仅做多或现金，无杠杆；现金收益为零，期末按收盘价估值不强制平仓。",
            "as_of 必须是信号真实可用时间；仅 as_of 严格早于调仓收盘时间的信号可用。",
            "每个输入收盘周期重设目标权重，费用和滑点按单边交易金额扣除；每日回测需输入每日收盘行情。",
            "首个有效信号前持有现金；随后沿用最新有效信号，数据不足的快照不改变研究仓位。",
            "需要历史时点真实可用的新闻和分析，今天生成的分析不能倒填历史可用时间。",
        ],
    }
