#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 20:05
# software:Vscode
# brief :离线验证日线采集时间边界、币种映射与失败策略

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import requests

from market_data.market_fetcher import fetch_daily_market


class MarketFetcherTest(unittest.TestCase):
    """模拟公共行情响应，所有测试均不联网。"""

    def setUp(self):
        """准备日线和配置样本。

        :return: 无
        """
        self.config = {
            "base_url": "https://data-api.binance.vision", "klines_path": "/api/v3/klines",
            "time_path": "/api/v3/time", "quote_asset": "USDT", "interval": "1d",
            "history_days": 2, "timeout": 20, "user_agent": "SocialAlpha-test",
        }
        self.now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
        self.open_ms = int(datetime(2026, 10, 4, tzinfo=timezone.utc).timestamp() * 1000)
        self.rows = [[self.open_ms + offset * 86400000, "100", "110", "90", "105", "10", self.open_ms + (offset + 1) * 86400000 - 1, "1050"] for offset in range(3)]

    def _response(self, payload):
        """构造成功响应。

        :param payload: 响应 JSON
        :return: HTTP 响应模拟对象
        """
        response = MagicMock()
        response.json.return_value = payload
        return response

    @patch("market_data.market_fetcher.requests.Session")
    def test_incomplete_excluded_and_close_boundary_used(self, session_class):
        """未完成日线不能出现，时间应为收盘毫秒的下一毫秒。

        :param session_class: 模拟会话类
        :return: 无
        """
        session = session_class.return_value.__enter__.return_value
        session.get.return_value = self._response(self.rows)
        records = fetch_daily_market(self.config, ["BTC"], now=self.now)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["timestamp"], "2026-10-05T00:00:00+00:00")
        self.assertEqual(records[-1]["timestamp"], "2026-10-06T00:00:00+00:00")
        self.assertEqual(records[0]["close"], 105)
        self.assertEqual(session.get.call_args.kwargs["params"]["limit"], 3)

    @patch("market_data.market_fetcher.requests.Session")
    def test_six_symbols_map_to_usdt_pairs(self, session_class):
        """六个资产均请求对应现货交易对。

        :param session_class: 模拟会话类
        :return: 无
        """
        session = session_class.return_value.__enter__.return_value
        session.get.return_value = self._response(self.rows)
        symbols = ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB"]
        records = fetch_daily_market(self.config, symbols, now=self.now)
        self.assertEqual(len(records), 12)
        self.assertEqual([call.kwargs["params"]["symbol"] for call in session.get.call_args_list], [symbol + "USDT" for symbol in symbols])

    @patch("market_data.market_fetcher.requests.Session")
    def test_invalid_ohlc_fails(self, session_class):
        """不合理最高价不能进入行情文件。

        :param session_class: 模拟会话类
        :return: 无
        """
        self.rows[0][2] = "95"
        session_class.return_value.__enter__.return_value.get.return_value = self._response(self.rows)
        with self.assertRaises(ValueError):
            fetch_daily_market(self.config, ["BTC"], now=self.now)

    @patch("market_data.market_fetcher.requests.Session")
    def test_one_source_failure_aborts_refresh(self, session_class):
        """第二个币种失败不得返回第一个币种的部分结果。

        :param session_class: 模拟会话类
        :return: 无
        """
        session_class.return_value.__enter__.return_value.get.side_effect = [self._response(self.rows), requests.HTTPError("503")]
        with self.assertRaises(requests.HTTPError):
            fetch_daily_market(self.config, ["BTC", "ETH"], now=self.now)

    @patch("market_data.market_fetcher.requests.Session")
    def test_server_time_controls_completed_filter(self, session_class):
        """默认先请求服务器时间而非依赖本机日期判断收盘。

        :param session_class: 模拟会话类
        :return: 无
        """
        session = session_class.return_value.__enter__.return_value
        session.get.side_effect = [self._response({"serverTime": int(self.now.timestamp() * 1000)}), self._response(self.rows)]
        records = fetch_daily_market(self.config, ["BTC"])
        self.assertEqual(len(records), 2)
        self.assertTrue(session.get.call_args_list[0].args[0].endswith("/api/v3/time"))

    @patch("market_data.market_fetcher.requests.Session")
    def test_duplicate_and_nonfinite_rejected(self, session_class):
        """重复日线和非有限数值都导致整次失败。

        :param session_class: 模拟会话类
        :return: 无
        """
        session = session_class.return_value.__enter__.return_value
        session.get.return_value = self._response([self.rows[0], self.rows[0]])
        with self.assertRaises(ValueError):
            fetch_daily_market(self.config, ["BTC"], now=self.now)
        self.rows[0][5] = "NaN"
        session.get.return_value = self._response(self.rows)
        with self.assertRaises(ValueError):
            fetch_daily_market(self.config, ["BTC"], now=self.now)
