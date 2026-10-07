#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 15:42
# software:Vscode
# brief :验证历史回测时序约束与费用扣除

import copy
import unittest

from backtest.sentiment_backtest import run_sentiment_backtest
from market_data.market_loader import validate_market_records


class SentimentBacktestTest(unittest.TestCase):
    """使用人工行情测试边界，不生成项目运行数据。"""

    def setUp(self):
        """准备测试专用行情。

        :return: 无
        """
        self.config = {"symbols": ["BTC", "ETH"], "fee_bps": 0, "slippage_bps": 0}
        self.prices = [
            {"symbol": "BTC", "timestamp": "2026-10-01T00:00:00Z", "close": 100},
            {"symbol": "BTC", "timestamp": "2026-10-02T00:00:00Z", "close": 200},
            {"symbol": "BTC", "timestamp": "2026-10-03T00:00:00Z", "close": 300},
        ]

    def test_signal_at_close_waits_next_close(self):
        """验证等于收盘时间的信号无法吃到当期涨幅。

        :return: 无
        """
        signals = [{"symbol": "BTC", "as_of": "2026-10-01T00:00:00Z", "target_weight": 1}]
        result = run_sentiment_backtest(signals, self.prices, self.config)
        self.assertAlmostEqual(result["symbols"]["BTC"]["total_return"], 0.5)

    def test_full_allocation_cost_is_self_financing(self):
        """验证满仓扣费后不产生隐含负现金及重复调仓。

        :return: 无
        """
        self.config.update({"fee_bps": 10, "slippage_bps": 5})
        signals = [{"symbol": "BTC", "as_of": "2026-09-30T00:00:00Z", "target_weight": 1}]
        result = run_sentiment_backtest(signals, self.prices, self.config)["symbols"]["BTC"]
        self.assertAlmostEqual(result["total_return"], 3 / 1.0015 - 1)
        self.assertEqual(result["trades"], 1)
        self.assertAlmostEqual(result["costs"], 0.0015 / 1.0015)

    def test_future_and_missing_signals_have_no_performance(self):
        """未来及缺失信号不得输出伪造的零收益绩效。

        :return: 无
        """
        signals = [{"symbol": "BTC", "as_of": "2026-10-02T00:00:00Z", "target_weight": 1}]
        future = run_sentiment_backtest(signals, self.prices, self.config)["symbols"]["BTC"]
        missing = run_sentiment_backtest([], self.prices, self.config)["symbols"]["BTC"]
        self.assertEqual(future["status"], "insufficient_signal_history")
        self.assertEqual(missing["status"], "no_signals")
        self.assertNotIn("total_return", future)
        self.assertNotIn("total_return", missing)

    def test_weight_drift_rebalances_before_next_period(self):
        """半仓上涨后的持仓漂移应在下一期恢复目标权重。

        :return: 无
        """
        signals = [{"symbol": "BTC", "as_of": "2026-09-30T00:00:00Z", "target_weight": 0.5}]
        result = run_sentiment_backtest(signals, self.prices, self.config)["symbols"]["BTC"]
        self.assertAlmostEqual(result["total_return"], 1.5 * 1.25 - 1)
        self.assertEqual(result["trades"], 2)

    def test_market_data_rejects_duplicate_instants_and_naive_time(self):
        """不同偏移表示的同一时点不可重复，时间不得缺少时区。

        :return: 无
        """
        duplicate = copy.deepcopy(self.prices)
        duplicate.append({"symbol": "BTC", "timestamp": "2026-10-01T08:00:00+08:00", "close": 100})
        with self.assertRaises(ValueError):
            validate_market_records(duplicate)
        naive = copy.deepcopy(self.prices)
        naive[0]["timestamp"] = "2026-10-01T00:00:00"
        with self.assertRaises(ValueError):
            validate_market_records(naive)
