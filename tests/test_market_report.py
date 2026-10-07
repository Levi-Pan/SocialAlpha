#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 20:06
# software:Vscode
# brief :验证日线行情报告的时间边界、连续性和计价单位

import unittest

from reporting.market_report import build_market_comparison, render_market_comparison_markdown


class MarketReportTests(unittest.TestCase):
    """验证行情汇总只使用可知且有效的完整日线。"""

    def setUp(self):
        """
        创建共享行情配置。

        :return: 无
        """
        self.config = {"quote_asset": "USDT", "max_age_hours": 36, "expected_interval_hours": 24}
        self.as_of = "2026-10-06T12:00:00+00:00"
        self.prices = [
            {"symbol": "BTC", "timestamp": "2026-10-05T00:00:00Z", "close": 100},
            {"symbol": "BTC", "timestamp": "2026-10-06T00:00:00Z", "close": 110},
        ]

    def test_future_candle_is_excluded(self):
        """
        验证未来结束的日线不会改变当前收盘价。

        :return: 无
        """
        prices = self.prices + [{"symbol": "BTC", "timestamp": "2026-10-07T00:00:00Z", "close": 10000}]
        report = build_market_comparison(prices, ["BTC"], self.as_of, self.config)
        self.assertEqual(report["coins"][0]["latest_close"], 110)
        self.assertEqual(report["coins"][0]["status"], "ready")
        self.assertAlmostEqual(report["coins"][0]["day_change_percent"], 10)

    def test_gap_has_no_daily_return(self):
        """
        验证跨越缺失日线的变动不能标为每日变动。

        :return: 无
        """
        prices = [dict(self.prices[0], timestamp="2026-10-04T00:00:00Z"), self.prices[1]]
        coin = build_market_comparison(prices, ["BTC"], self.as_of, self.config)["coins"][0]
        self.assertEqual(coin["status"], "insufficient_history")
        self.assertIsNone(coin["day_change_percent"])

    def test_stale_and_missing_are_explicit(self):
        """
        验证过期行情和缺失币种不产生当前有效变动。

        :return: 无
        """
        report = build_market_comparison(self.prices, ["BTC", "ETH"], "2026-10-08T00:00:00Z", self.config)
        self.assertEqual(report["coins"][0]["status"], "stale")
        self.assertIsNone(report["coins"][0]["day_change_percent"])
        self.assertEqual(report["coins"][1]["status"], "missing_data")
        self.assertIsNone(report["coins"][1]["latest_close"])

    def test_duplicate_invalid_and_quote_labels(self):
        """
        验证重复、非法数据不增加历史，且报告明确 USDT 单位。

        :return: 无
        """
        prices = self.prices + [self.prices[1], {"symbol": "BTC", "timestamp": "2026-10-04T00:00:00Z", "close": -1}]
        report = build_market_comparison(prices, ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB"], self.as_of, self.config)
        self.assertEqual(len(report["coins"]), 6)
        self.assertEqual(report["duplicate_rows"], 1)
        self.assertEqual(report["rejected_rows"], 1)
        self.assertIn("最近收盘价（USDT）", render_market_comparison_markdown(report))
        self.assertIn("不是实时行情", render_market_comparison_markdown(report))

    def test_conflicting_duplicate_is_rejected(self):
        """
        验证同一完成时刻的冲突价格显式报错。

        :return: 无
        """
        with self.assertRaises(ValueError):
            build_market_comparison(self.prices + [dict(self.prices[1], close=120)], ["BTC"], self.as_of, self.config)

    def test_one_candle_and_naive_time(self):
        """
        验证单根日线没有收益，缺少时区的时间不可使用。

        :return: 无
        """
        coin = build_market_comparison(self.prices[-1:], ["BTC"], self.as_of, self.config)["coins"][0]
        self.assertEqual(coin["status"], "insufficient_history")
        self.assertIsNone(coin["day_change_percent"])
        with self.assertRaises(ValueError):
            build_market_comparison(self.prices, ["BTC"], "2026-10-06T12:00:00", self.config)
