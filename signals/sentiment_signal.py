#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 15:43
# software:Vscode
# brief :将每日情绪汇总转换为带覆盖标记的研究信号

import math


def build_research_signals(report, config):
    """
    将足够覆盖的新闻情绪转换为长仓或现金的研究假设。

    :param report: 每日币种报告
    :param config: 阈值和研究仓位上限配置
    :return: 币种信号字典列表，不含实盘指令
    """
    positive = config["positive_threshold"]
    negative = config["negative_threshold"]
    weight = config["max_symbol_weight"]
    if not -1 <= negative < positive <= 1 or not 0 <= weight <= 1:
        raise ValueError("研究信号阈值或仓位配置不合法")
    signals = []
    for coin in report["coins"]:
        score = coin["sentiment_score"]
        if coin["coverage"] != "sufficient" or score is None:
            direction, target, status = "unknown", None, "insufficient_data"
        else:
            if not math.isfinite(score) or not -1 <= score <= 1:
                raise ValueError("情绪评分应在 -1 至 1 之间")
            direction = "positive" if score >= positive else "negative" if score <= negative else "neutral"
            target = weight if direction == "positive" else 0.0
            status = "research_only"
        signals.append({
            "symbol": coin["symbol"], "as_of": report["as_of"],
            "status": status, "direction": direction, "sentiment_score": score,
            "target_weight": target, "usable_count": coin["usable_count"],
            "evidence_ids": [item["id"] for item in coin["evidence"]],
        })
    total_weight = sum(signal["target_weight"] or 0 for signal in signals)
    if total_weight > config["max_total_weight"] + 1e-9:
        raise ValueError("研究信号总仓位超过配置上限")
    return signals
